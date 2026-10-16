"""Sorriso pilot: historical observations, field labels and supervised learning."""
import hashlib
import json
import math
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from . import storage, municipalities, inactive_soy
from .catalog_search import extract_geometry

POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='history')
LOCK=threading.Lock(); RUNNING=set()
TRAIN_LOCK=threading.Lock()
MODEL_PATH=Path(__file__).resolve().parents[1]/'data/models/manejo.joblib'
STAGES={'emergencia':'Emergência','desenvolvimento':'Desenvolvimento','colheita':'Colheita recente','solo_exposto':'Solo exposto','preparo':'Preparo do solo','plantio':'Plantio','pousio':'Pousio'}
FEATURE_NAMES=['latest','mean','min','max','amplitude','slope_day','peak_drop','first_last_delta','observations','span_days','valid_fraction','month_sin','month_cos']

def fingerprint(value): return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def dataset(dataset_id):
    if not isinstance(dataset_id,str) or len(dataset_id)!=64 or any(c not in '0123456789abcdef' for c in dataset_id): raise ValueError('Histórico inválido.')
    saved=storage.source_snapshot('history:'+dataset_id)
    if not saved: raise ValueError('Histórico não encontrado.')
    return saved['result']

def restore_history(dataset_id):
    """Resume a persisted job whose worker was lost when the server stopped."""
    with LOCK:
        history=dataset(dataset_id)
        if history['status']=='loading' and dataset_id not in RUNNING:
            RUNNING.add(dataset_id)
            try: POOL.submit(build_history,dataset_id,history['parameters'])
            except Exception:
                RUNNING.discard(dataset_id)
                raise
    return history

def start_history(data):
    geometry=extract_geometry(data.get('geojson'))
    first,last=data.get('start_year',2018),data.get('end_year',inactive_soy.today().year)
    if type(first) is not int or type(last) is not int or not 2018<=first<=last<=inactive_soy.today().year: raise ValueError('Escolha anos entre 2018 e o ano atual.')
    from shapely.geometry import shape
    from shapely.ops import unary_union
    code=data.get('municipality_code','5107925')
    municipalities.key(code)
    boundary=municipalities.boundary(code)
    region=unary_union([shape(f['geometry']) for f in boundary['features']])
    area=shape(geometry)
    if not area.is_valid or area.is_empty or not region.buffer(1e-8).covers(area): raise ValueError('Selecione uma área dentro do município informado.')
    from .web_app import project_to_web_mercator,geometry_bbox
    bbox=geometry_bbox(project_to_web_mercator(geometry)); width=(bbox[2]-bbox[0])/10; height=(bbox[3]-bbox[1])/10
    if width>2500 or height>2500 or width*height>4_000_000: raise ValueError('Selecione uma área menor para reconstruir seu histórico em 10 m.')
    area_key=fingerprint(geometry)
    params={'area_key':area_key,'geometry':geometry,'start_year':first,'end_year':last,'as_of':inactive_soy.today().isoformat(),'municipality_code':code}
    dataset_id=fingerprint(params)
    with LOCK:
        saved=storage.source_snapshot('history:'+dataset_id)
        if dataset_id not in RUNNING and (not saved or saved['result']['status']!='ready'):
            RUNNING.add(dataset_id)
            storage.source_snapshot('history:'+dataset_id,{'id':dataset_id,'parameters':params,'status':'loading','points':[],'years':[],'processed':0,'total':last-first+1})
            POOL.submit(build_history,dataset_id,params)
    return dataset(dataset_id)

def build_history(dataset_id,params):
    from .web_app import request_ndvi_series
    result={'id':dataset_id,'parameters':params,'status':'loading','points':[],'years':[],'processed':0,'total':params['end_year']-params['start_year']+1,'source':'Copernicus Sentinel-2 L2A','resolution_m':10,'aggregation_days':5,'note':'Histórico de vegetação; cultura e manejo de cada ano ainda dependem de referência de campo.'}
    def persist():
        result['updated_at']=storage.now();storage.source_snapshot('history:'+dataset_id,result)
    try:
        persist()
        for year in range(params['start_year'],params['end_year']+1):
            start=date(year,1,1); end=min(date(year,12,31),date.fromisoformat(params['as_of']))
            cache_key='history-year:'+fingerprint([params['area_key'],start.isoformat(),end.isoformat(),2])
            cached=storage.source_snapshot(cache_key)
            try:
                series=cached['result'] if cached else request_ndvi_series(params['geometry'],start.isoformat(),end.isoformat())
                if not cached: storage.source_snapshot(cache_key,series)
                result['points'].extend(series['points'])
                result['years'].append({'year':year,'status':'ready','observations':len(series['points'])})
            except Exception as exc:
                from .collection_issues import failure
                result['years'].append({'year':year,'status':'error','observations':0,'issue':failure('Sentinel-2','histórico anual',exc)})
            result['processed']+=1;persist()
        result['points'].sort(key=lambda p:p['date'])
        result['status']='partial' if any(y['status']=='error' for y in result['years']) else 'ready'
        persist()
    except Exception:
        result['status']='error'; result['error']='Não foi possível concluir o histórico.';persist()
    finally:
        with LOCK: RUNNING.discard(dataset_id)

