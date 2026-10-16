import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import assistant, assistant_tools as tools, agricultural_knowledge, storage


class AssistantToolsTests(unittest.TestCase):
    def test_map_complaint_retries_selected_culture_without_provider(self):
        for prompt in ('vc nao destaco no mapa, nao apareceu','não apareceu nada no mapa'):
            with patch.object(assistant,'provider_response') as provider:
                result=assistant.ask({'prompt':prompt,'state_code':'52','crop_class_ids':[39]}, {})
            self.assertEqual(result['action'],{'kind':'filter_crops','class_ids':[39]})
            provider.assert_not_called()
        self.assertIsNone(tools.retry_map('não apareceu, mas não tente de novo',{'state_code':'52','crop_class_ids':[39]},[]))

    def test_plain_municipality_name_navigates_and_preserves_selected_soy(self):
        city={'kind':'municipality','code':'5215652','name':'Palestina de Goiás','uf':'GO'}
        with patch.object(tools.localities,'search',return_value={'exact':True,'matches':[city]}) as search:
            result=assistant.ask({'prompt':'palestina de goias','state_code':'52','crop_class_ids':[39]}, {})
        search.assert_called_once_with('palestina de goias')
        self.assertEqual(result['action']['region'],city)
        self.assertEqual(result['action']['class_ids'],[39])

    def test_bare_location_does_not_turn_questions_into_navigation(self):
        with patch.object(tools.localities,'search') as search:
            for question in ('e depois?','no mapa','como está o vigor','sim','produção de soja','Olá'):
                self.assertIsNone(tools.bare_location(question,{}))
        search.assert_not_called()

    def test_short_crop_state_and_typo_execute_state_layer(self):
        state={'kind':'state','code':'52','name':'Goiás','uf':'GO'}
        city={'kind':'municipality','code':'5208905','name':'Goiás','uf':'GO'}
        for question in ('soja em goias','oja em goias','mostre soja em Goiás'):
            plan=tools.command(question)
            self.assertEqual(plan['class_ids'],[39])
            with patch.object(tools.localities,'search',return_value={'exact':True,'matches':[state,city]}):
                result=tools.execute(plan,{})
            self.assertEqual(result['action']['region'],state)
            self.assertEqual(result['action']['class_ids'],[39])
        with patch.object(tools.localities,'search',return_value={'exact':True,'matches':[state,city]}):
            result=tools.execute(tools.command('abra a cidade de Goiás'),{})
        self.assertEqual(result['action']['region'],city)
    def test_location_and_crop_are_resolved_together(self):
        for question in ('mostre soja em Sinop MT','onde tem soja em Sinop MT?'):
            plan=tools.command(question)
            self.assertEqual(plan['query'],'sinop mt')
            city={'kind':'municipality','code':'5107909','name':'Sinop','uf':'MT'}
            with patch.object(tools.localities,'search',return_value={'exact':True,'matches':[city]}):
                result=assistant.ask({'prompt':question},{})
            self.assertEqual(result['action']['region'],city)
            self.assertEqual(result['action']['class_ids'],[39])

    def test_ambiguous_location_never_navigates(self):
        with patch.object(tools.localities,'search',return_value={'exact':True,'matches':[
            {'name':'Bom Jesus','uf':'GO'},{'name':'Bom Jesus','uf':'PI'}]}):
            result=tools.execute(tools.command('abra Bom Jesus'),{})
        self.assertEqual(result['action']['kind'],'none')
        self.assertIn('UF',result['answer'])

    def test_negation_and_interpretation_do_not_execute_commands(self):
        for question in ('não abra Sinop','como abrir Sinop?','explique o histórico',
                         'mostre a colheita','onde a soja está com baixo vigor?'):
            self.assertIsNone(tools.command(question))

    def test_history_requires_selected_area_and_monitoring_requires_history(self):
        result=tools.execute(tools.command('analise o histórico da área'),{})
        self.assertEqual(result['action']['kind'],'none')
        result=tools.execute(tools.command('atualize o acompanhamento'),{'area_geojson':{'type':'Polygon'}})
        self.assertEqual(result['action']['kind'],'analyze_area')
        result=tools.execute(tools.command('atualize o acompanhamento'),{'dataset_id':'a'*64})
        self.assertEqual(result['action']['kind'],'update_monitoring')

    def test_concepts_without_city_never_get_default_sorriso_evidence(self):
        with patch.object(storage,'source_snapshot') as read:
            ctx=assistant.context({'prompt':'Como funciona plantio direto?'})
        read.assert_not_called()
        self.assertIsNone(ctx['map']['municipality_code'])
        self.assertTrue(all(e['id'].startswith('agro_') for e in ctx['evidence']))
        self.assertTrue(any(e.get('url') for e in ctx['evidence']))

    def test_cached_city_readings_respect_city_and_cutoff(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(storage,'DB_PATH',Path(temp)/'db.sqlite3'),patch.object(assistant.research,'model_status',return_value={}):
            storage.source_snapshot('municipal-activity:one',{'parameters':{'municipality_code':'5107925','as_of':'2026-10-13'},'status':'ready','points':[{'date':'2026-10-01'},{'date':'2026-10-13'}]})
            storage.source_snapshot('municipal-activity:other',{'parameters':{'municipality_code':'5107909','as_of':'2026-10-14'},'status':'ready','points':[{'date':'2026-10-14'}]})
            storage.source_snapshot('ml:satellite:v1:5107925',{'areas':10,'profiles':[],'period':{'to':'2026-10-13'}})
            ctx=assistant.context({'prompt':'Como está a vegetação?','municipality_code':'5107925','map_date':'2026-10-05'})
        evidence=next(e for e in ctx['evidence'] if e['id']=='cached_municipal_vegetation')
        self.assertEqual(evidence['points'],[{'date':'2026-10-01'}])
        self.assertNotIn('municipal_learned_profiles',[e['id'] for e in ctx['evidence']])

    def test_reference_retrieval_is_bounded_and_separate_from_observations(self):
        self.assertEqual(agricultural_knowledge.retrieve('Olá'),[])
        cards=agricultural_knowledge.retrieve('plantio direto palhada seca água solo ciclo colheita fase')
        self.assertLessEqual(len(cards),3)
        self.assertTrue(all('scope' in c and 'url' in c for c in cards))

    def test_municipal_summary_never_assigns_a_cause_to_low_vigor(self):
        evidence={'map':{'municipality_name':'Sorriso'},'evidence':[
            {'id':'cached_municipal_vegetation','points':[{'date':'2026-10-09',
             'possible_inactive_ha':100,'unknown_ha':20,'pending_ha':5}]}]}
        result=tools.read_reply('Como está a vegetação?',evidence)
        self.assertIn('100 ha',result['answer'])
        self.assertIn('2026-10-09',result['answer'])
        self.assertIn('não identifica preparo',result['answer'])
        self.assertIsNone(tools.read_reply('Como está a vegetação do talhão?',evidence))


if __name__=='__main__':unittest.main()
