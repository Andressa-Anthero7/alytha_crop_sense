"""NASA POWER daily grid meteorology with bounded reads and provenance.

Regional reanalysis estimates are never labeled station readings or forecasts.
Only explicit weather requests allow a network read; syntheses reuse cache.
"""
import hashlib
import json
import math
import threading
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from . import storage, research, evidence_contract

API = 'https://power.larc.nasa.gov/api/temporal/daily/point'
DOCS = 'https://power.larc.nasa.gov/docs/methodology/meteorology/'
PARAMETERS = {'PRECTOTCORR': ('precipitation_mm', 'mm/day'),
              'T2M_MIN': ('temperature_min_c', 'C'), 'T2M_MAX': ('temperature_max_c', 'C')}
LOCK = threading.Lock()
VERSION = 1


def cell_for(geometry):
    from shapely.geometry import shape
    point = shape(geometry).centroid
    if not (-180 <= point.x <= 180 and -90 <= point.y <= 90):
        raise ValueError('Coordenadas meteorológicas inválidas.')
    # Canonical MERRA-2 grid point; cache and requests use exactly the same point.
    lon = -180 + math.floor((point.x + 180) / .625 + .5) * .625
    lat = -90 + math.floor((point.y + 90) / .5 + .5) * .5
    if lon >= 180: lon = -180
    return {'longitude': lon, 'latitude': lat, 'resolution_degrees': [.625, .5]}


def query(history, first, last):
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    if not date(1981,1,1) <= start <= end <= date.today() or (end-start).days > 365:
        raise ValueError('Meteorologia aceita até 366 dias passados a partir de 1981.')
    cell = cell_for(history['parameters']['geometry'])
    params = {'parameters': ','.join(PARAMETERS), 'community': 'AG', **{k:cell[k] for k in ('longitude','latitude')},
              'start': start.strftime('%Y%m%d'), 'end': end.strftime('%Y%m%d'),
              'format': 'JSON', 'time-standard': 'UTC'}
    key = 'weather:nasa-power:v1:' + research.fingerprint(params)
    return key, params, cell


def normalize(payload, first, last):
    units = payload.get('parameters', {})
    for parameter, (_, unit) in PARAMETERS.items():
        if units.get(parameter, {}).get('units') != unit:
            raise ValueError('Unidades meteorológicas inesperadas; dados não foram utilizados.')
    header = payload.get('header', {})
    if header.get('time_standard') != 'UTC':
        raise ValueError('A fonte não confirmou a agregação meteorológica em UTC.')
    raw = payload.get('properties', {}).get('parameter', {})
    if not isinstance(raw, dict) or any(not isinstance(raw.get(k), dict) for k in PARAMETERS):
        raise ValueError('Série meteorológica incompleta ou inválida.')
    fill = header.get('fill_value', -999)
    points = []
    day = date.fromisoformat(first)
    while day <= date.fromisoformat(last):
        row = {'date': day.isoformat()}
        for parameter, (name, _) in PARAMETERS.items():
            value = raw[parameter].get(day.strftime('%Y%m%d'))
            valid = type(value) in (int,float) and math.isfinite(value) and value != fill
            valid = valid and (0 <= value <= 3000 if name == 'precipitation_mm' else -100 <= value <= 70)
            row[name] = value if valid else None
        if row['temperature_min_c'] is not None and row['temperature_max_c'] is not None and row['temperature_min_c'] > row['temperature_max_c']:
            row['temperature_min_c'] = row['temperature_max_c'] = None
        points.append(row); day += timedelta(days=1)
    return points


