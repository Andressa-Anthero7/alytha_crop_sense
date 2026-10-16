#!/usr/bin/env python3
"""Explore Sentinel-2 scene metadata intersecting a GeoJSON field geometry."""

from __future__ import annotations

import argparse
import json
import sys
import hashlib
import gzip
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urljoin, urlsplit


DEFAULT_ENDPOINT = "https://stac.dataspace.copernicus.eu/v1/search"
DEFAULT_COLLECTION = "sentinel-2-l2a"
DEFAULT_GEOJSON = Path(__file__).resolve().parents[1] / "data" / "sample-field.geojson"
MAX_RESPONSE_BYTES = 20_000_000


class CatalogUnavailable(ValueError):
    """The provider did not return usable scene metadata."""


def read_catalog(response):
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise CatalogUnavailable('A resposta do catálogo excedeu o limite de leitura.')
    if body.startswith(b'\x1f\x8b'):
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
            body = compressed.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise CatalogUnavailable('A resposta do catálogo excedeu o limite de leitura.')
    try:
        result = json.loads(body.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        raise CatalogUnavailable('O catálogo devolveu uma página de bloqueio ou uma resposta vazia, em vez dos dados das cenas.') from None
    if not isinstance(result, dict) or result.get('type') != 'FeatureCollection' or not isinstance(result.get('features'), list):
        raise CatalogUnavailable('O catálogo retornou uma resposta STAC inesperada.')
    if any(not isinstance(item, dict) or item.get('type') != 'Feature' or not isinstance(item.get('geometry'), dict)
           for item in result['features']):
        raise CatalogUnavailable('O catálogo retornou cenas com geometria inválida.')
    return result


def request_items_get(args, geometry):
    encoded_geometry = json.dumps(geometry, separators=(',', ':'))
    params = {'collections': args.collection, 'datetime': f'{args.date_from}T00:00:00Z/{args.date_to}T23:59:59Z',
              'query': json.dumps({'eo:cloud_cover': {'lte': args.max_cloud}}),
              'limit': min(args.limit, 100), 'sortby': '-properties.datetime'}
    area = None
    if len(encoded_geometry) < 3000:
        params['intersects'] = encoded_geometry
    else:
        try:
            from shapely.geometry import shape
        except ImportError:
            raise CatalogUnavailable('Para consultar este contorno complexo, instale as dependências geoespaciais da aplicação.') from None
        area = shape(geometry)
        params['bbox'] = ','.join(map(str, area.bounds))
    url = args.endpoint + '?' + urlencode(params)
    origin = urlsplit(args.endpoint)
    scenes, seen, visited = [], set(), set()
    result = None
    while url and url not in visited and len(visited) < 10:
        visited.add(url)
        request = Request(url, headers={'Accept': 'application/geo+json, application/json', 'User-Agent': 'Alytha/1.0'})
        with urlopen(request, timeout=45) as response:
            result = read_catalog(response)
        for item in result['features']:
            if area is not None and not area.intersects(shape(item['geometry'])):
                continue
            identifier = (item.get('collection'), item.get('id'))
            if identifier in seen:
                continue
            seen.add(identifier); scenes.append(item)
            if len(scenes) >= args.limit:
                break
        next_link = next((link for link in result.get('links', []) if link.get('rel') == 'next'), None)
        url = urljoin(url, next_link['href']) if next_link and next_link.get('href') else None
        if url and (urlsplit(url).scheme, urlsplit(url).netloc) != (origin.scheme, origin.netloc):
            raise CatalogUnavailable('O catálogo retornou uma paginação fora do serviço consultado.')
        if len(scenes) >= args.limit:
            break
    return {**result, 'features': scenes, 'catalog_transport': 'GET',
            'catalog_limited': bool(url), 'catalog_pages': len(visited)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Busca metadados Sentinel-2 para um talhão GeoJSON; não baixa imagens."
    )
    parser.add_argument("--geojson", type=Path, default=DEFAULT_GEOJSON, help="Arquivo GeoJSON (default: polígono fictício).")
    parser.add_argument("--from", dest="date_from", required=True, help="Data inicial inclusiva (AAAA-MM-DD).")
    parser.add_argument("--to", dest="date_to", required=True, help="Data final inclusiva (AAAA-MM-DD).")
    parser.add_argument("--max-cloud", type=float, default=40, help="Cobertura máxima de nuvens em %% (default: 40).")
    parser.add_argument("--limit", type=int, default=100, help="Máximo de cenas a solicitar (default: 100).")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="Endpoint STAC Item Search.")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help="Identificador da coleção STAC.")
    return parser.parse_args()


