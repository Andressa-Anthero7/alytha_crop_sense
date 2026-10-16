/* Field observations belong to the geometry of the loaded history. */
function evidenceForArea(records, areaKey) {
  return records.filter(record=>record.area_key===areaKey);
}

document.addEventListener('DOMContentLoaded',()=>{
  let history=null, records=[], revision=0;
  const el=id=>document.getElementById(id);
  const labels={emergencia:'Emergência',desenvolvimento:'Desenvolvimento',colheita:'Colheita recente',solo_exposto:'Solo exposto',preparo:'Preparo do solo',plantio:'Plantio',pousio:'Pousio'};
  async function refresh() {
    const current=++revision, selected=history;
    records=[]; el('export-field-evidence').disabled=true;
    el('field-evidence-list').replaceChildren();
    if(!selected)return;
    el('field-evidence-list').textContent='Carregando registros desta área…';
    try {
      const all=await storageJson('/api/research/events');
      if(current!==revision)return;
      records=evidenceForArea(all,selected.parameters.area_key);
      el('field-evidence-list').replaceChildren();
      if(!records.length)el('field-evidence-list').textContent='Ainda não há registros de campo nesta área.';
      for(const record of records) {
        const row=document.createElement('p');
        row.textContent=`${record.date_from.split('-').reverse().join('/')} a ${record.date_to.split('-').reverse().join('/')} · ${labels[record.stage] || record.stage} · ${record.note}`;
        el('field-evidence-list').append(row);
      }
      el('export-field-evidence').disabled=!records.length;
    } catch(error) {if(current===revision)el('field-evidence-list').textContent=error.message;}
  }
  document.addEventListener('alytha-history-ready',event=>{
    if(history?.parameters.area_key!==event.detail.parameters.area_key) {
      for(const id of ['event-from','event-to','event-note'])el(id).value='';
      el('event-status').textContent='';
    }
    history=event.detail;
    el('field-evidence-panel').dataset.historyId=history.id;
    el('save-field-event').disabled=false;
    el('field-evidence-scope').textContent=`Registros vinculados ao polígono deste histórico · ${history.parameters.start_year}–${history.parameters.end_year}. Confira a área no mapa antes de salvar.`;
    for(const id of ['event-from','event-to']) {
      el(id).min=`${history.parameters.start_year}-01-01`;
      el(id).max=history.parameters.as_of;
    }
    refresh();
  });
  document.addEventListener('alytha-field-event-saved',refresh);
  for(const type of ['alytha-area-selected','alytha-area-cleared','alytha-history-cleared'])document.addEventListener(type,()=>{
    history=null; revision++; records=[];
    delete el('field-evidence-panel').dataset.historyId;
    el('save-field-event').disabled=true;
    el('export-field-evidence').disabled=true;
    el('field-evidence-list').replaceChildren();
    el('field-evidence-scope').textContent='A área mudou. Abra seu histórico antes de registrar uma observação.';
    for(const id of ['event-from','event-to','event-note'])el(id).value='';
    el('event-status').textContent='';
  });
  el('export-field-evidence').addEventListener('click',()=>{
    if(!history || !records.length)return;
    const payload={schema_version:1,exported_at:new Date().toISOString(),dataset_id:history.id,area_key:history.parameters.area_key,geometry:history.parameters.geometry,records,note:'Registros informados de campo; exportação não certifica a veracidade das informações.'};
    const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download=`registros-campo-${history.id.slice(0,12)}.json`;link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
});
