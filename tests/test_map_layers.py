"""Background crop maps keep one resumable job per validated request."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import map_layers, storage


class MapLayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = patch.object(storage, 'DB_PATH', Path(self.temp.name)/'test.sqlite3')
        self.db.start()
        self.submit = patch.object(map_layers.POOL, 'submit')
        self.worker = self.submit.start()
        self.worker.return_value.cancel.return_value=False
        self.params = {'bounds':[-55.2,-12.5,-55.19,-12.49],'year':2025,'class_id':39}

    def tearDown(self):
        map_layers.RUNNING.clear()
        map_layers.FUTURES.clear();map_layers.LATEST.clear()
        self.submit.stop()
        self.db.stop()
        self.temp.cleanup()

    def finish(self, job, result=None, error=None):
        options = {'side_effect':error} if error else {'return_value':result}
        with patch.object(map_layers.data_sources, 'mapbiomas', **options):
            map_layers._build(job['id'], job['parameters'])
        return map_layers.get(job['id'])

    def test_loading_deduplicates_and_completed_map_is_reused(self):
        first = map_layers.start(self.params)
        self.assertEqual(first['status'], 'loading')
        self.assertEqual(map_layers.start({**self.params,'unused':True}), first)
        self.assertEqual(map_layers.get(first['id']), first)
        self.worker.assert_called_once()

        result = {'type':'FeatureCollection','features':[]}
        ready = self.finish(first, result)
        self.assertEqual(ready['result'], result)
        self.assertEqual(ready['status'], 'ready')
        self.assertEqual(map_layers.start(self.params), ready)
        self.worker.assert_called_once()

    def test_full_state_views_share_one_job_but_detail_stays_separate(self):
        storage.source_snapshot('ibge-boundary:v1:states:52',{'bounds':[-51,-19,-46,-12]})
        first=map_layers.start({'bounds':[-60,-25,-40,-8],'state_code':'52','class_id':39})
        second=map_layers.start({'bounds':[-65,-30,-35,-5],'state_code':'52','class_id':39})
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(first['parameters']['bounds'],[-51,-19,-46,-12])
        self.assertEqual(self.worker.call_count,1)
        detail=map_layers.start({'bounds':[-50,-18,-49,-17],'state_code':'52','class_id':39})
        self.assertNotEqual(first['id'],detail['id'])
        self.assertNotIn('full_region',detail['parameters'])

    def test_existing_complete_state_result_is_promoted_without_worker(self):
        storage.source_snapshot('ibge-boundary:v1:states:52',{'bounds':[-51,-19,-46,-12]})
        prepared={'type':'FeatureCollection','features':[],'candidate_count':1000,'year':2025}
        storage.source_snapshot('crop-map:v1:legacy-complete',{'status':'ready',
            'parameters':{'bounds':[-60,-25,-40,-8],'state_code':'52','year':2025,'class_id':39},'result':prepared})
        job=map_layers.start({'bounds':[-65,-30,-35,-5],'state_code':'52','class_id':39})
        self.assertEqual(job['status'],'ready')
        self.assertEqual(job['result'],prepared)
        self.worker.assert_not_called()

    def test_partial_state_cache_never_becomes_a_complete_state(self):
        storage.source_snapshot('ibge-boundary:v1:states:52',{'bounds':[-51,-19,-46,-12]})
        storage.source_snapshot('crop-map:v1:partial',{'status':'ready',
            'parameters':{'bounds':[-50,-18,-49,-17],'state_code':'52','year':2025,'class_id':39},
            'result':{'features':[],'candidate_count':1000}})
        job=map_layers.start({'bounds':[-60,-25,-40,-8],'state_code':'52','class_id':39})
        self.assertEqual(job['status'],'loading')
        self.worker.assert_called_once()

    def test_state_scope_has_separate_cache_and_validates_codes(self):
        ordinary=map_layers.start(self.params)
        state=map_layers.start({**self.params,'state_code':'52'})
        self.assertNotEqual(ordinary['id'],state['id'])
        self.assertEqual(state['parameters']['state_code'],'52')
        for code in ('99',52,True,'../../'):
            with self.assertRaises(ValueError):map_layers.start({**self.params,'state_code':code})
        with self.assertRaises(ValueError):map_layers.start({**self.params,'state_code':'52','municipality_code':'5107925'})

    def test_region_viewport_padding_is_clamped_before_raster_work(self):
        job=map_layers.start({**self.params,'state_code':'52','bounds':[-90,-40,-20,12]})
        self.assertEqual(job['parameters']['bounds'],[-75,-35,-30,6])
        with self.assertRaises(ValueError):map_layers.start({**self.params,'state_code':'52','bounds':[10,20,15,25]})
        self.assertEqual(self.worker.call_count,1)

    def test_interrupted_work_resumes_after_restart_once(self):
        job = map_layers.start(self.params)
        map_layers.RUNNING.clear()
        resumed = map_layers.get(job['id'])
        self.assertEqual(resumed['id'], job['id'])
        self.assertEqual(resumed['status'], 'loading')
        map_layers.get(job['id'])
        self.assertEqual(self.worker.call_count, 2)

    def test_remote_timeout_is_sanitized_and_next_request_retries(self):
        job = map_layers.start(self.params)
        failed = self.finish(job, error=TimeoutError('private-source-details'))
        self.assertEqual(failed['status'], 'error')
        self.assertNotIn('private-source-details', failed['error'])
        self.assertEqual(map_layers.get(job['id']), failed)
        self.worker.assert_called_once()
        self.assertEqual(map_layers.start(self.params)['id'], job['id'])
        self.assertEqual(self.worker.call_count, 2)

    def test_invalid_requests_never_queue_and_backlog_is_bounded(self):
        for data in (None, {}, {**self.params,'year':True}, {**self.params,'municipality_code':'bad'}, {**self.params,'bounds':[float('nan'),0,1,2]}):
            with self.assertRaises(ValueError): map_layers.start(data)
        self.worker.assert_not_called()
        for year in range(2010,2010+map_layers.MAX_PENDING):
            map_layers.start({**self.params,'year':year})
        waiting=map_layers.start(self.params)
        self.assertEqual(waiting['status'],'loading')
        self.assertEqual(waiting['phase'],'waiting')
        self.assertEqual(self.worker.call_count, map_layers.MAX_PENDING)

    def test_latest_browser_view_cancels_queued_previous_view_without_resuming_it(self):
        from concurrent.futures import Future
        self.worker.side_effect=lambda *args:Future()
        owner='a'*32
        first=map_layers.start({**self.params,'request_owner':owner})
        second=map_layers.start({**self.params,'bounds':[-55.3,-12.5,-55.29,-12.49],'request_owner':owner})
        self.assertNotIn(first['id'],map_layers.RUNNING)
        self.assertEqual(map_layers.get(first['id'])['status'],'superseded')
        self.assertIn(second['id'],map_layers.RUNNING)
        self.assertEqual(self.worker.call_count,2)

    def test_running_read_is_preserved_and_full_queue_waits_then_resumes(self):
        for year in range(2010,2010+map_layers.MAX_PENDING):map_layers.start({**self.params,'year':year})
        waiting=map_layers.start({**self.params,'request_owner':'a'*32})
        self.assertEqual(waiting['phase'],'waiting')
        self.assertEqual(map_layers.get(waiting['id'])['phase'],'waiting')
        old_id=next(iter(map_layers.RUNNING));old=storage.source_snapshot('crop-map:v1:'+old_id)['result']
        self.finish(old,{'features':[]})
        self.assertEqual(map_layers.get(waiting['id'])['phase'],'queued')
        self.assertIn(waiting['id'],map_layers.RUNNING)

    def test_new_browser_request_can_replace_legacy_queued_work_but_not_running_reads(self):
        from concurrent.futures import Future
        self.worker.side_effect=lambda *args:Future()
        jobs=[map_layers.start({**self.params,'year':year}) for year in range(2010,2010+map_layers.MAX_PENDING)]
        for job in jobs[:2]:map_layers.FUTURES[job['id']].set_running_or_notify_cancel()
        newest=map_layers.start({**self.params,'request_owner':'b'*32})
        self.assertEqual(newest['phase'],'queued')
        self.assertEqual(len(map_layers.RUNNING),map_layers.MAX_PENDING)
        self.assertTrue(all(j['id'] in map_layers.RUNNING for j in jobs[:2]))
        self.assertEqual(map_layers.get(jobs[2]['id'])['status'],'superseded')

    def test_failed_submission_does_not_leave_job_running(self):
        self.worker.side_effect = RuntimeError('executor stopped')
        with self.assertRaises(ValueError): map_layers.start(self.params)
        self.assertFalse(map_layers.RUNNING)
        self.worker.side_effect = None
        self.assertEqual(map_layers.start(self.params)['status'], 'loading')


if __name__ == '__main__': unittest.main()
