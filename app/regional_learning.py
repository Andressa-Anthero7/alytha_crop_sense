"""Consolidate the entire collected cohort before any LLM call.

One database read snapshot supplies immutable files, exact-area observations,
field-only targets, recurring area plans and a separately controlled AI queue.
No collector or provider is called while building the base.
"""
import argparse
import copy
import csv
import hashlib
import json
import logging
import math
import statistics
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from . import storage, research, learning_cycle

OUTPUT = Path(__file__).resolve().parents[1] / 'data/outputs/regional-learning'
LOCK = threading.Lock()
START_LOCK = threading.Lock()
BUILD_FUTURE = None
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='regional-base')
PREFIXES = ('municipality:v1:', 'municipal-activity:', 'municipal-soy:v1:',
            'inactive-evidence:', 'history:', 'ml:satellite:v1:', 'regional-scan:v1:', 'cv:job:')
AI_PROMPT = (
    'Revise a base agrícola deste município. Avalie a cobertura e a qualidade, '
    'os padrões de vegetação disponíveis, mudanças que merecem investigação e '
    'as lacunas. Pondere hipóteses alternativas e proponha verificações com '
    'parceiros para melhorar a base de ML. Respeite a escala de cada evidência: '
    'os recortes não representam todo o município. A seleção de exemplos é '
    'uma amostra explicitamente limitada. Não transforme hipóteses em rótulos '
    'confirmados, não estime produtividade nem execute ações no mapa.'
)


def now():
    return datetime.now(timezone.utc)


def schema(db):
    """Compatibility hook; storage.connect applies versioned migrations first."""


def source_stamp(db):
    clauses = ' OR '.join('cache_key LIKE ?' for _ in PREFIXES)
    row = db.execute('SELECT count(*) AS n,max(fetched_at) AS latest FROM source_snapshots WHERE ('+clauses+
                     ") AND NOT(cache_key LIKE 'history:%' AND coalesce(json_extract(result,'$.regional_seed'),0)=1)",
                     tuple(p+'%' for p in PREFIXES)).fetchone()
    labels = db.execute('SELECT count(*) AS n,max(id) AS latest FROM field_events').fetchone()
    visual=None
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='visual_jobs'").fetchone():
        visual=dict(db.execute("SELECT count(*) AS n,max(json_extract(result,'$.reviewed_at')) AS latest FROM visual_jobs WHERE status='ready'").fetchone())
    return research.fingerprint([dict(row),dict(labels),visual if visual and visual['n'] else None])


def read_sources():
    with storage.connect() as db:
        db.execute('BEGIN')
        clauses = ' OR '.join('cache_key LIKE ?' for _ in PREFIXES)
        raw = {row['cache_key']: row['result'] for row in db.execute(
            'SELECT cache_key,result FROM source_snapshots WHERE ('+clauses+
            ") AND NOT(cache_key LIKE 'history:%' AND coalesce(json_extract(result,'$.regional_seed'),0)=1)",tuple(p+'%' for p in PREFIXES))}
        fields = [dict(row) for row in db.execute('SELECT * FROM field_events ORDER BY id')]
        from . import visual_learning
        visual_rows=visual_learning.feature_rows(db)
        stamp = source_stamp(db)
    return raw, fields, stamp,visual_rows


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def roster(raw):
    """Include queued cities and data outside the regional roster as well."""
    from . import regional_batch
    cities = {}
    for _, uf in regional_batch.STATES:
        path = regional_batch.OUTPUT / ('roster-'+uf+'.json')
        if path.exists():
            for item in json.loads(path.read_text(encoding='utf-8'))['municipalities']:
                code = str(item['id'])
                cities[code] = {'code':code, 'name':item['nome'], 'uf':uf, 'collection_status':'queued'}
    for key, text in raw.items():
        if key.startswith('regional-scan:v1:'):
            for item in json.loads(text).get('cities', []):
                code = item['code']
                # A municipal scan may be newer than the state scan.
                prior = cities.get(code, {})
                if code not in cities or item.get('status') != 'queued' or prior.get('collection_status') == 'queued':
                    cities[code] = {**prior, 'code':code, 'name':item['name'],
                                    'collection_status':item.get('status','queued'), 'regional_record':item}
        elif key.startswith('municipality:v1:'):
            code = key.rsplit(':',1)[-1]; value = json.loads(text)
            cities.setdefault(code, {'code':code,'collection_status':'unlinked'})
            cities[code].update(name=value.get('name', code), uf=value.get('uf',''))
        elif key.startswith(('municipal-soy:v1:', 'ml:satellite:v1:')):
            code = key.rsplit(':',1)[-1]
            cities.setdefault(code, {'code':code,'name':code,'uf':'','collection_status':'unlinked'})
    return cities


