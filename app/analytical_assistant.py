"""Executable local tools: history, saved spatial direction and declared calendar.

No tool here acquires satellite data or calls a language model. Work records survive
restarts and contain the actual evidence used to render the answer.
"""
import json
import re
import secrets
from datetime import date
from . import storage, research, local_inventory, evidence_contract
from .assistant_intents import normalize

VERSION = 1


def requested(prompt):
    text = normalize(prompt)
    if re.match(r'(?:nao|nunca)\b', text):
        return None
    if re.search(r'\b(?:consulte|consulte|busque|pesquise|cruze|compare|analise|como (?:estava|foi)|qual foi|quanta)\b.*\b(?:chuva|clima|meteorologia|temperatura|precipitacao)\b', text):
        return 'meteorology'
    if re.search(r'\bjanela (?:de )?plantio\b', text):
        return 'regional_calendar' if re.search(r'\b(?:regional|oficial|zarc|normativa|referencia)\b',text) else 'planting_window'
    if re.search(r'\b(?:direcao|direcional|esverdeamento|progressao|setores que mudaram)\b', text):
        return 'direction'
    if re.search(r'\b(?:compar\w*|diferenca)\b.*\b(?:historico|safras?|anos?|periodos?)\b', text):
        return 'historical_comparison'
    if re.search(r'\b(?:sintese|hipoteses|alternativas|cruze|cruzar|analise integrada)\b', text):
        return 'synthesis'
    return None


def _date(value):
    if not isinstance(value, str):
        raise ValueError('Data inválida para a análise.')
    try:
        if '/' in value:
            value = date(*map(int, reversed(value.split('/')))).isoformat()
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise ValueError('Data inválida para a análise.') from None


def history_for(data):
    scope = local_inventory.request_scope(data)
    identifier = data.get('dataset_id')
    if not identifier and scope['area_key']:
        with storage.connect() as db:
            row = db.execute("SELECT json_extract(result,'$.id') FROM source_snapshots "
                "WHERE cache_key >= 'history:' AND cache_key < 'history;' AND json_valid(result) "
                "AND json_extract(result,'$.parameters.area_key')=? "
                "ORDER BY json_extract(result,'$.parameters.as_of') DESC,fetched_at DESC LIMIT 1",
                (scope['area_key'],)).fetchone()
        identifier = row[0] if row else None
    if not identifier:
        raise ValueError('Selecione uma área com histórico salvo. Uma referência municipal não substitui o talhão.')
    history = research.dataset(identifier)
    params = history['parameters']
    actual_key = research.fingerprint(params['geometry'])
    if params.get('area_key') != actual_key:
        raise ValueError('O vínculo entre a geometria e o histórico precisa de revisão.')
    if scope['area_key'] and actual_key != scope['area_key']:
        raise ValueError('O histórico pertence a outro recorte. Abra o histórico da área selecionada.')
    code = params.get('municipality_code')
    if scope['municipality_code'] and code != scope['municipality_code']:
        raise ValueError('O histórico pertence a outro município.')
    if scope['state_code'] and (not code or not code.startswith(scope['state_code'])):
        raise ValueError('O histórico pertence a outro estado.')
    return history


