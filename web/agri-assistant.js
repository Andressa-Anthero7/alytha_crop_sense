/* Session conversation stays with the current map area and period. */
document.addEventListener('DOMContentLoaded',()=>{
  const el=id=>document.getElementById(id),output=el('ai-prompt-status'),input=el('ai-prompt'),send=el('ai-prompt-submit');
  let conversation=[],generation=0,scopeKey=null,conversationId=null,conversationState=null;
  function scope() {
    const context=window.agriAssistantContext?.();
    return JSON.stringify([context?.state_code,context?.municipality_code,context?.map_date,el('mapbiomas-year').value,researchHistory?.id]);
  }
  function reset() {generation++;conversation=[];conversationId=null;conversationState=null;output.replaceChildren();send.disabled=false;scopeKey=scope();}
  function sync() {if(scopeKey!==scope())reset();}
  for(const type of ['alytha-area-selected','alytha-area-cleared','alytha-map-search'])document.addEventListener(type,reset);
  for(const type of ['alytha-soy-date-selected','alytha-region-ready','alytha-soy-context-cleared','alytha-history-ready'])document.addEventListener(type,()=>queueMicrotask(sync));
  for(const id of ['municipality-select','state-select','mapbiomas-year'])el(id).addEventListener('change',()=>queueMicrotask(sync));
  for(const id of ['area-crop','area-season'])el(id)?.addEventListener('change',reset);
  window.addEventListener('popstate',()=>queueMicrotask(sync));

  function turn(label,text,kind) {
    const article=document.createElement('article'),name=document.createElement('span'),message=document.createElement('p');
    article.className='ai-turn ai-turn-'+kind;name.className='ai-turn-name';name.textContent=label;message.textContent=text;
    article.append(name,message);return article;
  }
  function followups(result) {
    output.querySelectorAll('.ai-followups').forEach(row=>row.remove());
    const row=document.createElement('div');row.className='ai-followups';row.setAttribute('aria-label','Continuar a conversa');
    const choices=result.intent==='soy_production' ? [['Mostrar soja no mapa','Mostre as áreas de soja no mapa.']] : [];
    if(!choices.length)return null;
    for(const [label,question] of choices) {
      const button=document.createElement('button');button.type='button';button.textContent=label;
      button.addEventListener('click',()=>{input.value=question;input.focus();});row.append(button);
    }
    return row;
  }
  send.addEventListener('click',async()=>{
    if(send.disabled)return;
    sync();const prompt=input.value.trim(),context=window.agriAssistantContext(),current=generation;
    if(!prompt){input.focus();return;}
    send.disabled=true;
    const question=turn('Você',prompt,'user'),reply=turn('Alytha','Estou olhando o acompanhamento desta área…','assistant');
    reply.setAttribute('aria-busy','true');output.querySelectorAll('.ai-followups').forEach(row=>row.remove());output.append(question,reply);input.value='';input.dispatchEvent(new Event('input'));
    while(output.querySelectorAll('.ai-turn').length>8)output.firstElementChild.remove();
    let navigationTarget=null;
    const stillAtTarget=()=>navigationTarget && new URL(location.href).searchParams.get(navigationTarget.kind==='state'?'estado':'municipio')===navigationTarget.code;
    try {
      const monitoring=window.cropMonitoringContext?.();
      const history=monitoring?.municipality_code===context.municipality_code ? monitoring : researchHistory;
      const dataset=history?.parameters?.municipality_code || history?.municipality_code || '5107925';
      const result=await storageJson('/api/assistant',{prompt,conversation_id:conversationId,conversation:conversation.slice(-3),season:conversationState?.season || el('area-season')?.value || undefined,declared_crop:conversationState?.declared_crop || el('area-crop')?.value || undefined,state_code:context.state_code,municipality_code:context.municipality_code,municipal_job_id:context.municipal_job_id,map_date:conversationState?.map_date || context.map_date,map_year:Number(el('mapbiomas-year').value),crop_class_ids:[...document.querySelectorAll('input[name="map-crop"]:checked')].map(input=>Number(input.value)),dataset_id:dataset===context.municipality_code ? history?.dataset_id || history?.id : undefined,area_geojson:fieldLoaded && !drawingArea ? await fieldGeojson() : undefined});
      if(current!==generation)return;
      if(window.agriAssistantContext().revision!==context.revision)throw Error('O acompanhamento do mapa mudou durante a consulta. Pergunte novamente para considerar os dados atuais.');
      conversationId=result.conversation_id || null;
      conversationState=result.conversation_context || null;
      reply.querySelector('p').textContent=result.answer;
      if(result.work){const status=document.createElement('small');status.textContent=result.work.status==='ready'?'Análise local concluída.':result.work.status==='inconclusive'?'Análise local com dados insuficientes.':'A análise não pôde ser concluída.';reply.append(status);}
      if(result.sources.length || result.limitations.length) {
        const sources=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('p');
        summary.textContent='Fontes e observações';text.textContent=result.sources.map(source=>source.source).join(', ');
        sources.append(summary,text);
        for(const source of result.sources)if(source.url){const link=document.createElement('a');link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=source.source;sources.append(link);}
        if(result.limitations.length) {const note=document.createElement('p');note.textContent=result.limitations.join(' ');sources.append(note);}
        reply.append(sources);
      }
      const choices=followups(result);if(choices)reply.append(choices);
      if(result.action.kind==='show_activity'){
        if(!el('soy-activity-panel').classList.contains('visible'))el('soy-expand-toggle').click();
        const toggle=el('soy-map-classes');toggle.checked=true;toggle.dispatchEvent(new Event('change'));
      }
      if(result.action.kind==='show_collection'){
        const link=document.createElement('a');link.href='/coleta.html';link.target='_blank';link.rel='noopener';link.textContent='Abrir mapa da coleta e treinamento';reply.append(link);window.open('/coleta.html','_blank','noopener');
      }
      if(result.action.kind==='select_region'){
        navigationTarget=result.action.region;
        await window.navigateAssistantRegion(result.action.region);
        const next=window.agriAssistantContext();
        if(result.action.region.kind==='state' && next.state_code!==result.action.region.code)return;
        if(result.action.region.kind==='municipality' && next.municipality_code!==result.action.region.code)return;
        if(result.action.class_ids.length){
          const region=result.action.region,state=region.kind==='state';
          const shown=await window.showCropClasses({class_ids:result.action.class_ids,year:result.map_year,municipality_code:state?undefined:region.code,state_code:state?region.code:undefined,isCurrent:()=>state?new URL(location.href).searchParams.get('estado')===region.code:window.agriAssistantContext().municipality_code===region.code});
          if(!shown)return;
          result.answer=shown.features?'Carreguei as culturas solicitadas no mapa de '+result.action.region.name+'.':'O mapa da localidade abriu, mas não apareceram manchas dessa cultura no enquadramento.';
        }else result.answer='Abri '+result.action.region.name+' / '+result.action.region.uf+' no mapa.';
        reply.querySelector('p').textContent=result.answer;output.append(question,reply);
        conversation.push({question:prompt,answer:result.answer.slice(0,3000)});conversation=conversation.slice(-3);
        scopeKey=scope();return;
      }
      if(result.action.kind==='analyze_area'){
        el('research-panel').open=true;const button=el('start-area-history');
        if(button && !button.disabled)button.click();
        else reply.querySelector('p').textContent='A consulta do histórico já está em andamento.';
      }
      if(result.action.kind==='update_monitoring'){
        const button=el('start-crop-monitoring');
        if(button && !button.disabled)button.click();
        else reply.querySelector('p').textContent='O histórico ainda está carregando ou o acompanhamento já está em atualização.';
      }
      if(result.action.kind==='filter_crops') {
        reply.querySelector('p').textContent='Carregando a camada da cultura no mapa…';
        const shown=await window.showCropClasses({class_ids:result.action.class_ids,year:result.map_year,municipality_code:context.municipality_code || undefined,state_code:context.municipality_code?undefined:context.state_code,focus_results:Boolean(result.map_retry),isCurrent:()=>current===generation && window.agriAssistantContext().revision===context.revision});
        if(current!==generation || window.agriAssistantContext().revision!==context.revision || !shown)return;
        result.answer=shown.hidden ? 'Ocultei as camadas de culturas do mapa.' : shown.features ? `${shown.features} manchas de culturas históricas de ${shown.year} estão visíveis no mapa${result.action.class_ids.length===1 && result.action.class_ids[0]===39?' · soja em dourado':''}. Clique em uma mancha para selecionar a área.` : `Não apareceram manchas dessa cultura no enquadramento de ${shown.year}. Aproxime o mapa para conferir áreas menores.`;
        reply.querySelector('p').textContent=result.answer;
      }
      conversation.push({question:prompt,answer:result.answer.slice(0,3000)});conversation=conversation.slice(-3);
      if(result.action.kind==='show_history')document.dispatchEvent(new Event('alytha-show-history'));
      if(result.action.kind==='view_sorriso') {const url=new URL(location.href);url.searchParams.set('municipio','5107925');url.searchParams.delete('estado');window.history.pushState({},'',url);window.dispatchEvent(new PopStateEvent('popstate'));}
    } catch(error) {
      if(current===generation || stillAtTarget()){reply.querySelector('p').textContent=error.message;output.append(question,reply);if(!input.value)input.value=prompt;}
    } finally {
      reply.removeAttribute('aria-busy');if(current===generation || stillAtTarget())send.disabled=false;
    }
  });
});
