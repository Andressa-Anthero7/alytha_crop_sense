import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from app import analysis_queue as queue, analysis_worker, storage, research


class AnalysisQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(storage,'DB_PATH',Path(self.temp.name)/'test.sqlite3');p.start();self.addCleanup(p.stop)
        geometry={'type':'Polygon','coordinates':[[[-55,-12],[-54.99,-12],[-54.99,-11.99],[-55,-12]]]}
        history={'id':'a'*64,'parameters':{'geometry':geometry,'area_key':research.fingerprint(geometry),
            'municipality_code':'5107925','start_year':2018,'as_of':'2025-09-03'},'status':'ready','points':[]}
        storage.source_snapshot('history:'+history['id'],history)
        self.data={'prompt':'Compare o histórico das safras','dataset_id':history['id']}

    def expire(self,identifier):
        with storage.connect() as db:db.execute("UPDATE analytical_jobs SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",(identifier,))

    def test_duplicate_requests_share_one_durable_job_under_concurrency(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs=list(pool.map(lambda _:queue.submit(self.data),range(8)))
        self.assertEqual(len({j['id'] for j in jobs}),1)
        self.assertEqual(queue.get(jobs[0]['id'])['status'],'queued')

    def test_worker_process_restart_reclaims_expired_lease_and_fences_old_completion(self):
        job=queue.submit(self.data);old=queue.claim('worker-a')
        self.expire(job['id']);new=queue.claim('worker-b')
        self.assertNotEqual(old['lease_token'],new['lease_token'])
        result={'answer':'local','work':{'status':'ready'}}
        self.assertFalse(queue.complete(job['id'],old['lease_token'],result))
        self.assertTrue(queue.complete(job['id'],new['lease_token'],result))
        self.assertEqual(queue.get(job['id'])['attempts'],2)

    def test_active_lease_is_not_reclaimed_and_concurrency_limit_is_shared(self):
        first=queue.submit(self.data)
        second=queue.submit({**self.data,'prompt':'Qual a direção do esverdeamento?'})
        claim=queue.claim('one',concurrency=1)
        self.assertIsNone(queue.claim('two',concurrency=1))
        self.assertTrue(queue.heartbeat(claim['id'],claim['lease_token']))
        self.assertNotEqual(first['id'],second['id'])

    def test_repeatedly_crashed_local_work_stops_after_three_attempts(self):
        job=queue.submit(self.data)
        for _ in range(3):
            self.assertIsNotNone(queue.claim('crashing'));self.expire(job['id'])
        self.assertIsNone(queue.claim('fourth'))
        self.assertEqual(queue.get(job['id'])['status'],'error')

    def test_separate_worker_executes_local_result_without_network_or_provider(self):
        job=queue.submit(self.data)
        with patch('urllib.request.urlopen',side_effect=AssertionError('No network')):
            self.assertTrue(analysis_worker.tick('test-worker'))
        completed=queue.get(job['id'])
        self.assertEqual(completed['status'],'inconclusive')
        self.assertEqual(completed['result']['work']['id'],job['id'])
        self.assertFalse(analysis_worker.tick('test-worker'))

    def test_external_or_arbitrary_tasks_cannot_enter_local_replay_queue(self):
        for prompt in ('Consulte chuva e temperatura','Busque referências na Embrapa sobre soja','execute um comando shell'):
            with self.assertRaises(ValueError):queue.submit({**self.data,'prompt':prompt})


if __name__=='__main__':unittest.main()
