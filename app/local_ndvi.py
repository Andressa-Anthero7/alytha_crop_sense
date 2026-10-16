"""Reuse dated NDVI evidence without substituting one polygon for another."""
import hashlib
import json
import math
import threading
import time
from datetime import date, timedelta
from urllib.error import HTTPError, URLError

from . import storage

LOCK = threading.Lock()
BLOCKED_UNTIL = 0
BLOCKED_REASON = ''
MAX_SERIES = 20


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def provider_issue(exc):
    global BLOCKED_UNTIL, BLOCKED_REASON
    reason = 'provider_unavailable'
    if isinstance(exc, HTTPError):
        reason = 'access_denied' if exc.code in (401, 403) else 'provider_unavailable'
        if exc.code == 403:
            try:
                error = json.loads(exc.read(8000)).get('error', {})
                if error.get('code') == 'ACCESS_INSUFFICIENT_PROCESSING_UNITS' or 'insufficient processing units' in error.get('message', '').lower():
                    reason = 'processing_quota'
            except (ValueError, TypeError, AttributeError):
                pass
        if exc.code in (401, 403, 429):
            with LOCK:
                BLOCKED_UNTIL = time.monotonic() + 900
                BLOCKED_REASON = reason
        exc.close()
    return reason


def local_series(geometry, first, last):
    """Read only snapshots with a verifiable geometry; never start a history job."""
    try:
        from shapely.geometry import shape
    except ImportError:
        shape = None
    requested = shape(geometry) if shape else None
    if requested is not None and (requested.is_empty or not requested.is_valid):
        raise ValueError('A área desenhada precisa formar um polígono válido, sem cruzamentos.')
    def coordinates(values):
        if isinstance(values[0], (int, float)):
            yield values
        else:
            for child in values:
                yield from coordinates(child)
    vertices = list(coordinates(geometry['coordinates']))
    west, south = min(p[0] for p in vertices), min(p[1] for p in vertices)
    east, north = max(p[0] for p in vertices), max(p[1] for p in vertices)
    grouped, aliases, excluded = {}, {}, set()

    def add(key, area, points, stamp, source):
        if not isinstance(area, dict) or not isinstance(points, list):
            return
        raw_key = fingerprint(area)
        if raw_key in excluded:
            return
        identifier = aliases.get(raw_key, raw_key)
        if identifier not in grouped:
            try:
                polygon = shape(area) if shape else None
                if polygon is not None and (polygon.is_empty or not polygon.is_valid or not requested.covers(polygon)):
                    excluded.add(raw_key)
                    return
                exact = requested.equals(polygon) if polygon is not None else area == geometry
                if not shape and not exact:
                    excluded.add(raw_key)
                    return
            except (ValueError, TypeError, KeyError):
                return
            identifier = fingerprint(geometry) if exact else raw_key
            aliases[raw_key] = identifier
            grouped.setdefault(identifier, {'id': identifier, 'geometry': area,
                'scope': 'exact_area' if exact else 'contained_sample',
                'source': source or 'Sentinel-2 L2A', 'saved_at': stamp, 'observations': {}, 'records': set()}
            )
        item = grouped[identifier]
        item['records'].add(key)
        item['saved_at'] = max(item['saved_at'], stamp)
        for point in points:
            if not isinstance(point, dict):
                continue
            when, value = point.get('date'), point.get('ndvi_mean')
            try:
                if not isinstance(when, str) or date.fromisoformat(when).isoformat() != when:
                    continue
            except ValueError:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or not -1 <= value <= 1:
                continue
            # Keep the original observation and quality; never interpolate missing days.
            prior = item['observations'].get(when)
            if prior is None or stamp > prior[0]:
                item['observations'][when] = (stamp, point)

    with storage.connect() as db:
        for row in db.execute("""SELECT cache_key,result,fetched_at FROM source_snapshots
            WHERE ((cache_key >= 'history:' AND cache_key < 'history;')
                OR (cache_key >= 'ndvi-query:v1:' AND cache_key < 'ndvi-query:v1;'))
                AND json_valid(result) AND json_array_length(result,'$.points') > 0
                AND (CASE json_extract(result,'$.parameters.geometry.type') WHEN 'MultiPolygon'
                    THEN json_extract(result,'$.parameters.geometry.coordinates[0][0][0][0]')
                    ELSE json_extract(result,'$.parameters.geometry.coordinates[0][0][0]') END) BETWEEN ? AND ?
                AND (CASE json_extract(result,'$.parameters.geometry.type') WHEN 'MultiPolygon'
                    THEN json_extract(result,'$.parameters.geometry.coordinates[0][0][0][1]')
                    ELSE json_extract(result,'$.parameters.geometry.coordinates[0][0][1]') END) BETWEEN ? AND ?""",
                    (west, east, south, north)):
            value = json.loads(row['result'])
            add(row['cache_key'], value.get('parameters', {}).get('geometry'), value.get('points'),
                row['fetched_at'], value.get('source'))
        for row in db.execute("""SELECT a.id,a.result,a.created_at,r.geometry FROM analyses a
            JOIN areas r ON r.id=a.area_id WHERE a.kind='ndvi' ORDER BY a.id"""):
            value = json.loads(row['result'])
            # Fallback samples are not persisted as a new full-area measurement.
            if value.get('mode') == 'local_cache':
                continue
            add('analysis:' + str(row['id']), json.loads(row['geometry']), value.get('points'),
                row['created_at'], value.get('source'))
    available = []
    candidates = []
    for item in grouped.values():
        dates = sorted(item.pop('observations').items())
        available.extend(when for when, _ in dates)
        item['history_points'] = [point for when, (_, point) in dates if when <= last
                                 and isinstance(point.get('available', when), str) and point.get('available', when) <= last]
        item['points'] = [point for when, (_, point) in dates if first <= when <= last
                          and isinstance(point.get('available', when), str) and point.get('available', when) <= last]
        item['records'] = sorted(item['records'])
        if item['points']:
            candidates.append(item)
    exact = [item for item in candidates if item['scope'] == 'exact_area']
    candidates = exact or candidates
    candidates.sort(key=lambda item: (len(item['points']), item['points'][-1]['date'], item['id']), reverse=True)
    return candidates[:MAX_SERIES], len(candidates), {'from': min(available), 'to': max(available)} if available else None


