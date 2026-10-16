"""Persistent municipality dossiers, assembled on demand by server workers."""
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from . import storage, data_sources
from .localities import fetch_ibge, BASE

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='municipality')
LOCK = threading.Lock()
RUNNING = set()

def key(code):
    if not isinstance(code,str) or not re.fullmatch(r'[0-9]{7}',code):
        raise ValueError('Código municipal IBGE inválido.')
    return 'municipality:v1:' + code

def request(code):
    cache_key = key(code)
    with LOCK:
        snapshot = storage.source_snapshot(cache_key)
        recent = snapshot and datetime.now(timezone.utc)-datetime.fromisoformat(snapshot['fetched_at']) < timedelta(days=1)
        if code not in RUNNING and (not recent or snapshot['result']['status'] in ('queued','loading','partial','error')):
            RUNNING.add(code)
            queued=dict(snapshot['result']) if snapshot else {'code':code,'sources':{}}
            queued.update(status='queued',updated_at=storage.now())
            storage.source_snapshot(cache_key,queued)
            try: POOL.submit(build,code)
            except Exception:
                RUNNING.discard(code)
                queued.update(status='error',error='Não foi possível iniciar a base municipal. Tente novamente.')
                storage.source_snapshot(cache_key,queued)
                raise ValueError(queued['error']) from None
    return storage.source_snapshot(cache_key)['result']

def build(code):
    dossier={'code':code,'status':'loading','sources':{},'updated_at':storage.now()}
    def persist():
        dossier['updated_at']=storage.now(); storage.source_snapshot(key(code),dossier)
    try:
        persist()
        city=fetch_ibge('/v1/localidades/municipios/'+code)
        uf=next(item['sigla'] for item in fetch_ibge('/v1/localidades/estados?orderBy=nome') if str(item['id'])==code[:2])
        path=f'/v3/malhas/municipios/{code}?formato=application/vnd.geo%2Bjson&qualidade=minima'
        boundary=fetch_ibge(path)
        dossier.update(name=city['nome'],uf=uf,boundary=boundary)
        dossier['sources']['ibge']={'status':'ready','scope':'municipality','source_url':BASE+path,'fetched_at':storage.now(),'note':'Malha simplificada IBGE; limite administrativo.'}
        persist()
        try:
            dossier['conab']={crop:data_sources.conab(uf,crop) for crop in ('SOJA','MILHO','SORGO')}
            dossier['sources']['conab']={'status':'ready','scope':'UF','note':'Contexto estadual; não representa produção municipal.'}
        except Exception as exc:
            from .collection_issues import failure
            dossier['sources']['conab']={'status':'error','note':'Fonte indisponível. Nova seleção tentará novamente.','issue':failure('CONAB','base municipal',exc)}
        dossier['sources']['satveg']={'status':'pending','note':'Consulta depende de token e período. Não incluída automaticamente.'}
        dossier['sources']['mapbiomas']={'status':'loading','year':2025,'resolution_m':30}
        persist()
        try:
            dossier['mapbiomas']=data_sources.municipal_landcover(boundary)
            dossier['sources']['mapbiomas']={'status':'ready','year':2025,'resolution_m':30,'scope':'municipality','source_url':data_sources.MAPBIOMAS_PAGE}
        except Exception as exc:
            from .collection_issues import failure
            dossier['sources']['mapbiomas']={'status':'error','note':'Resumo indisponível. Verifique dependências geoespaciais/conexão; nova seleção tentará novamente.','issue':failure('MapBiomas','resumo municipal',exc)}
        dossier['status']='partial' if any(s['status']=='error' for s in dossier['sources'].values()) else 'ready'
        persist()
    except Exception as exc:
        from .collection_issues import failure
        dossier['status']='error'; dossier['issue']=failure('IBGE','limite municipal',exc);dossier['error']='Não foi possível obter o município no IBGE. Tente novamente.'; persist()
    finally:
        with LOCK: RUNNING.discard(code)

def boundary(code):
    saved=storage.source_snapshot(key(code))
    if not saved or not saved['result'].get('boundary'):
        raise ValueError('Aguarde o preparo da base municipal.')
    return saved['result']['boundary']
