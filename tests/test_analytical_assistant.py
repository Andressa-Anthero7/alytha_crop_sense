"""Local integration cases: chronology, continuity, scope and actual work receipts."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import assistant, storage, research, analytical_assistant as tools


class AnalyticalAssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db = patch.object(storage, 'DB_PATH', Path(self.temp.name) / 'test.sqlite3')
        db.start(); self.addCleanup(db.stop)
        network = patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden'))
        network.start(); self.addCleanup(network.stop)
        provider = patch.object(assistant, 'review_context', side_effect=AssertionError('Provider forbidden'))
        provider.start(); self.addCleanup(provider.stop)
        self.geometry = {'type': 'Polygon', 'coordinates': [[[-55,-12],[-54.99,-12],[-54.99,-11.99],[-55,-12]]]}
        self.history = self.save_history('a' * 64)

    def save_history(self, identifier, geometry=None, city='5107925'):
        geometry = geometry or self.geometry
        points = [{'date': f'{year}-09-{day:02}', 'ndvi_mean': .6 if year < 2026 else .2 + day / 200,
                   'valid_fraction': .8, 'valid_pixels': 500}
                  for year in range(2018,2027) for day in (10,20,30)]
        history = {'id': identifier, 'parameters': {'geometry': geometry, 'area_key': research.fingerprint(geometry),
                   'municipality_code': city, 'start_year': 2018, 'as_of': '2026-10-08'},
                   'status': 'ready', 'points': points}
        storage.source_snapshot('history:' + identifier, history)
        return history

    def ask(self, prompt, **data):
        return assistant.ask({'prompt': prompt, 'dataset_id': self.history['id'], **data}, {})

    def spatial(self, status='not_detected', fronts=None):
        job = {'id': 'b'*64, 'parameters': {'area_id': self.history['parameters']['area_key'],
               'as_of': '2026-10-08', 'algorithm_version': 3},
               'status': 'ready', 'periods': [{'from':'2026-09-20','to':'2026-09-24'},
               {'from':'2026-09-25','to':'2026-09-29'}, {'from':'2026-09-30','to':'2026-10-04'}],
               'common_coverage': .8, 'progression': {'status':status, 'fronts':fronts or []}}
        storage.source_snapshot('cv:job:' + job['id'], job)
        return job

    def test_comparison_executes_without_provider_and_persists_result(self):
        result = self.ask('Compare com o histórico das safras anteriores')
        self.assertEqual(result['work']['status'], 'ready')
        self.assertIn('NDVI médio 0.300', result['answer'])
        self.assertIn('faixa central', result['answer'])
        saved = storage.source_snapshot('assistant-work:v1:' + result['work']['id'])['result']
        self.assertEqual(saved['result']['answer'], result['answer'])
        self.assertEqual(saved['result']['evidence'][0]['contract_version'], 1)
        json.dumps(result, allow_nan=False)

    def test_missing_history_is_failed_work_not_completed_analysis(self):
        result = assistant.ask({'prompt':'Compare o histórico das safras'}, {})
        self.assertEqual(result['work']['status'], 'error')
        self.assertIn('Selecione uma área', result['answer'])

    def test_area_city_and_state_mismatches_reject_history(self):
        other = {'type':'Polygon','coordinates':[[[-54,-12],[-53.99,-12],[-53.99,-11.99],[-54,-12]]]}
        for data in ({'municipality_code':'5208707'}, {'state_code':'52'}, {'area_geojson':other}):
            result = self.ask('Compare o histórico das safras', **data)
            self.assertEqual(result['work']['status'], 'error', data)

    def test_same_geometry_resolves_history_without_starting_collection(self):
        result = assistant.ask({'prompt':'Compare o histórico das safras', 'area_geojson':self.geometry}, {})
        self.assertEqual(result['dataset_id'], self.history['id'])

    def test_no_direction_stays_explicit_and_does_not_claim_machine_path(self):
        self.spatial()
        result = self.ask('Qual a direção do esverdeamento?')
        self.assertEqual(result['work']['status'], 'ready')
        self.assertIn('Não foi detectada direção', result['answer'])
        self.assertEqual(result['evidence'][2]['period']['from'], '2026-09-20')

    def test_missing_spatial_data_is_inconclusive(self):
        result = self.ask('Qual a direção do esverdeamento?')
        self.assertEqual(result['work']['status'], 'inconclusive')
        self.assertIn('Falta análise espacial salva', result['answer'])

    def test_direction_references_computed_sectors_and_dates(self):
        self.spatial('detected', [{'signal':'vegetation_gain','direction_label':'leste',
                                  'affected_area_ha':9, 'centroid_distance_m':150}])
        result = self.ask('Qual a direção do esverdeamento?')
        for text in ('leste', '9.00 ha', '2026-09-20', '2026-10-04', 'setores'):
            self.assertIn(text, result['answer'])

    def test_cloudy_history_does_not_invent_comparison(self):
        self.history['points'] = [{**p, 'valid_fraction':.1} for p in self.history['points']]
        storage.source_snapshot('history:' + self.history['id'], self.history)
        result = self.ask('Compare o histórico das safras')
        self.assertEqual(result['work']['status'], 'inconclusive')
        self.assertNotIn('NDVI médio', result['answer'])

    def test_window_can_be_declared_in_portuguese_and_remains_scoped(self):
        result = self.ask('Registre minha janela de plantio de 01/09/2026 a 30/09/2026')
        self.assertEqual(result['work']['status'], 'ready')
        self.assertIn('fora', result['answer'])
        self.assertIn('2026-09-01', result['answer'])
        self.assertTrue(result['evidence'][1]['data']['retrospective_declaration'])
        self.history = self.save_history('c'*64, city='5208707', geometry={'type':'Polygon',
            'coordinates':[[[-54,-12],[-53.99,-12],[-53.99,-11.99],[-54,-12]]]})
        self.assertIn('Não há janela', self.ask('Qual a janela de plantio?')['answer'])

    def test_window_rejects_reversed_or_incomplete_dates(self):
        for dates in ('30/09/2026 a 01/09/2026', '01/09/2026', '31/02/2026 a 01/09/2026'):
            result = self.ask('Registre minha janela de plantio de ' + dates)
            self.assertEqual(result['work']['status'], 'error')

    def test_synthesis_separates_measurement_hypothesis_conflict_and_missing(self):
        self.ask('Registre minha janela de plantio de 01/09/2026 a 30/09/2026')
        self.spatial('detected', [{'signal':'vegetation_gain','direction_label':'leste',
                                  'affected_area_ha':9, 'centroid_distance_m':150}])
        result = self.ask('Faça uma síntese das hipóteses e alternativas')
        for field in ('measurements', 'hypotheses', 'divergences', 'missing', 'next_check'):
            self.assertTrue(result['synthesis'][field])
        self.assertIn('reb rota'.replace(' ', ''), result['answer'])
        self.assertIn('aumentando, mas permanece abaixo', result['answer'])
        self.assertIn('fora da janela', result['answer'])

    def test_context_preserves_area_season_and_cutoff_across_turns(self):
        first = self.ask('Compare o histórico das safras', season='2026/27', map_date='2026-10-04')
        result = assistant.ask({'prompt':'E a direção do esverdeamento?',
                                'conversation_id':first['conversation_id']}, {})
        self.assertEqual(result['dataset_id'], self.history['id'])
        self.assertEqual(result['as_of'], '2026-10-04')
        self.assertEqual(result['conversation_context']['season'], '2026/27')

    def test_explicit_location_change_drops_previous_area(self):
        first = self.ask('Compare o histórico das safras', municipality_code='5107925')
        result = assistant.ask({'prompt':'Compare o histórico das safras',
                               'conversation_id':first['conversation_id'], 'municipality_code':'5208707'}, {})
        self.assertEqual(result['work']['status'], 'error')
        self.assertNotIn('dataset_id', result['conversation_context'])

    def test_explicit_new_area_wins_and_cutoff_cannot_exceed_history(self):
        first = self.ask('Compare o histórico das safras')
        other = self.save_history('c'*64)
        result = self.ask('Compare o histórico das safras', dataset_id=other['id'], conversation_id=first['conversation_id'])
        self.assertEqual(result['dataset_id'], other['id'])
        result = self.ask('Compare o histórico das safras', map_date='2026-10-09')
        self.assertEqual(result['work']['status'], 'error')

    def test_explicit_season_and_cutoff_in_prompt_override_old_map_defaults(self):
        result=self.ask('Compare o histórico até 04/10/2026 para a safra 2026/27',map_date='2026-10-08',season='2025/2026')
        self.assertEqual(result['as_of'],'2026-10-04')
        self.assertEqual(result['conversation_context']['season'],'2026/2027')
        self.assertEqual(result['conversation_context']['map_date'],'2026-10-04')

    def test_legacy_provider_context_respects_cutoff_and_carries_contract(self):
        from app import regional_learning, learning_cycle, visual_learning, crop_monitoring
        with patch.object(research,'analyze',return_value={}) as analyze, \
             patch.object(research,'model_status',return_value={}), \
             patch.object(regional_learning,'city_evidence',return_value=None), \
             patch.object(learning_cycle,'evidence',return_value=None), \
             patch.object(visual_learning,'evidence',return_value=None), \
             patch.object(crop_monitoring,'report',return_value={}):
            result=assistant.context({'dataset_id':self.history['id'],'map_date':'2026-09-25'})
        analyze.assert_called_once_with(self.history['id'],'2026-09-25')
        history=next(e for e in result['evidence'] if e['id']=='satellite_history')
        self.assertTrue(all(p['date']<='2026-09-25' for p in history['recent_points']))
        self.assertEqual(history['contract_version'],1)
        self.assertEqual(history['provenance']['version'],1)
        self.assertEqual(history['area_key'],self.history['parameters']['area_key'])


if __name__ == '__main__':
    unittest.main()
