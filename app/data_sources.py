"""Source-specific adapters; keep historical maps and aggregate statistics distinct."""
import csv
import gzip
import io
import json
import heapq
import math
import time
import re
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from . import storage
from .catalog_search import extract_geometry, validate_date

CONAB_URL = 'https://portaldeinformacoes.conab.gov.br/downloads/arquivos/SerieHistoricaGraos.txt'
MAPBIOMAS_PAGE = 'https://brasil.mapbiomas.org/downloads/mapas-para-download-geotiff/'
MAPBIOMAS_URL = 'https://storage.googleapis.com/mapbiomas-public/initiatives/brasil/collection11/lulc/coverage/brazil_coverage/brazil_coverage-col11_{year}.tif'
SATVEG_URL = 'https://api.cnptia.embrapa.br/satveg/v2/seriespoligono'
CLASSES = {39: 'Soja', 20: 'Cana', 40: 'Arroz', 62: 'Algodão (beta)', 41: 'Outras lavouras temporárias', 46: 'Café', 47: 'Citrus', 35: 'Dendê', 48: 'Outras lavouras perenes'}

def read_bytes(url, payload=None, token=None):
    headers = {'User-Agent': 'Alytha-LotMonitoring/1.0'}
    if payload is not None: headers['Content-Type'] = 'application/json'
    if token: headers['Authorization'] = 'Bearer ' + token
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
    with urlopen(request, timeout=45) as response:
        body = response.read(30_000_001)
    if len(body) > 30_000_000: raise ValueError('Resposta da fonte excedeu o limite local.')
    return gzip.decompress(body) if body.startswith(b'\x1f\x8b') else body

def conab(uf, crop):
    if not re.fullmatch('[A-Z]{2}', uf) or crop not in {'SOJA', 'MILHO', 'SORGO'}:
        raise ValueError('Selecione UF e cultura válidas.')
    key = 'conab:graos:v1'
    snapshot = storage.source_snapshot(key)
    if not snapshot or datetime.now(timezone.utc) - datetime.fromisoformat(snapshot['fetched_at']) > timedelta(days=1):
        raw = read_bytes(CONAB_URL)
        try: content = raw.decode('utf-8-sig')
        except UnicodeDecodeError: content = raw.decode('cp1252')
        rows = list(csv.DictReader(io.StringIO(content), delimiter=';'))
        required = {'ano_agricola','uf','produto','area_plantada_mil_ha','producao_mil_t'}
        if not rows or not required.issubset(rows[0]): raise ValueError('Formato CONAB mudou; importação não realizada.')
        storage.source_snapshot(key, rows); snapshot = storage.source_snapshot(key)
    records = []
    for row in snapshot['result']:
        if row['uf'].strip() != uf or not row['produto'].strip().startswith(crop): continue
        def number(key, factor=1):
            text = row.get(key, '').strip()
            return float(text.replace(',', '.')) * factor if text else None
        records.append({'season': row['ano_agricola'].strip(), 'crop': row['produto'].strip(), 'phase': row.get('dsc_safra_previsao','').strip(), 'area_ha': number('area_plantada_mil_ha',1000), 'production_t': number('producao_mil_t',1000), 'yield_t_ha': number('produtividade_mil_ha_mil_t')})
    records.sort(key=lambda r: (r['season'], r['phase']))
    return {'source':'CONAB — Série Histórica Grãos', 'source_url':CONAB_URL, 'scope':'UF', 'uf':uf, 'crop':crop, 'fetched_at':snapshot['fetched_at'], 'records':records, 'note':'Dados agregados por UF; não são estimativas para o polígono selecionado.'}

