import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import assistant,storage


class StateContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=patch.object(storage,'DB_PATH',Path(self.temp.name)/'fixture.sqlite3')
        self.db.start()

    def tearDown(self):
        self.db.stop();self.temp.cleanup()

    def test_state_and_crop_remain_in_followup_without_an_unrelated_history(self):
        with patch.object(assistant.research,'dataset') as history:
            response=assistant.ask({'prompt':'E comparado com a safra anterior?','state_code':'52','crop_class_ids':[39],
                'conversation':[{'question':'soja em Goiás','answer':'Camada carregada.'}]},{})
        history.assert_not_called()
        self.assertIn('Goiás',response['answer'])
        self.assertIn('soja',response['answer'])
        self.assertIn('comparação estadual',response['answer'])
        self.assertEqual(response['action']['kind'],'none')

    def test_current_state_wins_over_previous_conversation(self):
        response=assistant.ask({'prompt':'E o vigor comparado ao ano passado?','state_code':'51',
            'conversation':[{'question':'soja em Goiás','answer':'Goiás carregado.'}]},{})
        self.assertIn('Mato Grosso',response['answer'])
        self.assertNotIn('Goiás',response['answer'])

    def test_saved_state_evidence_is_scoped_and_not_a_vigor_comparison(self):
        for code in ('51','52'):
            storage.source_snapshot('regional-scan:v1:'+code,{'status':'partial','parameters':{'kind':'state','code':code},
                'total':2,'processed':1,'cities':[{'history':{'id':'reference'}}]})
            storage.source_snapshot('ml:satellite:v1:'+code+'00001',{'areas':10,'profiles':[{'id':1}]})
        ctx=assistant.context({'state_code':'52','crop_class_ids':[39]})
        self.assertEqual(ctx['map']['state_name'],'Goiás')
        self.assertEqual(ctx['map']['selected_crops'],['Soja'])
        self.assertTrue(all(e['state_code']=='52' for e in ctx['evidence']))
        coverage=next(e for e in ctx['evidence'] if e['id']=='state_learned_coverage')
        self.assertEqual(coverage['areas'],10)

    def test_invalid_or_mismatched_state_and_old_history_are_rejected(self):
        for data in ({'state_code':'99'},{'state_code':52},
                     {'state_code':'52','municipality_code':'5107925'},
                     {'state_code':'52','dataset_id':'a'*64},
                     {'state_code':'52','map_year':2026},
                     {'state_code':'52','crop_class_ids':[True]}):
            with self.subTest(data=data),self.assertRaises(ValueError):assistant.context(data)

    def test_explicit_map_followup_uses_the_selected_state(self):
        response=assistant.ask({'prompt':'no mapa','state_code':'52',
            'conversation':[{'question':'soja em Goiás','answer':'Camada carregada.'}]},{})
        self.assertEqual(response['action'],{'kind':'filter_crops','class_ids':[39]})
        self.assertIn('Goiás',response['answer'])


if __name__=='__main__':unittest.main()
