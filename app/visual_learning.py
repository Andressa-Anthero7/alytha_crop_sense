"""Real satellite pixels -> dated PNG evidence -> AI -> unconfirmed features."""
import argparse
import copy
import hashlib
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from . import storage, research, spatial_raster, spatial_activity, learning_cycle

ROOT=Path(__file__).resolve().parents[1]/'data/outputs/vision'
RASTERS=Path(__file__).resolve().parents[1]/'data/rasters/visual'
POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='visual-review')
LOCK=threading.Lock()
RUNNING=set()
VERSION=1
REGISTER_BATCH_SIZE=100
EVALSCRIPT='''//VERSION=3
function setup() {
 return {input:[{bands:["B02","B03","B04","B08","SCL","dataMask"]}],
         output:{bands:5,sampleType:"FLOAT32"}};
}
function evaluatePixel(s) {
 const d=s.B08+s.B04;
 const valid=s.dataMask && d>0 && [2,4,5,7].includes(s.SCL);
 return [s.B04,s.B03,s.B02,valid?(s.B08-s.B04)/d:0,valid?1:0];
}'''
PROMPT=(
 'Analise diretamente as imagens deste mesmo recorte em períodos diferentes, '
 'junto das medições e características do ML. Descreva padrões espaciais e '
 'mudanças visíveis; pondere hipóteses alternativas e o que verificar com '
 'parceiros em campo. Respeite as máscaras de qualidade e a resolução de 10 m. '
 'Quando houver somente mapas NDVI, não alegue ter visto cor natural, textura '
 'do solo ou operações agrícolas. Separe observações visuais, hipóteses e '
 'verificações de campo. Cite os IDs das imagens. Não produza rótulos confirmados '
 'de manejo, produtividade, probabilidades de acerto ou linhas individuais de plantio.'
)


def now():return datetime.now(timezone.utc)


def schema(db):
    """Compatibility hook; storage.connect applies versioned migrations first."""


def rgb_raster(geometry,grid,period,allow_download=True):
    import numpy as np
    import rasterio
    key=research.fingerprint([geometry,grid['crs'],grid['bounds'],period,EVALSCRIPT])
    path=RASTERS/(key+'.tif')
    if not path.exists():
        if not allow_download:return None
        from .web_app import get_cdse_access_token
        from . import cdse_access
        payload={'input':{'bounds':{'bbox':grid['bounds'],'properties':{
                    'crs':'http://www.opengis.net/def/crs/EPSG/0/'+grid['crs'].split(':')[1]}},
                    'data':[{'type':'sentinel-2-l2a','dataFilter':{'timeRange':{
                        'from':period['from']+'T00:00:00Z','to':period['to']+'T23:59:59Z'},
                        'maxCloudCoverage':80,'mosaickingOrder':'leastCC'}}]},
                 'output':{'width':grid['width'],'height':grid['height'],'responses':[{
                    'identifier':'default','format':{'type':'image/tiff'}}]},'evalscript':EVALSCRIPT}
        request=Request('https://sh.dataspace.copernicus.eu/process/v1',data=json.dumps(payload).encode(),
                        headers={'Content-Type':'application/json','Accept':'image/tiff'})
        with cdse_access.RATE.open(request,urlopen,prepare=lambda r:r.add_header('Authorization','Bearer '+get_cdse_access_token())) as response:
            binary=response.read(40_000_001)
        if len(binary)>40_000_000:raise ValueError('Raster visual acima do limite de processamento.')
        RASTERS.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.tmp')
        temporary.write_bytes(binary)
        try:
            validate_raster(temporary,grid)
            temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)
    data=validate_raster(path,grid)
    rgb=np.moveaxis(data[:3],0,-1)
    valid=grid['mask'] & (data[4]>.5) & np.isfinite(data).all(axis=0) & (data[3]>=-1) & (data[3]<=1)
    return {'rgb':rgb,'ndvi':data[3],'valid':valid,'source_path':str(path)}


