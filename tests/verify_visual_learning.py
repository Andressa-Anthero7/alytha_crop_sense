"""Isolated browser workflow; synthetic responses never enter the real base."""
import argparse
import base64
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8765')
    base=parser.parse_args().url.rstrip('/')
    history={'id':'a'*64,'status':'ready','points':[],'years':[],'parameters':{
        'area_key':'fixture','municipality_code':'5107925','start_year':2026,'end_year':2026,'as_of':'2026-10-14',
        'geometry':{'type':'Polygon','coordinates':[[[-55,-12],[-54.99,-12],[-54.99,-11.99],[-55,-12]]]}}}
    asset={'id':'c'*64,'kind':'ndvi','period':{'from':'2026-10-03','to':'2026-10-07'},
        'valid_fraction':.8,'note':'Mapa NDVI real; cinza sem observação.'}
    job={'id':'b'*64,'status':'ready','analysis_mode':'visual','assets':[asset],'missing_true_color':True,
        'review':{'answer':'<img src=x onerror=alert(1)> Há heterogeneidade visual.',
                  'visual_observations':[{'description':'Diferenças espaciais visíveis.'}],
                  'hypotheses':['Estabelecimento desigual.'],'field_checks':['Conferir em campo.'],'limitations':[]}}
    requests=[]
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=')
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1366,'height':900})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        def route(req):
            url=req.request.url
            if not url.startswith(base):req.abort();return
            path=url[len(base):].split('?')[0]
            if '/api/' not in path:req.continue_();return
            body=[]
            if path=='/api/config':body={'google_maps_api_key':'','ndvi_configured':False}
            elif path=='/api/research/status':body={'ml':{'events':0,'areas':0,'model':None},'satellite':None,'assistant':{'configured':True,'provider':'Gemini'}}
            elif path=='/api/sources/status':body={'satveg_configured':False}
            elif path=='/api/visual-learning':
                requests.append(req.request.post_data_json);body={'id':job['id'],'status':'running'}
            elif path=='/api/visual-learning/'+job['id']:body=job
            elif path.startswith('/api/visual-learning/assets/'):
                req.fulfill(body=png,content_type='image/png');return
            req.fulfill(json=body)
        page.route('**/*',route)
        page.goto(base,wait_until='domcontentloaded')
        page.evaluate("""history=>{
          document.getElementById('research-panel').open=true;
          document.getElementById('side-panel').classList.remove('closed');
          document.dispatchEvent(new CustomEvent('alytha-history-ready',{detail:history}));
        }""",history)
        button=page.locator('#start-visual-learning')
        assert not button.is_disabled()
        assert not requests
        button.click()
        page.wait_for_function("document.getElementById('visual-learning-status').textContent.includes('concluída')")
        assert requests==[{'dataset_id':history['id']}]
        output=page.locator('#visual-learning-results')
        assert output.locator('img').count()==1
        assert 'não foi simulada' in output.inner_text()
        assert 'Hipótese: Estabelecimento desigual.' in output.inner_text()
        assert 'Verificar em campo: Conferir em campo.' in output.inner_text()
        assert '<img src=x' in output.inner_text()
        page.evaluate("document.dispatchEvent(new Event('alytha-area-cleared'))")
        assert button.is_disabled()
        assert output.inner_text()==''
        assert not errors,errors
        browser.close()
    print('OK: solicitação visual, imagens, datas, hipóteses, segurança de texto e troca de área.')


if __name__=='__main__':main()
