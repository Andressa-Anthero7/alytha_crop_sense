"""Isolated browser check: build first, then explicitly activate municipal AI."""
import argparse
import copy
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8765')
    base=parser.parse_args().url.rstrip('/')
    result={'base':{'totals':{'municipalities':2,'processed_municipalities':1,'municipalities_with_data':1,
        'areas_with_observations':10,'feature_windows':20},'municipalities':[
        {'code':'5107925','name':'Sorriso <img src=x>','uf':'MT','readiness':'temporal_data',
         'areas_with_observations':10,'feature_windows':20,'ai_status':'pending'},
        {'code':'5000203','name':'Água Clara','uf':'MS','readiness':'no_data',
         'areas_with_observations':0,'feature_windows':0,'ai_status':'blocked'}]},
        'build':{'status':'ready'},'ai_enabled':False,'queue':{'pending':1,'blocked':1}}
    calls=[]
    dashboard={'generated_at':'2026-10-14T12:00:00Z','total':2,'processed':1,'ready':0,'partial':1,
               'errors':0,'states':[],'municipalities':[],'status':'running'}
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':900})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        def route(req):
            url=req.request.url
            if not url.startswith(base):req.abort();return
            path=url[len(base):].split('?')[0]
            if path=='/collection-data.json':req.fulfill(json=dashboard);return
            if path=='/collection-map.geojson':req.fulfill(json={'type':'FeatureCollection','features':[]});return
            if path.startswith('/api/regional-learning'):
                if req.request.method=='POST':
                    calls.append((path,req.request.post_data_json))
                    if path.endswith('/build'):result['build']['status']='building'
                    if path.endswith('/configure'):result['ai_enabled']=req.request.post_data_json['ai_enabled']
                if '/files/' in path:
                    req.fulfill(json={'fixture':True},headers={'Content-Disposition':'attachment; filename="manifest.json"'});return
                req.fulfill(json=copy.deepcopy(result));return
            req.continue_()
        page.route('**/*',route)
        page.goto(base+'/coleta.html',wait_until='domcontentloaded')
        page.wait_for_function("document.getElementById('regional-base-status').textContent.includes('20 janelas')")
        assert page.locator('#regional-base-cities img').count()==0
        assert not calls
        page.locator('#regional-base-filter').fill('Água')
        assert page.locator('#regional-base-cities tr').count()==1
        assert 'Sem dados para revisão' in page.locator('#regional-base-cities').inner_text()
        page.locator('#toggle-regional-ai').click()
        page.wait_for_function("document.getElementById('regional-ai-status').textContent.includes('Fila da Alytha ativa')")
        assert calls[-1][1]=={'ai_enabled':True}
        page.locator('#toggle-regional-ai').click()
        page.wait_for_function("document.getElementById('regional-ai-status').textContent.includes('pausada')")
        with page.expect_download() as download:
            page.get_by_role('link',name='Inventário completo',exact=True).click()
        assert download.value.suggested_filename=='manifest.json'
        page.locator('#build-regional-base').click()
        page.wait_for_function("document.getElementById('build-regional-base').disabled")
        assert 'Consolidando' in page.locator('#regional-base-status').inner_text()
        assert not errors,errors
        browser.close()
    print('OK: inventário completo, pendências, texto seguro, busca, download e ativação/pausa explícita da IA.')


if __name__=='__main__':main()
