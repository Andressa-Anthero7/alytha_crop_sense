"""Persistent five-day monitoring of fixed areas, with auditable AI reviews.

Observations and exploratory patterns can grow without field labels. Only
explicit human field records enter the supervised target. Candidate models
never replace the active management model from this worker.
"""
import argparse
import copy
import csv
import json
import logging
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from . import storage, research

STOP = threading.Event()
WAKE = threading.Event()
THREAD = None
THREAD_LOCK = threading.Lock()
OUTPUT = Path(__file__).resolve().parents[1] / 'data/outputs/learning-cycle'
REVIEW_PROMPT = (
    'Faça uma revisão agronômica do acompanhamento deste recorte. Compare as '
    'evidências temporais e os padrões aprendidos; pondere explicações alternativas '
    'para as mudanças, limitações de qualidade e o que verificar com o produtor '
    'na próxima visita. Diferencie observações de hipóteses. Não confirme cultura '
    'ou manejo, não crie rótulos de treinamento nem solicite ações no mapa.'
)


def clock():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.isoformat()


def collection_failure(exc):
    from .collection_issues import failure
    from urllib.error import HTTPError
    issue = failure('Copernicus', 'releitura periódica', exc)
    if isinstance(exc, HTTPError) and exc.code == 403:
        try:
            payload = json.loads(exc.read(8000))
            message = payload.get('error', {}).get('message', '')
            if isinstance(message, str) and 'insufficient processing units or requests' in message.lower():
                issue.update(reason='processing_quota', message='Cota de processamento Copernicus esgotada (HTTP 403).')
        except (ValueError, TypeError, AttributeError):
            pass
    return issue


def ai_failure(exc):
    import re
    from .collection_issues import failure
    issue = failure('IA', 'revisão', exc)
    # The adapter emits bounded local errors; do not persist arbitrary messages.
    if isinstance(exc, ValueError):
        message = str(exc)
        status = re.search(r'HTTP (\d{3})', message)
        if status:
            issue.update(reason='http_'+status[1], message='Revisão da IA indisponível (HTTP '+status[1]+').')
        elif any(word in message.lower() for word in ('cota', 'saldo')):
            issue.update(reason='quota', message='Cota ou saldo do provedor de IA indisponível.')
    return issue


@contextmanager
def database():
    with storage.connect() as db:
        yield db


def decode(row):
    return {**json.loads(row['config']), 'next_due': row['next_due'],
            'running': bool(row['lease_until'] and row['lease_until'] > stamp(clock()))}


def plans(municipality_code=None,area_key=None,limit=None):
    with database() as db:
        query='SELECT * FROM learning_plans';conditions=[];params=[]
        if municipality_code:conditions.append('json_extract(config,\'$.municipality_code\')=?');params.append(municipality_code)
        if area_key:conditions.append('area_key=?');params.append(area_key)
        if conditions:query+=' WHERE '+' AND '.join(conditions)
        query+=' ORDER BY id'
        if limit is not None:query+=' LIMIT ?';params.append(limit)
        return [decode(row) for row in db.execute(query,params)]


def get(plan_id):
    with database() as db:
        row = db.execute('SELECT * FROM learning_plans WHERE id=?', (plan_id,)).fetchone()
        if not row:
            raise ValueError('Acompanhamento contínuo não encontrado.')
        result = decode(row)
        result['runs'] = [json.loads(r['result']) for r in db.execute(
            'SELECT result FROM learning_runs WHERE plan_id=? ORDER BY created_at DESC, rowid DESC LIMIT 12', (plan_id,))]
    return result


def enroll(data):
    history = research.dataset(data.get('dataset_id'))
    params = history['parameters']
    if history['status'] not in ('ready', 'partial') or not params.get('geometry'):
        raise ValueError('Aguarde um histórico com geometria e leituras disponíveis.')
    name = data.get('name', 'Área acompanhada')
    ai_enabled = data.get('ai_enabled', True)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200 or type(ai_enabled) is not bool:
        raise ValueError('Informe nome e opção de revisão da IA válidos.')
    from .municipalities import key
    code = params.get('municipality_code', '5107925')
    key(code)
    area_key = research.fingerprint(params['geometry'])
    plan_id = research.fingerprint(['continuous-monitoring', area_key])
    config = {'id': plan_id, 'area_key': area_key, 'name': name.strip(),
              'municipality_code': code, 'seed_dataset_id': history['id'],
              'latest_dataset_id': history['id'], 'interval_days': 5,
              'ai_enabled': ai_enabled, 'enabled': True, 'created_at': stamp(clock())}
    with database() as db:
        # Repeated clicks neither reset the cadence nor discard earlier cycles.
        db.execute('INSERT OR IGNORE INTO learning_plans VALUES(?,?,?,?,NULL)',
                   (plan_id, area_key, json.dumps(config), stamp(clock())))
    WAKE.set()
    return get(plan_id)


