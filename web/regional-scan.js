/* Official-name lookup and persistent regional collection, independent of map vendor. */
document.addEventListener('DOMContentLoaded',()=>{
  const el=id=>document.getElementById(id);
  let selected=null,job=null,revision=0,poll;
  const search=el('location-search'),choices=el('location-matches'),options=el('location-options'),searchStatus=el('location-search-status');
  let lookupRevision=0,lookupTimer,lookupController,activeOption=-1;
  function closeChoices() {
    clearTimeout(lookupTimer);lookupController?.abort();lookupRevision++;
    choices.hidden=true;search.setAttribute('aria-expanded','false');
    search.removeAttribute('aria-activedescendant');search.removeAttribute('aria-busy');activeOption=-1;
  }
  window.dismissOfficialRegionSuggestions=closeChoices;
  function showChoices(message) {
    options.replaceChildren();activeOption=-1;search.removeAttribute('aria-activedescendant');
    searchStatus.textContent=message;choices.hidden=false;search.setAttribute('aria-expanded','true');
  }
  function navigate(item) {
    closeChoices();window.cancelPendingLocationSearch?.();
    const url=new URL(location.href);url.searchParams.delete('estado');url.searchParams.delete('municipio');
    url.searchParams.set(item.kind==='state'?'estado':'municipio',item.code);
    history.pushState({},'',url);window.dispatchEvent(new PopStateEvent('popstate'));
    el('location-search').value=`${item.name}${item.uf?' / '+item.uf:''}`;
    el('location-matches').hidden=true;
    document.dispatchEvent(new CustomEvent('alytha-map-search',{detail:{municipality_code:item.kind==='municipality'?item.code:'',municipality_name:item.name}}));
  }
  window.navigateAssistantRegion=(item)=>new Promise((resolve,reject)=>{
    if(mapReady && new URL(location.href).searchParams.get(item.kind==='state'?'estado':'municipio')===item.code){resolve();return;}
    const timer=setTimeout(()=>{document.removeEventListener('alytha-region-ready',ready);reject(Error('A localidade está carregando. Aguarde o mapa e solicite a cultura novamente.'));},30000);
    function ready(event){
      if(event.detail.id!==item.code)return;
      clearTimeout(timer);document.removeEventListener('alytha-region-ready',ready);resolve();
    }
    document.addEventListener('alytha-region-ready',ready);
    navigate(item);
  });
  async function lookup(query,isCurrent,submit=false) {
    closeChoices();const current=lookupRevision;
    lookupController=new AbortController();
    showChoices('Consultando localidades no IBGE…');search.setAttribute('aria-busy','true');
    try {
      const response=await fetch('/api/locations/search?q='+encodeURIComponent(query),{signal:lookupController.signal});
      const result=await response.json();
      if(current!==lookupRevision)return true;
      if(!isCurrent()) {closeChoices();return true;}
      if(!response.ok)throw Error(result.error || 'Não foi possível consultar localidades no IBGE. Tente novamente.');
      if(submit && result.exact && result.matches.length===1) {navigate(result.matches[0]);return true;}
      if(!result.matches.length) {
        if(submit)closeChoices();else showChoices('Nenhuma localidade encontrada no IBGE. Tente o nome e a UF.');
        return false;
      }
      showChoices('Localidades do IBGE · escolha para abrir no mapa');
      for(const [index,item] of result.matches.entries()) {
        const button=document.createElement('button');button.type='button';button.tabIndex=-1;
        button.id=`location-option-${current}-${index}`;button.setAttribute('role','option');button.setAttribute('aria-selected','false');
        button.textContent=`${item.name} / ${item.uf} · ${item.kind==='state'?'Estado':'Município'}`;
        button.addEventListener('click',()=>navigate(item));options.append(button);
      }
      if(result.truncated)searchStatus.textContent+=' · refine com o nome e a UF para ver mais opções';
      return true;
    } catch(error) {
      if(current!==lookupRevision || !isCurrent() || error.name==='AbortError')return true;
      showChoices(error.message);
      if(submit)throw error;
      return false;
    } finally {if(current===lookupRevision)search.removeAttribute('aria-busy');}
  }
  window.searchOfficialRegion=(query,isCurrent)=>lookup(query,isCurrent,true);
  function suggest(delay=250) {
    closeChoices();const query=search.value.trim();
    // Coordinates and punctuation are handled by the map search, not the locality lookup.
    if(query.length<2 || query.length>120 || (!/[\p{L}]/u.test(query) && !/^\d{2,7}$/.test(query)))return;
    lookupTimer=setTimeout(()=>{
      if(document.activeElement===search)lookup(query,()=>search.value.trim()===query && document.activeElement===search);
    },delay);
  }
  search.addEventListener('input',event=>{if(event.isComposing)closeChoices();else suggest();});
  search.addEventListener('compositionend',()=>suggest());
  search.addEventListener('focus',()=>suggest());
  search.addEventListener('search',()=>{if(!search.value)closeChoices();});
  search.closest('.searchbar').addEventListener('focusout',event=>{
    if(!event.currentTarget.contains(event.relatedTarget))closeChoices();
  });
  document.addEventListener('pointerdown',event=>{if(!search.closest('.searchbar').contains(event.target))closeChoices();});
  window.handleOfficialRegionKeydown=event=>{
    if(event.key==='Escape') {closeChoices();return true;}
    if(event.key==='Tab') {closeChoices();return false;}
    const buttons=[...options.querySelectorAll('button')];
    if(event.key==='Enter' && !choices.hidden && activeOption>=0) {
      event.preventDefault();buttons[activeOption].click();return true;
    }
    if(event.key!=='ArrowDown' && event.key!=='ArrowUp')return false;
    event.preventDefault();
    if(choices.hidden) {suggest(0);return true;}
    if(!buttons.length)return true;
    activeOption=activeOption<0 ? (event.key==='ArrowDown'?0:buttons.length-1) : (activeOption+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;
    buttons.forEach((button,index)=>button.setAttribute('aria-selected',String(index===activeOption)));
    search.setAttribute('aria-activedescendant',buttons[activeOption].id);buttons[activeOption].scrollIntoView({block:'nearest'});
    return true;
  };
  function render(value) {
    job=value;
    const cities=job.cities || [], ready=cities.filter(c=>c.status==='ready').length;
    const partial=cities.filter(c=>c.status==='partial').length, failed=cities.filter(c=>c.status==='error').length;
    el('regional-scan-status').textContent=job.status==='error'?job.error:`${job.processed || 0}/${job.total || 0} municípios processados · ${ready} completos · ${partial} parciais · ${failed} com falha${job.status==='loading'?' · coleta em andamento.':' · rodada encerrada.'} Rodada iniciada em ${job.parameters.as_of.split('-').reverse().join('/')}.`;
    if(job.phase==='localities')el('regional-scan-status').textContent='Identificando municípios no IBGE…';
    el('retry-regional-scan').disabled=job.status==='loading';
    el('export-regional-scan').disabled=!cities.length;
    el('regional-scan-results').replaceChildren();
    const active=cities.find(c=>c.status==='loading');
    const visible=[...(active?[active]:[]),...cities.filter(c=>c!==active).slice(0,24)];
    for(const city of visible) {
      const row=document.createElement('p');
      const states={queued:'na fila',loading:'coletando',ready:'pronto',partial:'parcial',error:'falha'};
      row.textContent=`${city.name} · ${states[city.status] || city.status}${city.activity?.total?` · ${city.activity.processed || 0}/${city.activity.total} recortes recentes`:''}${city.history?.observations?` · ${city.history.observations} leituras no histórico de referência`:''}`;
      const sources={ready:'pronto',loading:'coletando',partial:'parcial',error:'falha',unavailable:'indisponível',not_applicable:'sem referência de soja',insufficient:'dados insuficientes'};
      for(const [key,label] of [['dossier','Base municipal'],['activity','Atividade recente'],['history','Histórico do recorte'],['learning','Perfis exploratórios']]) {
        const child=city[key];if(!child)continue;
        const line=document.createElement('span');line.style.display='block';
        line.textContent=`${label}: ${sources[child.status] || child.status}${child.as_of?' · até '+child.as_of.split('-').reverse().join('/'):''}${key==='history' && child.area_ha?' · '+child.area_ha.toLocaleString('pt-BR',{maximumFractionDigits:2})+' ha':''}${child.note?' · '+child.note:''}`;
        row.append(line);
      }
      if(city.error)row.append(document.createTextNode(' · '+city.error));
      const open=document.createElement('button');open.type='button';open.textContent='Abrir cidade';
      open.addEventListener('click',()=>navigate({kind:'municipality',code:city.code,name:city.name,uf:city.uf}));row.append(open);
      if(city.history?.id) {
        const historyButton=document.createElement('button');historyButton.type='button';historyButton.textContent='Histórico de referência';
        historyButton.addEventListener('click',()=>document.dispatchEvent(new CustomEvent('alytha-open-regional-history',{detail:{id:city.history.id,code:city.code,name:city.name}})));
        row.append(historyButton);
      }
      el('regional-scan-results').append(row);
    }
    if(cities.length>visible.length) {const note=document.createElement('p');note.textContent=`Exibindo ${visible.length} de ${cities.length} municípios. O relatório exportado contém todos.`;el('regional-scan-results').append(note);}
  }
  async function watch(value,current) {
    if(current!==revision)return;
    render(value);
    if(value.status==='loading')poll=setTimeout(async()=>{
      try {await watch(await storageJson('/api/regional-scans/'+value.id),current);}
      catch(error) {if(current===revision){el('regional-scan-status').textContent=error.message;el('retry-regional-scan').disabled=false;}}
    },4000);
  }
  async function start(item) {
    selected=item;job=null;const current=++revision;clearTimeout(poll);
    el('regional-scan-panel').open=true;
    el('side-panel').classList.remove('closed');el('panel-toggle').setAttribute('aria-expanded','true');
    el('regional-scan-status').textContent='Preparando a coleta da região…';
    el('regional-scan-results').replaceChildren();el('export-regional-scan').disabled=true;el('retry-regional-scan').disabled=true;
    try {await watch(await storageJson('/api/regional-scans',item),current);}
    catch(error) {if(current===revision){el('regional-scan-status').textContent=error.message;el('retry-regional-scan').disabled=false;}}
  }
  document.addEventListener('alytha-region-ready',event=>{
    const item={kind:event.detail.kind==='states'?'state':'municipality',code:event.detail.id};
    if(selected?.kind===item.kind && selected?.code===item.code)return;
    start(item);
  });
  // Invalidate pending responses immediately, before the next map boundary finishes loading.
  function invalidate() {
    selected=null;job=null;revision++;clearTimeout(poll);
    el('regional-scan-results').replaceChildren();el('export-regional-scan').disabled=true;el('retry-regional-scan').disabled=true;
    el('regional-scan-status').textContent='Aguardando a localidade selecionada…';
  }
  for(const id of ['state-select','municipality-select'])el(id).addEventListener('change',invalidate);
  window.addEventListener('popstate',invalidate);
  el('retry-regional-scan').addEventListener('click',()=>{if(selected)start(selected);});
  el('export-regional-scan').addEventListener('click',()=>{
    if(!job)return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(job,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download=`coleta-${job.parameters.code}-${job.parameters.as_of}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
});
