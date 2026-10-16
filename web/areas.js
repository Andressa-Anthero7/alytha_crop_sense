/* Locality navigation and polygon drawing for Google Maps and Leaflet. */
let regionLayer, sketchLayer, drawingArea = false, drawingPoints = [], regionRequest = 0;
let vertexLayers = [];
let municipalPoll, municipalRevision = 0;

function resetMunicipalBase() {
  municipalRevision++; clearTimeout(municipalPoll);
  document.getElementById('municipal-base-results').replaceChildren();
  document.getElementById('municipal-base-status').textContent = 'Escolha uma cidade para consultar o panorama agrícola.';
}

async function prepareMunicipalBase(code) {
  resetMunicipalBase();
  if (!code) return;
  const revision = municipalRevision;
  const status = document.getElementById('municipal-base-status');
  status.textContent = 'Carregando o panorama agrícola do município…';
  async function poll() {
    try {
      const dossier = await locationJson(`/api/municipalities/${code}`);
      if (revision !== municipalRevision) return;
      status.textContent = dossier.status === 'ready' ? `${dossier.name} / ${dossier.uf} · panorama agrícola disponível` : dossier.status === 'partial' ? `${dossier.name} · alguns dados ainda estão indisponíveis` : `${dossier.name || 'Município'} · carregando indicadores agrícolas…`;
      if (dossier.error) status.textContent = dossier.error;
      const output = document.getElementById('municipal-base-results'); output.replaceChildren();
      if (dossier.mapbiomas) {
        const note = document.createElement('p'); note.textContent = `Área cultivada mapeada · ${dossier.mapbiomas.year} · município inteiro`; output.append(note);
        dossier.mapbiomas.classes.filter(item => [39,20,40,62,41,46,47,35,48].includes(item.class_id)).forEach(item => {
          const p = document.createElement('div'); p.className='municipal-metric';
          const label=document.createElement('span'); label.textContent=item.class_name;
          label.style.borderLeft=`3px solid ${cropColor(item.class_id)}`; label.style.paddingLeft='7px';
          const value=document.createElement('strong'); value.textContent=`${item.area_ha.toLocaleString('pt-BR')} ha`;
          p.append(label,value); output.append(p);
        });
        const source=document.createElement('small'); source.textContent='Fonte: MapBiomas · histórico de uso do solo. Não confirma o plantio atual.'; output.append(source);
      }
      if (dossier.uf) document.getElementById('conab-uf').value = dossier.uf;
      if (['queued','loading'].includes(dossier.status)) municipalPoll=setTimeout(poll,3000);
    } catch(error) { if(revision===municipalRevision) status.textContent=error.message; }
  }
  await poll();
}

function clearVertices() {
  vertexLayers.forEach(removeMapLayer);
  vertexLayers = [];
}

function removeMapLayer(layer) {
  if (!layer) return;
  if (openMap) map.removeLayer(layer); else layer.setMap(null);
}

function resetAnalysisResults() {
  removeMapLayer(scenesLayer); scenesLayer = null;
  removeMapLayer(ndviOverlay); ndviOverlay = null;
  if (ndviObjectUrl) URL.revokeObjectURL(ndviObjectUrl);
  ndviObjectUrl = null;
  document.getElementById('items').replaceChildren();
  document.getElementById('count').textContent = '—';
  document.getElementById('ndvi-chart').replaceChildren();
  document.getElementById('ndvi-panel').classList.remove('visible');
}

function clearAnalysisArea(clearFile = true) {
  if (!mapReady) return;
  if (drawingArea) cancelAreaDrawing();
  if (openMap) fieldLayer.clearLayers();
  else fieldLayer.forEach(feature => fieldLayer.remove(feature));
  uploadedGeojson = undefined; fieldLoaded = false;
  document.body.classList.remove('has-analysis-area');
  resetSavedArea();
  resetAnalysisResults();
  document.dispatchEvent(new Event('alytha-area-cleared'));
  if (clearFile) document.getElementById('field-file').value = '';
  document.getElementById('map-label').textContent = 'Nenhuma área selecionada';
  document.getElementById('area-details').textContent = 'Desenhe uma área ou carregue um GeoJSON para analisar.';
  setStatus('Selecione uma área de análise.');
}

