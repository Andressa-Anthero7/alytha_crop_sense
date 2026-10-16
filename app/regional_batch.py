"""Start and monitor a persisted Centro-Oeste development dataset through the local server."""
import argparse
import json
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from . import storage
from .localities import fetch_ibge, BASE

STATES = [('53','DF'),('52','GO'),('50','MS'),('51','MT')]
OUTPUT = Path(__file__).resolve().parents[1] / 'data/outputs/centro-oeste'


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,suffix='.tmp',delete=False) as stream:
        stream.write(json.dumps(data,ensure_ascii=False,indent=2))
        temporary=Path(stream.name)
    temporary.replace(path)


def api(base, path, payload=None):
    request=Request(base.rstrip('/')+path,data=json.dumps(payload).encode() if payload else None,
                    headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=45) as response:
        return json.load(response)


def backup(destination):
    if not storage.DB_PATH.is_file():return
    with closing(sqlite3.connect(storage.DB_PATH.resolve().as_uri()+'?mode=ro',uri=True)) as source:
        with closing(sqlite3.connect(destination)) as target:source.backup(target)


def start(base, output=OUTPUT):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    path=output/'manifest.json'
    if path.exists():
        manifest=json.loads(path.read_text(encoding='utf-8'))
        if len(manifest['states'])==4 and all(s.get('job_id') for s in manifest['states']):return manifest
    else:
        # Preserve the existing Sorriso base; never reset or replace the live database.
        backup(output/'baseline-before.sqlite3')
        manifest={'schema_version':1,'region':'Centro-Oeste','purpose':'Base de desenvolvimento e validação técnica',
              'created_at':now(),'base_url':base.rstrip('/'),'status':'starting','states':[],
              'note':'Cobertura municipal e consultas recentes; histórico desde 2018 somente dos recortes de referência. Pendências e dados inconclusivos não são confirmação agronômica.'}
    write(path,manifest)
    for code,uf in STATES:
        existing=next((s for s in manifest['states'] if s['code']==code),None)
        if existing and existing.get('job_id'):continue
        roster=fetch_ibge(f'/v1/localidades/estados/{code}/municipios?orderBy=nome')
        if not roster or any(not str(city['id']).startswith(code) for city in roster):
            raise ValueError('Lista municipal inesperada para '+uf)
        write(output/f'roster-{uf}.json',{'source_url':BASE+f'/v1/localidades/estados/{code}/municipios?orderBy=nome','fetched_at':now(),'municipalities':roster})
        entry=existing or {'code':code,'uf':uf,'municipalities':len(roster),'status':'pending'}
        if not existing:manifest['states'].append(entry)
        write(path,manifest)
        job=api(manifest['base_url'],'/api/regional-scans',{'kind':'state','code':code})
        entry.update(job_id=job['id'],status=job['status']);write(path,manifest)
    manifest.update(status='running',total_municipalities=sum(s['municipalities'] for s in manifest['states']))
    write(path,manifest)
    return manifest


def refresh(output=OUTPUT):
    output=Path(output);path=output/'manifest.json'
    manifest=json.loads(path.read_text(encoding='utf-8'))
    if len(manifest['states'])<4:
        manifest=start(manifest['base_url'],output)
    for entry in manifest['states']:
        try:
            if not entry.get('job_id'):
                job=api(manifest['base_url'],'/api/regional-scans',{'kind':'state','code':entry['code']})
                entry['job_id']=job['id']
            else:job=api(manifest['base_url'],'/api/regional-scans/'+entry['job_id'])
            cities=job.get('cities',[])
            entry.update(status=job['status'],processed=job.get('processed',0),total=job.get('total',0),
                         ready=sum(c['status']=='ready' for c in cities),partial=sum(c['status']=='partial' for c in cities),
                         errors=sum(c['status']=='error' for c in cities),active=[{'code':c['code'],'name':c['name'],'phase':c.get('phase')} for c in cities if c['status']=='loading'])
            entry.pop('monitor_error',None)
            write(output/f"scan-{entry['uf']}.json",job)
        except Exception:
            entry['monitor_error']='Servidor ou consulta indisponível; monitor tentará reconectar.'
    manifest['updated_at']=now()
    manifest['processed']=sum(e.get('processed',0) for e in manifest['states'])
    finished=len(manifest['states'])==4 and all(e['status'] in ('ready','partial','error') and not e.get('monitor_error') for e in manifest['states'])
    manifest['status']='finished' if finished and all(e['status']=='ready' for e in manifest['states']) else 'finished_with_pending' if finished else 'running'
    write(path,manifest)
    if finished and not manifest.get('final_snapshot'):
        backup(output/'baseline-collected.sqlite3')
        manifest['final_snapshot']=str(output/'baseline-collected.sqlite3');write(path,manifest)
    return manifest


