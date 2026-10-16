"""Browser check with synthetic API responses; never writes producer records.

Run against a local server: python tests/verify_partner_demo.py --url http://127.0.0.1:8766
Requires Playwright and Chromium; these are optional development tools.
"""
import argparse
import json
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--url', default='http://127.0.0.1:8765')
    base = parser.parse_args().url.rstrip('/')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))

        def route(request):
            url = request.request.url
            if not url.startswith(base): request.abort(); return
            if '/api/' not in url: request.continue_(); return
            body = []
            if url.endswith('/api/config'): body = {'google_maps_api_key': '', 'ndvi_configured': False}
            elif url.endswith('/api/research/status'):
                body = {'ml': {'events': 0, 'areas': 0, 'model': None}, 'satellite': None, 'assistant': {'configured': False, 'provider': 'Gemini'}}
            elif url.endswith('/api/sources/status'): body = {'satveg_configured': False}
            request.fulfill(json=body)

        page.route('**/*', route)
        page.goto(base, wait_until='domcontentloaded')
        page.wait_for_function('mapReady')
        page.evaluate("""() => {
          localStorage.removeItem('cropsense-research-history');
          window.fixtureRecords=[
            {area_key:'one',date_from:'2025-10-01',date_to:'2025-10-01',stage:'plantio',note:'<img src=x onerror=alert(1)> Registro autorizado'},
            {area_key:'two',date_from:'2025-10-02',date_to:'2025-10-02',stage:'pousio',note:'Registro de outra área'}
          ];
          window.storageJson=async()=>window.fixtureRecords;
          window.fixtureHistory=key=>({id:key.repeat(64),points:[],parameters:{area_key:key,start_year:2018,end_year:2025,as_of:'2025-12-31',geometry:{type:'Polygon',coordinates:[[[-55,-12],[-55.01,-12],[-55,-12.01],[-55,-12]]]}}});
          document.dispatchEvent(new CustomEvent('alytha-history-ready',{detail:fixtureHistory('one')}));
        }""")
        page.wait_for_function("document.getElementById('field-evidence-list').textContent.includes('Registro autorizado')")
        assert 'outra área' not in page.locator('#field-evidence-list').inner_text()
        assert page.locator('#field-evidence-list img').count() == 0
        page.evaluate("document.getElementById('research-panel').open=true; document.getElementById('field-evidence-panel').open=true; document.getElementById('side-panel').classList.remove('closed')")
        with page.expect_download() as download:
            page.locator('#export-field-evidence').click()
        with open(download.value.path(), encoding='utf-8') as exported:
            payload = json.load(exported)
        assert len(payload['records']) == 1 and payload['area_key'] == 'one'
        assert payload['geometry']['type'] == 'Polygon'
        page.evaluate("""() => {
          researchHistory=fixtureHistory('one');
          window.storageJson=async(url,payload)=>{
            if(url==='/api/research/events' && payload) {
              window.savedEvidence=payload;
              fixtureRecords.push({area_key:'one',date_from:payload.from,date_to:payload.to,stage:payload.stage,note:payload.note});
              return {saved:true};
            }
            if(url==='/api/research/status')return {ml:{events:1,areas:1,model:null},satellite:null};
            return fixtureRecords;
          };
        }""")
        page.locator('#event-from').fill('2025-10-03')
        page.locator('#event-to').fill('2025-10-03')
        page.locator('#event-note').fill('Visita confirmada pelo produtor')
        page.locator('#save-field-event').click()
        page.wait_for_function("document.getElementById('field-evidence-list').textContent.includes('Visita confirmada')")
        assert page.evaluate('savedEvidence.dataset_id') == 'one' * 64
        page.locator('#event-note').fill('Descrição ainda não salva')
        page.evaluate("document.dispatchEvent(new CustomEvent('alytha-history-ready',{detail:fixtureHistory('two')}))")
        page.wait_for_function("document.getElementById('field-evidence-list').textContent.includes('outra área')")
        assert page.locator('#event-note').input_value() == ''
        page.evaluate("""() => {
          window.storageJson=()=>new Promise(resolve=>window.delayedEvidence=resolve);
          document.dispatchEvent(new CustomEvent('alytha-history-ready',{detail:fixtureHistory('one')}));
          window.storageJson=async()=>[];
          document.dispatchEvent(new CustomEvent('alytha-history-ready',{detail:fixtureHistory('two')}));
          window.delayedEvidence(window.fixtureRecords);
        }""")
        page.wait_for_function("document.getElementById('field-evidence-list').textContent.includes('Ainda não há')")
        assert page.locator('#export-field-evidence').is_disabled()
        page.evaluate("document.dispatchEvent(new Event('alytha-area-cleared'))")
        assert page.locator('#save-field-event').is_disabled()
        assert page.locator('#field-evidence-list').inner_text() == ''
        assert not errors, errors
        browser.close()
    print('PASS: field evidence scoped by geometry, safe text, JSON download, area switch and stale response.')


if __name__ == '__main__':
    main()
