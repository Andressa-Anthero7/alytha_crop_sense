"""Browser file drops and picker imports, with collection APIs fully isolated."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8765')
    base=parser.parse_args().url.rstrip('/')
    fixture=json.loads(Path('data/sample-field.geojson').read_text(encoding='utf-8'))
    errors=[];queries=[]
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':768})
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(r):
            path=urlsplit(r.request.url).path
            if not r.request.url.startswith(base+'/'):r.abort();return
            if not path.startswith('/api/'):r.continue_();return
            body=[]
            if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
            elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':False,'provider':'Gemini'}}
            elif path=='/api/sources/status':body={'satveg_configured':False}
            elif path=='/api/ndvi-series':queries.append(r.request.post_data_json);body={'points':[]}
            r.fulfill(json=body)
        page.route('**/*',route);page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')

        def transfer(files):
            return page.evaluate_handle("""files=>{
              const data=new DataTransfer();
              for(const file of files)data.items.add(new File([file.content],file.name,{type:file.type || 'application/geo+json'}));
              return data;
            }""",files)

        def drop(files,target='#map'):
            data=transfer(files)
            page.dispatch_event(target,'dragenter',{'dataTransfer':data})
            page.dispatch_event(target,'dragover',{'dataTransfer':data})
            page.dispatch_event(target,'drop',{'dataTransfer':data})
            data.dispose()

        data=transfer([{'name':'teste.geojson','content':json.dumps(fixture)}])
        page.dispatch_event('#map','dragenter',{'dataTransfer':data})
        assert page.locator('#geojson-drop-overlay').is_visible()
        page.dispatch_event('#map-label','dragenter',{'dataTransfer':data})
        page.dispatch_event('#map-label','dragleave',{'dataTransfer':data})
        assert page.locator('#geojson-drop-overlay').is_visible(), 'Moving between map children must not flicker.'
        output=Path('data/outputs/geojson-upload');output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/'drop-target.png'))
        page.dispatch_event('#map','drop',{'dataTransfer':data});data.dispose()
        page.wait_for_function("fieldLoaded && document.getElementById('map-label').textContent==='teste.geojson'")
        assert page.evaluate('uploadedGeojson')==fixture
        assert not page.locator('#geojson-drop-overlay').is_visible()
        assert queries==[], 'Dropping a file must not start a satellite consultation.'
        original=page.evaluate('uploadedGeojson')

        # A loaded map must not swallow the next drop: the overlay owns the hit target.
        replacement={'type':'MultiPolygon','coordinates':[fixture['geometry']['coordinates']]}
        data=transfer([{'name':'replacement.geojson','content':json.dumps(replacement)}])
        page.dispatch_event('#map','dragenter',{'dataTransfer':data})
        assert page.evaluate("document.elementFromPoint(innerWidth/2,innerHeight/2).closest('#geojson-drop-overlay')!==null")
        page.dispatch_event('#geojson-drop-overlay','dragover',{'dataTransfer':data})
        page.dispatch_event('#geojson-drop-overlay','drop',{'dataTransfer':data});data.dispose()
        page.wait_for_function("document.getElementById('map-label').textContent==='replacement.geojson'")
        assert page.evaluate('uploadedGeojson')==replacement
        assert not page.locator('#geojson-drop-overlay').is_visible()
        original=replacement

        for files,message in [
            ([{'name':'bad.geojson','content':'{bad'}],'JSON válido'),
            ([{'name':'point.json','content':json.dumps({'type':'Point','coordinates':[0,0]})}],'polígono GeoJSON único'),
            ([{'name':'invalid.json','content':json.dumps({'type':'Polygon','coordinates':[]})}],'sem contorno'),
            ([{'name':'too-big.geojson','content':' '*2_000_001}],'2 MB'),
            ([{'name':'file.txt','content':'hello','type':'text/plain'}],'.geojson ou .json'),
            ([{'name':'one.json','content':'{}'},{'name':'two.json','content':'{}'}],'apenas um arquivo'),
            ([{'name':'collection.json','content':json.dumps({'type':'FeatureCollection','features':[fixture,fixture]})}],'polígono GeoJSON único'),
        ]:
            drop(files)
            page.wait_for_function("message=>document.getElementById('status').textContent.includes(message)",arg=message)
            assert page.evaluate('uploadedGeojson')==original
            assert page.locator('#map-loading').get_attribute('data-state')=='error'
            assert not page.locator('#geojson-drop-overlay').is_visible()

        multi={'type':'MultiPolygon','coordinates':[fixture['geometry']['coordinates']]}
        page.locator('#field-file').set_input_files({'name':'picker.json','mimeType':'application/json','buffer':json.dumps(multi).encode()})
        page.wait_for_function("document.getElementById('map-label').textContent==='picker.json'")
        assert page.evaluate('uploadedGeojson')==multi
        collection={'type':'FeatureCollection','features':[fixture]}
        drop([{'name':'colecao.geojson','content':'\ufeff'+json.dumps(collection)}],target='#ai-prompt')
        page.wait_for_function("document.getElementById('map-label').textContent==='colecao.geojson'")
        assert page.evaluate('uploadedGeojson')==collection
        assert page.locator('#ai-prompt').input_value()==''

        # An older asynchronous file read must not replace the latest selected file.
        page.evaluate("""()=>{
          window.originalFileText=File.prototype.text;
          File.prototype.text=function(){
            if(this.name==='slow.geojson')return new Promise(resolve=>window.finishSlowUpload=resolve);
            return originalFileText.call(this);
          };
        }""")
        drop([{'name':'slow.geojson','content':json.dumps(fixture)}])
        page.wait_for_function("typeof finishSlowUpload==='function'")
        drop([{'name':'latest.geojson','content':json.dumps(multi)}])
        page.wait_for_function("document.getElementById('map-label').textContent==='latest.geojson'")
        page.evaluate("value=>{finishSlowUpload(JSON.stringify(value));File.prototype.text=originalFileText;}",fixture)
        page.wait_for_timeout(100)
        assert page.evaluate('uploadedGeojson')==multi
        assert page.locator('#map-label').inner_text()=='latest.geojson'

        data=transfer([{'name':'cancel.geojson','content':json.dumps(fixture)}])
        page.dispatch_event('#map','dragenter',{'dataTransfer':data});page.keyboard.press('Escape')
        assert not page.locator('#geojson-drop-overlay').is_visible()
        data.dispose()
        page.locator('#ndvi-button').click()
        page.wait_for_function("document.getElementById('ndvi-status').textContent.includes('Não foi possível avaliar')")
        assert queries[-1]['geojson']==multi
        assert page.url.rstrip('/')==base
        assert not errors,errors
        browser.close()
    print('PASS: file drops, visual target, picker, Polygon/MultiPolygon, BOM, validation, preserved area, latest upload wins and NDVI payload. No satellite requests.')


if __name__=='__main__':main()
