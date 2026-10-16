"""Browser regression for assistant actions, with mocked APIs and no satellite requests."""
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page()
        page.set_content('''<input id="ai-prompt"><button id="ai-prompt-submit">Enviar</button><div id="ai-prompt-status"></div>
          <select id="mapbiomas-year"><option>2025</option></select><select id="municipality-select"></select><select id="state-select"></select>
          <details id="research-panel"><button id="start-area-history">Histórico</button></details><button id="start-crop-monitoring">Atualizar</button>''')
        page.add_script_tag(content='''
          let researchHistory=null,fieldLoaded=true,drawingArea=false;
          window.testContext={municipality_code:'5107925',revision:0};
          window.agriAssistantContext=()=>window.testContext;
          window.fieldGeojson=async()=>({type:'Polygon',coordinates:[]});
          window.calls=[];
          document.getElementById('start-area-history').onclick=()=>calls.push('history');
          document.getElementById('start-crop-monitoring').onclick=()=>calls.push('monitoring');
          window.showCropClasses=async(params)=>{calls.push(params);return {features:1};};
          window.navigateAssistantRegion=async(region)=>{
            document.dispatchEvent(new Event('alytha-area-cleared'));
            window.testContext={municipality_code:region.code,revision:1};
            return true;
          };
          window.storageJson=async()=>window.testResponse;
        ''')
        page.add_script_tag(path=str(Path('web/agri-assistant.js').resolve()))
        page.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")
        def ask(action):
            page.evaluate('(action)=>{window.testResponse={answer:"Solicitando consulta",sources:[],limitations:[],map_year:2025,action};}',action)
            page.locator('#ai-prompt').fill('Pedido de teste')
            page.locator('#ai-prompt-submit').click()
            page.wait_for_function("!document.getElementById('ai-prompt-submit').disabled")
        ask({'kind':'analyze_area','class_ids':[]})
        assert page.evaluate("calls.includes('history')")
        ask({'kind':'update_monitoring','class_ids':[]})
        assert page.evaluate("calls.includes('monitoring')")
        ask({'kind':'select_region','class_ids':[39], 'region':{'kind':'municipality','code':'5107909','name':'Sinop','uf':'MT'}})
        page.wait_for_function("calls.some(c=>c.municipality_code==='5107909' && c.class_ids[0]===39)")
        assert 'Sinop' in page.locator('#ai-prompt-status').inner_text()
        # General concepts work without a selected city.
        page.evaluate("window.testContext={municipality_code:'',revision:2}")
        ask({'kind':'none','class_ids':[]})
        assert 'Solicitando consulta' in page.locator('#ai-prompt-status').inner_text()
        # A conversational cutoff/season survives the unchanged map defaults.
        page.evaluate("""() => {
          window.sent=[];
          window.storageJson=async(path,payload)=>{
            sent.push(payload);
            return {...testResponse,conversation_id:'a'.repeat(64),
              conversation_context:{map_date:'2026-10-04',season:'2026/2027'}};
          };
          testContext.map_date='2026-10-08';
        }""")
        ask({'kind':'none','class_ids':[]})
        ask({'kind':'none','class_ids':[]})
        payload=page.evaluate('sent.at(-1)')
        assert payload['conversation_id']=='a'*64
        assert payload['map_date']=='2026-10-04'
        assert payload['season']=='2026/2027'
        page.evaluate("document.dispatchEvent(new Event('alytha-area-cleared'))")
        ask({'kind':'none','class_ids':[]})
        payload=page.evaluate('sent.at(-1)')
        assert payload['conversation_id'] is None
        assert payload['map_date']=='2026-10-08'
        browser.close()
        print('Assistant browser actions: OK')


if __name__=='__main__':main()
