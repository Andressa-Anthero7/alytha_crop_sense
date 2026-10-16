import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import weather, storage, research, assistant


class Response:
    def __init__(self, payload): self.payload=payload
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,limit): return json.dumps(self.payload).encode()


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(storage,'DB_PATH',Path(self.temp.name)/'test.sqlite3');p.start();self.addCleanup(p.stop)
        geometry={'type':'Polygon','coordinates':[[[-55,-12],[-54.99,-12],[-54.99,-11.99],[-55,-12]]]}
        self.history={'id':'a'*64,'parameters':{'geometry':geometry,'area_key':research.fingerprint(geometry),
            'municipality_code':'5107925','start_year':2018,'as_of':'2025-09-03'},'points':[],'status':'ready'}
        storage.source_snapshot('history:'+self.history['id'],self.history)
        self.payload={'header':{'time_standard':'UTC','fill_value':-999,'api':{'version':'test'}},
            'parameters':{k:{'units':v[1]} for k,v in weather.PARAMETERS.items()},
            'properties':{'parameter':{
                'PRECTOTCORR':{'20250901':2,'20250902':0,'20250903':3},
                'T2M_MIN':{'20250901':20,'20250902':21,'20250903':22},
                'T2M_MAX':{'20250901':30,'20250902':31,'20250903':32}}}}

    def test_live_response_is_normalized_cached_and_shared_by_grid(self):
        with patch.object(weather,'urlopen',return_value=Response(self.payload)) as fetch:
            first=weather.series(self.history,'2025-09-01','2025-09-03',True)
            other=copy.deepcopy(self.history)
            other['parameters']['geometry']['coordinates'][0][0][0]-=.001
            again=weather.series(other,'2025-09-01','2025-09-03',True)
        self.assertEqual(fetch.call_count,1)
        self.assertTrue(again['cache']['hit'])
        self.assertEqual(first['summary']['precipitation_sum_available_mm'],5)
        self.assertEqual(first['cell'],again['cell'])
        self.assertEqual(first['kind'],'gridded_reanalysis')
        self.assertFalse(first['is_station']);self.assertFalse(first['is_forecast'])

    def test_missing_negative_and_nonfinite_are_not_zero_precipitation(self):
        self.payload['properties']['parameter']['PRECTOTCORR']={'20250901':-999,'20250902':None,'20250903':float('nan')}
        rows=weather.normalize(self.payload,'2025-09-01','2025-09-03')
        self.assertTrue(all(p['precipitation_mm'] is None for p in rows))
        with patch.object(weather,'urlopen',return_value=Response(self.payload)):
            result=weather.series(self.history,'2025-09-01','2025-09-03',True)
        self.assertEqual(result['status'],'inconclusive')
        self.assertIsNone(result['summary']['precipitation_sum_available_mm'])

    def test_units_timezone_and_temperature_order_are_checked(self):
        self.payload['parameters']['T2M_MIN']['units']='F'
        with self.assertRaisesRegex(ValueError,'Unidades'):weather.normalize(self.payload,'2025-09-01','2025-09-03')
        self.payload['parameters']['T2M_MIN']['units']='C';self.payload['header']['time_standard']='LST'
        with self.assertRaisesRegex(ValueError,'UTC'):weather.normalize(self.payload,'2025-09-01','2025-09-03')
        self.payload['header']['time_standard']='UTC'
        self.payload['properties']['parameter']['T2M_MIN']['20250901']=40
        self.assertIsNone(weather.normalize(self.payload,'2025-09-01','2025-09-03')[0]['temperature_max_c'])

    def test_local_synthesis_never_downloads_missing_weather(self):
        with patch.object(weather,'urlopen',side_effect=AssertionError('No network')):
            self.assertIsNone(weather.series(self.history,'2025-09-01','2025-09-03'))
            result=assistant.ask({'prompt':'Faça uma síntese das hipóteses','dataset_id':self.history['id']},{})
        self.assertEqual(result['work']['status'],'inconclusive')

    def test_source_failure_is_a_failed_tool_with_no_invented_weather(self):
        with patch.object(weather,'urlopen',side_effect=OSError('secret internal detail')):
            result=assistant.ask({'prompt':'Consulte chuva e temperatura','dataset_id':self.history['id']},{})
        self.assertEqual(result['work']['status'],'error')
        self.assertNotIn('secret',result['answer'])
        self.assertFalse(result['evidence_ids'])

    def test_date_alignment_tracks_missing_days_without_future_ndvi(self):
        self.history['points']=[{'date':'2025-09-01','ndvi_mean':.4,'valid_pixels':500,'valid_fraction':.9},
                                {'date':'2025-09-04','ndvi_mean':.9,'valid_pixels':500,'valid_fraction':.9}]
        rows=weather.normalize(self.payload,'2025-09-01','2025-09-03');rows[1]['precipitation_mm']=None
        result=weather.cross_windows({'period':{'from':'2025-09-01','to':'2025-09-03'},'points':rows},self.history,'2025-09-03')
        self.assertEqual(len(result['windows']),1)
        window=result['windows'][0]
        self.assertEqual(window['weather_days'],2);self.assertFalse(window['complete'])
        self.assertEqual(window['ndvi_mean'],.4)


if __name__=='__main__':unittest.main()