def validate_raster(path,grid):
    import rasterio
    with rasterio.open(path) as ds:
        if (ds.count!=5 or ds.width!=grid['width'] or ds.height!=grid['height'] or
            ds.crs!=rasterio.crs.CRS.from_string(grid['crs']) or not ds.transform.almost_equals(grid['transform'])):
            raise ValueError('Raster visual incompatível com a geometria e a grade solicitadas.')
        return ds.read()


def render(geometry,grid,period,kind,values,valid,source_path):
    import numpy as np
    from PIL import Image,ImageDraw
    area_key=research.fingerprint(geometry)
    folder=ROOT/'assets';folder.mkdir(parents=True,exist_ok=True)
    rgb=np.full((*valid.shape,3),128,dtype=np.uint8)
    if kind=='true_color':
        # Same fixed reflectance stretch on every date: no per-image equalization.
        rgb[valid]=np.round(np.clip(values[valid]*2.5,0,1)*255).astype(np.uint8)
        note='Cor natural B04/B03/B02. Ganho fixo 2,5; cinza sem observação. Não revela linhas individuais de plantio em 10 m.'
    else:
        # Fixed physical NDVI scale [-1, 1], not an invented crop illustration.
        stops=np.array([[120,75,50],[220,165,60],[240,220,100],[110,165,65],[15,95,45]],dtype=float)
        t=np.clip((np.nan_to_num(values,nan=0,posinf=1,neginf=-1)+1)*2,0,4)
        lo=np.floor(t).astype(int);hi=np.minimum(lo+1,4);weight=(t-lo)[...,None]
        colors=stops[lo]*(1-weight)+stops[hi]*weight
        rgb[valid]=np.round(colors[valid]).astype(np.uint8)
        note='Mapa NDVI com escala fixa -1 a 1; marrom/amarelo baixo, verde alto, cinza sem observação. Não é fotografia de cor natural.'
    image=Image.fromarray(rgb)
    scale=min(1024/max(image.size),max(1,360/image.width))
    image=image.resize((max(1,round(image.width*scale)),max(1,round(image.height*scale))),Image.Resampling.NEAREST)
    canvas=Image.new('RGB',(max(360,image.width),image.height+54),(245,245,240))
    canvas.paste(image,(0,54));draw=ImageDraw.Draw(canvas)
    draw.text((5,4),f'{kind} | {period["from"]} - {period["to"]}',fill=(0,0,0))
    draw.text((5,22),'gray = no observation | native pixel: 10 m',fill=(0,0,0))
    if kind=='ndvi':draw.text((5,38),'NDVI: brown -1 / yellow 0 / green +1',fill=(0,0,0))
    stream=io.BytesIO();canvas.save(stream,format='PNG');binary=stream.getvalue()
    content_hash=hashlib.sha256(binary).hexdigest()
    identifier=research.fingerprint([area_key,period,kind,VERSION,content_hash])
    path=folder/(identifier+'.png')
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=content_hash:
        temporary=path.with_suffix('.tmp');temporary.write_bytes(binary);temporary.replace(path)
    valid_pixels=int(np.count_nonzero(valid));area_pixels=int(np.count_nonzero(grid['mask']))
    metadata={'id':identifier,'evidence_id':'image_'+identifier[:20],'area_key':area_key,
              'kind':kind,'period':period,'path':str(path.resolve()),'mime_type':'image/png',
              'sha256':content_hash,'source':'Copernicus Sentinel-2 L2A',
              'source_path':source_path,'source_resolution_m':10,'crs':grid['crs'],'bounds':grid['bounds'],
              'native_size':[grid['width'],grid['height']],'preview_size':list(image.size),
              'raster_region_px':{'x':0,'y':54,'width':image.width,'height':image.height},
              'valid_pixels':valid_pixels,'valid_fraction':valid_pixels/area_pixels if area_pixels else 0,
              'note':note,'render_version':VERSION}
    with storage.connect() as db:
        schema(db);db.execute('INSERT OR REPLACE INTO visual_assets VALUES(?,?,?)',(identifier,area_key,json.dumps(metadata)))
    (folder/(identifier+'.json')).write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    return metadata