def mapbiomas_parameters(data):
    """Validate before scheduling any remote raster work."""
    if not isinstance(data, dict): raise ValueError('Informe um objeto JSON.')
    year, class_id = data.get('year',2025), data.get('class_id',39)
    if type(year) is not int or not 1985 <= year <= 2025 or type(class_id) is not int or class_id not in CLASSES:
        raise ValueError('Ano ou classe MapBiomas inválidos.')
    bounds = data.get('bounds')
    if not isinstance(bounds,list) or len(bounds)!=4 or any(type(v) not in (float,int) or not math.isfinite(v) for v in bounds):
        raise ValueError('Informe os limites da área visível no mapa.')
    west,south,east,north = bounds
    if data.get('municipality_code') or data.get('state_code'):
        # Fit-to-region viewports may include ocean/foreign territory at low zoom.
        # The administrative mask still limits the raster to the chosen region.
        west,south,east,north=max(-75,west),max(-35,south),min(-30,east),min(6,north)
        bounds=[west,south,east,north]
    if not (-75<=west<east<=-30 and -35<=south<north<=6):
        raise ValueError('Escolha uma área no Brasil e aproxime o mapa.')
    code = data.get('municipality_code') or None
    if code:
        from .municipalities import key
        key(code)
    state=data.get('state_code') or None
    if state and (not isinstance(state,str) or state not in ('11','12','13','14','15','16','17','21','22','23','24','25','26','27','28','29','31','32','33','35','41','42','43','50','51','52','53')):
        raise ValueError('Estado inválido.')
    if state and code and not code.startswith(state):raise ValueError('O município não pertence ao estado informado.')
    params={'year':year,'class_id':class_id,'bounds':list(bounds),'municipality_code':code}
    if state:params['state_code']=state
    if state and not code:
        saved=storage.source_snapshot('ibge-boundary:v1:states:'+state)
        extent=saved['result'].get('bounds') if saved else None
        if extent and bounds_cover(bounds,extent):
            params['bounds']=extent
            params['full_region']='state'
    return params


def bounds_cover(outer,inner):
    return outer[0]<=inner[0] and outer[1]<=inner[1] and outer[2]>=inner[2] and outer[3]>=inner[3]


def mapbiomas_cache_key(data):
    return 'mapbiomas:v5:'+json.dumps([data['year'],data['class_id'],data['bounds'],data.get('municipality_code')]+([data['state_code']] if data.get('state_code') else []))


def cached_mapbiomas(data):
    """Reuse only identical coverage; a partial or coarser viewport never substitutes detail."""
    key=mapbiomas_cache_key(data)
    saved=storage.source_snapshot(key)
    if saved:return saved['result']
    if data.get('full_region')!='state':return None
    # Promote previously prepared full-state results without downloading the raster.
    with storage.connect() as db:
        rows=db.execute("SELECT result FROM source_snapshots WHERE cache_key LIKE 'crop-map:v1:%' AND json_extract(result,'$.status')='ready' AND json_extract(result,'$.parameters.state_code')=? AND json_extract(result,'$.parameters.year')=? AND json_extract(result,'$.parameters.class_id')=? AND json_extract(result,'$.result.candidate_count') IS NOT NULL ORDER BY fetched_at DESC",(data['state_code'],data['year'],data['class_id'])).fetchall()
    for row in rows:
        job=json.loads(row['result']);params=job['parameters']
        if not params.get('municipality_code') and bounds_cover(params['bounds'],data['bounds']):
            result=job['result']
            storage.source_snapshot(key,result)
            return result
    return None


def _mapbiomas_result(features, year, class_id, overview, resolution_m):
    url = MAPBIOMAS_URL.format(year=year)
    return {'type':'FeatureCollection','features':features,'source':'MapBiomas Brasil — Coleção 11','year':year,'class_name':CLASSES[class_id],'source_url':url,'attribution':'MapBiomas — CC BY 4.0','fetched_at':storage.now(),'limit':200,'note':'Manchas históricas recortadas pela área visível, mínimo 5 ha. Não representam limites cadastrais, titularidade ou cultura atual.','overview':overview,'resolution_m':resolution_m}


