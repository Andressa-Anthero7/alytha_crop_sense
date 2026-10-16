"""Exercise a real HTTP 403 fallback with an isolated database and mocked provider."""
import io
import json
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import local_ndvi, storage, web_app
from playwright.sync_api import sync_playwright


def polygon(west, south, east, north):
    return {'type':'Polygon','coordinates':[[[west,south],[east,south],[east,north],[west,north],[west,south]]]}


def main():
    area=polygon(-55.1,-12.1,-55,-12)
    samples=[polygon(-55.09,-12.09,-55.08,-12.08),polygon(-55.03,-12.03,-55.02,-12.02)]
    denied=HTTPError('https://example.invalid',403,'Forbidden',{},io.BytesIO(json.dumps({
        'error':{'code':'ACCESS_INSUFFICIENT_PROCESSING_UNITS'}}).encode()))
    provider=Mock(side_effect=denied)
    errors=[];catalog_cache=[False]
    with tempfile.TemporaryDirectory() as temporary, \
         patch.object(storage,'DB_PATH',Path(temporary)/'base.sqlite3'), \
         patch.object(web_app,'read_app_env',return_value={'CDSE_CLIENT_ID':'test','CDSE_CLIENT_SECRET':'test'}), \
         patch.object(web_app,'request_ndvi_series',provider), \
         patch.multiple(local_ndvi,BLOCKED_UNTIL=0,BLOCKED_REASON=''):
        for index, geometry in enumerate(samples):
            storage.source_snapshot('history:'+str(index),{'parameters':{'geometry':geometry},'points':[
                {'date':'2026-10-'+day,'ndvi_mean':.2+index*.4,'valid_pixels':100,'valid_fraction':.9}
                for day in ('01','06')]})
        server=web_app.ThreadingHTTPServer(('127.0.0.1',0),web_app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':768})
                page.on('pageerror',lambda error:errors.append(str(error)))
                def route(r):
                    path=urlsplit(r.request.url).path
                    if not r.request.url.startswith(base+'/'):r.abort();return
                    if not path.startswith('/api/') or path=='/api/ndvi-series':r.continue_();return
                    body=[]
                    if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
                    elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':False,'provider':'Gemini'}}
                    elif path=='/api/sources/status':body={'satveg_configured':False}
                    elif path=='/api/search':
                        body={'type':'FeatureCollection','features':[
                            {'type':'Feature','geometry':geometry,'properties':{'datetime':'2026-10-01T00:00:00Z'},'id':str(i)}
                            for i,geometry in enumerate(samples)]}
                        if catalog_cache[0]:body.update(mode='local_cache',message='Catálogo indisponível. Exibindo cenas já salvas desta mesma área, período e limite de nuvens.')
                    r.fulfill(json=body)
                page.route('**/*',route);page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')
                page.evaluate("geometry=>selectAnalysisArea({type:'Feature',geometry,properties:{}},'Área de teste')",area)
                page.locator('#date-from').fill('2026-10-01');page.locator('#date-to').fill('2026-10-08')
                assert page.locator('#ndvi-button').is_enabled(), 'Local consultation must work without configured credentials.'
                page.locator('#ndvi-button').click()
                page.wait_for_function("document.getElementById('ndvi-local-message').textContent.includes('Cota de processamento')")
                assert 'não representa toda a área' in page.locator('#ndvi-local-message').inner_text()
                assert page.locator('#ndvi-local-series option').count()==2
                assert page.evaluate('map.hasLayer(ndviReferenceLayer)')
                first=page.evaluate('ndviReferenceLayer.toGeoJSON()')
                page.locator('#ndvi-local-series').select_option('1')
                assert page.evaluate('ndviReferenceLayer.toGeoJSON()')!=first
                assert 'borda roxa' in page.locator('#ndvi-local-scope').inner_text()
                provider.assert_called_once()
                page.locator('#ndvi-button').click()
                page.wait_for_function("!document.getElementById('ndvi-button').disabled")
                provider.assert_called_once()
                page.wait_for_function("map.latLngToContainerPoint(ndviReferenceLayer.getBounds().getSouthWest()).y < document.getElementById('ai-prompt-panel').getBoundingClientRect().top-document.getElementById('map').getBoundingClientRect().top")
                output=Path('data/outputs/local-ndvi');output.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(output/'quota-fallback.png'))

                page.locator('#date-from').fill('2026-09-01');page.locator('#date-to').fill('2026-09-08')
                page.locator('#ndvi-button').click()
                page.wait_for_function("!document.getElementById('ndvi-local-period').hidden")
                assert 'Não há leituras NDVI salvas' in page.locator('#ndvi-local-message').inner_text()
                page.locator('#ndvi-local-period').click()
                page.wait_for_function("document.getElementById('ndvi-local-series').options.length===2 && !document.getElementById('ndvi-button').disabled")
                assert page.locator('#date-to').input_value()=='2026-10-06'
                provider.assert_called_once()

                page.locator('#ndvi-panel-close').click();page.locator('#search').click()
                page.wait_for_function("document.getElementById('status').textContent.includes('2 cena(s)')")
                assert page.locator('#scene-footprints-control').is_visible()
                assert not page.evaluate('map.hasLayer(scenesLayer)')
                page.locator('#scene-footprints').check()
                assert page.evaluate('map.hasLayer(scenesLayer)')
                page.locator('#scene-footprints').uncheck()
                assert not page.evaluate('map.hasLayer(scenesLayer)')
                catalog_cache[0]=True;page.locator('#search').click()
                page.wait_for_function("document.getElementById('status').textContent.includes('Exibindo cenas já salvas')")
                assert not page.locator('#status').evaluate("node=>node.classList.contains('error')")
                assert not errors,errors
                browser.close()
        finally:
            server.shutdown();server.server_close();thread.join()
    print('PASS: real HTTP quota fallback, sample selection, date gaps, local-only retry and optional scene boundaries. No external requests.')


if __name__=='__main__':main()
