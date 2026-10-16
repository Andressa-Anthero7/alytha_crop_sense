"""End-to-end state crop commands with synthetic APIs, no remote raster downloads."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from unittest.mock import patch
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from app import assistant,assistant_tools


def main():
    base='http://127.0.0.1:8765'
    state={'kind':'state','code':'52','name':'Goiás','uf':'GO'}
    city={'kind':'municipality','code':'5215652','name':'Palestina de Goiás','uf':'GO'}
    boundary={'type':'FeatureCollection','features':[{'type':'Feature','properties':{},
        'geometry':{'type':'Polygon','coordinates':[[[-50,-17],[-48,-17],[-48,-15],[-50,-15],[-50,-17]]]}}]}
    crop={'type':'Feature','properties':{'class_id':39,'class_name':'Soja','area_ha':100,'historical':True,'year':2025},
          'geometry':{'type':'Polygon','coordinates':[[[-49.2,-16.5],[-49.1,-16.5],[-49.1,-16.4],[-49.2,-16.4],[-49.2,-16.5]]]}}
    requests=[];assistant_requests=[];failures={'crop':False,'delay':True}
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':768});errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(r):
            if not r.request.url.startswith(base):r.abort();return
            path=urlsplit(r.request.url).path
            if '/api/' not in path:r.continue_();return
            body=[]
            if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
            elif path=='/api/locations/states':body=[{'id':52,'nome':'Goiás','sigla':'GO'}]
            elif path=='/api/locations/states/52/municipalities':body=[{'id':5208707,'nome':'Goiânia'},{'id':5215652,'nome':'Palestina de Goiás'}]
            elif path.startswith('/api/locations/boundaries/'):body=boundary
            elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':True,'provider':'Gemini'}}
            elif path=='/api/sources/status':body={'satveg_configured':False}
            elif path=='/api/assistant':
                assistant_requests.append(r.request.post_data_json)
                def lookup(query):
                    return {'exact':True,'matches':[city] if query=='palestina de goias' else [state,{'kind':'municipality','code':'5208905','name':'Goiás','uf':'GO'}]}
                with patch.object(assistant_tools.localities,'search',side_effect=lookup):
                    body=assistant.ask(r.request.post_data_json,{})
            elif path.startswith('/api/municipalities/'):body={'status':'ready','sources':{},'name':city['name'],'uf':'GO','boundary':boundary}
            elif path=='/api/regional-scans':body={'id':'a'*64,'status':'ready','processed':0,'total':0,'cities':[],'parameters':{'code':'52'}}
            elif path.startswith('/api/sources/mapbiomas/jobs'):
                if r.request.method=='POST':requests.append(r.request.post_data_json)
                if failures['crop']:
                    r.fulfill(status=502,json={'error':'Fonte indisponível no teste'});return
                if failures['delay']:
                    r.fulfill(json={'id':'b'*64,'status':'loading','phase':'waiting'});return
                body={'id':'b'*64,'status':'ready','result':{'type':'FeatureCollection','features':[crop],'year':2025,'class_name':'Soja','overview':True,'resolution_m':300}}
            r.fulfill(json=body)
        page.route('**/*',route);page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')
        if page.locator('#ai-prompt-panel').is_hidden():page.locator('#ai-mode-toggle').click()
        for prompt in ('soja em goias','oja em goias'):
            page.locator('#ai-prompt').fill(prompt);page.locator('#ai-prompt-submit').click()
            if failures['delay']:
                try:
                    page.wait_for_function("document.getElementById('map-loading-message').textContent.includes('Consulta na fila')",timeout=10000)
                except Exception:
                    print(page.evaluate("({message:document.getElementById('map-loading-message').textContent,reply:document.getElementById('ai-prompt-status').textContent,wanted:[...cropWanted],requests:cropRequest})"),errors,requests)
                    raise
                assert page.locator('#map-loading').is_visible()
                assert page.locator('#map-loading').get_attribute('aria-busy')=='true'
                failures['delay']=False
            page.wait_for_function("document.querySelector('#ai-prompt-status > .ai-turn-assistant:last-child')?.textContent.includes('Carreguei')")
            assert page.locator('#state-select').input_value()=='52'
            assert page.locator('input[name="map-crop"][value="39"]').is_checked()
            assert page.evaluate('agriculturalFeatures.length')==1
            assert page.locator('#map-loading').get_attribute('data-state')=='ready'
            assert requests[-1]['state_code']=='52' and not requests[-1].get('municipality_code')
            page.wait_for_function("!document.getElementById('ai-prompt-submit').disabled")
        page.locator('#ai-prompt').fill('E comparado com a safra anterior?')
        page.locator('#ai-prompt-submit').click()
        page.wait_for_function("document.querySelector('#ai-prompt-status > .ai-turn-assistant:last-child')?.textContent.includes('Continuamos em')")
        payload=assistant_requests[-1]
        assert payload['state_code']=='52' and not payload['municipality_code']
        assert payload['crop_class_ids']==[39]
        assert payload['conversation'][-1]['question']=='oja em goias'
        assert 'Goiás' in page.locator('#ai-prompt-status').inner_text()
        page.wait_for_function("!document.getElementById('ai-prompt-submit').disabled")
        page.locator('#ai-prompt').fill('vc nao destaco no mapa, nao apareceu')
        page.locator('#ai-prompt-submit').click()
        page.wait_for_function("document.querySelector('#ai-prompt-status > .ai-turn-assistant:last-child')?.textContent.includes('estão visíveis')")
        assert page.evaluate('map.hasLayer(agriculturalLayer)')
        page.wait_for_function("!document.getElementById('ai-prompt-submit').disabled")
        page.locator('#ai-prompt').fill('palestina de goias')
        page.locator('#ai-prompt-submit').click()
        page.wait_for_function("document.querySelector('#ai-prompt-status > .ai-turn-assistant:last-child')?.textContent.includes('Carreguei') && new URL(location.href).searchParams.get('municipio')==='5215652'")
        assert page.locator('#municipality-select').input_value()=='5215652'
        assert requests[-1]['municipality_code']=='5215652' and not requests[-1].get('state_code')
        assert page.locator('input[name="map-crop"][value="39"]').is_checked()
        page.wait_for_function("!document.getElementById('ai-prompt-submit').disabled")
        failures['crop']=True;page.evaluate('cropDataCache.clear()')
        page.locator('#ai-prompt').fill('nao apareceu nada no mapa')
        page.locator('#ai-prompt-submit').click()
        page.wait_for_function("document.querySelector('#ai-prompt-status > .ai-turn-assistant:last-child')?.textContent.includes('Fonte indisponível no teste')")
        assert page.locator('#map-loading').is_visible()
        assert page.locator('#map-loading').get_attribute('data-state')=='error'
        assert page.locator('#map-loading').get_attribute('aria-busy')=='false'
        assert 'estão visíveis' not in page.locator('#ai-prompt-status .ai-turn-assistant').last.inner_text()
        assert not errors,errors
        browser.close();print('State + soy + follow-up + bare municipality navigation: OK')


if __name__=='__main__':main()
