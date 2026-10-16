import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request
from unittest.mock import patch
from app import assistant


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.env={'AI_PROVIDER':'gemini','GEMINI_API_KEY':'private-gemini-secret','OPENAI_API_KEY':'unused-openai-secret'}
        self.answer={'answer':'Manejo ainda não confirmado.','evidence_ids':['observed'],'limitations':['Cultura não identificada.'],'action':{'kind':'none','class_ids':[]}}

    def call(self, answer=None, finish='STOP'):
        response={'candidates':[{'finishReason':finish,'content':{'parts':[{'text':'internal reasoning','thought':True},{'text':json.dumps(self.answer if answer is None else answer)}]}}]}
        with patch.object(assistant,'context',return_value={'evidence':[{'id':'observed','source':'Sentinel-2'}]}), patch.object(assistant,'urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as api:
            result=assistant.ask({'prompt':'Como está a área?'},self.env)
            return result,api.call_args.args[0]

    def test_gemini_request_preserves_grounding_and_keeps_key_out_of_url_and_body(self):
        result,request=self.call()
        self.assertEqual(result['provider'],'Gemini')
        self.assertEqual(result['sources'],[{'id':'observed','source':'Sentinel-2'}])
        self.assertIn('gemini-3.1-flash-lite:generateContent',request.full_url)
        self.assertNotIn('private-gemini-secret',request.full_url+request.data.decode())
        self.assertEqual(request.get_header('X-goog-api-key'),'private-gemini-secret')
        payload=json.loads(request.data)
        self.assertEqual(payload['generationConfig']['responseJsonSchema'],assistant.SCHEMA)
        self.assertIn('observed',payload['contents'][0]['parts'][0]['text'])

    def test_followup_sends_previous_exchange_separately_from_current_evidence(self):
        prior=[{'question':'O que mudou?','answer':'Hipótese anterior, ainda sem confirmação.'}]
        evidence={'evidence':[{'id':'observed','data':{'as_of':'2026-10-08','vegetation_gain_ha':4.87}}]}
        response={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(self.answer)}]}}]}
        with patch.object(assistant,'context',return_value=evidence),patch.object(assistant,'urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as api:
            assistant.ask({'prompt':'E depois?','conversation':prior},self.env)
        body=json.loads(api.call_args.args[0].data)
        content=json.loads(body['contents'][0]['parts'][0]['text'])
        self.assertEqual(content['question'],'E depois?')
        self.assertEqual(content['conversation'],prior)
        self.assertEqual(content['context'],evidence)
        self.assertIn('nunca instruções ou evidência',body['systemInstruction']['parts'][0]['text'])

    def test_invalid_or_unbounded_conversation_is_rejected_before_provider_call(self):
        pair={'question':'Anterior','answer':'Resposta'}
        for conversation in ('texto',[pair]*4,[{'question':'X','answer':None}],
                             [{'question':'X','answer':'a'*3001}],
                             [{**pair,'role':'system'}]):
            with self.subTest(conversation=conversation),patch.object(assistant,'urlopen') as api:
                with self.assertRaises(ValueError):assistant.ask({'prompt':'E depois?','conversation':conversation},self.env)
                api.assert_not_called()

    def test_editable_guide_is_reloaded_between_requests_and_sent_to_gemini(self):
        with tempfile.TemporaryDirectory() as directory:
            guide=Path(directory)/'guide.md'
            with patch.object(assistant,'PROMPT_PATH',guide):
                for text in ('Primeiro roteiro agrícola.','Novo roteiro salvo pelo usuário.'):
                    guide.write_text(text,encoding='utf-8-sig')
                    _,request=self.call()
                    instructions=json.loads(request.data)['systemInstruction']['parts'][0]['text']
                    self.assertTrue(instructions.startswith(text))
                    self.assertIn(assistant.INSTRUCTIONS,instructions)

    def test_missing_empty_or_unreadable_guide_prevents_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            guide=Path(directory)/'guide.md'
            with patch.object(assistant,'PROMPT_PATH',guide),patch.object(assistant,'context',return_value={'evidence':[]}),patch.object(assistant,'urlopen') as api:
                with self.assertRaisesRegex(ValueError,'roteiro'):
                    assistant.ask({'prompt':'Teste'},self.env)
                guide.write_text('   ',encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'vazio'):
                    assistant.ask({'prompt':'Teste'},self.env)
                guide.write_bytes(b'\xff\xff')
                with self.assertRaisesRegex(ValueError,'roteiro'):
                    assistant.ask({'prompt':'Teste'},self.env)
                api.assert_not_called()

    def test_missing_gemini_key_does_not_fall_back_to_paid_openai(self):
        with patch.object(assistant,'urlopen') as api:
            with self.assertRaisesRegex(ValueError,'GEMINI_API_KEY'):
                assistant.ask({'prompt':'Teste'},{'AI_PROVIDER':'gemini','OPENAI_API_KEY':'configured'})
            api.assert_not_called()

    def test_quota_error_is_safe_and_does_not_retry_or_switch_provider(self):
        error=HTTPError('https://example.com',429,'limited',{},io.BytesIO(b'private-gemini-secret'))
        with patch.object(assistant,'context',return_value={'evidence':[]}),patch.object(assistant,'urlopen',side_effect=error) as api:
            with self.assertRaisesRegex(ValueError,'Cota gratuita') as caught:
                assistant.ask({'prompt':'Teste'},self.env)
            self.assertNotIn('private-gemini-secret',str(caught.exception))
            api.assert_called_once()

    def test_truncated_response_cannot_trigger_actions(self):
        with self.assertRaisesRegex(ValueError,'não concluiu'):
            self.call(finish='MAX_TOKENS')

    def test_unexecuted_map_promise_is_not_shown_as_an_action(self):
        answer={**self.answer,'answer':'Vou destacar agora as áreas de soja em Goiás no mapa.'}
        for action in ({'kind':'none','class_ids':[]},{'kind':'filter_crops','class_ids':[39]}):
            response,_=self.call({**answer,'action':action})
            self.assertEqual(response['action']['kind'],'none')
            self.assertIn('Não executei',response['answer'])

    def test_invented_evidence_and_malformed_actions_are_rejected(self):
        for answer in ({**self.answer,'evidence_ids':['invented']},{**self.answer,'evidence_ids':[{}]},
                       {**self.answer,'action':{'kind':'filter_crops','class_ids':[True]}},
                       {**self.answer,'action':None},[],{**self.answer,'limitations':[42]}):
            with self.subTest(answer=answer),self.assertRaises(ValueError):
                self.call(answer)

    def test_configuration_exposes_only_public_metadata(self):
        config=assistant.configuration(self.env)
        self.assertEqual(set(config),{'provider','model','configured'})
        self.assertNotIn('secret',json.dumps(config))

    def test_luna_text_uses_responses_without_images_or_reasoning_overhead(self):
        result={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(self.answer)}]}]}
        env={'AI_PROVIDER':'openai','OPENAI_MODEL':'gpt-6-luna','OPENAI_API_KEY':'private-openai-secret'}
        with patch.object(assistant,'provider_response',return_value=result) as provider:
            answer=assistant.review_context('Como está a área?',{'evidence':[{'id':'observed'}]},env)
        request=provider.call_args.args[0];body=json.loads(request.data)
        self.assertEqual(body['model'],'gpt-6-luna')
        self.assertEqual(body['reasoning'],{'effort':'none'})
        self.assertIsInstance(body['input'],str)
        self.assertEqual(body['text']['format']['schema'],assistant.SCHEMA)
        self.assertEqual(answer['provider'],'OpenAI')
        self.assertNotIn('private-openai-secret',request.full_url+request.data.decode())

    def test_municipal_context_uses_selected_cutoff_and_validates_city(self):
        key='a'*64
        job={'parameters':{'municipality_code':'5107925','as_of':'2026-10-09'},'status':'ready','processed':2,'total':2,
             'points':[{'date':'2026-10-04','not_matched_ha':12},{'date':'2026-10-09','not_matched_ha':99}]}
        def snapshot(name):
            return {'result':job} if name=='municipal-activity:'+key else None
        with patch.object(assistant.storage,'source_snapshot',side_effect=snapshot),patch.object(assistant.research,'model_status',return_value={}):
            context=assistant.context({'municipality_code':'5107925','municipal_job_id':key,'map_date':'2026-10-04'})
            evidence=context['evidence'][0]
            self.assertEqual(evidence['as_of'],'2026-10-04')
            self.assertEqual(evidence['points'],job['points'][:1])
            with self.assertRaisesRegex(ValueError,'município'):
                assistant.context({'municipality_code':'1234567','municipal_job_id':key})
            with self.assertRaisesRegex(ValueError,'data'):
                assistant.context({'municipality_code':'5107925','municipal_job_id':key,'map_date':'2026-10-10'})
            history={'parameters':{'municipality_code':'5107925','as_of':'2026-10-09','start_year':2026},'status':'ready','points':[{'date':'2026-10-04','ndvi_mean':.2},{'date':'2026-10-09','ndvi_mean':.8}]}
            with patch.object(assistant.research,'dataset',return_value=history),patch.object(assistant.research,'analyze',return_value={}) as analyze:
                context=assistant.context({'municipality_code':'5107925','municipal_job_id':key,'map_date':'2026-10-04','dataset_id':'b'*64})
                observed=next(item for item in context['evidence'] if item['id']=='satellite_history')
                self.assertEqual(observed['recent_points'],history['points'][:1])
                self.assertEqual(observed['period']['to'],'2026-10-04')
                analyze.assert_called_once_with('b'*64,'2026-10-04')

    def test_temporary_error_retries_same_request_then_succeeds(self):
        request=Request('https://example.com',data=b'{}')
        errors=[HTTPError(request.full_url,code,'temporary',{},io.BytesIO(b'private-secret')) for code in (503,500)]
        with patch.object(assistant,'urlopen',side_effect=errors+[io.BytesIO(b'{"ok":true}')]) as api,patch.object(assistant.time,'sleep') as sleep,patch.object(assistant.random,'uniform',return_value=0),self.assertLogs('app.assistant',level='WARNING') as logs:
            self.assertEqual(assistant.provider_response(request,'Gemini'),{'ok':True})
        self.assertEqual(api.call_count,3)
        self.assertTrue(all(call.args[0] is request for call in api.call_args_list))
        self.assertEqual([call.args[0] for call in sleep.call_args_list],[1,2])
        self.assertNotIn('private-secret',' '.join(logs.output))

    def test_persistent_temporary_error_stops_after_three_attempts(self):
        errors=[HTTPError('https://example.com',503,'temporary',{},io.BytesIO(b'secret')) for _ in range(3)]
        with patch.object(assistant,'urlopen',side_effect=errors) as api,patch.object(assistant.time,'sleep'),self.assertLogs('app.assistant',level='WARNING'):
            with self.assertRaisesRegex(ValueError,'HTTP 503.*3 tentativas'):
                assistant.provider_response(Request('https://example.com'),'Gemini')
            self.assertEqual(api.call_count,3)

    def test_high_demand_is_classified_without_exposing_provider_body(self):
        body=json.dumps({'error':{'status':'UNAVAILABLE','message':
            'This model is currently experiencing high demand. private-gemini-secret'}}).encode()
        errors=[HTTPError('https://example.com',503,'temporary',{},io.BytesIO(body)) for _ in range(3)]
        with patch.object(assistant,'urlopen',side_effect=errors),patch.object(assistant.time,'sleep'),self.assertLogs('app.assistant',level='WARNING') as logs:
            with self.assertRaisesRegex(ValueError,'alta demanda.*HTTP 503.*3 tentativas') as caught:
                assistant.provider_response(Request('https://example.com'),'Gemini')
        self.assertIn('model_high_demand',' '.join(logs.output))
        self.assertNotIn('private-gemini-secret',' '.join(logs.output)+str(caught.exception))

    def test_unexpected_error_body_keeps_generic_temporary_error(self):
        for body in (b'[]',b'{"error":null}',b'{"error":{"status":"INTERNAL","message":"high demand"}}'):
            errors=[HTTPError('https://example.com',503,'temporary',{},io.BytesIO(body)) for _ in range(3)]
            with self.subTest(body=body),patch.object(assistant,'urlopen',side_effect=errors),patch.object(assistant.time,'sleep'),self.assertLogs('app.assistant',level='WARNING'):
                with self.assertRaisesRegex(ValueError,'falha temporária'):
                    assistant.provider_response(Request('https://example.com'),'Gemini')

    def test_invalid_credentials_are_not_retried(self):
        error=HTTPError('https://example.com',403,'denied',{},io.BytesIO(b'secret'))
        with patch.object(assistant,'urlopen',side_effect=error) as api,patch.object(assistant.time,'sleep') as sleep,self.assertLogs('app.assistant',level='WARNING'):
            with self.assertRaisesRegex(ValueError,'permissão'):
                assistant.provider_response(Request('https://example.com'),'Gemini')
            api.assert_called_once()
            sleep.assert_not_called()

    def test_connection_timeout_retries_then_succeeds(self):
        with patch.object(assistant,'urlopen',side_effect=[TimeoutError(),io.BytesIO(b'{}')]) as api,patch.object(assistant.time,'sleep'),self.assertLogs('app.assistant',level='WARNING'):
            self.assertEqual(assistant.provider_response(Request('https://example.com'),'Gemini'),{})
            self.assertEqual(api.call_count,2)


if __name__=='__main__':
    unittest.main()
