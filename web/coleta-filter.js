const collectionIssueLabels={sentinel_failure:'Sentinel-2 · falha de consulta',mapbiomas_failure:'MapBiomas · falha de consulta',
  no_reference:'Sem recorte ≥ 5 ha',no_soy:'Sem soja histórica',reference_blocked:'Referência não preparada',
  processing_limit:'Limite de processamento',insufficient_readings:'Leituras insuficientes',credentials:'Credenciais ausentes',
  ibge_failure:'IBGE · falha',conab_failure:'CONAB · falha',ml_pending:'ML · pendente',undetailed:'Causa não detalhada'};
let collectionListLimit=100;
function collectionTrainingLabel(city){
  const t=city?.training;
  return t?.status==='trained'?`Modelo treinado · ${t.areas.toLocaleString('pt-BR')} recortes · ${t.profiles} perfis · dados até ${t.period?.to || 'data não informada'}`:'Sem modelo treinado registrado';
}
function collectionPartialBand(city){
  const value=city.history_completeness?.percent;
  return value===null || value===undefined?'partial_unknown':value<=25?'partial_25':value<=50?'partial_50':value<=75?'partial_75':'partial_100';
}
function collectionStatusLabel(city){
  if(city.status!=='partial')return collectionLabels[city.status] || 'Aguardando';
  const h=city.history_completeness;
  return h?.percent!==null && h?.percent!==undefined?`Parcial · histórico ${h.percent.toLocaleString('pt-BR')}% (${h.years_with_readings}/${h.expected_years} anos)`:'Parcial · histórico não avaliado';
}
function collectionStatusColor(city){
  if(document.getElementById('collection-map-mode')?.value==='training')return city?.training?.status==='trained'?'#7652b3':'#d5ddd3';
  const colors={partial_25:'#ffd600',partial_50:'#d6ad5c',partial_75:'#b9c97c',partial_100:'#79b399',partial_unknown:'#c89c4b'};
  return city?.status==='partial'?colors[collectionPartialBand(city)]:collectionColors[city?.status] || collectionColors.queued;
}
function collectionMatches(city){
  const status=document.getElementById('collection-status-filter').value,cause=document.getElementById('collection-cause-filter').value;
  const normalize=text=>text.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const term=normalize(document.getElementById('collection-name-filter').value.trim());
  const training=document.getElementById('collection-training-filter')?.value || 'all';
  return (training==='all' || (training==='trained')===(city.training?.status==='trained')) && (status==='all' || city.status===status || (city.status==='partial' && status===collectionPartialBand(city))) && (cause==='all' || (city.issues || []).some(issue=>issue.category===cause)) && normalize(city.name+' '+city.uf).includes(term);
}
function collectionIssueText(issue){
  let text=`${issue.source} · ${issue.stage}: ${issue.message}`;
  if(issue.detail?.years)for(const year of issue.detail.years)text+=` ${year.year}: ${year.issue?.message || 'motivo técnico não registrado'}`;
  if(issue.detail?.message)text+=' '+issue.detail.message;
  if(issue.detail?.failures){const reasons=[...new Set(issue.detail.failures.map(f=>f.message))];text+=' '+reasons.join(' ');}
  return text;
}
function renderCollectionList(data){
  const select=document.getElementById('collection-cause-filter'),chosen=select.value;
  const cities=data.municipalities || data.recent || [];
  const counts={};for(const city of cities)for(const category of new Set((city.issues || []).map(issue=>issue.category)))counts[category]=(counts[category] || 0)+1;
  select.replaceChildren(new Option('Todas as causas','all'));
  for(const [key,label] of Object.entries(collectionIssueLabels))select.add(new Option(`${label} (${counts[key] || 0})`,key));
  select.value=chosen || 'all';
  const matches=cities.filter(collectionMatches),rows=[];
  for(const city of matches.slice(0,collectionListLimit)){
    const row=document.createElement('tr'),name=document.createElement('td'),link=document.createElement('a');link.href='/?municipio='+city.code;link.textContent=city.name+' / '+city.uf;name.append(link);
    const status=document.createElement('td');status.textContent=collectionStatusLabel(city);
    const recortes=document.createElement('td');recortes.textContent=`${city.recortes || 0}/${city.recortes_total || 0}`;
    const observations=document.createElement('td');observations.textContent=city.observations || 0;
    const training=document.createElement('td');training.textContent=collectionTrainingLabel(city);training.className='collection-issues';
    const issues=document.createElement('td');issues.className='collection-issues';
    for(const issue of city.issues || []){const line=document.createElement('p');line.textContent=collectionIssueText(issue);issues.append(line);}
    if(!issues.childNodes.length)issues.textContent=city.status==='queued'?'Ainda não consultado.':city.status==='loading'?'Coleta em andamento.':'Sem pendência registrada.';
    row.append(name,status,recortes,observations,training,issues);rows.push(row);
  }
  if(!rows.length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=6;cell.textContent='Nenhum município corresponde aos filtros.';row.append(cell);rows.push(row);}
  document.getElementById('recent').replaceChildren(...rows);
  document.getElementById('collection-filter-count').textContent=`${matches.length} de ${cities.length} municípios correspondem aos filtros · exibindo até ${collectionListLimit}. Os indicadores gerais continuam mostrando toda a rodada.`;
  document.getElementById('collection-show-more').hidden=matches.length<=collectionListLimit;
}
document.addEventListener('DOMContentLoaded',()=>{
  for(const id of ['collection-status-filter','collection-cause-filter','collection-name-filter','collection-training-filter','collection-map-mode'])document.getElementById(id).addEventListener(id==='collection-name-filter'?'input':'change',()=>{
    collectionListLimit=100;if(lastData){renderCollectionList(lastData);window.updateCollectionMap?.(lastData);}
  });
  document.getElementById('collection-show-more').addEventListener('click',()=>{collectionListLimit+=100;if(lastData)renderCollectionList(lastData);});
});
