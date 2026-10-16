"""Persistent regional acquisition: official sources, bounded workers, resumable cities."""
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from . import storage, municipalities, municipal_activity, research, inactive_soy
from .localities import fetch_ibge

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='regional-scan')
LOCK = threading.Lock()
RUNNING = set()
STOP = threading.Event()
MAX_PENDING = 4


def key(job_id):
    if not isinstance(job_id,str) or not re.fullmatch(r'[a-f0-9]{64}',job_id):
        raise ValueError('Varredura regional inválida.')
    return 'regional-scan:v1:'+job_id


def parameters(data):
    if not isinstance(data,dict): raise ValueError('Informe uma região.')
    kind,code = data.get('kind'),data.get('code')
    if kind not in ('state','municipality') or not isinstance(code,str) or not re.fullmatch(r'[0-9]{2}' if kind=='state' else r'[0-9]{7}',code):
        raise ValueError('Informe estado ou município com código IBGE válido.')
    return {'kind':kind,'code':code,'as_of':inactive_soy.today().isoformat(),'start_year':2018,'version':1}


def persist(job):
    job['updated_at']=storage.now()
    cities=job.get('cities',[])
    job['total']=len(cities)
    job['processed']=sum(c['status'] in ('ready','partial','error') for c in cities)
    storage.source_snapshot(key(job['id']),job)


def schedule(job):
    if len(RUNNING)>=MAX_PENDING: raise ValueError('Há varreduras em andamento. Aguarde e tente novamente.')
    job['status']='loading';persist(job);RUNNING.add(job['id'])
    try: POOL.submit(build,job['id'])
    except Exception:
        RUNNING.discard(job['id']);job.update(status='error',error='Não foi possível iniciar a varredura. Tente novamente.');persist(job)
        raise ValueError(job['error']) from None
    return job


def start(data):
    params=parameters(data);job_id=research.fingerprint(params)
    with LOCK:
        saved=storage.source_snapshot(key(job_id))
        if job_id in RUNNING or (saved and saved['result']['status']=='ready'): return saved['result']
        job=saved['result'] if saved else {'id':job_id,'parameters':params,'phase':'localities','cities':[],
            'note':'Dossiês e atividade recente por município; histórico desde 2018 de um recorte de referência por cidade, sem extrapolação municipal.'}
        # Retry only incomplete cities; ready results remain available.
        for city in job['cities']:
            if city['status'] in ('partial','error'): city['status']='queued'
        job.pop('error',None)
        return schedule(job)


def get(job_id):
    with LOCK:
        saved=storage.source_snapshot(key(job_id))
        if not saved: raise ValueError('Varredura não encontrada.')
        job=saved['result']
        if job['status']=='loading' and job_id not in RUNNING: return schedule(job)
        return job


def wait_for(read):
    while True:
        if STOP.is_set(): raise InterruptedError('Servidor encerrando.')
        result=read()
        if result['status'] not in ('queued','loading'): return result
        STOP.wait(2)