function fitGeojson(geojson) {
  if (openMap) {
    const temporary = L.geoJSON(geojson);
    map.fitBounds(temporary.getBounds(), { padding: [65, 65] });
  } else {
    const bounds = new google.maps.LatLngBounds();
    const features = geojson.type === 'FeatureCollection' ? geojson.features : [geojson];
    features.forEach(feature => extendBounds(bounds, (feature.geometry || feature).coordinates));
    map.fitBounds(bounds, 65);
  }
}

function regionBoundaryLabel() {
  let label=document.getElementById('region-boundary-label');
  if(!label) {
    const card=document.querySelector('.map-card');if(!card)return null;
    label=document.createElement('div');label.id='region-boundary-label';label.hidden=true;
    const swatch=document.createElement('i');swatch.setAttribute('aria-hidden','true');
    const name=document.createElement('span');label.append(swatch,name);card.append(label);
  }
  return label;
}

function clearRegionBoundary() {
  removeMapLayer(regionLayer);regionLayer=null;
  const label=regionBoundaryLabel();if(label)label.hidden=true;
}

async function fitRegionBoundary(geometry,request) {
  // The regional panel opens on selection; settle its layout before fitting.
  document.getElementById('side-panel').classList.remove('closed');
  document.getElementById('panel-toggle').setAttribute('aria-expanded','true');
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  if(request!==regionRequest)return false;
  if(openMap)map.invalidateSize({pan:false});
  else if(window.google?.maps?.event)google.maps.event.trigger(map,'resize');
  const canvas=document.getElementById('map').getBoundingClientRect();
  const chat=document.getElementById('ai-prompt-panel');
  const chatBox=chat?.getBoundingClientRect();
  const chatVisible=chat && !chat.hidden && getComputedStyle(chat).visibility!=='hidden';
  const overlap=chatVisible && chatBox.right>canvas.left && chatBox.left<canvas.right
    ? Math.max(0,canvas.bottom-Math.max(canvas.top,chatBox.top)) : 0;
  const padding={top:82,right:50,bottom:Math.min(Math.max(50,overlap+24),canvas.height*.55),left:50};
  if(openMap) {
    map.fitBounds(L.geoJSON(geometry).getBounds(),{
      paddingTopLeft:[padding.left,padding.top],paddingBottomRight:[padding.right,padding.bottom],animate:false
    });
  } else {
    const bounds=new google.maps.LatLngBounds();
    for(const feature of geometry.type==='FeatureCollection'?geometry.features:[geometry])extendBounds(bounds,(feature.geometry || feature).coordinates);
    map.fitBounds(bounds,padding);
  }
  return true;
}

function selectAnalysisArea(geojson, name) {
  if (drawingArea) cancelAreaDrawing();
  clearAnalysisArea(false);
  uploadedGeojson = geojson;
  if (openMap) fieldLayer.addData(geojson); else fieldLayer.addGeoJson(geojson);
  fieldLoaded = true;
  document.body.classList.add('has-analysis-area');
  fitGeojson(geojson);
  document.getElementById('map-label').textContent = name;
  document.getElementById('area-details').textContent = `${name}. Área pronta para consultar imagens e NDVI; permanece nesta sessão.`;
  setStatus('Área selecionada. Escolha o período e consulte imagens ou calcule NDVI.');
  document.dispatchEvent(new CustomEvent('alytha-area-selected',{detail:{geojson,name}}));
}

