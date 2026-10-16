"""No external calls: quota fallback must preserve geometry, dates and provenance."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from app import local_ndvi, storage, web_app


def polygon(west=0, south=0, east=1, north=1):
    return {'type': 'Polygon', 'coordinates': [[[west,south],[east,south],[east,north],[west,north],[west,south]]]}


def point(day, mean=.4):
    return {'date': '2026-10-' + day, 'ndvi_mean': mean, 'valid_pixels': 100, 'valid_fraction': .8}


class LocalNdviTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        for field, value in ((storage, {'DB_PATH': Path(temporary.name)/'base.sqlite3'}),
                             (local_ndvi, {'BLOCKED_UNTIL': 0, 'BLOCKED_REASON': ''})):
            patcher = patch.multiple(field, **value); patcher.start(); self.addCleanup(patcher.stop)
        self.geometry = polygon()

    def history(self, key='a', geometry=None, points=None):
        storage.source_snapshot('history:'+key, {'parameters': {'geometry': geometry or self.geometry},
            'source': 'Sentinel-2 L2A', 'points': points if points is not None else [point('01'),point('06')]})

    def denied(self, code=403):
        return HTTPError('https://example.invalid', code, 'Forbidden', {}, io.BytesIO(json.dumps({
            'error': {'code':'ACCESS_INSUFFICIENT_PROCESSING_UNITS', 'message':'private-provider-details'}}).encode()))

    def test_quota_uses_same_polygon_and_skips_repeated_denied_requests(self):
        self.history(points=[point('01'),point('06'),point('11')])
        provider=Mock(side_effect=self.denied())
        for _ in range(2):
            result=local_ndvi.consult(self.geometry,'2026-10-01','2026-10-08',provider)
            self.assertEqual(result['reason'],'processing_quota')
            self.assertEqual(result['scope'],'exact_area')
            self.assertEqual([p['date'] for p in result['points']],['2026-10-01','2026-10-06'])
            self.assertFalse(result['new_collection'])
            self.assertNotIn('private-provider-details',json.dumps(result))
        provider.assert_called_once()

    def test_contained_samples_are_separate_and_other_geometries_are_excluded(self):
        self.history('inside-a',polygon(.1,.1,.2,.2),[point('01',.2)])
        self.history('inside-b',polygon(.6,.6,.8,.8),[point('01',.8)])
        self.history('outside',polygon(3,3,4,4))
        self.history('intersecting',polygon(.9,.9,1.1,1.1))
        self.history('larger',polygon(-1,-1,2,2))
        result=local_ndvi.fallback(self.geometry,'2026-10-01','2026-10-08','processing_quota')
        self.assertEqual(result['scope'],'contained_sample')
        self.assertEqual(result['total_series'],2)
        self.assertIn('não representa toda a área',result['message'])
        self.assertEqual({s['points'][0]['ndvi_mean'] for s in result['series']},{.2,.8})
        self.assertIn(result['points'][0]['ndvi_mean'],(.2,.8))

    def test_identical_shape_with_reversed_ring_merges_dates_and_prefers_exact(self):
        reverse=copy.deepcopy(self.geometry);reverse['coordinates'][0].reverse()
        self.history('one',points=[point('01')])
        self.history('two',reverse,[point('06')])
        self.history('sample',polygon(.1,.1,.3,.3))
        result=local_ndvi.fallback(self.geometry,'2026-10-01','2026-10-08','access_denied')
        self.assertEqual(result['scope'],'exact_area')
        self.assertEqual(len(result['series']),1)
        self.assertEqual(len(result['points']),2)

    def test_no_credentials_does_not_call_provider_or_use_another_area(self):
        self.history('elsewhere',polygon(5,5,6,6))
        provider=Mock()
        result=local_ndvi.consult(self.geometry,'2026-10-01','2026-10-08',provider,configured=False)
        provider.assert_not_called()
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(result['points'],[])
        self.assertIsNone(result['available_period'])

    def test_old_dates_are_offered_without_filling_the_requested_period(self):
        self.history(points=[point('01')])
        result=local_ndvi.fallback(self.geometry,'2026-10-06','2026-10-08','access_denied')
        self.assertEqual(result['points'],[])
        self.assertEqual(result['available_period'],{'from':'2026-10-01','to':'2026-10-01'})

    def test_remote_success_is_cached_even_for_unsaved_drawings(self):
        provider=Mock(return_value={'points':[point('01')],'source':'Sentinel-2 L2A'})
        first=local_ndvi.consult(self.geometry,'2026-10-01','2026-10-08',provider)
        self.assertEqual(first['mode'],'remote')
        with patch.object(local_ndvi,'local_series',side_effect=AssertionError('Exact cache needs no full scan')):
            cached=local_ndvi.consult(self.geometry,'2026-10-01','2026-10-08',provider)
        provider.assert_called_once()
        self.assertEqual(cached['mode'],'local_cache')
        self.assertEqual(cached['points'],first['points'])
        self.assertNotIn('indisponível',cached['message'])

    def test_saved_analysis_is_available_without_a_history_job(self):
        area=storage.save_area({'name':'A','municipality':'X','crop':'Não confirmada','season':'2026','geojson':self.geometry})
        storage.save_analysis(area['id'],'ndvi',{}, {'points':[point('01')]})
        provider=Mock(side_effect=URLError('offline'))
        result=local_ndvi.consult(self.geometry,'2026-10-01','2026-10-08',provider)
        self.assertEqual(result['points'],[point('01')])
        self.assertEqual(len(storage.history(area['id'])),1)

    def test_invalid_observations_are_not_reused_or_interpolated(self):
        self.history(points=[point('01'),point('01'),{**point('03'),'available':'2026-10-09'},point('06','NaN'),point('07',True),point('08',2),{'date':'bad','ndvi_mean':.3}])
        result=local_ndvi.fallback(self.geometry,'2026-10-01','2026-10-08','access_denied')
        self.assertEqual(result['points'],[point('01')])

    def test_http_handler_returns_local_evidence_after_403_without_saving_fake_full_area_analysis(self):
        self.history('sample',polygon(.1,.1,.2,.2))
        payload=json.dumps({'geojson':self.geometry,'from':'2026-10-01','to':'2026-10-08'}).encode()
        handler=object.__new__(web_app.Handler);handler.headers={'Content-Length':str(len(payload))};handler.rfile=io.BytesIO(payload)
        with patch.object(web_app,'read_app_env',return_value={'CDSE_CLIENT_ID':'test','CDSE_CLIENT_SECRET':'test'}), \
             patch.object(web_app,'request_ndvi_series',side_effect=self.denied()), \
             patch.object(storage,'save_analysis') as save, patch.object(handler,'_send_json') as send:
            handler._handle_ndvi_series()
        save.assert_not_called()
        self.assertEqual(send.call_args.args[0]['scope'],'contained_sample')
        self.assertEqual(send.call_args.kwargs.get('status',200),200)

    def test_remote_cross_year_request_is_split_and_combined_in_date_order(self):
        def fetch(geometry, first, last):
            return {'points':[{**point('01'),'date':first}],'source':'Sentinel-2 L2A'}
        provider=Mock(side_effect=fetch)
        result=local_ndvi.consult(self.geometry,'2023-03-01','2024-03-01',provider)
        self.assertEqual([(c.args[1],c.args[2]) for c in provider.call_args_list],
                         [('2023-03-01','2023-12-31'),('2024-01-01','2024-03-01')])
        self.assertEqual([p['date'] for p in result['points']],['2023-03-01','2024-01-01'])
        local_ndvi.consult(self.geometry,'2023-03-01','2024-03-01',provider)
        self.assertEqual(provider.call_count,2)

    def test_quota_after_one_year_preserves_collected_chunk_and_other_saved_years(self):
        self.history(points=[{**point('01'),'date':'2026-01-01'}])
        provider=Mock(side_effect=[{'points':[{**point('01'),'date':'2025-12-15'}]},self.denied()])
        result=local_ndvi.consult(self.geometry,'2025-12-15','2026-02-15',provider)
        self.assertEqual(result['reason'],'processing_quota')
        self.assertEqual([p['date'] for p in result['points']],['2025-12-15','2026-01-01'])
        self.assertEqual(provider.call_count,2)

    def test_http_handler_accepts_multiyear_local_history(self):
        self.history(points=[{**point('01'),'date':day} for day in ('2018-01-01','2020-02-29','2025-12-31','2026-01-01')])
        payload=json.dumps({'geojson':self.geometry,'from':'2018-01-01','to':'2026-01-01'}).encode()
        handler=object.__new__(web_app.Handler);handler.headers={'Content-Length':str(len(payload))};handler.rfile=io.BytesIO(payload)
        with patch.object(web_app,'read_app_env',return_value={}),patch.object(web_app,'request_ndvi_series') as provider,patch.object(handler,'_send_json') as send:
            handler._handle_ndvi_series()
        provider.assert_not_called()
        result=send.call_args.args[0]
        self.assertEqual(result['mode'],'local_cache')
        self.assertEqual(len(result['points']),4)
        self.assertEqual(result['requested_period'],{'from':'2018-01-01','to':'2026-01-01'})


if __name__ == '__main__':
    unittest.main()
