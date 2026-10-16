import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import evolution_index as index,storage


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=patch.object(storage,'DB_PATH',Path(self.temp.name)/'db.sqlite3');self.db.start()
        self.history={'parameters':{'municipality_code':'5107925','geometry':{'type':'Polygon','coordinates':[[[-55,-12],[-54.99,-12],[-54.99,-11.99],[-55,-11.99],[-55,-12]]]}}}
        self.current={'current':{'usable':True,'slope_day':.006,'observations':6,'mean_observed_fraction':1,'last_observation':'2026-10-13','trend':'aumento'}}
        self.spatial={'status':'ready','observed_area_ha':10,'vegetation_gain_ha':10,'vegetation_loss_ha':0,'progression':{'status':'detected','fronts':[{'signal':'vegetation_gain','affected_area_ha':10,'spatial_order_r2':.75}]}}
        self.cover={'fraction':.8,'year':2025}
        self.window={'from':'2026-09-01','to':'2026-11-01'}
    def tearDown(self):self.db.stop();self.temp.cleanup()
    def score(self,**kw):
        result=index.calculate(self.history,'2026-10-13',kw.get('comparison',self.current),kw.get('spatial',self.spatial),kw.get('cover',self.cover),kw.get('window',self.window))
        return result['scores']['vegetation_gain']
    def test_full_evidence_is_100_points_not_probability(self):
        result=index.calculate(self.history,'2026-10-13',self.current,self.spatial,self.cover,self.window)
        self.assertEqual(result['scores']['vegetation_gain']['value'],100)
        self.assertFalse(result['is_probability']);self.assertTrue(result['experimental'])
        self.assertEqual(sum(index.WEIGHTS.values()),100)
    def test_missing_factors_are_not_renormalized(self):
        score=self.score(spatial=None,cover=None,window=None)
        self.assertEqual(score['available_weight'],35)
        self.assertEqual(score['value'],35)
    def test_no_change_does_not_score_high_from_context_alone(self):
        comparison=copy.deepcopy(self.current);comparison['current']['slope_day']=0
        spatial=copy.deepcopy(self.spatial);spatial.update(vegetation_gain_ha=0,vegetation_loss_ha=0,progression={'status':'not_detected','fronts':[]})
        self.assertEqual(self.score(comparison=comparison,spatial=spatial)['value'],30)
    def test_insufficient_readings_have_null_score(self):
        score=self.score(comparison={'current':{'usable':False}})
        self.assertIsNone(score['value']);self.assertEqual(score['level'],'insuficiente')
    def test_mixed_changes_reduce_spatial_contribution(self):
        spatial=copy.deepcopy(self.spatial);spatial['vegetation_loss_ha']=10
        factors=self.score(spatial=spatial)['factors']
        self.assertEqual(next(f for f in factors if f['id']=='spatial')['points'],0)
    def test_harvest_does_not_use_planting_calendar(self):
        result=index.calculate(self.history,'2026-10-13',self.current,self.spatial,self.cover,self.window)
        factor=next(f for f in result['scores']['vegetation_loss']['factors'] if f['id']=='calendar')
        self.assertFalse(factor['available']);self.assertEqual(factor['points'],0)
    def test_historical_cover_is_geometric_and_not_future_landcover(self):
        feature={'geometry':self.history['parameters']['geometry']}
        storage.source_snapshot('municipal-soy:v1:5107925',{'year':2025,'features':[feature]})
        self.assertAlmostEqual(index.historical_cover(self.history,'2026-10-13')['fraction'],1)
        self.assertIsNone(index.historical_cover(self.history,'2025-10-13'))
        outside=copy.deepcopy(self.history)
        outside['parameters']['geometry']['coordinates']=[[[x+1,y] for x,y in ring] for ring in feature['geometry']['coordinates']]
        self.assertEqual(index.historical_cover(outside,'2026-10-13')['fraction'],0)
    def test_declared_calendar_is_bounded_and_does_not_leak_to_past(self):
        with patch.object(storage,'now',return_value='2026-10-13T12:00:00+00:00'):
            record=index.planting_window(self.history,{'planting_window':self.window},'2026-10-13')
        self.assertIn('declarada',record['source'])
        self.assertIsNone(index.planting_window(self.history,{},'2026-10-12'))
        with self.assertRaises(ValueError):index.planting_window(self.history,{'planting_window':{'from':'2026-01-01','to':'2026-12-31'}},'2026-10-13')


if __name__=='__main__':unittest.main()
