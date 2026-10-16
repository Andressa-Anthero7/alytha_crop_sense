import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import regional_calendar as calendars, storage


class RegionalCalendarTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(storage,'DB_PATH',Path(self.temp.name)/'test.sqlite3');p.start();self.addCleanup(p.stop)
        self.record={'crop':'soja','season':'2026/2027','state_code':'51','municipality_code':'5107925',
            'kind':'zarc','source_url':'https://www.gov.br/agricultura/exemplo-de-teste',
            'source_title':'Fixture sintética de teste, não orientação real','reviewed_by':'test fixture',
            'reviewed_at':'2026-10-15','valid_from':'2026-07-01','valid_to':'2027-06-30',
            'windows':[{'from':'2026-09-10','to':'2026-11-30'}],
            'soil':'AD2','cultivar_group':'II','risk_percent':20,'management':'sequeiro'}
        self.data={'declared_crop':'soja','season':'2026/2027','municipality_code':'5107925',
                   'soil':'AD2','cultivar_group':'II','risk_percent':20,'management':'sequeiro'}

    def test_exact_conditions_and_vigency_are_required_and_retrospective_review_is_visible(self):
        calendars.register(self.record)
        result=calendars.compare(self.data,'2026-10-08')
        self.assertEqual(result['status'],'ready')
        self.assertTrue(result['references'][0]['inside'])
        self.assertTrue(result['references'][0]['retrospective_review'])
        for changes in ({'season':'2025/2026'},{'soil':'AD1'},{'municipality_code':'5107909'}):
            self.assertEqual(calendars.compare({**self.data,**changes},'2026-10-08')['status'],'inconclusive')
        self.assertEqual(calendars.compare(self.data,'2027-10-08')['status'],'inconclusive')

    def test_unknown_soil_is_not_silently_filled_and_declaration_is_not_overwritten(self):
        calendars.register(self.record)
        storage.source_snapshot('evolution-window:v1:area',{'from':'2026-09-01','to':'2026-09-30'})
        before=storage.source_snapshot('evolution-window:v1:area')
        data={k:v for k,v in self.data.items() if k!='soil'}
        result=calendars.compare(data,'2026-10-08')
        self.assertIn('soil',result['missing_conditions'])
        self.assertFalse(result['references'])
        self.assertEqual(before,storage.source_snapshot('evolution-window:v1:area'))

    def test_invalid_source_or_missing_normative_conditions_are_rejected(self):
        for changes in ({'source_url':'https://unofficial.test/window'}, {'soil':None},
                        {'kind':'declaration'},{'valid_to':'2026-09-01'}, {'risk_percent':15}):
            with self.assertRaises(ValueError):calendars.register({**self.record,**changes})


if __name__=='__main__':unittest.main()
