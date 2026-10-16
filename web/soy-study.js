/* Research catalogue, deliberately separate from diagnosis of the selected polygon. */
document.addEventListener('DOMContentLoaded',()=>{
  const panel=document.getElementById('soy-study-panel'),selector=document.getElementById('soy-study-topic'),output=document.getElementById('soy-study-content'),status=document.getElementById('soy-study-status');
  let catalogue=null,loading=false;
  function add(tag,value,parent=output) {const element=document.createElement(tag);element.textContent=value;parent.append(element);return element;}
  function render() {
    output.replaceChildren();const topic=catalogue.topics.find(t=>t.id===selector.value);if(!topic)return;
    add('strong',topic.name);add('p',topic.question);
    for(const [label,value] of [['Objetivo',topic.objective],['O que estudar no sistema',topic.system],['O que conferir no campo',topic.field],['Limite da leitura',topic.limit]]) {
      const section=document.createElement('details');output.append(section);add('summary',label,section);add('p',value,section);
    }
    const sources=document.createElement('details');output.append(sources);add('summary','Referências consultadas',sources);
    for(const id of topic.sources) {
      const source=catalogue.sources.find(s=>s.id===id),link=add('a',source.title,sources);link.href=source.url;link.target='_blank';link.rel='noopener';add('small',source.scope,sources);
    }
    add('small','Planejamento: '+topic.work);
  }
  panel.addEventListener('toggle',async()=>{
    if(!panel.open || catalogue || loading)return;loading=true;status.textContent='Carregando trilha de estudo…';
    try {
      const response=await fetch('/soy-study.json');if(!response.ok)throw Error('Não foi possível carregar a trilha de estudo.');
      catalogue=await response.json();selector.replaceChildren();
      for(const group of new Set(catalogue.topics.map(t=>t.group))) {
        const options=document.createElement('optgroup');options.label=group;
        for(const topic of catalogue.topics.filter(t=>t.group===group))options.append(new Option(topic.name,topic.id));selector.append(options);
      }
      selector.disabled=false;status.textContent=`${catalogue.topics.length} temas · pesquisa inicial em ${catalogue.researched_at.split('-').reverse().join('/')}. Não é uma classificação da área atual.`;
      const roadmap=document.getElementById('soy-study-roadmap');roadmap.replaceChildren();
      for(const feature of catalogue.features) {add('strong',feature.title,roadmap);add('small',feature.status,roadmap);add('p',feature.next,roadmap);}
      render();
    } catch(error){catalogue=null;status.textContent=error.message;}finally{loading=false;}
  });
  selector.addEventListener('change',render);
});