def finite(point):
    return all(type(point.get(k)) in (int,float) and math.isfinite(point[k])
               for k in ('ndvi_mean','valid_pixels','valid_fraction'))


def observed(points, as_of):
    """Preserve actual partial composites with their source availability date."""
    end = date.fromisoformat(as_of)
    rows = {}
    for point in points:
        try:
            when = date.fromisoformat(point['date'])
            if when > end or not finite(point):
                continue
            available = point.get('available') or min(when+timedelta(days=4),date(when.year,12,31),end).isoformat()
            if not when<=date.fromisoformat(available)<=end:continue
            row = {**point,'available':available}
            old = rows.get(point['date'])
            if old is None or (learning_cycle.quality(row),row['valid_fraction']) >= (learning_cycle.quality(old),old['valid_fraction']):
                rows[point['date']] = row
        except (ValueError,TypeError,KeyError):
            continue
    return [rows[key] for key in sorted(rows)]


def csv_file(path, fields):
    stream = path.open('w',encoding='utf-8-sig',newline='')
    writer = csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
    writer.writeheader()
    return stream, writer


def build(output_root=None):
    if not LOCK.acquire(blocking=False):
        raise ValueError('A consolidação regional já está em andamento.')
    folder = None
    try:
        storage.source_snapshot('regional-learning:build',{'status':'building','started_at':now().isoformat()})
        raw, labels, stamp,visual_rows = read_sources()
        cities = roster(raw)
        if not cities:
            raise ValueError('Nenhuma cidade coletada ou cadastrada na rodada regional.')
        base_id = uuid.uuid4().hex
        folder = Path(output_root or OUTPUT) / base_id
        folder.mkdir(parents=True)
        (folder/'municipios').mkdir()
        get = lambda key: json.loads(raw[key]) if key in raw else None
        histories, jobs = {}, {}
        for key, text in raw.items():
            if key.startswith(('history:', 'municipal-activity:')):
                value = json.loads(text)
                code = value.get('parameters',{}).get('municipality_code','5107925')
                cities.setdefault(code,{'code':code,'name':code,'uf':'','collection_status':'unlinked'})
                (histories if key.startswith('history:') else jobs).setdefault(code,[]).append(value)
        labels_by_area = {}
        for label in labels:labels_by_area.setdefault(label['area_key'],[]).append(label)
        manifest = {'schema_version':1,'id':base_id,'created_at':now().isoformat(),'source_stamp':stamp,
                    'status':'building','folder':str(folder.resolve()),'municipalities':[],
                    'note':'Base observacional consolidada antes da IA. Hipóteses automáticas não são rótulos. Cada recorte conserva geometria, datas, qualidade e origem. Não extrapola cobertura para todo o município.'}
        common = ['municipality_code','area_key','track','source_id']
        obs_stream, obs_writer = csv_file(folder/'observacoes.csv', common+['date','available','ndvi_mean','valid_pixels','valid_fraction','quality_usable'])
        win_stream, win_writer = csv_file(folder/'janelas_ml.csv', common+['date_to']+research.FEATURE_NAMES+['target_stage','field_event_id','label_source'])
        seeds = {}
        counts = {'observations':0,'usable_observations':0,'feature_windows':0,'field_labeled_windows':0,'spatial_rows':0}
        obs_seen, win_seen = set(), set()
        records = []
        try:
            for code in sorted(cities):
                city = cities[code]
                dossier = get('municipality:v1:'+code)
                mapped = get('municipal-soy:v1:'+code)
                learned = get('ml:satellite:v1:'+code)
                city_jobs = sorted(jobs.get(code,[]), key=lambda item:(item['parameters']['as_of'], item.get('updated_at','')))
                latest_job = city_jobs[-1] if city_jobs else None
                city_histories = histories.get(code,[])
                per_area = {}
                city_counts = dict.fromkeys(counts,0)
                track_records = []

                def add_track(geometry, points, as_of, track, source_id, area_ha=None, history=None):
                    as_of=min(as_of,now().date().isoformat())
                    area_key = research.fingerprint(geometry)
                    rows = observed(points,as_of)
                    if not rows:return
                    usable = sum(learning_cycle.quality(row) for row in rows)
                    origin = dict(zip(common,[code,area_key,track,source_id]))
                    for index, point in enumerate(rows):
                        obs_key = (code,area_key,track,point['date'],point['available'])
                        if obs_key not in obs_seen:
                            obs_seen.add(obs_key)
                            obs_writer.writerow({**origin,**point,'quality_usable':learning_cycle.quality(point)})
                            city_counts['observations'] += 1
                            city_counts['usable_observations'] += int(learning_cycle.quality(point))
                        cutoff = point['available']
                        window_key = (code,area_key,track,cutoff)
                        if window_key in win_seen:continue
                        try:vector = research.features(rows[:index+1],cutoff)
                        except ValueError:continue
                        matched = [label for label in labels_by_area.get(area_key,[]) if label['date_from'] <= cutoff <= label['date_to']]
                        label = matched[0] if len(matched)==1 else None
                        win_writer.writerow({**origin,'date_to':cutoff,**dict(zip(research.FEATURE_NAMES,vector)),
                                             'target_stage':label['stage'] if label else '',
                                             'field_event_id':label['id'] if label else '',
                                             'label_source':'registro_de_campo' if label else ''})
                        win_seen.add(window_key);city_counts['feature_windows'] += 1
                        city_counts['field_labeled_windows'] += int(label is not None)
                    track_records.append({'area_key':area_key,'track':track,'source_id':source_id,'as_of':as_of,
                                          'observations':len(rows),'usable':usable,'area_ha':area_ha})
                    try:recent = dict(zip(research.FEATURE_NAMES,research.features(rows,as_of)))
                    except ValueError:recent = None
                    prior = per_area.get(area_key)
                    rank = (rows[-1]['available'],len(rows),track=='historical')
                    if prior is None or rank > prior['_rank']:
                        per_area[area_key] = {'area_key':area_key,'area_ha':area_ha,'last_observation':rows[-1]['date'],
                                              'available':rows[-1]['available'],'features':recent,'_rank':rank,
                                              'track':track,'source_id':source_id,'usable':usable}
                    if rows:
                        prior_seed = seeds.get(area_key)
                        # Prefer the full historical track when it exists, without
                        # combining overlapping composites from different grids.
                        seed_rank = (track=='historical',as_of,len(rows))
                        if prior_seed is None or seed_rank > prior_seed['_rank']:
                            seed = copy.deepcopy(history) if history else {'parameters':{'geometry':geometry,'area_key':area_key,
                                    'municipality_code':code,'start_year':int(rows[0]['date'][:4]),
                                    'end_year':int(as_of[:4]),'as_of':as_of},'status':'ready','points':rows,'years':[]}
                            seed['parameters'].update(as_of=as_of,end_year=int(as_of[:4]),area_key=area_key)
                            seed['points']=rows
                            seeds[area_key] = {'history':seed,'_rank':seed_rank,'name':city['name'],
                                              'area_key':area_key,'municipality_code':code,'as_of':as_of}

                # Historical tracks are deduplicated by geometry, choosing the
                # newest persisted version. Partial histories remain explicit.
                by_geometry = {}
                for history in sorted(city_histories,key=lambda h:h.get('parameters',{}).get('as_of','')):
                    params = history.get('parameters',{})
                    if not params.get('geometry'):continue
                    area_key = research.fingerprint(params['geometry'])
                    prior = by_geometry.get(area_key)
                    if prior is None:
                        by_geometry[area_key] = copy.deepcopy(history)
                    else:
                        # Later partial jobs must not erase previously collected years.
                        combined=observed(prior.get('points',[]),prior['parameters']['as_of'])+observed(history.get('points',[]),params['as_of'])
                        merged=copy.deepcopy(history)
                        merged['parameters']['start_year']=min(prior['parameters']['start_year'],params['start_year'])
                        merged['points']=observed(combined,params['as_of'])
                        merged['merged_source_ids']=list(dict.fromkeys(prior.get('merged_source_ids',[prior['id']])+[history['id']]))
                        by_geometry[area_key]=merged
                for history in by_geometry.values():
                    params = history['parameters']
                    add_track(params['geometry'],history.get('points',[]),params['as_of'],'historical',history['id'],history=history)
                if mapped:
                    write_json(folder/'municipios'/f'{code}-areas.geojson',{'type':'FeatureCollection','features':mapped.get('features',[])})
                    # Latest available query first so repeated exports do not
                    # replace better/updated observations with older values.
                    for job in reversed(city_jobs):
                        end = date.fromisoformat(job['parameters']['as_of'])
                        period = {'from':(end-timedelta(days=60)).isoformat(),'to':end.isoformat()}
                        for feature in mapped.get('features',[]):
                            cache_key = 'inactive-evidence:'+hashlib.sha256(json.dumps([feature['geometry'],period],sort_keys=True).encode()).hexdigest()
                            series = get(cache_key)
                            if series:
                                add_track(feature['geometry'],series.get('points',[]),end.isoformat(),
                                          'recent',cache_key,feature.get('properties',{}).get('area_ha'))
                    # A mapped area without a clear reading still needs a future
                    # revisit. Scheduling it must not invent an observation.
                    seed_as_of=latest_job['parameters']['as_of'] if latest_job else now().date().isoformat()
                    for feature in mapped.get('features',[]):
                        area_key=research.fingerprint(feature['geometry'])
                        if area_key in seeds:continue
                        history={'status':'partial','parameters':{'geometry':feature['geometry'],
                            'area_key':area_key,'municipality_code':code,'start_year':int(seed_as_of[:4]),
                            'end_year':int(seed_as_of[:4]),'as_of':seed_as_of},'points':[],'years':[],
                            'note':'Recorte mapeado sem leituras coletadas; condição da vegetação inconclusiva.'}
                        seeds[area_key]={'history':history,'_rank':(False,seed_as_of,0),
                            'name':city['name'],'area_key':area_key,'municipality_code':code,'as_of':seed_as_of}
                available_areas = [{k:v for k,v in row.items() if k!='_rank'} for row in per_area.values()]
                useful = [row for row in available_areas if row['features']]
                examples = sorted(useful,key=lambda row:abs(row['features']['first_last_delta']),reverse=True)[:12]
                regional = city.get('regional_record',{})
                from .collection_issues import diagnose
                issues = diagnose(regional,dossier,latest_job,None)
                readiness = 'temporal_data' if useful else 'observations_only' if available_areas else 'context_only' if dossier or mapped or learned else 'no_data'
                entry = {'code':code,'name':city['name'],'uf':city.get('uf',''),
                         'collection_status':city['collection_status'],'readiness':readiness,
                         'mapped_areas':len((mapped or {}).get('features',[])), 'areas_with_observations':len(available_areas),
                         'areas_with_recent_features':len(useful),'historical_tracks':len(by_geometry),
                         'has_model':bool(learned),'issues':issues,**city_counts}
                evidence = [{'id':'base_coverage','source':'CropSense · base consolidada','data':dict(entry),
                             'note':'Contagens de registros/recortes, sem extrapolação municipal. Histórico e série recente são trilhas separadas; podem representar a mesma geometria.'}]
                if dossier:
                    evidence.append({'id':'municipal_sources','source':'IBGE, CONAB e MapBiomas',
                                     'data':{k:dossier.get(k) for k in ('name','uf','status','sources','mapbiomas','conab')}})
                if latest_job:
                    evidence.append({'id':'municipal_vegetation','source':'Sentinel-2 · consulta municipal salva',
                                     'data':{k:latest_job.get(k) for k in ('status','parameters','summary','total','processed','failure_count','failures','note')},
                                     'points':latest_job.get('points',[])[-12:]})
                if learned:
                    evidence.append({'id':'municipal_learned_profiles','source':'CropSense · KMeans e IsolationForest',
                                     'data':{k:learned.get(k) for k in ('trained_at','period','areas','profiles','atypical_areas','collection_complete','note')}})
                if examples:
                    evidence.append({'id':'temporal_examples','source':'Características das leituras reais',
                                     'data':examples,'sample_size':len(examples),'eligible_areas':len(useful),
                                     'selection':'Até 12 recortes com maior mudança absoluta na janela disponível; não representa todo o município.'})
                city_fields = [label for label in labels if label['area_key'] in per_area]
                if city_fields:
                    evidence.append({'id':'field_observations','source':'Registros humanos de campo',
                                     'records':[{k:r[k] for k in ('id','area_key','date_from','date_to','stage','note')} for r in city_fields[:30]],
                                     'total':len(city_fields),'note':'Declarações de campo; não são inferências da IA.'})
                packet = {'schema_version':1,'base_id':base_id,'municipality':entry,'tracks':track_records,
                          'area_summaries':available_areas,'reference_histories':list(by_geometry.values()),
                          'ai_context':{'evidence':evidence,'map':{'municipality_code':code,'municipality_name':city['name']},
                                        'note':'Pacote congelado antes da revisão da IA. Hipóteses não são alvos de treinamento.'}}
                packet_path = folder/'municipios'/f'{code}.json'
                write_json(packet_path,packet)
                entry['packet_path'] = str(packet_path.resolve())
                entry['evidence_signature'] = research.fingerprint(packet['ai_context'])
                manifest['municipalities'].append(entry)
                for key in counts:counts[key] += city_counts[key]
                records.extend(city_fields)
        finally:
            obs_stream.close();win_stream.close()
        # Spatial features keep their own geometry and interval; no future join.
        spatial_stream, spatial_writer = csv_file(folder/'caracteristicas_espaciais.csv',
            ['area_key','job_id','date_from','date_to','features_json'])
        try:
            for key,text in raw.items():
                if not key.startswith('cv:job:'):continue
                value=json.loads(text);params=value.get('parameters',{});periods=value.get('periods',[])
                if value.get('status')=='ready' and params.get('area_id') in seeds and periods and value.get('ml_features'):
                    spatial_writer.writerow({'area_key':params['area_id'],'job_id':value['id'],
                        'date_from':periods[0]['from'],'date_to':periods[-1]['to'],
                        'features_json':json.dumps(value['ml_features'],ensure_ascii=False,allow_nan=False)})
                    counts['spatial_rows'] += 1
        finally:spatial_stream.close()
        write_json(folder/'registros_campo.json',list({record['id']:record for record in records}.values()))
        from .assistant import VISUAL_FEATURES
        visual_stream,visual_writer=csv_file(folder/'caracteristicas_visuais.csv',
            ['area_key','municipality_code','as_of','visual_job_id','feature_origin','image_hashes','available_at',
             'provider','model','field_informed','eligible_as_training_input']+VISUAL_FEATURES+['target_stage','label_source'])
        try:visual_writer.writerows(visual_rows)
        finally:visual_stream.close()
        manifest.update(status='ready', totals={**counts,'municipalities':len(cities),
            'processed_municipalities':sum(c['collection_status'] in ('ready','partial','error') for c in manifest['municipalities']),
            'municipalities_with_data':sum(c['readiness']!='no_data' for c in manifest['municipalities']),
            'municipalities_with_temporal_data':sum(c['readiness']=='temporal_data' for c in manifest['municipalities']),
            'municipalities_with_model':sum(c['has_model'] for c in manifest['municipalities']),
            'monitoring_areas':len(seeds),
            'visual_feature_rows':len(visual_rows),
            'areas_with_observations':sum(c['areas_with_observations'] for c in manifest['municipalities'])})
        (folder/'LEIA-ME.md').write_text('# Base regional antes da IA\n\n'
            'Observações e janelas preservam geometria, trilha temporal, datas e origem. '
            'Trilhas históricas e recentes podem se sobrepor na mesma área: não são exemplos independentes. '
            'Separe áreas espacialmente independentes e safras na avaliação. '
            'Alvos de manejo só vêm dos registros humanos de campo. '
            'Municípios sem dados ficam registrados como pendentes. '
            'Os pacotes para IA incluem contagens completas e uma amostra explícita de até 12 recortes; '
            'não enviam todas as imagens nem todas as geometrias ao provedor.\n',encoding='utf-8')
        write_json(folder/'manifest.json',manifest)
        with learning_cycle.database() as db:
            schema(db)
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO regional_base_versions VALUES(?,?,?,?)',
                       (base_id,manifest['created_at'],str(folder.resolve()),json.dumps(manifest)))
            for city in manifest['municipalities']:
                review_id=research.fingerprint([base_id,city['code']])
                reused=db.execute("SELECT id,result FROM regional_ai_reviews WHERE municipality_code=? AND signature=? AND status='ready' ORDER BY rowid DESC LIMIT 1",
                                  (city['code'],city['evidence_signature'])).fetchone()
                status='ready' if reused else 'blocked' if city['readiness']=='no_data' else 'pending'
                result={**json.loads(reused['result']),'reused_from':reused['id']} if reused else {}
                db.execute('INSERT INTO regional_ai_reviews(id,base_id,municipality_code,packet_path,signature,status,next_attempt,result) VALUES(?,?,?,?,?,?,?,?)',
                           (review_id,base_id,city['code'],city['packet_path'],city['evidence_signature'],status,manifest['created_at'],json.dumps(result)))
            scheduled=0
            for area_key, seed in seeds.items():
                history=seed['history'];params=history['parameters']
                plan_id=research.fingerprint(['continuous-monitoring',area_key])
                existing=db.execute('SELECT config,lease_until FROM learning_plans WHERE id=?',(plan_id,)).fetchone()
                prior_config=json.loads(existing['config']) if existing else None
                signature=research.fingerprint([params,history.get('points',[]),history.get('status')])
                if prior_config:
                    # Respect manually managed plans and preserve pauses. Reuse
                    # unchanged seeds instead of copying every geometry again.
                    if prior_config.get('base_seed_signature')==signature:
                        continue
                    if existing['lease_until'] and existing['lease_until']>now().isoformat():continue
                dataset_id=research.fingerprint(['regional-base-seed',base_id,area_key])
                frozen={**history,'id':dataset_id,'points':observed(history.get('points',[]),seed['as_of']),
                        'status':'partial' if history.get('status') in ('loading','error','partial') else 'ready',
                        'source':'Copernicus Sentinel-2 L2A','aggregation_days':5,'base_id':base_id,'regional_seed':True}
                db.execute('INSERT OR IGNORE INTO source_snapshots VALUES(?,?,?)',
                           ('history:'+dataset_id,json.dumps(frozen),manifest['created_at']))
                config={'id':plan_id,'area_key':area_key,'name':seed['name']+' · '+area_key[:8],
                        'municipality_code':seed['municipality_code'],'seed_dataset_id':dataset_id,
                        'latest_dataset_id':dataset_id,'interval_days':5,'ai_enabled':False,'enabled':True,
                        'created_at':manifest['created_at'],'base_id':base_id,
                        'ai_scope':'municipal_queue','base_seed_signature':signature}
                if history.get('points'):config['last_collected_to']=seed['as_of']
                if prior_config:
                    if prior_config.get('ai_scope')!='municipal_queue':
                        prior_config.update(ai_scope='municipal_queue',ai_enabled=False)
                    prior_config.update(seed_dataset_id=dataset_id,base_id=base_id,base_seed_signature=signature)
                    current=db.execute('SELECT result FROM source_snapshots WHERE cache_key=?',
                                       ('history:'+prior_config['latest_dataset_id'],)).fetchone()
                    if not current or json.loads(current['result'])['parameters']['as_of']<=seed['as_of']:
                        prior_config['latest_dataset_id']=dataset_id
                    db.execute('UPDATE learning_plans SET config=? WHERE id=?',(json.dumps(prior_config),plan_id))
                else:
                    db.execute('INSERT INTO learning_plans VALUES(?,?,?,?,NULL)',
                        (plan_id,area_key,json.dumps(config),(now()+timedelta(days=5)).isoformat()))
                    scheduled += 1
        manifest['new_monitoring_plans']=scheduled
        write_json(folder/'manifest.json',manifest)
        with storage.connect() as db:
            db.execute('UPDATE regional_base_versions SET manifest=? WHERE id=?',(json.dumps(manifest),base_id))
        storage.source_snapshot('regional-learning:latest',{'id':base_id,'folder':str(folder.resolve()),
            'created_at':manifest['created_at'],'totals':manifest['totals'],'new_monitoring_plans':scheduled,
            'source_stamp':stamp,'municipalities':manifest['municipalities']})
        config=storage.source_snapshot('regional-learning:config')
        settings=(config or {}).get('result',{'ai_enabled':False,'sync_enabled':True})
        settings.update(next_sync_check=(now()+timedelta(minutes=5)).isoformat())
        storage.source_snapshot('regional-learning:config',settings)
        storage.source_snapshot('regional-learning:build',{'status':'ready','base_id':base_id,'finished_at':now().isoformat()})
        return status_snapshot()
    except Exception:
        storage.source_snapshot('regional-learning:build',{'status':'error','note':'Consolidação não concluída; a base anterior foi preservada.'})
        raise
    finally:
        LOCK.release()