def periods_for(history,cutoff):
    area_key=research.fingerprint(history['parameters']['geometry'])
    # Prefer already acquired, georegistered composites when still recent.
    with storage.connect() as db:
        rows=db.execute("SELECT result FROM source_snapshots WHERE cache_key LIKE 'cv:job:%' "
                        "AND json_extract(result,'$.parameters.area_id')=?",(area_key,)).fetchall()
    candidates=[]
    for row in rows:
        job=json.loads(row['result']);periods=job.get('periods',[])
        if (len(periods)==3 and all(p['to']<=cutoff for p in periods) and
            0<=(date.fromisoformat(cutoff)-date.fromisoformat(periods[-1]['to'])).days<=20):
            candidates.append(periods)
    return max(candidates,key=lambda p:p[-1]['to']) if candidates else spatial_activity.select_periods(history['points'],cutoff)


def prepare(dataset_id,cutoff=None,allow_download=True):
    history=research.dataset(dataset_id);params=history['parameters']
    cutoff=cutoff or params['as_of']
    if not date(2018,1,1)<=date.fromisoformat(cutoff)<=min(date.fromisoformat(params['as_of']),now().date()):
        raise ValueError('Data visual fora do histórico disponível.')
    geometry=params['geometry'];area_key=research.fingerprint(geometry)
    result={'dataset_id':dataset_id,'area_key':area_key,'municipality_code':params.get('municipality_code','5107925'),
            'cutoff':cutoff,'assets':[],'issues':[],'geometry':geometry,'status':'waiting_images'}
    try:periods=periods_for(history,cutoff)
    except ValueError as exc:result['issues'].append({'message':str(exc)});return result
    grid=spatial_raster.grid_for(geometry)
    gate=storage.source_snapshot('learning:collection-gate')
    can_download=allow_download and not (gate and gate['result'].get('until','')>now().isoformat())
    for period in periods:
        multispectral=None
        try:multispectral=rgb_raster(geometry,grid,period,can_download)
        except Exception as exc:
            issue=learning_cycle.collection_failure(exc);result['issues'].append(issue)
            if issue['reason']=='processing_quota':
                can_download=False
                storage.source_snapshot('learning:collection-gate',{'until':(now()+timedelta(hours=6)).isoformat(),'issue':issue})
        if multispectral:
            images=[('true_color',multispectral['rgb']),('ndvi',multispectral['ndvi'])]
            valid=multispectral['valid'];source_path=multispectral['source_path']
        else:
            # Existing numerical rasters are real spatial images, not NDVI charts.
            path=spatial_raster.cache_path(geometry,grid,period)
            if not path.is_file():continue
            values,valid=spatial_raster.read_raster(path,grid)
            images=[('ndvi',values)];source_path=str(path)
        import numpy as np
        coverage=np.count_nonzero(valid)/max(1,np.count_nonzero(grid['mask']))
        if np.count_nonzero(valid)<50 or coverage<.5:
            result['issues'].append({'message':'Imagem excluída por cobertura válida insuficiente.','period':period});continue
        for kind,values in images:result['assets'].append(render(geometry,grid,period,kind,values,valid,source_path))
    result['periods']=periods
    result['image_kinds']=sorted({a['kind'] for a in result['assets']})
    result['missing_true_color']='true_color' not in result['image_kinds']
    if result['assets']:result['status']='ready'
    if gate and not can_download:result['issues'].append(gate['result']['issue'])
    return result


