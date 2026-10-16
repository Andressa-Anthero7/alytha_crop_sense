let savedAreaId = null, savedAreas = [], savedAnalyses = [], historyRevision = 0;
let selectedAreaProvenance = {};

function resetSavedArea() {
  selectedAreaProvenance = {};
  savedAreaId = null; savedAnalyses = []; historyRevision++;
  document.getElementById('saved-areas').value = '';
  document.getElementById('saved-status').textContent = 'Área não salva. Salve antes de consultar para guardar o histórico.';
  document.getElementById('saved-history').replaceChildren(new Option('Selecione uma área salva', ''));
  document.getElementById('saved-history').disabled = true;
  document.getElementById('compare-history').replaceChildren(new Option('Escolha uma série anterior', ''));
  document.getElementById('compare-history').disabled = true;
  document.getElementById('comparison-result').textContent = '';
  document.getElementById('download-history').disabled = true;
}

async function storageJson(url, payload) {
  const response = await fetch(url, payload ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } : {});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Não foi possível acessar os dados salvos.');
  return result;
}

async function refreshSavedAreas() {
  savedAreas = await storageJson('/api/areas');
  const select = document.getElementById('saved-areas');
  select.replaceChildren(new Option('Selecione uma área salva', ''));
  savedAreas.forEach(area => select.add(new Option(`${area.name} · ${area.municipality} · ${area.season}`, area.id)));
  select.value = savedAreaId || '';
}

function historyLabel(record) {
  const when = new Date(record.created_at).toLocaleString('pt-BR');
  return `${record.kind === 'ndvi' ? 'NDVI' : 'Cenas'}: ${record.parameters.from} a ${record.parameters.to} · ${when}`;
}

async function refreshSavedHistory() {
  if (!savedAreaId) return;
  const areaId = savedAreaId, revision = ++historyRevision;
  try {
    const records = await storageJson(`/api/areas/${areaId}/history`);
    if (revision !== historyRevision || savedAreaId !== areaId) return;
    savedAnalyses = records;
    const select = document.getElementById('saved-history');
    select.replaceChildren(new Option('Selecione uma consulta', ''));
    records.forEach(record => select.add(new Option(historyLabel(record), record.id)));
    select.disabled = !records.length;
    const comparison = document.getElementById('compare-history');
    comparison.replaceChildren(new Option('Comparar com a série NDVI mais recente', ''));
    const series = records.filter(record => record.kind === 'ndvi');
    series.slice(1).forEach(record => comparison.add(new Option(historyLabel(record), record.id)));
    comparison.disabled = series.length < 2;
    document.getElementById('download-history').disabled = !records.length;
    document.getElementById('saved-status').textContent = `${records.length} consulta(s) salva(s) para esta área. Dados armazenados neste computador.`;
  } catch (error) { document.getElementById('saved-status').textContent = `Consulta concluída, mas não foi possível atualizar o histórico: ${error.message}`; }
}

document.addEventListener('DOMContentLoaded', () => {
  const status = document.getElementById('saved-status');
  refreshSavedAreas().catch(error => status.textContent = error.message);
  document.getElementById('refresh-areas').addEventListener('click', () => refreshSavedAreas().catch(error => status.textContent = error.message));
  document.getElementById('save-area').addEventListener('click', async event => {
    if (!fieldLoaded || drawingArea) { status.textContent = 'Conclua o desenho ou carregue uma área antes de salvar.'; return; }
    if (savedAreaId) { status.textContent = 'Esta área já está salva. As novas consultas serão adicionadas ao histórico.'; return; }
    const button = event.currentTarget; button.disabled = true;
    try {
      const area = await storageJson('/api/areas', {
        name: document.getElementById('area-name').value,
        municipality: document.getElementById('area-city').value,
        crop: document.getElementById('area-crop').value,
        season: document.getElementById('area-season').value,
        geojson: await fieldGeojson(), provenance: selectedAreaProvenance
      });
      savedAreaId = area.id;
      await refreshSavedAreas(); await refreshSavedHistory();
      document.getElementById('area-details').textContent = `${area.name}: área salva. Novas consultas ficam no histórico.`;
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  document.getElementById('municipality-select').addEventListener('change', event => {
    if (event.target.value && !savedAreaId) document.getElementById('area-city').value = `${event.target.selectedOptions[0].textContent} / ${document.getElementById('state-select').selectedOptions[0].textContent}`;
  });
  document.getElementById('saved-areas').addEventListener('change', async event => {
    const area = savedAreas.find(item => item.id === Number(event.target.value));
    if (!area) { clearAnalysisArea(); return; }
    if (!mapReady) { status.textContent = 'Aguarde o mapa carregar.'; return; }
    selectAnalysisArea({ type: 'Feature', properties: {}, geometry: area.geometry }, area.name);
    savedAreaId = area.id;
    selectedAreaProvenance = area.provenance || {};
    for (const [id,key] of [['area-name','name'],['area-city','municipality'],['area-crop','crop'],['area-season','season']]) document.getElementById(id).value = area[key];
    event.target.value = area.id;
    await refreshSavedHistory();
  });
  document.getElementById('saved-history').addEventListener('change', event => {
    const record = savedAnalyses.find(item => item.id === Number(event.target.value));
    if (!record) return;
    setObservationPeriod(record.parameters.from,record.parameters.to);
    if (record.kind === 'ndvi') {
      document.querySelector('#ndvi-panel .analysis-subtitle').textContent = 'Histórico da vegetação nesta área · leituras de até 5 dias. Partes sem boa visibilidade ficam fora do cálculo.';
      renderNdvi(record.result.points || []);
      document.getElementById('ndvi-panel').classList.add('visible');
      setNdviStatus(`Histórico: ${record.source} · consulta em ${new Date(record.created_at).toLocaleString('pt-BR')}.`);
    } else {
      renderItems(record.result.features || []);
      renderSceneFootprints(record.result);
      document.getElementById('cloud').value = record.parameters.max_cloud;
      document.getElementById('cloud-value').textContent = `${record.parameters.max_cloud}%`;
    }
    setStatus('Consulta histórica reaberta; não foi necessário consultar o provedor novamente.');
  });
  document.getElementById('compare-history').addEventListener('change', event => {
    const latest = savedAnalyses.find(record => record.kind === 'ndvi');
    const previous = savedAnalyses.find(record => record.id === Number(event.target.value));
    const output = document.getElementById('comparison-result'); output.textContent = '';
    if (!latest || !previous) return;
    const mean = record => {
      const values = (record.result.points || []).map(point => point.ndvi_mean).filter(Number.isFinite);
      return values.length ? values.reduce((a,b) => a+b,0)/values.length : null;
    };
    const a = mean(latest), b = mean(previous);
    output.textContent = a === null || b === null ? 'Uma das séries não tem observações válidas para comparar.' : `Média dos intervalos: mais recente ${a.toFixed(3)}; selecionada ${b.toFixed(3)}; diferença ${(a-b).toFixed(3)}. Períodos e cobertura de observações podem diferir; isso não estima produtividade.`;
  });
  document.getElementById('download-history').addEventListener('click', () => {
    const area = savedAreas.find(item => item.id === savedAreaId);
    const url = URL.createObjectURL(new Blob([JSON.stringify({ area, analyses: savedAnalyses }, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `area-${savedAreaId}-historico.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
});