def calendar(history, data, cutoff):
    key = 'evolution-window:v1:' + history['parameters']['area_key']
    supplied = data.get('planting_window')
    text = normalize(data['prompt'])
    if supplied is None and re.search(r'\b(?:declare|declarar|registre|registrar|minha janela|janela declarada)\b', text):
        dates = re.findall(r'\b(?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b', text)
        if len(dates) != 2:
            raise ValueError('Informe duas datas completas para declarar a janela de plantio.')
        supplied = {'from': dates[0], 'to': dates[1]}
    if supplied is not None:
        if not isinstance(supplied, dict):
            raise ValueError('Informe início e fim da janela de plantio.')
        first, last = _date(supplied.get('from')), _date(supplied.get('to'))
        if not 0 <= (date.fromisoformat(last) - date.fromisoformat(first)).days <= 180:
            raise ValueError('A janela de plantio precisa ter início e fim em até 180 dias.')
        record = {'from': first, 'to': last, 'source': 'Janela declarada pelo usuário, sem verificação externa',
                  'declared_at': storage.now(), 'season': data.get('season'),
                  'crop': data.get('declared_crop'), 'origin': 'user_declaration'}
        # Keep an immutable record as well as the current declaration used by the UI.
        declaration_key=key + ':declaration:' + research.fingerprint([first,last,data.get('season'),data.get('declared_crop')])
        existing=storage.source_snapshot(declaration_key)
        if existing:record=existing['result']
        else:storage.source_snapshot(declaration_key, record)
        storage.source_snapshot(key, record)
    saved = storage.source_snapshot(key)
    if not saved:
        return {'status': 'unavailable', 'reading': 'Não há janela de plantio declarada para este recorte.'}
    record = saved['result']
    if any(record.get(key) and data.get(request_key) and record[key]!=data[request_key]
           for key,request_key in (('season','season'),('crop','declared_crop'))):
        return {'status':'unavailable','reading':'A janela salva pertence a outra cultura ou safra declarada; informe a janela correspondente.'}
    inside = record['from'] <= cutoff <= record['to']
    return {'status': 'ready', **record, 'as_of': cutoff, 'inside': inside,
            'retrospective_declaration': record['declared_at'][:10] > cutoff,
            'reading': f"A data {cutoff} está {'dentro' if inside else 'fora'} da janela declarada de {record['from']} a {record['to']}. "
                       'Essa declaração não equivale a calendário oficial nem confirma semeadura.'}


