let agriculturalLayer, agriculturalFeatures = [], cropRequest = 0;
let inactivePoll;
// Product palette shared by filters, map layers and municipal indicators.
const CROP_COLORS = {39:'#d6a316',20:'#269b65',40:'#3b82f6',62:'#a855f7',46:'#a66b44',47:'#f97316',35:'#db2777',41:'#14b8a6',48:'#64748b'};
function cropColor(classId) { return CROP_COLORS[classId] || '#64748b'; }
function featureColor(properties) { return properties.possible_inactive ? '#e76f51' : cropColor(properties.class_id); }
const cropDataCache = new Map();
const cropWanted=new Map();
const cropRequestOwner=(()=>{const key='alytha-crop-request-owner';let value=sessionStorage.getItem(key);if(!value){value=crypto.randomUUID();sessionStorage.setItem(key,value);}return value;})();
async function cropMapJson(url, payload) {
  try {
    const response = await fetch(url, {method:payload ? 'POST' : 'GET',headers:payload ? {'Content-Type':'application/json'} : undefined,body:payload ? JSON.stringify(payload) : undefined,signal:AbortSignal.timeout(15000)});
    const result = await response.json();
    if(!response.ok) throw new Error(result.error || 'Não foi possível consultar as culturas do mapa.');
    return result;
  } catch(error) {
    if(error.name==='TimeoutError' || error.name==='AbortError') throw new Error('A conexão com o mapa demorou para responder. Envie o pedido novamente para retomar a consulta.');
    if(error instanceof TypeError) throw new Error('A conexão com o mapa foi interrompida. Confira sua conexão e envie o pedido novamente para retomar a consulta.');
    throw error;
  }
}
async function loadCropData(payload,onProgress=()=>{}) {
  const wantedKey=JSON.stringify(payload);
  const current=()=>cropWanted.get(payload.class_id)===wantedKey;
  onProgress('Consultando as culturas históricas da região…');
  let job=await cropMapJson('/api/sources/mapbiomas/jobs',{...payload,request_owner:cropRequestOwner});
  const started=Date.now();
  while(job.status==='loading') {
    if(!current())throw Error('Consulta substituída por outro enquadramento do mapa.');
    onProgress(job.phase==='waiting' || job.phase==='queued'?'Consulta na fila. O mapa vai carregar automaticamente quando houver uma vaga…':'Preparando as manchas de culturas. Esta consulta pode levar alguns minutos…');
    if(!/^[a-f0-9]{64}$/.test(job.id))throw new Error('Não foi possível acompanhar a consulta de culturas. Tente novamente.');
    if(Date.now()-started>=600000)throw new Error('O mapa de culturas ainda está sendo preparado. Envie o pedido novamente para acompanhar a mesma consulta.');
    await new Promise(resolve=>setTimeout(resolve,1500));
    job=await cropMapJson('/api/sources/mapbiomas/jobs/'+job.id);
    if(job.status==='superseded' && current())job=await cropMapJson('/api/sources/mapbiomas/jobs',{...payload,request_owner:cropRequestOwner});
  }
  if(job.status!=='ready')throw new Error(job.error || 'Não foi possível carregar as culturas do mapa. Tente novamente.');
  return job.result;
}
function cropData(payload,onProgress) {
  const key = JSON.stringify(payload);
  cropWanted.set(payload.class_id,key);
  if (!cropDataCache.has(key)) {
    const request = loadCropData(payload,onProgress)
      .catch(error => { cropDataCache.delete(key); throw error; });
    cropDataCache.set(key,request);
    if(cropDataCache.size>40) cropDataCache.delete(cropDataCache.keys().next().value);
  }
  return cropDataCache.get(key);
}

