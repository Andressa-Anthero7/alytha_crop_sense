"""Guided regional workflow in Chromium with isolated official-source fixtures."""
import argparse
import json
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8765')
    base=parser.parse_args().url.rstrip('/')
    states=[{'id':51,'nome':'Mato Grosso','sigla':'MT'}]
    cities=[{'id':5107925,'nome':'Sorriso'},{'id':5107909,'nome':'Sinop'}]
    boundary={'type':'FeatureCollection','features':[{'type':'Feature','properties':{},'geometry':{'type':'Polygon','coordinates':[[[-55,-12],[-54.99,-12],[-54.99,-11.99],[-55,-11.99],[-55,-12]]]}}]}
    reference={'id':'b'*64,'status':'ready','processed':1,'total':1,'years':[{'year':2025,'status':'ready','observations':6}],
        'parameters':{'municipality_code':'5107925','area_key':'reference','geometry':boundary['features'][0]['geometry'],'start_year':2025,'end_year':2025,'as_of':'2025-12-31'},
        'points':[{'date':f'2025-10-{day:02}','ndvi_mean':.2,'valid_pixels':500,'valid_fraction':.8} for day in (1,6,11,16,21,26)]}
    starts=[]
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':768})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        def route(request):
            url=request.request.url
            if not url.startswith(base):request.abort();return
            path=urlsplit(url).path;query=parse_qs(urlsplit(url).query)
            if '/api/' not in path:request.continue_();return
            body=[]
            if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
            elif path=='/api/locations/states':body=states
            elif path=='/api/locations/states/51/municipalities':body=cities
            elif path.startswith('/api/locations/boundaries/'):body=boundary
            elif path=='/api/locations/search':
                term=query['q'][0]
                matches=[{'kind':'state','code':'51','name':'Mato Grosso','uf':'MT'}] if term=='MT' else [{'kind':'municipality','code':'5107925','name':'Sorriso','uf':'MT'}]
                if term=='Ambigua':matches.append({'kind':'municipality','code':'5107909','name':'Sinop','uf':'MT'})
                body={'matches':matches,'exact':True}
            elif path=='/api/regional-scans':
                payload=request.request.post_data_json;starts.append(payload)
                body={'id':'a'*64,'status':'ready','phase':'complete','parameters':{**payload,'as_of':'2026-10-13'},'processed':2,'total':2,
                    'cities':[{'code':str(c['id']),'name':c['nome'],'status':'ready',**({'history':{'id':'b'*64,'observations':6}} if c['id']==5107925 else {})} for c in cities]}
            elif path.startswith('/api/municipalities/'):
                body={'status':'ready','sources':{},'name':'Sorriso','uf':'MT','boundary':boundary}
            elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':False,'provider':'Gemini'}}
            elif path.startswith('/api/research/history/'):body=reference
            elif path=='/api/research/analyze':body={'baseline':{'stage':'inconclusivo','reason':'Fixture sem interpretação agronômica.'}}
            elif path=='/api/sources/status':body={'satveg_configured':False}
            request.fulfill(json=body)
        page.route('**/*',route);page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')
        page.locator('#location-search').fill('Sorriso / MT');page.locator('#location-search').press('Enter')
        try:
            page.wait_for_function("document.getElementById('regional-scan-status').textContent.includes('2/2')")
        except Exception:
            print(page.evaluate("({region:document.getElementById('region-status').textContent,scan:document.getElementById('regional-scan-status').textContent,request:regionRequest,municipality:document.getElementById('municipality-select').value})"),errors,starts)
            raise
        assert starts[-1]=={'kind':'municipality','code':'5107925'}
        assert page.locator('#municipality-select').input_value()=='5107925'
        page.locator('#location-search').fill('Ambigua');page.locator('#location-search').press('Enter')
        page.wait_for_function("!document.getElementById('location-matches').hidden")
        assert page.locator('#location-matches button').count()==2
        assert starts[-1]['kind']=='municipality'
        page.locator('#location-search').fill('MT');page.locator('#location-search').press('Enter')
        page.wait_for_function("new URL(location.href).searchParams.get('estado')==='51' && document.getElementById('regional-scan-status').textContent.includes('2/2')")
        assert starts[-1]=={'kind':'state','code':'51'}
        page.evaluate("document.getElementById('side-panel').classList.remove('closed');document.getElementById('regional-scan-panel').open=true")
        with page.expect_download() as download:page.locator('#export-regional-scan').click()
        with open(download.value.path(),encoding='utf-8') as stream:report=json.load(stream)
        assert report['parameters']['kind']=='state' and len(report['cities'])==2
        page.locator('#regional-scan-results button',has_text='Histórico de referência').click()
        page.wait_for_function("document.getElementById('research-status').textContent.includes('6 leituras')")
        assert page.locator('#municipality-select').input_value()=='5107925'
        assert page.evaluate('researchHistory.parameters.municipality_code')=='5107925'
        assert not errors,errors
        browser.close()
    print('PASS: official city search, ambiguous names, state scan, JSON export and regional reference history.')


if __name__=='__main__':main()