def run(data, kind):
    from . import historical_comparison, crop_monitoring
    history = history_for(data)
    cutoff = _date(data.get('map_date') or history['parameters']['as_of'])
    if not date(2018, 1, 1) <= date.fromisoformat(cutoff) <= date.fromisoformat(history['parameters']['as_of']):
        raise ValueError('A data precisa estar dentro do histórico salvo; nenhuma nova coleta foi iniciada.')
    comparison = historical_comparison.compare(history, cutoff)
    window = calendar(history, data, cutoff)
    spatial = crop_monitoring.spatial_for(history, cutoff)
    if kind in ('direction', 'synthesis') and not (spatial or {}).get('progression'):
        from . import local_spatial
        spatial = local_spatial.analyze(history, cutoff, spatial)
    progression = (spatial or {}).get('progression') or {'status': 'unavailable', 'fronts': []}
    period = {'from': comparison['current']['from'], 'to': cutoff}
    envelope = lambda identifier, category, method, quality, value, resource=None: evidence_contract.computed(
        identifier, category, history, period, method, VERSION, quality, value, resource)
    evidence = [envelope('historical_comparison', 'seasonal_comparison', 'seasonal_30_day_comparison',
                        comparison['quality'], comparison),
                envelope('planting_window', 'declared_calendar', 'declared_window_comparison',
                         {'available': window['status'] == 'ready', 'independently_verified': False}, window)]
    regional = None
    if kind in ('regional_calendar','synthesis'):
        from . import regional_calendar
        regional = regional_calendar.compare({**data,'municipality_code':history['parameters'].get('municipality_code')},cutoff)
        evidence.append(envelope('regional_calendar','regional_calendar','reviewed_regional_reference_matching',
            {'status':regional['status'],'conditions_inferred':False},regional,'sqlite:regional-calendar:v1'))
    direction = {'status': progression['status'], 'fronts': progression.get('fronts', []),
                 'periods': (spatial or {}).get('periods', []),
                 'common_coverage': (spatial or {}).get('common_coverage')}
    evidence.append(envelope('vegetation_direction', 'spatial_progression',
        progression.get('method', 'saved_spatial_progression'),
        {'available': bool(spatial), 'status': direction['status'], 'common_coverage': direction['common_coverage']},
        direction, 'sqlite:cv:job:' + spatial['id'] if spatial else 'local:spatial_result_missing'))
    if direction['periods']:
        evidence[-1]['period'] = {'from': direction['periods'][0]['from'], 'to': direction['periods'][-1]['to']}
    weather_evidence = None
    weather_reading = None
    if kind in ('meteorology', 'synthesis'):
        from . import weather
        weather_evidence = weather.evidence(history, period['from'], cutoff, allow_network=kind == 'meteorology')
        if weather_evidence:
            meteorology = weather_evidence['data']
            meteorology['temporal_alignment'] = weather.cross_windows(meteorology, history, cutoff)
            evidence.append(weather_evidence)
            summary = meteorology['summary']
            amount = summary['precipitation_sum_available_mm']
            rain = f"{amount:.1f} mm nos dias disponíveis" if amount is not None else 'precipitação indisponível'
            weather_reading = f"Entre {period['from']} e {cutoff}, NASA POWER indica {rain}; {summary['precipitation_days']} de {summary['expected_days']} dias com precipitação utilizável. "
            if summary['minimum_temperature_c'] is not None and summary['maximum_temperature_c'] is not None:
                weather_reading += f"Temperaturas do ar entre {summary['minimum_temperature_c']:.1f} e {summary['maximum_temperature_c']:.1f} °C nos dias disponíveis. "
            weather_reading += 'Estimativas de grade regional de 0,5° × 0,625°, agregadas em UTC; não são medição de estação, previsão ou chuva medida no talhão. O cruzamento temporal não demonstra causa da mudança vegetal.'
    measurements = [comparison['reading']]
    if comparison['current'].get('usable'):
        current = comparison['current']
        measurements.append(f"NDVI médio {current['mean_ndvi']:.3f}; {current['observations']} observações válidas entre {current['from']} e {current['to']}.")
    fronts = direction['fronts']
    if fronts:
        periods = direction['periods']
        measurements.append(f"Sequência espacial entre {periods[0]['from']} e {periods[-1]['to']}.")
        for front in fronts:
            signal = 'Ganho' if front['signal'] == 'vegetation_gain' else 'Redução'
            measurements.append(f"{signal} de vegetação em sequência para {front['direction_label']}, em {front['affected_area_ha']:.2f} ha; centros dos setores inicial e posterior separados por {front['centroid_distance_m']:.1f} m.")
    else:
        measurements.append('Não foi detectada direção organizada nas comparações salvas.' if direction['status'] == 'not_detected'
                            else 'Direção inconclusiva nas comparações salvas.' if direction['status'] == 'inconclusive'
                            else 'Falta análise espacial salva compatível com este recorte e período.')
    measurements.append(window['reading'])
    hypotheses, divergences, missing = [], [], []
    if any(f['signal'] == 'vegetation_gain' for f in fronts):
        hypotheses.append('A progressão pode acompanhar estabelecimento vegetal, inclusive semeadura em setores; rebrota, plantas daninhas e diferenças de umidade são alternativas.')
    if any(f['signal'] == 'vegetation_loss' for f in fronts):
        hypotheses.append('Redução em sequência pode acompanhar senescência, colheita, dessecação ou outros eventos; a operação não está identificada.')
    current = comparison['current']
    if current.get('trend') == 'aumento' and comparison.get('position') == 'abaixo':
        divergences.append('O NDVI está aumentando, mas permanece abaixo da faixa central histórica.')
    if window.get('inside') is False:
        divergences.append('A data está fora da janela declarada; o sinal vegetal não confirma semeadura fora da janela.')
    if not current.get('usable'): missing.append('Leituras recentes suficientes, sem lacunas grandes.')
    if comparison['status'] != 'ready': missing.append('Ao menos três anos sazonais comparáveis do mesmo recorte.')
    if not spatial: missing.append('Rasters ou resultado espacial compatível, com datas e máscara de validade.')
    if window['status'] != 'ready': missing.append('Janela de plantio com origem identificada.')
    missing.extend(['Condições meteorológicas compatíveis e registros de campo para investigar causas.',
                    'Cor natural para examinar cobertura do solo; a legenda NDVI não identifica palhada.'])
    synthesis = {'measurements': measurements, 'hypotheses': hypotheses,
                 'divergences': divergences, 'missing': missing,
                 'next_check': 'Conferir datas de semeadura e emergência com o produtor e comparar os mesmos setores nas observações disponíveis.'}
    if weather_reading and kind == 'synthesis':
        measurements.append(weather_reading)
        missing[missing.index('Condições meteorológicas compatíveis e registros de campo para investigar causas.')] = 'Registros de campo para investigar causas; a grade meteorológica é uma estimativa regional.'
    if kind == 'regional_calendar':
        answer=regional['reading'];used=['regional_calendar']
        for reference in regional['references']:
            answer+=f"\n{reference['source_title']} ({reference['kind']}): {'dentro' if reference['inside'] else 'fora'} dos intervalos para as condições informadas; vigência {reference['valid_from']} a {reference['valid_to']}."
        answer+=' A janela declarada pelo usuário permanece registrada separadamente.'
    elif kind == 'meteorology':
        answer = weather_reading
        used = ['meteorology']
    elif kind == 'historical_comparison':
        answer = ' '.join(measurements[:2] if current.get('usable') else measurements[:1])
        used = ['historical_comparison']
    elif kind == 'direction':
        answer = ' '.join(measurements[2:-1] if current.get('usable') else measurements[1:-1])
        used = ['vegetation_direction']
    elif kind == 'planting_window':
        answer = window['reading']; used = ['planting_window']
    else:
        sections = [('Medições', measurements), ('Hipóteses e alternativas', hypotheses or ['Sem evidência suficiente para propor uma sequência de manejo.']),
                    ('Divergências', divergences or ['Nenhuma divergência adicional foi identificada nos dados disponíveis.']),
                    ('Pendências', missing)]
        answer = '\n\n'.join(title + ': ' + ' '.join(lines) for title, lines in sections)
        answer += '\n\nPróxima verificação: ' + synthesis['next_check']
        used = [e['id'] for e in evidence]
    limitations = [('Meteorologia consultada na NASA POWER; nenhuma consulta Sentinel ou chamada a provedor de IA.' if kind == 'meteorology' else 'Análise de resultados locais e contexto externo em cache; nenhuma consulta Sentinel ou chamada a provedor de IA.'),
                   'Direção vegetal não comprova trajeto de plantadeira, linhas, cultura, data de semeadura ou produtividade.']
    if window.get('retrospective_declaration'):
        limitations.append('Janela declarada depois da data analisada; comparação retrospectiva, sem alegar que a declaração já existia naquela data.')
    if data.get('season'):
        limitations.append('Safra declarada: ' + data['season'] + '; não confirmada pelas imagens.')
    return {'answer': answer, 'evidence_ids': used, 'limitations': limitations,
            'action': {'kind': 'none', 'class_ids': []}, 'provider': 'CropSense',
            'model': 'local-analytics-v1', 'intent': kind,
            'sources': [{'id': e['id'], 'source': e['source'], **({'url': e['url']} if e.get('url') else {})} for e in evidence if e['id'] in used],
            'evidence': evidence, 'synthesis': synthesis, 'as_of': cutoff, 'dataset_id': history['id']}


