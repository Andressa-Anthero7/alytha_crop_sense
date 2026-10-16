"""Persistent low vegetation in co-registered satellite pixels, without field labels."""
import csv
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from . import inactive_soy, research, spatial_raster, storage
from .catalog_search import extract_geometry

POOL = ThreadPoolExecutor(max_workers=1,thread_name_prefix='cv-spatial')
LOCK = threading.Lock()
RUNNING = set()
OUTPUT_ROOT = Path(__file__).resolve().parents[1]/'data/outputs/cv'
FEATURE_NAMES = ['common_coverage','persistent_low_fraction','latest_ndvi_std','mean_ndvi_change','patches_per_100ha','largest_patch_fraction','vegetation_gain_fraction','vegetation_loss_fraction']


def change_patches(mask, grid, signal, delta):
    import cv2
    import numpy as np
    from rasterio.features import shapes
    from rasterio.warp import transform_geom
    from shapely.geometry import shape, mapping
    from shapely import make_valid
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8),connectivity=8)
    retained=[index for index in range(1,count) if stats[index,cv2.CC_STAT_AREA]>=100]
    mapped=np.isin(labels,retained)
    features=[]
    for geometry,index in shapes(labels.astype(np.int32),mask=mapped,transform=grid['transform'],connectivity=8):
        index=int(index)
        geometry=make_valid(shape(geometry))
        if geometry.geom_type=='GeometryCollection':
            from shapely.ops import unary_union
            geometry=unary_union([part for part in geometry.geoms if part.geom_type in ('Polygon','MultiPolygon')])
        rectangle = geometry.minimum_rotated_rectangle
        corners = list(rectangle.exterior.coords) if rectangle.geom_type == 'Polygon' else []
        sides = [((a[0]-b[0])**2+(a[1]-b[1])**2)**.5 for a,b in zip(corners,corners[1:])]
        rectangularity = float(geometry.area/rectangle.area) if rectangle.area else 0
        elongation = max(sides)/min(sides) if sides and min(sides)>0 else 0
        pattern = 'faixa regular' if rectangularity>=.7 and elongation>=3 else 'bloco regular' if rectangularity>=.7 else 'mancha irregular'
        features.append({'type':'Feature','geometry':transform_geom(grid['crs'],'EPSG:4326',mapping(geometry)),
                         'properties':{'patch_id':index,'area_ha':int(stats[index,cv2.CC_STAT_AREA])*.01,'signal':signal,
                                       'mean_ndvi_change':float(delta[labels==index].mean()),'observations':3,
                                       'shape_pattern':pattern,'rectangularity':round(rectangularity,3),
                                       'elongation':round(elongation,2)}})
    return features,int(mapped.sum())*.01


def select_periods(points, as_of):
    end = date.fromisoformat(as_of)
    candidates = sorted([p for p in points if (end-timedelta(days=35)).isoformat()<=p['date']<=as_of
                         and p.get('valid_pixels',0)>=50 and p.get('valid_fraction',0)>=.5],key=lambda p:p['date'],reverse=True)
    periods = []
    for point in candidates:
        first = date.fromisoformat(point['date'])
        last = min(end,first+timedelta(days=4))
        if not periods or last.isoformat()<periods[-1]['from']:
            periods.append({'from':first.isoformat(),'to':last.isoformat()})
        if len(periods)==3:break
    periods.reverse()
    if len(periods)<3 or (date.fromisoformat(periods[-1]['from'])-date.fromisoformat(periods[0]['from'])).days<10:
        raise ValueError('Faltam três períodos recentes, distintos e com leitura suficiente, separados por pelo menos 10 dias.')
    if (end-date.fromisoformat(periods[-1]['to'])).days>15:
        raise ValueError('A última leitura útil está antiga demais para a análise atual.')
    return periods