def mapbiomas(data):
    started=time.perf_counter()
    data = mapbiomas_parameters(data)
    cached=cached_mapbiomas(data)
    if cached:return {**cached,'delivery':{'cache_hit':True,'seconds':round(time.perf_counter()-started,4)}}
    try:
        import numpy as np
        import rasterio
        from rasterio.windows import from_bounds
        from rasterio.features import shapes
        from rasterio.warp import transform_geom
        from shapely.geometry import shape, mapping
    except ImportError as exc:
        raise ValueError('Instale requirements-geospatial.txt para processar MapBiomas.') from exc
    year, class_id, bounds = data['year'], data['class_id'], data['bounds']
    key = mapbiomas_cache_key(data)
    municipal_geometry = None
    raster_bounds = bounds
    if data.get('municipality_code') or data.get('state_code'):
        from .municipalities import boundary
        from shapely.ops import unary_union
        from shapely.geometry import box
        if data.get('municipality_code'):
            boundary_data = boundary(data['municipality_code'])
        else:
            from .localities import location_data
            boundary_data=location_data('/api/locations/boundaries/states/'+data['state_code'])
        municipal_geometry = unary_union([shape(f['geometry']) for f in boundary_data['features']]).intersection(box(*bounds))
        if municipal_geometry.is_empty:
            result = _mapbiomas_result([], year, class_id, False, 30)
            storage.source_snapshot(key, result)
            return result
        # Read only the municipality visible in the viewport, not its neighbours.
        raster_bounds = municipal_geometry.bounds
    url = MAPBIOMAS_URL.format(year=year)
    features = []
    largest=[];candidate_number=0
    raster_started=time.perf_counter()
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_TIMEOUT='30', GDAL_HTTP_MAX_RETRY='1', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif'):
        with rasterio.open(url) as ds:
            from rasterio.windows import Window
            from rasterio.enums import Resampling
            window = from_bounds(*raster_bounds, ds.transform).round_offsets().round_lengths().intersection(Window(0,0,ds.width,ds.height))
            if window.width<1 or window.height<1: raise ValueError('Área visível pequena demais para pixels de 30 m.')
            factor = max(1, math.sqrt(window.width*window.height/1_000_000))
            width, height = max(1,int(window.width/factor)), max(1,int(window.height/factor))
            raster = ds.read(1,window=window,out_shape=(height,width),resampling=Resampling.nearest)
            raster_seconds=time.perf_counter()-raster_started
            processing_started=time.perf_counter()
            raster_transform = ds.window_transform(window) * ds.transform.scale(window.width/width,window.height/height)
            resolution_m = round(30*max(window.width/width,window.height/height))
            overview = factor > 1
            mask = raster==class_id
            for geometry,value in shapes(np.where(mask,1,0).astype('uint8'), mask=mask, transform=raster_transform):
                if municipal_geometry is not None:
                    clipped = shape(geometry).intersection(municipal_geometry)
                    if clipped.is_empty or clipped.geom_type not in ('Polygon','MultiPolygon'): continue
                    geometry = mapping(clipped)
                area_ha = shape(transform_geom(ds.crs,'EPSG:6933',geometry)).area/10000
                if area_ha < 5: continue
                simplified = mapping(shape(geometry).simplify(ds.res[0],preserve_topology=True)) if municipal_geometry is None else geometry
                feature={'type':'Feature','geometry':simplified,'properties':{'source':'MapBiomas','collection':11,'year':year,'class_id':class_id,'class_name':CLASSES[class_id],'resolution_m':resolution_m,'native_resolution_m':30,'overview':overview,'area_ha':round(area_ha,2),'source_url':url,'historical':True,'clipped_to_view':True}}
                candidate_number+=1
                candidate=(area_ha,candidate_number,feature)
                if len(largest)<200:heapq.heappush(largest,candidate)
                elif area_ha>largest[0][0]:heapq.heapreplace(largest,candidate)
    features=[item[2] for item in sorted(largest,reverse=True)]
    result = _mapbiomas_result(features, year, class_id, overview, resolution_m)
    result['candidate_count']=candidate_number
    result['selection']='até 200 maiores manchas da cultura no recorte visível; não é cobertura integral'
    result['timing']={'raster_seconds':round(raster_seconds,3),'processing_seconds':round(time.perf_counter()-processing_started,3),'total_seconds':round(time.perf_counter()-started,3)}
    storage.source_snapshot(key,result)
    return result