def review(prepared,analysis=None):
    if prepared['status']!='ready' or not prepared['assets']:
        return {**prepared,'status':'waiting_images','analysis_mode':'not_analyzed','training_target':None}
    from . import assistant
    from .web_app import read_app_env
    history=research.dataset(prepared['dataset_id'])
    analysis=analysis or research.analyze(history['id'],prepared['cutoff'])
    evidence=[{'id':'temporal_measurements','source':'Sentinel-2 · medições do mesmo recorte',
               'data':analysis,'recent_points':research.windows(history['points'],prepared['cutoff'])[-24:]},
              {'id':'image_quality','source':'CropSense · preparação visual',
               'missing_true_color':prepared['missing_true_color'],'issues':prepared['issues']}]
    field_records=[r for r in research.events() if r['area_key']==prepared['area_key']
                   and r['date_to']<=prepared['cutoff'] and r['created_at'][:10]<=prepared['cutoff']]
    if field_records:
        evidence.append({'id':'field_observations','source':'Registros humanos de campo',
                         'records':[{k:r[k] for k in ('id','date_from','date_to','stage','note')} for r in field_records[:30]]})
    for asset in prepared['assets']:
        evidence.append({'id':asset['evidence_id'],'source':asset['source'],
                         'data':{k:asset[k] for k in ('kind','period','sha256','valid_fraction','valid_pixels','source_resolution_m','note')}})
    grounded={'evidence':evidence,'map':{'municipality_code':prepared['municipality_code'],
               'scope':'somente o recorte mostrado nas imagens'},'note':'Hipóteses visuais não são rótulos de campo.'}
    response=assistant.review_context(PROMPT,grounded,read_app_env(),images=prepared['assets'])
    features={feature:None for feature in assistant.VISUAL_FEATURES}
    for observation in response['visual_observations']:
        value={'present':1,'absent':0,'uncertain':None}[observation['presence']]
        key=observation['feature']
        if features[key] is None or value==1:features[key]=value
    return {**prepared,'status':'ready','analysis_mode':'visual','review':response,'reviewed_at':now().isoformat(),
            'visual_features':features,'feature_origin':response['provider'].lower()+'_visual_interpretation',
            'field_feedback_signature':research.fingerprint(field_records),
            'field_informed':bool(field_records),'model_informed':bool(analysis.get('model_prediction')),
            'eligible_as_training_input':not bool(field_records) and not bool(analysis.get('model_prediction')),
            'training_target':None,'note':'Características interpretadas pela IA para investigação. Não são manejo confirmado nem alvos supervisionados.'}