def start_build():
    global BUILD_FUTURE
    with START_LOCK:
        if not LOCK.locked() and (BUILD_FUTURE is None or BUILD_FUTURE.done()):
            storage.source_snapshot('regional-learning:build',{'status':'building','started_at':now().isoformat()})
            BUILD_FUTURE=POOL.submit(build)
    return status_snapshot()


def status_snapshot():
    latest=storage.source_snapshot('regional-learning:latest')
    build_state=storage.source_snapshot('regional-learning:build')
    settings=storage.source_snapshot('regional-learning:config')
    result={'base':latest['result'] if latest else None,
            'build':build_state['result'] if build_state else {'status':'not_started'},
            'ai_enabled':bool(settings and settings['result'].get('ai_enabled')),
            'backoff_until':settings['result'].get('backoff_until') if settings else None,'queue':{}}
    if latest:
        with storage.connect() as db:
            schema(db)
            result['queue']={r['status']:r['n'] for r in db.execute('SELECT status,count(*) AS n FROM regional_ai_reviews WHERE base_id=? GROUP BY status',(latest['result']['id'],))}
            queue={r['municipality_code']:r['status'] for r in db.execute('SELECT municipality_code,status FROM regional_ai_reviews WHERE base_id=?',(latest['result']['id'],))}
        result['base']['municipalities']=[{**city,'ai_status':queue.get(city['code'],'blocked')} for city in result['base']['municipalities']]
    from . import visual_learning
    result['visual']=visual_learning.status_snapshot()
    if latest:
        with storage.connect() as db:
            visual_learning.schema(db)
            counts={}
            for row in db.execute('SELECT municipality_code,status,count(*) AS n FROM visual_jobs WHERE base_id=? GROUP BY municipality_code,status',(latest['result']['id'],)):
                counts.setdefault(row['municipality_code'],{})[row['status']]=row['n']
        for city in result['base']['municipalities']:
            q=counts.get(city['code'],{})
            city['visual_areas']=q
            if q:
                city['ai_status']='ready' if q.get('ready',0)==sum(q.values()) else 'running' if q.get('running') else 'partial_review' if q.get('ready') else 'retry' if q.get('retry') else 'waiting_images'
    return result


