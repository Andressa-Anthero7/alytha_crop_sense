"""Local SQLite storage for areas and immutable analysis snapshots."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from .catalog_search import extract_geometry
from . import migrations

DB_PATH = Path(__file__).resolve().parents[1] / 'data' / 'monitoring.sqlite3'

@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        migrations.ensure(connection, DB_PATH)
        with connection:
            yield connection
    finally:
        connection.close()

def now():
    return datetime.now(timezone.utc).isoformat()

def area_record(row):
    result = dict(row)
    result['geometry'] = json.loads(result['geometry'])
    result['provenance'] = json.loads(result['provenance'])
    return result

def list_areas():
    with connect() as db:
        return [area_record(row) for row in db.execute('SELECT * FROM areas ORDER BY id DESC')]

def get_area(area_id):
    with connect() as db:
        row = db.execute('SELECT * FROM areas WHERE id=?', (area_id,)).fetchone()
    if row is None:
        raise ValueError('Área salva não encontrada.')
    return area_record(row)

def save_area(data):
    if not isinstance(data, dict):
        raise ValueError('Informe um cadastro de área válido.')
    values = []
    for key, label in [('name','Nome'),('municipality','Município'),('crop','Cultura'),('season','Safra')]:
        value = data.get(key, '')
        if not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError(f'{label} é obrigatório e deve ter até 200 caracteres.')
        values.append(value.strip())
    geometry = extract_geometry(data.get('geojson'))
    with connect() as db:
        provenance = data.get('provenance', {})
        if not isinstance(provenance, dict) or len(json.dumps(provenance)) > 10000:
            raise ValueError('Metadados de origem inválidos.')
        cursor = db.execute('INSERT INTO areas(name,municipality,crop,season,geometry,created_at,provenance) VALUES(?,?,?,?,?,?,?)',
                            (*values, json.dumps(geometry), now(), json.dumps(provenance)))
        area_id = cursor.lastrowid
    return get_area(area_id)

def validate_analysis_area(data, geometry):
    area_id = data.get('area_id')
    if area_id is None:
        return None
    if isinstance(area_id, bool) or not isinstance(area_id, int):
        raise ValueError('Identificador de área inválido.')
    if get_area(area_id)['geometry'] != geometry:
        raise ValueError('A geometria foi alterada. Salve a nova área antes de registrar a análise.')
    return area_id

def save_analysis(area_id, kind, parameters, result):
    if area_id is None:
        return
    with connect() as db:
        db.execute('INSERT INTO analyses(area_id,kind,parameters,result,created_at) VALUES(?,?,?,?,?)',
                   (area_id, kind, json.dumps(parameters), json.dumps(result), now()))

def history(area_id):
    get_area(area_id)
    with connect() as db:
        records = []
        for row in db.execute('SELECT * FROM analyses WHERE area_id=? ORDER BY id DESC', (area_id,)):
            record = dict(row)
            record['parameters'] = json.loads(record['parameters'])
            record['result'] = json.loads(record['result'])
            record['source'] = 'Copernicus Sentinel-2 L2A'
            records.append(record)
        return records

def source_snapshot(key, result=None):
    with connect() as db:
        if result is not None:
            db.execute('INSERT OR REPLACE INTO source_snapshots VALUES(?,?,?)', (key, json.dumps(result), now()))
        row = db.execute('SELECT * FROM source_snapshots WHERE cache_key=?', (key,)).fetchone()
    return {'result': json.loads(row['result']), 'fetched_at': row['fetched_at']} if row else None