def configure(data):
    plan_id = data.get('plan_id')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM learning_plans WHERE id=?', (plan_id,)).fetchone()
        if not row:
            raise ValueError('Acompanhamento contínuo não encontrado.')
        config = json.loads(row['config'])
        for key in ('enabled', 'ai_enabled'):
            if key in data:
                if type(data[key]) is not bool:
                    raise ValueError('Opção de acompanhamento inválida.')
                config[key] = data[key]
        next_due = stamp(clock()) if data.get('refresh') is True else row['next_due']
        db.execute('UPDATE learning_plans SET config=?,next_due=? WHERE id=?',
                   (json.dumps(config), next_due, plan_id))
    WAKE.set()
    return get(plan_id)


def claim():
    """SQLite lease prevents two server/CLI workers collecting the same area."""
    now = clock()
    gate=storage.source_snapshot('learning:collection-gate')
    if gate and gate['result'].get('until','')>stamp(now):return None
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT * FROM learning_plans WHERE next_due<=? "
                         "AND (lease_until IS NULL OR lease_until<=?) "
                         "AND json_extract(config,'$.enabled')=1 ORDER BY next_due LIMIT 1",
                         (stamp(now), stamp(now))).fetchone()
        if not row:
            return None
        # An interrupted attempt remains visible and will be retried.
        db.execute("UPDATE learning_runs SET status='interrupted', "
                   "result=json_set(result,'$.status','interrupted') "
                   "WHERE plan_id=? AND status='running'", (row['id'],))
        run_id = uuid.uuid4().hex
        run = {'id': run_id, 'plan_id': row['id'], 'created_at': stamp(now),
               'as_of': now.date().isoformat(), 'status': 'running'}
        db.execute('INSERT INTO learning_runs VALUES(?,?,?,?,?)',
                   (run_id, row['id'], stamp(now), 'running', json.dumps(run)))
        config = json.loads(row['config'])
        config['active_run_id'] = run_id
        db.execute('UPDATE learning_plans SET config=?,lease_until=? WHERE id=?',
                   (json.dumps(config), stamp(now + timedelta(hours=1)), row['id']))
        return config, run


def quality(point):
    try:
        import math
        value = point['ndvi_mean']
        pixels, fraction = point.get('valid_pixels', 0), point.get('valid_fraction', 0)
        return (type(value) in (int, float) and math.isfinite(value) and -1 <= value <= 1
                and type(pixels) in (int, float) and pixels >= 50
                and type(fraction) in (int, float) and .5 <= fraction <= 1)
    except (KeyError, TypeError):
        return False


def merge_points(previous, incoming, cutoff):
    """Closed five-day composites only; bad rereads cannot erase good evidence."""
    merged = {}
    for point in previous + incoming:
        try:
            when = date.fromisoformat(point['date'])
            available = min(when + timedelta(days=4), date(when.year, 12, 31))
            if available > date.fromisoformat(cutoff):
                continue
            item = {**point, 'available': available.isoformat()}
            old = merged.get(point['date'])
            if old is None or (quality(item), item.get('valid_fraction', 0)) >= (quality(old), old.get('valid_fraction', 0)):
                merged[point['date']] = item
        except (KeyError, TypeError, ValueError):
            continue
    return [merged[key] for key in sorted(merged)]


def input_signature(points, cutoff):
    end = date.fromisoformat(cutoff)
    return research.fingerprint([p for p in points if quality(p) and
                                 end - timedelta(days=90) <= date.fromisoformat(p['date']) <= end])


