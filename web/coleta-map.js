/* Municipal collection and training coverage; colors do not describe crop condition. */
let collectionMap,collectionLayer,collectionLatest=null,collectionSelection=null;
const collectionColors={ready:'#278253',partial:'#c89c4b',loading:'#3284bc',error:'#ff0000',queued:'#c4cec2'};
const collectionLabels={ready:'Completo',partial:'Parcial',loading:'Carregando',error:'Com falha',queued:'Na fila'};
function collectionCity(code){return collectionLatest?.municipalities?.find(city=>city.code===code);}
function collectionPopup(feature){
  const city=collectionCity(feature.properties.code) || {...feature.properties,status:'queued'};
  const output=document.createElement('div');
  for(const text of [`${city.name} / ${city.uf}`,collectionStatusLabel(city),
    collectionTrainingLabel(city),
    `${city.recortes || 0}/${city.recortes_total || 0} recortes recentes · ${city.observations || 0} leituras históricas`]){
    const line=document.createElement('p');line.textContent=text;output.append(line);
  }
  const link=document.createElement('a');link.href='/?municipio='+city.code;link.textContent='Abrir município no mapa agrícola';output.append(link);
  for(const issue of city.issues || []){const line=document.createElement('p');line.textContent=collectionIssueText(issue);output.append(line);}
  return output;
}
function collectionDetail(){
  if(!collectionSelection)return;
  const city=collectionCity(collectionSelection);
  if(city)document.getElementById('collection-map-detail').textContent=`${city.name} / ${city.uf} · ${collectionStatusLabel(city)} · ${collectionTrainingLabel(city)} · ${city.recortes || 0}/${city.recortes_total || 0} recortes recentes · ${city.observations || 0} leituras históricas. ${(city.issues || []).map(collectionIssueText).join(' ')}`;
}
window.updateCollectionMap=data=>{
  collectionLatest=data;
  const trainingMode=document.getElementById('collection-map-mode').value==='training';
  document.getElementById('collection-progress-legend').hidden=trainingMode;
  document.getElementById('collection-training-legend').hidden=!trainingMode;
  const trained=(data.municipalities || []).filter(c=>c.training?.status==='trained');
  document.getElementById('collection-training-summary').textContent=`${trained.length} municípios com modelo treinado · ${trained.reduce((sum,c)=>sum+c.training.areas,0).toLocaleString('pt-BR')} recortes usados. A cor cobre o município; o treinamento usa apenas os recortes coletados, e pode coexistir com pendências no histórico.`;
  if(!collectionLayer)return;
  if(collectionSelection && !collectionMatches(collectionCity(collectionSelection))){collectionSelection=null;document.getElementById('collection-map-detail').textContent='Clique em um município que corresponde aos filtros.';}
  collectionLayer.eachLayer(layer=>{const city=collectionCity(layer.feature.properties.code);const matches=city && collectionMatches(city);if(matches && !collectionMap.hasLayer(layer))collectionMap.addLayer(layer);else if(!matches && collectionMap.hasLayer(layer))collectionMap.removeLayer(layer);});
  collectionLayer.setStyle(feature=>{const city=collectionCity(feature.properties.code),status=city?.status || 'queued';return {color:trainingMode?'#665477':status==='error'?'#b00000':status==='loading'?'#185481':'#71826e',weight:trainingMode?.7:status==='loading'?2.5:.6,fillColor:collectionStatusColor(city),fillOpacity:trainingMode?.75:status==='error'?.95:status==='loading'?.85:.65};});
  collectionLayer.eachLayer(layer=>{if(layer.isPopupOpen())layer.setPopupContent(collectionPopup(layer.feature));});
  collectionDetail();
};
async function loadCollectionMap(){
  try{
    const response=await fetch('/collection-map.geojson',{cache:'no-store',signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw Error('Limites indisponíveis');const data=await response.json();
    collectionMap=L.map('collection-map',{preferCanvas:true,scrollWheelZoom:false}).setView([-16,-54],5);
    // A faint basemap is optional: municipal polygons remain usable without tiles.
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:14,attribution:'© OpenStreetMap · Limites IBGE'}).addTo(collectionMap);
    collectionLayer=L.geoJSON(data,{onEachFeature:(feature,layer)=>{
      layer.bindTooltip(`${feature.properties.name} / ${feature.properties.uf}`,{sticky:true});
      layer.bindPopup(()=>collectionPopup(feature));
      layer.on('click',()=>{collectionSelection=feature.properties.code;collectionDetail();});
    }}).addTo(collectionMap);
    collectionMap.fitBounds(collectionLayer.getBounds(),{padding:[15,15]});
    if(collectionLatest)window.updateCollectionMap(collectionLatest);
    const missing=data.metadata?.missing || [];
    document.getElementById('collection-map-status').textContent=`${data.metadata?.mapped || data.features.length}/${data.metadata?.expected || data.features.length} municípios com limites disponíveis · IBGE.${missing.length?' Sem malha nesta fonte: '+missing.map(city=>city.name+' / '+city.uf).join(', ')+'.':''}`;
    document.getElementById('collection-map-fit').addEventListener('click',()=>collectionMap.fitBounds(collectionLayer.getBounds(),{padding:[15,15]}));
    new ResizeObserver(()=>collectionMap.invalidateSize({pan:false})).observe(document.getElementById('collection-map'));
  }catch(error){document.getElementById('collection-map-status').textContent='Não foi possível carregar o mapa da coleta. Os demais indicadores continuam disponíveis. Atualize a página para tentar novamente.';}
}
document.addEventListener('DOMContentLoaded',loadCollectionMap);
