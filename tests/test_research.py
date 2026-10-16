import copy
import hashlib
import io
import json
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
from app import research,storage,assistant,web_app

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=patch.object(storage,'DB_PATH',Path(self.temp.name)/'db.sqlite3');self.db.start()
        self.model=patch.object(research,'MODEL_PATH',Path(self.temp.name)/'model.joblib');self.model.start()
        self.end=date(2025,12,1)
    def tearDown(self): self.db.stop();self.model.stop();self.temp.cleanup()
    def points(self,values,end=None):
        end=end or self.end
        return [{'date':(end-timedelta(days=5*(len(values)-index-1))).isoformat(),'ndvi_mean':v,'valid_pixels':500,'valid_fraction':0.8} for index,v in enumerate(values)]
    def save_dataset(self,index,values,group='area',end=None):
        key=hashlib.sha256(str(index).encode()).hexdigest();end=end or self.end
        value={'id':key,'status':'ready','parameters':{'area_key':group,'start_year':2018,'end_year':2025,'as_of':'2025-12-31'},'points':self.points(values,end),'years':[],'updated_at':'2025-12-01'}
        storage.source_snapshot('history:'+key,value);return value
    def test_temporal_rules_distinguish_growth_drop_and_insufficient_data(self):
        growth=self.points([.1,.15,.25,.4,.55,.7])
        drop=self.points([.8,.8,.75,.6,.3,.2])
        self.assertEqual(research.baseline(growth,self.end.isoformat())['stage'],'emergencia')
        self.assertEqual(research.baseline(drop,self.end.isoformat())['stage'],'colheita')
        self.assertEqual(research.baseline(growth[:2],self.end.isoformat())['stage'],'inconclusivo')
    def test_features_never_use_future_or_cloudy_observations(self):
        points=self.points([.2]*6);expected=research.features(points,self.end.isoformat())
        points.append({'date':'2026-01-01','ndvi_mean':.9,'valid_pixels':1000,'valid_fraction':1})
        points.append({'date':self.end.isoformat(),'ndvi_mean':.9,'valid_pixels':5,'valid_fraction':.01})
        self.assertEqual(research.features(points,self.end.isoformat()),expected)
    def test_field_labels_require_reference_and_reject_overlapping_periods(self):
        d=self.save_dataset('one',[.2]*6)
        event={'dataset_id':d['id'],'from':'2025-11-28','to':'2025-12-01','stage':'pousio','note':'Visita de campo'}
        self.assertTrue(research.add_event(event)['saved'])
        with self.assertRaisesRegex(ValueError,'sobrepostos'): research.add_event(event)
        with self.assertRaises(ValueError):research.add_event({**event,'stage':'inventado'})
    def test_training_requires_ground_truth(self):
        with self.assertRaisesRegex(ValueError,'30 registros'):research.train()
        self.assertIsNone(research.model_status()['model'])
    def test_interrupted_history_is_resumed_only_once(self):
        d=self.save_dataset('interrupted',[.2]*6)
        d['status']='loading'
        storage.source_snapshot('history:'+d['id'],d)
        try:
            with patch.object(research.POOL,'submit') as submit:
                self.assertEqual(research.restore_history(d['id'])['points'],d['points'])
                research.restore_history(d['id'])
                submit.assert_called_once_with(research.build_history,d['id'],d['parameters'])
        finally: research.RUNNING.discard(d['id'])
    def test_finished_history_does_not_start_another_worker(self):
        d=self.save_dataset('finished',[.2]*6)
        with patch.object(research.POOL,'submit') as submit:
            research.restore_history(d['id'])
            submit.assert_not_called()
    def test_field_event_cannot_exceed_last_requested_year(self):
        d=self.save_dataset('short-history',[.2]*6)
        d['parameters']['end_year']=2024
        storage.source_snapshot('history:'+d['id'],d)
        with self.assertRaisesRegex(ValueError,'fora do histórico'):
            research.add_event({'dataset_id':d['id'],'from':'2025-12-01','to':'2025-12-01','stage':'pousio','note':'Visita de campo'})
    def test_supervised_pipeline_validates_by_area_and_predicts(self):
        for group in range(3):
            for index in range(10):
                end=date(2020,2,1)+timedelta(days=index*60)
                values=[.2]*6 if index%2==0 else [.35,.4,.5,.6,.7,.8]
                d=self.save_dataset(f'{group}-{index}',values,f'area-{group}',end)
                research.add_event({'dataset_id':d['id'],'from':end.isoformat(),'to':end.isoformat(),'stage':'solo_exposto' if index%2==0 else 'desenvolvimento','note':'Fixture sintética apenas para teste'})
        metadata=research.train()
        self.assertEqual(metadata['areas'],3);self.assertEqual(metadata['events'],30)
        self.assertIn('GroupKFold',metadata['validation'])
        self.assertGreaterEqual(metadata['balanced_accuracy'],.8)
        active_bytes=research.MODEL_PATH.read_bytes()
        candidate=research.train(promote=False)
        self.assertFalse(candidate['promoted'])
        self.assertTrue(Path(candidate['model_path']).is_file())
        self.assertEqual(research.MODEL_PATH.read_bytes(),active_bytes)
        self.assertEqual(research.model_status()['model']['version'],metadata['version'])
        prediction=research.analyze(d['id'],end.isoformat())['model_prediction']
        self.assertEqual(prediction['stage'],'desenvolvimento');self.assertTrue(prediction['experimental'])
    def test_year_jobs_keep_partial_data_and_resume_cached_successes(self):
        params={'geometry':{'type':'Polygon','coordinates':[]},'area_key':'test','start_year':2018,'end_year':2019,'as_of':'2025-12-31'}
        key='a'*64
        with patch.object(web_app,'request_ndvi_series',side_effect=[{'points':self.points([.2]*6)},RuntimeError()]) as api:research.build_history(key,params)
        result=research.dataset(key);self.assertEqual(result['status'],'partial');self.assertEqual(len(result['points']),6)
        with patch.object(web_app,'request_ndvi_series',return_value={'points':[]}) as api:
            research.build_history(key,params);api.assert_called_once()
        self.assertEqual(research.dataset(key)['status'],'ready')
    def test_unsupervised_patterns_are_not_management_ground_truth(self):
        values=[.2+(index%30)/50 for index in range(180)]
        d=self.save_dataset('clusters',values)
        patterns=research.patterns(d,self.end.isoformat())
        self.assertEqual(patterns['kind'],'unsupervised');self.assertEqual(len(patterns['groups']),4)
        self.assertIn('não são etapas',patterns['note'])
    def test_historical_groups_do_not_learn_from_future_observations(self):
        d=self.save_dataset('causal-clusters',[.2+(index%30)/50 for index in range(180)])
        first=research.patterns(d,self.end.isoformat())
        later=copy.deepcopy(d)
        later['points'].extend(self.points([.95]*60,date(2026,12,1)))
        second=research.patterns(later,self.end.isoformat())
        self.assertEqual(first,second)
    def test_openai_missing_key_and_grounded_structured_response(self):
        with patch.object(assistant,'urlopen') as api:
            with self.assertRaisesRegex(ValueError,'OPENAI_API_KEY'):assistant.ask({'prompt':'Olá'}, {})
            api.assert_not_called()
        evidence={'evidence':[{'id':'temporal_analysis','source':'Regras temporais','data':{'stage':'inconclusivo'}}]}
        answer={'answer':'Ainda inconclusivo.','evidence_ids':['temporal_analysis'],'limitations':['Manejo não confirmado.'],'action':{'kind':'none','class_ids':[]}}
        response={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]}
        with patch.object(assistant,'context',return_value=evidence),patch.object(assistant,'urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as api:
            result=assistant.ask({'prompt':'Como está a área?'},{'OPENAI_API_KEY':'private-key'})
            payload=json.loads(api.call_args.args[0].data)
            self.assertFalse(payload['store']);self.assertEqual(payload['text']['format']['type'],'json_schema')
            self.assertNotIn('private-key',json.dumps(payload));self.assertEqual(result['provider'],'OpenAI')
    def test_openai_rejects_invented_evidence(self):
        response={'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'answer':'inventado','evidence_ids':['fake'],'limitations':[],'action':{'kind':'none','class_ids':[]}})}]}]}
        with patch.object(assistant,'context',return_value={'evidence':[]}),patch.object(assistant,'urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaisesRegex(ValueError,'evidência'):assistant.ask({'prompt':'Teste'},{'OPENAI_API_KEY':'test'})

if __name__=='__main__': unittest.main()
