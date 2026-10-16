#!/usr/bin/env python3
"""Serve a local browser UI and proxy read-only Copernicus STAC searches."""

from __future__ import annotations

import json
import math
import os
import argparse
import re
from datetime import date
from argparse import Namespace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import Request, urlopen

from .catalog_search import DEFAULT_COLLECTION, DEFAULT_ENDPOINT, extract_geometry, request_items, validate_date
from .catalog_search import consult_items, CatalogUnavailable
from .localities import location_data, search as search_localities
from . import storage, data_sources, municipalities, inactive_soy, research, assistant, municipal_activity, satellite_learning, spatial_activity, crop_monitoring, map_layers
from . import learning_cycle
from . import regional_learning
from . import visual_learning
from . import regional_scan
from . import cdse_access
from . import local_ndvi
from . import planting_readiness


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
APP_ENV = ROOT / ".env"
CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_STATS_URL = "https://sh.dataspace.copernicus.eu/statistics/v1"

NDVI_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL", "dataMask"] }],
    output: [
      { id: "ndvi", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(samples) {
  const denominator = samples.B08 + samples.B04;
  const excludedClasses = [3, 6, 8, 9, 10, 11];
  const valid = samples.dataMask && denominator !== 0 && !excludedClasses.includes(samples.SCL);
  const value = denominator === 0 ? 0 : (samples.B08 - samples.B04) / denominator;
  return { ndvi: [value], dataMask: [valid ? 1 : 0] };
}"""

NDVI_MAP_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B08", "SCL", "dataMask"] }],
    output: { bands: 4, sampleType: "AUTO" }
  };
}
function evaluatePixel(samples) {
  const denominator = samples.B08 + samples.B04;
  const excludedClasses = [3, 6, 8, 9, 10, 11];
  if (!samples.dataMask || denominator === 0 || excludedClasses.includes(samples.SCL)) return [0, 0, 0, 0];
  const ndvi = (samples.B08 - samples.B04) / denominator;
  if (ndvi < 0.15) return [0.72, 0.48, 0.32, 0.68];
  if (ndvi < 0.35) return [0.94, 0.82, 0.35, 0.72];
  if (ndvi < 0.55) return [0.58, 0.76, 0.29, 0.76];
  return [0.12, 0.48, 0.22, 0.82];
}"""


def read_map_config():
    env = read_app_env()
    return {
        "google_maps_api_key": env.get("GOOGLE_MAPS_API_KEY", ""),
        "google_maps_map_id": env.get("GOOGLE_MAPS_MAP_ID", ""),
    }


def read_app_env():
    values = {}
    lines = APP_ENV.read_text(encoding="utf-8-sig").splitlines() if APP_ENV.is_file() else []
    for line in lines:
        name, separator, value = line.partition("=")
        if separator and not name.lstrip().startswith("#"):
            values[name.strip()] = value.strip().strip('"').strip("'")
    values.update({key: os.environ[key] for key in (
        "GOOGLE_MAPS_API_KEY", "GOOGLE_MAPS_MAP_ID", "CDSE_CLIENT_ID", "CDSE_CLIENT_SECRET", "GEE_PROJECT_ID", "EMBRAPA_ACCESS_TOKEN", "OPENAI_API_KEY", "OPENAI_MODEL", "AI_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL"
    ) if key in os.environ})
    return values


def project_to_web_mercator(geometry):
    import math

    def project(node):
        if isinstance(node, (list, tuple)) and len(node) >= 2 and isinstance(node[0], (int, float)):
            longitude, latitude = node[:2]
            if not -180 <= longitude <= 180 or not -85.05112878 <= latitude <= 85.05112878:
                raise ValueError("Coordenadas fora dos limites válidos para GeoJSON/WGS84.")
            radius = 6378137
            x = radius * math.radians(longitude)
            y = radius * math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2))
            return [x, y]
        return [project(value) for value in node]

    return {"type": geometry["type"], "coordinates": project(geometry["coordinates"]) }