def collect_city(city,job):
    city.pop('error',None)
    city['status']='loading';city['phase']='dossier';persist(job)
    municipalities.request(city['code'])
    dossier=wait_for(lambda: storage.source_snapshot(municipalities.key(city['code']))['result'])
    city['dossier']={'status':dossier['status'],'sources':dossier.get('sources',{})}
    city['name']=dossier.get('name',city['name']);city['uf']=dossier.get('uf',city['code'][:2]);persist(job)
    if not dossier.get('boundary'):
        city.update(status='error',error='Limite municipal indisponível; nenhuma área foi analisada.');return
    from .web_app import read_app_env
    env=read_app_env()
    if not all(env.get(k) for k in ('CDSE_CLIENT_ID','CDSE_CLIENT_SECRET')):
        city.update(status='partial',activity={'status':'unavailable','note':'Configure Copernicus para coletar imagens.'},history={'status':'unavailable'});return
    city['phase']='satellite';persist(job)
    activity=municipal_activity.start({'municipality_code':city['code']})
    city['activity']={'id':activity['id'],'status':activity['status'],'as_of':activity['parameters']['as_of']};persist(job)
    # Mapping supplies the same cached geometries used by the full-city recent series.
    def mapped():
        value=municipal_activity.get(activity['id'])
        city['activity'].update(status=value['status'],processed=value.get('processed',0),total=value.get('total',0),failure_count=value.get('failure_count',0))
        if value.get('error'):city['activity']['note']=value['error']
        persist(job)
        return {'status':'ready' if value.get('phase')!='mapping' or value['status']=='error' else 'loading'}
    wait_for(mapped)
    candidates=storage.source_snapshot('municipal-soy:v1:'+city['code'])
    history=None
    if candidates and candidates['result']['features']:
        reference=min(candidates['result']['features'],key=lambda f:f['properties']['area_ha'])
        try:
            history=research.start_history({'municipality_code':city['code'],'geojson':reference,'start_year':job['parameters']['start_year']})
            city['history']={'id':history['id'],'status':history['status'],'scope':'reference','as_of':history['parameters']['as_of'],'area_ha':reference['properties']['area_ha'],'source':reference['properties']}
        except Exception:
            city['history']={'status':'error','note':'Não foi possível iniciar o histórico do recorte de referência.'}
    else:
        empty=candidates and candidates['result'].get('total_soy_ha')==0
        city['history']={'status':'not_applicable' if empty else 'unavailable','note':'Sem recorte de soja histórica disponível para referência.'}
    persist(job)
    def progress():
        value=municipal_activity.get(activity['id'])
        city['activity'].update(status=value['status'],processed=value.get('processed',0),total=value.get('total',0),failure_count=value.get('failure_count',0))
        if value.get('error'):city['activity']['note']=value['error']
        if history:
            h=research.restore_history(history['id'])
            city['history'].update(status=h['status'],processed=h.get('processed',0),total=h.get('total',0),observations=len(h.get('points',[])))
        persist(job)
        pending=city['activity']['status']=='loading' or city['history']['status']=='loading'
        return {'status':'loading' if pending else 'ready'}
    wait_for(progress)
    if city['activity']['status']=='ready':
        from . import satellite_learning
        city['phase']='learning';persist(job)
        try:
            learned=satellite_learning.status(city['code'])
            if not learned or learned['period']['to']!=city['activity']['as_of'] or not learned['collection_complete']:
                learned=satellite_learning.train(city['code'])
            city['learning']={'status':'ready','areas':learned['areas'],'profiles':len(learned['profiles']),'period':learned['period'],'collection_complete':learned['collection_complete']}
        except ValueError:
            city['learning']={'status':'insufficient','note':'Ainda não há leituras suficientes ou diversidade para aprender perfis.'}
        except Exception:
            city['learning']={'status':'error','note':'Não foi possível aprender perfis; as observações permanecem disponíveis.'}
    city['status']='ready' if dossier['status']=='ready' and city['activity']['status']=='ready' and not city['activity'].get('failure_count') and city['history']['status'] in ('ready','not_applicable') else 'partial'
    city['phase']='complete'


def build(job_id):
    job=storage.source_snapshot(key(job_id))['result']
    try:
        params=job['parameters']
        if not job['cities']:
            if params['kind']=='state':
                cities=fetch_ibge(f"/v1/localidades/estados/{params['code']}/municipios?orderBy=nome")
            else: cities=[fetch_ibge('/v1/localidades/municipios/'+params['code'])]
            if not cities or any(not re.fullmatch(r'[0-9]{7}',str(c.get('id',''))) or (params['kind']=='state' and not str(c['id']).startswith(params['code'])) for c in cities):
                raise ValueError('Região não encontrada no IBGE.')
            job['cities']=[{'code':str(c['id']),'name':c['nome'],'status':'queued'} for c in cities]
        job['phase']='collecting';persist(job)
        for city in job['cities']:
            if STOP.is_set(): raise InterruptedError('Servidor encerrando.')
            if city['status'] in ('ready','partial','error'): continue
            try: collect_city(city,job)
            except InterruptedError: raise
            except Exception: city.update(status='error',error='Falha na coleta desta cidade. As demais continuam disponíveis.')
            persist(job)
        job['status']='ready' if all(c['status']=='ready' for c in job['cities']) else 'partial'
        job['phase']='complete';persist(job)
    except InterruptedError:
        job.update(status='loading',phase='interrupted');persist(job)
    except Exception:
        job.update(status='error',error='Não foi possível preparar a região. Verifique a conexão e o código IBGE.');persist(job)
    finally:
        with LOCK: RUNNING.discard(job_id)