def register_base():
    latest=storage.source_snapshot('regional-learning:latest')
    if not latest:return None
    base_id=latest['result']['id']
    registered=storage.source_snapshot('visual-learning:registered')
    if registered and registered['result']['base_id']==base_id:return base_id
    codes={c['code'] for c in latest['result']['municipalities']}
    with learning_cycle.database() as db:
        cached={json.loads(r['result'])['parameters']['area_id'] for r in db.execute(
            "SELECT result FROM source_snapshots WHERE cache_key LIKE 'cv:job:%' AND json_extract(result,'$.status') IN ('ready','inconclusive')")}
        cached.update(r['area_key'] for r in db.execute('SELECT DISTINCT area_key FROM visual_assets'))
        rows=db.execute('SELECT config FROM learning_plans').fetchall()
        field_records=[dict(r) for r in db.execute('SELECT * FROM field_events ORDER BY id DESC')]
        existing_ids={r['id'] for r in db.execute('SELECT id FROM visual_jobs WHERE base_id=?',(base_id,))}
    records_by_area={}
    for record in field_records:records_by_area.setdefault(record['area_key'],[]).append(record)
    # Prepare each batch without holding a write transaction. Inserts are short
    # and idempotent, so an interrupted registration can resume safely.
    for offset in range(0,len(rows),REGISTER_BATCH_SIZE):
        batch=[]
        with storage.connect() as db:
            for row in rows[offset:offset+REGISTER_BATCH_SIZE]:
                plan=json.loads(row['config'])
                if plan['municipality_code'] not in codes:continue
                data=db.execute('SELECT result FROM source_snapshots WHERE cache_key=?',('history:'+plan['latest_dataset_id'],)).fetchone()
                if not data:continue
                history=json.loads(data['result']);cutoff=min(history['parameters']['as_of'],latest['result']['created_at'][:10])
                identifier=research.fingerprint([base_id,plan['area_key'],plan['latest_dataset_id'],cutoff,VERSION])
                if identifier in existing_ids:continue
                priority=0 if plan['area_key'] in cached else 1
                records=[r for r in records_by_area.get(plan['area_key'],[]) if r['date_to']<=cutoff and r['created_at'][:10]<=cutoff]
                feedback_signature=research.fingerprint(records)
                previous=db.execute("SELECT id,result FROM visual_jobs WHERE area_key=? AND dataset_id=? AND cutoff=? AND status='ready' ORDER BY rowid DESC LIMIT 1",
                                    (plan['area_key'],plan['latest_dataset_id'],cutoff)).fetchone()
                reused=json.loads(previous['result']) if previous else None
                if reused and reused.get('field_feedback_signature')!=feedback_signature:reused=None
                status='ready' if reused else 'pending' if priority==0 else 'waiting_images'
                result={**reused,'reused_from':previous['id']} if reused else {'note':'Aguardando imagens reais deste recorte.'}
                batch.append((identifier,base_id,plan['area_key'],plan['municipality_code'],plan['latest_dataset_id'],cutoff,
                              status,priority,now().isoformat(),json.dumps(result)))
        if batch:
            with storage.connect() as db:
                db.executemany('INSERT OR IGNORE INTO visual_jobs(id,base_id,area_key,municipality_code,dataset_id,cutoff,status,priority,next_attempt,result) VALUES(?,?,?,?,?,?,?,?,?,?)',batch)
    storage.source_snapshot('visual-learning:registered',{'base_id':base_id})
    return base_id


def get(job_id):
    with storage.connect() as db:
        schema(db);row=db.execute('SELECT * FROM visual_jobs WHERE id=?',(job_id,)).fetchone()
    if not row:raise ValueError('Análise visual não encontrada.')
    return {'id':row['id'],'dataset_id':row['dataset_id'],'municipality_code':row['municipality_code'],
            'area_key':row['area_key'],**json.loads(row['result']),'status':row['status']}


