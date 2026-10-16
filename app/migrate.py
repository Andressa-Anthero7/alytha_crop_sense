"""Inspect or apply the application's versioned SQLite migrations."""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from . import migrations, storage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'up'], nargs='?', default='status')
    parser.add_argument('--database', type=Path, default=storage.DB_PATH)
    args = parser.parse_args()
    path = args.database.resolve()
    if args.command == 'status' and not path.exists():
        print(json.dumps({'exists': False, 'applied': [], 'pending': [m[0] for m in migrations.MIGRATIONS]}))
        return
    if args.command == 'up':
        path.parent.mkdir(parents=True, exist_ok=True)
    uri = path.as_uri() + ('?mode=ro' if args.command == 'status' else '?mode=rwc')
    with closing(sqlite3.connect(uri, uri=True, timeout=15)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        if args.command == 'up':
            result = migrations.migrate(db)
        else:
            rows = migrations.applied(db)
            result = {'exists': True, 'applied': [{'version': v, 'name': n} for v, n in rows],
                      'pending': [v for v, _, _ in migrations.MIGRATIONS if v not in dict(rows)],
                      'journal_mode': db.execute('PRAGMA journal_mode').fetchone()[0]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
