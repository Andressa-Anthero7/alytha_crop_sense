"""Load historical crop maps without holding browser connections open."""
import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from . import data_sources, storage

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='crop-map')
LOCK = threading.Lock()
RUNNING = set()
FUTURES = {}
LATEST = {}
MAX_PENDING = 8


def start(data):
    params = data_sources.mapbiomas_parameters(data)
    owner=data.get('request_owner')
    if owner is not None and (not isinstance(owner,str) or not re.fullmatch(r'[a-f0-9-]{16,64}',owner)):
        raise ValueError('Identificação da consulta inválida.')
    job_id = hashlib.sha256(json.dumps([params,5], sort_keys=True).encode()).hexdigest()
    with LOCK:
        if owner:
            slot=(owner,params['class_id'])
            previous=LATEST.get(slot)
            if previous and previous!=job_id:_supersede(previous)
            LATEST[slot]=job_id
        saved = storage.source_snapshot('crop-map:v1:' + job_id)
        if job_id in RUNNING or (saved and saved['result']['status'] == 'ready'):
            return saved['result']
        cached=data_sources.cached_mapbiomas(params)
        if cached:
            job={'id':job_id,'status':'ready','phase':'cached','parameters':params,'result':cached}
            storage.source_snapshot('crop-map:v1:'+job_id,job)
            return job
        return _schedule(job_id, params,owner)


def get(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{64}', job_id):
        raise ValueError('Consulta de culturas inválida.')
    with LOCK:
        saved = storage.source_snapshot('crop-map:v1:' + job_id)
        if not saved: raise ValueError('Consulta de culturas não encontrada. Envie o pedido novamente.')
        job = saved['result']
        # A server restart should resume pending work, not poll forever.
        if job['status'] == 'loading' and job_id not in RUNNING:
            owner=job.get('request_owner')
            if owner and LATEST.get((owner,job['parameters']['class_id']),job_id)!=job_id:
                _supersede(job_id);return storage.source_snapshot('crop-map:v1:'+job_id)['result']
            return _schedule(job_id, job['parameters'],owner)
        return job


def _supersede(job_id):
    future=FUTURES.get(job_id)
    if future and not future.cancel():return False
    saved=storage.source_snapshot('crop-map:v1:'+job_id)
    if saved and saved['result']['status']=='loading':
        job=saved['result'];job.update(status='superseded',phase='superseded',error='Esta consulta foi substituída por uma solicitação mais recente.')
        storage.source_snapshot('crop-map:v1:'+job_id,job)
    RUNNING.discard(job_id);FUTURES.pop(job_id,None)
    return True


def _schedule(job_id, params,owner=None):
    # New browser requests can replace obsolete queued legacy work, never another
    # browser's work or a raster read already running.
    if owner and len(RUNNING)>=MAX_PENDING:
        for old_id in list(FUTURES):
            saved=storage.source_snapshot('crop-map:v1:'+old_id)
            if saved and saved['result'].get('request_owner') is None and _supersede(old_id):break
    job = {'id':job_id,'status':'loading','phase':'queued','parameters':params}
    if owner:job['request_owner']=owner
    if len(RUNNING) >= MAX_PENDING:
        job['phase']='waiting'
        storage.source_snapshot('crop-map:v1:'+job_id,job)
        return job
    storage.source_snapshot('crop-map:v1:' + job_id, job)
    RUNNING.add(job_id)
    try:
        FUTURES[job_id]=POOL.submit(_build, job_id, params)
    except Exception:
        RUNNING.discard(job_id)
        FUTURES.pop(job_id,None)
        job.update(status='error', error='Não foi possível iniciar a consulta de culturas. Tente novamente.')
        storage.source_snapshot('crop-map:v1:' + job_id, job)
        raise ValueError(job['error']) from None
    return job


def _build(job_id, params):
    with LOCK:
        saved=storage.source_snapshot('crop-map:v1:'+job_id)
        job=saved['result'] if saved else {'id':job_id,'parameters':params}
        job.update(status='loading',phase='processing')
        storage.source_snapshot('crop-map:v1:'+job_id,job)
    try:
        result = data_sources.mapbiomas(params)
        job.update(status='ready', result=result)
    except ValueError as exc:
        job.update(status='error', error=str(exc))
    except Exception:
        job.update(status='error', error='A fonte do mapa de culturas não respondeu. Tente novamente em instantes.')
    finally:
        try:
            storage.source_snapshot('crop-map:v1:' + job_id, job)
        finally:
            with LOCK:
                RUNNING.discard(job_id)
                FUTURES.pop(job_id,None)
