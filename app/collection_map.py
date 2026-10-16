"""Prepare IBGE municipal boundaries for the read-only collection dashboard."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .localities import fetch_ibge,BASE
from .regional_batch import OUTPUT,STATES,write,now


def prepare(output=OUTPUT,destination=None):
    output=Path(output)
    roster={}
    for code,uf in STATES:
        for city in json.loads((output/f'roster-{uf}.json').read_text(encoding='utf-8'))['municipalities']:
            roster[str(city['id'])]={'code':str(city['id']),'name':city['nome'],'uf':uf}
    def fetch(state):
        code,uf=state
        path=f'/v3/malhas/estados/{code}?intrarregiao=municipio&formato=application/vnd.geo%2Bjson&qualidade=minima'
        data=fetch_ibge(path)
        return data['features'],BASE+path
    features=[];sources=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for items,source in pool.map(fetch,STATES):
            sources.append(source)
            for feature in items:
                code=str(feature.get('properties',{}).get('codarea',''))
                if code in roster:
                    features.append({'type':'Feature','geometry':feature['geometry'],'properties':roster[code]})
    present={f['properties']['code'] for f in features}
    missing=[item for code,item in roster.items() if code not in present]
    result={'type':'FeatureCollection','features':features,'metadata':{'prepared_at':now(),'source':'IBGE · malhas simplificadas',
            'source_urls':sources,'expected':len(roster),'mapped':len(present),'missing':missing}}
    write(Path(destination or Path(__file__).resolve().parents[1]/'web/collection-map.geojson'),result)
    return result['metadata']


if __name__=='__main__':print(json.dumps(prepare(),ensure_ascii=False,indent=2))
