"""Whole-municipality job, preserving unassessed land instead of extrapolating a sample."""
import hashlib
import json
from datetime import date,timedelta
from . import storage,municipalities,data_sources,inactive_soy

POOL=inactive_soy.POOL
LOCK=inactive_soy.LOCK
RUNNING=set()

def map_assessment(job_id,include_geometry=True,processed=None):
    """Read the same job snapshot and date cutoffs as the chart; no new imagery."""
    from . import research
    with storage.connect() as db:
        db.execute('BEGIN')
        row=db.execute('SELECT result FROM source_snapshots WHERE cache_key=?',('municipal-activity:'+job_id,)).fetchone()
        if not row:raise ValueError('Consulta municipal não encontrada.')
        job=json.loads(row['result'])
        row=db.execute('SELECT result FROM source_snapshots WHERE cache_key=?',('municipal-soy:v1:'+job['parameters']['municipality_code'],)).fetchone()
        if not row:raise ValueError('O mapeamento da soja ainda está em andamento.')
        historical=json.loads(row['result'])
        evidence={r['cache_key']:json.loads(r['result']) for r in db.execute("SELECT cache_key,result FROM source_snapshots WHERE cache_key LIKE 'inactive-evidence:%'")}
    dates=[point['date'] for point in job.get('points',[])]
    if not dates:raise ValueError('A avaliação municipal ainda não possui datas disponíveis.')
    processed=job['processed'] if processed is None else processed
    if type(processed) is not int or not 0<=processed<=job['processed']:raise ValueError('Andamento da avaliação municipal inválido.')
    end=date.fromisoformat(job['parameters']['as_of'])
    period={'from':(end-timedelta(days=60)).isoformat(),'to':end.isoformat()}
    states=[]
    features=historical['features']
    for index,feature in enumerate(features):
        if index>=processed:
            states.append(['pending']*len(dates));continue
        key='inactive-evidence:'+hashlib.sha256(json.dumps([feature['geometry'],period],sort_keys=True).encode()).hexdigest()
        series=evidence.get(key)
        if not series:
            states.append(['unknown']*len(dates));continue
        try:
            points=series['points']
            available_dates=[min(end,date.fromisoformat(point['date'])+timedelta(days=4)) for point in points]
            states.append([inactive_soy.classify([point for point,available in zip(points,available_dates) if available<=date.fromisoformat(cutoff)],date.fromisoformat(cutoff))['status'] for cutoff in dates])
        except (KeyError,TypeError,ValueError):
            states.append(['unknown']*len(dates))
    summaries=job['points']
    if processed!=job['processed']:
        summaries=[]
        for date_index,cutoff in enumerate(dates):
            entry={'date':cutoff,'possible_inactive_ha':0,'not_matched_ha':0,'unknown_ha':0,'pending_ha':historical['total_soy_ha'],'total_soy_ha':historical['total_soy_ha']}
            for feature,area_states in zip(features[:processed],states[:processed]):
                hectares=feature['properties']['area_ha']
                entry[area_states[date_index]+'_ha']+=hectares
                entry['pending_ha']=max(0,entry['pending_ha']-hectares)
            summaries.append(entry)
    result={'job_id':job_id,'municipality_code':job['parameters']['municipality_code'],'processed':processed,
            'dates':dates,'states':states,'historical_year':2025,'summary_by_date':summaries,
            'note':'Classes de vigor vegetativo em polígonos de soja histórica. Contornos simplificados para exibição; áreas calculadas nas geometrias originais. Fragmentos menores que 5 ha não são desenhados nesta camada.'}
    if include_geometry:
        # Geometry changes only with the historical municipal base, not on hover
        # or progress updates. Keep a separate display cache to avoid large transfers.
        cache_key='municipal-activity-display:v1:'+job['parameters']['municipality_code']+':'+research.fingerprint([f['geometry'] for f in features])
        cached=storage.source_snapshot(cache_key)
        if cached:display=cached['result']
        else:
            from shapely.geometry import shape,mapping
            from rasterio.warp import transform_geom
            display=[]
            for index,feature in enumerate(features):
                projected=shape(transform_geom('EPSG:4326','EPSG:3857',feature['geometry']))
                simplified=projected.simplify(10,preserve_topology=True)
                geometry=transform_geom('EPSG:3857','EPSG:4326',mapping(simplified))
                display.append({'type':'Feature','geometry':geometry,'properties':{**feature['properties'],'activity_index':index}})
            storage.source_snapshot(cache_key,display)
        result['geojson']={'type':'FeatureCollection','features':display}
    return result