def execute(plan, run):
    from .web_app import request_ndvi_series, read_app_env
    from . import assistant
    history = copy.deepcopy(research.dataset(plan['latest_dataset_id']))
    history.pop('regional_seed',None)
    cutoff = date.fromisoformat(run['as_of'])
    run['phase'] = 'collection'
    # Anchor intervals to Jan 1 of each year, like the historical collector.
    # Query 90 days for warm-up; overlap the last ten days on subsequent runs.
    start = cutoff - timedelta(days=90)
    if plan.get('last_collected_to'):
        start = date.fromisoformat(plan['last_collected_to']) - timedelta(days=10)
    incoming = []
    collection_issue = None
    try:
        for year in range(start.year, cutoff.year + 1):
            anchor = date(year, 1, 1)
            first = max(anchor, start)
            first -= timedelta(days=(first - anchor).days % 5)
            last = min(date(year, 12, 31), cutoff)
            series = request_ndvi_series(history['parameters']['geometry'], first.isoformat(), last.isoformat())
            incoming.extend(series['points'])
    except Exception as exc:
        collection_issue = collection_failure(exc)
        if collection_issue['reason']=='processing_quota':
            storage.source_snapshot('learning:collection-gate',{'until':stamp(clock()+timedelta(hours=6)),
                                    'issue':collection_issue})
    previous = merge_points(history['points'], [], run['as_of'])
    points = merge_points(history['points'], incoming, run['as_of'])
    run.update(collection={'status': 'unavailable' if collection_issue else 'ready',
                           'issue': collection_issue, 'from': start.isoformat(), 'to': run['as_of'],
                           'received': len(incoming), 'new_intervals': len({p['date'] for p in points} - {p['date'] for p in previous}),
                           'usable_recent': len(research.windows(points, run['as_of'])),
                           'last_observation': points[-1]['date'] if points else None})
    run['received_points'] = incoming
    history.update(id=research.fingerprint(['learning-run', run['id']]),
                   points=points, updated_at=stamp(clock()), source='Copernicus Sentinel-2 L2A',
                   aggregation_days=5, resolution_m=10)
    history['parameters'].update(as_of=run['as_of'], end_year=cutoff.year)
    if collection_issue:
        history.update(status='partial', collection_issue=collection_issue,
                       note='Releitura indisponível; análise usa apenas as observações preservadas, sem preencher lacunas.')
    prior_years = {item['year']: item for item in history.get('years', [])}
    history['years'] = [{'year': year, 'status': prior_years.get(year, {}).get('status', 'partial'),
                         'observations': sum(p['date'].startswith(str(year)) for p in points)}
                        for year in range(history['parameters']['start_year'], cutoff.year + 1)]
    history['processed'] = history['total'] = len(history['years'])
    storage.source_snapshot('history:' + history['id'], history)
    run['dataset_id'] = history['id']
    run['phase'] = 'analysis'
    signature = input_signature(points, run['as_of'])
    changed = signature != plan.get('input_signature')
    run['input_changed'] = changed
    analysis = research.analyze(history['id'], run['as_of'])
    run['analysis'] = analysis
    prepared_visual=None
    if not collection_issue and changed:
        try:
            from . import visual_learning
            prepared_visual=visual_learning.prepare(history['id'],run['as_of'])
            run['visual_inputs']={'status':prepared_visual['status'],
                                  'image_ids':[a['id'] for a in prepared_visual['assets']],
                                  'issues':prepared_visual['issues']}
        except Exception:
            run['visual_inputs']={'status':'waiting_images'}
    try:
        vector = research.features(points, run['as_of'])
        run['features'] = dict(zip(research.FEATURE_NAMES, vector))
    except ValueError:
        run['features'] = None
    baseline = analysis['baseline']
    prediction = analysis.get('model_prediction')
    disagreement = bool(prediction and baseline['stage'] != 'inconclusivo' and prediction['stage'] != baseline['stage'])
    run['field_review'] = {'status': 'pending', 'priority': 'high' if collection_issue or disagreement or baseline['stage'] == 'inconclusivo' else 'normal',
                           'reason': 'Divergência entre regra e ML.' if disagreement else baseline['reason'],
                           'suggested_stage': baseline['stage'], 'confirmed_stage': None}
    labels = [record for record in research.events() if record['area_key'] == plan['area_key']
              and record['date_from'] <= run['as_of'] <= record['date_to']]
    if len(labels) == 1:
        run['field_review'].update(status='confirmed', confirmed_stage=labels[0]['stage'],
                                   field_event_id=labels[0]['id'], reviewed_at=labels[0]['created_at'])
    if not plan['ai_enabled']:
        run['ai_review'] = {'status': 'disabled'}
    elif not changed and plan.get('last_ai_review'):
        run['ai_review'] = {'status': 'unchanged', 'previous_run_id': plan['last_ai_review']}
    else:
        try:
            from . import visual_learning
            prepared_visual=prepared_visual or visual_learning.prepare(history['id'],run['as_of'])
            visual=visual_learning.review(prepared_visual,analysis=analysis)
            if visual['status']!='ready':raise ValueError('Imagens indisponíveis para revisão visual.')
            if visual.get('analysis_mode')=='visual':visual_learning.record_review(visual)
            run['visual_review']=visual
            response=visual['review']
            if response.get('provider') not in ('Gemini', 'OpenAI'):
                raise ValueError('A revisão precisa de um provedor de IA conectado.')
            run['ai_review'] = {'status': 'ready', **{k: response.get(k) for k in
                                ('answer', 'provider', 'model', 'sources', 'limitations', 'evidence_ids')}}
        except Exception as exc:
            # API failures never discard observations, invent reviews or expose secrets.
            run['ai_review'] = {'status': 'unavailable', 'issue': ai_failure(exc),
                                'note': 'Revisão da IA indisponível nesta rodada; observações preservadas.'}
    try:
        run['supervised_candidate'] = candidate()
    except Exception:
        run['supervised_candidate'] = {'status': 'unavailable'}
    run['status'] = 'partial' if collection_issue else 'ready' if run['features'] else 'insufficient_data'
    run['phase'] = 'finished'
    return {'latest_dataset_id': history['id'],
            **({'last_collected_to': run['as_of']} if not collection_issue else {}),
            'input_signature': signature,
            **({'last_ai_review': run['id']} if run['ai_review']['status'] == 'ready' else {})}