def windows(points,cutoff):
    end=date.fromisoformat(cutoff); valid=[]
    for p in points:
        try:
            when=date.fromisoformat(p['date']);value=p['ndvi_mean']
            available=date.fromisoformat(p.get('available',p['date']))
            if end-timedelta(days=90)<=when<=end and available<=end and type(value) in (int,float) and math.isfinite(value) and -1<=value<=1 and p.get('valid_pixels',0)>=50 and 0.5<=p.get('valid_fraction',0)<=1: valid.append(p)
        except (ValueError,TypeError,KeyError): continue
    return sorted({p['date']:p for p in valid}.values(),key=lambda p:p['date'])

def features(points,cutoff):
    valid=windows(points,cutoff)
    if len(valid)<5: raise ValueError('A janela precisa de ao menos cinco intervalos com cobertura suficiente.')
    days=[(date.fromisoformat(p['date'])-date.fromisoformat(valid[0]['date'])).days for p in valid]
    if days[-1]<20 or (date.fromisoformat(cutoff)-date.fromisoformat(valid[-1]['date'])).days>20: raise ValueError('Janela temporal insuficiente ou observações antigas demais.')
    values=[p['ndvi_mean'] for p in valid]; xm=sum(days)/len(days);ym=sum(values)/len(values)
    slope=sum((x-xm)*(y-ym) for x,y in zip(days,values))/sum((x-xm)**2 for x in days)
    phase=date.fromisoformat(cutoff).timetuple().tm_yday*2*math.pi/365.25
    return [values[-1],ym,min(values),max(values),max(values)-min(values),slope,max(values)-values[-1],values[-1]-values[0],len(values),days[-1],sum(p['valid_fraction'] for p in valid)/len(valid),math.sin(phase),math.cos(phase)]

def baseline(points,cutoff):
    try: vector=features(points,cutoff)
    except ValueError as exc: return {'method':'regras_temporais','stage':'inconclusivo','label':'Inconclusivo','reason':str(exc)}
    latest,mean,low,peak,amplitude,slope,drop,delta=vector[:8]
    if peak>=0.5 and latest<=0.35 and drop>=0.25 and delta<=-0.2: stage='colheita';reason='Vegetação anteriormente alta seguida de queda; também pode indicar outros eventos de perda de vegetação.'
    elif low<=0.25 and delta>=0.2 and slope>=0.003: stage='emergencia';reason='Crescimento após fase de baixo vigor; pode indicar emergência, rebrota ou vegetação espontânea.'
    elif latest>=0.4 and slope>=0.001: stage='desenvolvimento';reason='Vegetação com vigor crescente.'
    elif all(p['ndvi_mean']<=0.25 for p in windows(points,cutoff)[-3:]): stage='solo_exposto';reason='Vigor baixo persistente; preparo, pousio e pós-colheita não são separados apenas por esta regra.'
    else: return {'method':'regras_temporais','stage':'inconclusivo','label':'Inconclusivo','reason':'A trajetória não corresponde claramente às regras experimentais.'}
    return {'method':'regras_temporais','stage':stage,'label':'Possível '+STAGES[stage].lower(),'reason':reason,'experimental':True,'features':dict(zip(FEATURE_NAMES,vector))}

def events():
    with storage.connect() as db:
        return [dict(row) for row in db.execute('SELECT * FROM field_events ORDER BY id DESC')]

