/* Calendar-month ranges share the same start/end fields as custom history queries. */
document.addEventListener('DOMContentLoaded',()=>{
  const first=document.getElementById('date-from'),last=document.getElementById('date-to');
  const preset=document.getElementById('date-range-preset');
  const now=new Date();
  const today=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
  for(const input of [first,last]) {input.min='2018-01-01';input.max=today;}
  function applyPreset() {
    if(preset.value==='custom')return;
    const end=new Date((last.value || today)+'T00:00:00Z');
    if(!Number.isFinite(end.getTime()))return;
    const start=new Date(end);start.setUTCDate(1);start.setUTCMonth(start.getUTCMonth()-Number(preset.value));
    const days=new Date(Date.UTC(start.getUTCFullYear(),start.getUTCMonth()+1,0)).getUTCDate();
    start.setUTCDate(Math.min(end.getUTCDate(),days));
    first.value=[first.min,start.toISOString().slice(0,10)].sort().at(-1);
  }
  window.setObservationPeriod=(from,to)=>{
    first.value=from;last.value=to;preset.value='custom';
  };
  last.value=today;applyPreset();
  preset.addEventListener('change',applyPreset);
  first.addEventListener('input',()=>{preset.value='custom';});
  first.addEventListener('change',()=>{preset.value='custom';});
  last.addEventListener('input',applyPreset);
  last.addEventListener('change',applyPreset);
});
