/* Show saved evidence with its original spatial and temporal scope. */
let ndviReferenceLayer=null,localNdviResult=null;
function fitNdviReference(geometry,layer) {
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    if(ndviReferenceLayer!==layer || !mapReady)return;
    const canvas=document.getElementById('map').getBoundingClientRect();
    const chat=document.getElementById('ai-prompt-panel'),box=chat.getBoundingClientRect();
    const overlap=!chat.hidden && getComputedStyle(chat).visibility!=='hidden' && box.right>canvas.left && box.left<canvas.right
      ? Math.max(0,canvas.bottom-Math.max(canvas.top,box.top)) : 0;
    const bottom=Math.min(Math.max(30,overlap+24),canvas.height*.6);
    if(openMap) {
      map.invalidateSize({pan:false});
      map.fitBounds(L.geoJSON(geometry).getBounds(),{paddingTopLeft:[30,110],paddingBottomRight:[30,bottom],animate:false});
    } else {
      google.maps.event.trigger(map,'resize');
      const bounds=new google.maps.LatLngBounds();extendBounds(bounds,geometry.coordinates);
      map.fitBounds(bounds,{top:110,right:30,bottom,left:30});
    }
  }));
}
function clearLocalNdvi() {
  removeMapLayer(ndviReferenceLayer);ndviReferenceLayer=null;localNdviResult=null;
  document.getElementById('ndvi-local-selector').hidden=true;
  document.getElementById('ndvi-local-message').textContent='';
  document.getElementById('ndvi-local-scope').textContent='';
  document.getElementById('ndvi-local-period').hidden=true;
}
function showNdviResult(result,index=0) {
  clearLocalNdvi();localNdviResult=result;
  const local=result.mode==='local_cache',series=result.series || [],selected=series[index];
  const points=selected?.points || result.points || [];
  renderNdvi(points,{historyPoints:selected?.history_points || result.history_points || points});
  const subtitle=document.querySelector('#ndvi-panel .analysis-subtitle');
  subtitle.textContent=local ? 'Leituras NDVI já salvas · nenhuma nova coleta.' : 'Evolução da vegetação na área · leituras de até 5 dias. Nuvens e sombras podem impedir a avaliação de parte da área.';
  if(local) {
    document.getElementById('ndvi-local-message').textContent=result.message;
    const select=document.getElementById('ndvi-local-series');select.replaceChildren();
    series.forEach((item,i)=>select.add(new Option(`Recorte salvo ${i+1} · ${item.points.length} leituras`,i)));
    select.value=String(index);document.getElementById('ndvi-local-selector').hidden=series.length<2;
    const available=result.available_period;
    document.getElementById('ndvi-local-period').hidden=points.length>0 || !available;
    if(selected) {
      const dates=`${points[0].date.split('-').reverse().join('/')} a ${points.at(-1).date.split('-').reverse().join('/')}`;
      document.getElementById('ndvi-local-scope').textContent=`${selected.scope==='exact_area'?'Mesmo recorte selecionado':'Amostra dentro da área · borda roxa no mapa'}. ${points.length} leituras de ${dates}. Salvo em ${selected.saved_at.slice(0,10).split('-').reverse().join('/')}.${result.truncated?' Lista limitada a 20 recortes.':''}`;
      if(selected.scope==='contained_sample') {
        if(openMap) {
          const pane=map.getPane('local-ndvi') || map.createPane('local-ndvi');pane.style.zIndex='460';pane.style.pointerEvents='none';
          ndviReferenceLayer=L.geoJSON(selected.geometry,{pane:'local-ndvi',style:{color:'#7c3a9e',weight:3,fill:false},interactive:false}).addTo(map);
        }
        else {
          ndviReferenceLayer=new google.maps.Data({map});
          ndviReferenceLayer.addGeoJson({type:'Feature',geometry:selected.geometry,properties:{}});
          ndviReferenceLayer.setStyle({strokeColor:'#7c3a9e',strokeWeight:3,fillOpacity:0,clickable:false,zIndex:45});
        }
        fitNdviReference(selected.geometry,ndviReferenceLayer);
      }
    } else if(available) {
      document.getElementById('ndvi-local-scope').textContent=`Datas salvas para esta área: ${available.from.split('-').reverse().join('/')} a ${available.to.split('-').reverse().join('/')}.`;
    }
    setNdviStatus(points.length?`${points.length} leituras da base local; não são uma atualização por satélite.`:result.message);
  } else {
    setNdviStatus(points.length?`${points.length} leituras disponíveis. Consulte cada data para ver quanto da área pôde ser avaliado. Fonte: satélite Sentinel-2.`:'Não foi possível avaliar a vegetação neste período. Nuvens, sombras ou falta de imagens podem explicar a ausência de leitura.');
  }
}
function renderSceneFootprints(result) {
  removeMapLayer(scenesLayer);
  if(openMap)scenesLayer=L.geoJSON(result,{style:{color:'#b66a17',weight:1,fillOpacity:0},interactive:false});
  else {
    scenesLayer=new google.maps.Data();scenesLayer.addGeoJson(result);
    scenesLayer.setStyle({strokeColor:'#b66a17',strokeWeight:1,fillOpacity:0,clickable:false});
  }
  document.getElementById('scene-footprints').checked=false;
  document.getElementById('scene-footprints-control').hidden=!(result.features || []).length;
  document.getElementById('scene-footprints-count').textContent=String((result.features || []).length);
}
document.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('ndvi-local-series').addEventListener('change',event=>showNdviResult(localNdviResult,Number(event.target.value)));
  document.getElementById('ndvi-local-period').addEventListener('click',()=>{
    const period=localNdviResult?.available_period;if(!period)return;
    setObservationPeriod(period.from,period.to);
    document.getElementById('ndvi-button').click();
  });
  document.getElementById('scene-footprints').addEventListener('change',event=>{
    if(!scenesLayer || !mapReady)return;
    if(!event.target.checked)removeMapLayer(scenesLayer);
    else if(openMap)scenesLayer.addTo(map);else scenesLayer.setMap(map);
  });
  document.addEventListener('alytha-area-cleared',()=>{
    clearLocalNdvi();document.getElementById('scene-footprints-control').hidden=true;
  });
});
