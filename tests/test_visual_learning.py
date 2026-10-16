import base64
import copy
import hashlib
import io
import json
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
import numpy as np
from rasterio.transform import from_origin
from app import storage,research,assistant,visual_learning as visual,spatial_raster,learning_cycle,regional_learning


class VisualLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.addCleanup(self.temp.cleanup)
        self.instant=datetime(2026,10,14,12,tzinfo=timezone.utc)
        for target,key,value in [(storage,'DB_PATH',self.root/'db.sqlite3'),(visual,'ROOT',self.root/'vision'),
            (visual,'RASTERS',self.root/'rasters'),(spatial_raster,'ROOT',self.root/'ndvi'),(visual,'now',lambda:self.instant)]:
            mock=patch.object(target,key,value);mock.start();self.addCleanup(mock.stop)
        self.geometry={'type':'Polygon','coordinates':[[[-55,-12],[-54.99,-12],[-54.99,-11.99],[-55,-12]]]}
        self.area=research.fingerprint(self.geometry)
        self.grid={'width':20,'height':20,'mask':np.ones((20,20),dtype=bool),'crs':'EPSG:32721',
            'bounds':[100,100,300,300],'transform':from_origin(100,300,10,10)}
        self.periods=[{'from':'2026-09-18','to':'2026-09-22'},
            {'from':'2026-09-23','to':'2026-09-27'},{'from':'2026-10-03','to':'2026-10-07'}]
        self.history={'id':'a'*64,'status':'ready','parameters':{'geometry':self.geometry,'area_key':self.area,
            'municipality_code':'5107925','start_year':2026,'end_year':2026,'as_of':'2026-10-14'},
            'points':[],'years':[]}
        storage.source_snapshot('history:'+self.history['id'],self.history)
        self.env={'AI_PROVIDER':'gemini','GEMINI_API_KEY':'private-key'}

    def prepared(self,rgb=True,valid=True):
        data={'rgb':np.full((20,20,3),.1,dtype='float32'),
              'ndvi':np.full((20,20),.4,dtype='float32'),
              'valid':np.full((20,20),valid,dtype=bool),'source_path':'synthetic-test-raster.tif'}
        with patch.object(visual,'periods_for',return_value=self.periods), \
             patch.object(spatial_raster,'grid_for',return_value=self.grid), \
             patch.object(visual,'rgb_raster',return_value=data if rgb else None):
            return visual.prepare(self.history['id'],allow_download=False)

    def response(self,prepared):
        assets=prepared['assets']
        return {'answer':'Há heterogeneidade visual; manejo precisa de campo.',
            'evidence_ids':[assets[0]['evidence_id']],'limitations':['Sem confirmação de manejo.'],
            'action':{'kind':'none','class_ids':[]},'visual_observations':[
                {'image_ids':[assets[0]['evidence_id']],'feature':'patchy_vegetation',
                 'presence':'present','description':'Padrões espaciais visíveis no recorte.'}],
            'hypotheses':['Diferenças de estabelecimento ou manejo.'],
            'field_checks':['Conferir cultura e operação com o parceiro.']}

    def call(self,prepared,answer=None):
        answer=answer or self.response(prepared)
        result={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(answer)}]}}]}
        if self.env.get('AI_PROVIDER')=='openai':
            result={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}],
                    'usage':{'input_tokens':100,'output_tokens':20,'total_tokens':120}}
        from app import web_app
        with patch.object(web_app,'read_app_env',return_value=self.env), \
             patch.object(assistant,'provider_response',return_value=result) as provider:
            reviewed=visual.review(prepared)
        return reviewed,provider.call_args.args[0]

    def test_actual_png_bytes_are_sent_inline_with_dates_and_hashes(self):
        prepared=self.prepared();self.assertEqual(len(prepared['assets']),6)
        reviewed,request=self.call(prepared)
        body=json.loads(request.data);parts=body['contents'][0]['parts']
        images=[p['inline_data'] for p in parts if 'inline_data' in p]
        self.assertEqual(len(images),6)
        for sent,asset in zip(images,prepared['assets']):
            binary=base64.b64decode(sent['data'])
            self.assertEqual(binary,Path(asset['path']).read_bytes())
            self.assertEqual(hashlib.sha256(binary).hexdigest(),asset['sha256'])
            self.assertEqual(sent['mime_type'],'image/png')
        self.assertNotIn('private-key',request.full_url+request.data.decode())
        self.assertEqual(reviewed['analysis_mode'],'visual')
        self.assertIsNone(reviewed['training_target'])
        self.assertEqual(reviewed['visual_features']['patchy_vegetation'],1)
        self.assertEqual(research.events(),[])

    def test_cached_ndvi_is_visual_evidence_and_never_mislabeled_true_color(self):
        with patch.object(visual,'periods_for',return_value=self.periods), \
             patch.object(spatial_raster,'grid_for',return_value=self.grid), \
             patch.object(visual,'rgb_raster',return_value=None), \
             patch.object(spatial_raster,'cache_path',return_value=self.root/'cached.tif'), \
             patch.object(spatial_raster,'read_raster',return_value=(np.full((20,20),.3),self.grid['mask'])):
            (self.root/'cached.tif').write_bytes(b'fixture')
            prepared=visual.prepare(self.history['id'],allow_download=False)
        self.assertEqual(len(prepared['assets']),3)
        self.assertEqual(prepared['image_kinds'],['ndvi'])
        self.assertTrue(prepared['missing_true_color'])
        reviewed,_=self.call(prepared)
        self.assertEqual(reviewed['review']['analysis_mode'],'visual')

    def test_openai_luna_sends_real_images_and_preserves_provenance_and_usage(self):
        self.env={'AI_PROVIDER':'openai','OPENAI_MODEL':'gpt-6-luna','OPENAI_API_KEY':'private-openai-key'}
        prepared=self.prepared();reviewed,request=self.call(prepared)
        body=json.loads(request.data)
        self.assertEqual(request.full_url,'https://api.openai.com/v1/responses')
        self.assertEqual(body['model'],'gpt-6-luna')
        self.assertFalse(body['store'])
        self.assertEqual(body['reasoning'],{'effort':'low'})
        self.assertEqual(body['text']['format']['schema'],assistant.VISUAL_SCHEMA)
        images=[p for p in body['input'][0]['content'] if p['type']=='input_image']
        self.assertEqual(len(images),6)
        for sent,asset in zip(images,prepared['assets']):
            self.assertEqual(sent['detail'],'high')
            self.assertEqual(base64.b64decode(sent['image_url'].split(',',1)[1]),Path(asset['path']).read_bytes())
        self.assertNotIn('private-openai-key',request.full_url+request.data.decode())
        self.assertEqual(reviewed['feature_origin'],'openai_visual_interpretation')
        self.assertEqual(reviewed['review']['usage']['total_tokens'],120)
        self.assertIsNone(reviewed['training_target'])
        visual.record_review(reviewed)
        row=visual.feature_rows()[0]
        self.assertEqual(row['feature_origin'],'openai_visual_interpretation')
        self.assertEqual(row['provider'],'OpenAI')
        self.assertEqual(row['model'],'gpt-6-luna')
        self.assertEqual(row['target_stage'],'')
        self.assertEqual(visual.evidence(self.area,'2026-10-14')['source'],'OpenAI · interpretação de imagens reais')

    def test_openai_rejects_tampered_images_and_invented_evidence(self):
        self.env={'AI_PROVIDER':'openai','OPENAI_MODEL':'gpt-6-luna','OPENAI_API_KEY':'private-openai-key'}
        prepared=self.prepared();answer=self.response(prepared)
        answer['visual_observations'][0]['image_ids']=['invented']
        with self.assertRaisesRegex(ValueError,'vínculo'):self.call(prepared,answer)
        Path(prepared['assets'][0]['path']).write_bytes(b'changed')
        with patch.object(assistant,'provider_response') as provider:
            with self.assertRaises(ValueError):
                assistant.review_context('Teste',{'evidence':[{'id':a['evidence_id']} for a in prepared['assets']]},
                                         self.env,images=prepared['assets'])
            provider.assert_not_called()

    def test_missing_or_cloudy_images_do_not_call_gemini(self):
        missing=self.prepared(rgb=False)
        cloudy=self.prepared(valid=False)
        with patch.object(assistant,'provider_response') as provider:
            for prepared in (missing,cloudy):
                self.assertEqual(visual.review(prepared)['status'],'waiting_images')
            provider.assert_not_called()

    def test_image_tampering_and_fabricated_image_ids_are_rejected(self):
        prepared=self.prepared()
        Path(prepared['assets'][0]['path']).write_bytes(b'changed')
        with patch.object(assistant,'provider_response') as provider:
            with self.assertRaises(ValueError):self.call(prepared)
            provider.assert_not_called()
        prepared=self.prepared();answer=self.response(prepared)
        answer['visual_observations'][0]['image_ids']=['image_that_was_not_sent']
        with self.assertRaisesRegex(ValueError,'vínculo'):self.call(prepared,answer)

    def test_changes_require_two_distinct_dates_and_ndvi_does_not_confirm_bare_soil(self):
        prepared=self.prepared();answer=self.response(prepared)
        answer['visual_observations'][0]['feature']='vegetation_gain'
        with self.assertRaisesRegex(ValueError,'duas datas'):self.call(prepared,answer)
        ndvi=[a for a in prepared['assets'] if a['kind']=='ndvi']
        answer['visual_observations'][0].update(feature='exposed_surface',image_ids=[ndvi[0]['evidence_id']])
        with self.assertRaisesRegex(ValueError,'solo exposto'):self.call(prepared,answer)
        answer['visual_observations'][0].update(feature='vegetation_gain',image_ids=[ndvi[0]['evidence_id'],ndvi[-1]['evidence_id']])
        self.assertEqual(self.call(prepared,answer)[0]['visual_features']['vegetation_gain'],1)

    def test_render_preserves_mask_and_content_addressed_images(self):
        valid=self.grid['mask'].copy();valid[0,0]=False
        values=np.full((20,20),.5);values[0,0]=float('nan')
        first=visual.render(self.geometry,self.grid,self.periods[0],'ndvi',values,valid,'fixture')
        original=Path(first['path']).read_bytes()
        second=visual.render(self.geometry,self.grid,self.periods[0],'ndvi',values*.5,valid,'fixture')
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(Path(first['path']).read_bytes(),original)
        self.assertLess(first['valid_fraction'],1)

    def test_visual_features_are_exported_as_inputs_with_empty_target(self):
        prepared=self.prepared();reviewed,_=self.call(prepared)
        identifier='b'*64
        with storage.connect() as db:
            visual.schema(db)
            db.execute('INSERT INTO visual_jobs(id,area_key,municipality_code,dataset_id,cutoff,status,priority,next_attempt,result) VALUES(?,?,?,?,?,?,?,?,?)',
                (identifier,self.area,'5107925',self.history['id'],'2026-10-14','ready',0,self.instant.isoformat(),json.dumps(reviewed)))
        rows=visual.feature_rows()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['target_stage'],'')
        self.assertEqual(rows[0]['feature_origin'],'gemini_visual_interpretation')
        self.assertEqual(rows[0]['patchy_vegetation'],1)

    def test_field_informed_revision_does_not_replace_prelabel_training_features(self):
        prepared=self.prepared();before,_=self.call(prepared)
        with storage.connect() as db:
            db.execute('INSERT INTO field_events(dataset_id,area_key,date_from,date_to,stage,note,created_at) VALUES(?,?,?,?,?,?,?)',
                (self.history['id'],self.area,'2026-10-14','2026-10-14','pousio','Fixture de campo','2026-10-14T12:00:00+00:00'))
        informed,_=self.call(prepared)
        self.assertTrue(informed['field_informed'])
        self.assertFalse(informed['eligible_as_training_input'])
        with storage.connect() as db:
            visual.schema(db)
            for identifier,value in [('b'*64,before),('c'*64,informed)]:
                db.execute('INSERT INTO visual_jobs(id,area_key,municipality_code,dataset_id,cutoff,status,priority,next_attempt,result) VALUES(?,?,?,?,?,?,?,?,?)',
                    (identifier,self.area,'5107925',self.history['id'],'2026-10-14','ready',0,self.instant.isoformat(),json.dumps(value)))
        rows=visual.feature_rows()
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]['eligible_as_training_input'])
        self.assertEqual(rows[0]['visual_job_id'],'b'*64)
        self.assertEqual(rows[0]['target_stage'],'pousio')
        self.assertIsNone(visual.evidence('another-area','2026-10-14'))
        self.assertIsNone(visual.evidence(self.area,'2026-10-13'))

    def test_provider_error_keeps_images_and_audits_actual_multimodal_attempt(self):
        prepared=self.prepared();identifier='b'*64
        with storage.connect() as db:
            visual.schema(db)
            db.execute('INSERT INTO visual_jobs(id,area_key,municipality_code,dataset_id,cutoff,status,priority,next_attempt,result) VALUES(?,?,?,?,?,?,?,?,?)',
                (identifier,self.area,'5107925',self.history['id'],'2026-10-14','running',0,self.instant.isoformat(),'{}'))
        from app import web_app
        with patch.object(visual,'prepare',return_value=prepared),patch.object(web_app,'read_app_env',return_value=self.env), \
             patch.object(assistant,'provider_response',side_effect=ValueError('Falha temporária (HTTP 503)')):
            result=visual.execute({'id':identifier,'dataset_id':self.history['id'],'cutoff':'2026-10-14'})
        self.assertEqual(result['status'],'retry')
        self.assertEqual(result['analysis_mode'],'not_analyzed')
        self.assertEqual(result['image_request']['image_count'],6)
        self.assertEqual(len(result['assets']),6)
        self.assertNotIn('private-key',json.dumps(result))
        self.assertNotIn('visual_features',result)

    def test_queue_includes_all_recortes_and_prioritizes_cached_images_during_quota_block(self):
        for index in range(3):
            geom=copy.deepcopy(self.geometry)
            if index:geom['coordinates'][0][0][0]+=index*.00001
            key=research.fingerprint(geom)
            history={**self.history,'id':str(index)*64,'parameters':{**self.history['parameters'],'geometry':geom,'area_key':key}}
            storage.source_snapshot('history:'+history['id'],history)
            plan={'id':str(index)*64,'area_key':key,'municipality_code':'5107925','latest_dataset_id':history['id']}
            with learning_cycle.database() as db:
                db.execute('INSERT INTO learning_plans VALUES(?,?,?,?,NULL)',(plan['id'],key,json.dumps(plan),self.instant.isoformat()))
        storage.source_snapshot('cv:job:fixture',{'status':'ready','parameters':{'area_id':self.area}})
        storage.source_snapshot('regional-learning:latest',{'id':'fixture','created_at':self.instant.isoformat(),
            'municipalities':[{'code':'5107925'}]})
        storage.source_snapshot('regional-learning:config',{'ai_enabled':True})
        storage.source_snapshot('learning:collection-gate',{'until':(self.instant+timedelta(hours=6)).isoformat()})
        with patch.object(visual,'execute',return_value={}) as execute:
            visual.review_next()
            self.assertEqual(execute.call_args.args[0]['area_key'],self.area)
            self.assertIsNone(visual.review_next())
        self.assertEqual(sum(visual.status_snapshot()['queue'].values()),3)

    def test_registration_commits_batches_and_resumes_without_duplicates(self):
        from contextlib import contextmanager
        for index in range(3):
            key='area-'+str(index)
            history={**self.history,'id':str(index)*64,'parameters':{**self.history['parameters'],'area_key':key}}
            storage.source_snapshot('history:'+history['id'],history)
            plan={'id':str(index)*64,'area_key':key,'municipality_code':'5107925','latest_dataset_id':history['id']}
            with learning_cycle.database() as db:
                db.execute('INSERT INTO learning_plans VALUES(?,?,?,?,NULL)',(plan['id'],key,json.dumps(plan),self.instant.isoformat()))
        storage.source_snapshot('regional-learning:latest',{'id':'batch-test','created_at':self.instant.isoformat(),
            'municipalities':[{'code':'5107925'}]})
        original=storage.connect
        @contextmanager
        def interrupted():
            statements=[]
            with original() as db:
                db.set_trace_callback(statements.append)
                yield db
            if any(s.startswith('INSERT OR IGNORE INTO visual_jobs') for s in statements):
                raise RuntimeError('Interrupted after committed batch')
        with patch.object(visual,'REGISTER_BATCH_SIZE',1),patch.object(storage,'connect',interrupted):
            with self.assertRaisesRegex(RuntimeError,'Interrupted'):visual.register_base()
        with original() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM visual_jobs').fetchone()[0],1)
        self.assertIsNone(storage.source_snapshot('visual-learning:registered'))
        with patch.object(visual,'REGISTER_BATCH_SIZE',1):visual.register_base()
        visual.register_base()
        with original() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM visual_jobs').fetchone()[0],3)
        self.assertEqual(storage.source_snapshot('visual-learning:registered')['result']['base_id'],'batch-test')

    def test_manual_request_reuses_an_inflight_cohort_job(self):
        identifier='b'*64
        with storage.connect() as db:
            visual.schema(db)
            db.execute('INSERT INTO visual_jobs(id,area_key,municipality_code,dataset_id,cutoff,status,priority,next_attempt,lease_until,result) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (identifier,self.area,'5107925',self.history['id'],'2026-10-14','running',0,
                 self.instant.isoformat(),(self.instant+timedelta(minutes=15)).isoformat(),'{}'))
        with patch.object(visual.POOL,'submit') as submit:
            job=visual.start({'dataset_id':self.history['id']})
        submit.assert_not_called()
        self.assertEqual(job['id'],identifier)
        self.assertEqual(job['status'],'running')


if __name__=='__main__':unittest.main()
