const el=id=>document.getElementById(id);
const names={MT:'Mato Grosso',MS:'Mato Grosso do Sul',GO:'Goiás',DF:'Distrito Federal'};
const fmt=value=>(value || 0).toLocaleString('pt-BR');
const percent=(part,total)=>total?Math.min(100,part/total*100):0;
const date=value=>new Date(value).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'});
let fetching=false,lastData=null,lastFetchAt=0,offline=false;
const STALLED_AFTER=120000;
function elapsed(value){const seconds=Math.max(0,Math.floor((Date.now()-new Date(value).getTime())/1000));return seconds<60?`${seconds}s`:`${Math.floor(seconds/60)}min ${seconds%60}s`;}
function liveState(city,data){
  if(offline)return 'offline';
  if(Date.now()-new Date(data.generated_at).getTime()>45000)return 'stale';
  return city.progress_at && Date.now()-new Date(city.progress_at).getTime()>STALLED_AFTER?'stalled':'loading';
}
function updateLive(){
  if(!lastData)return;
  const data=lastData,cities=data.states.flatMap(state=>state.active.map(city=>({...city,uf:state.uf})));
  const stale=Date.now()-new Date(data.generated_at).getTime()>45000;
  const loading=cities.some(city=>liveState(city,data)==='loading');
  el('connection').textContent=offline?'Sem conexão':data.status!=='running'?'Rodada encerrada':stale?'Parado · monitor sem atualização':loading?'Carregando dados…':cities.length?'Parado · sem avanço':'Aguardando a fila';
  el('connection').classList.toggle('live',loading && !offline && data.status==='running');
  el('warning').hidden=!(offline || stale);
  if(stale && !offline)el('warning').textContent='O monitor não atualiza há mais de 45 segundos. Exibindo o último registro; verifique se o computador e o monitor estão ativos.';
  el('next-refresh').textContent=fetching?'Atualizando status…':`Próxima atualização em ${Math.max(0,10-Math.floor((Date.now()-lastFetchAt)/1000))}s`;
  const lines=cities.map(city=>{
    const state=liveState(city,data),line=node('div',undefined,'live-city '+state);
    line.append(node('i',undefined,state==='loading'?'spinner':'dot amber'),node('strong',`${city.name} / ${city.uf}`));
    const message=state==='loading'?'Carregando…':state==='offline'?'Sem conexão · último registro':state==='stale'?'Parado · monitor sem atualização':'Parado · sem avanço';
    line.append(node('span',`${message}${city.progress_at?' · último avanço há '+elapsed(city.progress_at):' · observando o primeiro avanço'}`));
    return line;
  });
  if(!lines.length)lines.push(node('p',data.status==='running'?'Aguardando o próximo município da fila.':'Coleta encerrada. Consulte as pendências abaixo.'));
  el('live-cities').replaceChildren(...lines);
  document.querySelectorAll('.city-live-status').forEach(label=>{
    const city=cities.find(c=>c.code===label.dataset.code);if(!city)return;
    const state=liveState(city,data);label.className='city-live-status '+state;
    label.textContent=(state==='loading'?'Carregando':state==='stalled'?'Sem avanço há mais de 2 minutos':state==='offline'?'Sem conexão':'Monitor sem atualização')+(city.progress_at?' · último avanço há '+elapsed(city.progress_at):'');
  });
  document.querySelectorAll('.state-live-tag').forEach(label=>{
    const states=cities.filter(c=>c.uf===label.dataset.uf).map(city=>liveState(city,data));
    const running=states.includes('loading');
    label.textContent=running?'Carregando…':offline?'Sem conexão':'Parado · sem avanço';
    label.classList.toggle('active',running);
  });
}
function node(tag,text,className){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(className)n.className=className;return n;}
function mini(container,label,part,total){
  container.append(node('p',`${label}: ${fmt(part)} / ${fmt(total)}`));
  const track=node('div',undefined,'mini-track'),bar=node('div');bar.style.width=percent(part,total)+'%';track.append(bar);container.append(track);
}
function render(data){
  lastData=data;
  window.updateCollectionMap?.(data);
  const ratio=percent(data.processed,data.total);
  el('processed').textContent=fmt(data.processed);el('total').textContent='/ '+fmt(data.total);
  el('percentage').textContent=ratio.toLocaleString('pt-BR',{maximumFractionDigits:1})+'%';
  el('overall-bar').style.width=ratio+'%';el('overall-bar').setAttribute('aria-valuenow',ratio.toFixed(1));
  for(const key of ['ready','partial','errors'])el(key).textContent=fmt(data[key]);
  el('pending').textContent=fmt(Math.max(0,data.total-data.processed));
  el('summary').textContent=data.status==='running'?'Municípios concluídos nesta rodada, incluindo resultados parciais e falhas.':data.status==='finished'?'Rodada concluída.':'Rodada encerrada com pendências para revisar.';
  el('updated').textContent='Atualização: '+date(data.generated_at);
  const cards=[];
  for(const state of data.states){
    const card=node('article',undefined,'state'),top=node('div',undefined,'state-top'),name=node('div',undefined,'state-name');
    name.append(node('span',state.uf,'uf'),node('h3',names[state.uf] || state.uf));
    const active=state.active.length>0;
    const tag=node('span',active?'Carregando…':state.status==='queued'?'Na fila':state.status==='ready'?'Concluído':state.status==='partial'?'Encerrado · parcial':state.status==='error'?'Com falha':'Aguardando',active?'tag active state-live-tag':'tag');tag.dataset.uf=state.uf;
    top.append(name,tag);card.append(top);
    const count=node('div',undefined,'state-count');count.append(node('span',`${fmt(state.processed)} de ${fmt(state.total)} processados`),node('span',percent(state.processed,state.total).toLocaleString('pt-BR',{maximumFractionDigits:1})+'%'));card.append(count);
    const track=node('div',undefined,'track'),bar=node('div',undefined,'fill');bar.style.width=percent(state.processed,state.total)+'%';track.append(bar);card.append(track);
    for(const city of state.active){
      const current=node('div',undefined,'active-city');current.append(node('strong',city.name));
      const live=node('p',undefined,'city-live-status');live.dataset.code=city.code;current.append(live);
      const phases={dossier:'Reunindo IBGE, CONAB e MapBiomas',satellite:'Consultando imagens de satélite',learning:'Aprendendo perfis de vegetação'};
      current.append(node('p',phases[city.phase] || 'Coletando dados'));
      if(city.activity?.total)mini(current,'Recortes recentes',city.activity.processed,city.activity.total);
      if(city.history?.total){mini(current,'Anos do histórico de referência',city.history.processed,city.history.total);current.append(node('p',`${fmt(city.history.observations)} leituras históricas · ${city.history.status==='partial'?'alguns anos indisponíveis':city.history.status==='ready'?'histórico processado':'histórico em coleta'}`));}
      card.append(current);
    }
    if(!active)card.append(node('p',state.status==='queued'?'A região entra quando um trabalhador ficar livre.':`${fmt(state.ready)} completos · ${fmt(state.partial)} parciais · ${fmt(state.errors)} com falha`,'state-idle'));
    cards.push(card);
  }
  el('states').replaceChildren(...cards);
  renderCollectionList(data);
  updateLive();
}
async function refresh(){
  if(fetching)return;fetching=true;
  try{
    const response=await fetch('/collection-data.json',{cache:'no-store',signal:AbortSignal.timeout(8000)});
    if(!response.ok)throw Error('Sem relatório');offline=false;lastFetchAt=Date.now();render(await response.json());
  }catch(error){offline=true;el('connection').textContent='Sem conexão';el('connection').classList.remove('live');el('warning').hidden=false;el('warning').textContent='Não foi possível atualizar. Os resultados exibidos são os últimos disponíveis. Nova tentativa automática em 10 segundos.';updateLive();}
  finally{fetching=false;}
}
refresh();setInterval(refresh,10000);
setInterval(updateLive,1000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
