import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from app import backup, storage


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'data';self.data.mkdir()
        p=patch.object(storage,'DB_PATH',self.data/'monitoring.sqlite3');p.start();self.addCleanup(p.stop)
        storage.source_snapshot('known',{'value':42})
        folder=self.data/'rasters';folder.mkdir();(folder/'raster.tif').write_bytes(b'original bytes')
        (self.data/'outputs').mkdir();(self.data/'outputs'/'regenerable.csv').write_text('data')
        self.archive=self.root/'backup.zip'

    def test_core_database_and_original_artifacts_restore_with_matching_counts_and_hashes(self):
        result=backup.create(self.archive,data_root=self.data)
        restored=backup.restore(self.archive,self.root/'restored')
        self.assertEqual(restored['database_rows'],result['database_rows'])
        self.assertEqual((self.root/'restored/data/rasters/raster.tif').read_bytes(),b'original bytes')
        self.assertFalse((self.root/'restored/data/outputs/regenerable.csv').exists())
        self.assertEqual(restored['verified_files'],2)
        with self.assertRaises(ValueError):backup.restore(self.archive,self.root/'restored')

    def test_full_backup_includes_exports_and_live_database_is_not_changed(self):
        before=storage.source_snapshot('known')
        backup.create(self.archive,full=True,data_root=self.data)
        backup.restore(self.archive,self.root/'full')
        self.assertTrue((self.root/'full/data/outputs/regenerable.csv').exists())
        self.assertEqual(before,storage.source_snapshot('known'))

    def test_bad_hash_and_path_traversal_are_rejected_without_writing_outside_target(self):
        for name in ('data/../../escape','data/ok'):
            path=self.root/(name.replace('/','_')+'.zip')
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('manifest.json',json.dumps({'files':{name:{'sha256':'invalid','bytes':1},
                    'data/monitoring.sqlite3':{'sha256':'invalid','bytes':1}},'database_rows':{}}))
                archive.writestr(name,'x')
            with self.assertRaises(ValueError):backup.restore(path,self.root/(path.stem+'-restore'))
        self.assertFalse((self.root/'escape').exists())


if __name__=='__main__':unittest.main()
