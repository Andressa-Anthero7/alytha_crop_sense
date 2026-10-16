"""Browser verification of a synthetic directional front; no provider calls or writes."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from rasterio.transform import from_origin
from rasterio.warp import transform_geom
from playwright.sync_api import sync_playwright
from app import spatial_activity,evolution_index


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8765')
    base=parser.parse_args().url.rstrip('/')
    grid={'mask':np.ones((30,30),dtype=bool),'crs':'EPSG:32721','transform':from_origin(500000,8600000,10,10),'width':30,'height':30}
    cube=np.full((3,30,30),.2,dtype=np.float32);cube[1,:,:15]=.6;cube[2,:,:]=.7
    result=spatial_activity.analyze_pixels([(image,np.ones((30,30),dtype=bool)) for image in cube],grid)
    geometry=transform_geom(grid['crs'],'EPSG:4326',{'type':'Polygon','coordinates':[[[500000,8599700],[500300,8599700],[500300,8600000],[500000,8600000],[500000,8599700]]]})
    periods=[{'from':'2026-09-18','to':'2026-09-22'},{'from':'2026-09-23','to':'2026-09-27'},{'from':'2026-10-03','to':'2026-10-07'}]
    result['progression']['periods']=periods
    job={**result,'id':'a'*64,'periods':periods,'parameters':{'geometry':geometry,'scope':'Área sintética de teste'},'processed':3,'total':3}
    comparison={'current':{'usable':True,'slope_day':.006,'observations':6,'mean_observed_fraction':1,'last_observation':'2026-10-13','trend':'aumento'}}
    history={'id':'f'*64,'points':[{'date':'2026-10-03'}],'parameters':{'geometry':geometry,'municipality_code':'5107925','as_of':'2026-10-13','start_year':2018,'end_year':2026,'area_key':'fixture'}}
    index=evolution_index.calculate(history,'2026-10-13',comparison,job)
    report={'status':'ready','as_of':'2026-10-13','geometry':geometry,'geojson':job['change_geojson'],'progression':job['progression'],
            'evolution_index':index,'spatial':job,'note':'Teste sintético, sem validação agronômica.',
            'what_changed':'Vegetação em aumento.','where_changed':'Recorte sintético.','priority':'Acompanhar','next_signal':'Conferir no campo.'}
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':768});errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(request):
            url=request.request.url
            if not url.startswith(base):request.abort();return
            if '/api/' not in url:request.continue_();return
            body=[]
            if '/api/config' in url:body={'google_maps_api_key':'','ndvi_configured':False}
            elif '/api/research/status' in url:body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':False}}
            elif '/api/sources/status' in url:body={'satveg_configured':False}
            elif '/api/spatial-activity' in url:body=job
            elif '/api/crop-monitoring' in url:body=report
            request.fulfill(json=body)
        page.route('**/*',route);page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')
        page.evaluate('(g)=>selectAnalysisArea({type:"Feature",properties:{},geometry:g},"Teste de direção")',geometry)
        page.locator('#panel-toggle').click()
        page.evaluate('document.getElementById("spatial-panel").open=true')
        page.locator('#start-spatial-analysis').click()
        page.wait_for_function('document.getElementById("spatial-results").textContent.includes("leste")')
        assert page.locator('#spatial-results').inner_text().find('Plantio e colheita')>=0
        assert 'Aumento de vegetação' in page.locator('#spatial-status').inner_text()
        assert 'bloco regular' in page.locator('#spatial-results').inner_text()
        assert page.evaluate("Object.values(map._layers).filter(l=>l.feature).every(l=>l.feature.properties.signal!=='persistent_low_vegetation')")
        page.locator('#spatial-view').select_option('sequence')
        assert page.evaluate("new Set(Object.values(map._layers).map(l=>l.feature?.properties.growth_stage).filter(Boolean)).size===2")
        assert 'Verde claro' in page.locator('#spatial-map-legend').inner_text()
        from pathlib import Path
        output=Path('data/outputs/vegetation-growth');output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/'organized-growth-synthetic.png'))
        with page.expect_download() as download:page.locator('#spatial-results a').click()
        import json
        with open(download.value.path(),encoding='utf-8') as stream:exported=json.load(stream)
        assert any(f['geometry']['type']=='MultiLineString' for f in exported['features'])
        assert page.evaluate('Object.values(map._layers).some(l=>l.feature?.properties.progression)')
        page.evaluate('(h)=>{document.dispatchEvent(new CustomEvent("alytha-history-ready",{detail:h}));document.getElementById("research-panel").open=true;}',history)
        page.locator('#start-crop-monitoring').click()
        page.wait_for_function('document.querySelectorAll(".evolution-score").length===2')
        assert page.locator('.evolution-score progress').first.get_attribute('value')=='80'
        assert '/ 100 pontos' in page.locator('.evolution-score').first.inner_text()
        page.locator('.evolution-score details').first.evaluate('(el)=>el.open=true')
        assert 'não avaliado' in page.locator('.evolution-score').first.inner_text()
        assert not errors,errors
        browser.close()
    print('PASS: eastward arrow on Leaflet, experimental interpretation and direction export.')


if __name__=='__main__':main()