def start(data):
    code=data.get('municipality_code')
    municipalities.key(code)
    params={'municipality_code':code,'as_of':inactive_soy.today().isoformat(),'year':2025,'version':1}
    job_id=hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()
    with LOCK:
        saved=storage.source_snapshot('municipal-activity:'+job_id)
        if not saved:
            storage.source_snapshot('municipal-activity:'+job_id,{'id':job_id,'parameters':params,'status':'loading','phase':'mapping','processed':0,'total':0,'points':[]})
        if job_id not in RUNNING and (not saved or saved['result']['status']!='ready'):
            RUNNING.add(job_id)
            POOL.submit(build,job_id,params)
    return get(job_id,False)

def get(job_id,resume=True):
    if len(job_id)!=64 or any(c not in '0123456789abcdef' for c in job_id): raise ValueError('Consulta municipal inválida.')
    saved=storage.source_snapshot('municipal-activity:'+job_id)
    if not saved: raise ValueError('Consulta municipal não encontrada.')
    result=saved['result']
    if resume and result['status']=='loading':
        with LOCK:
            if job_id not in RUNNING:
                RUNNING.add(job_id);POOL.submit(build,job_id,result['parameters'])
    return result

def build(job_id,params):
    end=date.fromisoformat(params['as_of']);first=end-timedelta(days=60)
    cutoffs=[];cursor=first
    while cursor<=end:
        cutoffs.append(min(cursor+timedelta(days=4),end));cursor+=timedelta(days=5)
    result={'id':job_id,'parameters':params,'status':'loading','phase':'mapping','processed':0,'total':0,'points':[],
            'period':{'from':first.isoformat(),'to':end.isoformat()},'scope':'municipality','historical_year':2025,'source':'MapBiomas e Sentinel-2','failure_count':0,'failures':[],
            'note':'Abrange o município selecionado. Hectares estimados em manchas de soja histórica, sem limites de talhões confirmados. Pouca vegetação não comprova terra parada.'}
    def persist():
        result['updated_at']=storage.now();storage.source_snapshot('municipal-activity:'+job_id,result)
    try:
        persist()
        historical=data_sources.municipal_soy_areas(params['municipality_code'])
        features=historical['features'];total_ha=historical['total_soy_ha']
        result.update(total=len(features),total_soy_ha=total_ha,assessed_ha=0,phase='images')
        result['points']=[{'date':when.isoformat(),'possible_inactive_ha':0,'not_matched_ha':0,'unknown_ha':0,'pending_ha':total_ha,'total_soy_ha':total_ha} for when in cutoffs]
        current={'possible_inactive_ha':0,'not_matched_ha':0,'unknown_ha':0,'pending_ha':total_ha}
        result['summary']=current
        persist()
        for feature in features:
            hectares=feature['properties']['area_ha']
            try:
                # This shares exactly the same geometry/period cache as the per-area chart.
                with_points=inactive_soy.activity({'geojson':feature},end=end)
                points=with_points['points']
                status=with_points['summary']['status']
            except Exception as exc:
                from .collection_issues import failure
                result['failure_count']+=1
                issue=failure('Sentinel-2','atividade recente',exc)
                issue['recorte_index']=result['processed']
                result['failures'].append(issue)
                points=[];status='unknown'
            for entry,cutoff in zip(result['points'],cutoffs):
                available=[p for p in points if date.fromisoformat(p.get('activity_as_of',p['date']))<=cutoff]
                state=inactive_soy.classify(available,cutoff)['status']
                entry[state+'_ha']+=hectares
                entry['pending_ha']=max(0,entry['pending_ha']-hectares)
            current[status+'_ha']+=hectares;current['pending_ha']=max(0,current['pending_ha']-hectares)
            result['assessed_ha']+=hectares;result['processed']+=1;persist()
        result['status']='ready';result['phase']='complete';persist()
    except Exception as exc:
        from .collection_issues import failure
        result['issue']=failure('MapBiomas' if result.get('phase')=='mapping' else 'Sentinel-2',result.get('phase','coleta'),exc)
        result['status']='error'
        result['error']=str(exc) if isinstance(exc,(ValueError,ImportError)) else 'Não foi possível concluir a análise municipal. Tente novamente.'
        persist()
    finally:
        with LOCK: RUNNING.discard(job_id)