def geometry_bbox(geometry):
    points = []

    def collect(node):
        if isinstance(node, list) and len(node) >= 2 and isinstance(node[0], (int, float)):
            points.append(node)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(geometry["coordinates"])
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def request_ndvi_map(geometry, acquisition_date):
    bbox = geometry_bbox(geometry)
    midpoint_lat = (bbox[1] + bbox[3]) / 2
    meters_per_degree_lat = 111320
    meters_per_degree_lon = max(1, meters_per_degree_lat * math.cos(math.radians(midpoint_lat)))
    width = max(1, round((bbox[2] - bbox[0]) * meters_per_degree_lon / 10))
    height = max(1, round((bbox[3] - bbox[1]) * meters_per_degree_lat / 10))
    scale = min(1, 1800 / max(width, height))
    width, height = max(1, round(width * scale)), max(1, round(height * scale))
    process_request = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "geometry": geometry,
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {"from": f"{acquisition_date}T00:00:00Z", "to": f"{acquisition_date}T23:59:59Z"},
                    "maxCloudCoverage": 80,
                    "mosaickingOrder": "leastCC",
                },
            }],
        },
        "output": {
            "width": width,
            "height": height,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": NDVI_MAP_EVALSCRIPT,
    }
    request = Request(
        "https://sh.dataspace.copernicus.eu/process/v1",
        data=json.dumps(process_request).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "image/png"},
        method="POST",
    )
    with cdse_access.RATE.open(request,urlopen,prepare=lambda req:req.add_header('Authorization','Bearer '+get_cdse_access_token())) as response:
        image = response.read()
    return image, bbox


def get_cdse_access_token():
    with cdse_access.RATE.lock:
        return _cached_cdse_access_token()


