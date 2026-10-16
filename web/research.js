let researchHistory=null, researchPoll, researchRevision=0, researchAnalysisRevision=0;

document.addEventListener('DOMContentLoaded',()=>{
  const el=id=>document.getElementById(id);
  let requestedCity=null,modelRevision=0;
  function satelliteStatus(model) {
    el('satellite-model-status').textContent=model ? `${model.areas.toLocaleString('pt-BR')} recortes com leituras recentes suficientes · ${model.profiles.length} perfis de vegetação · ${model.atypical_areas.toLocaleString('pt-BR')} recortes com comportamento diferente do conjunto. ${model.collection_complete ? 'Coleta concluída.' : 'Leitura parcial: atualize os padrões quando a coleta terminar.'} Base até ${model.period.to.split('-').reverse().join('/')}.` : 'O aprendizado usa somente as imagens já coletadas da cidade. Não precisa preencher registros de campo.';
    el('satellite-profiles').replaceChildren();
    (model?.profiles || []).forEach(profile=>{
      const line=document.createElement('p');
      line.textContent=`${profile.label}: ${profile.areas.toLocaleString('pt-BR')} recortes · ${profile.area_ha.toLocaleString('pt-BR',{maximumFractionDigits:0})} ha. ${profile.id===1 ? 'Grupo com menor presença média de vegetação no conjunto.' : profile.id===model.profiles.length ? 'Grupo com maior presença média de vegetação no conjunto.' : ''}`;
      el('satellite-profiles').append(line);
    });
  }
  async function modelStatus() {
    const current=++modelRevision;
    const code=el('municipality-select').value || new URL(location.href).searchParams.get('municipio') || '';
    const status=await storageJson('/api/research/status'+(code?'?municipality_code='+encodeURIComponent(code):'')),ml=status.ml;
    if(current!==modelRevision)return status;
    satelliteStatus(code?status.satellite:null);
    el('model-status').textContent=ml.model ? `A análise também usa ${ml.model.events} situações de manejo confirmadas. Ainda precisa ser conferida em outras áreas antes de apoiar decisões de manejo.` : `Recurso opcional para quem possui informações de manejo: ${ml.events} situações confirmadas em ${ml.areas} áreas. Este modelo exige 30 situações em 3 áreas, com 2 etapas diferentes e 5 exemplos de cada etapa. A leitura e o aprendizado por satélite funcionam sem esses registros.`;
    el('train-management-model').disabled=ml.events<30 || ml.areas<3;
    return status;
  }
  async function analysis(date) {
    if(!researchHistory) return;
    const revision=researchRevision,id=researchHistory.id,analysisRevision=++researchAnalysisRevision;
    const result=await storageJson('/api/research/analyze',{dataset_id:id,date});
    if(revision!==researchRevision || researchHistory?.id!==id || analysisRevision!==researchAnalysisRevision) return;
    const readings={
      inconclusivo:'Ainda não há leitura suficiente para interpretar o manejo da área.',
      emergencia:'A vegetação aumentou depois de um período com pouco verde. Pode ser início do desenvolvimento da cultura, rebrota ou plantas espontâneas.',
      desenvolvimento:'A área apresentou aumento do vigor da vegetação, compatível com desenvolvimento vegetal.',
      colheita:'O vigor caiu depois de um período com mais vegetação. Pode estar relacionado à colheita ou a outro evento de perda de vegetação.',
      solo_exposto:'A área manteve pouco sinal de vegetação. Pode haver solo exposto, pós-colheita ou pousio; o satélite sozinho não diferencia essas situações.'
    };
    el('research-analysis').textContent=`${readings[result.baseline.stage] || result.baseline.label} ${result.historical_comparison?.reading || ''} ${result.model_prediction ? `A análise baseada nos registros de campo sugere ${result.model_prediction.label.toLowerCase()}, ainda sem confirmação.` : ''}`;
    el('research-analysis-method').textContent=`${result.baseline.reason}${result.vegetation_patterns ? ` O histórico foi separado em ${result.vegetation_patterns.groups.length} grupos de comportamento da vegetação. Esses grupos não identificam etapas de manejo.` : ''}${result.model_prediction ? ` Resultado experimental do modelo: ${result.model_prediction.label}; pontuação ${(result.model_prediction.probability_uncalibrated*100).toLocaleString('pt-BR',{maximumFractionDigits:0})}%, que não representa uma chance comprovada de acerto.` : ' A interpretação utiliza somente a evolução observada pelo satélite; as hipóteses de manejo não são confirmações.'}`;
  }
  function chartYear(syncDates=false) {
    if(!researchHistory) return;
    const year=el('research-year').value;
    const points=researchHistory.points.filter(p=>year==='all' || p.date.startsWith(year)).slice().sort((a,b)=>a.date.localeCompare(b.date));
    clearLocalNdvi();
    renderNdvi(points,{historyPoints:researchHistory.points});el('ndvi-panel').classList.add('visible');
    document.querySelector('#ndvi-panel .analysis-subtitle').textContent=`Recorte em ${researchHistory.parameters.municipality_code} · ${year==='all'?'histórico completo':'vegetação em '+year} · cada leitura reúne até 5 dias de imagens. Períodos sem leitura não foram estimados.`;
    if(syncDates && points.length)setObservationPeriod(points[0].date,points.at(-1).date);
    setNdviStatus(`${points.length} leituras do satélite. Compare os períodos de aumento e queda da vegetação com os outros anos disponíveis.`);
    const cutoff=points.length ? points[points.length-1].date : `${year}-12-31`;
    analysis(cutoff).catch(error=>el('research-analysis').textContent=error.message);
  }
  async function watch(history,revision) {
    if(revision!==researchRevision) return;
    const firstLoad=researchHistory?.id!==history.id;
    researchHistory=history;
    document.dispatchEvent(new CustomEvent('alytha-history-ready',{detail:history}));
    const previous=el('research-year').value;
    el('research-year').replaceChildren();
    if(history.points.length)el('research-year').add(new Option('Todo o histórico','all'));
    (history.years || []).filter(y=>y.status==='ready').forEach(y=>el('research-year').add(new Option(`${y.year} · ${y.observations} leituras`,y.year)));
    el('research-year').disabled=!el('research-year').options.length;
    if([...el('research-year').options].some(o=>o.value===previous)) el('research-year').value=previous;
    else if(el('research-year').options.length) el('research-year').value='all';
    el('research-status').textContent=`${history.processed}/${history.total} anos consultados · ${history.points.length} leituras da vegetação${history.status==='loading' ? ' · carregando…' : history.status==='partial' ? ' · alguns anos indisponíveis' : ''}`;
    if(history.points.length) chartYear(firstLoad);
    if(history.status==='loading') researchPoll=setTimeout(async()=>{
      try {await watch(await storageJson(`/api/research/history/${history.id}`),revision);}catch(error){if(revision===researchRevision)el('research-status').textContent=error.message;}
    },3000);
    else if(history.error) el('research-status').textContent=history.error;
  }
  async function start(button,pilot) {
    button.disabled=true;clearTimeout(researchPoll);const revision=++researchRevision;
    el('research-status').textContent='Preparando o histórico da área…';
    try {
      if(!pilot && (!fieldLoaded || drawingArea)) throw Error('Selecione ou conclua uma área primeiro.');
      const code=el('municipality-select').value || new URL(location.href).searchParams.get('municipio');
      requestedCity=pilot?'5107925':code;
      if(!pilot && !code)throw Error('Selecione o município da área antes de abrir o histórico.');
      const history=await storageJson(pilot?'/api/research/pilot':'/api/research/history',pilot ? {start_year:2018} : {geojson:await fieldGeojson(),municipality_code:code,start_year:Number(el('research-start-year').value)});
      if(revision!==researchRevision)return;
      if(pilot) {
        const ready=new Promise(resolve=>{
          const listener=event=>{if(event.detail.kind==='municipalities' && event.detail.id==='5107925'){clearTimeout(timeout);document.removeEventListener('alytha-region-ready',listener);resolve();}};
          const timeout=setTimeout(()=>{document.removeEventListener('alytha-region-ready',listener);resolve();},20000);
          document.addEventListener('alytha-region-ready',listener);
        });
        const url=new URL(location.href);url.searchParams.delete('estado');url.searchParams.set('municipio','5107925');historyPush(url);
        await ready;
        if(mapReady && revision===researchRevision) selectAnalysisArea({type:'Feature',properties:{},geometry:history.parameters.geometry},'Referência do piloto Sorriso');
      }
      localStorage.setItem('cropsense-research-history',history.id);
      await watch(history,revision);
    } catch(error) {if(revision===researchRevision)el('research-status').textContent=error.message;}
    finally {if(revision===researchRevision)requestedCity=null;button.disabled=false;}
  }
  function historyPush(url) {window.history.pushState({},'',url);window.dispatchEvent(new PopStateEvent('popstate'));}
  el('start-sorriso-pilot').addEventListener('click',event=>start(event.currentTarget,true));
  el('start-area-history').addEventListener('click',event=>start(event.currentTarget,false));
  el('research-year').addEventListener('change',chartYear);
  el('learn-satellite-patterns').addEventListener('click',async event=>{
    const button=event.currentTarget;button.disabled=true;
    el('satellite-model-status').textContent='Comparando as leituras da cidade e aprendendo padrões de vegetação…';
    try {
      const code=el('municipality-select').value || new URL(location.href).searchParams.get('municipio');
      if(!code)throw Error('Selecione uma cidade para aprender seus padrões.');
      satelliteStatus(await storageJson('/api/research/satellite-learning',{municipality_code:code}));
    }
    catch(error){el('satellite-model-status').textContent=error.message;}
    finally{button.disabled=false;}
  });
  el('save-field-event').addEventListener('click',async event=>{
    const button=event.currentTarget;button.disabled=true;
    try {
      if(!researchHistory) throw Error('Carregue o histórico da área primeiro.');
      if(el('field-evidence-panel').dataset.historyId!==researchHistory.id) throw Error('A área mudou. Abra o histórico da área atual antes de registrar uma observação.');
      await storageJson('/api/research/events',{dataset_id:researchHistory.id,from:el('event-from').value,to:el('event-to').value,stage:el('event-stage').value,note:el('event-note').value});
      el('event-status').textContent='Registro de campo salvo.';
      document.dispatchEvent(new CustomEvent('alytha-field-event-saved'));
      await modelStatus();
    }catch(error){el('event-status').textContent=error.message;}finally{button.disabled=!el('field-evidence-panel').dataset.historyId;}
  });
  el('train-management-model').addEventListener('click',async event=>{
    const button=event.currentTarget;button.disabled=true;el('model-status').textContent='Treinando e validando por área…';
    try{await storageJson('/api/research/train',{});await modelStatus();if(researchHistory)await analysis();}
    catch(error){el('model-status').textContent=error.message;}finally{button.disabled=false;}
  });
  document.addEventListener('alytha-show-history',()=>{el('research-panel').open=true;if(researchHistory)chartYear();});
  document.addEventListener('alytha-open-regional-history',async event=>{
    clearTimeout(researchPoll);const revision=++researchRevision;
    el('research-panel').open=true;
    el('research-status').textContent='Abrindo histórico de referência…';
    try {
      const {id,code,name}=event.detail;
      requestedCity=code;
      if(el('municipality-select').value!==code) {
        const ready=new Promise((resolve,reject)=>{
          const listener=e=>{if(e.detail.kind==='municipalities' && e.detail.id===code){clearTimeout(timeout);document.removeEventListener('alytha-region-ready',listener);resolve();}};
          const timeout=setTimeout(()=>{document.removeEventListener('alytha-region-ready',listener);reject(Error('Não foi possível abrir a cidade. Tente novamente.'));},30000);
          document.addEventListener('alytha-region-ready',listener);
        });
        const url=new URL(location.href);url.searchParams.delete('estado');url.searchParams.set('municipio',code);historyPush(url);
        await ready;
      }
      const loaded=await storageJson('/api/research/history/'+id);
      if(revision!==researchRevision)return;
      selectAnalysisArea({type:'Feature',properties:{},geometry:loaded.parameters.geometry},`Referência histórica · ${name}`);
      localStorage.setItem('cropsense-research-history',id);
      await watch(loaded,revision);await modelStatus();
    } catch(error){if(revision===researchRevision)el('research-status').textContent=error.message;}
    finally {if(revision===researchRevision)requestedCity=null;}
  });
  document.addEventListener('alytha-region-ready',event=>{
    const code=event.detail.kind==='municipalities'?event.detail.id:null;
    if(researchHistory && researchHistory.parameters.municipality_code!==code && requestedCity!==code) {
      researchHistory=null;researchRevision++;clearTimeout(researchPoll);
      el('research-year').disabled=true;el('research-analysis').textContent='';
      el('research-status').textContent='Abra um histórico da localidade atual.';
      document.dispatchEvent(new Event('alytha-history-cleared'));
    }
    modelStatus().catch(error=>el('satellite-model-status').textContent=error.message);
  });
  const initialRevision=researchRevision;
  document.addEventListener('alytha-learning-history',event=>{
    const history=event.detail;
    if(!researchHistory || researchHistory.parameters.area_key!==history.parameters.area_key)return;
    clearTimeout(researchPoll);
    localStorage.setItem('cropsense-research-history',history.id);
    watch(history,++researchRevision).catch(error=>el('research-status').textContent=error.message);
  });
  modelStatus().then(async status=>{
    if(researchRevision!==initialRevision) return;
    const id=localStorage.getItem('cropsense-research-history') || status.pilot?.dataset_id;
    if(id)try{
      const loaded=await storageJson(`/api/research/history/${id}`);
      const code=new URL(location.href).searchParams.get('municipio');
      const state=new URL(location.href).searchParams.get('estado');
      if((!code && !state) || loaded.parameters.municipality_code===code)await watch(loaded,++researchRevision);
    }catch{localStorage.removeItem('cropsense-research-history');}
  }).catch(error=>el('model-status').textContent=error.message);
});