def municipal_landcover(boundary):
    """Count native pixels across the whole municipality in bounded memory tiles."""
    import numpy as np
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.windows import from_bounds, Window
    from rasterio.warp import transform
    from shapely.geometry import shape
    from shapely.ops import unary_union
    geometries=[f['geometry'] for f in boundary['features']]
    region=unary_union([shape(g) for g in geometries])
    totals={}; pixels=0
    url=MAPBIOMAS_URL.format(year=2025)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',GDAL_HTTP_TIMEOUT='30',GDAL_HTTP_MAX_RETRY='1',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif'):
        with rasterio.open(url) as ds:
            window=from_bounds(*region.bounds,ds.transform).round_offsets().round_lengths().intersection(Window(0,0,ds.width,ds.height))
            if window.width*window.height>350_000_000: raise ValueError('Município excede limite do piloto.')
            for row in range(0,int(window.height),512):
                for col in range(0,int(window.width),512):
                    tile=Window(window.col_off+col,window.row_off+row,min(512,int(window.width)-col),min(512,int(window.height)-row))
                    t=ds.window_transform(tile)
                    from shapely.geometry import box
                    if not region.intersects(box(t.c,t.f+t.e*tile.height,t.c+t.a*tile.width,t.f)): continue
                    values=ds.read(1,window=tile)
                    mask=geometry_mask(geometries,out_shape=values.shape,transform=t,invert=True)&(values!=0)
                    pixels+=int(mask.sum())
                    latitudes=[t.f+t.e*i for i in range(values.shape[0]+1)]
                    _,ys=transform(ds.crs,'EPSG:6933',[t.c]*len(latitudes),latitudes)
                    xs,_=transform(ds.crs,'EPSG:6933',[t.c,t.c+t.a],[0,0])
                    row_ha=np.abs(np.diff(ys))*abs(xs[1]-xs[0])/10000
                    for value in np.unique(values[mask]):
                        hectares=float(np.sum(np.sum(mask&(values==value),axis=1)*row_ha))
                        label=str(int(value)); totals[label]=totals.get(label,0)+hectares
    return {'source':'MapBiomas Coleção 11','source_url':url,'year':2025,'resolution_m':30,'scope':'municipality','valid_pixels':pixels,'classes':[{'class_id':int(k),'class_name':CLASSES.get(int(k),'Outra classe de cobertura'),'area_ha':round(v,2)} for k,v in sorted(totals.items(),key=lambda item:-item[1])],'fetched_at':storage.now(),'note':'Área estimada por pixels de 30 m dentro da malha simplificada IBGE; mapa histórico, não cadastro de talhões.'}

