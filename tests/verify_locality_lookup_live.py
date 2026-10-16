"""Use real locality endpoints in Chromium, isolating collection side effects."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8765');args=parser.parse_args()
    base=args.url.rstrip('/');lookups=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':768})
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(r):
            url=r.request.url;path=urlsplit(url).path
            if not url.startswith(base+'/'):r.abort();return
            if '/api/' not in path:r.continue_();return
            if path.startswith('/api/locations/'):
                lookups.append(path)
                r.continue_();return
            if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
            elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':False,'provider':'Gemini'}}
            elif path=='/api/sources/status':body={'satveg_configured':False}
            elif path=='/api/municipalities/5107925':body={'status':'ready','name':'Sorriso','uf':'MT','sources':{}}
            elif path=='/api/regional-scans':body={'id':'a'*64,'status':'ready','processed':0,'total':0,'cities':[],
                                                 'parameters':{'as_of':'2026-10-15','kind':'municipality','code':'5107925'}}
            else:body=[]
            r.fulfill(json=body)
        page.route('**/*',route)
        page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')
        page.locator('#location-search').fill('sorri')
        page.wait_for_function("!document.getElementById('location-matches').hidden && document.querySelector('#location-options button')?.textContent.includes('Sorriso / MT')")
        assert 'municipio=' not in page.url
        page.locator('#location-options button',has_text='Sorriso / MT').click()
        page.wait_for_function("document.getElementById('municipality-select').value==='5107925' && document.getElementById('region-status').textContent.includes('Limite IBGE exibido')",timeout=30000)
        assert page.locator('#state-select').input_value()=='51'
        assert page.locator('#location-search').input_value()=='Sorriso / MT'
        assert 'municipio=5107925' in page.url
        page.wait_for_function("document.getElementById('map-loading').hidden")
        assert page.locator('#region-boundary-label').is_visible()
        assert 'Sorriso' in page.locator('#region-boundary-label').inner_text()
        boundary=page.evaluate("""() => {
          const bounds=regionLayer.getBounds(),northEast=map.latLngToContainerPoint(bounds.getNorthEast()),
            southWest=map.latLngToContainerPoint(bounds.getSouthWest());
          const canvas=document.getElementById('map').getBoundingClientRect();
          const chat=document.getElementById('ai-prompt-panel').getBoundingClientRect();
          const overlay=L.geoJSON(regionLayer.toGeoJSON(),{style:{fillOpacity:1,color:'#269b65'}}).addTo(map);
          const visible={north:northEast.y,south:southWest.y,east:northEast.x,west:southWest.x,
            width:canvas.width,height:canvas.height,chatTop:chat.top-canvas.top,
            aboveCrops:Number(getComputedStyle(map.getPane('region-boundary')).zIndex)>Number(getComputedStyle(map.getPane('overlayPane')).zIndex),
            boundaryPresent:map.hasLayer(regionLayer)};
          overlay.remove();return visible;
        }""")
        assert boundary['boundaryPresent'] and boundary['aboveCrops']
        assert 0<=boundary['west']<boundary['east']<=boundary['width']
        assert 0<=boundary['north']<boundary['south']<min(boundary['height'],boundary['chatTop'])
        assert not errors,errors
        output=Path('data/outputs/localities');output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/'sorriso-search.png'),full_page=True)
        report={'query':'sorri','selection_mode':'autocomplete','city':'Sorriso / MT','code':'5107925','url':page.url,
                'real_locality_endpoints':lookups,'boundary_visibility':boundary,
                'console_errors':errors,'collection_requests_isolated':True}
        (output/'browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        browser.close();print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
