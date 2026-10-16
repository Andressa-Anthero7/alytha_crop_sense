"""Browser planting screening with mocked climate; no provider or image requests."""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import planting_readiness as planting
from test_planting_readiness import TODAY,GEOMETRY,NDVI,weather_fixture
from playwright.sync_api import sync_playwright


def main():
    base='http://127.0.0.1:8765';errors=[];requests=[];mode='normal';held=[]
    climate={**planting.normalize(weather_fixture(),TODAY),'cache':{'hit':True,'stale':False},
             'source':'Open-Meteo · teste simulado','requested_point':{'latitude':-12.5,'longitude':-55.8},
             'grid_point':{'latitude':-12.5,'longitude':-55.8},'documentation_url':planting.DOCS,'fetched_at':'2026-10-16T12:00:00+00:00'}
    def result_for(data,weather=climate):
        return {**planting.evaluate(weather,planting.field_inputs(data.get('field_inputs',{})),TODAY,NDVI),'geometry':data['geojson']['geometry']}
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':900})
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(r):
            if not r.request.url.startswith(base+'/'):r.abort();return
            path=urlsplit(r.request.url).path
            if not path.startswith('/api/'):r.continue_();return
            body=[]
            if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
            elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':False}}
            elif path=='/api/sources/status':body={'satveg_configured':False}
            elif path=='/api/planting-readiness':
                data=r.request.post_data_json;requests.append(data)
                if mode=='held':held.append((r,result_for(data)));return
                body=result_for(data,None if mode=='offline' else climate)
            r.fulfill(json=body)
        page.route('**/*',route);page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')
        page.locator('#panel-toggle').click();page.evaluate("document.getElementById('planting-panel').open=true")
        page.locator('#start-planting').click()
        assert 'Selecione uma área' in page.locator('#planting-status').inner_text()
        assert not requests
        page.evaluate('g=>selectAnalysisArea({type:"Feature",geometry:g,properties:{}},"Recorte de teste")',GEOMETRY)
        page.locator('#start-planting').click()
        page.wait_for_selector('.planting-verdict')
        assert page.locator('.planting-verdict').get_attribute('data-status')=='incomplete'
        assert 'Clima sem alerta; área ainda não confirmada' in page.locator('.planting-verdict').inner_text()
        assert 'profundidade da semente' in page.locator('.planting-next-step').inner_text()
        assert page.locator('.planting-evidence').get_attribute('open') is None
        assert not page.locator('[data-factor="zarc"]').is_visible()
        assert page.locator('[data-factor="zarc"]').get_attribute('data-status')=='missing'
        assert requests[-1]['geojson']['geometry']==GEOMETRY
        page.evaluate("document.querySelector('#planting-panel > details').open=true")
        for key,value in [('soil','adequate'),('drainage','adequate'),('fertility','verified'),('calendar','verified'),('zarc','verified')]:
            page.locator('#planting-'+key).select_option(value)
        assert page.locator('.planting-verdict').count()==0
        page.locator('#start-planting').click();page.wait_for_selector('.planting-verdict')
        assert page.locator('.planting-verdict').get_attribute('data-status')=='favorable'
        assert 'Condições avaliadas favoráveis ao plantio' in page.locator('.planting-verdict').inner_text()
        with page.expect_download() as download:page.get_by_role('button',name='Exportar avaliação JSON').click()
        exported=json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
        assert exported['field_inputs']['calendar']=='verified'
        assert exported['geometry']==GEOMETRY
        page.locator('#planting-soil').select_option('waterlogged')
        page.locator('#start-planting').click();page.wait_for_selector('.planting-verdict')
        assert page.locator('.planting-verdict').get_attribute('data-status')=='attention'
        assert 'Solo encharcado: condição desfavorável' in page.locator('.planting-verdict').inner_text()
        output=Path('data/outputs/planting-readiness');output.mkdir(parents=True,exist_ok=True)
        page.locator('.planting-verdict').scroll_into_view_if_needed()
        page.screenshot(path=str(output/'planting-desktop.png'))
        page.evaluate('g=>selectAnalysisArea({type:"Feature",geometry:g,properties:{}},"Outra área")',GEOMETRY)
        assert page.locator('.planting-verdict').count()==0
        assert page.locator('#planting-soil').input_value()=='unknown'
        assert page.locator('#planting-calendar').input_value()=='unknown'
        mode='offline';page.locator('#start-planting').click();page.wait_for_selector('.planting-verdict')
        assert page.locator('.planting-verdict').get_attribute('data-status')=='incomplete'
        assert page.locator('[data-factor="soil_temperature"]').get_attribute('data-status')=='missing'
        assert 'Ainda não dá para avaliar o clima' in page.locator('.planting-verdict').inner_text()
        mode='held';page.locator('#start-planting').click();page.wait_for_function("document.getElementById('start-planting').disabled")
        page.evaluate('g=>selectAnalysisArea({type:"Feature",geometry:g,properties:{}},"Nova área durante consulta")',GEOMETRY)
        for r,body in held:
            try:r.fulfill(json=body)
            except Exception:pass
        page.wait_for_timeout(100)
        assert page.locator('.planting-verdict').count()==0
        mode='normal';page.set_viewport_size({'width':390,'height':844})
        page.locator('#start-planting').click();page.wait_for_selector('.planting-verdict')
        page.locator('.planting-verdict').scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(output/'planting-mobile.png'))
        assert not errors,errors
        browser.close()
    print('PASS: area required, incomplete/favorable/attention, field declarations, reset, stale response, no weather, export and mobile. No provider requests.')


if __name__=='__main__':main()
