/* Consolidation and LLM review are distinct, explicit phases. */
document.addEventListener('DOMContentLoaded',()=>{
  const panel=document.getElementById('regional-learning-panel');
  if(!panel)return;
  const el=id=>document.getElementById(id);
  let loading=false, data=null;
  async function request(path,payload) {
    const response=await fetch(path,payload===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const value=await response.json();if(!response.ok)throw Error(value.error || 'Operação indisponível.');return value;
  }
  function render(value) {
    data=value;
    const totals=value.base?.totals;
    el('regional-base-status').textContent=value.build.status==='building'?'Consolidando a base local. As versões anteriores continuam preservadas.':totals?
      `${totals.municipalities} municípios no inventário · ${totals.processed_municipalities} processados · ${totals.municipalities_with_data} com dados · ${totals.areas_with_observations} recortes com observações · ${totals.feature_windows} janelas de ML.`:
      value.build.status==='error'?'A consolidação ficou pendente; a base anterior foi preservada.':'A base regional ainda não foi consolidada.';
    el('regional-ai-status').textContent=totals?`${value.ai_enabled?'Fila da Alytha ativa':'Base preparada · fila da Alytha pausada'} · análise visual por recorte · ${totals.municipalities_with_data} cidades com base preparada · ${value.queue.blocked || 0} cidades sem dados.${value.backoff_until && Date.parse(value.backoff_until)>Date.now()?' Provedor em espera até '+new Date(value.backoff_until).toLocaleString('pt-BR')+'.':''}`:'Consolide os dados antes de iniciar a IA.';
    if(value.visual && el('regional-visual-status')) {
      const q=value.visual.queue;
      el('regional-visual-status').textContent=`Análise visual por recorte: ${q.ready || 0} concluídas · ${q.pending || 0} com imagens em preparação · ${q.waiting_images || 0} aguardando imagens reais · ${q.retry || 0} pendentes da IA. ${value.visual.assets} imagens preparadas. A revisão visual é separada do resumo textual municipal.`;
    }
    el('build-regional-base').disabled=value.build.status==='building';
    el('toggle-regional-ai').disabled=!totals;
    el('toggle-regional-ai').textContent=value.ai_enabled?'Pausar análises da Alytha':'Iniciar análises da Alytha sobre esta base';
    el('regional-base-downloads').hidden=!totals;
    const body=el('regional-base-cities');
    if(body) {
      const filter=el('regional-base-filter').value.trim().toLocaleLowerCase('pt-BR');
      const rows=(value.base?.municipalities || []).filter(c=>(c.name+' '+c.uf).toLocaleLowerCase('pt-BR').includes(filter));
      body.replaceChildren();
      const readiness={temporal_data:'Características temporais disponíveis',observations_only:'Leituras ainda insuficientes para janelas',context_only:'Contexto disponível; sem série aproveitável',no_data:'Aguardando dados'};
      const states={pending:'Aguardando IA',blocked:'Sem dados para revisão',ready:'Revisão disponível',running:'Em análise',retry:'Nova tentativa pendente',waiting_images:'Aguardando imagens reais',partial_review:'Revisão visual parcial'};
      for(const city of rows.slice(0,150)) {
        const row=document.createElement('tr');
        for(const text of [city.name+' / '+city.uf,readiness[city.readiness],String(city.areas_with_observations),String(city.feature_windows),states[city.ai_status] || 'Aguardando IA']) {
          const cell=document.createElement('td');cell.textContent=text;row.append(cell);
        }
        body.append(row);
      }
      el('regional-base-count').textContent=`${rows.length} municípios · exibindo até 150. O manifesto contém o inventário completo.`;
    }
  }
  async function refresh() {
    if(loading)return;loading=true;
    try {render(await request('/api/regional-learning'));}
    catch(error){el('regional-base-status').textContent=error.message;}
    finally{loading=false;}
  }
  el('build-regional-base').addEventListener('click',async()=>{
    el('build-regional-base').disabled=true;
    try{render(await request('/api/regional-learning/build',{}));}
    catch(error){el('regional-base-status').textContent=error.message;el('build-regional-base').disabled=false;}
  });
  el('toggle-regional-ai').addEventListener('click',async()=>{
    el('toggle-regional-ai').disabled=true;
    try{render(await request('/api/regional-learning/configure',{ai_enabled:!data.ai_enabled}));}
    catch(error){el('regional-ai-status').textContent=error.message;el('toggle-regional-ai').disabled=false;}
  });
  el('regional-base-filter')?.addEventListener('input',()=>{if(data)render(data);});
  refresh();setInterval(()=>{if(!document.hidden)refresh();},15000);
});
