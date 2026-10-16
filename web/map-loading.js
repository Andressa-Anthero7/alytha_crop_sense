/* Concurrent map work stays visible until the last current request finishes. */
(()=>{
  let sequence=0,timer;
  const active=new Map();
  const panel=()=>document.getElementById('map-loading');
  function render(title,message,state='loading'){
    clearTimeout(timer);const box=panel();if(!box)return;
    box.hidden=false;box.dataset.state=state;
    box.setAttribute('aria-busy',String(state==='loading'));
    document.getElementById('map-loading-title').textContent=title;
    document.getElementById('map-loading-message').textContent=message;
    document.getElementById('map-loading-close').hidden=state==='loading';
  }
  function current(){const job=[...active.values()].at(-1);if(job)render(job.title,job.message);}
  window.mapLoading={
    cancel(key){active.delete(key);if(active.size)current();else if(panel())panel().hidden=true;},
    begin(key,title,message='Aguarde enquanto os dados são preparados.'){
      const id=++sequence;active.set(key,{id,title,message});current();
      const valid=()=>active.get(key)?.id===id;
      return {
        update(message){if(valid()){active.get(key).message=message;current();}},
        finish(message){if(!valid())return;active.delete(key);if(active.size)current();else{render('Mapa atualizado',message || 'Consulta concluída.','ready');timer=setTimeout(()=>{panel().hidden=true;},3500);}},
        fail(message){if(!valid())return;active.delete(key);if(active.size)current();else render('Não foi possível carregar',message,'error');},
        cancel(){if(!valid())return;active.delete(key);if(active.size)current();else panel().hidden=true;}
      };
    }
  };
  document.addEventListener('DOMContentLoaded',()=>document.getElementById('map-loading-close').addEventListener('click',()=>{panel().hidden=true;}));
})();