def add_event(data):
    history=dataset(data.get('dataset_id'));first=date.fromisoformat(data.get('from',''));last=date.fromisoformat(data.get('to',''))
    history_end=min(date(history['parameters']['end_year'],12,31),date.fromisoformat(history['parameters']['as_of']))
    if last<first or first.year<history['parameters']['start_year'] or last>history_end: raise ValueError('Período de manejo fora do histórico.')
    stage=data.get('stage');note=data.get('note','')
    if stage not in STAGES or not isinstance(note,str) or not 3<=len(note.strip())<=500: raise ValueError('Informe etapa e referência de campo (3–500 caracteres).')
    provenance=data.get('provenance',{})
    if not isinstance(provenance,dict) or len(json.dumps(provenance))>3000:
        raise ValueError('Origem do registro de campo inválida.')
    provenance={**provenance,'origin':'human_field_record'}
    features(history['points'],last.isoformat())
    with storage.connect() as db:
        if db.execute('SELECT id FROM field_events WHERE area_key=? AND date_from<=? AND date_to>=?',(history['parameters']['area_key'],last.isoformat(),first.isoformat())).fetchone(): raise ValueError('Já existe registro de campo para esta área neste período. Evite rótulos sobrepostos.')
        cursor=db.execute('INSERT INTO field_events(dataset_id,area_key,date_from,date_to,stage,note,created_at,provenance) VALUES(?,?,?,?,?,?,?,?)',(history['id'],history['parameters']['area_key'],first.isoformat(),last.isoformat(),stage,note.strip(),storage.now(),json.dumps(provenance)))
        event_id=cursor.lastrowid
    return {'saved':True,'events':len(events()),'event_id':event_id}

def model_status():
    counts={stage:0 for stage in STAGES};records=events()
    for r in records: counts[r['stage']]+=1
    saved=storage.source_snapshot('ml:model:v1')
    return {'events':len(records),'areas':len({r['area_key'] for r in records}),'class_counts':counts,'minimum_events':30,'minimum_areas':3,'model':saved['result'] if saved and MODEL_PATH.is_file() else None,'note':'Treinamento usa apenas registros informados de campo; resultados continuam experimentais.'}

def train(promote=True):
    if not TRAIN_LOCK.acquire(blocking=False): raise ValueError('Um treinamento já está em andamento.')
    try: return _train(promote=promote)
    finally: TRAIN_LOCK.release()

def _train(promote=True):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import GroupKFold,cross_val_predict
    from sklearn.metrics import balanced_accuracy_score,classification_report,confusion_matrix
    import joblib
    records=events();x=[];y=[];groups=[]
    for record in records:
        try: vector=features(dataset(record['dataset_id'])['points'],record['date_to'])
        except ValueError: continue
        x.append(vector);y.append(record['stage']);groups.append(record['area_key'])
    if len(x)<30 or len(set(groups))<3 or len(set(y))<2: raise ValueError('Para treinar: ao menos 30 registros utilizáveis de campo, três áreas distintas e duas etapas.')
    if any(y.count(stage)<5 for stage in set(y)): raise ValueError('Cada etapa precisa de pelo menos cinco registros de campo.')
    model=RandomForestClassifier(n_estimators=150,max_depth=6,min_samples_leaf=2,class_weight='balanced',random_state=42,n_jobs=1)
    prediction=cross_val_predict(model,x,y,groups=groups,cv=GroupKFold(n_splits=min(5,len(set(groups)))))
    metadata={'method':'RandomForest','status':'experimental','trained_at':storage.now(),'events':len(x),'areas':len(set(groups)),'classes':sorted(set(y)),'features':FEATURE_NAMES,'validation':'GroupKFold por área; o mesmo polígono não aparece em treino e teste do mesmo fold. Áreas sobrepostas distintas ainda precisam de revisão.','balanced_accuracy':float(balanced_accuracy_score(y,prediction)),'report':classification_report(y,prediction,output_dict=True,zero_division=0),'confusion_matrix':confusion_matrix(y,prediction,labels=sorted(set(y))).tolist(),'note':'Métricas de validação interna; validação externa de campo pendente. Probabilidades não calibradas.'}
    model.fit(x,y)
    MODEL_PATH.parent.mkdir(parents=True,exist_ok=True)
    version=uuid.uuid4().hex
    destination=MODEL_PATH.parent/'versions'/f'manejo-{version}.joblib'
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix('.tmp');joblib.dump(model,temporary);temporary.replace(destination)
    metadata.update(version=version,model_path=str(destination),promoted=promote)
    if promote:
        import shutil
        temporary=MODEL_PATH.with_suffix('.tmp');shutil.copyfile(destination,temporary);temporary.replace(MODEL_PATH)
    storage.source_snapshot('ml:model:v1' if promote else 'ml:candidate:v1',metadata)
    storage.source_snapshot('ml:version:'+version,metadata)
    return metadata

