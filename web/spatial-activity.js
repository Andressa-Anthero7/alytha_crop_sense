/* Spatial results follow the selected area, with explicit reference scope. */
document.addEventListener('DOMContentLoaded',()=>{
  const el=id=>document.getElementById(id);
  let revision=0,poll,layer=null,result=null,geometry=null,downloadUrl=null,info=null;
  const ha=value=>value.toLocaleString('pt-BR',{maximumFractionDigits:1})+' ha';
  const date=value=>value.split('-').reverse().join('/');
  function removeLayer() {
    if(layer && mapReady)removeMapLayer(layer);
    info?.close();info=null;
    layer=null;el('clear-spatial-analysis').hidden=true;
  }
  function clear() {
    revision++;clearTimeout(poll);result=null;removeLayer();
    if(downloadUrl)URL.revokeObjectURL(downloadUrl);downloadUrl=null;
    el('start-spatial-analysis').disabled=false;
    el('spatial-results').replaceChildren();
    el('spatial-status').textContent='Pronto para comparar três períodos de imagens. Nuvens e áreas sem leitura ficam fora da conclusão.';
  }
  function draw() {
    removeLayer();
    if(!mapReady || !result)return;
    const view=el('spatial-view').value,signal={gain:'vegetation_gain',loss:'vegetation_loss',low:'persistent_low_vegetation'}[view];
    const patches=view==='sequence'?(result.growth_sequence?.geojson.features || []):(result.change_geojson || result.geojson).features.filter(f=>f.properties.signal===signal);
    const arrows=(result.progression?.geojson.features || []).filter(f=>view!=='low' && f.properties.signal===(view==='loss'?'vegetation_loss':'vegetation_gain'));
    const collection={type:'FeatureCollection',features:[...patches,...arrows]};
    el('spatial-map-legend').textContent=view==='sequence'?'Verde claro: aumentou primeiro. Verde escuro: aumentou depois. Flechas: direção consistente, quando detectada.':view==='gain'?'Verde vivo: onde o NDVI aumentou pelo menos 0,15 entre a primeira e a última imagem.':view==='loss'?'Rosa: onde o NDVI diminuiu pelo menos 0,15.':'Bege: pouca vegetação nos três períodos.';
    if(view==='sequence' && !result.growth_sequence)el('spatial-map-legend').textContent='A sequência não está disponível neste resultado salvo. Nenhuma etapa foi estimada.';
    if(!collection.features.length)return;
    const colors={persistent_low_vegetation:'#c7b18a',vegetation_gain:'#39e65d',vegetation_loss:'#ae5d71'};
    const color=properties=>properties.growth_stage==='early'?'#a0ed54':properties.growth_stage==='late'?'#087e38':properties.progression?'#153dce':colors[properties.signal];
    const popup=properties=>properties.progression?progressionPopup(properties):`${properties.growth_stage==='early'?'Aumentou primeiro':properties.growth_stage==='late'?'Aumentou depois':properties.signal==='vegetation_gain'?'Ganho de vegetação':properties.signal==='vegetation_loss'?'Perda de vegetação':'Pouca vegetação persistente'} · ${ha(properties.area_ha)}${properties.shape_pattern?' · Forma: '+properties.shape_pattern:''}. Não confirma manejo.`;
    if(openMap) {
      layer=L.geoJSON(collection,{style:feature=>({color:color(feature.properties),weight:feature.properties.progression?4:2,fillOpacity:.5}),onEachFeature:(feature,polygon)=>{
        const text=document.createElement('span');text.textContent=feature.properties.progression?progressionPopup(feature.properties):`${feature.properties.signal==='vegetation_gain'?'Ganho de vegetação':feature.properties.signal==='vegetation_loss'?'Perda de vegetação':'Pouca vegetação persistente'} · ${ha(feature.properties.area_ha)} · três períodos. Não confirma manejo.`;
        text.textContent=popup(feature.properties);polygon.bindPopup(text);
      }}).addTo(map);
    } else {
      layer=new google.maps.Data({map});layer.addGeoJson(collection);
      layer.setStyle(feature=>{const properties={};feature.forEachProperty((v,k)=>properties[k]=v);return {strokeColor:color(properties),strokeWeight:properties.progression?4:2,fillColor:color(properties),fillOpacity:.5};});
      info=new google.maps.InfoWindow();
      layer.addListener('click',event=>{
        const properties={};event.feature.forEachProperty((value,key)=>properties[key]=value);
        const text=document.createElement('p');text.textContent=properties.progression?progressionPopup(properties):`${properties.signal==='vegetation_gain'?'Ganho de vegetação':properties.signal==='vegetation_loss'?'Perda de vegetação':'Pouca vegetação persistente'} · ${ha(properties.area_ha)}. Sem confirmação de manejo.`;
        text.textContent=popup(properties);info.setContent(text);info.setPosition(event.latLng);info.open({map});
      });
    }
    el('clear-spatial-analysis').hidden=false;
  }
  async function watch(job,current) {
    if(current!==revision)return;
    if(job.status==='loading') {
      el('spatial-status').textContent=job.phase==='dates' ? 'Buscando três períodos recentes com imagens úteis…' : `${job.processed}/3 períodos obtidos. Comparando os mesmos pixels da área…`;
      poll=setTimeout(async()=>{
        try {await watch(await storageJson('/api/spatial-activity/'+job.id),current);}
        catch(error){if(current===revision){el('spatial-status').textContent=error.message;el('start-spatial-analysis').disabled=false;}}
      },2000);return;
    }
    el('start-spatial-analysis').disabled=false;
    if(job.status==='error'){el('spatial-status').textContent=job.error;return;}
    result=job;draw();
    el('spatial-status').textContent=job.status==='inconclusive' ? 'Sem conclusão: faltou observar pelo menos metade do recorte nos três períodos. Não foram marcadas manchas.' : `Aumento de vegetação: ${ha(job.vegetation_gain_ha || 0)}. Selecione a sequência para ver onde aumentou primeiro e depois.`;
    el('spatial-scope').textContent=job.parameters.scope;
    el('spatial-results').replaceChildren();
    for(const text of [`Períodos: ${job.periods.map(p=>date(p.from)+' a '+date(p.to)).join(' · ')}.`,
      `Mesmos pontos observados nos três períodos: ${(job.common_coverage*100).toLocaleString('pt-BR',{maximumFractionDigits:1})}% do recorte (${ha(job.observed_area_ha)}).`,
      `Sem leitura comum suficiente: ${ha(job.unobserved_area_ha)}.`,
      ...(job.status==='ready'?[`Regiões menores que 1 ha, fora dos contornos: ${ha(job.small_low_regions_ha)}. Características espaciais salvas para exploração com ML.`]:[])]) {
      const line=document.createElement('p');line.textContent=text;el('spatial-results').append(line);
    }
    if(job.status==='ready') {
      const gains=(job.change_geojson?.features || []).filter(f=>f.properties.signal==='vegetation_gain');
      for(const [i,f] of gains.entries()) {
        const p=document.createElement('p'),properties=f.properties;
        p.textContent=`Mancha de aumento ${i+1}: ${ha(properties.area_ha)} · ${properties.shape_pattern || 'forma ainda não analisada'}${Number.isFinite(properties.rectangularity)?' · ocupação do retângulo envolvente: '+(properties.rectangularity*100).toLocaleString('pt-BR',{maximumFractionDigits:0})+'%':''}.`;el('spatial-results').append(p);
      }
      if(job.growth_sequence) {
        const areas=document.createElement('p');areas.textContent=job.growth_sequence.stages.map(s=>`${s.stage==='early'?'Aumentou primeiro':'Aumentou depois'}: ${ha(s.area_ha)}`).join(' · ');el('spatial-results').append(areas);
        const p=document.createElement('p');p.textContent=job.growth_sequence.note;el('spatial-results').append(p);
      }
      const note=document.createElement('p');note.textContent='Bloco ou faixa regular descreve a forma da mancha; organização temporal exige também mudança em sequência. Pixels de 10 m não mostram linhas individuais de semeadura.';el('spatial-results').append(note);
      renderVegetationProgression(el('spatial-results'),job.progression);
      const link=document.createElement('a');link.textContent='Baixar contornos GeoJSON';
      downloadUrl=URL.createObjectURL(new Blob([JSON.stringify({type:'FeatureCollection',features:[...(job.change_geojson || job.geojson).features,...(job.progression?.geojson.features || [])]})],{type:'application/geo+json'}));link.href=downloadUrl;
      link.download='manchas-vegetacao-'+job.periods.at(-1).to+'.geojson';
      el('spatial-results').append(link);
    }
    if(!geometry && mapReady)fitGeojson({type:'Feature',properties:{},geometry:job.parameters.geometry});
  }
  el('start-spatial-analysis').addEventListener('click',async()=>{
    clear();const current=revision;el('start-spatial-analysis').disabled=true;
    el('spatial-status').textContent='Preparando a análise espacial…';
    try {
      if(drawingArea)throw Error('Conclua o desenho da área antes de analisar suas manchas.');
      const payload=fieldLoaded && !drawingArea ? {geojson:await fieldGeojson()} : {municipality_code:el('municipality-select').value || new URL(location.href).searchParams.get('municipio') || '5107925'};
      await watch(await storageJson('/api/spatial-activity',payload),current);
    } catch(error){if(current===revision){el('spatial-status').textContent=error.message;el('start-spatial-analysis').disabled=false;}}
  });
  el('clear-spatial-analysis').addEventListener('click',removeLayer);
  el('spatial-view').addEventListener('change',draw);
  document.addEventListener('alytha-hide-spatial-layers',removeLayer);
  document.addEventListener('alytha-area-selected',event=>{clear();geometry=event.detail.geojson;el('spatial-scope').textContent=`Recorte selecionado: ${event.detail.name}. Não representa o município inteiro.`;});
  document.addEventListener('alytha-area-cleared',()=>{clear();geometry=null;el('spatial-scope').textContent='Sem recorte selecionado: a análise usa a referência de Sorriso, somente uma amostra.';});
  document.addEventListener('alytha-map-search',()=>{clear();});
  document.addEventListener('alytha-region-ready',()=>{clear();});
  document.addEventListener('alytha-map-ready',draw);
});