function redrawSketch() {
  clearVertices();
  removeMapLayer(sketchLayer);
  if (openMap) sketchLayer = L.polyline(drawingPoints.map(p => [p[1], p[0]]), { color: '#e53935', weight: 3, interactive: false }).addTo(map);
  else sketchLayer = new google.maps.Polyline({ map, path: drawingPoints.map(p => ({ lat: p[1], lng: p[0] })), strokeColor: '#e53935', strokeWeight: 3, clickable: false });
  vertexLayers = drawingPoints.map(point => {
    if (openMap) return L.circleMarker([point[1], point[0]], { radius: 5, color: '#e53935', weight: 2, fillColor: '#fff', fillOpacity: 1, interactive: false }).addTo(map);
    return new google.maps.Circle({ map, center: { lat: point[1], lng: point[0] }, radius: 5 * 156543.03392 * Math.cos(point[1] * Math.PI / 180) / 2 ** map.getZoom(), strokeColor: '#e53935', strokeWeight: 2, fillColor: '#fff', fillOpacity: 1, clickable: false, zIndex: 100 });
  });
  document.getElementById('finish-drawing').disabled = drawingPoints.length < 3;
  document.getElementById('finish-drawing').textContent = drawingPoints.length < 3 ? `Concluir (${drawingPoints.length}/3 pontos)` : 'Concluir desenho';
  document.getElementById('area-details').textContent = `${drawingPoints.length} pontos. Clique no mapa; use Concluir desenho após pelo menos três pontos.`;
  document.getElementById('drawing-hint').textContent = drawingPoints.length<3
    ? `Marque pelo menos 3 pontos no mapa (${drawingPoints.length}/3).`
    : `${drawingPoints.length} pontos. Conclua o desenho ou clique em Buscar imagens.`;
  document.getElementById('drawing-hint').classList.remove('error');
  document.getElementById('undo-point').disabled=!drawingPoints.length;
}

function finishAreaDrawing() {
  if(!drawingArea)return fieldLoaded;
  let error='';
  if(drawingPoints.length<3)error='Marque pelo menos 3 pontos no mapa para formar a área de consulta.';
  const ring=[...drawingPoints.map(point=>[...point]),drawingPoints[0] && [...drawingPoints[0]]];
  if(!error) {
    let signedArea=0;
    for(let i=0;i<ring.length-1;i++)signedArea+=ring[i][0]*ring[i+1][1]-ring[i+1][0]*ring[i][1];
    if(Math.abs(signedArea)<1e-12)error='Os pontos precisam formar uma área; escolha pontos fora de uma mesma linha.';
  }
  if(error) {
    setStatus(error,true);
    document.getElementById('drawing-hint').textContent=error;
    document.getElementById('drawing-hint').classList.add('error');return false;
  }
  selectAnalysisArea({type:'Feature',properties:{name:'Área desenhada'},geometry:{type:'Polygon',coordinates:[ring]}},'Área desenhada');
  return true;
}

function ensureAnalysisArea() {
  if(!mapReady || !fieldLayer) {setStatus('Aguarde o carregamento do mapa.',true);return false;}
  // Finish the current sketch before consulting; never query a previous area by mistake.
  if(drawingArea)return finishAreaDrawing();
  if(fieldLoaded)return true;
  setStatus('Desenhe uma área ou carregue um GeoJSON antes de consultar imagens.',true);return false;
}

function cancelAreaDrawing() {
  clearVertices();
  drawingArea = false; drawingPoints = [];
  removeMapLayer(sketchLayer); sketchLayer = null;
  if (openMap) map.doubleClickZoom.enable(); else map.setOptions({ disableDoubleClickZoom: false, draggableCursor: null });
  document.getElementById('draw-controls').hidden = true;
  document.getElementById('draw-area').disabled = false;
  document.getElementById('draw-area').textContent = 'Desenhar área';
  document.getElementById('pen-tool').setAttribute('aria-pressed', 'false');
  document.getElementById('map').classList.remove('drawing-mode');
  document.getElementById('area-details').textContent = fieldLoaded ? 'A área anterior foi mantida.' : 'Desenhe uma área ou carregue um GeoJSON.';
}

function enableAreaTools() {
  document.getElementById('pen-tool').disabled = false;
  document.getElementById('draw-area').disabled = false;
  const capture = event => {
    if (!drawingArea || drawingPoints.length >= 200) return;
    const point = openMap ? [event.latlng.lng, event.latlng.lat] : [event.latLng.lng(), event.latLng.lat()];
    if (drawingPoints.some(p => p[0] === point[0] && p[1] === point[1])) return;
    drawingPoints.push(point); redrawSketch();
  };
  const finish=event=>{if(drawingArea){capture(event);finishAreaDrawing();}};
  if (openMap) { map.on('click', capture); map.on('dblclick', finish); }
  else { map.addListener('click', capture); map.addListener('dblclick', finish); }
}

