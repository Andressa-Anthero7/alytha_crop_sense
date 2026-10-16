/* Explicit climate screening follows the selected polygon; no background collection. */
document.addEventListener('DOMContentLoaded',()=>{
  const el=id=>document.getElementById(id),output=el('planting-results'),button=el('start-planting');
  let revision=0,controller=null;
  const fields={soil_condition:'planting-soil',drainage:'planting-drainage',fertility:'planting-fertility',calendar:'planting-calendar',zarc:'planting-zarc',water_management:'planting-water'};
  function invalidate(resetFields=false) {
    revision++;controller?.abort();controller=null;button.disabled=false;output.replaceChildren();
    el('planting-status').textContent='Avalie novamente para usar a área e as verificações atuais.';
    if(resetFields)for(const [key,id] of Object.entries(fields))el(id).value=key==='water_management'?'rainfed':'unknown';
  }
  for(const id of Object.values(fields))el(id).addEventListener('change',()=>invalidate());
  function text(tag,value,parent=output,className) {
    const node=document.createElement(tag);node.textContent=value;if(className)node.className=className;parent.append(node);return node;
  }
  function link(label,url,parent) {
    const a=text('a',label,parent);a.href=url;a.target='_blank';a.rel='noopener';return a;
  }
  const date=value=>value.split('-').reverse().join('/');
  function conclusion(result) {
    const factors=result.factors,byKey=Object.fromEntries(factors.map(f=>[f.key,f]));
    const actions={
      calendar:['Há restrição no calendário de plantio','Foi informado que a data está fora do calendário sanitário permitido.','Confira o calendário oficial vigente antes de programar a semeadura.'],
      zarc:['Data fora da janela ZARC informada','A janela consultada não atende ao município, cultivar e solo informados.','Revise a data e a combinação de cultivar e solo no ZARC.'],
      soil_condition:result.field_inputs.soil_condition==='waterlogged'?['Solo encharcado: condição desfavorável','A condição de campo informada impede considerar o solo adequado agora.','Reavalie a umidade e a trafegabilidade no campo antes de programar o plantio.']:['Solo seco: condição desfavorável','Foi informada falta de umidade na profundidade da semente.','Confirme a reposição de água no solo antes de programar o plantio.'],
      drainage:['Drenagem ou acesso com problema','Há restrição de drenagem ou trafegabilidade informada para a área.','Resolva ou avalie essa restrição em campo antes de programar a operação.'],
      fertility:['Correção do solo pendente','A análise e as correções do solo ainda não foram atendidas.','Revise as correções com o responsável técnico antes de programar o plantio.'],
      soil_temperature:['Temperatura do solo fora da faixa de referência','A média estimada a 6 cm está fora de 20 a 30 °C.','Meça a temperatura na profundidade da semente e reavalie a data.'],
      dry_spell:['Pouca reposição de chuva para o sequeiro','Houve pouca chuva recente e há pouca chuva prevista pelos critérios usados.','Confira a umidade na profundidade da semente; não decida apenas pela previsão.'],
      heavy_rain:['Chuva intensa prevista: atenção à operação','A previsão atingiu o limite de alerta usado para chuva intensa.','Confira drenagem, encharcamento e acesso antes de programar a semeadura.'],
      air_temperature:['Extremo de temperatura previsto','A previsão do ar atingiu o limite de atenção usado nesta avaliação.','Confira a temperatura do solo e acompanhe a próxima atualização da previsão.']
    };
    const priorities=['calendar','zarc','soil_condition','drainage','fertility','soil_temperature','heavy_rain','dry_spell','air_temperature'];
    const main=priorities.find(key=>byKey[key]?.status==='attention');
    if(main)return {title:actions[main][0],reason:actions[main][1],next:actions[main][2],state:'attention'};
    const climateMissing=factors.some(f=>f.status==='missing' && !['soil_condition','drainage','fertility','calendar','zarc','ndvi'].includes(f.key));
    if(climateMissing)return {title:'Ainda não dá para avaliar o clima',reason:'Os dados de clima ou solo estimado estão incompletos ou desatualizados.',next:'Atualize a consulta. Enquanto faltarem esses dados, confira chuva e condição do solo no campo.',state:'incomplete'};
    if(result.status==='favorable')return {title:'Condições avaliadas favoráveis ao plantio',reason:'Sem alertas nos critérios climáticos; as verificações de campo e de janela foram informadas como atendidas.',next:'Confirme que essas condições continuam válidas no momento da operação com o responsável técnico.',state:'favorable'};
    const pending=['soil_condition','drainage','calendar','zarc','fertility'].find(key=>byKey[key]?.status==='missing');
    const checks={soil_condition:'Confira se o solo está úmido e em condição física adequada na profundidade da semente.',drainage:'Confira drenagem e trafegabilidade na área.',fertility:'Confira a análise e as correções do solo.',calendar:'Confira o calendário sanitário local vigente.',zarc:'Confira a janela ZARC para município, cultivar e solo.'};
    return {title:'Clima sem alerta; área ainda não confirmada',reason:'Os critérios climáticos avaliados não indicaram restrição. Ainda faltam '+(pending?'verificações de campo ou da janela de plantio.':'dados recentes da cobertura vegetal do recorte.'),next:checks[pending] || 'Atualize ou confira em campo a cobertura vegetal e o manejo atual da área.',state:'incomplete'};
  }
  function render(result) {
    output.replaceChildren();
    const summary=document.createElement('div');summary.className='planting-verdict';summary.dataset.status=result.status;output.append(summary);
    const verdict=conclusion(result);
    text('strong',verdict.title,summary);
    text('p',verdict.reason,summary,'planting-conclusion-reason');
    text('small','Próximo passo',summary);
    text('p',verdict.next,summary,'planting-next-step');
    if(result.attention.length>1)text('small',`Há mais ${result.attention.length-1} ponto(s) de atenção nos detalhes.`,summary);
    text('span',`Soja · avaliação em ${date(result.as_of)}`,summary);
    const keyNumbers=document.createElement('div');keyNumbers.className='planting-key-numbers';output.append(keyNumbers);
    for(const [key,label] of [['rain7','Chuva recente · 7 dias'],['forecast7','Chuva prevista · 7 dias'],['soil_temperature','Solo a 6 cm · ontem']]) {
      const factor=result.factors.find(f=>f.key===key),row=document.createElement('div');
      text('span',label,row);text('strong',Number.isFinite(factor?.value)?`${factor.value.toLocaleString('pt-BR',{maximumFractionDigits:1})} ${factor.unit}`:'Sem dados',row);keyNumbers.append(row);
    }
    if(result.missing.some(key=>['soil_condition','drainage','fertility','calendar','zarc'].includes(key))) {
      const complete=text('button','Completar verificações da área');complete.type='button';complete.addEventListener('click',()=>{
        const checks=document.querySelector('#planting-panel > details');checks.open=true;checks.scrollIntoView({block:'start',behavior:'smooth'});
      });
    }
    const details=document.createElement('details');details.className='planting-evidence';output.append(details);
    text('summary',`Ver critérios e pendências (${result.factors.length})`,details);
    const evidence=document.createElement('div');details.append(evidence);
    if(result.weather_error)text('p',result.weather_error,evidence,'planting-warning');
    const periods=result.periods;
    text('p',`Clima recente: ${date(periods.recent_from)} a ${date(periods.recent_to)}. Previsão: ${date(periods.forecast_from)} a ${date(periods.forecast_to)}.`,evidence,'analysis-subtitle');
    const labels={favorable:'Favorável neste critério',attention:'Atenção',missing:'Pendente',context:'Contexto'};
    // Put actionable factors and missing evidence before descriptive climate totals.
    const order={attention:0,missing:1,favorable:2,context:3};
    for(const factor of [...result.factors].sort((a,b)=>order[a.status]-order[b.status])) {
      const card=document.createElement('div');card.className='planting-factor';card.dataset.status=factor.status;card.dataset.factor=factor.key;evidence.append(card);
      text('small',labels[factor.status],card);text('strong',factor.label,card);text('p',factor.reading,card);text('small',factor.source,card);
    }
    const source=document.createElement('details');output.append(source);text('summary','Fontes e limites desta avaliação',source);
    text('p',result.note,source);
    if(result.weather) {
      const weather=result.weather,point=weather.requested_point,grid=weather.grid_point;
      text('p',`${weather.source}. Atualização: ${new Date(weather.fetched_at).toLocaleString('pt-BR')}. ${weather.cache?.stale?'Cache desatualizado.':weather.cache?.hit?'Dados salvos recentes.':'Consulta atualizada.'} Dias no fuso America/Sao_Paulo.`,source);
      if(point)text('p',`Ponto consultado: ${point.latitude}, ${point.longitude}. Célula retornada: ${grid?.latitude ?? 'não informada'}, ${grid?.longitude ?? 'não informada'}. Não representa variações internas do talhão.`,source);
      link('Open-Meteo · documentação e atribuição',weather.documentation_url,source);
    }
    link('Embrapa · condições de semeadura da soja',result.agronomy_url,source);
    const report=text('button','Exportar avaliação JSON');report.type='button';report.addEventListener('click',()=>{
      const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download=`condicoes-plantio-soja-${result.as_of}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });
  }
  button.addEventListener('click',async()=>{
    invalidate();const current=revision;
    if(!mapReady || !fieldLoaded || drawingArea) {el('planting-status').textContent='Selecione uma área ou conclua o desenho antes de avaliar o plantio.';return;}
    button.disabled=true;controller=new AbortController();
    el('planting-status').textContent='Consultando clima, solo estimado e leituras salvas da área…';
    try {
      const geojson=await fieldGeojson();if(current!==revision)return;
      const field_inputs=Object.fromEntries(Object.entries(fields).map(([key,id])=>[key,el(id).value]));
      const response=await fetch('/api/planting-readiness',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({geojson,field_inputs}),signal:controller.signal});
      const result=await response.json();if(current!==revision)return;
      if(!response.ok || result.error)throw Error(result.error || 'Não foi possível avaliar as condições para plantio.');
      render(result);el('planting-status').textContent='Avaliação concluída.';
      output.querySelector('.planting-verdict').scrollIntoView({block:'start',behavior:'smooth'});
    } catch(error) {
      if(current===revision && error.name!=='AbortError')el('planting-status').textContent=error.message;
    } finally {if(current===revision){button.disabled=false;controller=null;}}
  });
  document.addEventListener('alytha-area-selected',event=>{invalidate(true);el('planting-scope').textContent=`Recorte: ${event.detail.name}. Avaliação das condições atuais; não usa as datas do gráfico.`;});
  document.addEventListener('alytha-area-cleared',()=>{invalidate(true);el('planting-scope').textContent='Selecione uma área no mapa.';el('planting-status').textContent='Aguardando área selecionada.';});
});
