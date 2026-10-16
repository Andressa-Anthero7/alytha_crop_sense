"""Read-only inventory of local evidence. Never starts workers or downloads data."""
import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

from . import storage
from .catalog_search import extract_geometry

DATA_ROOT = Path(__file__).resolve().parents[1] / 'data'
VERSION = 1
LIMIT = 100


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def request_scope(data):
    result = {key: data.get(key) for key in ('dataset_id', 'municipality_code', 'state_code', 'map_date')}
    for key, pattern in [('dataset_id', r'[a-f0-9]{64}'), ('municipality_code', r'\d{7}'), ('state_code', r'\d{2}')]:
        value = result[key]
        if value is not None and (not isinstance(value, str) or not re.fullmatch(pattern, value)):
            raise ValueError('Identificador inválido no inventário local: ' + key)
    if result['municipality_code'] and result['state_code'] and not result['municipality_code'].startswith(result['state_code']):
        raise ValueError('O município não pertence ao estado selecionado.')
    if result['map_date'] is not None:
        try:
            value = result['map_date']
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError('Data inválida no inventário local.') from None
    result['area_key'] = fingerprint(extract_geometry(data['area_geojson'])) if data.get('area_geojson') else None
    return result


def evidence(identifier, kind, area_key, period, resource, quality, data, source='CropSense · arquivo local'):
    """Versioned envelope shared by the inventory tools and their consumers."""
    return {
        'id': identifier, 'contract_version': VERSION, 'kind': kind,
        'source': source, 'scope': 'mesmo recorte' if area_key else 'arquivo sem vínculo de área confirmado',
        'area_key': area_key, 'period': period,
        'provenance': {'resource': resource, 'method': 'read_only_local_inventory', 'version': VERSION},
        'quality': quality, 'data': data,
    }


