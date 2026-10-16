"""Versioned, transactional SQLite schema initialization, once per database file."""
import sqlite3
import threading
from datetime import datetime, timezone

LOCK = threading.RLock()
READY = {}


def core(db):
    for sql in (
        'CREATE TABLE IF NOT EXISTS areas (id INTEGER PRIMARY KEY, name TEXT NOT NULL, municipality TEXT NOT NULL, crop TEXT NOT NULL, season TEXT NOT NULL, geometry TEXT NOT NULL, created_at TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS analyses (id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL REFERENCES areas(id), kind TEXT NOT NULL, parameters TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS source_snapshots (cache_key TEXT PRIMARY KEY, result TEXT NOT NULL, fetched_at TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS field_events (id INTEGER PRIMARY KEY, dataset_id TEXT NOT NULL, area_key TEXT NOT NULL, date_from TEXT NOT NULL, date_to TEXT NOT NULL, stage TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL)',
    ):
        db.execute(sql)


def provenance(db):
    for table in ('areas', 'field_events'):
        if 'provenance' not in {r[1] for r in db.execute('PRAGMA table_info(' + table + ')')}:
            db.execute("ALTER TABLE " + table + " ADD COLUMN provenance TEXT NOT NULL DEFAULT '{}'")


def learning(db):
    for sql in (
        'CREATE TABLE IF NOT EXISTS learning_plans (id TEXT PRIMARY KEY, area_key TEXT UNIQUE NOT NULL, config TEXT NOT NULL, next_due TEXT NOT NULL, lease_until TEXT)',
        'CREATE TABLE IF NOT EXISTS learning_runs (id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES learning_plans(id), created_at TEXT NOT NULL, status TEXT NOT NULL, result TEXT NOT NULL)',
        'CREATE INDEX IF NOT EXISTS learning_runs_plan ON learning_runs(plan_id, created_at)',
        'CREATE TABLE IF NOT EXISTS regional_base_versions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, folder TEXT NOT NULL, manifest TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS regional_ai_reviews (id TEXT PRIMARY KEY, base_id TEXT NOT NULL REFERENCES regional_base_versions(id), municipality_code TEXT NOT NULL, packet_path TEXT NOT NULL, signature TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt TEXT NOT NULL, lease_until TEXT, result TEXT NOT NULL)',
        'CREATE INDEX IF NOT EXISTS regional_ai_base ON regional_ai_reviews(base_id, status)',
        'CREATE TABLE IF NOT EXISTS visual_assets (id TEXT PRIMARY KEY, area_key TEXT NOT NULL, result TEXT NOT NULL)',
        'CREATE INDEX IF NOT EXISTS visual_assets_area ON visual_assets(area_key)',
        'CREATE TABLE IF NOT EXISTS visual_jobs (id TEXT PRIMARY KEY, base_id TEXT, area_key TEXT NOT NULL, municipality_code TEXT NOT NULL, dataset_id TEXT NOT NULL, cutoff TEXT NOT NULL, status TEXT NOT NULL, priority INTEGER NOT NULL, next_attempt TEXT NOT NULL, lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL)',
        'CREATE INDEX IF NOT EXISTS visual_jobs_queue ON visual_jobs(base_id,status,priority,next_attempt)',
    ):
        db.execute(sql)


def queue_indexes(db):
    db.execute('CREATE INDEX IF NOT EXISTS visual_jobs_lookup ON visual_jobs(area_key,dataset_id,cutoff,status)')
    db.execute('CREATE INDEX IF NOT EXISTS regional_ai_reuse ON regional_ai_reviews(municipality_code,signature,status)')


def analytical_queue(db):
    db.execute('''CREATE TABLE IF NOT EXISTS analytical_jobs (
        id TEXT PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL, tool TEXT NOT NULL,
        payload TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        lease_until TEXT, lease_token TEXT, worker_id TEXT, result TEXT, error TEXT)''')
    db.execute('CREATE INDEX IF NOT EXISTS analytical_jobs_pending ON analytical_jobs(status,created_at,lease_until)')


MIGRATIONS = ((1, 'core', core), (2, 'provenance', provenance),
              (3, 'learning_and_visual', learning), (4, 'queue_lookup_indexes', queue_indexes),
              (5, 'analytical_queue', analytical_queue))


def applied(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
    return list(db.execute('SELECT version,name FROM schema_migrations ORDER BY version')) if exists else []


def migrate(db):
    """Do not use executescript: it would commit before all migrations succeed."""
    if db.in_transaction:
        raise ValueError('Execute migrations antes de iniciar a transação de trabalho.')
    known = {version: name for version, name, _ in MIGRATIONS}
    for version, name in applied(db):
        if known.get(version) != name:
            raise ValueError('O banco possui migrations incompatíveis com esta versão da aplicação.')
    mode = db.execute('PRAGMA journal_mode').fetchone()[0]
    if mode.lower() != 'wal':
        mode = db.execute('PRAGMA journal_mode=WAL').fetchone()[0]
    if mode.lower() != 'wal':
        raise ValueError('Não foi possível habilitar WAL no banco SQLite local.')
    # Serialize competing application/CLI initializations across processes.
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)')
        current = dict(applied(db))
        if any(known.get(v) != name for v, name in current.items()):
            raise ValueError('Migrations incompatíveis com esta versão da aplicação.')
        for version, name, operation in MIGRATIONS:
            if version not in current:
                operation(db)
                db.execute('INSERT INTO schema_migrations VALUES(?,?,?)',
                           (version, name, datetime.now(timezone.utc).isoformat()))
    return {'journal_mode': mode, 'applied': [{'version': v, 'name': n} for v, n in applied(db)]}


def ensure(db, path):
    path = path.resolve()
    # Replacements at the same path must not inherit the former file's cache.
    identity = (path.stat().st_dev, path.stat().st_ino)
    with LOCK:
        if READY.get(path) == identity:
            return
        migrate(db)
        READY[path] = identity
