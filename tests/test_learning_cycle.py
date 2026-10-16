import csv
import io
import json
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from app import storage, research, learning_cycle as cycle, assistant, web_app
from app import visual_learning


class LearningCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        for target, name, value in [(storage, 'DB_PATH', Path(self.temp.name)/'db.sqlite3'),
                                    (research, 'MODEL_PATH', Path(self.temp.name)/'active.joblib'),
                                    (cycle, 'clock', lambda: self.now)]:
            mock = patch.object(target, name, value); mock.start(); self.addCleanup(mock.stop)
        cycle.WAKE.clear()
        geometry = {'type':'Polygon', 'coordinates':[[[-55.8,-12.5],[-55.79,-12.5],[-55.79,-12.49],[-55.8,-12.5]]]}
        area_key = research.fingerprint(geometry)
        # Jan-1-aligned five-day composites, all closed by the cutoff.
        self.points = [{'date':(date(2026, 1, 1)+timedelta(days=5*i)).isoformat(),
                        'ndvi_mean':.2+i/500, 'valid_pixels':500, 'valid_fraction':.8}
                       for i in range(45, 56)]
        self.history = {'id':'a'*64, 'status':'ready', 'parameters':{
            'geometry':geometry, 'area_key':area_key, 'municipality_code':'5107925',
            'start_year':2026, 'end_year':2026, 'as_of':'2026-10-08'},
            'points':self.points, 'years':[{'year':2026,'status':'ready','observations':len(self.points)}]}
        storage.source_snapshot('history:'+self.history['id'], self.history)
        self.analysis = {'baseline':{'stage':'desenvolvimento','label':'Possível desenvolvimento',
                                    'reason':'Vigor crescente.'}, 'model_prediction':None,
                         'vegetation_patterns':{'kind':'unsupervised','groups':[{'id':0},{'id':1}]}}

    def enroll(self, ai_enabled=True):
        return cycle.enroll({'dataset_id':self.history['id'], 'name':'Parceiro piloto', 'ai_enabled':ai_enabled})

    def run_cycle(self, points=None, ai=None):
        response = ai or {'provider':'Gemini','model':'test','answer':'Hipótese de desenvolvimento; conferir com o produtor.',
                         'sources':[], 'limitations':['Manejo não confirmado.'], 'evidence_ids':['temporal_analysis']}
        with patch.object(web_app, 'request_ndvi_series', return_value={'points':points if points is not None else []}), \
             patch.object(web_app, 'read_app_env', return_value={}), \
             patch.object(research, 'analyze', return_value=self.analysis), \
             patch.object(visual_learning,'prepare',side_effect=lambda dataset_id,cutoff:{'status':'ready','dataset_id':dataset_id,'assets':[],'issues':[]}), \
             patch.object(visual_learning,'review',return_value={'status':'ready','review':response}) as ask:
            result = cycle.run_once()
        return result, ask

    def test_enrollment_idempotence_and_persistent_lease(self):
        plan = self.enroll()
        self.assertEqual(self.enroll()['id'], plan['id'])
        self.assertEqual(len(cycle.plans()), 1)
        first = cycle.claim()
        self.assertIsNotNone(first)
        self.assertIsNone(cycle.claim())
        self.now += timedelta(hours=2)
        replacement = cycle.claim()
        self.assertNotEqual(first[1]['id'], replacement[1]['id'])
        with cycle.database() as db:
            old = db.execute('SELECT status,result FROM learning_runs WHERE id=?',(first[1]['id'],)).fetchone()
        self.assertEqual(old['status'], 'interrupted')
        self.assertEqual(json.loads(old['result'])['status'], 'interrupted')

    def test_cycle_collects_reviews_and_keeps_labels_empty_until_field_confirmation(self):
        plan = self.enroll()
        incoming = [{'date':'2026-10-08','ndvi_mean':.6,'valid_pixels':500,'valid_fraction':.9}]
        run, ask = self.run_cycle(incoming)
        self.assertEqual(run['status'], 'ready')
        self.assertEqual(run['collection']['new_intervals'], 1)
        self.assertEqual(run['ai_review']['status'], 'ready')
        self.assertEqual(run['field_review']['status'], 'pending')
        self.assertEqual(research.events(), [])
        ask.assert_called_once()
        self.assertEqual(ask.call_args.args[0]['dataset_id'], run['dataset_id'])
        self.assertEqual(cycle.get(plan['id'])['latest_dataset_id'], run['dataset_id'])
        self.assertIsNone(cycle.run_once())
        output = cycle.export(Path(self.temp.name)/'output')
        with (Path(output['folder'])/'janelas_ml.csv').open(encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['target_stage'], '')
        confirmed = cycle.review({'run_id':run['id'], 'stage':'pousio', 'note':'Visita com parceiro confirmou pousio.',
                                  'partner':'Parceiro A', 'crop':'soja'})
        self.assertEqual(confirmed['field_review']['confirmed_stage'], 'pousio')
        record = research.events()[0]
        provenance = json.loads(record['provenance'])
        self.assertEqual(provenance['learning_run_id'], run['id'])
        self.assertEqual(provenance['origin'], 'human_field_record')
        self.assertEqual(provenance['partner'], 'Parceiro A')
        with self.assertRaises(ValueError):cycle.review({'run_id':run['id'], 'stage':'plantio','note':'Duplicado'})
        output = cycle.export(Path(self.temp.name)/'output')
        with (Path(output['folder'])/'janelas_ml.csv').open(encoding='utf-8-sig') as stream:
            self.assertEqual(list(csv.DictReader(stream))[0]['target_stage'], 'pousio')

    def test_no_cloud_or_future_composite_becomes_training_signal(self):
        good = {'date':'2026-10-08','ndvi_mean':.7,'valid_pixels':500,'valid_fraction':.9}
        cloudy = {**good,'ndvi_mean':.01,'valid_pixels':3,'valid_fraction':.02}
        future = {**good,'date':'2026-10-13'}
        rows = cycle.merge_points([good], [cloudy, future], '2026-10-14')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ndvi_mean'], .7)
        self.assertEqual(rows[0]['available'], '2026-10-12')
        self.assertFalse(cycle.quality({**good,'ndvi_mean':float('nan')}))
        self.assertFalse(cycle.quality({**good,'valid_fraction':1.2}))
        self.assertEqual(research.windows([rows[0]], '2026-10-10'), [])

    def test_ai_failure_preserves_observations_and_does_not_invent_review(self):
        plan = self.enroll()
        with patch.object(web_app, 'request_ndvi_series', return_value={'points':[]}), \
             patch.object(research, 'analyze', return_value=self.analysis), \
             patch.object(visual_learning, 'prepare', side_effect=RuntimeError('private-key')), \
             patch.object(web_app, 'read_app_env', return_value={}):
            result = cycle.run_once()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['ai_review']['status'], 'unavailable')
        self.assertNotIn('private-key', json.dumps(result))
        self.assertEqual(cycle.get(plan['id'])['latest_dataset_id'], result['dataset_id'])

    def test_satellite_outage_retries_and_preserves_original_history(self):
        plan = self.enroll()
        with patch.object(web_app, 'request_ndvi_series', side_effect=RuntimeError('private-key')), \
             patch.object(research, 'analyze', return_value=self.analysis), \
             patch.object(visual_learning, 'prepare', side_effect=RuntimeError('private-key')):
            result = cycle.run_once()
        self.assertEqual(result['status'], 'partial')
        saved = cycle.get(plan['id'])
        self.assertNotEqual(saved['latest_dataset_id'], self.history['id'])
        self.assertEqual(research.dataset(self.history['id']), self.history)
        self.assertNotIn('last_collected_to',saved)
        self.assertEqual(result['collection']['status'],'unavailable')
        self.assertEqual(datetime.fromisoformat(saved['next_due']), self.now+timedelta(hours=6))
        self.assertNotIn('private-key', json.dumps(result))

    def test_pause_and_refresh_do_not_start_duplicate_collection(self):
        plan = self.enroll(False)
        cycle.configure({'plan_id':plan['id'], 'enabled':False})
        self.assertIsNone(cycle.claim())
        cycle.configure({'plan_id':plan['id'], 'enabled':True, 'refresh':True})
        first = cycle.claim()
        cycle.configure({'plan_id':plan['id'], 'refresh':True})
        self.assertIsNone(cycle.claim())
        self.assertIsNotNone(first)

    def test_second_unchanged_cycle_avoids_repeated_ai_call_and_freezes_old_dataset(self):
        plan = self.enroll()
        first, _ = self.run_cycle()
        frozen = research.dataset(first['dataset_id'])
        cycle.configure({'plan_id':plan['id'], 'refresh':True})
        second, ask = self.run_cycle()
        self.assertFalse(second['input_changed'])
        self.assertEqual(second['ai_review']['status'], 'unchanged')
        ask.assert_not_called()
        self.assertNotEqual(first['dataset_id'], second['dataset_id'])
        self.assertEqual(research.dataset(first['dataset_id']), frozen)
        exported=cycle.export(Path(self.temp.name)/'deduplicated')
        self.assertEqual(exported['runs'],2)
        self.assertEqual(exported['windows'],1)

    def test_evidence_is_exact_geometry_and_has_no_future_field_label_or_ai_claim(self):
        self.enroll()
        run, _ = self.run_cycle()
        area_key = self.history['parameters']['area_key']
        self.assertIsNone(cycle.evidence('another-area', '2026-10-14'))
        self.assertIsNone(cycle.evidence(area_key, '2026-10-13'))
        self.now += timedelta(days=2)
        cycle.review({'run_id':run['id'],'stage':'pousio','note':'Confirmado na visita posterior.'})
        evidence = cycle.evidence(area_key, '2026-10-14')
        self.assertEqual(evidence['field_review']['status'], 'pending')
        self.assertNotIn('confirmed_stage', evidence['field_review'])
        self.assertNotIn('ai_review', evidence)
        self.assertEqual(cycle.evidence(area_key,'2026-10-16')['field_review']['confirmed_stage'], 'pousio')

    def test_candidate_uses_only_human_records_and_never_promotes(self):
        with patch.object(research,'events',return_value=[{'id':i,'stage':'pousio'} for i in range(30)]), \
             patch.object(research,'model_status',return_value={'events':30,'areas':3}), \
             patch.object(research,'train',return_value={'version':'candidate'}) as train:
            result = cycle.candidate()
            self.assertEqual(result['status'], 'evaluated')
            train.assert_called_once_with(promote=False)
            cycle.candidate()
            self.assertEqual(train.call_count, 1)
        self.assertIsNone(storage.source_snapshot('ml:model:v1'))

    def test_processing_quota_is_reported_without_exposing_provider_body(self):
        exc=HTTPError('https://example.invalid',403,'Forbidden',{},io.BytesIO(json.dumps({
            'error':{'message':'Insufficient processing units or requests available in your account. private-key'}}).encode()))
        issue=cycle.collection_failure(exc)
        exc.close()
        self.assertEqual(issue['reason'],'processing_quota')
        self.assertNotIn('private-key',json.dumps(issue))
        self.assertEqual(cycle.ai_failure(ValueError('Falha temporária (HTTP 503) private-key'))['reason'],'http_503')
        self.assertNotIn('private-key',json.dumps(cycle.ai_failure(ValueError('Falha temporária (HTTP 503) private-key'))))

    def test_conversation_gets_only_same_area_past_human_records(self):
        records=[{'id':1,'area_key':self.history['parameters']['area_key'],'date_from':'2026-10-01',
                  'date_to':'2026-10-03','stage':'pousio','note':'Visita confirmada','created_at':'2026-10-04T12:00:00+00:00'}]
        records += [{**records[0],'id':2,'area_key':'other'},
                    {**records[0],'id':3,'created_at':'2026-10-16T12:00:00+00:00'}]
        from app import crop_monitoring
        with patch.object(research,'events',return_value=records), \
             patch.object(research,'model_status',return_value={}), \
             patch.object(research,'analyze',return_value=self.analysis), \
             patch.object(crop_monitoring,'report',return_value={}), \
             patch.object(crop_monitoring,'evidence',return_value={}):
            context=assistant.context({'dataset_id':self.history['id'],'municipality_code':'5107925'})
        fields=next(e for e in context['evidence'] if e['id']=='field_observations')
        self.assertEqual([r['id'] for r in fields['records']],[1])

    def test_http_enrollment_status_pause_and_export(self):
        server = web_app.ThreadingHTTPServer(('127.0.0.1',0), web_app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        try:
            base = 'http://127.0.0.1:'+str(server.server_address[1])
            def post(path, payload):
                req = Request(base+path, data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
                with urlopen(req,timeout=3) as response:return json.load(response)
            plan = post('/api/learning-cycle', {'dataset_id':self.history['id']})
            with urlopen(base+'/api/learning-cycle/'+plan['id'],timeout=3) as response:
                self.assertEqual(json.load(response)['runs'], [])
            self.assertFalse(post('/api/learning-cycle/configure', {'plan_id':plan['id'],'enabled':False})['enabled'])
            with patch.object(cycle,'OUTPUT',Path(self.temp.name)/'exports'):
                self.assertEqual(post('/api/learning-cycle/export', {})['windows'],0)
        finally:
            server.shutdown();server.server_close();thread.join(3)


if __name__ == '__main__':
    unittest.main()
