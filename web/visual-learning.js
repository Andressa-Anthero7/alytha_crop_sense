document.addEventListener('DOMContentLoaded',()=>{
  const el=id=>document.getElementById(id);
  let history=null,revision=0,timer;
  const text=(parent,value)=>{const p=document.createElement('p');p.className='analysis-subtitle';p.textContent=value;parent.append(p);};
  function show(job) {
    const output=el('visual-learning-results');output.replaceChildren();
    const labels={running:'Preparando imagens e consultando a IA…',pending:'Análise visual na fila.',ready:'Análise visual concluída com imagens enviadas à IA.',waiting_images:'Aguardando imagens reais utilizáveis.',retry:'A análise visual ficou pendente; nova tentativa necessária.'};
    el('visual-learning-status').textContent=labels[job.status] || job.status;
    if(job.issue)text(output,job.issue.message);
    for(const issue of job.issues || [])text(output,issue.message);
    for(const asset of job.assets || []) {
      const figure=document.createElement('figure');figure.style.margin='8px 0';
      const img=document.createElement('img');img.src='/api/visual-learning/assets/'+asset.id+'.png';
      img.alt=`${asset.kind==='true_color'?'Cor natural':'Mapa NDVI'} · ${asset.period.from} a ${asset.period.to}`;
      img.style.maxWidth='100%';img.style.maxHeight='260px';img.style.objectFit='contain';img.loading='lazy';
      const caption=document.createElement('figcaption');caption.className='analysis-subtitle';
      caption.textContent=`${img.alt} · ${(asset.valid_fraction*100).toLocaleString('pt-BR',{maximumFractionDigits:0})}% do recorte com pixels válidos. ${asset.note}`;
      figure.append(img,caption);output.append(figure);
    }
    if(job.review) {
      text(output,job.review.provider+' · '+job.review.model);
      text(output,job.review.answer);
      for(const observation of job.review.visual_observations || [])text(output,observation.description);
      for(const value of job.review.hypotheses || [])text(output,'Hipótese: '+value);
      for(const value of job.review.field_checks || [])text(output,'Verificar em campo: '+value);
      for(const value of job.review.limitations || [])text(output,value);
    }
    if(job.missing_true_color)text(output,'Esta rodada dispõe de mapas NDVI. A imagem em cor natural ainda está indisponível; ela não foi simulada.');
  }
  async function watch(job,current) {
    if(current!==revision)return;
    show(job);
    if(job.status==='running' || job.status==='pending') {
      timer=setTimeout(async()=>{
        try{await watch(await storageJson('/api/visual-learning/'+job.id),current);}
        catch(error){if(current===revision)el('visual-learning-status').textContent=error.message;}
      },2500);
    } else el('start-visual-learning').disabled=!history;
  }
  document.addEventListener('alytha-history-ready',event=>{
    history=event.detail;revision++;clearTimeout(timer);
    el('start-visual-learning').disabled=!['ready','partial'].includes(history.status);
    el('visual-learning-status').textContent='A IA configurada receberá imagens deste recorte, com data e qualidade, junto das medições.';
    el('visual-learning-results').replaceChildren();
  });
  for(const name of ['alytha-area-selected','alytha-area-cleared','alytha-history-cleared'])document.addEventListener(name,()=>{
    history=null;revision++;clearTimeout(timer);el('start-visual-learning').disabled=true;
    el('visual-learning-results').replaceChildren();el('visual-learning-status').textContent='Abra o histórico da área para analisar suas imagens.';
  });
  el('start-visual-learning').addEventListener('click',async()=>{
    if(!history)return;const current=++revision;clearTimeout(timer);el('start-visual-learning').disabled=true;
    try{await watch(await storageJson('/api/visual-learning',{dataset_id:history.id}),current);}
    catch(error){if(current===revision){el('visual-learning-status').textContent=error.message;el('start-visual-learning').disabled=!history;}}
  });
});
