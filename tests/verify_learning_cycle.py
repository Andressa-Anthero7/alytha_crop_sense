"""Browser workflow with synthetic responses; never creates real field records."""
import argparse
import copy
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    base = parser.parse_args().url.rstrip('/')
    history = {'id':'a'*64, 'status':'ready', 'points':[], 'years':[], 'parameters':{
        'area_key':'area-one', 'municipality_code':'5107925', 'start_year':2026,
        'end_year':2026, 'as_of':'2026-10-14', 'geometry':{'type':'Polygon',
        'coordinates':[[[-55,-12],[-55.01,-12],[-55,-12.01],[-55,-12]]]}}}
    plan = {'id':'b'*64, 'name':'Área parceira', 'area_key':'area-one', 'municipality_code':'5107925',
            'enabled':True, 'ai_enabled':True, 'next_due':'2026-10-19T12:00:00+00:00', 'running':False,
            'runs':[{'id':'c'*32, 'dataset_id':'d'*64, 'as_of':'2026-10-14', 'status':'ready',
                     'features':{'latest':.6}, 'collection':{'new_intervals':1,'usable_recent':6},
                     'analysis':{'baseline':{'label':'Possível desenvolvimento','reason':'Vigor crescente.'}},
                     'ai_review':{'status':'ready','provider':'Gemini','answer':'<img src=x onerror=alert(1)> Conferir com o produtor.', 'limitations':[]},
                     'field_review':{'status':'pending'}}]}
    state = {'enrolled':False, 'reviews':[], 'configs':[]}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':1366,'height':900})
        errors = []; page.on('pageerror',lambda error:errors.append(str(error)))
        def route(request):
            url = request.request.url
            if not url.startswith(base):request.abort();return
            if '/api/' not in url:request.continue_();return
            path = url[len(base):].split('?')[0]
            method = request.request.method
            body = []
            if path == '/api/config':body = {'google_maps_api_key':'','ndvi_configured':False}
            elif path == '/api/research/status':body = {'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':False,'provider':'Gemini'}}
            elif path == '/api/sources/status':body = {'satveg_configured':False}
            elif path == '/api/learning-cycle':
                if method == 'POST':
                    assert request.request.post_data_json['dataset_id'] == history['id']
                    state['enrolled'] = True; body = plan
                else:body = [plan] if state['enrolled'] else []
            elif path == '/api/learning-cycle/'+plan['id']:body = plan
            elif path == '/api/learning-cycle/configure':
                payload = request.request.post_data_json;state['configs'].append(payload)
                plan.update({key:payload[key] for key in ('enabled','ai_enabled') if key in payload});body = plan
            elif path == '/api/learning-cycle/review':
                payload = request.request.post_data_json;state['reviews'].append(payload)
                plan['runs'][0]['field_review'] = {'status':'confirmed','confirmed_stage':payload['stage']};body = plan['runs'][0]
            elif path == '/api/learning-cycle/export':body = {'windows':1,'field_labeled_windows':1,'folder':'data/outputs/test-fixture'}
            request.fulfill(json=copy.deepcopy(body))
        page.route('**/*',route)
        page.goto(base,wait_until='domcontentloaded')
        page.wait_for_function('typeof storageJson === "function"')
        page.evaluate("""history => {
          document.getElementById('research-panel').open=true;
          document.getElementById('side-panel').classList.remove('closed');
          document.dispatchEvent(new CustomEvent('alytha-history-ready',{detail:history}));
        }""", history)
        enable = page.locator('#enable-learning-cycle')
        page.wait_for_function("!document.getElementById('enable-learning-cycle').disabled")
        enable.click()
        panel = page.locator('#learning-cycle-panel')
        page.wait_for_function("document.getElementById('learning-cycle-plans').textContent.includes('Conferir com o produtor')")
        assert panel.locator('img').count() == 0
        assert enable.is_disabled()
        panel.get_by_role('button',name='Pausar acompanhamento',exact=True).click()
        page.wait_for_function("document.getElementById('learning-cycle-plans').textContent.includes('Acompanhamento pausado')")
        panel.get_by_role('button',name='Retomar acompanhamento',exact=True).click()
        page.wait_for_function("document.getElementById('learning-cycle-plans').textContent.includes('Pausar acompanhamento')")
        panel.get_by_text('Validar ou corrigir com informações de campo',exact=True).click()
        form = panel.locator('form')
        assert form.locator('select').input_value() == ''
        form.locator('select').select_option('pousio')
        form.get_by_label('Parceiro ou responsável').fill('Parceiro piloto')
        form.get_by_label('Cultura informada · opcional').fill('soja')
        form.get_by_label('Referência da informação').fill('Visita confirmou pousio no recorte.')
        form.get_by_role('button',name='Salvar confirmação de campo').click()
        page.wait_for_function("document.getElementById('learning-cycle-plans').textContent.includes('Validação de campo registrada: Pousio')")
        assert state['reviews'][0]['run_id'] == 'c'*32
        assert state['reviews'][0]['stage'] == 'pousio'
        panel.get_by_role('button',name='Exportar base de aprendizado contínuo').click()
        page.wait_for_function("document.getElementById('learning-cycle-status').textContent.includes('1 com referência de campo')")
        page.evaluate("document.dispatchEvent(new Event('alytha-area-cleared'))")
        assert enable.is_disabled()
        assert not errors, errors
        browser.close()
    print('OK: inscrição, pausa/retomada, revisão segura, correção humana, exportação e troca de área.')


if __name__ == '__main__':
    main()
