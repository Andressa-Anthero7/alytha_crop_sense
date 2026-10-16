"""Numerical Sentinel-2 rasters on a fixed local metric grid."""
import hashlib
import json
import math
import threading
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]/'data/rasters'
LOCK = threading.Lock()
EVALSCRIPT = '''//VERSION=3
function setup() {
  return {input: [{bands: ["B04", "B08", "SCL", "dataMask"]}],
          output: {bands: 2, sampleType: "FLOAT32"}};
}
function evaluatePixel(s) {
  const d = s.B08 + s.B04;
  const valid = s.dataMask && d > 0 && [2,4,5,7].includes(s.SCL);
  return [valid ? (s.B08-s.B04)/d : 0, valid ? 1 : 0];
}'''


def grid_for(geometry):
    import numpy as np
    from shapely.geometry import shape
    from rasterio.warp import transform_geom
    from rasterio.features import geometry_mask
    from rasterio.transform import from_origin
    area = shape(geometry)
    if area.is_empty or not area.is_valid:
        raise ValueError('Selecione uma geometria válida para a análise espacial.')
    bounds = area.bounds
    if not all(math.isfinite(v) for v in bounds) or not (-180 <= bounds[0] <= bounds[2] <= 180 and -80 <= bounds[1] <= bounds[3] <= 84):
        raise ValueError('Coordenadas fora dos limites para a análise espacial.')
    longitude, latitude = area.centroid.coords[0]
    zone = min(60,max(1,int((longitude+180)//6)+1))
    crs = f'EPSG:{(32600 if latitude>=0 else 32700)+zone}'
    projected = transform_geom('EPSG:4326',crs,geometry)
    west,south,east,north = shape(projected).bounds
    west,south = math.floor(west/10)*10,math.floor(south/10)*10
    east,north = math.ceil(east/10)*10,math.ceil(north/10)*10
    width,height = round((east-west)/10),round((north-south)/10)
    if not 1 <= width <= 2000 or not 1 <= height <= 2000 or width*height>2_000_000:
        raise ValueError('Selecione um recorte menor: a análise mantém os pixels de 10 m, sem reduzir o detalhe.')
    transform = from_origin(west,north,10,10)
    mask = geometry_mask([projected],out_shape=(height,width),transform=transform,invert=True)
    if np.count_nonzero(mask)<50:
        raise ValueError('A área precisa conter pelo menos 50 pixels de 10 m para esta análise.')
    return {'crs':crs,'bounds':[west,south,east,north],'width':width,'height':height,'transform':transform,'mask':mask}


def read_raster(path, grid):
    import numpy as np
    import rasterio
    with rasterio.open(path) as dataset:
        if dataset.count!=2 or dataset.width!=grid['width'] or dataset.height!=grid['height'] or dataset.crs!=rasterio.crs.CRS.from_string(grid['crs']) or not dataset.transform.almost_equals(grid['transform']):
            raise ValueError('A imagem não corresponde à grade geográfica solicitada.')
        ndvi,quality = dataset.read()
        valid = grid['mask'] & (quality>.5) & np.isfinite(ndvi) & (ndvi>=-1) & (ndvi<=1)
    return ndvi,valid


def cache_path(geometry,grid,period):
    key = hashlib.sha256(json.dumps({'geometry':geometry,'crs':grid['crs'],'bounds':grid['bounds'],'period':period,'evalscript':EVALSCRIPT},sort_keys=True).encode()).hexdigest()
    return ROOT/(key+'.tif')


def fetch(geometry, grid, period):
    from .web_app import get_cdse_access_token
    ROOT.mkdir(parents=True,exist_ok=True)
    path = cache_path(geometry,grid,period)
    with LOCK:
        if path.is_file():return read_raster(path,grid)
        payload = {'input':{'bounds':{'bbox':grid['bounds'],'properties':{'crs':'http://www.opengis.net/def/crs/EPSG/0/'+grid['crs'].split(':')[1]}},
                            'data':[{'type':'sentinel-2-l2a','dataFilter':{'timeRange':{'from':period['from']+'T00:00:00Z','to':period['to']+'T23:59:59Z'},'maxCloudCoverage':80,'mosaickingOrder':'leastCC'}}]},
                   'output':{'width':grid['width'],'height':grid['height'],'responses':[{'identifier':'default','format':{'type':'image/tiff'}}]},'evalscript':EVALSCRIPT}
        from . import cdse_access
        request = Request('https://sh.dataspace.copernicus.eu/process/v1',data=json.dumps(payload).encode(),
                          headers={'Content-Type':'application/json','Accept':'image/tiff'},method='POST')
        with cdse_access.RATE.open(request,urlopen,prepare=lambda req:req.add_header('Authorization','Bearer '+get_cdse_access_token())) as response:
            binary = response.read(20_000_001)
        if len(binary)>20_000_000:raise ValueError('A imagem excedeu o limite de processamento deste recorte.')
        temporary = path.with_suffix('.tmp')
        try:
            temporary.write_bytes(binary)
            result = read_raster(temporary,grid)
            temporary.replace(path)
            return result
        finally:
            temporary.unlink(missing_ok=True)