def city_review(code):
    latest=storage.source_snapshot('regional-learning:latest')
    if not latest:raise ValueError('A base regional ainda não foi consolidada.')
    with storage.connect() as db:
        schema(db)
        row=db.execute('SELECT status,attempts,result FROM regional_ai_reviews WHERE base_id=? AND municipality_code=?',
                       (latest['result']['id'],code)).fetchone()
    if not row:raise ValueError('Município fora da base consolidada.')
    return {'base_id':latest['result']['id'],'municipality_code':code,
            'status':row['status'],'attempts':row['attempts'],**json.loads(row['result'])}


def configure(data):
    if type(data.get('ai_enabled')) is not bool:
        raise ValueError('Informe se a fila da IA deve ser ativada ou pausada.')
    if not storage.source_snapshot('regional-learning:latest'):
        raise ValueError('Consolide a base antes de iniciar a IA.')
    saved=storage.source_snapshot('regional-learning:config')
    settings=saved['result'] if saved else {'sync_enabled':True}
    settings['ai_enabled']=data['ai_enabled']
    settings['analysis_mode']='visual'
    storage.source_snapshot('regional-learning:config',settings)
    learning_cycle.WAKE.set()
    return status_snapshot()


def review_one():
    settings=storage.source_snapshot('regional-learning:config')
    latest=storage.source_snapshot('regional-learning:latest')
    if not settings or not settings['result'].get('ai_enabled') or not latest:return None
    instant=now().isoformat()
    if settings['result'].get('backoff_until','')>instant:return None
    with storage.connect() as db:
        schema(db);db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM regional_ai_reviews WHERE base_id=? AND "
                       "((status IN ('pending','retry') AND next_attempt<=?) OR (status='running' AND lease_until<=?)) ORDER BY municipality_code LIMIT 1",
                       (latest['result']['id'],instant,instant)).fetchone()
        if not row:return None
        db.execute("UPDATE regional_ai_reviews SET status='running',attempts=attempts+1,lease_until=? WHERE id=?",
                   ((now()+timedelta(minutes=15)).isoformat(),row['id']))
    try:
        packet=json.loads(Path(row['packet_path']).read_text(encoding='utf-8'))
        from . import assistant
        from .web_app import read_app_env
        response=assistant.review_context(AI_PROMPT,packet['ai_context'],read_app_env())
        if response.get('provider') not in ('Gemini','OpenAI'):raise ValueError('Provedor de IA indisponível.')
        result={'review':response,'reviewed_at':now().isoformat(),'training_target':None,
                'note':'Interpretação da IA, sem confirmação de manejo. Não é rótulo para o ML.'}
        status='ready';next_attempt=instant
    except Exception as exc:
        issue=learning_cycle.ai_failure(exc)
        next_attempt=(now()+timedelta(minutes=min(360,30*(row['attempts']+1)))).isoformat()
        result={'issue':issue,'training_target':None};status='retry'
        # A provider outage must not generate one failed request per city.
        current=storage.source_snapshot('regional-learning:config')['result']
        current['backoff_until']=next_attempt
        storage.source_snapshot('regional-learning:config',current)
    with storage.connect() as db:
        db.execute('UPDATE regional_ai_reviews SET status=?,next_attempt=?,lease_until=NULL,result=? WHERE id=?',
                   (status,next_attempt,json.dumps(result),row['id']))
    return {'municipality_code':row['municipality_code'],'status':status,**result}