def analyze_pixels(images, grid):
    import cv2
    import numpy as np
    from rasterio.features import shapes
    from rasterio.warp import transform_geom
    from shapely.geometry import shape, mapping
    from shapely import make_valid
    if len(images)!=3 or any(ndvi.shape!=grid['mask'].shape or valid.shape!=grid['mask'].shape for ndvi,valid in images):
        raise ValueError('As três imagens devem usar a mesma grade geográfica.')
    cube = np.stack([ndvi for ndvi,_ in images])
    valid = np.stack([mask for _,mask in images]) & grid['mask']
    valid &= np.isfinite(cube) & (cube>=-1) & (cube<=1)
    common = np.all(valid,axis=0)
    area_pixels = int(grid['mask'].sum())
    common_pixels = int(common.sum())
    coverage = common_pixels/area_pixels
    base = {'analysis_area_ha':area_pixels*.01, 'observed_area_ha':common_pixels*.01,
            'common_coverage':coverage, 'window_coverage':[float(mask.sum()/area_pixels) for mask in valid],
            'unobserved_area_ha':(area_pixels-common_pixels)*.01,
            'geojson':{'type':'FeatureCollection','features':[]},'resolution_m':10,'minimum_patch_ha':1,
            'threshold_ndvi':.25,'status':'inconclusive','ml_features':None,
            'progression':{'status':'inconclusive','fronts':[],'geojson':{'type':'FeatureCollection','features':[]},'note':'Cobertura comum insuficiente para analisar direção.'}}
    if coverage<.5 or common_pixels<50:return base
    low = common & np.all(cube<=.25,axis=0)
    count,labels,stats,_ = cv2.connectedComponentsWithStats(low.astype(np.uint8),connectivity=8)
    retained = [label for label in range(1,count) if stats[label,cv2.CC_STAT_AREA]>=100]
    mapped = np.isin(labels,retained)
    features = []
    # Raster polygonization retains holes and full pixel footprints.
    for geometry,label in shapes(labels.astype(np.int32),mask=mapped,transform=grid['transform'],connectivity=8):
        label = int(label)
        geometry = mapping(make_valid(shape(geometry)))
        if geometry['type']=='GeometryCollection':
            from shapely.ops import unary_union
            geometry = mapping(unary_union([part for part in shape(geometry).geoms if part.geom_type in ('Polygon','MultiPolygon')]))
        features.append({'type':'Feature','geometry':transform_geom(grid['crs'],'EPSG:4326',geometry),
                         'properties':{'patch_id':label,'area_ha':int(stats[label,cv2.CC_STAT_AREA])*.01,
                                       'signal':'persistent_low_vegetation','observations':3}})
    persistent_pixels = int(mapped.sum())
    patch_sizes = [int(stats[label,cv2.CC_STAT_AREA]) for label in retained]
    base.update({'status':'ready','persistent_low_ha':persistent_pixels*.01,'patches':len(retained),
                 'small_low_regions_ha':int((low & ~mapped).sum())*.01,
                 'geojson':{'type':'FeatureCollection','features':features},
                 'ml_features':{'common_coverage':coverage,'persistent_low_fraction':persistent_pixels/common_pixels,
                                'latest_ndvi_std':float(np.std(cube[-1][common])),
                                'mean_ndvi_change':float(np.mean(cube[-1][common]-cube[0][common])),
                                'patches_per_100ha':len(retained)/(common_pixels*.01)*100,
                                'largest_patch_fraction':max(patch_sizes,default=0)/common_pixels}})
    delta=cube[-1]-cube[0]
    gain,gain_ha=change_patches(common & ~low & (delta>=.15),grid,'vegetation_gain',delta)
    loss,loss_ha=change_patches(common & ~low & (delta<=-.15),grid,'vegetation_loss',delta)
    base.update(change_geojson={'type':'FeatureCollection','features':features+gain+loss},
                vegetation_gain_ha=gain_ha,vegetation_loss_ha=loss_ha,change_threshold_ndvi=.15)
    base['ml_features'].update(vegetation_gain_fraction=gain_ha/base['observed_area_ha'],vegetation_loss_fraction=loss_ha/base['observed_area_ha'])
    from . import vegetation_progression
    base['progression']=vegetation_progression.analyze(cube,common,grid)
    # Separate chronological gains, even when no coherent direction is detected.
    # Early gains must persist into the last image; a later reversal is excluded.
    early_mask=common & (cube[1]-cube[0]>=.15) & (cube[2]-cube[0]>=.15) & (cube[2]>=cube[1]-.05)
    late_mask=common & ~early_mask & (cube[2]-cube[1]>=.15) & (cube[2]-cube[0]>=.15)
    stages=[]
    for stage,mask,change in [('early',early_mask,cube[1]-cube[0]),('late',late_mask,cube[2]-cube[1])]:
        patches,area=change_patches(mask,grid,'vegetation_gain',change)
        for feature in patches:feature['properties']['growth_stage']=stage
        stages.append({'stage':stage,'area_ha':area,'features':patches})
    base['growth_sequence']={'version':1,'stages':stages,
        'geojson':{'type':'FeatureCollection','features':[f for stage in stages for f in stage['features']]},
        'note':'Ganho de NDVI ≥ 0,15 em manchas de pelo menos 1 ha. Claro: aumento entre a primeira e a segunda imagem, mantido na última; escuro: aumento entre a segunda e a terceira, sem repetir os pixels da primeira etapa. A forma descreve a mancha observada, não delimita talhão cadastral nem confirma plantio.'}
    return base


def resolve_geometry(data):
    if data.get('geojson'):
        geometry=extract_geometry(data['geojson'])
        if data.get('dataset_id'):
            history=research.dataset(data['dataset_id'])
            if research.fingerprint(geometry)!=research.fingerprint(history['parameters']['geometry']):
                raise ValueError('O histórico carregado é de outro recorte. Abra o histórico da área selecionada para iniciar seu acompanhamento.')
        return geometry, 'Recorte selecionado no mapa'
    if str(data.get('municipality_code','5107925'))!='5107925':
        raise ValueError('Selecione um recorte no mapa. A referência automática deste piloto é somente de Sorriso.')
    reference = storage.source_snapshot('research:sorriso:pilot')
    history = storage.source_snapshot('history:'+reference['result']['dataset_id']) if reference else None
    if not history:raise ValueError('Abra a área de referência de Sorriso ou selecione um recorte no mapa.')
    return history['result']['parameters']['geometry'], 'Área de referência de Sorriso · amostra, não município inteiro'


