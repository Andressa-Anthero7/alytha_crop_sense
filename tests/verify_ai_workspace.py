"""Visual/browser check. Mock all APIs; never triggers collection or a paid AI call."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'data/outputs/layout-ai'
BASE='http://127.0.0.1:8765'


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch()
        report=[]
        for width,height in [(1366,768),(1440,900),(390,844),(320,740),(844,390)]:
            page=browser.new_page(viewport={'width':width,'height':height},device_scale_factor=1)
            errors=[];calls=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def route(r):
                path=urlsplit(r.request.url).path
                if not r.request.url.startswith(BASE):
                    # Basemap only: no Sentinel, external APIs or model providers.
                    if r.request.url.startswith('https://tile.openstreetmap.org/'):
                        r.continue_()
                    else:r.abort()
                    return
                if not path.startswith('/api/'):
                    r.continue_();return
                body=[]
                if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
                elif path=='/api/locations/states':body=[{'id':51,'nome':'Mato Grosso','sigla':'MT'}]
                elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':True,'provider':'CropSense'}}
                elif path=='/api/sources/status':body={'satveg_configured':False}
                elif path=='/api/assistant':
                    calls.append(r.request.post_data_json)
                    body={'answer':'Temos prévias NDVI e rasters salvos. A consulta utilizou somente a base local.',
                          'evidence_ids':['local_inventory'],'limitations':[],
                          'sources':[{'id':'local_inventory','source':'Inventário local'}],
                          'action':{'kind':'none','class_ids':[]}}
                r.fulfill(json=body)
            page.route('**/*',route)
            page.goto(BASE,wait_until='domcontentloaded')
            page.wait_for_function('mapReady')
            page.wait_for_timeout(1000)
            assert page.locator('#ai-prompt-panel').is_visible()
            assert page.locator('#side-panel').evaluate("e=>e.classList.contains('closed')")
            assert page.locator('#ai-mode-toggle').get_attribute('aria-expanded')=='true'
            assert not page.locator('.timeline').is_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            prompt=page.locator('#ai-prompt');box=prompt.bounding_box()
            assert box and box['width']>150 and box['height']>=44
            panel=page.locator('#ai-prompt-panel').bounding_box()
            assert panel['y']>=64 and panel['y']+panel['height']<=height
            page.screenshot(path=str(OUTPUT/f'initial-{width}.png'))
            page.get_by_role('button',name='Meus dados salvos').click()
            assert 'imagens temos salvas' in prompt.input_value()
            prompt.press('Shift+Enter')
            assert '\n' in prompt.input_value() and len(calls)==0
            prompt.press('Enter')
            page.wait_for_function("document.querySelector('#ai-prompt-status')?.textContent.includes('somente a base local')")
            assert len(calls)==1
            assert not page.locator('.ai-welcome').is_visible()
            page.screenshot(path=str(OUTPUT/f'conversation-{width}.png'))
            page.locator('#ai-panel-close').click()
            assert not page.locator('#ai-prompt-panel').is_visible()
            assert page.locator('#ai-mode-toggle').get_attribute('aria-expanded')=='false'
            page.locator('#ai-mode-toggle').click()
            assert page.locator('#ai-prompt-panel').is_visible()
            page.locator('#panel-toggle').click()
            assert page.locator('#side-panel').is_visible()
            assert page.locator('.timeline').is_visible()
            if width<1000:
                assert not page.locator('#ai-prompt-panel').is_visible()
                page.locator('#ai-mode-toggle').click()
                assert page.locator('#ai-prompt-panel').is_visible()
                assert not page.locator('#side-panel').is_visible()
            else:
                page.locator('#panel-toggle').click()
            assert not errors,errors
            report.append({'viewport':[width,height],'prompt_size':box,'console_errors':errors,'assistant_requests':len(calls)})
            page.close()
        browser.close()
    (OUTPUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Verified {len(report)} viewports. Screenshots: {OUTPUT}')


if __name__=='__main__':main()