def candidate():
    records = research.events()
    signature = research.fingerprint(records)
    previous = storage.source_snapshot('learning:supervised-attempt')
    if previous and previous['result']['signature'] == signature:
        return previous['result']
    status = research.model_status()
    result = {'signature': signature, 'status': 'awaiting_field_records', 'events': len(records)}
    if status['events'] >= 30 and status['areas'] >= 3:
        try:
            result.update(status='evaluated', model=research.train(promote=False))
        except (ValueError, ImportError) as exc:
            result.update(status='not_ready', reason=str(exc))
    storage.source_snapshot('learning:supervised-attempt', result)
    return result


def run_once():
    claimed = claim()
    if not claimed:
        return None
    plan, run = claimed
    updates = {}
    try:
        updates = execute(plan, run)
        next_due = clock() + (timedelta(hours=6) if run.get('collection',{}).get('status')=='unavailable'
                              else timedelta(days=plan['interval_days']))
    except Exception as exc:
        logging.error('Falha na rodada de monitoramento %s (%s)', run['id'], type(exc).__name__)
        from .collection_issues import failure
        issue=failure('Copernicus' if run.get('phase')=='collection' else 'CropSense',run.get('phase','monitoramento'),exc)
        run.update(status='error', issue=issue, error=issue['message']+' Nova tentativa em seis horas.')
        next_due = clock() + timedelta(hours=6)
    run['finished_at'] = stamp(clock())
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT config FROM learning_plans WHERE id=?', (plan['id'],)).fetchone()
        config = json.loads(row['config'])
        if config.get('active_run_id') != run['id']:
            # A newer worker owns an expired lease: it alone may advance the plan.
            run.update(status='interrupted', error='Concessão expirada; uma nova rodada assumiu o acompanhamento.')
            db.execute('UPDATE learning_runs SET status=?,result=? WHERE id=?', (run['status'], json.dumps(run), run['id']))
            return run
        config.update(updates, last_run_id=run['id'])
        config.pop('active_run_id', None)
        db.execute('UPDATE learning_runs SET status=?,result=? WHERE id=?', (run['status'], json.dumps(run), run['id']))
        db.execute('UPDATE learning_plans SET config=?,next_due=?,lease_until=NULL WHERE id=?',
                   (json.dumps(config), stamp(next_due), plan['id']))
    return run


