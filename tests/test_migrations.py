"""Legacy upgrade, atomicity and reader/writer concurrency on real SQLite files."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from app import migrations, storage


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'test.sqlite3'
        self.addCleanup(self.temp.cleanup)
        p=patch.object(storage,'DB_PATH',self.path);p.start();self.addCleanup(p.stop)

    def test_new_database_has_all_versions_wal_and_foreign_keys(self):
        with storage.connect() as db:
            self.assertEqual([r[0] for r in migrations.applied(db)],[1,2,3,4,5])
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO learning_runs VALUES('r','missing','today','ready','{}')")

    def test_legacy_upgrade_preserves_rows_and_is_idempotent(self):
        with closing(sqlite3.connect(self.path)) as db:
            migrations.core(db)
            db.execute("INSERT INTO areas VALUES(1,'A','Sorriso','soja','2026','{}','today')")
            db.commit()
            migrations.migrate(db)
            first=list(db.execute('SELECT * FROM schema_migrations'))
            self.assertEqual(db.execute('SELECT name,provenance FROM areas').fetchone(),('A','{}'))
            migrations.migrate(db)
            self.assertEqual(list(db.execute('SELECT * FROM schema_migrations')),first)

    def test_rollback_does_not_mark_or_partially_apply_failed_migration(self):
        with storage.connect() as db:pass
        def failing(db):
            db.execute('CREATE TABLE must_rollback(id INTEGER)')
            raise RuntimeError('failure')
        with closing(sqlite3.connect(self.path)) as db:
            with patch.object(migrations,'MIGRATIONS',migrations.MIGRATIONS+((6,'failure',failing),)):
                with self.assertRaises(RuntimeError):migrations.migrate(db)
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='must_rollback'").fetchone())
            self.assertEqual(db.execute('SELECT max(version) FROM schema_migrations').fetchone()[0],5)

    def test_unknown_migration_is_rejected(self):
        with storage.connect() as db:
            db.execute("INSERT INTO schema_migrations VALUES(999,'future','today')")
        with closing(sqlite3.connect(self.path)) as db:
            with self.assertRaisesRegex(ValueError,'incompatíveis'):migrations.migrate(db)

    def test_reader_continues_while_another_connection_writes(self):
        storage.source_snapshot('existing',{'value':1})
        with storage.connect() as writer:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute("UPDATE source_snapshots SET result='{}' WHERE cache_key='existing'")
            # The read must return the last committed value without waiting for the writer.
            self.assertEqual(storage.source_snapshot('existing')['result'],{'value':1})
            with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=.1)) as reader:
                self.assertEqual(reader.execute("SELECT result FROM source_snapshots WHERE cache_key='existing'").fetchone()[0],'{"value": 1}')

    def test_normal_connections_do_not_execute_schema_ddl(self):
        with storage.connect():pass
        original=sqlite3.connect
        statements=[]
        def traced(*args,**kwargs):
            db=original(*args,**kwargs);db.set_trace_callback(statements.append);return db
        with patch.object(storage.sqlite3,'connect',side_effect=traced):
            storage.list_areas()
        self.assertFalse(any(s.startswith(('CREATE','ALTER','BEGIN')) for s in statements),statements)

    def test_failed_initialization_closes_connection(self):
        with patch.object(migrations,'ensure',side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                with storage.connect():pass
        self.path.unlink()  # On Windows this fails if the connection leaked.

    def test_replaced_database_is_migrated_again(self):
        with storage.connect():pass
        self.path.unlink()
        with storage.connect() as db:
            self.assertEqual(len(migrations.applied(db)),5)

    def test_visual_reuse_lookup_uses_index(self):
        with storage.connect() as db:
            rows=db.execute("EXPLAIN QUERY PLAN SELECT id,result FROM visual_jobs WHERE area_key=? AND dataset_id=? AND cutoff=? AND status='ready' ORDER BY rowid DESC LIMIT 1",('area','dataset','2026-10-15')).fetchall()
            self.assertTrue(any('visual_jobs_lookup' in r[3] for r in rows))


if __name__=='__main__':unittest.main()
