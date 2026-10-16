/* Resize the map's viewport when notebook docks open or close. */
document.addEventListener('DOMContentLoaded',()=>{
  const canvas=document.getElementById('map');
  let frame;
  function resizeMap() {
    cancelAnimationFrame(frame);
    frame=requestAnimationFrame(()=>{
      if(!mapReady)return;
      if(openMap)map.invalidateSize({pan:false,debounceMoveend:true});
      else if(window.google?.maps?.event) {
        const center=map.getCenter();google.maps.event.trigger(map,'resize');
        if(center)map.setCenter(center);
      }
    });
  }
  new ResizeObserver(resizeMap).observe(canvas);
  const aiPanel=document.getElementById('ai-prompt-panel');
  const aiResult=document.getElementById('ai-prompt-status');
  new ResizeObserver(()=>{
    if(!aiPanel.hidden)document.body.style.setProperty('--ai-panel-height',aiPanel.getBoundingClientRect().height+'px');
  }).observe(aiPanel);
  let followLatest=true,scrollFrame;
  function scrollLatest() {
    cancelAnimationFrame(scrollFrame);
    scrollFrame=requestAnimationFrame(()=>{aiResult.scrollTop=aiResult.scrollHeight;});
  }
  aiResult.addEventListener('scroll',()=>{followLatest=aiResult.scrollHeight-aiResult.clientHeight-aiResult.scrollTop<=12;});
  new ResizeObserver(()=>{if(followLatest)scrollLatest();}).observe(aiResult);
  new MutationObserver(()=>{
    document.body.classList.toggle('ai-has-conversation',aiResult.childElementCount>0);
    followLatest=true;scrollLatest();
  })
    .observe(aiResult,{childList:true,subtree:true,characterData:true});
  document.addEventListener('alytha-map-ready',resizeMap);
  document.getElementById('panel-toggle').setAttribute('aria-expanded',String(!document.getElementById('side-panel').classList.contains('closed')));
  if(matchMedia('(min-width:1000px)').matches)document.getElementById('crop-layers-panel').open=false;
  let searchedCity=null,municipalJob=null,selectedDate='',contextRevision=0;
  const citySelect=document.getElementById('municipality-select');
  function assistantContext() {
    const code=searchedCity!==null ? searchedCity.municipality_code : citySelect.value || new URL(location.href).searchParams.get('municipio') || '';
    const stateCode=code ? code.slice(0,2) : new URL(location.href).searchParams.get('estado') || document.getElementById('state-select').value || '';
    const name=searchedCity!==null ? searchedCity.municipality_name : citySelect.value===code && code ? citySelect.selectedOptions[0]?.textContent : code ? 'Município '+code : 'Localidade não selecionada';
    const job=municipalJob?.parameters?.municipality_code===code ? municipalJob : null;
    return {municipality_code:code,state_code:stateCode,municipal_job_id:job?.id,map_date:job ? selectedDate || job.parameters.as_of : undefined,name,revision:contextRevision};
  }
  window.agriAssistantContext=assistantContext;
  document.addEventListener('alytha-map-search',event=>{searchedCity=event.detail;contextRevision++;});
  for(const id of ['municipality-select','state-select'])document.getElementById(id).addEventListener('change',()=>{searchedCity=null;contextRevision++;});
  document.getElementById('mapbiomas-year').addEventListener('change',()=>{contextRevision++;});
  window.addEventListener('popstate',()=>{searchedCity=null;contextRevision++;});
  document.addEventListener('alytha-soy-job-updated',event=>{municipalJob=event.detail;});
  document.addEventListener('alytha-soy-context-cleared',()=>{municipalJob=null;selectedDate='';contextRevision++;});
  document.addEventListener('alytha-soy-date-selected',event=>{if(selectedDate!==event.detail.date)contextRevision++;selectedDate=event.detail.date;});
  for(const type of ['alytha-area-selected','alytha-area-cleared'])document.addEventListener(type,()=>{contextRevision++;});
  for(const type of ['alytha-crop-monitoring-updated','alytha-crop-monitoring-cleared'])document.addEventListener(type,()=>{contextRevision++;});
  document.querySelectorAll('[data-ai-question]').forEach(button=>button.addEventListener('click',()=>{
    document.getElementById('ai-prompt').value=button.dataset.aiQuestion;
    document.getElementById('ai-prompt').dispatchEvent(new Event('input'));
    document.getElementById('ai-prompt').focus();
  }));
  document.getElementById('ai-prompt').addEventListener('keydown',event=>{
    if(event.key==='Enter' && !event.shiftKey && !event.isComposing) {event.preventDefault();document.getElementById('ai-prompt-submit').click();}
  });
  const prompt=document.getElementById('ai-prompt');
  const narrowPrompt=matchMedia('(max-width:600px)');
  const fullPlaceholder=prompt.placeholder;
  const resizePlaceholder=()=>{prompt.placeholder=narrowPrompt.matches?'Pergunte à Alytha…':fullPlaceholder;};
  resizePlaceholder();
  narrowPrompt.addEventListener('change',resizePlaceholder);
  prompt.addEventListener('input',()=>{
    prompt.style.height='auto';
    prompt.style.height=Math.min(prompt.scrollHeight,140)+'px';
  });

  for(const prefix of ['soy','ndvi'])document.getElementById(prefix+'-panel-close').addEventListener('click',()=>{
    document.getElementById(prefix==='soy'?'soy-activity-panel':'ndvi-panel').classList.remove('visible');
  });
});