async function locationJson(url) {
  const response = await fetch(url);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Não foi possível consultar a localidade.');
  return result;
}

function populateOptions(select, items, placeholder) {
  select.replaceChildren(new Option(placeholder, ''));
  items.forEach(item => select.add(new Option(item.nome + (item.sigla ? ` (${item.sigla})` : ''), item.id)));
}

async function showRegion(kind, id, request) {
  clearRegionBoundary();
  if (!id) return;
  const work=window.mapLoading?.begin('localidade','Abrindo localidade no mapa','Buscando os limites oficiais da região…');
  try {
  const geometry = await locationJson(`/api/locations/boundaries/${kind}/${id}`);
  if (request !== regionRequest) return;
  if (!mapReady) throw new Error('Aguarde o mapa carregar e selecione novamente a localidade.');
  if (openMap) {
    const pane=map.getPane('region-boundary') || map.createPane('region-boundary');
    pane.style.zIndex='450';pane.style.pointerEvents='none';
    regionLayer = L.geoJSON(geometry, { pane:'region-boundary',style: { color:'#ffd600',weight:3,opacity:1,fill:false,className:'region-boundary-line' },interactive:false }).addTo(map);
  }
  else {
    regionLayer = new google.maps.Data({ map }); regionLayer.addGeoJson(geometry);
    regionLayer.setStyle({ strokeColor:'#ffd600',strokeWeight:3,strokeOpacity:1,fillOpacity:0,clickable:false,zIndex:30 });
  }
  if(!await fitRegionBoundary(geometry,request))return;
  const label=regionBoundaryLabel();
  if(label) {
    const select=document.getElementById(kind==='municipalities'?'municipality-select':'state-select');
    const name=select?.value===id ? select.selectedOptions[0]?.textContent : id;
    label.querySelector('span').textContent=`${kind==='municipalities'?'Limite municipal':'Limite estadual'} · ${name || id}`;
    label.hidden=false;
  }
  document.getElementById('region-status').textContent = 'Limite IBGE exibido. Aproxime o mapa e desenhe uma área menor para analisar.';
  document.dispatchEvent(new CustomEvent('alytha-region-ready',{detail:{kind,id}}));
  work?.finish('Localidade carregada.');
  } catch(error){work?.fail(error.message);throw error;}
  finally{work?.cancel();}
}

