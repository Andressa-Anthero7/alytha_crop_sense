/* One import path for the file picker and files dropped on the workspace. */
document.addEventListener('DOMContentLoaded',()=>{
  const input=document.getElementById('field-file');
  const overlay=document.getElementById('geojson-drop-overlay');
  let dragDepth=0,revision=0;
  function clearDrag() {
    dragDepth=0;overlay.hidden=true;document.body.classList.remove('geojson-dragging');
  }
  function showDrag() {
    overlay.hidden=false;document.body.classList.add('geojson-dragging');
  }
  const hasFiles=event=>Array.from(event.dataTransfer?.types || []).includes('Files');
  function validate(geojson) {
    if(!geojson || typeof geojson!=='object' || Array.isArray(geojson))throw Error('O arquivo não contém um GeoJSON válido.');
    const features=geojson.type==='FeatureCollection'?geojson.features:[geojson.type==='Feature'?geojson:{geometry:geojson}];
    if(!Array.isArray(features) || features.length!==1 || !['Polygon','MultiPolygon'].includes(features[0]?.geometry?.type))throw Error('Envie um polígono GeoJSON único (Polygon ou MultiPolygon).');
    if(geojson.type==='FeatureCollection' && features[0].type!=='Feature')throw Error('A coleção GeoJSON precisa conter uma Feature com o polígono da área.');
    const geometry=features[0].geometry,polygons=geometry.type==='Polygon'?[geometry.coordinates]:geometry.coordinates;
    if(!Array.isArray(polygons) || !polygons.length)throw Error('O GeoJSON não contém coordenadas de uma área.');
    for(const polygon of polygons) {
      if(!Array.isArray(polygon) || !polygon.length)throw Error('O GeoJSON contém um polígono sem contorno.');
      for(const ring of polygon) {
        if(!Array.isArray(ring) || ring.length<4)throw Error('Cada contorno precisa ter pelo menos três vértices e repetir o primeiro ponto no final.');
        for(const point of ring) {
          if(!Array.isArray(point) || point.length<2 || !Number.isFinite(point[0]) || !Number.isFinite(point[1]) || Math.abs(point[0])>180 || Math.abs(point[1])>85.05112878)throw Error('Use coordenadas válidas em longitude e latitude (WGS84), dentro dos limites do mapa.');
        }
        const first=ring[0],last=ring.at(-1);
        if(first[0]!==last[0] || first[1]!==last[1])throw Error('O contorno GeoJSON precisa estar fechado: repita o primeiro ponto no final.');
        if(new Set(ring.map(point=>point[0]+','+point[1])).size<3)throw Error('O contorno precisa ter pelo menos três vértices diferentes.');
      }
    }
  }
  async function importFiles(files) {
    const current=++revision;
    const work=window.mapLoading?.begin('geojson','Carregando área GeoJSON');
    try {
      if(files.length!==1)throw Error('Solte apenas um arquivo GeoJSON por vez.');
      const file=files[0];
      if(!mapReady)throw Error('Aguarde o carregamento do mapa e solte o arquivo novamente.');
      if(!/\.(geojson|json)$/i.test(file.name) && !['application/geo+json','application/json'].includes(file.type))throw Error('Selecione um arquivo .geojson ou .json com o contorno da área.');
      if(file.size>2_000_000)throw Error('O GeoJSON precisa ter no máximo 2 MB.');
      let geojson;
      try {geojson=JSON.parse((await file.text()).replace(/^\uFEFF/,''));}
      catch {throw Error('Não foi possível ler o GeoJSON. Confira se o arquivo contém JSON válido.');}
      if(current!==revision)return;
      validate(geojson);
      selectAnalysisArea(geojson,file.name);
      input.value='';
      setStatus('GeoJSON carregado. Escolha o período e clique em Buscar imagens ou Consultar vigor.');
      work?.finish(`Área carregada: ${file.name}`);
    } catch(error) {
      if(current!==revision)return;
      setStatus(error.message,true);work?.fail(error.message);
    } finally {work?.cancel();}
  }
  input.addEventListener('change',()=>{
    const files=Array.from(input.files || []);input.value='';
    if(files.length)importFiles(files);
  });
  window.addEventListener('dragenter',event=>{
    if(!hasFiles(event))return;
    event.preventDefault();event.stopPropagation();dragDepth++;showDrag();
  },true);
  window.addEventListener('dragover',event=>{
    if(!hasFiles(event))return;
    event.preventDefault();event.stopPropagation();event.dataTransfer.dropEffect='copy';showDrag();
  },true);
  document.addEventListener('dragleave',()=>{
    dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)clearDrag();
  },true);
  window.addEventListener('drop',event=>{
    clearDrag();if(!hasFiles(event) && !event.dataTransfer?.files?.length)return;
    event.preventDefault();event.stopPropagation();
    importFiles(Array.from(event.dataTransfer.files));
  },true);
  document.addEventListener('dragend',clearDrag,true);
  document.addEventListener('keydown',event=>{if(event.key==='Escape')clearDrag();});
  window.addEventListener('blur',clearDrag);
});