def dashboard(manifest, database=None, roster_dir=OUTPUT):
    """Compact public progress snapshot; reads SQLite without starting any work."""
    result={'generated_at':now(),'started_at':manifest['created_at'],'total':manifest['total_municipalities'],
            'processed':0,'ready':0,'partial':0,'errors':0,'states':[],'recent':[],'municipalities':[]}
    path=Path(database or storage.DB_PATH).resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        def cached(key):
            row=db.execute('SELECT result FROM source_snapshots WHERE cache_key=?',(key,)).fetchone()
            return json.loads(row[0]) if row else None
        for entry in manifest['states']:
            job=cached('regional-scan:v1:'+entry['job_id']) or {}
            cities=job.get('cities',[])
            roster_path=Path(roster_dir)/f"roster-{entry['uf']}.json"
            roster=json.loads(roster_path.read_text(encoding='utf-8'))['municipalities'] if roster_path.is_file() else [{'id':c['code'],'nome':c['name']} for c in cities]
            lookup={c['code']:c for c in cities}
            from .collection_issues import diagnose
            for item in roster:
                city=lookup.get(str(item['id']),{})
                dossier=cached('municipality:v1:'+str(item['id'])) if city else None
                activity=cached('municipal-activity:'+city['activity']['id']) if city.get('activity',{}).get('id') else None
                history=cached('history:'+city['history']['id']) if city.get('history',{}).get('id') else None
                issues=diagnose(city,dossier,activity,history)
                years=(history or {}).get('years',[])
                expected=(history or {}).get('total',len(years))
                obtained=sum(y['status']=='ready' and y.get('observations',0)>0 for y in years)
                history_percent=round(obtained/expected*100,1) if expected else None
                learned=cached('ml:satellite:v1:'+str(item['id']))
                training={'status':'pending','areas':0,'profiles':0}
                if learned:
                    training={'status':'trained','areas':learned.get('areas',0),
                              'profiles':len(learned.get('profiles',[])),
                              'trained_at':learned.get('trained_at'),'period':learned.get('period'),
                              'collection_complete':learned.get('collection_complete',False)}
                result['municipalities'].append({'code':str(item['id']),'name':item['nome'],'uf':entry['uf'],
                    'training':training,
                    'status':city.get('status','queued'),'phase':city.get('phase'),
                    'recortes':city.get('activity',{}).get('processed',0),'recortes_total':city.get('activity',{}).get('total',0),
                    'observations':city.get('history',{}).get('observations',0),'issues':issues,
                    'history_completeness':{'percent':history_percent,'years_with_readings':obtained,'expected_years':expected}})
            state={'uf':entry['uf'],'code':entry['code'],'total':entry['municipalities'],
                   'status':job.get('status','pending'),'updated_at':job.get('updated_at'),
                   'ready':sum(c['status']=='ready' for c in cities),'partial':sum(c['status']=='partial' for c in cities),
                   'errors':sum(c['status']=='error' for c in cities),'active':[]}
            state['processed']=state['ready']+state['partial']+state['errors']
            if not cities and state['status']=='loading':state['status']='queued'
            for city in cities:
                if city['status']=='loading':
                    active={'name':city['name'],'code':city['code'],'phase':city.get('phase','dossier')}
                    for field,prefix in [('activity','municipal-activity:'),('history','history:')]:
                        child=city.get(field,{})
                        value=cached(prefix+child['id']) if child.get('id') else None
                        if value:
                            active[field]={'status':value['status'],'processed':value.get('processed',0),'total':value.get('total',0),
                                           'observations':len(value.get('points',[])),'updated_at':value.get('updated_at')}
                    if active['phase']=='dossier':
                        dossier=cached('municipality:v1:'+city['code']) or {}
                        active['progress_at']=dossier.get('updated_at',job.get('updated_at'))
                    elif active['phase']=='learning':active['progress_at']=job.get('updated_at')
                    else:
                        timestamps=[c['updated_at'] for field in ('activity','history') if (c:=active.get(field)) and c.get('updated_at')]
                        active['progress_at']=max(timestamps) if timestamps else job.get('updated_at')
                    state['active'].append(active)
                elif city['status'] in ('ready','partial','error'):
                    result['recent'].append({'name':city['name'],'code':city['code'],'uf':entry['uf'],'status':city['status'],
                        'observations':city.get('history',{}).get('observations',0),'recortes':city.get('activity',{}).get('processed',0)})
            for field in ('processed','ready','partial','errors'):result[field]+=state[field]
            result['states'].append(state)
    result['recent']=result['recent'][-20:]
    trained=[c for c in result['municipalities'] if c['training']['status']=='trained']
    result['training']={'municipalities':len(trained),'areas':sum(c['training']['areas'] for c in trained)}
    finished=all(s['status'] in ('ready','partial','error') for s in result['states'])
    result['status']='finished_with_pending' if finished and (result['partial'] or result['errors']) else 'finished' if finished else 'running'
    return result


def publish_dashboard(manifest):
    write(Path(__file__).resolve().parents[1]/'web/collection-data.json',dashboard(manifest))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['start','status','watch','dashboard'])
    parser.add_argument('--base-url',default='http://127.0.0.1:8765')
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args()
    if args.command=='start':
        result=start(args.base_url,args.output)
    elif args.command=='status':result=json.loads((args.output/'manifest.json').read_text(encoding='utf-8'))
    elif args.command=='dashboard':
        result=json.loads((args.output/'manifest.json').read_text(encoding='utf-8'))
        publish_dashboard(result)
    else:
        while True:
            try:
                result=refresh(args.output)
                publish_dashboard(result)
                print(now(),result['status'],result['processed'],flush=True)
                if result['status'] in ('finished','finished_with_pending'):break
            except Exception:print(now(),'Não foi possível atualizar; nova tentativa em 10 s.',flush=True)
            time.sleep(10)
        return
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
