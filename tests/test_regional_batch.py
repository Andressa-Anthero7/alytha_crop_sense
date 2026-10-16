import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import regional_batch as batch


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.output=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def bootstrap(self):
        def roster(path):
            code=path.split('/estados/')[1][:2]
            return [{'id':int(code+'00001'),'nome':'Fixture'}]
        def api(base,path,payload=None):return {'id':payload['code']+'a'*62,'status':'loading'}
        with patch.object(batch,'backup') as backup,patch.object(batch,'fetch_ibge',side_effect=roster),patch.object(batch,'api',side_effect=api) as request:
            result=batch.start('http://localhost:8765',self.output)
            self.assertEqual(request.call_count,4);backup.assert_called_once()
        return result

    def test_start_saves_rosters_and_preserves_existing_cohort(self):
        result=self.bootstrap()
        self.assertEqual(result['total_municipalities'],4)
        self.assertEqual({s['uf'] for s in result['states']},{'DF','GO','MS','MT'})
        with patch.object(batch,'api') as api,patch.object(batch,'backup') as backup:
            self.assertEqual(batch.start('http://localhost:8765',self.output)['created_at'],result['created_at'])
            api.assert_not_called();backup.assert_not_called()

    def test_partial_results_are_not_reported_as_complete(self):
        self.bootstrap()
        job={'status':'partial','processed':1,'total':1,'cities':[{'code':'5300108','name':'Fixture','status':'partial'}]}
        with patch.object(batch,'api',return_value=job),patch.object(batch,'backup') as backup:
            result=batch.refresh(self.output)
            self.assertEqual(result['status'],'finished_with_pending')
            self.assertEqual(result['processed'],4);backup.assert_called_once()
            batch.refresh(self.output);backup.assert_called_once()

    def test_connection_failure_keeps_collection_pending(self):
        self.bootstrap()
        with patch.object(batch,'api',side_effect=TimeoutError()),patch.object(batch,'backup') as backup:
            result=batch.refresh(self.output)
        self.assertEqual(result['status'],'running');backup.assert_not_called()
        self.assertTrue(all(s.get('monitor_error') for s in result['states']))

    def test_dashboard_reads_live_child_progress_and_keeps_queue_totals(self):
        path=self.output/'fixture.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE source_snapshots(cache_key TEXT,result TEXT)')
            job={'status':'loading','cities':[{'status':'ready','name':'Pronto','code':'5200050'},{'status':'loading','name':'Atual','code':'5200100','phase':'satellite','activity':{'id':'child','processed':1}}]}
            db.execute('INSERT INTO source_snapshots VALUES(?,?)',('regional-scan:v1:go',json.dumps(job)))
            db.execute('INSERT INTO source_snapshots VALUES(?,?)',('municipal-activity:child',json.dumps({'status':'loading','processed':7,'total':10,'updated_at':'2026-10-13T21:00:00+00:00'})))
            db.execute('INSERT INTO source_snapshots VALUES(?,?)',('regional-scan:v1:mt',json.dumps({'status':'loading','cities':[]})))
            db.commit()
        manifest={'created_at':'2026-10-13','total_municipalities':388,'states':[{'job_id':'go','uf':'GO','code':'52','municipalities':246},{'job_id':'mt','uf':'MT','code':'51','municipalities':142}]}
        result=batch.dashboard(manifest,path)
        self.assertEqual(result['processed'],1)
        self.assertEqual(result['states'][0]['active'][0]['activity']['processed'],7)
        self.assertEqual(result['states'][0]['active'][0]['progress_at'],'2026-10-13T21:00:00+00:00')
        self.assertEqual(result['states'][1]['status'],'queued')
        self.assertEqual(result['states'][1]['total'],142)
        self.assertEqual(result['status'],'running')
        self.assertTrue(any(city['status']=='queued' and city['uf']=='MT' for city in result['municipalities']))

    def test_training_coverage_uses_saved_models_even_for_partial_cities(self):
        path=self.output/'training.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE source_snapshots(cache_key TEXT,result TEXT)')
            job={'status':'partial','cities':[{'status':'partial','code':'5200050','name':'Com modelo'},
                                            {'status':'ready','code':'5200100','name':'Sem modelo'}]}
            learned={'areas':16,'profiles':[{'id':1},{'id':2}],'trained_at':'2026-10-14',
                     'period':{'to':'2026-10-13'},'collection_complete':True}
            db.executemany('INSERT INTO source_snapshots VALUES(?,?)',[
                ('regional-scan:v1:go',json.dumps(job)),('ml:satellite:v1:5200050',json.dumps(learned))])
            db.commit()
        manifest={'created_at':'2026-10-13','total_municipalities':2,
                  'states':[{'job_id':'go','uf':'GO','code':'52','municipalities':2}]}
        result=batch.dashboard(manifest,path,roster_dir=self.output)
        self.assertEqual(result['training'],{'municipalities':1,'areas':16})
        self.assertEqual(result['municipalities'][0]['status'],'partial')
        self.assertEqual(result['municipalities'][0]['training']['profiles'],2)
        self.assertEqual(result['municipalities'][0]['training']['period']['to'],'2026-10-13')
        self.assertEqual(result['municipalities'][1]['training']['status'],'pending')


if __name__=='__main__':unittest.main()
