/* One municipal geometry download; date selection restyles the same polygons. */
document.addEventListener('DOMContentLoaded',()=>{
  const el=id=>document.getElementById(id),toggle=el('soy-map-classes');
  const legend=el('activity-map-legend');
  let job=null,model=null,layer=null,selectedDate='',generation=0,request=null;
  let popup=null,popupIndex=null;
  const ha=value=>value.toLocaleString('pt-BR',{maximumFractionDigits:1})+' ha';
  const formatDate=value=>value.split('-').reverse().join('/');
  function state(index) {
    const dateIndex=model?.dates.indexOf(selectedDate) ?? -1;
    return dateIndex>=0 ? model.states[index]?.[dateIndex] || 'unknown' : 'unknown';
  }
  function classification(index) {return SOY_ACTIVITY_CLASSES[state(index)] || SOY_ACTIVITY_CLASSES.unknown;}
  function content(index) {
    const feature=model.geojson.features[index],status=state(index),group=classification(index);
    const output=document.createElement('div');
    for(const text of [group.label,`${ha(feature.properties.area_ha)} · avaliação em ${formatDate(selectedDate)}`,
      status==='pending' ? 'O acompanhamento desta área ainda não foi concluído.' : status==='unknown' ? 'Ainda não há acompanhamento suficiente para interpretar a condição desta área.' : status==='possible_inactive' ? 'A área manteve baixo vigor nos períodos recentes. Pós-colheita, preparo ou pousio são possibilidades; o manejo ainda não está identificado.' : 'A vegetação ficou acima da faixa de baixo vigor em pelo menos um dos períodos recentes. Isso ainda não confirma a cultura ou a implantação da safra.',
      'Área com histórico de soja em 2025. O acompanhamento não confirma o limite de um talhão.']) {
      const line=document.createElement('p');line.textContent=text;line.style.margin='4px 0';output.append(line);
    }
    return output;
  }
  function hide() {
    if(layer && mapReady)removeMapLayer(layer);layer=null;
    if(popup)popup.close();popup=null;popupIndex=null;
    legend.hidden=true;
    if(mapReady && agriculturalLayer) {
      if(openMap && !map.hasLayer(agriculturalLayer))agriculturalLayer.addTo(map);
      else if(!openMap)agriculturalLayer.setMap(map);
    }
  }
  function clear() {
    generation++;request?.abort();request=null;hide();job=null;model=null;selectedDate='';
  }
  function hideCropLayer() {
    if(toggle.checked && layer && agriculturalLayer && mapReady)removeMapLayer(agriculturalLayer);
  }
  function updateLegend() {
    el('activity-map-date').textContent=`Avaliação em ${formatDate(selectedDate)} · soja histórica 2025`;
    const summary=model.summary_by_date.find(point=>point.date===selectedDate);
    el('activity-map-rows').replaceChildren();
    for(const [key,value] of Object.entries(SOY_ACTIVITY_CLASSES)) {
      const row=document.createElement('div');row.className='activity-map-row';
      const swatch=document.createElement('i');swatch.style.background=value.color;
      const title=document.createElement('span');title.textContent=value.label;
      const amount=document.createElement('strong');
      amount.textContent=summary ? ha(key==='unknown'?summary.unknown_ha+summary.pending_ha:summary[key+'_ha']) : '';
      row.append(swatch,title,amount);el('activity-map-rows').append(row);
    }
    el('activity-map-note').textContent=`Soja histórica 2025 cruzada com NDVI recente · ${model.processed}/${model.states.length} áreas. Bege: pouca vegetação nos três intervalos válidos recentes. Verde: vegetação em pelo menos um deles, não necessariamente na última imagem. Cinza: leitura insuficiente ou pendente. Não confirma solo vazio ou soja atual. Áreas menores que 5 ha não aparecem.`;
    legend.hidden=false;
  }
  function draw() {
    if(!toggle.checked || !model || !mapReady)return;
    if(!model.dates.includes(selectedDate))selectedDate=model.dates.at(-1);
    if(!layer) {
      if(openMap) {
        layer=L.geoJSON(model.geojson,{onEachFeature:(feature,polygon)=>{
          const index=feature.properties.activity_index;
          polygon.bindPopup(()=>content(index));
          polygon.on('click',event=>{
            if(drawingArea){polygon.closePopup();drawingPoints.push([event.latlng.lng,event.latlng.lat]);redrawSketch();}
          });
        }}).addTo(map);
      } else {
        layer=new google.maps.Data({map});layer.addGeoJson(model.geojson);
        layer.addListener('click',event=>{
          if(drawingArea){drawingPoints.push([event.latLng.lng(),event.latLng.lat()]);redrawSketch();return;}
          popupIndex=event.feature.getProperty('activity_index');
          if(!popup)popup=new google.maps.InfoWindow();
          popup.setContent(content(popupIndex));popup.setPosition(event.latLng);popup.open({map});
        });
      }
    }
    if(openMap) {
      layer.setStyle(feature=>{const color=classification(feature.properties.activity_index).color;return {color,fillColor:color,weight:1,fillOpacity:.5};});
      layer.eachLayer(polygon=>{if(polygon.isPopupOpen())polygon.setPopupContent(content(polygon.feature.properties.activity_index));});
    } else {
      layer.setStyle(feature=>{const color=classification(feature.getProperty('activity_index')).color;return {strokeColor:color,fillColor:color,strokeWeight:1,fillOpacity:.5};});
      if(popup && popupIndex!==null)popup.setContent(content(popupIndex));
    }
    hideCropLayer();updateLegend();
  }
  async function refresh() {
    if(!job?.points?.length || request || !toggle.checked)return;
    if(model?.job_id===job.id && model.processed===job.processed){draw();return;}
    const current=generation,id=job.id,controller=new AbortController();request=controller;
    const includeGeometry=!model?.geojson;
    let refreshed=false;
    try {
      const response=await fetch(`/api/soy-activity/municipality/${id}/map?geometry=${includeGeometry?1:0}&processed=${job.processed}`,{signal:controller.signal});
      const result=await response.json();
      if(!response.ok)throw Error(result.error || 'Não foi possível carregar as classes no mapa.');
      if(current!==generation || job?.id!==id)return;
      model={...result,geojson:result.geojson || model.geojson};refreshed=true;draw();
    } catch(error) {
      if(current===generation && error.name!=='AbortError')el('soy-map-status').textContent=error.message;
    } finally {
      if(request===controller)request=null;
      if(refreshed && current===generation && model && job?.processed>model.processed)refresh();
    }
  }
  document.addEventListener('alytha-soy-job-updated',event=>{
    const next=event.detail;
    if(job && next.id!==job.id)clear();
    job=next;
    if(!selectedDate)selectedDate=next.points?.at(-1)?.date || '';
    el('soy-map-status').textContent='';refresh();
  });
  document.addEventListener('alytha-soy-date-selected',event=>{
    if(selectedDate===event.detail.date)return;
    selectedDate=event.detail.date;draw();
  });
  document.addEventListener('alytha-soy-context-cleared',clear);
  document.addEventListener('alytha-map-ready',()=>{draw();refresh();});
  document.addEventListener('alytha-crop-layer-updated',hideCropLayer);
  toggle.addEventListener('change',()=>{el('soy-map-status').textContent='';if(toggle.checked)refresh();else hide();});
  el('hide-activity-map').addEventListener('click',()=>{toggle.checked=false;hide();});
});