document.addEventListener('DOMContentLoaded', () => {
  const states = document.getElementById('state-select');
  const municipalities = document.getElementById('municipality-select');
  const regionStatus = document.getElementById('region-status');
  const retry = document.getElementById('retry-locations');
  async function loadStates() {
    states.disabled = true; retry.hidden = true;
    try { populateOptions(states, await locationJson('/api/locations/states'), 'Selecione um estado'); states.disabled = false; }
    catch (error) { regionStatus.textContent = error.message; retry.hidden = false; }
  }
  retry.addEventListener('click', async () => { await loadStates(); await restoreLocalityUrl(); });
  const statesReady = loadStates();
  function updateLocalityUrl() {
    const url = new URL(window.location.href);
    url.searchParams.delete('municipio'); url.searchParams.delete('estado');
    if (municipalities.value) url.searchParams.set('municipio', municipalities.value);
    else if (states.value) url.searchParams.set('estado', states.value);
    if (url.href !== window.location.href) history.pushState({}, '', url);
  }
  async function restoreLocalityUrl() {
    await statesReady;
    if (!mapReady) return;
    const url = new URL(window.location.href), code = url.searchParams.get('municipio');
    const state = code ? code.slice(0,2) : url.searchParams.get('estado') || '';
    if ((code && !/^[0-9]{7}$/.test(code)) || (state && ![...states.options].some(option => option.value === state))) {
      regionStatus.textContent = 'Localidade inválida na URL.'; return;
    }
    resetMunicipalBase(); const request = ++regionRequest;
    states.value = state; municipalities.disabled = true;
    populateOptions(municipalities, [], 'Selecione um estado');
    if (!state) { clearRegionBoundary(); return; }
    try {
      regionStatus.textContent = 'Abrindo localidade da URL…';
      const cities = await locationJson(`/api/locations/states/${state}/municipalities`);
      if (request !== regionRequest) return;
      populateOptions(municipalities,cities,'Selecione um município'); municipalities.disabled = false;
      if (code && !cities.some(city => String(city.id) === code)) throw new Error('Município inválido na URL.');
      municipalities.value = code || '';
      if (code) {
        prepareMunicipalBase(code);
        document.getElementById('area-city').value = `${municipalities.selectedOptions[0].textContent} / ${states.selectedOptions[0].textContent}`;
      }
      await showRegion(code ? 'municipalities' : 'states', code || state, request);
    } catch(error) { if(request===regionRequest) regionStatus.textContent=error.message; }
  }
  window.addEventListener('popstate', restoreLocalityUrl);
  document.addEventListener('alytha-map-ready', restoreLocalityUrl);
  statesReady.then(() => { if(mapReady) restoreLocalityUrl(); });
  states.addEventListener('change', async () => {
    resetMunicipalBase();
    const request = ++regionRequest, id = states.value;
    municipalities.disabled = true; populateOptions(municipalities, [], id ? 'Carregando municípios…' : 'Selecione um estado');
    updateLocalityUrl();
    if (!id) { clearRegionBoundary(); return; }
    regionStatus.textContent = 'Carregando municípios e limite do estado…';
    try {
      const cities = await locationJson(`/api/locations/states/${id}/municipalities`);
      if (request !== regionRequest) return;
      populateOptions(municipalities, cities, 'Selecione um município'); municipalities.disabled = false;
      await showRegion('states', id, request);
    } catch (error) { if (request === regionRequest) regionStatus.textContent = error.message; }
  });
  municipalities.addEventListener('change', async () => {
    updateLocalityUrl();
    prepareMunicipalBase(municipalities.value);
    const request = ++regionRequest;
    regionStatus.textContent = 'Carregando limite territorial…';
    try { await showRegion(municipalities.value ? 'municipalities' : 'states', municipalities.value || states.value, request); }
    catch (error) { if (request === regionRequest) regionStatus.textContent = error.message; }
  });
  function togglePen() {
    if (!mapReady) return;
    if (drawingArea) { cancelAreaDrawing(); setStatus('Desenho cancelado.'); return; }
    drawingArea = true; drawingPoints = [];
    document.getElementById('draw-controls').hidden = false;
    document.getElementById('draw-area').textContent = 'Cancelar desenho';
    document.getElementById('pen-tool').setAttribute('aria-pressed', 'true');
    document.getElementById('map').classList.add('drawing-mode');
    document.querySelectorAll('.analysis.visible').forEach(panel=>panel.classList.remove('visible'));
    document.getElementById('side-panel').classList.toggle('closed',matchMedia('(max-width:999px)').matches);
    document.getElementById('selected-area-tools').open = true;
    document.getElementById('panel-toggle').setAttribute('aria-expanded',String(!document.getElementById('side-panel').classList.contains('closed')));
    if (openMap) map.doubleClickZoom.disable(); else map.setOptions({ disableDoubleClickZoom: true, draggableCursor: 'crosshair' });
    redrawSketch(); setStatus('Caneta ativa: clique nos vértices e depois em Concluir desenho. Esc cancela.');
  }
  document.getElementById('draw-area').addEventListener('click', togglePen);
  document.getElementById('pen-tool').addEventListener('click', togglePen);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && drawingArea) { cancelAreaDrawing(); setStatus('Desenho cancelado.'); }
  });
  document.getElementById('undo-point').addEventListener('click', () => { drawingPoints.pop(); redrawSketch(); });
  document.getElementById('cancel-drawing').addEventListener('click', () => { cancelAreaDrawing(); setStatus('Desenho cancelado.'); });
  document.getElementById('finish-drawing').addEventListener('click',finishAreaDrawing);
  document.getElementById('clear-area').addEventListener('click', () => clearAnalysisArea());
});