def validate_date(value: str, option: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{option} deve usar o formato AAAA-MM-DD: {value}") from exc


def extract_geometry(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("GeoJSON deve ser um objeto JSON.")
    kind = document.get("type")
    if kind == "Feature":
        geometry = document.get("geometry")
    elif kind == "FeatureCollection":
        features = document.get("features", [])
        if len(features) != 1:
            raise ValueError("FeatureCollection deve conter exatamente uma Feature.")
        geometry = features[0].get("geometry")
    elif kind in {"Polygon", "MultiPolygon"}:
        geometry = document
    else:
        raise ValueError("Informe uma geometria Polygon/MultiPolygon, Feature ou FeatureCollection.")
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("A geometria deve ser Polygon ou MultiPolygon.")
    if not geometry.get("coordinates"):
        raise ValueError("A geometria não contém coordenadas.")
    return geometry


def request_items(args: argparse.Namespace, geometry: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "collections": [args.collection],
        "datetime": f"{args.date_from}T00:00:00Z/{args.date_to}T23:59:59Z",
        "intersects": geometry,
        "query": {"eo:cloud_cover": {"lte": args.max_cloud}},
        "limit": args.limit,
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
    }
    request = Request(
        args.endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/geo+json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            return read_catalog(response)
    except HTTPError as exc:
        exc.close()
        return request_items_get(args, geometry)
    except (CatalogUnavailable, URLError, TimeoutError, OSError):
        return request_items_get(args, geometry)


def consult_items(args, geometry, provider):
    from . import storage
    parameters = {'geometry': geometry, 'from': args.date_from, 'to': args.date_to,
                  'max_cloud': args.max_cloud, 'limit': args.limit,
                  'endpoint': args.endpoint, 'collection': args.collection}
    key = 'catalog-query:v1:' + hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()
    try:
        result = provider(args, geometry)
    except (ValueError, OSError, HTTPError, URLError, TimeoutError):
        cached = storage.source_snapshot(key)
        if cached:
            return {**cached['result']['catalog'], 'mode': 'local_cache',
                    'message': 'Catálogo indisponível. Exibindo cenas já salvas desta mesma área, período e limite de nuvens.',
                    'saved_at': cached['fetched_at']}
        with storage.connect() as db:
            for row in db.execute("SELECT a.result,a.parameters,a.created_at,r.geometry FROM analyses a JOIN areas r ON r.id=a.area_id WHERE a.kind='catalog' ORDER BY a.id DESC"):
                if json.loads(row['geometry']) != geometry:
                    continue
                period = json.loads(row['parameters'])
                if period.get('from') == args.date_from and period.get('to') == args.date_to and period.get('max_cloud') == args.max_cloud and args.endpoint == DEFAULT_ENDPOINT and args.collection == DEFAULT_COLLECTION:
                    return {**json.loads(row['result']), 'mode': 'local_cache',
                            'message': 'Catálogo indisponível. Exibindo uma consulta anterior salva desta área e período.',
                            'saved_at': row['created_at']}
        raise CatalogUnavailable('O catálogo de cenas está temporariamente indisponível e não há uma consulta salva para esta área e período. Tente novamente mais tarde. Consultar vigor continua disponível com as leituras NDVI salvas.') from None
    storage.source_snapshot(key, {'parameters': parameters, 'catalog': result})
    return result


def summarize(result: dict[str, Any]) -> list[dict[str, Any]]:
    scenes = []
    for item in result["features"]:
        properties = item.get("properties") or {}
        scenes.append(
            {
                "id": item.get("id"),
                "datetime": properties.get("datetime"),
                "cloud_cover_percent": properties.get("eo:cloud_cover"),
                "collection": item.get("collection"),
                "metadata_url": next(
                    (link.get("href") for link in item.get("links", []) if link.get("rel") == "self"),
                    None,
                ),
            }
        )
    return scenes


def main() -> int:
    args = parse_args()
    try:
        start = validate_date(args.date_from, "--from")
        end = validate_date(args.date_to, "--to")
        if end < start:
            raise ValueError("--to deve ser igual ou posterior a --from.")
        if not 0 <= args.max_cloud <= 100:
            raise ValueError("--max-cloud deve ficar entre 0 e 100.")
        if args.limit < 1 or args.limit > 500:
            raise ValueError("--limit deve ficar entre 1 e 500.")
        with args.geojson.open(encoding="utf-8") as source:
            geometry = extract_geometry(json.load(source))
        result = request_items(args, geometry)
        scenes = summarize(result)
    except (OSError, json.JSONDecodeError, ValueError, HTTPError, URLError, TimeoutError) as exc:
        print(f"Erro na busca STAC: {exc}", file=sys.stderr)
        return 2

    print(f"Coleção: {args.collection} | cenas encontradas: {len(scenes)}")
    print("Metadados apenas; nenhuma imagem foi baixada.")
    if not scenes:
        print("Nenhuma cena atende ao polígono, período e limite de nuvens informados.")
    for scene in scenes:
        cloud = scene["cloud_cover_percent"]
        cloud_text = f"{cloud:.1f}%" if isinstance(cloud, (int, float)) else "não informado"
        print(f"- {scene['datetime'] or 'data ausente'} | nuvens {cloud_text} | {scene['id']}")
        if scene["metadata_url"]:
            print(f"  {scene['metadata_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