def execute(job):
    identifier=job['id']
    prepared=None
    try:
        prepared=prepare(job['dataset_id'],job['cutoff'])
        result=review(prepared);status=result['status']
        next_attempt=(now()+timedelta(hours=6)).isoformat()
    except Exception as exc:
        result={**(prepared or {}),'analysis_mode':'not_analyzed','issue':learning_cycle.ai_failure(exc),'training_target':None}
        if getattr(exc,'visual_request',None):result['image_request']=exc.visual_request
        status='retry';next_attempt=(now()+timedelta(minutes=30)).isoformat()
        config=storage.source_snapshot('regional-learning:config')
        if config:
            settings=config['result'];settings['backoff_until']=next_attempt
            storage.source_snapshot('regional-learning:config',settings)
    folder=ROOT/'reviews';folder.mkdir(parents=True,exist_ok=True)
    (folder/(identifier+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    with storage.connect() as db:
        schema(db);db.execute('UPDATE visual_jobs SET status=?,next_attempt=?,lease_until=NULL,result=? WHERE id=?',
                            (status,next_attempt,json.dumps(result),identifier))
    return get(identifier)


def review_next():
    base_id=register_base()
    config=storage.source_snapshot('regional-learning:config')
    if not base_id or not config or not config['result'].get('ai_enabled'):return None
    if config['result'].get('backoff_until','')>now().isoformat():return None
    gate=storage.source_snapshot('learning:collection-gate')
    blocked=bool(gate and gate['result'].get('until','')>now().isoformat())
    with storage.connect() as db:
        schema(db);db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM visual_jobs WHERE base_id=? AND (priority=0 OR ?=0) AND "
                       "((status IN ('pending','waiting_images','retry') AND next_attempt<=?) OR (status='running' AND lease_until<=?)) "
                       "ORDER BY priority,municipality_code,id LIMIT 1",(base_id,int(blocked),now().isoformat(),now().isoformat())).fetchone()
        if not row:return None
        db.execute("UPDATE visual_jobs SET status='running',attempts=attempts+1,lease_until=? WHERE id=?",
                   ((now()+timedelta(minutes=15)).isoformat(),row['id']))
    return execute(dict(row))


def start(data):
    history=research.dataset(data.get('dataset_id'));cutoff=data.get('date') or history['parameters']['as_of']
    if not isinstance(cutoff,str):raise ValueError('Data visual inválida.')
    if not date(2018,1,1)<=date.fromisoformat(cutoff)<=min(date.fromisoformat(history['parameters']['as_of']),now().date()):
        raise ValueError('Data visual fora do histórico disponível.')
    identifier=research.fingerprint(['explicit-visual',history['id'],cutoff,VERSION])
    with LOCK:
        with storage.connect() as db:
            schema(db)
            existing=db.execute('SELECT id FROM visual_jobs WHERE dataset_id=? AND cutoff=? ORDER BY (status=\'ready\') DESC,rowid DESC LIMIT 1',
                                (history['id'],cutoff)).fetchone()
            if existing:identifier=existing['id']
            db.execute('INSERT OR IGNORE INTO visual_jobs(id,area_key,municipality_code,dataset_id,cutoff,status,priority,next_attempt,result) VALUES(?,?,?,?,?,?,?,?,?)',
                (identifier,research.fingerprint(history['parameters']['geometry']),history['parameters'].get('municipality_code','5107925'),
                 history['id'],cutoff,'pending',0,now().isoformat(),'{}'))
            row=db.execute('SELECT * FROM visual_jobs WHERE id=?',(identifier,)).fetchone()
            cached=(row['status']=='ready' or identifier in RUNNING or
                    (row['status']=='running' and row['lease_until'] and row['lease_until']>now().isoformat()) or
                    (row['status']=='retry' and row['next_attempt']>now().isoformat()))
            if not cached:db.execute("UPDATE visual_jobs SET status='running',lease_until=? WHERE id=?",((now()+timedelta(minutes=15)).isoformat(),identifier))
        if cached:return get(identifier)
        RUNNING.add(identifier)
        def work():
            try:execute(dict(row))
            finally:
                with LOCK:RUNNING.discard(identifier)
        POOL.submit(work)
    return get(identifier)


def status_snapshot():
    latest=storage.source_snapshot('regional-learning:latest')
    with storage.connect() as db:
        schema(db)
        base_id=latest['result']['id'] if latest else ''
        counts={r['status']:r['n'] for r in db.execute('SELECT status,count(*) AS n FROM visual_jobs WHERE base_id=? GROUP BY status',(base_id,))}
        assets=db.execute('SELECT count(DISTINCT sha) FROM (SELECT json_extract(result,\'$.sha256\') AS sha FROM visual_assets)').fetchone()[0]
        latest_rows=db.execute("SELECT id,status,municipality_code,result FROM visual_jobs WHERE status IN ('ready','retry','running') ORDER BY rowid DESC LIMIT 5").fetchall()
    return {'queue':counts,'assets':assets,'recent':[{'id':r['id'],'status':r['status'],
        'municipality_code':r['municipality_code'],'analysis_mode':json.loads(r['result']).get('analysis_mode'),
        'issue':json.loads(r['result']).get('issue')} for r in latest_rows]}


def feature_rows(db=None):
    if db is None:
        with storage.connect() as connection:return feature_rows(connection)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='visual_jobs'").fetchone():return []
    labels=[dict(r) for r in db.execute('SELECT * FROM field_events')]
    selected={}
    for row in db.execute("SELECT * FROM visual_jobs WHERE status='ready' ORDER BY rowid"):
        value=json.loads(row['result'])
        if value.get('analysis_mode')!='visual' or not value.get('visual_features'):continue
        matched=[r for r in labels if r['area_key']==row['area_key'] and r['date_from']<=row['cutoff']<=r['date_to']]
        label=matched[0] if len(matched)==1 else None
        key=(row['area_key'],row['cutoff'])
        if key in selected and selected[key]['eligible_as_training_input'] and not value.get('eligible_as_training_input',False):
            continue
        selected[key]={'area_key':row['area_key'],
            'municipality_code':row['municipality_code'],'as_of':row['cutoff'],'visual_job_id':row['id'],
            'feature_origin':value.get('feature_origin',value['review']['provider'].lower()+'_visual_interpretation'),
            'image_hashes':json.dumps([a['sha256'] for a in value['assets']]),
            'available_at':value['reviewed_at'],'provider':value['review']['provider'],'model':value['review']['model'],
            'field_informed':value.get('field_informed',False),'eligible_as_training_input':value.get('eligible_as_training_input',False),
            **value['visual_features'],'target_stage':label['stage'] if label else '',
            'label_source':'registro_de_campo' if label else ''}
    return list(selected.values())


def record_review(result):
    """Keep a per-area cycle's completed visual result in the shared ML corpus."""
    identifier=research.fingerprint(['cycle-visual',result['dataset_id'],result['cutoff'],
        [a['sha256'] for a in result['assets']],result['review']['model'],VERSION])
    with storage.connect() as db:
        schema(db)
        db.execute('INSERT OR IGNORE INTO visual_jobs(id,area_key,municipality_code,dataset_id,cutoff,status,priority,next_attempt,result) VALUES(?,?,?,?,?,?,?,?,?)',
            (identifier,result['area_key'],result['municipality_code'],result['dataset_id'],result['cutoff'],
             'ready',0,now().isoformat(),json.dumps(result)))
    return identifier


def evidence(area_key,cutoff):
    with storage.connect() as db:
        schema(db)
        row=db.execute("SELECT id,result FROM visual_jobs WHERE area_key=? AND cutoff<=? AND status='ready' "
                       "AND json_extract(result,'$.reviewed_at')<=? ORDER BY cutoff DESC,rowid DESC LIMIT 1",
                       (area_key,cutoff,cutoff+'T23:59:59+00:00')).fetchone()
    if not row:return None
    value=json.loads(row['result'])
    return {'id':value.get('feature_origin',value['review']['provider'].lower()+'_visual_interpretation'),
            'source':value['review']['provider']+' · interpretação de imagens reais',
            'provider':value['review']['provider'],'model':value['review']['model'],
            'visual_job_id':row['id'],'kind':'unconfirmed_visual_interpretation',
            'images':[{k:a[k] for k in ('evidence_id','kind','period','sha256','valid_fraction')} for a in value['assets']],
            'observations':value['review']['visual_observations'],'hypotheses':value['review']['hypotheses'],
            'field_checks':value['review']['field_checks'],
            'note':'Interpretação visual anterior para continuidade. Não é confirmação de manejo nem rótulo de treinamento.'}


def asset(identifier):
    with storage.connect() as db:
        schema(db);row=db.execute('SELECT result FROM visual_assets WHERE id=?',(identifier,)).fetchone()
    if not row:raise ValueError('Imagem visual não encontrada.')
    metadata=json.loads(row['result']);path=Path(metadata['path']).resolve()
    if not path.is_relative_to(ROOT.resolve()):raise ValueError('Imagem fora do armazenamento visual.')
    return metadata,path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['register','status','review-next','pilot'])
    args=parser.parse_args()
    if args.command=='register':result={'base_id':register_base(),**status_snapshot()}
    elif args.command=='review-next':result=review_next()
    elif args.command=='pilot':
        reference=storage.source_snapshot('research:sorriso:pilot')['result']
        result=review(prepare(reference['dataset_id']))
    else:result=status_snapshot()
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
