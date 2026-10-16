"""Compare observed NDVI dates without treating cloud gaps as vegetation changes."""
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def main():
    base='http://127.0.0.1:8765';errors=[]
    points=[{'date':'2026-09-'+day,'ndvi_mean':value,'valid_fraction':coverage,'valid_pixels':pixels}
            for day,value,coverage,pixels in [('01',.24,.85,100),('06',.9,.1,10),('11',.36,.901,90),('16',.2,.92,120)]]
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
            r.fulfill(json=body)
        page.route('**/*',route);page.goto(base,wait_until='domcontentloaded');page.wait_for_function('mapReady')
        page.evaluate("points=>{renderNdvi(points);document.getElementById('ndvi-panel').classList.add('visible');}",points)
        card=page.locator('#ndvi-point-detail');chart=page.locator('#ndvi-chart')
        reference=chart.locator('[data-historical-mean]')
        assert page.locator('#ndvi-series-legend').is_visible()
        assert chart.locator('[data-observed-curve]').get_attribute('d').count('M ')==2, 'Do not join across a cloudy reading.'
        assert abs(float(reference.get_attribute('data-historical-mean'))-(.24+.36+.2)/3)<1e-10
        assert '3 leituras de 01/09/2026 a 16/09/2026' in card.locator('.ndvi-historical-reference').inner_text()
        page.locator('#ndvi-zoom-in').click()
        assert abs(float(reference.get_attribute('data-historical-mean'))-(.24+.36+.2)/3)<1e-10
        page.locator('#ndvi-zoom-reset').click()
        assert card.locator('.ndvi-metric strong').all_text_contents()==['0,200','92%','-0,160']
        assert '11/09/2026' in card.inner_text() and '5 dias' in card.inner_text()
        assert 'mínimo 0,200 e máximo 0,360' in card.inner_text()
        chart.focus();chart.press('ArrowLeft')
        assert card.locator('.ndvi-metric strong').all_text_contents()==['0,360','90,1%','+0,120']
        assert '01/09/2026' in card.inner_text() and '10 dias' in card.inner_text()
        assert 'mínimo 0,240 e máximo 0,360' in card.inner_text(), 'Older selection must not use future observations.'
        output=Path('data/outputs/ndvi-card');output.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(output/'comparison-desktop.png'))
        chart.press('ArrowLeft')
        assert card.locator('.ndvi-metric strong').nth(2).inner_text()=='—'
        assert 'Comparação indisponível' in card.inner_text()
        chart.press('Home')
        assert 'Ainda não há uma leitura anterior' in card.inner_text()
        page.evaluate("renderNdvi([{date:'2026-09-01',ndvi_mean:.3}])")
        assert reference.count()==0
        assert 'indisponível' in card.locator('.ndvi-historical-reference').inner_text()
        assert 'Não informada' in card.inner_text() and 'Comparação indisponível' in card.inner_text()
        page.evaluate("renderNdvi([])")
        assert 'Sem observações' in chart.text_content()
        assert card.locator('.ndvi-metric').count()==0
        page.set_viewport_size({'width':390,'height':844})
        page.evaluate('points=>renderNdvi(points)',points[:3])
        card.scroll_into_view_if_needed()
        assert card.locator('.ndvi-metric strong').nth(2).inner_text()=='+0,120'
        assert card.evaluate('node=>node.scrollWidth<=node.clientWidth')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(output/'comparison-mobile.png'))
        historical=[{'date':f'{year}-09-{day}','ndvi_mean':value,'valid_fraction':.9,'valid_pixels':100}
                    for year,value in [(2023,.3),(2024,.4),(2025,.5),(2026,.99),(2027,.99)] for day in ['01','11']]
        page.evaluate('h=>renderNdvi([{date:"2026-09-16",ndvi_mean:.4,valid_fraction:.9,valid_pixels:100}],{historyPoints:h})',historical)
        assert 'Dentro da faixa' in card.locator('.ndvi-seasonal-reference').inner_text()
        assert '2023, 2024, 2025' in card.locator('.ndvi-seasonal-reference').text_content()
        assert abs(float(chart.locator('[data-seasonal-mean]').get_attribute('data-seasonal-mean'))-.4)<1e-10
        for value,label in [(.1,'Abaixo'),(.8,'Acima')]:
            page.evaluate('args=>renderNdvi([{date:"2026-09-16",ndvi_mean:args.value,valid_fraction:.9,valid_pixels:100}],{historyPoints:args.h})',{'value':value,'h':historical})
            assert label in card.locator('.ndvi-seasonal-reference').inner_text()
            assert 'Fora da faixa habitual' in card.locator('.ndvi-seasonal-verdict').inner_text()
        for value,range_status,mean_status in [(.35,'within','Abaixo'),(.45,'within','Acima'),(.4,'within','Na média'),(.3,'within','Abaixo'),(.5,'within','Acima'),(.299,'below','Abaixo'),(.501,'above','Acima')]:
            page.evaluate('args=>renderNdvi([{date:"2026-09-16",ndvi_mean:args.value,valid_fraction:.9,valid_pixels:100}],{historyPoints:args.h})',{'value':value,'h':historical})
            assert card.locator('.ndvi-seasonal-reference').get_attribute('data-range')==range_status
            assert mean_status in card.locator('.ndvi-seasonal-mean-status').inner_text()
        page.evaluate('h=>renderNdvi([{date:"2026-09-16",ndvi_mean:.35,valid_fraction:.9,valid_pixels:100}],{historyPoints:h})',historical)
        card.locator('.ndvi-seasonal-reference').scroll_into_view_if_needed()
        page.screenshot(path=str(output/'seasonal-verdict-mobile.png'))
        page.evaluate('h=>renderNdvi([{date:"2026-09-16",ndvi_mean:.35,valid_fraction:.1,valid_pixels:10}],{historyPoints:h})',historical)
        assert card.locator('.ndvi-seasonal-reference').get_attribute('data-range')=='unavailable'
        assert card.locator('.ndvi-seasonal-mean-status').count()==0
        page.evaluate('h=>renderNdvi([{date:"2025-09-16",ndvi_mean:.4,valid_fraction:.9,valid_pixels:100}],{historyPoints:h})',historical)
        assert 'indisponível' in card.locator('.ndvi-seasonal-reference').inner_text()
        assert chart.locator('[data-seasonal-mean]').count()==0
        rising=[{'date':'2026-09-'+day,'ndvi_mean':value,'valid_fraction':.9,'valid_pixels':100}
                for day,value in [('01',.15),('06',.2),('11',.29),('16',.4),('21',.5)]]
        page.evaluate('p=>renderNdvi(p)',rising)
        signal=card.locator('.ndvi-emergence')
        assert signal.get_attribute('data-status')=='possible_emergence'
        assert 'Sinal — possível plantio ou rebrota' in signal.inner_text()
        assert '5 leituras' in signal.inner_text()
        page.locator('#ndvi-chart').focus();page.locator('#ndvi-chart').press('Home')
        assert signal.get_attribute('data-status')=='insufficient', 'No future observations in early selection.'
        cases=[
            ([dict(p,ndvi_mean=.5) for p in rising],'not_detected'),
            ([dict(p,ndvi_mean=.6-i*.08) for i,p in enumerate(rising)],'not_detected'),
            ([dict(p,ndvi_mean=.15 if i<4 else .6) for i,p in enumerate(rising)],'not_detected'),
            ([dict(p,valid_fraction=.1) for p in rising],'insufficient'),
            ([dict(p,valid_fraction=.5 if i<2 else .9) for i,p in enumerate(rising)],'insufficient'),
            (rising[:2],'insufficient'),
            ([rising[0],rising[1],rising[-1],dict(rising[-1],date='2026-09-26')],'insufficient'),
        ]
        for observations,status in cases:
            page.evaluate('p=>renderNdvi(p)',observations)
            assert signal.get_attribute('data-status')==status,(observations,signal.inner_text())
        page.evaluate('p=>renderNdvi(p)',rising)
        signal.scroll_into_view_if_needed()
        assert card.evaluate('node=>node.scrollWidth<=node.clientWidth')
        page.screenshot(path=str(output/'possible-emergence-mobile.png'))
        assert not errors,errors
        browser.close()
    print('PASS: automatic latest reading, NDVI/coverage/delta, quality gating, skipped cloud gaps, no future data, missing quality and mobile layout.')


if __name__=='__main__':main()
