function renderVegetationProgression(output,result) {
  const heading=document.createElement('strong');heading.textContent='Direção da evolução · experimental';output.append(heading);
  const lines=[];
  if(result?.status==='detected') {
    for(const front of result.fronts)lines.push(`${front.signal==='vegetation_gain'?'Ganho':'Perda'} de vegetação em direção a ${front.direction_label} · ${front.affected_area_ha.toLocaleString('pt-BR',{maximumFractionDigits:2})} ha envolvidos. ${front.reading}`);
    for(const front of result.fronts)if(Number.isFinite(front.spatial_order_r2))lines.push(`Organização espacial da sequência (R²): ${front.spatial_order_r2.toLocaleString('pt-BR',{maximumFractionDigits:3})}. Descreve o alinhamento entre posição e momento da mudança; não é probabilidade de plantio ou rebrota.`);
    if(result.periods)lines.push(`Sequência entre ${result.periods[0].from.split('-').reverse().join('/')} e ${result.periods.at(-1).to.split('-').reverse().join('/')}. As setas ligam centros de setores que mudaram antes e depois; não mostram o trajeto de máquinas.`);
  } else lines.push(result?.status==='not_detected'?'Sem direção consistente detectada: a mudança pode ser simultânea, dispersa ou pequena demais.':'Sem análise de direção disponível para este resultado. Execute uma nova comparação espacial.');
  lines.push('Plantio e colheita são hipóteses para conferir com o produtor. Não identifica linhas de plantio, soja atual ou a operação realizada.');
  for(const text of lines){const p=document.createElement('p');p.className='analysis-subtitle';p.textContent=text;output.append(p);}
}
function progressionPopup(properties) {
  return `Sequência de ${properties.signal==='vegetation_gain'?'ganho':'perda'} de vegetação em direção a ${properties.direction_label}. ${properties.reading} Não confirma a operação realizada.`;
}