def analyze(dataset_id,cutoff=None):
    history=dataset(dataset_id);cutoff=cutoff or history['parameters']['as_of']
    result={'dataset_id':dataset_id,'date':cutoff,'baseline':baseline(history['points'],cutoff),'model_prediction':None}
    from .historical_comparison import compare
    try: result['historical_comparison']=compare(history,cutoff)
    except ImportError: result['historical_comparison']={'status':'unavailable','reading':'Comparação histórica indisponível: instale as dependências de requirements-ml.txt.'}
    try: result['vegetation_patterns']=patterns(history,cutoff)
    except (ValueError,ImportError): result['vegetation_patterns']=None
    status=model_status()
    if status['model']:
        import joblib
        try:
            vector=features(history['points'],cutoff);model=joblib.load(MODEL_PATH);probabilities=model.predict_proba([vector])[0];index=int(probabilities.argmax())
            result['model_prediction']={'stage':str(model.classes_[index]),'label':STAGES[str(model.classes_[index])],'probability_uncalibrated':float(probabilities[index]),'experimental':True,'training_validation':status['model']['balanced_accuracy']}
        except ValueError: pass
    result['note']='Etapas são hipóteses. Registros de campo são necessários para confirmar manejo.'
    return result

def patterns(history,cutoff):
    """Learn vegetation groups without inventing management ground truth."""
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    from .historical_comparison import prepare
    frame,_=prepare(history,cutoff)
    eligible=[{**point,'date':point['date'].date().isoformat(),'available':point['available'].date().isoformat()} for point in frame.to_dict('records')]
    cache_key='ml:patterns:'+fingerprint([history['id'],history.get('updated_at'),len(eligible),cutoff,2])
    cached=storage.source_snapshot(cache_key)
    select=[0,1,2,3,4,5,6,7,10]
    if not cached:
        vectors=[]
        for point in eligible[::3]:
            try: vector=features(eligible,point['available'])
            except ValueError: continue
            vectors.append([vector[i] for i in select])
        if len(vectors)<20: raise ValueError('Histórico ainda insuficiente para aprender padrões de vegetação.')
        # The number of distinct windows also limits the meaningful cluster count.
        k=min(4,len({tuple(round(v,5) for v in row) for row in vectors}))
        if k<2: raise ValueError('Histórico não contém variação suficiente para separar padrões.')
        scaler=StandardScaler();scaled=scaler.fit_transform(vectors)
        with threadpool_limits(limits=1):
            model=KMeans(n_clusters=k,n_init=10,random_state=42).fit(scaled)
        centroids=scaler.inverse_transform(model.cluster_centers_)
        learned={'method':'KMeans','kind':'unsupervised','windows':len(vectors),'groups':[{'id':int(index),'windows':int(np.sum(model.labels_==index)),'mean_ndvi':round(float(center[1]),3),'latest_ndvi':round(float(center[0]),3),'slope_day':round(float(center[5]),5)} for index,center in enumerate(centroids)],'centers':model.cluster_centers_.tolist(),'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),'note':'Grupos aprendidos do histórico real; não são etapas de manejo confirmadas nem medem acurácia.'}
        storage.source_snapshot(cache_key,learned);cached=storage.source_snapshot(cache_key)
    learned=cached['result'];vector=features(eligible,cutoff)
    scaled=(np.array([vector[i] for i in select])-np.array(learned['mean']))/np.array(learned['scale'])
    group=int(np.sum((np.array(learned['centers'])-scaled)**2,axis=1).argmin())
    return {key:value for key,value in learned.items() if key not in ('centers','mean','scale')} | {'current_group':group}

def pilot():
    from . import data_sources
    municipalities.request('5107925')
    import time
    for attempt in range(120):
        try: municipalities.boundary('5107925');break
        except ValueError:
            if attempt==119: raise ValueError('Limite IBGE de Sorriso indisponível. Tente novamente.')
            time.sleep(0.25)
    features=data_sources.mapbiomas({'bounds':[-55.81,-12.51,-55.79,-12.49],'municipality_code':'5107925','year':2025,'class_id':39})['features']
    if not features: raise ValueError('Não foi encontrada área de referência neste recorte de Sorriso.')
    reference=min(features,key=lambda f:f['properties']['area_ha'])
    result=start_history({'geojson':reference,'start_year':2018,'end_year':inactive_soy.today().year})
    storage.source_snapshot('research:sorriso:pilot',{'dataset_id':result['id'],'source':reference['properties'],'note':'Mancha histórica MapBiomas; limite cadastral e manejo não confirmados.'})
    return result
