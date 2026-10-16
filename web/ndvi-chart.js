/* Shared interactive time series for Sentinel-2 and SATVeg. */
const SOY_ACTIVITY_CLASSES={
  possible_inactive:{label:'Pouca vegetação persistente',color:'#c7b18a'},
  not_matched:{label:'Vegetação observada no período',color:'#33816d'},
  unknown:{label:'Sem leitura suficiente',color:'#c5cdd2'}
};
function ndviSeasonalReference(point, history) {
  const usable=p=>Number.isFinite(p.ndvi_mean) && p.ndvi_mean>=-1 && p.ndvi_mean<=1 && Number.isFinite(p.valid_fraction) && p.valid_fraction>=.5 && p.valid_fraction<=1 && Number.isFinite(p.valid_pixels) && p.valid_pixels>=50;
  const year=Number(point.date.slice(0,4)),month=point.date.slice(5,7),groups=new Map(),seen=new Set();
  for(const p of history) {
    if(!usable(p) || !Number.isFinite(Date.parse(p.date)) || seen.has(p.date))continue;
    seen.add(p.date);
    const priorYear=Number(p.date.slice(0,4));
    if(priorYear>=year || p.date.slice(5,7)!==month || (p.available && p.available>point.date))continue;
    if(!groups.has(priorYear))groups.set(priorYear,[]);
    groups.get(priorYear).push(p.ndvi_mean);
  }
  const years=[...groups].filter(([,values])=>values.length>=2).sort((a,b)=>a[0]-b[0]);
  if(years.length<3)return null;
  const means=years.map(([,values])=>values.reduce((sum,v)=>sum+v,0)/values.length);
  const mean=means.reduce((sum,v)=>sum+v,0)/means.length;
  const spread=Math.sqrt(means.reduce((sum,v)=>sum+(v-mean)**2,0)/(means.length-1));
  return {mean,lower:Math.max(-1,mean-spread),upper:Math.min(1,mean+spread),years:years.map(([year])=>year),currentUsable:usable(point)};
}
function ndviEmergenceSignal(point, history, aggregationDays=5) {
  const day=86400000,end=Date.parse(point.date)+(aggregationDays-1)*day,start=end-27*day;
  const unique=new Map();
  for(const p of history) {
    const when=Date.parse(p.date),available=p.available?Date.parse(p.available):when+(aggregationDays-1)*day;
    if(!Number.isFinite(when) || !Number.isFinite(available) || when<start || when>Date.parse(point.date) || available>end || available<when)continue;
    if(!Number.isFinite(p.ndvi_mean) || p.ndvi_mean< -1 || p.ndvi_mean>1 || !Number.isFinite(p.valid_fraction) || p.valid_fraction<.5 || p.valid_fraction>1 || !Number.isFinite(p.valid_pixels) || p.valid_pixels<50)continue;
    const previous=unique.get(p.date);
    if(!previous || p.valid_fraction>previous.valid_fraction)unique.set(p.date,p);
  }
  const points=[...unique.values()].sort((a,b)=>a.date.localeCompare(b.date));
  const insufficient=reason=>({status:'insufficient',reason,observations:points.length});
  if(points.length<4 || !points.some(p=>p.date===point.date))return insufficient('São necessárias quatro leituras válidas, incluindo a data selecionada, nas últimas quatro semanas.');
  const span=(Date.parse(points.at(-1).date)-Date.parse(points[0].date))/day;
  const gaps=points.slice(1).map((p,i)=>(Date.parse(p.date)-Date.parse(points[i].date))/day);
  if(span<14 || Math.max(...gaps)>10 || (Date.parse(points[0].date)-start)/day>10)return insufficient('As leituras precisam cobrir ao menos 14 dias, sem lacunas maiores que 10 dias.');
  const coverage=points.map(p=>p.valid_fraction);
  if(Math.max(...coverage)-Math.min(...coverage)>.2+1e-9)return insufficient('A cobertura observada variou mais de 20 pontos percentuais; a mudança pode refletir partes diferentes da área.');
  const values=points.map(p=>p.ndvi_mean),delta=values.at(-1)-values[0];
  const times=points.map(p=>(Date.parse(p.date)-Date.parse(points[0].date))/day);
  const meanTime=times.reduce((s,v)=>s+v,0)/times.length,mean=values.reduce((s,v)=>s+v,0)/values.length;
  const slope=times.reduce((s,t,i)=>s+(t-meanTime)*(values[i]-mean),0)/times.reduce((s,t)=>s+(t-meanTime)**2,0);
  const steps=values.slice(1).map((v,i)=>v-values[i]);
  const detected=values[0]<=.25 && values[1]<=.25 && delta>=.15-1e-9 && slope>=.005-1e-9 && steps.filter(v=>v>=.03-1e-9).length>=2 && steps.every(v=>v>=-.03-1e-9);
  return {status:detected?'possible_emergence':'not_detected',observations:points.length,span,delta,slope,first:points[0],last:points.at(-1)};
}
function renderNdviReading(detail,points,selected,periodLabel,history=points,aggregationDays=5) {
  const point=points[selected];
  const number=value=>value.toLocaleString('pt-BR',{minimumFractionDigits:3,maximumFractionDigits:3});
  const date=value=>new Intl.DateTimeFormat('pt-BR',{timeZone:'UTC'}).format(new Date(value));
  const sufficient=p=>p.ndvi_mean>=-1 && p.ndvi_mean<=1 && Number.isFinite(p.valid_fraction) && p.valid_fraction>=.5 && p.valid_fraction<=1 && Number.isFinite(p.valid_pixels) && p.valid_pixels>=50;
  const currentOk=sufficient(point);
  const previous=points.slice(0,selected).reverse().find(p=>p.date<point.date && sufficient(p));
  const difference=currentOk && previous ? Number((point.ndvi_mean-previous.ndvi_mean).toFixed(3)) : null;
  const add=(text,className)=>{const span=document.createElement('span');span.textContent=text;if(className)span.className=className;detail.append(span);return span;};
  detail.replaceChildren();
  add(periodLabel,'ndvi-reading-date');
  add(!currentOk?'Leitura com dados insuficientes para comparação':point.ndvi_mean<=.25?'Pouca vegetação na parte observada':'Vegetação presente na parte observada','ndvi-reading-state');
  const metrics=document.createElement('span');metrics.className='ndvi-metrics';
  const coverage=Number.isFinite(point.valid_fraction)?`${(Math.max(0,Math.min(1,point.valid_fraction))*100).toLocaleString('pt-BR',{maximumFractionDigits:1})}%`:'Não informada';
  for(const [label,value] of [['NDVI médio',number(point.ndvi_mean)],['Área observada',coverage],['Variação do NDVI',difference===null?'—':(difference>0?'+':'')+number(difference)]]) {
    const metric=document.createElement('span');metric.className='ndvi-metric';
    const title=document.createElement('small'),amount=document.createElement('strong');title.textContent=label;amount.textContent=value;
    metric.append(title,amount);metrics.append(metric);
  }
  detail.append(metrics);
  if(difference!==null) {
    const days=Math.round((Date.parse(point.date)-Date.parse(previous.date))/86400000);
    add(`${difference>0?'Aumento':difference<0?'Redução':'Sem alteração na precisão exibida'}: NDVI de ${number(previous.ndvi_mean)} em ${date(previous.date)} para ${number(point.ndvi_mean)} em ${date(point.date)} (${days} dias).`,'ndvi-reading-comparison');
  } else {
    add(!currentOk?'Comparação indisponível: exige cobertura de pelo menos 50% e 50 pixels válidos em cada leitura.': 'Ainda não há uma leitura anterior com cobertura suficiente para comparar.','ndvi-reading-comparison');
  }
  const observed=points.slice(0,selected+1).filter(sufficient);
  if(observed.length) {
    const values=observed.map(p=>p.ndvi_mean);
    add(`Até esta data: ${observed.length} leitura(s) com cobertura suficiente · NDVI mínimo ${number(Math.min(...values))} e máximo ${number(Math.max(...values))}.`,'ndvi-reading-range');
  }
  add('As médias usam as partes observadas em cada data; a cobertura pode variar. A mudança do NDVI não confirma plantio, colheita ou produtividade.','ndvi-reading-note');
  const signal=ndviEmergenceSignal(point,history,aggregationDays);
  const signalCard=document.createElement('span');signalCard.className='ndvi-emergence';signalCard.dataset.status=signal.status;
  const title=document.createElement('strong');title.textContent=signal.status==='possible_emergence'?'Sinal — possível plantio ou rebrota':signal.status==='insufficient'?'Últimas quatro semanas: dados insuficientes':'Últimas quatro semanas: sem sinal consistente de possível plantio ou rebrota';
  const evidence=document.createElement('span');evidence.textContent=signal.status==='insufficient'?signal.reason:`${signal.observations} leituras válidas de ${date(signal.first.date)} a ${date(signal.last.date)}: NDVI de ${number(signal.first.ndvi_mean)} para ${number(signal.last.ndvi_mean)}; variação ${signal.delta>0?'+':''}${number(signal.delta)}, ritmo ${number(signal.slope)} por dia.`;
  const note=document.createElement('span');note.textContent='Sinal experimental de aumento da vegetação, compatível com possível plantio ou rebrota; plantas espontâneas também podem produzir esse padrão. Não distingue essas causas, não identifica soja, não confirma semeadura e não verifica o calendário local de plantio. Confira no campo.';
  const method=document.createElement('details'),summary=document.createElement('summary'),rule=document.createElement('span');summary.textContent='Critério do sinal';rule.textContent='Janela de 28 dias até o fim da leitura selecionada; pelo menos 4 leituras em 14 dias, cobertura ≥ 50% e 50 pixels por leitura, lacunas ≤ 10 dias e variação de cobertura ≤ 20 pontos percentuais. Duas primeiras leituras com NDVI ≤ 0,25, ganho ≥ 0,15, tendência ≥ 0,005/dia, dois aumentos ≥ 0,03 e nenhuma queda maior que 0,03. Limiares experimentais, sem validação agronômica. Ausência do sinal não exclui plantio.';method.append(summary,rule);
  signalCard.append(title,evidence,note,method);detail.append(signalCard);
}
function renderNdvi(input, options={}) {
  const prefix=options.prefix || 'ndvi';
  const svg=document.getElementById(prefix+'-chart');
  const detail=document.getElementById(prefix+'-point-detail');
  const technical=document.getElementById(prefix+'-technical-detail');
  const zoomIn=document.getElementById(prefix+'-zoom-in');
  const zoomOut=document.getElementById(prefix+'-zoom-out');
  const reset=document.getElementById(prefix+'-zoom-reset');
  detail.classList.toggle('ndvi-reading',!options.municipal && !options.activity);
  const points=input.filter(p=>Number.isFinite(options.municipal?p.total_soy_ha:p.ndvi_mean) && Number.isFinite(Date.parse(p.date)))
    .slice().sort((a,b)=>a.date.localeCompare(b.date));
  svg.setAttribute('viewBox','0 0 640 260');
  const left=options.municipal?82:options.activity?174:48,right=614,top=28,bottom=216;
  const activityLabels=Object.fromEntries(Object.entries(SOY_ACTIVITY_CLASSES).map(([key,value])=>[key,value.label]));
  const activityY={possible_inactive:60,not_matched:126,unknown:192};
  const activityColor=Object.fromEntries(Object.entries(SOY_ACTIVITY_CLASSES).map(([key,value])=>[key,value.color]));
  let start=0,end=points.length-1,selected=options.activity?-1:points.length-1,drag=null;
  if(!options.activity && !options.municipal && points.length) {
    const cutoff=Date.parse(points[end].date)-90*86400000;
    start=Math.max(0,points.findIndex(p=>Date.parse(p.date)>=cutoff));
  }
  let legend=document.getElementById(prefix+'-series-legend');
  if(!legend) {legend=document.createElement('div');legend.id=prefix+'-series-legend';legend.className='ndvi-series-legend';svg.before(legend);}
  legend.hidden=Boolean(options.activity || options.municipal);
  legend.replaceChildren();
  if(!legend.hidden)for(const [kind,label] of [['observed','NDVI observado'],['reference','Média de referência'],['range','Faixa histórica']]) {
    const item=document.createElement('span'),swatch=document.createElement('i');swatch.className=kind;swatch.setAttribute('aria-hidden','true');item.append(swatch,document.createTextNode(label));legend.append(item);
  }
  if(options.municipal && points.length) {
    const previous=svg.chartSelection;
    selected=previous ? points.findIndex(p=>p.date===previous.selectedDate) : end;
    if(selected<0)selected=end;
    if(previous && !previous.fullRange) {
      const from=points.findIndex(p=>p.date===previous.fromDate);
      const to=points.findIndex(p=>p.date===previous.toDate);
      if(from>=0 && to>=from) {start=from;end=to;}
    }
  }
  const node=(tag,attrs,text)=>{
    const element=document.createElementNS('http://www.w3.org/2000/svg',tag);
    Object.entries(attrs).forEach(([key,value])=>element.setAttribute(key,value));
    if(text!==undefined) element.textContent=text;
    svg.append(element);return element;
  };
  const formatDate=value=>new Intl.DateTimeFormat('pt-BR',{timeZone:'UTC'}).format(new Date(value));
  // Reference uses the complete loaded series, independently of zoom or selection.
  const historicalPoints=points.filter(p=>p.ndvi_mean>=-1 && p.ndvi_mean<=1 && Number.isFinite(p.valid_fraction) && p.valid_fraction>=.5 && p.valid_fraction<=1 && Number.isFinite(p.valid_pixels) && p.valid_pixels>=50);
  const historicalMean=historicalPoints.length>=2 ? historicalPoints.reduce((sum,p)=>sum+p.ndvi_mean,0)/historicalPoints.length : null;
  const historicalLabel=historicalMean===null ? 'Média do período indisponível: são necessárias ao menos duas leituras com cobertura de 50% e 50 pixels válidos.' : `Média do período carregado: ${historicalMean.toLocaleString('pt-BR',{minimumFractionDigits:3,maximumFractionDigits:3})} · ${historicalPoints.length} leituras de ${formatDate(historicalPoints[0].date)} a ${formatDate(historicalPoints.at(-1).date)}. Média simples das leituras válidas carregadas; não é uma média sazonal de vários anos.`;
  const seasonal=points.map(p=>ndviSeasonalReference(p,options.historyPoints || points));
  const time=i=>Date.parse(points[i].date);
  // Municipal snapshots are discrete assessments, not financial candles.
  // Equal-width date slots keep even adjacent assessment dates separate.
  const x=i=>options.municipal ? left+(i-start+.5)*(right-left)/(end-start+1) : time(start)===time(end) ? (left+right)/2 : left+(time(i)-time(start))/(time(end)-time(start))*(right-left);
  const low=Math.min(-.2,...points.map(p=>p.ndvi_mean));
  const y=value=>bottom-(Math.max(low,Math.min(1,value))-low)/(1-low)*(bottom-top);
  function paint() {
    svg.replaceChildren();
    zoomIn.disabled=points.length<3 || end-start<2;
    zoomOut.disabled=reset.disabled=!points.length || (start===0 && end===points.length-1);
    if(!points.length) {
      svg.chartSelection=null;
      node('text',{x:320,y:126,'text-anchor':'middle',fill:'#718078','font-size':14},'Sem observações válidas no período');
      detail.textContent='O satélite não conseguiu observar a vegetação neste período. Tente outra data.';
      technical.textContent='Sem dados disponíveis.';return;
    }
    if(options.municipal) svg.chartSelection={selectedDate:points[selected]?.date,fromDate:points[start].date,toDate:points[end].date,fullRange:start===0 && end===points.length-1};
    if(options.municipal) {
      const maximum=Math.max(1,...points.map(p=>p.total_soy_ha));
      const height=value=>value/maximum*(bottom-top);
      node('text',{x:left-12,y:14,'text-anchor':'end',fill:'#7b8892','font-size':11},'Hectares');
      [0,.25,.5,.75,1].forEach(fraction=>{
        node('line',{x1:left,x2:right,y1:bottom-fraction*(bottom-top),y2:bottom-fraction*(bottom-top),stroke:'#e8edf0','stroke-dasharray':fraction?'3 5':'none'});
        node('text',{x:left-12,y:bottom-fraction*(bottom-top)+4,'text-anchor':'end',fill:'#7b8892','font-size':12},(maximum*fraction).toLocaleString('pt-BR',{maximumFractionDigits:0}));
      });
      const slot=(right-left)/(end-start+1),width=Math.min(30,slot*.64);
      for(let i=start;i<=end;i++) {
        const p=points[i];let base=bottom;
        if(i===selected) node('rect',{x:x(i)-slot*.45,y:top-6,width:slot*.9,height:bottom-top+12,rx:5,fill:'#edf3f5','pointer-events':'none'});
        for(const [value,color] of [[p.possible_inactive_ha,activityColor.possible_inactive],[p.not_matched_ha,activityColor.not_matched],[p.unknown_ha+p.pending_ha,activityColor.unknown]]) {
          const h=height(value);base-=h;
          node('rect',{x:x(i)-width/2,y:base,width,height:h,fill:color,'data-chart-bar':i});
        }
      }
    } else if(options.activity) {
      Object.keys(activityLabels).forEach(status=>{
        node('line',{x1:left,x2:right,y1:activityY[status],y2:activityY[status],stroke:'#e4ebe6'});
        node('text',{x:4,y:activityY[status]+4,fill:'#50615e','font-size':10},activityLabels[status]);
      });
      for(let i=start;i<=end;i++) {
        const status=points[i].activity?.status || 'unknown';
        node('circle',{cx:x(i),cy:activityY[status],r:i===selected?7:5,fill:activityColor[status],stroke:i===selected?'#40534d':'none','stroke-width':2});
      }
    } else {
    [0,.25,.5,.75,1].forEach(value=>{
      node('line',{x1:left,x2:right,y1:y(value),y2:y(value),stroke:'#e4ebe6'});
      node('text',{x:8,y:y(value)+4,fill:'#718078','font-size':11},value.toFixed(2));
    });
    if(historicalMean!==null && !seasonal.some(Boolean)) {
      const reference=node('line',{x1:left,x2:right,y1:y(historicalMean),y2:y(historicalMean),stroke:'#a96820','stroke-width':2,'stroke-dasharray':'8 5','data-historical-mean':historicalMean,'pointer-events':'none'});
      const title=document.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=historicalLabel;reference.append(title);
      node('text',{x:right,y:16,'text-anchor':'end',fill:'#925a1b','font-size':12},`Média do período: ${historicalMean.toLocaleString('pt-BR',{minimumFractionDigits:3,maximumFractionDigits:3})}`);
    }
    let meanPath='',bandTop=[],bandBottom=[];
    const flushBand=()=>{if(bandTop.length)node('path',{d:`M ${bandTop.join(' L ')} L ${bandBottom.reverse().join(' L ')} Z`,fill:'#bd8a3c','fill-opacity':.14,'data-seasonal-band':'','pointer-events':'none'});bandTop=[];bandBottom=[];};
    let connected=false;
    for(let i=start;i<=end;i++) {
      const ref=seasonal[i];
      if(!ref){connected=false;flushBand();continue;}
      meanPath+=`${connected?' L ':' M '}${x(i)} ${y(ref.mean)}`;connected=true;
      bandTop.push(`${x(i)} ${y(ref.upper)}`);bandBottom.push(`${x(i)} ${y(ref.lower)}`);
      if(i===selected)node('circle',{cx:x(i),cy:y(ref.mean),r:3,fill:'#945c16','data-seasonal-mean':ref.mean});
    }
    flushBand();
    if(meanPath) {
      node('path',{d:meanPath,fill:'none',stroke:'#945c16','stroke-width':2,'stroke-dasharray':'5 4','data-seasonal-curve':''});
      node('text',{x:right,y:16,'text-anchor':'end',fill:'#925a1b','font-size':12},'Média sazonal e faixa habitual · anos anteriores');
    }
    // Break the observed line across cloudy readings and long observation gaps.
    let observedPath='',previousObserved=null;
    for(let i=start;i<=end;i++) {
      const p=points[i],usable=Number.isFinite(p.valid_fraction) && p.valid_fraction>=.5 && p.valid_fraction<=1 && Number.isFinite(p.valid_pixels) && p.valid_pixels>=50 && p.ndvi_mean>=-1 && p.ndvi_mean<=1;
      if(!usable){previousObserved=null;continue;}
      const join=previousObserved!==null && time(i)-time(previousObserved)<=15*86400000;
      observedPath+=`${join?' L ':' M '}${x(i)} ${y(p.ndvi_mean)}`;previousObserved=i;
    }
    node('path',{d:observedPath,fill:'none',stroke:'#fff','stroke-width':7,'stroke-linejoin':'round','pointer-events':'none'});
    node('path',{d:observedPath,fill:'none',stroke:'#19734a','stroke-width':3.5,'stroke-linejoin':'round','data-observed-curve':''});
    for(let i=start;i<=end;i++) if(i===selected || end-start<20) node('circle',{cx:x(i),cy:y(points[i].ndvi_mean),r:i===selected?5:3,fill:i===selected?'#19734a':points[i].valid_fraction<.5?'#9aa49d':'#19734a',stroke:'#fff','stroke-width':2});
    }
    if(selected>=0 && selected<points.length) {
      if(!options.municipal && selected>=start && selected<=end) node('line',{x1:x(selected),x2:x(selected),y1:top,y2:bottom,stroke:'#95a5ad','stroke-dasharray':'3 4','pointer-events':'none'});
      const p=points[selected];
      if(options.municipal) {
        const hectares=value=>value.toLocaleString('pt-BR',{maximumFractionDigits:1})+' ha';
        detail.replaceChildren();
        const date=document.createElement('span');date.className='chart-detail-date';date.textContent=`Avaliação da atividade vegetativa · ${formatDate(p.date)}`;detail.append(date);
        const cards=document.createElement('span');cards.className='chart-metrics';
        for(const [label,value,color] of [[activityLabels.possible_inactive,p.possible_inactive_ha,activityColor.possible_inactive],[activityLabels.not_matched,p.not_matched_ha,activityColor.not_matched],[activityLabels.unknown,p.unknown_ha+p.pending_ha,activityColor.unknown]]) {
          const card=document.createElement('span');card.className='chart-metric';card.style.setProperty('--metric-color',color);
          const title=document.createElement('span');title.textContent=label;
          const amount=document.createElement('strong');amount.textContent=hectares(value);
          card.append(title,amount);cards.append(card);
        }
        detail.append(cards);
        const note=document.createElement('span');note.className='chart-detail-note';note.textContent=`Avaliação inconclusiva: ${hectares(p.unknown_ha)} com observações insuficientes e ${hectares(p.pending_ha)} não avaliados. Área de soja mapeada em 2025: ${hectares(p.total_soy_ha)}. Não determina área plantada na safra atual ou condição de pousio.`;detail.append(note);
        technical.textContent='Classificação da atividade vegetativa em áreas de soja mapeadas pelo MapBiomas em 2025, delimitadas pelo município do IBGE. Baixo vigor persistente: NDVI médio ≤ 0,25 nas três observações válidas mais recentes, com intervalo mínimo de 10 dias entre a primeira e a última e última observação há no máximo 15 dias. Cada observação exige pelo menos 50 pixels válidos e cobertura de 50% da área. Vegetação mais expressiva no período: pelo menos uma dessas três observações apresenta NDVI acima de 0,25. Os polígonos são unidades de análise, não limites cadastrais de talhões; áreas menores que 5 ha permanecem não avaliadas. Valores médios podem reunir diferentes condições de cobertura vegetal. O limiar é experimental e não confirma colheita, preparo do solo, pousio ou implantação da cultura. Não há extrapolação para áreas não observadas.';
      } else {
      const coverage=Number.isFinite(p.valid_fraction)?Math.max(0,Math.min(1,p.valid_fraction)):null;
      const observed=coverage===null ? 'A fonte não informou quanto da área foi observado.' : `O satélite conseguiu avaliar ${(coverage*100).toLocaleString('pt-BR',{maximumFractionDigits:1})}% da área${coverage<1 ? '; o restante ficou sem leitura aproveitável' : ''}.`;
      const lastDay=new Date(p.date);lastDay.setUTCDate(lastDay.getUTCDate()+(options.aggregationDays || 5)-1);
      if(!options.activity) {
        renderNdviReading(detail,points,selected,`${formatDate(p.date)} a ${formatDate(lastDay.toISOString())}`,[...(options.historyPoints || []),...points],options.aggregationDays || 5);
        const reference=document.createElement('span');reference.className='ndvi-reading-range ndvi-historical-reference';reference.textContent=historicalLabel;detail.append(reference);
        const seasonalNote=document.createElement('span');seasonalNote.className='ndvi-seasonal-reference';
        const ref=seasonal[selected],fmt=v=>v.toLocaleString('pt-BR',{minimumFractionDigits:3,maximumFractionDigits:3});
        const addSeasonal=(tag,text,className)=>{const element=document.createElement(tag);element.textContent=text;if(className)element.className=className;seasonalNote.append(element);return element;};
        addSeasonal('small','Comparação sazonal · mesmo mês em anos anteriores');
        if(ref && ref.currentUsable) {
          const rounded=v=>Number(v.toFixed(3)),value=rounded(p.ndvi_mean),mean=rounded(ref.mean),lower=rounded(ref.lower),upper=rounded(ref.upper);
          const range=value<lower?'below':value>upper?'above':'within';
          seasonalNote.dataset.range=range;
          addSeasonal('strong',range==='within'?'Dentro da faixa habitual':range==='below'?'Fora da faixa habitual — abaixo':'Fora da faixa habitual — acima','ndvi-seasonal-verdict');
          const delta=rounded(value-mean);
          addSeasonal('span',delta===0?'Na média sazonal (na precisão exibida).':`${delta>0?'Acima':'Abaixo'} da média sazonal em ${fmt(Math.abs(delta))} de NDVI.`,'ndvi-seasonal-mean-status');
          addSeasonal('span',`NDVI observado: ${fmt(value)} · Média sazonal: ${fmt(mean)}`);
          addSeasonal('span',`Faixa habitual: ${fmt(lower)} a ${fmt(upper)}`);
          if(range==='within' && delta!==0)addSeasonal('span','Está dentro da variação habitual, mesmo estando '+(delta>0?'acima':'abaixo')+' da média.');
        } else {
          seasonalNote.dataset.range='unavailable';
          addSeasonal('strong','Comparação sazonal indisponível','ndvi-seasonal-verdict');
          addSeasonal('span',ref?'A leitura selecionada não tem qualidade suficiente para classificar dentro ou fora da faixa habitual.':'Faltam pelo menos três anos anteriores com duas leituras válidas no mesmo mês, para este recorte.');
          if(ref)addSeasonal('span',`Referência disponível: média ${fmt(ref.mean)} · faixa ${fmt(ref.lower)} a ${fmt(ref.upper)}.`);
        }
        if(ref) {
          const method=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('span');summary.textContent=`Base: ${ref.years.length} anos · como foi calculado`;
          text.textContent=`Anos: ${ref.years.join(', ')}. Cada ano tem o mesmo peso, com pelo menos duas leituras válidas no mês. Faixa descritiva: média ± 1 desvio padrão entre anos; limites incluídos. Comparação na precisão exibida de três casas decimais. Não indica produtividade.`;method.append(summary,text);seasonalNote.append(method);
        }
        detail.insertBefore(seasonalNote,detail.querySelector('.ndvi-metrics'));
      }
      technical.textContent=`Índice de vegetação (NDVI): ${p.ndvi_mean.toLocaleString('pt-BR',{minimumFractionDigits:3,maximumFractionDigits:3})}${Number.isFinite(p.valid_pixels)?` · ${p.valid_pixels.toLocaleString('pt-BR')} pixels aproveitados`:''}. O NDVI é calculado somente na parte da área com dados válidos. A indicação de pouca vegetação usa o limite experimental de 0,25 do piloto, sem confirmação agronômica.`;
      if(options.activity) {
        const status=p.activity?.status || 'unknown';
        const interpretation={possible_inactive:'Baixo vigor vegetativo nas três observações válidas mais recentes. Condição compatível com pós-colheita, preparo do solo ou pousio, sem identificação conclusiva do manejo.',not_matched:'Pelo menos uma das três observações válidas recentes apresenta vigor acima do limiar de baixa vegetação. Não determina a cultura presente nem sua fase fenológica.',unknown:'Série de observações insuficiente para classificar a atividade vegetativa no período.'};
        detail.replaceChildren();
        for(const text of [`Avaliação da atividade vegetativa até ${formatDate(p.activity_as_of || p.date)}`,activityLabels[status],interpretation[status],observed]) {
          const line=document.createElement('span');line.textContent=text;detail.append(line);
        }
        technical.textContent+=` Regra temporal: ${p.activity?.reason || 'Sem dados suficientes.'} Cada data usa somente as imagens disponíveis até ela, sem observações futuras.`;
      }
      }
    } else {
      detail.textContent=options.municipal || options.activity ? 'Selecione uma data para consultar a atividade vegetativa. Bege: pouca vegetação persistente. Verde: vegetação observada em pelo menos um dos três intervalos recentes. Cinza: sem leitura suficiente. As cores não confirmam cultura atual nem área vazia.' : 'Passe o mouse ou toque no gráfico para ver o que o satélite observou na área. Pontos cinza indicam menos da metade da área avaliada.';
      technical.textContent='Selecione uma data para consultar o índice e os dados da imagem.';
    }
    const ticks=[...new Set([start,Math.round(start+(end-start)/3),Math.round(start+2*(end-start)/3),end])];
    const multipleYears=points[start].date.slice(0,4)!==points[end].date.slice(0,4);
    let previousLabel=-Infinity;
    const lastLabel=options.municipal?x(end):right,spacing=multipleYears?100:60;
    ticks.forEach((i,index)=>{
      const position=options.municipal?x(i):index===0?left:index===ticks.length-1?right:x(i);
      if(index>0 && index<ticks.length-1 && (position-previousLabel<spacing || lastLabel-position<spacing))return;
      node('text',{x:position,y:244,'text-anchor':options.municipal?'middle':index===0?'start':index===ticks.length-1?'end':'middle',fill:'#7b8892','font-size':12},multipleYears?formatDate(points[i].date):formatDate(points[i].date).slice(0,5));
      previousLabel=position;
    });
    if(options.municipal && selected>=0) document.dispatchEvent(new CustomEvent('alytha-soy-date-selected',{detail:{date:points[selected].date}}));
  }
  function position(event) {
    const matrix=svg.getScreenCTM();
    return matrix ? new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse()).x : left;
  }
  function nearest(px) {
    let best=start;
    for(let i=start+1;i<=end;i++) if(Math.abs(x(i)-px)<Math.abs(x(best)-px)) best=i;
    if(selected!==best) {selected=best;paint();}
  }
  function zoom(factor) {
    if(points.length<2)return;
    const span=Math.max(1,Math.min(points.length-1,Math.round((end-start)*factor)));
    const center=selected>=start && selected<=end ? selected : (start+end)/2;
    start=Math.max(0,Math.min(points.length-1-span,Math.round(center-span/2)));
    end=start+span;paint();
  }
  zoomIn.onclick=()=>zoom(.6);
  zoomOut.onclick=()=>zoom(1/.6);
  reset.onclick=()=>{start=0;end=points.length-1;paint();};
  svg.onpointerdown=event=>{
    if(!points.length)return;
    svg.focus({preventScroll:true});
    nearest(position(event));
    drag={x:position(event),start,end};
    svg.setPointerCapture(event.pointerId);
  };
  svg.onpointermove=event=>{
    if(!points.length)return;
    if(drag) {
      const span=drag.end-drag.start;
      const shift=Math.round((drag.x-position(event))*span/(right-left));
      start=Math.max(0,Math.min(points.length-1-span,drag.start+shift));end=start+span;paint();
    } else nearest(position(event));
  };
  svg.onpointerup=svg.onpointercancel=()=>{drag=null;};
  svg.onkeydown=event=>{
    if(!points.length)return;
    if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
      event.preventDefault();
      selected=event.key==='Home'?0:event.key==='End'?points.length-1:Math.max(0,Math.min(points.length-1,(selected<0?start:selected)+(event.key==='ArrowLeft'?-1:1)));
      const span=end-start;
      if(selected<start) {start=selected;end=start+span;}
      if(selected>end) {end=selected;start=end-span;}
      paint();
    } else if(event.key==='+' || event.key==='=') {event.preventDefault();zoom(.6);}
    else if(event.key==='-') {event.preventDefault();zoom(1/.6);}
  };
  paint();
}
