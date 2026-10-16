"""Review all research topics in the browser without consulting satellite providers."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def main():
    catalogue=json.loads(Path('web/soy-study.json').read_text(encoding='utf-8'))
    sources={s['id']:s for s in catalogue['sources']}
    assert len(catalogue['topics'])==22
    assert len({t['id'] for t in catalogue['topics']})==22
    for topic in catalogue['topics']:
        assert all(topic.get(k) for k in ['group','name','objective','question','system','field','limit','work','sources'])
        assert all(s in sources for s in topic['sources'])
    assert all(urlsplit(s['url']).scheme=='https' for s in sources.values())
    assert all('dose' not in t['objective'] for t in catalogue['topics'])
    errors=[];research_requests=[];provider_requests=[];base='http://127.0.0.1:8765'
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':900})
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route(r):
            url=r.request.url
            if not url.startswith(base+'/'):provider_requests.append(url);r.abort();return
            path=urlsplit(url).path
            if path=='/soy-study.json':research_requests.append(path)
            if not path.startswith('/api/'):r.continue_();return
            body=[]
            if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
            elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':False}}
            elif path=='/api/sources/status':body={'satveg_configured':False}
            r.fulfill(json=body)
        page.route('**/*',route);page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')
        assert not research_requests
        page.locator('#panel-toggle').click();page.evaluate("document.getElementById('soy-study-panel').open=true")
        page.wait_for_function("!document.getElementById('soy-study-topic').disabled")
        assert '22 temas' in page.locator('#soy-study-status').inner_text()
        for topic in catalogue['topics']:
            page.locator('#soy-study-topic').select_option(topic['id'])
            assert topic['question'] in page.locator('#soy-study-content').inner_text()
            assert topic['limit'] in page.locator('#soy-study-content').text_content()
            assert page.locator('#soy-study-content a').count()==len(topic['sources'])
        page.locator('#soy-study-topic').select_option('sowing')
        page.locator('#soy-study-content details').first.evaluate('(e)=>e.open=true')
        output=Path('data/outputs/soy-study');output.mkdir(exist_ok=True,parents=True)
        page.screenshot(path=str(output/'study-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        page.locator('#soy-study-topic').select_option('window')
        page.locator('#soy-study-topic').scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(output/'study-mobile.png'))
        page.evaluate("document.getElementById('soy-study-panel').open=false")
        page.evaluate("document.getElementById('soy-study-panel').open=true")
        assert len(research_requests)==1
        assert not errors,errors
        browser.close()
    print('PASS: 22 sourced topics, planned features, lazy local catalogue, every topic, no area diagnosis and mobile layout. External requests blocked.')


if __name__=='__main__':main()
