"""Reject HTML responses, retry STAC GET, preserve exact scope and cached metadata."""
import gzip
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from app import catalog_search as catalog, storage


def feature(identifier='scene', geometry=None):
    return {'type':'Feature','id':identifier,'collection':'sentinel-2-l2a',
        'geometry':geometry or {'type':'Polygon','coordinates':[[[0,0],[1,0],[1,1],[0,1],[0,0]]]},
        'properties':{'datetime':'2026-10-01T00:00:00Z','eo:cloud_cover':10}}


def collection(features=None,links=None):
    return {'type':'FeatureCollection','features':features if features is not None else [feature()],'links':links or []}


def response(value):
    return io.BytesIO(json.dumps(value).encode())


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.args=Namespace(endpoint=catalog.DEFAULT_ENDPOINT,collection=catalog.DEFAULT_COLLECTION,
                            date_from='2026-10-01',date_to='2026-10-08',max_cloud=40,limit=100)
        self.geometry=feature()['geometry']
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        patcher=patch.object(storage,'DB_PATH',Path(temp.name)/'base.sqlite3');patcher.start();self.addCleanup(patcher.stop)

    def test_html_block_page_or_empty_body_is_retried_with_get(self):
        for body in (b'<html>Request Rejected</html>',b''):
            with self.subTest(body=body),patch.object(catalog,'urlopen',side_effect=[io.BytesIO(body),response(collection())]) as remote:
                result=catalog.request_items(self.args,self.geometry)
                self.assertEqual(result['catalog_transport'],'GET')
                self.assertEqual(len(result['features']),1)
                request=remote.call_args.args[0]
                self.assertEqual(request.get_method(),'GET')
                query=parse_qs(urlsplit(request.full_url).query)
                self.assertEqual(json.loads(query['intersects'][0]),self.geometry)
                self.assertEqual(json.loads(query['query'][0]),{'eo:cloud_cover':{'lte':40}})

    def test_valid_post_and_gzip_remain_supported(self):
        payload=collection()
        for body in (json.dumps(payload).encode(),gzip.compress(json.dumps(payload).encode())):
            with patch.object(catalog,'urlopen',return_value=io.BytesIO(body)) as remote:
                self.assertEqual(catalog.request_items(self.args,self.geometry),payload)
                self.assertEqual(remote.call_count,1)

    def test_complex_bbox_search_filters_holes_and_paginates_exact_intersections(self):
        # Detailed outer ring forces a compact bbox query instead of a huge URL.
        outer=[[i/100,0] for i in range(400)]+[[4,i/100] for i in range(400)]+[[4-i/100,4] for i in range(400)]+[[0,4-i/100] for i in range(400)]+[[0,0]]
        geometry={'type':'Polygon','coordinates':[outer,[[1,1],[3,1],[3,3],[1,3],[1,1]]]}
        hole=feature('hole',{'type':'Polygon','coordinates':[[[1.5,1.5],[2,1.5],[2,2],[1.5,2],[1.5,1.5]]]})
        good=feature('one');other=feature('two')
        self.args.limit=2
        next_url=catalog.DEFAULT_ENDPOINT+'?page=2'
        pages=[collection([hole,good],[{'rel':'next','href':next_url}]),collection([good,other])]
        with patch.object(catalog,'urlopen',side_effect=[response(page) for page in pages]) as remote:
            result=catalog.request_items_get(self.args,geometry)
        self.assertEqual([item['id'] for item in result['features']],['one','two'])
        self.assertEqual(result['catalog_pages'],2)
        query=parse_qs(urlsplit(remote.call_args_list[0].args[0].full_url).query)
        self.assertIn('bbox',query);self.assertNotIn('intersects',query)

    def test_invalid_response_and_external_pagination_are_not_accepted(self):
        for payload in ({'error':'blocked'}, {'type':'FeatureCollection','features':[{}]}):
            with self.assertRaises(catalog.CatalogUnavailable):catalog.read_catalog(response(payload))
        with patch.object(catalog,'urlopen',return_value=response(collection([], [{'rel':'next','href':'https://other.invalid/search'}]))):
            with self.assertRaises(catalog.CatalogUnavailable):catalog.request_items_get(self.args,self.geometry)

    def test_unsaved_query_survives_outage_without_using_another_period(self):
        provider=Mock(return_value=collection())
        first=catalog.consult_items(self.args,self.geometry,provider)
        provider.side_effect=catalog.CatalogUnavailable('provider returned private HTML')
        cached=catalog.consult_items(self.args,self.geometry,provider)
        self.assertEqual(cached['features'],first['features'])
        self.assertEqual(cached['mode'],'local_cache')
        self.assertNotIn('private HTML',cached['message'])
        self.args.date_from='2026-09-01'
        with self.assertRaises(catalog.CatalogUnavailable) as caught:catalog.consult_items(self.args,self.geometry,provider)
        self.assertNotIn('Expecting value',str(caught.exception))

    def test_saved_area_legacy_catalog_is_reused_only_for_same_scope(self):
        area=storage.save_area({'name':'A','municipality':'X','crop':'Não confirmada','season':'2026','geojson':self.geometry})
        storage.save_analysis(area['id'],'catalog',{'from':self.args.date_from,'to':self.args.date_to,'max_cloud':40},collection())
        provider=Mock(side_effect=TimeoutError())
        self.assertEqual(catalog.consult_items(self.args,self.geometry,provider)['mode'],'local_cache')
        different={'type':'Polygon','coordinates':[[[4,4],[5,4],[5,5],[4,5],[4,4]]]}
        with self.assertRaises(catalog.CatalogUnavailable):catalog.consult_items(self.args,different,provider)


if __name__=='__main__':unittest.main()