def refresh_saved_growth(job):
    """Upgrade visualization from saved rasters only, without provider requests."""
    if job.get('status')!='ready' or job.get('growth_sequence',{}).get('version')==1:
        return job
    geometry=job['parameters']['geometry']
    grid=spatial_raster.grid_for(geometry)
    paths=[spatial_raster.cache_path(geometry,grid,period) for period in job['periods']]
    if len(paths)!=3 or not all(path.is_file() for path in paths):return job
    result=analyze_pixels([spatial_raster.read_raster(path,grid) for path in paths],grid)
    result['progression']['periods']=job['periods']
    job={**job,**result}
    storage.source_snapshot('cv:job:'+job['id'],job)
    return job


def start(data):
    geometry,scope = resolve_geometry(data)
    spatial_raster.grid_for(geometry)  # Validate before queuing downloads.
    as_of=data.get('as_of') or inactive_soy.today().isoformat()
    if not isinstance(as_of,str) or not date(2018,1,1)<=date.fromisoformat(as_of)<=inactive_soy.today():
        raise ValueError('Escolha uma data de acompanhamento entre 2018 e hoje.')
    params = {'geometry':geometry,'area_id':research.fingerprint(geometry),'as_of':as_of,
              'scope':scope,'algorithm_version':3}
    job_id = research.fingerprint(params)
    with LOCK:
        cached = storage.source_snapshot('cv:job:'+job_id)
        if cached and cached['result']['status'] in ('ready','inconclusive'):return refresh_saved_growth(cached['result'])
        job = {'id':job_id,'parameters':params,'status':'loading','phase':'dates','processed':0,'total':3}
        if job_id not in RUNNING:
            RUNNING.add(job_id);storage.source_snapshot('cv:job:'+job_id,job);POOL.submit(build,job_id,params)
    return cached['result'] if cached and cached['result']['status']=='loading' else job


def get(job_id):
    cached = storage.source_snapshot('cv:job:'+job_id)
    if not cached:raise ValueError('Análise espacial não encontrada.')
    job = refresh_saved_growth(cached['result'])
    if job['status']=='loading':
        with LOCK:
            if job_id not in RUNNING:RUNNING.add(job_id);POOL.submit(build,job_id,job['parameters'])
    return job


def recent_points(params):
    with storage.connect() as db:
        histories = [json.loads(row['result']) for row in db.execute("SELECT result FROM source_snapshots WHERE cache_key LIKE 'history:%'")]
    matching = [h for h in histories if h['parameters']['area_key']==params['area_id']]
    for history in sorted(matching,key=lambda h:h['parameters']['as_of'],reverse=True):
        try:select_periods(history['points'],params['as_of']);return history['points']
        except ValueError:pass
    from .web_app import request_ndvi_series
    end = date.fromisoformat(params['as_of'])
    return request_ndvi_series(params['geometry'],(end-timedelta(days=35)).isoformat(),params['as_of'])['points']


def build(job_id,params):
    job = {'id':job_id,'parameters':params,'status':'loading','phase':'dates','processed':0,'total':3}
    def persist():
        job['updated_at']=storage.now();storage.source_snapshot('cv:job:'+job_id,job)
    try:
        periods = select_periods(recent_points(params),params['as_of'])
        grid = spatial_raster.grid_for(params['geometry'])
        job.update({'periods':periods,'phase':'images'});persist()
        images = []
        for period in periods:
            images.append(spatial_raster.fetch(params['geometry'],grid,period))
            job['processed']=len(images);persist()
        result = analyze_pixels(images,grid)
        result['progression']['periods']=periods
        job.update(result);job['phase']='complete'
        job['note']='Pouca vegetação nos mesmos pixels em três períodos. Não confirma abandono, terra disponível ou etapa de manejo. Nuvens, sombras e água são excluídas. Áreas em hectares são estimadas na grade de 10 m, sem extrapolação.'
        folder = OUTPUT_ROOT/job_id
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'manchas.geojson').write_text(json.dumps(result['geojson'],ensure_ascii=False),encoding='utf-8')
        if result.get('change_geojson'):
            (folder/'mudancas.geojson').write_text(json.dumps(result['change_geojson'],ensure_ascii=False),encoding='utf-8')
        (folder/'direcao.geojson').write_text(json.dumps(result['progression']['geojson'],ensure_ascii=False),encoding='utf-8')
        (folder/'progressao.json').write_text(json.dumps(result['progression'],ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        if result['ml_features']:
            row = {'area_id':params['area_id'],'date_from':periods[0]['from'],'date_to':periods[-1]['to'],**result['ml_features']}
            with (folder/'caracteristicas_ml.csv').open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader();writer.writerow(row)
        job['output_folder']=str(folder)
        persist()
        (folder/'analise.json').write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
    except ValueError as exc:
        job.update({'status':'error','error':str(exc)});persist()
    except Exception:
        job.update({'status':'error','error':'Não foi possível obter ou processar as imagens. Tente novamente; imagens válidas já obtidas ficam no cache.'});persist()
    finally:
        with LOCK:RUNNING.discard(job_id)
