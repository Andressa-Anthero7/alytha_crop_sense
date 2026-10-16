"""Read simplified Brazilian administrative areas from IBGE."""

import gzip
import io
import json
import logging
import re
import sqlite3
import ssl
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.request import Request, urlopen

BASE = "https://servicodados.ibge.gov.br/api"
CACHE_TTL = timedelta(days=7)
MAX_RESPONSE_BYTES = 20_000_000


def normalized(value):
    text = unicodedata.normalize('NFKD', value.casefold())
    return ' '.join(re.sub(r'[^a-z0-9 ]', ' ', ''.join(c for c in text if not unicodedata.combining(c))).split())


def search(query):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 120:
        raise ValueError('Digite uma cidade, estado ou sigla de UF (2–120 caracteres).')
    term = normalized(query)
    if len(term)<2: raise ValueError('Informe um nome de localidade válido.')
    states = fetch_ibge('/v1/localidades/estados?orderBy=nome')
    state_matches = [{'kind':'state','code':str(s['id']),'name':s['nome'],'uf':s['sigla']} for s in states if term in (normalized(s['nome']),normalized(s['sigla']),str(s['id']))]
    if state_matches and any(term in (normalized(s['sigla']),str(s['id'])) for s in states):
        return {'matches':state_matches,'exact':True}
    cities = fetch_ibge('/v1/localidades/municipios?orderBy=nome')
    uf_by_code = {str(s['id']):s for s in states}
    exact = list(state_matches)
    partial = [{'kind':'state','code':str(s['id']),'name':s['nome'],'uf':s['sigla']} for s in states if normalized(s['nome']).startswith(term)]
    for city in cities:
        code = str(city['id']); state = uf_by_code.get(code[:2])
        if not state: continue
        name = normalized(city['nome'])
        aliases = (name, name+' '+normalized(state['sigla']), name+' '+normalized(state['nome']), code)
        item = {'kind':'municipality','code':code,'name':city['nome'],'uf':state['sigla']}
        if term in aliases: exact.append(item)
        elif any(alias.startswith(term) for alias in aliases): partial.append(item)
    matches = exact or partial
    return {'matches':matches[:20],'exact':bool(exact),'truncated':len(matches)>20}


@lru_cache(maxsize=1)
def tls_context():
    """Use native certificate-chain building, without changing global SSL state."""
    try:
        import truststore
    except ImportError:
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def validate_response(path, data):
    if '/localidades/' in path:
        items = data if isinstance(data, list) else [data]
        if not items or any(not isinstance(item, dict) or type(item.get('id')) is not int
                            or not isinstance(item.get('nome'), str) or not item['nome'].strip()
                            for item in items):
            raise ValueError('Resposta de localidades do IBGE inválida.')
        if path.startswith('/v1/localidades/estados?') and any(
                not isinstance(item.get('sigla'),str) or not re.fullmatch('[A-Z]{2}',item['sigla']) for item in items):
            raise ValueError('Resposta de estados do IBGE inválida.')
    elif not isinstance(data, dict) or data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list):
        raise ValueError('Resposta de limites do IBGE inválida.')
    return data


def fetch_ibge(path):
    from . import storage
    if not isinstance(path, str) or not path.startswith(('/v1/localidades/', '/v3/malhas/')):
        raise ValueError('Recurso IBGE inválido.')
    key = 'ibge-response:v1:' + path
    saved = None
    try:
        saved = storage.source_snapshot(key)
        if saved:
            validate_response(path, saved['result']['data'])
            fetched = datetime.fromisoformat(saved['fetched_at'])
            if datetime.now(timezone.utc) - fetched < CACHE_TTL:
                return saved['result']['data']
    except (sqlite3.Error, ValueError, TypeError, KeyError):
        saved = None
    request = Request(BASE + path, headers={"Accept": "application/json", "User-Agent": "Alytha-LotMonitoring/1.0"})
    try:
        with urlopen(request, timeout=25, context=tls_context()) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError('Resposta do IBGE acima do limite local.')
        if body.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                body = compressed.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError('Resposta do IBGE acima do limite local.')
        result = validate_response(path, json.loads(body))
    except (OSError, ValueError):
        if saved:
            logging.getLogger(__name__).warning('IBGE unavailable; reusing saved administrative data: %s',path)
            return saved['result']['data']
        raise
    try:
        storage.source_snapshot(key, {'data': result, 'source': 'IBGE', 'source_url': BASE + path})
    except sqlite3.Error:
        logging.getLogger(__name__).warning('IBGE response available but local cache could not be saved: %s',path)
    return result


def location_data(path):
    if path == "/api/locations/states":
        return fetch_ibge("/v1/localidades/estados?orderBy=nome")
    match = re.fullmatch(r"/api/locations/states/([0-9]{2})/municipalities", path)
    if match:
        return fetch_ibge(f"/v1/localidades/estados/{match[1]}/municipios?orderBy=nome")
    match = re.fullmatch(r"/api/locations/boundaries/(states|municipalities)/([0-9]+)", path)
    if match:
        kind, code = match.groups()
        if len(code) != (2 if kind == "states" else 7):
            raise ValueError("Código IBGE inválido.")
        from . import storage
        key=f'ibge-boundary:v1:{kind}:{code}'
        saved=storage.source_snapshot(key)
        if saved:return saved['result']['boundary']
        resource = "estados" if kind == "states" else "municipios"
        result=fetch_ibge(f"/v3/malhas/{resource}/{code}?formato=application/vnd.geo%2Bjson&qualidade=minima")
        def points(coords):
            if len(coords)>=2 and isinstance(coords[0],(int,float)):
                yield coords[0],coords[1]
            else:
                for child in coords:yield from points(child)
        coords=[point for feature in result.get('features',[]) for point in points(feature['geometry'].get('coordinates',[]))]
        if coords:
            xs,ys=zip(*coords)
            storage.source_snapshot(key,{'boundary':result,'bounds':[min(xs),min(ys),max(xs),max(ys)],'source':'IBGE','source_url':BASE+f'/v3/malhas/{resource}/{code}'})
        return result
    raise ValueError("Localidade ou código IBGE inválido.")
