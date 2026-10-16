"""Render real cached Goiás polygons in Chromium, without new satellite/raster requests."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from app import storage,localities


def main():
    base='http://127.0.0.1:8765'
    with storage.connect() as db:
        row=db.execute("SELECT result FROM source_snapshots WHERE cache_key LIKE 'crop-map:v1:%' AND json_extract(result,'$.parameters.state_code')='52' AND json_extract(result,'$.parameters.class_id')=39 AND json_extract(result,'$.status')='ready' ORDER BY fetched_at DESC LIMIT 1").fetchone()
    if not row:raise ValueError('Nenhuma camada real de Goiás salva.')
    job=json.loads(row['result'])
    if 'candidate_count' not in job['result']:raise ValueError('A camada com seleção das maiores manchas ainda não terminou.')
    boundary=localities.location_data('/api/locations/boundaries/states/52')
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':900});errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(r):
            if not r.request.url.startswith(base):r.abort();return
            path=urlsplit(r.request.url).path
            if '/api/' not in path:r.continue_();return
            if path=='/api/assistant':r.continue_();return
            body=[]
            if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
            elif path=='/api/locations/states':body=[{'id':52,'nome':'Goiás','sigla':'GO'}]
            elif path=='/api/locations/states/52/municipalities':body=[]
            elif path.startswith('/api/locations/boundaries/'):body=boundary
            elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':True,'provider':'Gemini'}}
            elif path=='/api/sources/status':body={'satveg_configured':False}
            elif path=='/api/regional-scans':body={'id':'a'*64,'status':'ready','processed':0,'total':0,'cities':[],'parameters':{'code':'52'}}
            elif path=='/api/sources/mapbiomas/jobs':body=job
            r.fulfill(json=body)
        page.route('**/*',route);page.goto(base+'/?estado=52',wait_until='domcontentloaded')
        page.wait_for_function("mapReady && document.getElementById('state-select').value==='52'")
        if page.locator('#ai-prompt-panel').is_hidden():page.locator('#ai-mode-toggle').click()
        page.locator('#ai-prompt').fill('soja em goias');page.locator('#ai-prompt-submit').click()
        page.wait_for_function("document.querySelector('#ai-prompt-status > .ai-turn-assistant:last-child')?.textContent.includes('Carreguei')",timeout=60000)
        assert page.evaluate('map.hasLayer(agriculturalLayer)')
        assert page.evaluate('agriculturalFeatures.length')==len(job['result']['features'])
        visible=page.evaluate('agriculturalLayer.getLayers().filter(l=>map.getBounds().intersects(l.getBounds())).length')
        assert visible>0
        page.wait_for_function("!document.getElementById('ai-prompt-submit').disabled")
        page.locator('#ai-prompt').fill('vc nao destaco no mapa, nao apareceu');page.locator('#ai-prompt-submit').click()
        page.wait_for_function("document.querySelector('#ai-prompt-status > .ai-turn-assistant:last-child')?.textContent.includes('estão visíveis')",timeout=60000)
        assert page.evaluate('map.hasLayer(agriculturalLayer)')
        assert not errors,errors
        output=Path('data/outputs/assistant');output.mkdir(parents=True,exist_ok=True)
        page.locator('.map-card').screenshot(path=str(output/'goias-soja-real.png'),animations='disabled')
        print(json.dumps({'real_polygons':len(job['result']['features']),'candidate_count':job['result']['candidate_count'],'polygons_in_view':visible,'layer_attached':True,'screenshot':str(output/'goias-soja-real.png')}))
        browser.close()


if __name__=='__main__':main()
