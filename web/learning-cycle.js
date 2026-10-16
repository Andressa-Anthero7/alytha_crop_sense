/* Periodic collection survives page closure; the local server must stay on. */
document.addEventListener('DOMContentLoaded', () => {
  const el = id => document.getElementById(id);
  const host = el('learning-cycle-plans');
  let history = null, revision = 0, lastRender = '';
  const stages = {emergencia:'Emergência', desenvolvimento:'Desenvolvimento', colheita:'Colheita recente', solo_exposto:'Solo exposto', preparo:'Preparo do solo', plantio:'Plantio', pousio:'Pousio'};
  const text = (parent, value) => {
    const p = document.createElement('p'); p.className = 'analysis-subtitle'; p.textContent = value; parent.append(p); return p;
  };
  const button = (parent, label, action) => {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = label; parent.append(b);
    b.addEventListener('click', async () => {
      b.disabled = true;
      try { await action(); lastRender = ''; await refresh(); }
      catch (error) { el('learning-cycle-status').textContent = error.message; }
      finally { b.disabled = false; }
    });
    return b;
  };
  const input = (form, label, type = 'text', value = '') => {
    const wrapper = document.createElement('label'); wrapper.textContent = label;
    const field = document.createElement('input'); field.type = type; field.value = value;
    field.maxLength = 500; wrapper.append(field); form.append(wrapper); return field;
  };
  function fieldForm(parent, run) {
    const details = document.createElement('details'); parent.append(details);
    const summary = document.createElement('summary'); summary.textContent = 'Validar ou corrigir com informações de campo'; details.append(summary);
    const form = document.createElement('form'); details.append(form);
    text(form, 'Selecione o que foi observado. A sugestão do satélite não é confirmação. Informe a referência do parceiro ou da visita.');
    const stage = document.createElement('select'); stage.required = true;
    stage.add(new Option('Escolha a etapa confirmada', ''));
    Object.entries(stages).forEach(([key, label]) => stage.add(new Option(label, key)));
    const label = document.createElement('label'); label.textContent = 'Etapa observada'; label.append(stage); form.append(label);
    const from = input(form, 'Início', 'date', run.as_of), to = input(form, 'Fim', 'date', run.as_of);
    from.required = to.required = true; from.max = to.max = run.as_of;
    const partner = input(form, 'Parceiro ou responsável'), crop = input(form, 'Cultura informada · opcional');
    const note = input(form, 'Referência da informação'); note.required = true; note.minLength = 3;
    const save = document.createElement('button'); save.type = 'submit'; save.textContent = 'Salvar confirmação de campo'; form.append(save);
    const status = text(form, ''); status.setAttribute('role', 'status');
    form.addEventListener('submit', async event => {
      event.preventDefault(); save.disabled = true;
      try {
        await storageJson('/api/learning-cycle/review', {run_id:run.id, stage:stage.value, from:from.value, to:to.value, partner:partner.value, crop:crop.value, note:note.value});
        document.dispatchEvent(new Event('alytha-field-event-saved'));
        lastRender = ''; await refresh();
      } catch (error) { status.textContent = error.message; }
      finally { save.disabled = false; }
    });
  }
  function card(plan) {
    const section = document.createElement('section'); host.append(section);
    const title = document.createElement('strong'); title.textContent = `${plan.name} · município ${plan.municipality_code}`; section.append(title);
    text(section, plan.enabled ? (plan.running ? 'Leitura e análise em andamento…' : `Próxima consulta: ${new Date(plan.next_due).toLocaleString('pt-BR')}.`) : 'Acompanhamento pausado.');
    button(section, plan.enabled ? 'Pausar acompanhamento' : 'Retomar acompanhamento', () => storageJson('/api/learning-cycle/configure', {plan_id:plan.id, enabled:!plan.enabled}));
    if (plan.enabled) button(section, 'Consultar novas leituras agora', () => storageJson('/api/learning-cycle/configure', {plan_id:plan.id, refresh:true}));
    button(section, plan.ai_enabled ? 'Pausar revisões da Alytha' : 'Ativar revisões da Alytha', () => storageJson('/api/learning-cycle/configure', {plan_id:plan.id, ai_enabled:!plan.ai_enabled}));
    const run = plan.runs?.[0];
    if (!run) { text(section, 'Aguardando a primeira rodada.'); return; }
    const statusLabels = {running:'Em andamento', ready:'Leitura disponível', partial:'Análise da base preservada · nova coleta pendente', insufficient_data:'Ainda faltam leituras úteis', error:'Consulta pendente', interrupted:'Rodada interrompida; aguardando retomada'};
    text(section, `${run.as_of.split('-').reverse().join('/')} · ${statusLabels[run.status] || run.status} · ${plan.runs.length} rodadas recentes disponíveis.`);
    if (run.error) text(section, run.error);
    if (run.collection?.issue) text(section, `${run.collection.issue.message} A análise usa somente a base preservada; nova tentativa de coleta em seis horas.`);
    if (run.collection) text(section, `${run.collection.new_intervals} intervalos novos e ${run.collection.usable_recent} leituras úteis na janela recente. Nuvens e falhas de leitura não indicam ausência de vegetação.`);
    if (run.analysis?.baseline) text(section, `${run.analysis.baseline.label}: ${run.analysis.baseline.reason}`);
    if (run.analysis?.vegetation_patterns) text(section, `Padrões atualizados: ${run.analysis.vegetation_patterns.groups.length} grupos de vegetação no histórico desta área.`);
    const ai = run.ai_review;
    if (ai?.status === 'ready') {
      text(section, `Revisão da Alytha (${ai.provider}): ${ai.answer}`);
      (ai.limitations || []).forEach(value => text(section, value));
    } else if (ai) text(section, {disabled:'Revisão da Alytha pausada.', unavailable:`Revisão da Alytha indisponível nesta rodada. ${ai.issue?.message || ''} Os dados foram preservados.`, unchanged:'Sem mudança nas evidências úteis; a revisão anterior foi preservada.'}[ai.status] || 'Aguardando revisão da Alytha.');
    if (run.field_review?.status === 'confirmed') text(section, `Validação de campo registrada: ${stages[run.field_review.confirmed_stage]}.`);
    else if (run.features) fieldForm(section, run);
    if (history?.parameters.area_key === plan.area_key && run.dataset_id) {
      button(section, 'Abrir histórico desta rodada', async () => {
        const selected = history, current = revision;
        const loaded = await storageJson('/api/research/history/' + run.dataset_id);
        if (revision !== current || history !== selected) return;
        document.dispatchEvent(new CustomEvent('alytha-learning-history', {detail:loaded}));
      });
    }
    if (run.supervised_candidate?.status === 'evaluated') text(section, 'Nova versão do modelo de manejo avaliada com registros de campo. A versão candidata foi preservada para revisão; ainda não substituiu o modelo em uso.');
  }
  async function refresh() {
    const current = revision;
    const query=history ? '?area_key='+encodeURIComponent(history.parameters.area_key) : '?limit=10';
    const list = await storageJson('/api/learning-cycle'+query);
    const details = await Promise.all(list.map(plan => storageJson('/api/learning-cycle/' + plan.id)));
    if (current !== revision || (host.contains(document.activeElement) && ['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName))) return;
    const rendered = JSON.stringify([details, history?.parameters.area_key]);
    if (rendered === lastRender) return;
    lastRender = rendered; host.replaceChildren(); details.forEach(card);
    if (!details.length) text(host, 'Nenhuma área inscrita no acompanhamento contínuo.');
    el('enable-learning-cycle').disabled = !history || history.status === 'loading' || list.some(plan => plan.area_key === history.parameters.area_key);
  }
  document.addEventListener('alytha-history-ready', event => {
    history = event.detail; revision++;
    el('enable-learning-cycle').disabled = history.status === 'loading';
    el('learning-cycle-status').textContent = 'O acompanhamento roda com o servidor ligado, mesmo com a página fechada. Rodadas e agenda são preservadas ao reiniciar.';
    refresh().catch(error => el('learning-cycle-status').textContent = error.message);
  });
  for (const name of ['alytha-area-selected', 'alytha-area-cleared', 'alytha-history-cleared']) document.addEventListener(name, () => {
    history = null; revision++; lastRender = ''; el('enable-learning-cycle').disabled = true;
    el('learning-cycle-status').textContent = 'Abra o histórico da área selecionada para iniciar seu acompanhamento.';
  });
  el('enable-learning-cycle').addEventListener('click', async () => {
    if (!history) return;
    el('enable-learning-cycle').disabled = true;
    try {
      await storageJson('/api/learning-cycle', {dataset_id:history.id, name:`Área ${history.parameters.area_key.slice(0, 8)}`, ai_enabled:true});
      el('learning-cycle-status').textContent = 'Área inscrita. A primeira rodada será iniciada automaticamente.';
      lastRender = ''; await refresh();
    } catch (error) { el('learning-cycle-status').textContent = error.message; el('enable-learning-cycle').disabled = !history; }
  });
  el('export-learning-cycle').addEventListener('click', async () => {
    try {
      const result = await storageJson('/api/learning-cycle/export', {});
      el('learning-cycle-status').textContent = `${result.windows} janelas de aprendizado, ${result.field_labeled_windows} com referência de campo. Arquivos salvos em ${result.folder}.`;
    } catch (error) { el('learning-cycle-status').textContent = error.message; }
  });
  refresh().catch(error => el('learning-cycle-status').textContent = error.message);
  setInterval(() => { if (!document.hidden) refresh().catch(() => {}); }, 15000);
});