def series(history, first, last, allow_network=False):
    key, params, cell = query(history, first, last)
    with LOCK:
        cached = storage.source_snapshot(key)
        if cached:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(cached['fetched_at'])
            ttl = timedelta(days=30) if date.fromisoformat(last) < date.today()-timedelta(days=90) else timedelta(hours=24)
            if age < ttl or not allow_network:
                return {**cached['result'], 'cache': {'hit':True, 'stale':age >= ttl}, 'resource':key}
        if not allow_network:
            return None
        url = API + '?' + urlencode(params)
        request = Request(url, headers={'User-Agent':'AlythaCropSense/1.0', 'Accept':'application/json'})
        try:
            with urlopen(request, timeout=25) as response:
                binary = response.read(2_000_001)
            if len(binary) > 2_000_000: raise ValueError('Resposta meteorológica acima do limite.')
            payload = json.loads(binary)
        except (OSError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc) == 'Resposta meteorológica acima do limite.': raise
            raise ValueError('NASA POWER indisponível ou sem dados para o período; análise meteorológica pendente.') from None
        points = normalize(payload, first, last)
        valid = [p['precipitation_mm'] for p in points if p['precipitation_mm'] is not None]
        low = [p['temperature_min_c'] for p in points if p['temperature_min_c'] is not None]
        high = [p['temperature_max_c'] for p in points if p['temperature_max_c'] is not None]
        result = {'version': VERSION, 'source':'NASA POWER · MERRA-2', 'url':url, 'documentation_url':DOCS,
                  'kind':'gridded_reanalysis', 'is_station':False, 'is_forecast':False,
                  'cell':cell, 'period':{'from':first,'to':last}, 'time_standard':'UTC',
                  'fetched_at':storage.now(), 'raw_sha256':hashlib.sha256(binary).hexdigest(),
                  'api_version':payload.get('header',{}).get('api',{}).get('version'),
                  'points':points, 'status':'ready' if len(valid)==len(points) and len(low)==len(points) and len(high)==len(points) else 'inconclusive',
                  'summary':{'expected_days':len(points), 'precipitation_days':len(valid),
                             'precipitation_sum_available_mm':round(sum(valid),3) if valid else None,
                             'temperature_min_days':len(low), 'temperature_max_days':len(high),
                             'minimum_temperature_c':min(low) if low else None, 'maximum_temperature_c':max(high) if high else None},
                  'note':'Estimativa regional de grade, não pluviômetro do talhão nem umidade do solo. Dados recentes podem ser revistos. Ausências não são zeros.'}
        storage.source_snapshot(key,result)
        return {**result, 'cache':{'hit':False,'stale':False}, 'resource':key}


def evidence(history, first, last, allow_network=False):
    result = series(history, first, last, allow_network)
    if result is None: return None
    envelope = evidence_contract.computed('meteorology', 'gridded_meteorology', history,
        result['period'], 'nasa_power_daily', VERSION,
        {'status':result['status'], **result['summary']}, result, result['resource'], result['source'])
    envelope['scope'] = 'célula meteorológica regional associada ao centro do recorte; não medição do talhão'
    envelope['url'] = result['documentation_url']
    return envelope


def cross_windows(weather, history, cutoff):
    """Date alignment is descriptive, with no causal attribution or downscaling."""
    from .historical_comparison import prepare
    frame, _ = prepare(history, cutoff)
    frame = frame.loc[frame['date'] >= weather['period']['from']]
    rows = []
    for point in frame.to_dict('records'):
        first = point['date'].date().isoformat(); last = point['available'].date().isoformat()
        days = [p for p in weather['points'] if first <= p['date'] <= last]
        values = [p['precipitation_mm'] for p in days if p['precipitation_mm'] is not None]
        expected = (date.fromisoformat(last)-date.fromisoformat(first)).days+1
        rows.append({'from':first,'to':last,'ndvi_mean':point['ndvi_mean'],
                     'ndvi_valid_fraction':point['valid_fraction'], 'weather_days':len(values),
                     'expected_days':expected,'precipitation_available_mm':round(sum(values),3) if values else None,
                     'complete':len(values)==expected})
    return {'method':'alignment_of_available_days_v1','windows':rows,
            'note':'Alinhamento temporal entre escalas diferentes, sem demonstrar causa nem precisão meteorológica de 10 m.'}