function clearAgriculturalResults() {
  cropWanted.clear();
  window.mapLoading?.cancel('culturas');
  cropRequest++;
  clearTimeout(inactivePoll);
  if (mapReady) removeMapLayer(agriculturalLayer);
  agriculturalLayer = null; agriculturalFeatures = [];
  const legend=document.getElementById('crop-class-legend');if(legend)legend.hidden=true;
  const select = document.getElementById('mapbiomas-candidates');
  select.replaceChildren(new Option('Marque uma cultura para visualizar áreas','')); select.disabled = true;
}

function useAgriculturalArea(index) {
  const feature = agriculturalFeatures[index];
  if (!feature || drawingArea) return;
  const p = feature.properties, name = `${p.class_name} · mapa ${p.year} · ${p.area_ha} ha`;
  selectAnalysisArea(feature, name);
  selectedAreaProvenance = { ...p };
  if(p.class_id===39 && !p.overview) document.dispatchEvent(new CustomEvent('alytha-soy-selected',{detail:feature}));
  document.getElementById('area-name').value = name;
  document.getElementById('area-crop').value = 'Não confirmada';
  document.getElementById('area-season').value = 'Não confirmada';
  document.getElementById('area-details').textContent = `${name}. MapBiomas histórico · ${p.resolution_m} m.${p.overview ? ' Visão geral aproximada; aproxime o mapa para selecionar uma área em detalhe.' : ''} Confirme cultura e safra antes de salvar.`;
  if(p.evidence) {
    document.getElementById('selected-area-tools').open=true;
    document.getElementById('area-details').textContent=`${p.area_ha} ha · última observação ${p.evidence.latest_date} · NDVI ${p.evidence.latest_ndvi.toFixed(3)}. ${p.evidence.reason}`;
    renderNdvi(p.evidence.points); document.getElementById('ndvi-panel').classList.add('visible');
    document.querySelector('#ndvi-panel .analysis-subtitle').textContent='Três leituras recentes da vegetação, cada uma com pelo menos metade da área avaliada. Confira a situação no campo.';
    setNdviStatus('Possível ausência de lavoura ativa. Não confirma área vazia ou disponibilidade para plantio.');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const el = id => document.getElementById(id);
  const cropLegend=document.createElement('aside');cropLegend.id='crop-class-legend';cropLegend.className='map-legend';cropLegend.hidden=true;cropLegend.setAttribute('aria-label','Culturas do mapa histórico');document.querySelector('.map-card').append(cropLegend);
  el('inactive-soy-filter').checked=false;
  document.querySelectorAll('input[name="map-crop"]').forEach(input => { input.checked = false; input.closest('label').style.setProperty('--crop-color',cropColor(input.value)); });
  for (let year = 2025; year >= 1985; year--) el('mapbiomas-year').add(new Option(year, year));
  async function run(button, status, task, revision, propagate=false) {
    const work=status.id==='mapbiomas-status'?window.mapLoading?.begin('culturas','Carregando culturas no mapa'):null;
    let failed=false;
    if(button) button.disabled = true;
    status.setAttribute('aria-busy','true'); status.textContent = 'Buscando dados…';
    try { return await task(work); } catch (error) {failed=true;if (revision === undefined || revision === cropRequest){status.textContent = error.message;work?.fail(error.message);}else work?.cancel();if(propagate)throw error; }
    finally { if (revision === undefined || revision === cropRequest) { if(button) button.disabled = false; status.setAttribute('aria-busy','false');if(!failed && !el('inactive-soy-filter').checked)work?.finish(status.textContent); }else work?.cancel(); }
  }
  function updateCropMap(propagate=false,isCurrent=()=>true) {
    clearTimeout(inactivePoll);
    const revision = ++cropRequest;
    return run(null, el('mapbiomas-status'), async (work) => {
    if (!mapReady || drawingArea) throw new Error('Aguarde o mapa e conclua o desenho primeiro.');
    const classes = [...document.querySelectorAll('input[name="map-crop"]:checked')].map(input => Number(input.value));
    for(const classId of cropWanted.keys())if(!classes.includes(classId))cropWanted.delete(classId);
    if (!classes.length) { el('mapbiomas-status').textContent = 'Marque uma cultura para visualizar suas áreas.'; return; }
    const b = map.getBounds(), sw = b.getSouthWest(), ne = b.getNorthEast();
    const bounds = openMap ? [sw.lng,sw.lat,ne.lng,ne.lat] : [sw.lng(),sw.lat(),ne.lng(),ne.lat()];
    const municipality_code=window.agriAssistantContext?.().municipality_code || el('municipality-select').value || undefined;
    const state_code=!municipality_code ? el('state-select').value || new URL(location.href).searchParams.get('estado') || undefined : undefined;
    if(el('inactive-soy-filter').checked) {
      const job=await storageJson('/api/inactive-soy',{bounds,municipality_code,year:Number(el('mapbiomas-year').value)});
      if(revision===cropRequest) pollInactive(job,revision);
      return;
    }
    const results = [];
    let pending = classes.length;
    const tasks = classes.map(async class_id => {
      const result = await cropData({bounds,municipality_code,state_code,year:Number(el('mapbiomas-year').value),class_id},message=>{if(revision===cropRequest)work?.update(message);});
      results.push({...result,class_id}); pending--;
      if(revision===cropRequest && pending)work?.update(`${classes.length-pending}/${classes.length} culturas carregadas. Aguardando as demais…`);
      if (revision === cropRequest && isCurrent()) renderCropResults(results,pending);
    });
    const settled = await Promise.allSettled(tasks);
    if (revision !== cropRequest || !isCurrent()) return null;
    if(results.length) renderCropResults(results,0);
    const failures=settled.filter(item => item.status === 'rejected');
    if(failures.length) {el('mapbiomas-status').textContent += ' ' + failures.map(item => item.reason.message).join(' ');throw failures[0].reason;}
    const visible=agriculturalLayer && (openMap?map.hasLayer(agriculturalLayer):agriculturalLayer.getMap()===map);
    if(agriculturalFeatures.length && !visible)throw Error('A fonte retornou áreas, mas a camada não ficou visível no mapa. Tente carregar novamente.');
    return {features:agriculturalFeatures.length,visible:Boolean(visible),year:Number(el('mapbiomas-year').value)};
    }, revision,propagate);
  }
  function renderCropResults(results,pending) {
    const result = {type:'FeatureCollection', features:results.flatMap(item => item.features), year:results[0].year, class_name:results.map(item => item.class_name).join(', '), overview:results.some(item => item.overview), resolution_m:Math.max(...results.map(item => item.resolution_m))};
    removeMapLayer(agriculturalLayer); agriculturalFeatures = result.features;
    agriculturalFeatures.forEach((feature,index) => feature.properties.candidate_index = index);
    if (openMap) agriculturalLayer = L.geoJSON(result, { style:feature => ({color:featureColor(feature.properties),fillColor:featureColor(feature.properties),weight:2,fillOpacity:0.28}), onEachFeature:(feature,layer) => layer.on('click', () => useAgriculturalArea(agriculturalFeatures.indexOf(feature))) }).addTo(map);
    else {
      agriculturalLayer = new google.maps.Data({map}); agriculturalLayer.addGeoJson(result);
      agriculturalLayer.setStyle(feature => ({strokeColor:featureColor({class_id:feature.getProperty('class_id'),possible_inactive:feature.getProperty('possible_inactive')}),strokeWeight:2,fillColor:featureColor({class_id:feature.getProperty('class_id'),possible_inactive:feature.getProperty('possible_inactive')}),fillOpacity:0.28}));
      agriculturalLayer.addListener('click', event => {
        if (drawingArea) { drawingPoints.push([event.latLng.lng(),event.latLng.lat()]); redrawSketch(); return; }
        useAgriculturalArea(event.feature.getProperty('candidate_index'));
      });
    }
    el('mapbiomas-candidates').replaceChildren(new Option('Selecione ou clique em uma mancha no mapa',''));
    result.features.forEach((feature,index) => el('mapbiomas-candidates').add(new Option(`${feature.properties.class_name} · ${feature.properties.area_ha} ha`, index)));
    el('mapbiomas-candidates').disabled = !result.features.length;
    el('mapbiomas-status').textContent = `${result.features.length} áreas · ${result.class_name} · ${result.year}${result.overview ? ` · visão geral (${result.resolution_m} m)` : ' · detalhe de 30 m'}`;
    el('mapbiomas-detail-status').textContent = `Recorte visível${document.getElementById('municipality-select').value ? ' dentro do município' : ''}. Classificação histórica; não confirma a cultura atual.${results.some(item => item.features.length >= 200) ? ' Limite de áreas atingido; aproxime o mapa.' : ''}${result.overview ? ' Visualização aproximada: áreas pequenas podem não aparecer. Aproxime o mapa para o detalhe de 30 m.' : ''}`;
    cropLegend.replaceChildren();
    const title=document.createElement('strong');title.textContent='Culturas mapeadas · '+result.year;cropLegend.append(title);
    for(const item of results) {const row=document.createElement('p');row.textContent=item.class_name;row.style.borderLeft='3px solid '+cropColor(item.class_id || item.features[0]?.properties.class_id || 39);row.style.paddingLeft='6px';cropLegend.append(row);}
    const note=document.createElement('small');note.textContent='Referência histórica · MapBiomas';cropLegend.append(note);cropLegend.hidden=!result.features.length;
    document.dispatchEvent(new Event('alytha-crop-layer-updated'));
    if(pending) el('mapbiomas-status').textContent += ` / Carregando ${pending} cultura(s)...`;
  }
  function pollInactive(job,revision) {
    if(revision!==cropRequest || !el('inactive-soy-filter').checked) return;
    if(job.type==='FeatureCollection') renderCropResults([job],0);
    const unknown=(job.assessed || []).filter(item=>item.status==='unknown').length;
    el('mapbiomas-status').textContent=`${job.features.length} possíveis áreas inativas · ${job.processed}/${job.total ?? job.limit} verificadas${unknown ? ` · ${unknown} sem evidência suficiente` : ''}${job.status==='loading' ? ' · analisando…' : ''}`;
    el('mapbiomas-detail-status').textContent=`Área identificada como soja no mapa de ${job.parameters.year}; a cultura atual precisa ser conferida. A busca avalia até 10 áreas menores na parte do mapa exibida. Em coral: pouco sinal recente de vegetação, sem confirmação de área livre para plantio. A triagem exige três leituras recentes com pelo menos metade da área observada. Pós-colheita, preparo e pousio podem apresentar sinais parecidos; confirme o manejo no campo.`;
    const output=el('inactive-soy-evidence'); output.replaceChildren();
    (job.assessed || []).forEach(item=>{const p=document.createElement('p');p.textContent=`${item.area_ha} ha · ${item.status==='possible_inactive' ? 'possível inatividade' : item.status==='unknown' ? 'inconclusivo' : 'não corresponde'}${item.latest_date ? ` · ${item.latest_date} · NDVI ${item.latest_ndvi.toFixed(3)}` : ''}. ${item.reason}`;output.append(p);});
    if(job.status==='loading') inactivePoll=setTimeout(async()=>{
      try { const result=await storageJson(`/api/inactive-soy/${job.id}`);pollInactive(result,revision); }
      catch(error) { if(revision===cropRequest){el('mapbiomas-status').textContent=error.message;window.mapLoading?.begin('culturas','Analisando atividade no mapa').fail(error.message);} }
    },2500);
    if(job.status==='error') el('mapbiomas-status').textContent=job.error;
    const work=window.mapLoading?.begin('culturas','Analisando atividade no mapa',el('mapbiomas-status').textContent);
    if(job.status==='error')work?.fail(job.error);
    else if(job.status!=='loading')work?.finish(el('mapbiomas-status').textContent);
  }
  el('mapbiomas-candidates').addEventListener('change', event => { if (event.target.value !== '') useAgriculturalArea(Number(event.target.value)); });
  let layersHidden=false;
  window.showCropClasses=async ({class_ids,year,municipality_code,state_code,isCurrent,focus_results=false})=>{
    if(!mapReady || drawingArea)throw Error('Aguarde o mapa e conclua o desenho antes de mostrar a cultura.');
    if(!class_ids.length) {
      layersHidden=true;clearTimeout(viewportTimer);
      const activity=el('soy-map-classes');activity.checked=false;activity.dispatchEvent(new Event('change'));
      el('inactive-soy-filter').checked=false;
      document.querySelectorAll('input[name="map-crop"]').forEach(input=>{input.disabled=false;input.checked=false;});
      clearAgriculturalResults();el('mapbiomas-status').textContent='Camadas de culturas ocultas.';
      return {hidden:true,features:0,year:Number(el('mapbiomas-year').value)};
    }
    const dossier=state_code ? {boundary:await storageJson('/api/locations/boundaries/states/'+state_code)} : await storageJson('/api/municipalities/'+municipality_code);
    if(!isCurrent())return null;
    if(!dossier.boundary)throw Error('A base da cidade ainda está carregando. Tente novamente em instantes.');
    clearTimeout(viewportTimer);layersHidden=true;
    try {
      const activity=el('soy-map-classes');activity.checked=false;activity.dispatchEvent(new Event('change'));
      document.dispatchEvent(new Event('alytha-hide-spatial-layers'));
      if(ndviOverlay){removeMapLayer(ndviOverlay);ndviOverlay=null;}
      el('inactive-soy-filter').checked=false;
      document.querySelectorAll('input[name="map-crop"]').forEach(input=>{input.disabled=false;input.checked=class_ids.includes(Number(input.value));});
      if(year)el('mapbiomas-year').value=String(year);
      clearAgriculturalResults();
      if(openMap)map.fitBounds(L.geoJSON(dossier.boundary).getBounds(),{padding:[40,40],animate:false});
      else await new Promise(resolve=>{let listener;const finish=()=>{clearTimeout(timeout);if(listener)google.maps.event.removeListener(listener);resolve();};const timeout=setTimeout(finish,1500);listener=google.maps.event.addListenerOnce(map,'idle',finish);fitGeojson(dossier.boundary);});
      if(!isCurrent())return null;
      clearTimeout(viewportTimer);
      const shown=await updateCropMap(true,isCurrent);
      if(focus_results && shown?.features && isCurrent()){
        if(openMap)map.fitBounds(agriculturalLayer.getBounds(),{padding:[50,50],animate:false,maxZoom:12});
        else fitGeojson({type:'FeatureCollection',features:agriculturalFeatures});
      }
      return shown;
    } finally {layersHidden=false;if(isCurrent())clearTimeout(viewportTimer);}
  };
  el('clear-mapbiomas').addEventListener('click', () => { layersHidden=true; clearAgriculturalResults(); el('mapbiomas-status').setAttribute('aria-busy','false'); el('mapbiomas-status').textContent = 'Camada oculta. Marque uma cultura para voltar a exibir.'; });
  function filterChanged() {
    layersHidden=false;
    clearAgriculturalResults();
    el('inactive-soy-evidence').replaceChildren();
    if (selectedAreaProvenance.source === 'MapBiomas' &&
        (!document.querySelector(`input[name="map-crop"][value="${selectedAreaProvenance.class_id}"]:checked`) || selectedAreaProvenance.year !== Number(el('mapbiomas-year').value))) clearAnalysisArea();
    el('mapbiomas-status').textContent = 'Filtro alterado. Atualizando áreas…';
    updateCropMap();
  }
  document.querySelectorAll('input[name="map-crop"]').forEach(input => input.addEventListener('change',filterChanged));
  el('mapbiomas-year').addEventListener('change',filterChanged);
  el('inactive-soy-filter').addEventListener('change',event=>{
    document.querySelectorAll('input[name="map-crop"]').forEach(input=>{input.disabled=event.target.checked; if(event.target.checked) input.checked=input.value==='39';});
    filterChanged();
  });
  let viewportTimer, boundMap;
  function bindViewportUpdates() {
    if(!mapReady || boundMap===map) return;
    boundMap=map;
    const changed=()=>{
      clearTimeout(viewportTimer);
      viewportTimer=setTimeout(()=>{
        if(!layersHidden && !drawingArea && document.querySelector('input[name="map-crop"]:checked')) updateCropMap();
      },650);
    };
    if(openMap) map.on('moveend',changed); else map.addListener('idle',changed);
  }
  document.addEventListener('alytha-map-ready',bindViewportUpdates);
  if(mapReady) bindViewportUpdates();
  for (const id of ['state-select','municipality-select']) el(id).addEventListener('change',() => { layersHidden=false; clearTimeout(viewportTimer); clearAgriculturalResults(); el('mapbiomas-status').setAttribute('aria-busy','false'); el('mapbiomas-status').textContent='As culturas selecionadas serão exibidas ao carregar a localidade.'; });
  el('load-conab').addEventListener('click', event => run(event.currentTarget, el('conab-status'), async () => {
    const uf = el('conab-uf').value.trim().toUpperCase(), crop = el('conab-crop').value;
    const result = await storageJson(`/api/sources/conab?uf=${encodeURIComponent(uf)}&crop=${crop}`);
    const table = document.createElement('table'); table.style.fontSize = '10px';
    const row = values => { const tr = document.createElement('tr'); values.forEach(value => { const td = document.createElement('td'); td.textContent = value; td.style.padding = '4px'; tr.append(td); }); table.append(tr); };
    row(['Safra / produto / fase','Área (ha)','Produção (t)','Rendimento (t/ha)']);
    const format = value => value === null ? '—' : value.toLocaleString('pt-BR',{maximumFractionDigits:3});
    result.records.slice(-10).reverse().forEach(record => row([`${record.season} · ${record.crop} · ${record.phase}`,format(record.area_ha),format(record.production_t),format(record.yield_t_ha)]));
    el('conab-results').replaceChildren(table);
    el('conab-status').textContent = `${result.records.length} registros de ${uf}; exibindo os 10 últimos. ${result.note} Importado em ${new Date(result.fetched_at).toLocaleString('pt-BR')}.`;
    const link = document.createElement('a'); link.href = result.source_url; link.textContent = 'Arquivo oficial CONAB'; link.target = '_blank'; link.rel = 'noopener'; el('conab-results').append(link);
  }));
  storageJson('/api/sources/status').then(result => {
    el('load-satveg').disabled = !result.satveg_configured;
    el('satveg-status').textContent = result.satveg_configured ? 'Histórico de vegetação disponível para consulta. Resolução de 250 m; intervalos de 16 dias.' : 'Histórico Embrapa indisponível no momento. Você pode consultar o NDVI Sentinel-2 pela linha do tempo.';
  }).catch(error => el('satveg-status').textContent = error.message);
  el('load-satveg').addEventListener('click', event => run(event.currentTarget, el('satveg-status'), async () => {
    if (!fieldLoaded || drawingArea) throw new Error('Selecione uma área primeiro.');
    const result = await storageJson('/api/sources/satveg', {geojson:await fieldGeojson(),from:dateFrom.value,to:dateTo.value});
    renderNdvi(result.points,{aggregationDays:16}); el('ndvi-panel').classList.add('visible');
    document.querySelector('#ndvi-panel .analysis-subtitle').textContent = 'Histórico Embrapa · cada leitura reúne 16 dias. A imagem é menos detalhada que a do Sentinel-2; evite comparar os valores diretamente.';
    setNdviStatus(`${result.source}: ${result.points.length} observações. ${result.note}`);
    el('satveg-status').textContent = `${result.points.length} observações. ${result.note}`;
  }));
});
