import copy
import csv
import hashlib
import json
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from app import storage, research, regional_learning as regional, regional_batch, learning_cycle, assistant, web_app


class RegionalLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.instant=datetime(2026,10,14,12,tzinfo=timezone.utc)
        for target,key,value in [(storage,'DB_PATH',self.root/'db.sqlite3'),(regional,'OUTPUT',self.root/'base'),
                                 (regional_batch,'OUTPUT',self.root/'rosters'),(regional,'now',lambda:self.instant)]:
            mock=patch.object(target,key,value);mock.start();self.addCleanup(mock.stop)
        self.geometry={'type':'Polygon','coordinates':[[[-55,-12],[-54.99,-12],[-54.99,-11.99],[-55,-12]]]}
        self.area=research.fingerprint(self.geometry)
        self.end=date(2026,10,8)
        self.period={'from':(self.end-timedelta(days=60)).isoformat(),'to':self.end.isoformat()}
        self.points=[{'date':(self.end-timedelta(days=40-i*5)).isoformat(),'ndvi_mean':.2+i*.04,
                      'valid_pixels':500,'valid_fraction':.8} for i in range(8)]
        self.evidence_key='inactive-evidence:'+hashlib.sha256(json.dumps([self.geometry,self.period],sort_keys=True).encode()).hexdigest()
        storage.source_snapshot('regional-scan:v1:fixture',{'cities':[
            {'code':'5107925','name':'Sorriso','status':'partial'},
            {'code':'5200100','name':'Abadiânia','status':'error'},
            {'code':'5000203','name':'Água Clara','status':'queued'}]})
        storage.source_snapshot('municipality:v1:5107925',{'name':'Sorriso','uf':'MT','status':'partial','sources':{}})
        storage.source_snapshot('municipality:v1:5200100',{'name':'Abadiânia','uf':'GO','status':'partial','sources':{}})
        storage.source_snapshot('municipal-soy:v1:5107925',{'features':[{'type':'Feature','geometry':self.geometry,'properties':{'area_ha':10}}],'total_soy_ha':10})
        storage.source_snapshot('municipal-activity:'+'a'*64,{'id':'a'*64,'status':'loading',
            'parameters':{'municipality_code':'5107925','as_of':self.end.isoformat()},'points':[]})
        storage.source_snapshot(self.evidence_key,{'points':self.points})

    def build(self):
        # Consolidation must not trigger acquisition, training or the LLM.
        with patch.object(web_app,'request_ndvi_series',side_effect=AssertionError('network collector called')), \
             patch.object(assistant,'review_context',side_effect=AssertionError('LLM called')), \
             patch.object(research,'train',side_effect=AssertionError('supervised training called')):
            return regional.build()

    def rows(self,base,name):
        with (Path(base['base']['folder'])/name).open(encoding='utf-8-sig',newline='') as stream:
            return list(csv.DictReader(stream))

    def test_complete_inventory_partial_data_and_blocked_cities_are_preserved(self):
        result=self.build();totals=result['base']['totals']
        self.assertEqual(totals['municipalities'],3)
        self.assertEqual(totals['processed_municipalities'],2)
        self.assertEqual(totals['municipalities_with_data'],2)
        self.assertEqual(totals['areas_with_observations'],1)
        self.assertGreater(totals['feature_windows'],0)
        self.assertEqual(result['queue'],{'blocked':1,'pending':2})
        self.assertFalse(result['ai_enabled'])
        city={r['code']:r for r in result['base']['municipalities']}
        self.assertEqual(city['5107925']['readiness'],'temporal_data')
        self.assertEqual(city['5200100']['readiness'],'context_only')
        self.assertEqual(city['5000203']['readiness'],'no_data')
        self.assertTrue(all(row['target_stage']=='' for row in self.rows(result,'janelas_ml.csv')))
        plans=learning_cycle.plans()
        self.assertEqual(len(plans),1)
        self.assertFalse(plans[0]['ai_enabled'])
        self.assertEqual(plans[0]['ai_scope'],'municipal_queue')
        self.assertEqual(date.fromisoformat(plans[0]['next_due'][:10]),self.instant.date()+timedelta(days=5))

    def test_new_version_does_not_duplicate_plans_or_self_trigger_rebuild(self):
        first=self.build();second=self.build()
        self.assertNotEqual(first['base']['id'],second['base']['id'])
        self.assertEqual(first['base']['totals'],second['base']['totals'])
        self.assertEqual(len(learning_cycle.plans()),1)
        self.assertEqual(second['base']['new_monitoring_plans'],0)
        with storage.connect() as db:
            self.assertEqual(regional.source_stamp(db),second['base']['source_stamp'])
        self.instant+=timedelta(minutes=6)
        with patch.object(regional,'start_build') as build,patch.object(assistant,'review_context') as provider:
            regional.tick();build.assert_not_called();provider.assert_not_called()

    def test_missing_readings_are_scheduled_without_inventing_training_data(self):
        with storage.connect() as db:db.execute('DELETE FROM source_snapshots WHERE cache_key=?',(self.evidence_key,))
        result=self.build()
        self.assertEqual(result['base']['totals']['observations'],0)
        self.assertEqual(result['base']['totals']['feature_windows'],0)
        self.assertEqual(result['base']['totals']['monitoring_areas'],1)
        plan=learning_cycle.plans()[0]
        self.assertEqual(research.dataset(plan['latest_dataset_id'])['points'],[])
        self.assertNotIn('last_collected_to',plan)

    def test_future_and_bad_quality_are_not_silently_used_as_ml_features(self):
        storage.source_snapshot(self.evidence_key,{'points':self.points+[
            {**self.points[0],'date':'2027-01-01'},
            {**self.points[0],'date':'2026-10-08','ndvi_mean':.01,'valid_pixels':2,'valid_fraction':.01}]})
        result=self.build();rows=self.rows(result,'observacoes.csv')
        self.assertTrue(all(row['date']<='2026-10-08' for row in rows))
        self.assertEqual(rows[-1]['quality_usable'],'False')
        self.assertGreater(result['base']['totals']['observations'],result['base']['totals']['usable_observations'])

    def test_human_targets_match_only_exact_geometry_and_date(self):
        with storage.connect() as db:
            for area in (self.area,'other-area'):
                db.execute('INSERT INTO field_events(dataset_id,area_key,date_from,date_to,stage,note,created_at) VALUES(?,?,?,?,?,?,?)',
                    ('fixture',area,'2026-09-20','2026-10-08','pousio','Fixture de campo',storage.now()))
        result=self.build();rows=self.rows(result,'janelas_ml.csv')
        labeled=[row for row in rows if row['target_stage']]
        self.assertTrue(labeled)
        self.assertTrue(all(row['area_key']==self.area and row['label_source']=='registro_de_campo' for row in labeled))
        self.assertEqual(result['base']['totals']['field_labeled_windows'],len(labeled))

    def test_partial_new_history_keeps_older_observations(self):
        for key,as_of,points in [('b'*64,'2025-10-08',[{**p,'date':p['date'].replace('2026','2025')} for p in self.points]),
                                 ('c'*64,'2026-10-08',self.points[:2])]:
            storage.source_snapshot('history:'+key,{'id':key,'status':'partial','parameters':{
                'geometry':self.geometry,'area_key':self.area,'municipality_code':'5107925',
                'start_year':2025,'end_year':2026,'as_of':as_of},'points':points,'years':[]})
        result=self.build()
        city=next(c for c in result['base']['municipalities'] if c['code']=='5107925')
        packet=json.loads(Path(city['packet_path']).read_text(encoding='utf-8'))
        self.assertEqual(len(packet['reference_histories'][0]['points']),10)

    def test_ai_is_separate_uses_frozen_base_and_reuses_identical_completed_review(self):
        first=self.build()
        self.assertIsNone(regional.review_one())
        original=json.loads(Path(next(c for c in first['base']['municipalities'] if c['code']=='5107925')['packet_path']).read_text(encoding='utf-8'))['ai_context']
        storage.source_snapshot(self.evidence_key,{'points':[]})
        regional.configure({'ai_enabled':True})
        response={'provider':'Gemini','model':'fixture','answer':'Hipótese a validar.','sources':[],
                  'evidence_ids':['base_coverage'],'limitations':[],'action':{'kind':'none','class_ids':[]}}
        with patch.object(assistant,'review_context',return_value=response) as review:
            reviewed=regional.review_one()
        self.assertEqual(reviewed['status'],'ready')
        self.assertIsNone(reviewed['training_target'])
        self.assertEqual(review.call_args.args[1],original)
        self.assertEqual(research.events(),[])
        storage.source_snapshot(self.evidence_key,{'points':self.points})
        second=self.build()
        self.assertEqual(second['queue']['ready'],1)
        self.assertEqual(regional.city_review('5107925')['status'],'ready')

    def test_provider_failure_defers_entire_queue_instead_of_hammering_cities(self):
        self.build();regional.configure({'ai_enabled':True})
        with patch.object(assistant,'review_context',side_effect=ValueError('Falha temporária (HTTP 503) private-key')) as review:
            result=regional.review_one()
            self.assertEqual(result['status'],'retry')
            self.assertIsNone(regional.review_one())
            self.assertEqual(review.call_count,1)
        self.assertNotIn('private-key',json.dumps(result))
        self.assertTrue(regional.status_snapshot()['backoff_until'])

    def test_http_status_download_and_explicit_queue_activation(self):
        self.build()
        server=web_app.ThreadingHTTPServer(('127.0.0.1',0),web_app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_address[1])
        try:
            with urlopen(base+'/api/regional-learning') as response:self.assertFalse(json.load(response)['ai_enabled'])
            with urlopen(base+'/api/regional-learning/files/janelas_ml.csv') as response:
                self.assertIn('attachment',response.headers['Content-Disposition'])
                self.assertIn('target_stage',response.read().decode('utf-8-sig'))
            req=Request(base+'/api/regional-learning/configure',data=b'{"ai_enabled":true}',headers={'Content-Type':'application/json'})
            with urlopen(req) as response:self.assertTrue(json.load(response)['ai_enabled'])
        finally:server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':unittest.main()