def _database(scope):
    """Project small summaries instead of loading full historical time series."""
    if not storage.DB_PATH.exists():
        return [], {}, ['Banco local ainda não existe.'], False
    histories, areas = [], {}
    try:
        with closing(sqlite3.connect(storage.DB_PATH.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'source_snapshots' not in tables:
                return [], {}, ['Banco sem tabela de históricos.'], False
            clauses = ["cache_key >= 'history:'", "cache_key < 'history;'", 'json_valid(result)']
            params = []
            for field, value in [('municipality_code', scope['municipality_code']), ('area_key', scope['area_key'])]:
                if value:
                    clauses.append("json_extract(result,'$.parameters." + field + "')=?")
                    params.append(value)
            if scope['state_code']:
                clauses.append("json_extract(result,'$.parameters.municipality_code') LIKE ?")
                params.append(scope['state_code'] + '%')
            if scope['dataset_id']:
                clauses.append('cache_key=?')
                params.append('history:' + scope['dataset_id'])
            where = ' AND '.join(clauses)
            total = db.execute('SELECT count(*) FROM source_snapshots WHERE ' + where, params).fetchone()[0]
            areas['area_keys'] = [r[0] for r in db.execute(
                "SELECT DISTINCT json_extract(result,'$.parameters.area_key') FROM source_snapshots WHERE " + where, params) if r[0]]
            # A cutoff constrains observations, not the later snapshot's job status.
            projection = """SELECT substr(cache_key,9) AS id, fetched_at,
                json_extract(result,'$.parameters.area_key') AS area_key,
                json_extract(result,'$.parameters.municipality_code') AS municipality_code,
                json_extract(result,'$.status') AS status,
                json_extract(result,'$.parameters.as_of') AS as_of,
                json_extract(result,'$.source') AS source,
                (SELECT count(*) FROM json_each(json_extract(result,'$.points'))
                 WHERE json_extract(value,'$.date') <= ?) AS observations,
                (SELECT min(json_extract(value,'$.date')) FROM json_each(json_extract(result,'$.points'))
                 WHERE json_extract(value,'$.date') <= ?) AS first_date,
                (SELECT max(json_extract(value,'$.date')) FROM json_each(json_extract(result,'$.points'))
                 WHERE json_extract(value,'$.date') <= ?) AS last_date
                FROM source_snapshots WHERE """ + where + ' ORDER BY cache_key LIMIT ?'
            cutoff = scope['map_date'] or '9999-12-31'
            for r in db.execute(projection, [cutoff, cutoff, cutoff, *params, LIMIT]):
                histories.append(dict(r))
            if 'areas' in tables and not any(scope[k] for k in ('municipality_code', 'state_code', 'dataset_id', 'area_key')):
                areas['saved_areas'] = db.execute('SELECT count(*) FROM areas').fetchone()[0]
            areas['matching_histories'] = total
    except sqlite3.Error:
        return [], {}, ['Banco local indisponível ou ocupado; históricos não puderam ser inventariados.'], False
    return histories, areas, [], True


def _relative_file(value):
    if not isinstance(value, str):
        return None
    path = Path(value).resolve()
    try:
        path.relative_to(DATA_ROOT.resolve())
    except ValueError:
        return None
    return path


def _raster(path):
    result = {'resource': path.relative_to(DATA_ROOT).as_posix(), 'available': True}
    try:
        import rasterio
        with rasterio.open(path) as ds:
            result.update(band_count=ds.count, native_size=[ds.width, ds.height],
                          crs=str(ds.crs), pixel_size=[abs(ds.transform.a), abs(ds.transform.e)],
                          pixel_units='crs_units', integrity='header_readable')
    except ImportError:
        result.update(integrity='not_inspected', note='rasterio indisponível para conferir o cabeçalho.')
    except Exception:
        result.update(integrity='unreadable', available=False)
    return result


def inventory(data=None):
    scope = request_scope(data or {})
    histories, counts, issues, db_available = _database(scope)
    if scope['dataset_id'] and not histories and db_available:
        raise ValueError('Histórico não encontrado no escopo selecionado.')
    area_keys = set(counts.pop('area_keys', []))
    if scope['area_key']:
        area_keys.add(scope['area_key'])
    scoped = any(scope[k] for k in ('dataset_id', 'municipality_code', 'state_code', 'area_key'))
    assets, raster_links = [], {}
    for p in sorted((DATA_ROOT / 'outputs/vision/assets').glob('*.json')):
        try:
            asset = json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(asset, dict) or not isinstance(asset.get('period'), dict):
                raise ValueError
            if scoped and asset.get('area_key') not in area_keys:
                continue
            period = asset['period']
            if not all(isinstance(period.get(k), str) and date.fromisoformat(period[k]).isoformat() == period[k] for k in ('from', 'to')) or period['from'] > period['to']:
                raise ValueError
            if scope['map_date'] and period['to'] > scope['map_date']:
                continue
            preview = _relative_file(asset.get('path'))
            source = _relative_file(asset.get('source_path'))
            if source:
                raster_links.setdefault(source, []).append(asset)
            exists = bool(preview and preview.is_file())
            integrity = 'missing'
            if exists:
                integrity = 'unverified'
                if asset.get('sha256'):
                    digest = hashlib.sha256(preview.read_bytes()).hexdigest()
                    integrity = 'verified' if digest == asset['sha256'] else 'hash_mismatch'
            assets.append(evidence(
                'local_image_' + p.stem, 'image_preview', asset.get('area_key'), period,
                p.relative_to(DATA_ROOT).as_posix(),
                {'available': exists and integrity != 'hash_mismatch', 'integrity': integrity,
                 'valid_fraction': asset.get('valid_fraction'), 'valid_pixels': asset.get('valid_pixels')},
                {'kind': asset.get('kind'), 'native_size': asset.get('native_size'),
                 'source_resolution_m': asset.get('source_resolution_m'),
                 'preview_resource': preview.relative_to(DATA_ROOT).as_posix() if preview else None,
                 'source_raster_available': bool(source and source.is_file()),
                 'render_version': asset.get('render_version')}, asset.get('source', 'Arquivo local')))
        except (ValueError, TypeError, OSError, KeyError):
            issues.append('Metadado de imagem inválido ou ilegível: ' + p.name)
    rasters = []
    paths = set((DATA_ROOT / 'rasters').rglob('*.tif')) | set((DATA_ROOT / 'rasters').rglob('*.tiff'))
    for path in sorted(paths):
        path = path.resolve()
        if _relative_file(str(path)) is None:
            continue
        linked = raster_links.get(path, [])
        if (scoped or scope['map_date']) and not linked:
            continue
        r = _raster(path)
        rasters.append(evidence('local_raster_' + fingerprint(r['resource']), 'raster',
            linked[0].get('area_key') if linked else None,
            linked[0]['period'] if linked else None, r.pop('resource'),
            {'available': r.pop('available'), 'integrity': r.pop('integrity')},
            {**r, 'linked_image_ids': [a.get('id') for a in linked],
             'band_semantics': 'not_verified_by_inventory'}))
    history_evidence = [evidence('local_history_' + h['id'], 'ndvi_history', h['area_key'],
        {'from': h['first_date'], 'to': h['last_date']}, 'sqlite:history:' + h['id'],
        {'available': True, 'observations': h['observations'], 'pixel_quality': 'not_evaluated'},
        {'dataset_id': h['id'], 'municipality_code': h['municipality_code'],
         'snapshot_status': h['status'], 'snapshot_fetched_at': h['fetched_at'],
         'requested_as_of': h['as_of'], 'raw_bands_available': 'not_implied_by_time_series'},
        h['source'] or 'Sentinel-2 L2A · série local salva') for h in histories]
    usable = [a for a in assets if a['quality']['available']]
    limitations = [
        'Inventário somente local; nenhuma consulta externa ou trabalho de coleta foi iniciado.',
        'Série NDVI, prévia colorida e raster de bandas são recursos distintos.',
        'Cores do mapa NDVI não identificam palhada; direção vegetal não comprova trajeto de plantadeira.',
        'Contagem de observações não comprova cobertura válida nem suficiência para análise agronômica.',
    ]
    if counts.get('matching_histories', 0) > LIMIT:
        limitations.append(f'Lista limitada a {LIMIT} históricos; a contagem total e o vínculo de imagens consideram todos os históricos correspondentes.')
    if scope['map_date']:
        limitations.append('Data de corte filtra observações e períodos; o estado do snapshot é o atualmente salvo, não seu estado naquela data.')
    if scoped:
        limitations.append('Arquivos sem vínculo de área verificável não entram na seleção; ausência aqui não prova ausência no disco.')
    if not any(a['data']['kind'] == 'true_color' for a in usable):
        limitations.append('Nenhuma prévia em cor natural disponível no escopo inventariado.')
    return {'version': VERSION, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'local_read_only', 'scope': scope,
        'summary': {**counts, 'database_available': db_available, 'listed_histories': len(histories),
                    'histories_with_observations': sum(h['observations'] > 0 for h in histories),
                    'image_metadata': len(assets), 'available_previews': len(usable),
                    'ndvi_previews': sum(a['data']['kind'] == 'ndvi' for a in usable),
                    'true_color_previews': sum(a['data']['kind'] == 'true_color' for a in usable),
                    'raster_files': len(rasters)},
        'evidence': history_evidence + assets + rasters, 'issues': issues, 'limitations': limitations}


def requested(prompt):
    from .assistant_intents import normalize
    text = normalize(prompt)
    if re.search(r'\b(?:nao|nunca)\b', text):
        return False
    return bool(re.search(r'\binventario\b|\b(?:quais|que) (?:dados|imagens|arquivos|bandas|periodos|historicos)\b.*\b(?:temos|salvos|locais|disponiveis)\b|\bo que temos\b.*\b(?:salvo|local|imagem|imagens|dados|base)\b', text))


def reply(data):
    result = inventory(data)
    s = result['summary']
    place = 'da área selecionada' if result['scope']['area_key'] or result['scope']['dataset_id'] else 'da localidade selecionada' if result['scope']['municipality_code'] or result['scope']['state_code'] else 'do sistema'
    history = (f"{s['listed_histories']} históricos listados ({s['histories_with_observations']} com observações até o corte)"
               if s['database_available'] else 'históricos ainda não conferidos porque o banco está indisponível')
    answer = (f"No inventário local {place}, encontrei {history}, {s['raster_files']} arquivos raster "
              f"e {s['available_previews']} prévias disponíveis: {s['ndvi_previews']} NDVI e {s['true_color_previews']} em cor natural. "
              'Uma série salva não significa que suas bandas originais estejam no disco. Não consultei o Sentinel nem outro serviço externo.')
    return {'answer': answer, 'evidence_ids': ['local_inventory'],
        'limitations': result['issues'] + result['limitations'],
        'action': {'kind': 'none', 'class_ids': []}, 'provider': 'CropSense',
        'model': 'local-inventory-v1', 'intent': 'local_inventory',
        'sources': [{'id': 'local_inventory', 'source': 'CropSense · inventário local verificado'}],
        'inventory': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-id')
    parser.add_argument('--municipality-code')
    parser.add_argument('--state-code')
    parser.add_argument('--map-date')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = inventory(vars(args))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'summary': result['summary'], 'issues': result['issues']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