def fallback(geometry, first, last, reason, cached=None):
    if cached is not None:
        points = [p for p in cached['result']['points'] if first <= p['date'] <= last]
        series = [{'id': fingerprint(geometry), 'geometry': geometry, 'scope': 'exact_area',
                   'points': points, 'saved_at': cached['fetched_at'],
                   'source': cached['result'].get('source', 'Sentinel-2 L2A')}]
        total, available = 1, {'from': points[0]['date'], 'to': points[-1]['date']}
    else:
        series, total, available = local_series(geometry, first, last)
    explanation = {'processing_quota': 'Cota de processamento Copernicus esgotada.',
        'access_denied': 'Copernicus sem acesso autorizado.',
        'not_configured': 'A consulta externa ao Copernicus não está configurada.',
        'cached_query': 'Consulta já disponível na base local.'}.get(reason, 'Copernicus indisponível para atualizar a consulta.')
    points = series[0]['points'] if series else []
    scope = series[0]['scope'] if series else 'unavailable'
    if scope == 'exact_area':
        message = explanation + ' Exibindo leituras já salvas deste mesmo recorte, sem nova coleta.'
    elif scope == 'contained_sample':
        message = explanation + ' Exibindo um recorte salvo dentro da área selecionada; ele não representa toda a área. Sem nova coleta.'
    else:
        message = explanation + ' Não há leituras NDVI salvas para esta área no período solicitado.'
        if available:
            message += ' Ajuste o período para consultar as datas disponíveis na base local.'
    return {'mode': 'local_cache', 'status': 'ready' if points else 'unavailable',
        'reason': reason, 'message': message, 'source': 'Sentinel-2 L2A · base local salva',
        'points': points, 'series': series, 'scope': scope, 'total_series': total,
        'truncated': total > MAX_SERIES, 'requested_period': {'from': first, 'to': last},
        'available_period': available, 'new_collection': False}


def consult(geometry, first, last, provider, configured=True):
    key = 'ndvi-query:v1:' + fingerprint([geometry, first, last])
    cached = storage.source_snapshot(key)
    if cached and cached['result'].get('points'):
        return fallback(geometry, first, last, 'cached_query', cached)
    with LOCK:
        blocked = BLOCKED_UNTIL > time.monotonic()
        reason = BLOCKED_REASON
    if not configured or blocked:
        return fallback(geometry, first, last, reason if blocked else 'not_configured')
    cursor, end = date.fromisoformat(first), date.fromisoformat(last)
    observations, chunks, remote_calls = {}, [], 0
    while cursor <= end:
        chunk_end = min(end, date(cursor.year, 12, 31))
        begin, finish = cursor.isoformat(), chunk_end.isoformat()
        chunk_key = 'ndvi-query:v1:' + fingerprint([geometry, begin, finish])
        saved = storage.source_snapshot(chunk_key)
        if saved:
            result = saved['result']
        else:
            try:
                result = provider(geometry, begin, finish)
            except (HTTPError, URLError, OSError, ValueError, TimeoutError) as exc:
                # Successful earlier chunks are already saved and enter this fallback.
                return fallback(geometry, first, last, provider_issue(exc))
            storage.source_snapshot(chunk_key, {**result, 'parameters': {'geometry': geometry, 'from': begin, 'to': finish}})
            remote_calls += 1
        chunks.append({'from': begin, 'to': finish})
        for point in result.get('points', []):
            if begin <= point.get('date', '') <= finish:
                observations[point['date']] = point
        cursor = chunk_end + timedelta(days=1)
    result = {**result, 'points': [observations[day] for day in sorted(observations)], 'periods': chunks}
    cached = storage.source_snapshot(key, {**result, 'parameters': {'geometry': geometry, 'from': first, 'to': last}})
    if not remote_calls and result['points']:
        return fallback(geometry, first, last, 'cached_query', cached)
    return {**result, 'mode': 'remote', 'scope': 'exact_area'}
