"""Offline inventory: isolation, provenance, temporal leakage and failure handling."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import assistant, local_inventory as inventory, storage


class LocalInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / 'outputs/vision/assets'
        self.assets.mkdir(parents=True)
        self.patch_root = patch.object(inventory, 'DATA_ROOT', self.root)
        self.patch_db = patch.object(storage, 'DB_PATH', self.root / 'monitoring.sqlite3')
        self.patch_root.start(); self.patch_db.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.patch_root.stop); self.addCleanup(self.patch_db.stop)
        with storage.connect():
            pass

    def history(self, identifier='a'*64, area='area-a', city='5107925'):
        storage.source_snapshot('history:' + identifier, {
            'id': identifier, 'parameters': {'area_key': area, 'municipality_code': city, 'as_of': '2026-10-15'},
            'status': 'partial', 'points': [{'date': '2026-09-25'}, {'date': '2026-10-15'}]})

    def asset(self, identifier='image-a', area='area-a', period=None, **extra):
        preview = self.assets / (identifier + '.png')
        preview.write_bytes(b'\x89PNG\r\n\x1a\nlocal fixture')
        data = {'id': identifier, 'area_key': area, 'period': period or {'from': '2026-09-23', 'to': '2026-09-27'},
                'path': str(preview), 'source_path': str(self.root / 'rasters/a.tif'),
                'sha256': hashlib.sha256(preview.read_bytes()).hexdigest(), 'kind': 'ndvi',
                'source_resolution_m': 10, 'native_size': [98,222], 'valid_fraction': .8, 'valid_pixels': 90}
        data.update(extra)
        (self.assets / (identifier + '.json')).write_text(json.dumps(data), encoding='utf-8')
        return preview

    def test_missing_database_is_not_created(self):
        storage.DB_PATH.unlink()
        result = inventory.inventory()
        self.assertFalse(storage.DB_PATH.exists())
        self.assertFalse(result['summary']['database_available'])
        self.assertEqual(result['summary']['listed_histories'], 0)
        self.assertIn('Banco local ainda não existe.', result['issues'])

    def test_read_only_does_not_change_database_or_download(self):
        self.history(); self.asset()
        before = storage.DB_PATH.read_bytes()
        with patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden')):
            result = inventory.inventory()
        self.assertEqual(storage.DB_PATH.read_bytes(), before)
        self.assertEqual(result['mode'], 'local_read_only')
        self.assertEqual(result['summary']['matching_histories'], 1)
        self.assertEqual(result['summary']['ndvi_previews'], 1)
        self.assertEqual(result['summary']['true_color_previews'], 0)

    def test_selected_city_and_cutoff_exclude_other_area_and_future_image(self):
        self.history()
        self.history('b'*64, 'area-b', '5208707')
        self.asset(); self.asset('other', 'area-b')
        self.asset('future', period={'from':'2026-10-13','to':'2026-10-17'})
        result = inventory.inventory({'municipality_code':'5107925', 'map_date':'2026-10-01'})
        self.assertEqual(result['summary']['matching_histories'], 1)
        self.assertEqual(result['summary']['ndvi_previews'], 1)
        history = next(e for e in result['evidence'] if e['kind']=='ndvi_history')
        self.assertEqual(history['quality']['observations'], 1)
        self.assertEqual(history['period']['to'], '2026-09-25')
        self.assertTrue(all(e['area_key']=='area-a' for e in result['evidence']))

    def test_dataset_and_city_mismatch_rejected(self):
        self.history()
        with self.assertRaisesRegex(ValueError, 'escopo'):
            inventory.inventory({'dataset_id':'a'*64, 'municipality_code':'5208707'})

    def test_geometry_is_not_overridden_by_dataset(self):
        self.history()
        geometry={'type':'Polygon','coordinates':[[[-55,-12],[-54.99,-12],[-54.99,-11.99],[-55,-12]]]}
        with self.assertRaisesRegex(ValueError, 'escopo'):
            inventory.inventory({'dataset_id':'a'*64,'area_geojson':geometry})

    def test_cutoff_before_any_observation_does_not_imply_usable_history(self):
        self.history()
        result = inventory.inventory({'map_date':'2026-01-01'})
        self.assertEqual(result['summary']['histories_with_observations'],0)
        self.assertIsNone(result['evidence'][0]['period']['to'])

    def test_missing_or_changed_preview_is_not_available(self):
        self.asset().unlink()
        self.asset('changed').write_bytes(b'changed')
        result = inventory.inventory()
        self.assertEqual(result['summary']['image_metadata'], 2)
        self.assertEqual(result['summary']['available_previews'], 0)
        self.assertEqual({e['quality']['integrity'] for e in result['evidence']}, {'missing','hash_mismatch'})

    def test_invalid_metadata_is_a_visible_issue(self):
        (self.assets/'broken.json').write_text('{oops', encoding='utf-8')
        result=inventory.inventory()
        self.assertEqual(result['summary']['image_metadata'], 0)
        self.assertTrue(any('broken.json' in e for e in result['issues']))

    def test_external_file_reference_is_not_read(self):
        self.asset(path=str(self.root.parent/'outside.png'))
        result=inventory.inventory()
        self.assertEqual(result['summary']['available_previews'],0)
        self.assertIsNone(result['evidence'][0]['data']['preview_resource'])

    def test_busy_database_is_not_reported_as_empty_history(self):
        with patch.object(inventory.sqlite3,'connect',side_effect=sqlite3.OperationalError('locked')):
            reply=inventory.reply({})
        self.assertFalse(reply['inventory']['summary']['database_available'])
        self.assertIn('ainda não conferidos',reply['answer'])
        self.assertTrue(any('ocupado' in e for e in reply['limitations']))

    def test_envelope_records_provenance_without_claiming_bands(self):
        self.history()
        e=inventory.inventory()['evidence'][0]
        self.assertEqual(e['contract_version'],1)
        self.assertEqual(e['provenance']['resource'],'sqlite:history:'+'a'*64)
        self.assertEqual(e['quality']['pixel_quality'],'not_evaluated')
        self.assertEqual(e['data']['raw_bands_available'],'not_implied_by_time_series')

    def test_readable_raster_header_and_missing_band_semantics(self):
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        folder=self.root/'rasters';folder.mkdir()
        with rasterio.open(folder/'a.tif','w',driver='GTiff',height=4,width=3,count=2,dtype='float32',
                           crs='EPSG:32721',transform=from_origin(600000,8600000,10,10)) as ds:
            ds.write(np.ones((2,4,3),dtype='float32'))
        self.asset()
        result=inventory.inventory()
        raster=next(e for e in result['evidence'] if e['kind']=='raster')
        self.assertEqual(raster['data']['band_count'],2)
        self.assertEqual(raster['data']['native_size'],[3,4])
        self.assertEqual(raster['data']['band_semantics'],'not_verified_by_inventory')

    def test_assistant_inventory_does_not_call_provider_or_existing_context(self):
        self.asset()
        with patch.object(assistant,'review_context',side_effect=AssertionError('No provider')), \
             patch.object(assistant,'context',side_effect=AssertionError('No collection context')):
            reply=assistant.ask({'prompt':'Quais imagens temos salvas?'},{})
        self.assertEqual(reply['intent'],'local_inventory')
        self.assertEqual(reply['action']['kind'],'none')
        self.assertIn('1 NDVI',reply['answer'])

    def test_inventory_detection_does_not_capture_general_agronomic_question(self):
        for text in ['Quais dados meteorológicos ajudam a explicar a emergência?',
                     'Como funciona o NDVI?', 'Não mostre o inventário']:
            self.assertFalse(inventory.requested(text),text)
        for text in ['Mostre o inventário local','Que dados temos disponíveis?', 'O que temos salvo nesta área?']:
            self.assertTrue(inventory.requested(text),text)

    def test_invalid_scope_rejected(self):
        for data in [{'dataset_id':'oops'}, {'state_code':'51','municipality_code':'5208707'},
                     {'map_date':'2026-02-30'}, {'map_date':42}]:
            with self.assertRaises(ValueError):inventory.inventory(data)

    def test_history_list_limit_does_not_drop_image_area_links(self):
        self.history('a'*64,'area-a')
        self.history('b'*64,'area-b')
        self.asset('other','area-b')
        with patch.object(inventory,'LIMIT',1):
            result=inventory.inventory({'municipality_code':'5107925'})
        self.assertEqual(result['summary']['matching_histories'],2)
        self.assertEqual(result['summary']['listed_histories'],1)
        self.assertEqual(result['summary']['ndvi_previews'],1)

    def test_get_endpoint_and_invalid_query(self):
        from app.web_app import Handler
        handler=object.__new__(Handler)
        handler.path='/api/local-inventory?map_date=2026-10-01'
        with patch.object(handler,'_send_json') as send:
            handler.do_GET()
        self.assertEqual(send.call_args.args[0]['scope']['map_date'],'2026-10-01')
        handler.path='/api/local-inventory?map_date=invalid'
        with patch.object(handler,'_send_json') as send:
            handler.do_GET()
        self.assertEqual(send.call_args.kwargs['status'],400)


if __name__=='__main__':
    unittest.main()