def review(data):
    """Human confirmation/correction uses the existing validated label pipeline."""
    run_id = data.get('run_id')
    with database() as db:
        row = db.execute('SELECT result FROM learning_runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise ValueError('Rodada de acompanhamento não encontrada.')
    run = json.loads(row['result'])
    if not run.get('dataset_id') or run.get('field_review', {}).get('status') == 'confirmed':
        raise ValueError('Rodada indisponível ou já validada em campo.')
    result = research.add_event({'dataset_id': run['dataset_id'], 'from': data.get('from', run['as_of']),
                                 'to': data.get('to', run['as_of']), 'stage': data.get('stage'),
                                 'note': data.get('note'), 'provenance': {
                                     'origin': 'human_field_record', 'learning_run_id': run_id,
                                     'partner': data.get('partner', ''), 'crop': data.get('crop', '')}})
    run['field_review'].update(status='confirmed', confirmed_stage=data['stage'],
                               field_event_id=result['event_id'], reviewed_at=stamp(clock()))
    with database() as db:
        db.execute('UPDATE learning_runs SET result=? WHERE id=?', (json.dumps(run), run_id))
    WAKE.set()
    return run


def evidence(area_key, cutoff):
    """Only a completed review for this exact geometry and past cutoff."""
    with database() as db:
        row = db.execute("SELECT r.result FROM learning_runs r JOIN learning_plans p ON p.id=r.plan_id "
                         "WHERE p.area_key=? AND r.status IN ('ready','partial','insufficient_data') "
                         "AND json_extract(r.result,'$.as_of')<=? "
                         "ORDER BY r.created_at DESC,r.rowid DESC LIMIT 1", (area_key, cutoff)).fetchone()
    if not row:
        return None
    run = json.loads(row['result'])
    if run.get('field_review', {}).get('reviewed_at', '')[:10] > cutoff:
        run['field_review'] = {'status': 'pending', 'note': 'Validação posterior à data consultada.'}
    # The LLM's earlier answer is not independent measurement or ground truth.
    return {'id': 'continuous_learning', 'source': 'CropSense · acompanhamento contínuo',
            'scope': 'mesmo recorte', 'as_of': run['as_of'], 'run_id': run['id'],
            'collection': run.get('collection'), 'field_review': run.get('field_review'),
            'ai_review_status': run.get('ai_review', {}).get('status'),
            'note': 'Hipóteses da IA não são rótulos; apenas registros humanos entram no modelo supervisionado.'}


def export(output_root=None):
    """Frozen feature windows with human targets joined by exact area/date."""
    with database() as db:
        db.execute('BEGIN')
        rows = [json.loads(r['result']) for r in db.execute('SELECT result FROM learning_runs ORDER BY created_at')]
        configs = {r['id']: json.loads(r['config']) for r in db.execute('SELECT id,config FROM learning_plans')}
        labels = [dict(r) for r in db.execute('SELECT * FROM field_events')]
    windows_by_date = {}
    for run in rows:
        if run['status'] not in ('ready', 'partial', 'insufficient_data') or not run.get('features'):
            continue
        plan = configs[run['plan_id']]
        matched = [r for r in labels if r['area_key'] == plan['area_key'] and r['date_from'] <= run['as_of'] <= r['date_to']]
        label = matched[0] if len(matched) == 1 else None
        windows_by_date[(plan['area_key'],run['as_of'])] = {'run_id': run['id'], 'dataset_id': run['dataset_id'], 'area_key': plan['area_key'],
                        'municipality_code': plan['municipality_code'], 'as_of': run['as_of'],
                        **run['features'], 'target_stage': label['stage'] if label else '',
                        'field_event_id': label['id'] if label else '', 'label_source': 'registro_de_campo' if label else ''}
    windows = list(windows_by_date.values())
    folder = Path(output_root or OUTPUT) / uuid.uuid4().hex
    folder.mkdir(parents=True)
    fields = ['run_id', 'dataset_id', 'area_key', 'municipality_code', 'as_of'] + research.FEATURE_NAMES + ['target_stage', 'field_event_id', 'label_source']
    with (folder / 'janelas_ml.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(windows)
    (folder / 'rodadas.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest = {'schema_version': 1, 'created_at': stamp(clock()), 'runs': len(rows), 'windows': len(windows),
                'field_labeled_windows': sum(bool(r['target_stage']) for r in windows),
                'folder': str(folder), 'note': 'Janelas congeladas por rodada; hipóteses automáticas não são alvos. Separar áreas e safras na avaliação.'}
    (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def worker():
    while not STOP.is_set():
        try:
            from . import regional_learning
            regional_learning.tick()
            if run_once() is not None:
                continue
            candidate()
        except Exception as exc:
            logging.error('Monitor contínuo indisponível (%s); próxima tentativa em um minuto.', type(exc).__name__)
        WAKE.wait(60)
        WAKE.clear()


def start_worker():
    global THREAD
    with THREAD_LOCK:
        if THREAD is None or not THREAD.is_alive():
            STOP.clear()
            THREAD = threading.Thread(target=worker, name='learning-cycle', daemon=True)
            THREAD.start()


def main():
    parser = argparse.ArgumentParser(description='Acompanhamento contínuo e aprendizado validado.')
    parser.add_argument('--enroll-pilot', action='store_true')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--export', action='store_true')
    args = parser.parse_args()
    if args.enroll_pilot:
        pilot = storage.source_snapshot('research:sorriso:pilot')
        if not pilot:
            parser.error('Abra primeiro a área de referência em Sorriso.')
        enroll({'dataset_id': pilot['result']['dataset_id'], 'name': 'Referência Sorriso'})
    if args.export:
        result = export()
    elif args.once:
        result = run_once()
    else:
        result = plans()
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