def municipal_soy_areas(code):
    """Read every native soybean pixel inside the municipality, without viewport caps."""
    from . import municipalities
    municipalities.key(code)
    key='municipal-soy:v1:'+code
    cached=storage.source_snapshot(key)
    if cached: return cached['result']
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds,Window
    from rasterio.features import geometry_mask,shapes
    from rasterio.warp import transform_geom
    from shapely.geometry import shape,mapping,box
    from shapely.ops import unary_union
    from .localities import fetch_ibge
    saved=storage.source_snapshot(municipalities.key(code))
    boundary=saved['result'].get('boundary') if saved else None
    if not boundary:
        boundary=fetch_ibge(f'/v3/malhas/municipios/{code}?formato=application/vnd.geo%2Bjson&qualidade=minima')
    geometries=[f['geometry'] for f in boundary['features']]
    region=unary_union([shape(g) for g in geometries])
    url=MAPBIOMAS_URL.format(year=2025)
    features=[];total=0
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',GDAL_HTTP_TIMEOUT='30',GDAL_HTTP_MAX_RETRY='1',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif'):
        with rasterio.open(url) as ds:
            window=from_bounds(*region.bounds,ds.transform).round_offsets().round_lengths().intersection(Window(0,0,ds.width,ds.height))
            if window.width*window.height>50_000_000: raise ValueError('Este município excede o limite de processamento municipal do piloto. Nenhuma amostra parcial foi usada como total da cidade.')
            raster=ds.read(1,window=window)
            transform=ds.window_transform(window)
            mask=(raster==39)&geometry_mask(geometries,out_shape=raster.shape,transform=transform,invert=True)
            for geometry,value in shapes(mask.astype('uint8'),mask=mask,transform=transform):
                clipped=shape(geometry).intersection(region)
                if clipped.is_empty: continue
                geometry=mapping(clipped)
                hectares=shape(transform_geom(ds.crs,'EPSG:6933',geometry)).area/10000
                total+=hectares
                if hectares<5: continue
                projected=shape(transform_geom(ds.crs,'EPSG:3857',geometry))
                west,south,east,north=projected.bounds
                if east-west<=10_000 and north-south<=10_000:
                    parts=[geometry]
                else:
                    # Computational recortes, never claimed as field boundaries.
                    parts=[]
                    for x in range(math.floor(west/10_000)*10_000,math.ceil(east),10_000):
                        for y in range(math.floor(south/10_000)*10_000,math.ceil(north),10_000):
                            piece=projected.intersection(box(x,y,x+10_000,y+10_000))
                            if piece.is_empty or piece.geom_type not in ('Polygon','MultiPolygon'):continue
                            parts.append(transform_geom('EPSG:3857',ds.crs,mapping(piece)))
                for part in parts:
                    part_ha=shape(transform_geom(ds.crs,'EPSG:6933',part)).area/10000
                    if part_ha<5:continue
                    features.append({'type':'Feature','geometry':part,'properties':{'source':'MapBiomas','class_id':39,'year':2025,'area_ha':part_ha,'overview':False}})
    result={'features':features,'total_soy_ha':total,'candidate_ha':sum(f['properties']['area_ha'] for f in features),'year':2025,'municipality_code':code,'source_url':url}
    storage.source_snapshot(key,result)
    return result

def satveg(data, token):
    if not token: raise ValueError('SATVeg aguarda token AgroAPI. Configure EMBRAPA_ACCESS_TOKEN no .env; nenhum dado foi simulado.')
    geometry = extract_geometry(data.get('geojson'))
    if geometry['type'] != 'Polygon' or len(geometry['coordinates'])!=1:
        raise ValueError('SATVeg nesta versão aceita um Polygon sem ilhas internas.')
    start,end = data.get('from'),data.get('to')
    if not isinstance(start,str) or not isinstance(end,str) or validate_date(end,'Data final')<validate_date(start,'Data inicial'):
        raise ValueError('Período SATVeg inválido.')
    ring=geometry['coordinates'][0]
    payload={'tipoPerfil':'ndvi','satelite':'comb','preFiltro':3,'todasEstatisticas':False,'poligono':','.join(f'{p[0]} {p[1]}' for p in ring)}
    result=json.loads(read_bytes(SATVEG_URL,payload,token))
    dates,values=result.get('listaDatas'),result.get('listaSerie')
    if not isinstance(dates,list) or not isinstance(values,list) or len(dates)!=len(values): raise ValueError('Resposta SATVeg inesperada.')
    points=[{'date':d[:10],'ndvi_mean':v} for d,v in zip(dates,values) if start<=d[:10]<=end and isinstance(v,(float,int)) and math.isfinite(v) and -1<=v<=1]
    return {'source':'Embrapa SATVeg MODIS','source_url':SATVEG_URL,'resolution_m':250,'aggregation_days':16,'points':points,'fetched_at':storage.now(),'note':'MODIS 250 m; não comparar diretamente seus valores com Sentinel-2 10 m.'}