def _cached_cdse_access_token():
    env = read_app_env()
    client_id = env.get("CDSE_CLIENT_ID", "").strip()
    client_secret = env.get("CDSE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("Configure CDSE_CLIENT_ID e CDSE_CLIENT_SECRET no arquivo .env na raiz do projeto para processar NDVI.")
    credentials=(client_id,client_secret)
    token=cdse_access.TOKEN
    if token['credentials']==credentials and token['value'] and cdse_access.RATE.clock()<token['expires_at']:
        return token['value']
    request = Request(
        CDSE_TOKEN_URL,
        data=urlencode({"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with cdse_access.RATE.open(request,urlopen,timeout=30,milliseconds=False) as response:
        token_response = json.load(response)
    access_token = token_response.get("access_token")
    if not access_token:
        raise ValueError("O serviço Copernicus não retornou um token de acesso.")
    try:ttl=max(0,float(token_response.get('expires_in',0))-30)
    except (ValueError,TypeError):ttl=0
    token.update(credentials=credentials,value=access_token,expires_at=cdse_access.RATE.clock()+ttl if math.isfinite(ttl) else 0)
    return access_token


def request_ndvi_series(geometry, date_from, date_to):
    projected_geometry = project_to_web_mercator(geometry)
    bbox = geometry_bbox(projected_geometry)
    width = max(1, (bbox[2] - bbox[0]) / 10)
    height = max(1, (bbox[3] - bbox[1]) / 10)
    if width > 2500 or height > 2500 or width * height > 4_000_000:
        raise ValueError("Talhão grande demais para esta PoC em resolução de 10 m. Divida o polígono em áreas menores.")
    stats_request = {
        "input": {
            "bounds": {
                "geometry": projected_geometry,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/3857"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {"mosaickingOrder": "leastCC", "maxCloudCoverage": 80},
            }],
        },
        "aggregation": {
            "timeRange": {"from": f"{date_from}T00:00:00Z", "to": f"{date_to}T23:59:59Z"},
            "aggregationInterval": {"of": "P5D"},
            "evalscript": NDVI_EVALSCRIPT,
            "resx": 10,
            "resy": 10,
        },
    }
    request = Request(
        CDSE_STATS_URL,
        data=json.dumps(stats_request).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with cdse_access.RATE.open(request,urlopen,prepare=lambda req:req.add_header('Authorization','Bearer '+get_cdse_access_token())) as response:
        payload = json.load(response)
    points = []
    for interval in payload.get("data", []):
        stats = interval.get("outputs", {}).get("ndvi", {}).get("bands", {}).get("B0", {}).get("stats", {})
        mean = stats.get("mean")
        sample_count = stats.get('sampleCount',0)
        valid_count = max(0, sample_count - stats.get('noDataCount',0))
        if mean is None or not isinstance(mean,(int,float)) or not math.isfinite(mean) or not valid_count:
            continue
        geometry_count = interval.get('geometryPixelCount',sample_count)
        points.append({
            "date": interval.get("interval", {}).get("from", "")[:10],
            "ndvi_mean": mean,
            "valid_pixels": valid_count,
            "valid_fraction": min(1,valid_count/geometry_count) if geometry_count else 0,
        })
    return {"source": "Sentinel-2 L2A", "resolution_m": 10, "aggregation_days": 5, "points": points}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        region_path=urlsplit(self.path)
        if region_path.path == '/api/health':
            from . import health
            try:self._send_json(health.snapshot())
            except Exception:self._send_json({'status':'unavailable','database':'unreachable'},status=503)
            return
        work_match = re.fullmatch(r'/api/assistant/work/([a-f0-9]{64})', region_path.path)
        if work_match:
            from . import analysis_queue
            try:
                queued = analysis_queue.get(work_match[1])
            except ValueError:
                queued = None
            if queued:
                self._send_json(queued)
                return
            saved = storage.source_snapshot('assistant-work:v1:' + work_match[1])
            self._send_json(saved['result'] if saved else {'error':'Trabalho não encontrado.'}, status=200 if saved else 404)
            return
        if region_path.path == '/api/local-inventory':
            from . import local_inventory
            try:
                query = parse_qs(region_path.query)
                result = local_inventory.inventory({key: query[key][0] for key in
                    ('dataset_id', 'municipality_code', 'state_code', 'map_date') if key in query})
                self._send_json(result)
            except ValueError as exc:
                self._send_json({'error': str(exc)}, status=400)
            return
        scan_match=re.fullmatch(r'/api/regional-scans/([a-f0-9]{64})',region_path.path)
        if scan_match:
            try: self._send_json(regional_scan.get(scan_match[1]))
            except ValueError as exc: self._send_json({'error':str(exc)},status=400)
            return
        if region_path.path=='/api/locations/search':
            try: self._send_json(search_localities(parse_qs(region_path.query).get('q',[''])[0]))
            except ValueError as exc: self._send_json({'error':str(exc)},status=400)
            except Exception: self._send_json({'error':'Não foi possível consultar localidades no IBGE. Tente novamente.'},status=502)
            return
        parsed=urlsplit(self.path)
        visual_job=re.fullmatch(r'/api/visual-learning/([a-f0-9]{64})',parsed.path)
        if visual_job:
            try:self._send_json(visual_learning.get(visual_job[1]))
            except ValueError as exc:self._send_json({'error':str(exc)},status=400)
            return
        visual_asset=re.fullmatch(r'/api/visual-learning/assets/([a-f0-9]{64})\.png',parsed.path)
        if visual_asset:
            try:
                metadata,path=visual_learning.asset(visual_asset[1])
                binary=path.read_bytes()
                self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(binary)))
                self.end_headers();self.wfile.write(binary)
            except ValueError as exc:self._send_json({'error':str(exc)},status=400)
            except ConnectionError:pass
            return
        if parsed.path=='/api/regional-learning':
            self._send_json(regional_learning.status_snapshot());return
        base_city=re.fullmatch(r'/api/regional-learning/cities/([0-9]{7})',parsed.path)
        if base_city:
            try:self._send_json(regional_learning.city_review(base_city[1]))
            except ValueError as exc:self._send_json({'error':str(exc)},status=400)
            return
        base_file=re.fullmatch(r'/api/regional-learning/files/(manifest\.json|observacoes\.csv|janelas_ml\.csv|caracteristicas_visuais\.csv|caracteristicas_espaciais\.csv|registros_campo\.json)',parsed.path)
        if base_file:
            latest=storage.source_snapshot('regional-learning:latest')
            if not latest:self._send_json({'error':'Base ainda não consolidada.'},status=404);return
            path=Path(latest['result']['folder'])/base_file[1]
            try:
                with path.open('rb') as stream:
                    import shutil
                    self.send_response(200)
                    self.send_header('Content-Type','text/csv; charset=utf-8' if path.suffix=='.csv' else 'application/json; charset=utf-8')
                    self.send_header('Content-Disposition','attachment; filename="'+path.name+'"')
                    self.send_header('Content-Length',str(path.stat().st_size));self.end_headers()
                    shutil.copyfileobj(stream,self.wfile)
            except FileNotFoundError:self._send_json({'error':'Arquivo não disponível.'},status=404)
            except ConnectionError:pass
            return
        if parsed.path=='/api/learning-cycle':
            try:
                query=parse_qs(parsed.query)
                limit=int(query.get('limit',['50'])[0])
                if not 1<=limit<=200:raise ValueError('Limite de planos inválido.')
                plans=learning_cycle.plans(municipality_code=query.get('municipality_code',[None])[0],
                                          area_key=query.get('area_key',[None])[0],limit=limit)
                self._send_json(plans)
            except ValueError as exc:self._send_json({'error':str(exc)},status=400)
            return
        learning_match=re.fullmatch(r'/api/learning-cycle/([a-f0-9]{64})',parsed.path)
        if learning_match:
            try:self._send_json(learning_cycle.get(learning_match[1]))
            except ValueError as exc:self._send_json({'error':str(exc)},status=400)
            return
        crop_map_match=re.fullmatch(r'/api/sources/mapbiomas/jobs/([a-f0-9]{64})', parsed.path)
        if crop_map_match:
            try: self._send_json(map_layers.get(crop_map_match[1]))
            except ValueError as exc: self._send_json({'error':str(exc)}, status=400)
            return
        activity_map_match=re.fullmatch(r'/api/soy-activity/municipality/([a-f0-9]{64})/map',parsed.path)
        if activity_map_match:
            try:
                query=parse_qs(parsed.query)
                processed=int(query['processed'][0]) if 'processed' in query else None
                self._send_json(municipal_activity.map_assessment(activity_map_match[1],query.get('geometry',['1'])==['1'],processed))
            except ValueError as exc: self._send_json({'error':str(exc)},status=400)
            return
        spatial_match=re.fullmatch(r'/api/spatial-activity/([a-f0-9]{64})',self.path)
        if spatial_match:
            try: self._send_json(spatial_activity.get(spatial_match[1]))
            except ValueError as exc: self._send_json({'error':str(exc)},status=400)
            return
        municipal_match=re.fullmatch(r'/api/soy-activity/municipality/([a-f0-9]{64})',self.path)
        if municipal_match:
            try: self._send_json(municipal_activity.get(municipal_match[1]))
            except ValueError as exc: self._send_json({'error':str(exc)},status=400)
            return
        match=re.fullmatch(r'/api/research/history/([a-f0-9]{64})',self.path)
        if match:
            try: self._send_json(research.restore_history(match[1]))
            except ValueError as exc: self._send_json({'error':str(exc)},status=400)
            return
        if parsed.path=='/api/research/status':
            reference=storage.source_snapshot('research:sorriso:pilot')
            env=read_app_env()
            code=parse_qs(parsed.query).get('municipality_code',['5107925'])[0]
            try:
                municipalities.key(code)
                self._send_json({'assistant':assistant.configuration(env),'openai_configured':bool(env.get('OPENAI_API_KEY')),'ml':research.model_status(),'satellite':satellite_learning.status(code),'pilot':reference['result'] if reference and code=='5107925' else None})
            except ValueError as exc:self._send_json({'error':str(exc)},status=400)
            return
        if self.path=='/api/research/events':
            self._send_json(research.events());return
        match = re.fullmatch(r'/api/inactive-soy/([a-f0-9]{64})',self.path)
        if match:
            try: self._send_json(inactive_soy.get(match[1]))
            except ValueError as exc: self._send_json({'error':str(exc)},status=400)
            return
        match = re.fullmatch(r'/api/municipalities/([0-9]{7})', self.path)
        if match:
            try: self._send_json(municipalities.request(match[1]))
            except ValueError as exc: self._send_json({'error':str(exc)},status=400)
            return
        if self.path == '/api/sources/status':
            self._send_json({'satveg_configured': bool(read_app_env().get('EMBRAPA_ACCESS_TOKEN'))})
            return
        if urlsplit(self.path).path == '/api/sources/conab':
            try:
                query = parse_qs(urlsplit(self.path).query)
                self._send_json(data_sources.conab(query.get('uf',[''])[0], query.get('crop',[''])[0]))
            except ValueError as exc:
                self._send_json({'error': str(exc)}, status=400)
            except (OSError, URLError) as exc:
                self._send_json({'error': 'CONAB indisponível. Tente novamente mais tarde.'}, status=502)
            return
        if self.path == '/api/areas' or self.path.startswith('/api/areas/'):
            try:
                if self.path == '/api/areas':
                    self._send_json(storage.list_areas())
                else:
                    match = re.fullmatch(r'/api/areas/([0-9]+)(/history)?', self.path)
                    if not match:
                        raise ValueError('Consulta de área inválida.')
                    area_id = int(match[1])
                    self._send_json(storage.history(area_id) if match[2] else storage.get_area(area_id))
            except ValueError as exc:
                self._send_json({'error': str(exc)}, status=400)
            return
        if self.path.startswith("/api/locations/"):
            try:
                self._send_json(location_data(self.path))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except (OSError, HTTPError, URLError, TimeoutError) as exc:
                self._send_json({"error": "Não foi possível consultar o IBGE. Tente novamente em instantes."}, status=502)
            return
        if self.path == "/api/config":
            config = read_map_config()
            config["ndvi_configured"] = all(read_app_env().get(key) for key in ("CDSE_CLIENT_ID", "CDSE_CLIENT_SECRET"))
            self._send_json(config)
            return
        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if self.path == '/api/assistant/jobs':
            from . import analysis_queue
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=100_000:raise ValueError('Pedido de análise inválido.')
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict):raise ValueError('Informe um objeto JSON.')
                self._send_json(analysis_queue.submit(data),status=202)
            except (ValueError,TypeError) as exc:self._send_json({'error':str(exc)},status=400)
            return
        if self.path=='/api/visual-learning':
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2000:raise ValueError('Pedido visual inválido.')
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict):raise ValueError('Informe um objeto JSON.')
                self._send_json(visual_learning.start(data),status=202)
            except (ValueError,TypeError) as exc:self._send_json({'error':str(exc)},status=400)
            return
        if self.path in ('/api/regional-learning/build','/api/regional-learning/configure'):
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2000:raise ValueError('Pedido regional inválido.')
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict):raise ValueError('Informe um objeto JSON.')
                result=regional_learning.start_build() if self.path.endswith('/build') else regional_learning.configure(data)
                self._send_json(result,status=202 if self.path.endswith('/build') else 200)
            except (ValueError,TypeError) as exc:self._send_json({'error':str(exc)},status=400)
            return
        if self.path in ('/api/learning-cycle','/api/learning-cycle/configure','/api/learning-cycle/review','/api/learning-cycle/export'):
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=20_000:raise ValueError('Pedido de acompanhamento inválido.')
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict):raise ValueError('Informe um objeto JSON.')
                operations={'/api/learning-cycle':learning_cycle.enroll,
                            '/api/learning-cycle/configure':learning_cycle.configure,
                            '/api/learning-cycle/review':learning_cycle.review}
                result=learning_cycle.export() if self.path.endswith('/export') else operations[self.path](data)
                self._send_json(result)
            except (ValueError,TypeError) as exc:self._send_json({'error':str(exc)},status=400)
            except Exception:self._send_json({'error':'Não foi possível atualizar o acompanhamento contínuo.'},status=502)
            return
        if self.path=='/api/regional-scans':
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2000: raise ValueError('Pedido de região inválido.')
                job=regional_scan.start(json.loads(self.rfile.read(size)))
                self._send_json(job,status=202 if job['status']=='loading' else 200)
            except ValueError as exc: self._send_json({'error':str(exc)},status=400)
            except Exception: self._send_json({'error':'Não foi possível iniciar a varredura regional.'},status=502)
            return
        if self.path == '/api/sources/mapbiomas/jobs':
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 2_000_000: raise ValueError('Tamanho do pedido inválido.')
                job = map_layers.start(json.loads(self.rfile.read(size)))
                self._send_json(job, status=202 if job['status']=='loading' else 200)
            except ValueError as exc: self._send_json({'error':str(exc)}, status=400)
            except Exception: self._send_json({'error':'Não foi possível iniciar a consulta de culturas. Tente novamente.'}, status=502)
            return
        if self.path in ('/api/crop-monitoring','/api/spatial-activity','/api/research/history','/api/research/pilot','/api/research/events','/api/research/train','/api/research/satellite-learning','/api/research/analyze','/api/assistant','/api/soy-activity','/api/soy-activity/municipality'):
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2_000_000: raise ValueError('Pedido inválido.')
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict): raise ValueError('Informe um objeto JSON.')
                if self.path in ('/api/spatial-activity','/api/research/history','/api/research/pilot','/api/soy-activity','/api/soy-activity/municipality') and not all(read_app_env().get(key) for key in ('CDSE_CLIENT_ID','CDSE_CLIENT_SECRET')): raise ValueError('Histórico Sentinel-2 indisponível no momento.')
                if self.path=='/api/crop-monitoring': result=crop_monitoring.create(data)
                elif self.path=='/api/spatial-activity': result=spatial_activity.start(data)
                elif self.path=='/api/research/history': result=research.start_history(data)
                elif self.path=='/api/research/pilot': result=research.pilot()
                elif self.path=='/api/research/events': result=research.add_event(data)
                elif self.path=='/api/research/train': result=research.train()
                elif self.path=='/api/research/satellite-learning': result=satellite_learning.train(str(data.get('municipality_code','5107925')))
                elif self.path=='/api/research/analyze': result=research.analyze(data.get('dataset_id'),data.get('date'))
                elif self.path=='/api/soy-activity': result=inactive_soy.activity(data)
                elif self.path=='/api/soy-activity/municipality': result=municipal_activity.start(data)
                else: result=assistant.ask(data,read_app_env())
                self._send_json(result)
            except (ValueError,TypeError,ImportError) as exc: self._send_json({'error':str(exc)},status=400)
            except Exception: self._send_json({'error':'Não foi possível concluir esta operação. Verifique os dados e tente novamente.'},status=502)
            return
        if self.path == '/api/inactive-soy':
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2_000_000: raise ValueError('Pedido inválido.')
                if not all(read_app_env().get(key) for key in ('CDSE_CLIENT_ID','CDSE_CLIENT_SECRET')):
                    raise ValueError('Monitoramento Sentinel-2 indisponível no momento.')
                self._send_json(inactive_soy.start(json.loads(self.rfile.read(size))))
            except ValueError as exc: self._send_json({'error':str(exc)},status=400)
            except Exception: self._send_json({'error':'Não foi possível iniciar a triagem. Tente novamente.'},status=502)
            return
        if self.path in ('/api/sources/mapbiomas', '/api/sources/satveg'):
            try:
                size = int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 2_000_000: raise ValueError('Tamanho do pedido inválido.')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict): raise ValueError('Informe um objeto JSON.')
                result = data_sources.mapbiomas(data) if self.path.endswith('mapbiomas') else data_sources.satveg(data, read_app_env().get('EMBRAPA_ACCESS_TOKEN',''))
                self._send_json(result)
            except ValueError as exc:
                self._send_json({'error':str(exc)}, status=400)
            except Exception:
                self._send_json({'error':'Não foi possível consultar a fonte. Verifique sua conexão e configuração e tente novamente.'}, status=502)
            return
        if self.path == '/api/areas':
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 2_000_000:
                    raise ValueError('Tamanho do cadastro inválido.')
                self._send_json(storage.save_area(json.loads(self.rfile.read(size))), status=201)
            except (ValueError, OSError) as exc:
                self._send_json({'error': str(exc)}, status=400)
            return
        if self.path == "/api/ndvi-series":
            self._handle_ndvi_series()
            return
        if self.path == '/api/planting-readiness':
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2_000_000:raise ValueError('Tamanho do pedido inválido.')
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict):raise ValueError('Pedido inválido.')
                geometry=extract_geometry(data.get('geojson'))
                self._send_json(planting_readiness.consult(geometry,data.get('field_inputs',{})))
            except (ValueError,TypeError,OSError) as exc:
                self._send_json({'error':str(exc)},status=400)
            return
        if self.path == "/api/ndvi-map":
            self._handle_ndvi_map()
            return
        if self.path != "/api/search":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 2_000_000:
                raise ValueError("Tamanho do pedido inválido.")
            data = json.loads(self.rfile.read(size))
            geometry = extract_geometry(data.get("geojson"))
            area_id = storage.validate_analysis_area(data, geometry)
            date_from = data.get("from")
            date_to = data.get("to")
            max_cloud = float(data.get("max_cloud", 40))
            if not isinstance(date_from, str) or not isinstance(date_to, str):
                raise ValueError("Informe as datas inicial e final.")

            if validate_date(date_to, "Data final") < validate_date(date_from, "Data inicial"):
                raise ValueError("A data final deve ser igual ou posterior à inicial.")
            if not 0 <= max_cloud <= 100:
                raise ValueError("O limite de nuvens deve ficar entre 0 e 100%.")
            args = Namespace(
                endpoint=DEFAULT_ENDPOINT,
                collection=DEFAULT_COLLECTION,
                date_from=date_from,
                date_to=date_to,
                max_cloud=max_cloud,
                limit=100,
            )
            result = consult_items(args, geometry, request_items)
            if result.get('mode') != 'local_cache':
                storage.save_analysis(area_id, 'catalog', {'from': date_from, 'to': date_to, 'max_cloud': max_cloud}, result)
            self._send_json(result)
        except CatalogUnavailable as exc:
            self._send_json({'error': str(exc)}, status=502)
        except (OSError, json.JSONDecodeError, ValueError, HTTPError, URLError, TimeoutError) as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _handle_ndvi_series(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 2_000_000:
                raise ValueError("Tamanho do pedido inválido.")
            data = json.loads(self.rfile.read(size))
            geometry = extract_geometry(data.get("geojson"))
            area_id = storage.validate_analysis_area(data, geometry)
            date_from = data.get("from")
            date_to = data.get("to")
            if not isinstance(date_from, str) or not isinstance(date_to, str):
                raise ValueError("Informe o período de análise.")

            start, end = validate_date(date_from, "Data inicial"), validate_date(date_to, "Data final")
            if end < start:
                raise ValueError("A data final deve ser igual ou posterior à inicial.")
            if start < date(2018,1,1) or end > inactive_soy.today():
                raise ValueError('Escolha um período entre 01/01/2018 e hoje.')
            credentials = read_app_env()
            result = local_ndvi.consult(geometry, date_from, date_to, request_ndvi_series,
                configured=all(credentials.get(key) for key in ('CDSE_CLIENT_ID','CDSE_CLIENT_SECRET')))
            if result.get('mode') == 'remote':
                storage.save_analysis(area_id, 'ndvi', {'from': date_from, 'to': date_to}, result)
            # Reuse saved years of the same polygon; never collect new images here.
            saved, _, _ = local_ndvi.local_series(geometry, '2018-01-01', date_to)
            for series in result.get('series', []):
                match = next((item for item in saved if item['id'] == series['id']), None)
                if match:
                    series['history_points'] = match['history_points']
            exact = next((item for item in saved if item['scope'] == 'exact_area'), None)
            if exact:
                result['history_points'] = exact['history_points']
            self._send_json(result)
        except HTTPError as exc:
            message = exc.read(2000).decode("utf-8", errors="replace")
            self._send_json({"error": f"Copernicus retornou HTTP {exc.code}: {message}"}, status=502)
        except (OSError, json.JSONDecodeError, ValueError, URLError, TimeoutError) as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _handle_ndvi_map(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 2_000_000:
                raise ValueError("Tamanho do pedido inválido.")
            data = json.loads(self.rfile.read(size))
            geometry = extract_geometry(data.get("geojson"))
            acquisition_date = data.get("date")
            if not isinstance(acquisition_date, str):
                raise ValueError("Informe a data da cena.")

            validate_date(acquisition_date, "Data da cena")
            image, bbox = request_ndvi_map(geometry, acquisition_date)
            self._send_image(image, bbox)
        except HTTPError as exc:
            message = exc.read(2000).decode("utf-8", errors="replace")
            self._send_json({"error": f"Copernicus retornou HTTP {exc.code}: {message}"}, status=502)
        except (OSError, json.JSONDecodeError, ValueError, URLError, TimeoutError) as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:
            # A disconnected browser cannot receive a second error response.
            pass

    def _send_image(self, body, bbox):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Image-Bounds", json.dumps(bbox, separators=(",", ":")))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Monitoramento de lotes: servidor local independente.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-workers", action="store_true", help="Não iniciar o monitor automático ao abrir o servidor.")
    args = parser.parse_args()
    address = (args.host, args.port)
    # Migrate once before serving requests or starting background work.
    with storage.connect():
        pass
    server = ThreadingHTTPServer(address, Handler)
    if not args.no_workers:
        learning_cycle.start_worker()
    else:
        print("Monitor automático pausado (--no-workers).")
    print(f"PoC Alytha disponível em http://{address[0]}:{address[1]}")
    print("Servidor local; Ctrl+C para encerrar.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        learning_cycle.STOP.set()
        learning_cycle.WAKE.set()
        regional_scan.STOP.set()
        regional_scan.POOL.shutdown(wait=False,cancel_futures=True)
        server.server_close()


if __name__ == "__main__":
    main()
