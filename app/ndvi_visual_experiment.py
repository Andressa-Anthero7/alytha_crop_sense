"""Compare conventional display interpolation without modifying numerical NDVI."""
import argparse
import hashlib
import json
from pathlib import Path
from . import storage

ROOT=Path(__file__).resolve().parents[1]


def generate(path, output_root=None):
    import numpy as np
    import rasterio
    from PIL import Image, ImageDraw
    path=Path(path).resolve();before=hashlib.sha256(path.read_bytes()).hexdigest()
    with rasterio.open(path) as raster:
        if raster.count!=2 or raster.width*raster.height>2_000_000:
            raise ValueError('Use um raster local NDVI + máscara, com até dois milhões de pixels.')
        ndvi,mask=raster.read();valid=(mask>.5)&np.isfinite(ndvi)&(ndvi>=-1)&(ndvi<=1)
        crs=str(raster.crs);transform=list(raster.transform)
    colors=np.array([[120,75,50],[220,165,60],[240,220,100],[110,165,65],[15,95,45]],dtype=float)
    t=np.clip((np.nan_to_num(ndvi,nan=0,posinf=1,neginf=-1)+1)*2,0,4)
    lo=np.floor(t).astype(int);hi=np.minimum(lo+1,4);a=(t-lo)[...,None]
    rgb=np.round(colors[lo]*(1-a)+colors[hi]*a).astype('uint8');rgb[~valid]=128
    native=Image.fromarray(rgb)
    scale=min(4,1200/max(native.size));size=tuple(max(1,round(x*scale)) for x in native.size)
    enlarged_mask=np.array(Image.fromarray((valid*255).astype('uint8')).resize(size,Image.Resampling.NEAREST))>0
    folder=Path(output_root or ROOT/'data/outputs/experiments/ndvi')/before
    folder.mkdir(parents=True,exist_ok=True)
    native.save(folder/'native.png')
    canvas=Image.new('RGB',(size[0]*3,size[1]+75),(248,248,243));draw=ImageDraw.Draw(canvas)
    for i,(label,method) in enumerate([('Nearest (native pixels)',Image.Resampling.NEAREST),
                                      ('Bilinear (display only)',Image.Resampling.BILINEAR),
                                      ('Bicubic (display only)',Image.Resampling.BICUBIC)]):
        image=np.array(native.resize(size,method));image[~enlarged_mask]=128
        pane=Image.fromarray(image);pane.save(folder/(('nearest','bilinear','bicubic')[i]+'.png'))
        canvas.paste(pane,(i*size[0],75));draw.text((i*size[0]+5,8),label,fill=(0,0,0))
    draw.text((5,30),'NDVI palette -1..1 | Gray = missing | No AI super-resolution',fill=(0,0,0))
    draw.text((5,48),'Interpolation changes display appearance; original raster remains the analytical source.',fill=(0,0,0))
    canvas.save(folder/'comparison.png')
    after=hashlib.sha256(path.read_bytes()).hexdigest()
    if before!=after:raise ValueError('O arquivo original mudou durante o experimento.')
    report={'version':1,'created_at':storage.now(),'source':str(path),'source_sha256_before':before,
        'source_sha256_after':after,'native_size':list(native.size),'display_size':list(size),
        'crs':crs,'transform':transform,'valid_pixels':int(valid.sum()),
        'original_ndvi_min':float(ndvi[valid].min()) if valid.any() else None,
        'original_ndvi_max':float(ndvi[valid].max()) if valid.any() else None,
        'numerical_values_preserved':True,'ai_super_resolution':False,
        'methods':['nearest','bilinear_rgb','bicubic_rgb'],'mask_display':'nearest; reapplied after interpolation',
        'note':'Comparação de aparência e legibilidade. Suavização não acrescenta detalhes observados nem identifica palhada ou linhas de plantio.'}
    (folder/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return {**report,'folder':str(folder)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--raster',type=Path)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    path=args.raster or next(iter(sorted((ROOT/'data/rasters').glob('*.tif'))),None)
    if path is None:parser.error('Nenhum raster local disponível.')
    result=generate(path,args.output);print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
