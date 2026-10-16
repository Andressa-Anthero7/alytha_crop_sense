"""Real local catalog search from an uploaded area; isolate all other providers."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geojson',default='data/sample-field.geojson')
    args=parser.parse_args();base='http://127.0.0.1:8765';errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':768})
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(r):
            path=urlsplit(r.request.url).path
            if not r.request.url.startswith(base+'/'):r.abort();return
            if not path.startswith('/api/') or path=='/api/search':r.continue_();return
            body=[]
            if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
            elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':False,'provider':'Gemini'}}
            elif path=='/api/sources/status':body={'satveg_configured':False}
            r.fulfill(json=body)
        page.route('**/*',route);page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')
        page.locator('#field-file').set_input_files(args.geojson)
        page.wait_for_function('fieldLoaded')
        page.locator('#date-from').fill('2026-08-10');page.locator('#date-to').fill('2026-10-08')
        with page.expect_response(lambda r:urlsplit(r.url).path=='/api/search',timeout=120000) as completed:
            page.locator('#search').click()
        response=completed.value;result=response.json()
        assert response.status==200,result
        page.wait_for_function("!document.getElementById('search').disabled")
        assert not page.locator('#status').evaluate("node=>node.classList.contains('error')")
        assert 'Expecting value' not in page.locator('#status').inner_text()
        assert not errors,errors
        output=Path('data/outputs/catalog');output.mkdir(parents=True,exist_ok=True)
        report={'file':str(Path(args.geojson).resolve()),'scenes':len(result['features']),
            'transport':result.get('catalog_transport','POST'),'mode':result.get('mode','remote'),
            'period':{'from':'2026-08-10','to':'2026-10-08'},'console_errors':errors,'images_downloaded':False}
        (output/'browser-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        page.screenshot(path=str(output/'large-area-catalog.png'))
        browser.close();print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
