"""Calendar presets and multi-year graphs, without provider or collection calls."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def main():
    base='http://127.0.0.1:8765';errors=[];queries=[]
    feature=json.loads(Path('data/sample-field.geojson').read_text(encoding='utf-8'))
    points=[{'date':day,'ndvi_mean':.4+i*.1,'valid_pixels':100,'valid_fraction':.9}
            for i,day in enumerate(('2024-02-29','2025-12-31','2026-01-15'))]
    history={'id':'e'*64,'status':'ready','points':points,'processed':3,'total':3,
        'years':[{'year':year,'status':'ready','observations':1} for year in (2024,2025,2026)],
        'parameters':{'geometry':feature['geometry'],'municipality_code':'5107925','area_key':'a'*64,
                      'start_year':2024,'end_year':2026,'as_of':'2026-01-15'}}
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
            elif path=='/api/ndvi-series':queries.append(r.request.post_data_json);body={'points':points}
            elif path=='/api/research/history':body=history
            elif path=='/api/research/analyze':body={'baseline':{'stage':'inconclusivo','reason':'Teste de datas.'}}
            r.fulfill(json=body)
        page.route('**/*',route);page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')
        page.evaluate('feature=>selectAnalysisArea(feature,"Teste de períodos")',feature)
        page.locator('#date-to').fill('2026-01-15')
        preset=page.locator('#date-range-preset')
        for months,expected in [('1','2025-12-15'),('3','2025-10-15'),('6','2025-07-15'),('9','2025-04-15'),('12','2025-01-15')]:
            preset.select_option(months)
            assert page.locator('#date-from').input_value()==expected
            assert page.locator('#date-to').input_value()=='2026-01-15'
        assert queries==[], 'Changing dates must not start collection.'

        page.locator('#date-to').fill('2024-03-31');preset.select_option('1')
        assert page.locator('#date-from').input_value()=='2024-02-29'
        page.locator('#date-to').fill('2024-02-29');preset.select_option('12')
        assert page.locator('#date-from').input_value()=='2023-02-28'
        page.locator('#date-from').fill('2024-01-01')
        assert preset.input_value()=='custom'
        page.locator('#date-to').fill('2026-01-15')
        assert page.locator('#date-from').input_value()=='2024-01-01'
        page.locator('#ndvi-button').click()
        page.wait_for_function("!document.getElementById('ndvi-button').disabled")
        assert queries[-1]['from']=='2024-01-01' and queries[-1]['to']=='2026-01-15'
        assert '2024' in page.locator('#ndvi-chart').text_content() and '2026' in page.locator('#ndvi-chart').text_content()
        output=Path('data/outputs/date-ranges');output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/'multiyear.png'))

        page.locator('#ndvi-panel-close').click()
        page.evaluate("""()=>{
          const city=document.getElementById('municipality-select');city.add(new Option('Sorriso','5107925'));city.value='5107925';
          document.getElementById('side-panel').classList.remove('closed');document.getElementById('research-panel').open=true;
        }""")
        page.locator('#start-area-history').click()
        page.wait_for_function("document.getElementById('research-year').value==='all'")
        assert 'histórico completo' in page.locator('#ndvi-panel .analysis-subtitle').inner_text()
        assert page.locator('#date-from').input_value()=='2024-02-29'
        page.locator('#research-year').select_option('2025')
        assert page.locator('#date-from').input_value()=='2025-12-31'
        page.locator('#research-year').select_option('all')
        assert page.locator('#date-from').input_value()=='2024-02-29'
        assert page.locator('#date-to').input_value()=='2026-01-15'
        assert preset.input_value()=='custom'
        assert not errors,errors
        browser.close()
    print('PASS: 1/3/6/9/12 calendar months, year crossing, leap days, custom multi-year request and complete-history graph. No external requests.')


if __name__=='__main__':main()