def city_evidence(code, cutoff=None):
    latest=storage.source_snapshot('regional-learning:latest')
    if not latest:return None
    entry=next((c for c in latest['result'].get('municipalities',[]) if c['code']==code),None)
    if not entry:return None
    if cutoff and latest['result']['created_at'][:10]>cutoff:return None
    result={'id':'regional_base_coverage','source':'CropSense · base regional consolidada',
            'base_id':latest['result']['id'],'data':{k:entry[k] for k in
                ('readiness','collection_status','mapped_areas','areas_with_observations','areas_with_recent_features',
                 'observations','usable_observations','feature_windows','has_model')},
            'note':'A base integra todas as cidades da rodada. Recortes e trilhas não equivalem a cobertura integral municipal; hipóteses da IA ficam separadas dos alvos de campo.'}
    review=city_review(code)
    result['ai_review_status']=review['status']
    if review['status']=='ready' and (not cutoff or review.get('reviewed_at','')[:10]<=cutoff):
        result['previous_ai_interpretation']={'kind':'unconfirmed_hypothesis',
            'answer':review.get('review',{}).get('answer'),
            'note':'Interpretação anterior da IA para continuidade da conversa. Não é medição independente nem confirmação de campo.'}
    return result


def tick():
    latest=storage.source_snapshot('regional-learning:latest')
    settings=storage.source_snapshot('regional-learning:config')
    if not latest or not settings:return
    config=settings['result']
    if config.get('sync_enabled') and config.get('next_sync_check','')<=now().isoformat() and not LOCK.locked():
        with storage.connect() as db:stamp=source_stamp(db)
        config['next_sync_check']=(now()+timedelta(minutes=5)).isoformat()
        storage.source_snapshot('regional-learning:config',config)
        if stamp!=latest['result']['source_stamp']:start_build()
    from . import visual_learning
    visual_learning.review_next()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['build','status','ai-on','ai-off','review-one'])
    args=parser.parse_args()
    if args.command=='build':result=build()
    elif args.command=='status':result=status_snapshot()
    elif args.command in ('ai-on','ai-off'):result=configure({'ai_enabled':args.command=='ai-on'})
    else:
        from . import visual_learning
        result=visual_learning.review_next()
    # Keep the console compact; complete city inventory lives in the manifest.
    if result and 'base' in result and result['base']:
        result={**result,'base':{k:v for k,v in result['base'].items() if k!='municipalities'}}
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':main()