def reply(data, kind, work_id=None):
    identifier = work_id or secrets.token_hex(32)
    job = {'id': identifier, 'tool': kind, 'version': VERSION, 'status': 'running',
           'started_at': storage.now(), 'parameters': {k: data.get(k) for k in
               ('dataset_id', 'municipality_code', 'state_code', 'map_date', 'season', 'declared_crop')},
           'prompt': data['prompt'], 'mode': 'external_meteorology' if kind == 'meteorology' else 'local_only'}
    key = 'assistant-work:v1:' + identifier
    if work_id is None:storage.source_snapshot(key, job)
    try:
        response = run(data, kind)
        selected = [e for e in response['evidence'] if e['id'] in response['evidence_ids']]
        inconclusive = any(e['data'].get('status') in ('inconclusive', 'unavailable') for e in selected)
        job.update(status='inconclusive' if inconclusive else 'ready', result=response)
    except (ValueError, OSError, ImportError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Não foi possível concluir a análise local; confira arquivos e dependências.'
        response = {'answer': message, 'evidence_ids': [], 'limitations': ['Nenhuma nova coleta Sentinel foi iniciada.'],
                    'sources': [], 'action': {'kind': 'none', 'class_ids': []},
                    'provider': 'CropSense', 'model': 'local-analytics-v1', 'intent': kind}
        job.update(status='error', error=message, result=response)
    job['finished_at'] = storage.now()
    if work_id is None:storage.source_snapshot(key, job)
    response['work'] = {k: job[k] for k in ('id', 'tool', 'version', 'status', 'started_at', 'finished_at', 'mode')}
    return response
