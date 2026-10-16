/* History, localized changes and learned profile share one area and cutoff. */
document.addEventListener('DOMContentLoaded',()=>{
  const el=id=>document.getElementById(id);
  const classes={persistent_low_vegetation:{label:'Baixo vigor persistente',color:'#c68c49'},vegetation_gain:{label:'Ganho de vegetação',color:'#33816d'},vegetation_loss:{label:'Redução da vegetação',color:'#ae5d71'}};
  const mapLegend=document.createElement('aside');mapLegend.id='crop-monitoring-map-legend';mapLegend.className='map-legend';mapLegend.hidden=true;mapLegend.setAttribute('aria-label','Legenda das mudanças acompanhadas no recorte');
  const legendTitle=document.createElement('strong'),legendRows=document.createElement('div');legendRows.className='monitoring-legend';
  for(const value of Object.values(classes)) {const row=document.createElement('span');row.style.borderLeft='3px solid '+value.color;row.textContent=value.label;legendRows.append(row);}
  mapLegend.append(legendTitle,legendRows);document.querySelector('.map-card').append(mapLegend);
  let history=null,revision=0,poll,layer=null,result=null,urls=[],selectedArea=false,info=null,busy=false,cutoff=null;
  const ha=value=>value.toLocaleString('pt-BR',{maximumFractionDigits:2})+' ha';
  function hideLayer() {if(layer && mapReady)removeMapLayer(layer);layer=null;info?.close();info=null;el('hide-crop-monitoring').hidden=true;mapLegend.hidden=true;}
  function clear() {
    revision++;clearTimeout(poll);hideLayer();result=null;busy=false;cutoff=null;
    urls.forEach(url=>URL.revokeObjectURL(url));urls=[];
    el('crop-monitoring-results').replaceChildren();
    el('start-crop-monitoring').disabled=!history?.points?.length;
    document.dispatchEvent(new Event('alytha-crop-monitoring-cleared'));
  }
  window.cropMonitoringContext=()=>result;
  function contextDate(mapDate) {
    const context=window.agriAssistantContext?.();
    const selected=mapDate || context?.map_date;
    return context?.municipality_code===history?.parameters.municipality_code && selected ? [selected,history.parameters.as_of].sort()[0] : history?.parameters.as_of;
  }
  function draw() {
    hideLayer();
    if(!mapReady || !result)return;
    const collection={type:'FeatureCollection',features:[...result.geojson.features,...(result.progression?.geojson.features || [])]};
    if(!collection.features.length)return;
    function popup(feature) {
      const text=document.createElement('p');
      text.textContent=feature.properties.progression?progressionPopup(feature.properties):`${classes[feature.properties.signal].label} · ${ha(feature.properties.area_ha)}. Mudança na vegetação, sem confirmação de cultura ou manejo.`;
      return text;
    }
    if(openMap) {
      layer=L.geoJSON(collection,{style:feature=>({color:classes[feature.properties.signal].color,weight:feature.properties.progression?4:2,fillOpacity:.35}),onEachFeature:(feature,polygon)=>polygon.bindPopup(popup(feature))}).addTo(map);
    } else {
      layer=new google.maps.Data({map});layer.addGeoJson(collection);
      layer.setStyle(feature=>({strokeColor:classes[feature.getProperty('signal')].color,fillColor:classes[feature.getProperty('signal')].color,strokeWeight:2,fillOpacity:.35}));
      info=new google.maps.InfoWindow();
      layer.addListener('click',event=>{const properties={};event.feature.forEachProperty((value,key)=>properties[key]=value);info.setContent(popup({properties}));info.setPosition(event.latLng);info.open({map});});
    }
    el('hide-crop-monitoring').hidden=false;
    legendTitle.textContent='Mudanças · '+result.as_of.split('-').reverse().join('/');mapLegend.hidden=false;
  }
  function render(report) {
    result=report;draw();
    el('crop-monitoring-status').textContent=`Recorte acompanhado até ${report.as_of.split('-').reverse().join('/')} · ${report.status==='ready'?'leitura integrada disponível':'leitura parcial'}.`;
    const output=el('crop-monitoring-results');output.replaceChildren();
    if(report.evolution_index) {
      const index=report.evolution_index,heading=document.createElement('strong');heading.textContent=index.name;output.append(heading);
      for(const score of Object.values(index.scores)) {
        const card=document.createElement('div');card.className='evolution-score';
        const title=document.createElement('p');title.textContent=`${score.label}: ${score.value===null?'dados insuficientes':score.value.toLocaleString('pt-BR')+' / 100 pontos · evidências '+score.level}`;card.append(title);
        if(score.value!==null){const bar=document.createElement('progress');bar.max=100;bar.value=score.value;bar.setAttribute('aria-label',score.label);card.append(bar);}
        const note=document.createElement('p');note.className='analysis-subtitle';note.textContent=`Fatores disponíveis: ${score.available_weight}/100 pontos possíveis. ${score.hypothesis}`;card.append(note);
        const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Ver fatores e pesos';details.append(summary);
        for(const factor of score.factors){const row=document.createElement('p');row.className='analysis-subtitle';row.textContent=`${factor.label}: ${factor.available?factor.points+'/'+factor.weight+' pontos':'não avaliado (peso '+factor.weight+')'}. ${factor.reason}`;details.append(row);}
        card.append(details);output.append(card);
      }
      const note=document.createElement('p');note.className='analysis-subtitle';note.textContent=index.note;output.append(note);
    }
    for(const [title,text] of [['O que mudou',report.what_changed],['Onde mudou',report.where_changed],['Prioridade',report.priority],['Próximo sinal',report.next_signal]]) {
      const heading=document.createElement('strong'),line=document.createElement('p');
      heading.textContent=title;line.textContent=text;line.className='analysis-subtitle';output.append(heading,line);
    }
    if(report.learned_profile) {const p=document.createElement('p');p.className='analysis-subtitle';p.textContent=report.learned_profile.reading;output.append(p);}
    renderVegetationProgression(output,report.progression);
    const legend=document.createElement('div');legend.className='monitoring-legend';
    for(const value of Object.values(classes)) {const item=document.createElement('span');item.style.borderLeft='3px solid '+value.color;item.textContent=value.label;legend.append(item);}
    output.append(legend);
    const detail=document.createElement('details'),summary=document.createElement('summary'),note=document.createElement('p');
    summary.textContent='Bases e limites do acompanhamento';note.className='analysis-subtitle';
    note.textContent=report.note+(report.spatial.status!=='unavailable' ? ` Imagens comparadas entre ${report.spatial.periods[0].from.split('-').reverse().join('/')} e ${report.spatial.periods.at(-1).to.split('-').reverse().join('/')}. Parte acompanhada nas três datas: ${ha(report.spatial.observed_area_ha)}. Sem leitura comum: ${ha(report.spatial.unobserved_area_ha)}.` : ' A comparação espacial ainda não está disponível.');
    detail.append(summary,note);output.append(detail);
    for(const [name,filename,data,type] of [['Baixar acompanhamento','acompanhamento.json',report,'application/json'],['Baixar manchas','mudancas.geojson',report.geojson,'application/geo+json']]) {
      const url=URL.createObjectURL(new Blob([JSON.stringify(data)],{type}));urls.push(url);
      const link=document.createElement('a');link.href=url;link.download=filename;link.textContent=name;link.className='monitoring-download';output.append(link);
    }
    document.dispatchEvent(new CustomEvent('alytha-crop-monitoring-updated',{detail:report}));
  }
  async function watch(job,current,datasetId,date) {
    if(current!==revision)return;
    if(job.status==='loading') {
      el('crop-monitoring-status').textContent=job.phase==='dates'?'Escolhendo períodos compatíveis para localizar as mudanças…':`Comparando a área · ${job.processed}/3 períodos disponíveis…`;
      poll=setTimeout(async()=>{try {await watch(await storageJson('/api/spatial-activity/'+job.id),current,datasetId,date);}catch(error){if(current===revision){busy=false;el('crop-monitoring-status').textContent=error.message;el('start-crop-monitoring').disabled=false;}}},2000);
      return;
    }
    if(job.status==='error')throw Error(job.error);
    const payload={dataset_id:datasetId,date,spatial_job_id:job.id};
    const first=el('evolution-window-from').value,last=el('evolution-window-to').value;
    if(first || last)payload.planting_window={from:first,to:last};
    const report=await storageJson('/api/crop-monitoring',payload);
    if(current!==revision)return;
    render(report);busy=false;el('start-crop-monitoring').disabled=false;
    fitGeojson({type:'Feature',properties:{},geometry:report.geometry});
  }
  el('start-crop-monitoring').addEventListener('click',async()=>{
    if(!history)return;
    clear();const current=revision,datasetId=history.id;cutoff=contextDate();busy=true;el('start-crop-monitoring').disabled=true;
    try {
      if(drawingArea)throw Error('Conclua o desenho antes de acompanhar a área.');
      const date=cutoff;
      const job=await storageJson('/api/spatial-activity',{geojson:fieldLoaded ? await fieldGeojson() : history.parameters.geometry,dataset_id:datasetId,as_of:date});
      await watch(job,current,datasetId,date);
    } catch(error) {if(current===revision){busy=false;el('crop-monitoring-status').textContent=error.message;el('start-crop-monitoring').disabled=false;}}
  });
  el('hide-crop-monitoring').addEventListener('click',hideLayer);
  document.addEventListener('alytha-hide-spatial-layers',hideLayer);
  document.addEventListener('alytha-history-ready',event=>{
    if(history?.id===event.detail.id) {history=event.detail;el('start-crop-monitoring').disabled=busy || !history.points.length;return;}
    clear();history=event.detail;
    el('evolution-window-from').value='';el('evolution-window-to').value='';
    el('start-crop-monitoring').disabled=!history.points.length;
    el('crop-monitoring-scope').textContent=selectedArea?'Recorte do histórico carregado · não representa a cidade inteira.':'Recorte de referência do histórico · amostra, não município inteiro.';
    el('crop-monitoring-status').textContent='Atualize para juntar histórico, mudanças espaciais e padrões de vegetação.';
  });
  for(const type of ['alytha-area-selected','alytha-area-cleared','alytha-map-search'])document.addEventListener(type,()=>{
    selectedArea=type==='alytha-area-selected';history=null;clear();
    el('crop-monitoring-status').textContent='Abra o histórico do recorte atual para acompanhar esta área.';
  });
  document.addEventListener('alytha-region-ready',event=>{
    if(history && (event.detail.kind!=='municipalities' || event.detail.id!==history.parameters.municipality_code)) {
      history=null;clear();el('crop-monitoring-status').textContent='Abra o histórico do recorte nesta localidade.';
    }
  });
  document.addEventListener('alytha-soy-date-selected',event=>{
    if(cutoff && cutoff!==contextDate(event.detail.date)) {
      clear();el('crop-monitoring-status').textContent='A data no mapa mudou. Atualize o acompanhamento para comparar esse período.';
    }
  });
  document.addEventListener('alytha-map-ready',draw);
});
