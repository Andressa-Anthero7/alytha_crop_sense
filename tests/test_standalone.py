"""HTTP and configuration checks without external services or credentials."""

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import web_app
from app import storage
from app import research


class StandaloneTests(unittest.TestCase):
    def test_crop_map_returns_pending_while_raster_worker_is_blocked(self):
        from concurrent.futures import ThreadPoolExecutor
        entered, release = threading.Event(), threading.Event()
        params={'bounds':[-55.2,-12.5,-55.19,-12.49],'year':2025,'class_id':39}
        result={'type':'FeatureCollection','features':[]}
        def slow_raster(data):
            entered.set()
            if not release.wait(5): raise TimeoutError('test worker was not released')
            return result
        pool=ThreadPoolExecutor(max_workers=1)
        try:
            with patch.object(web_app.map_layers,'POOL',pool), patch.object(web_app.data_sources,'mapbiomas',side_effect=slow_raster) as raster:
                request=Request(self.base+'/api/sources/mapbiomas/jobs',data=json.dumps(params).encode(),headers={'Content-Type':'application/json'})
                with urlopen(request,timeout=2) as response:
                    self.assertEqual(response.status,202)
                    job=json.load(response)
                self.assertTrue(entered.wait(1))
                with urlopen(self.base+'/api/sources/mapbiomas/jobs/'+job['id'],timeout=2) as response:
                    self.assertEqual(json.load(response)['status'],'loading')
                with urlopen(request,timeout=2) as response:
                    self.assertEqual(json.load(response)['id'],job['id'])
                release.set()
                pool.shutdown(wait=True)
                with urlopen(self.base+'/api/sources/mapbiomas/jobs/'+job['id']) as response:
                    ready=json.load(response)
                self.assertEqual(ready['status'],'ready')
                self.assertEqual(ready['result'],result)
                raster.assert_called_once()
        finally:
            release.set()
            pool.shutdown(wait=True)

    def test_disconnected_browser_does_not_trigger_second_json_response(self):
        handler=object.__new__(web_app.Handler)
        with patch.object(handler,'send_response',side_effect=ConnectionAbortedError()) as send:
            handler._send_json({'status':'ready'})
            send.assert_called_once_with(200)

    def test_crop_monitoring_route_keeps_dataset_and_date(self):
        body={'dataset_id':'a'*64,'date':'2026-10-08','spatial_job_id':'b'*64}
        with patch.object(web_app.crop_monitoring,'create',return_value={'status':'ready','scope':'recorte'}) as operation:
            request=Request(self.base+'/api/crop-monitoring',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urlopen(request) as response:self.assertEqual(json.load(response)['status'],'ready')
            operation.assert_called_once_with(body)
    def test_activity_map_endpoint_supports_geometry_and_state_only_updates(self):
        result={'dates':['2026-10-09'],'states':[['unknown']]}
        with patch.object(web_app.municipal_activity,'map_assessment',return_value=result) as operation:
            with urlopen(self.base+'/api/soy-activity/municipality/'+'d'*64+'/map?geometry=0') as response:self.assertEqual(json.load(response),result)
            operation.assert_called_once_with('d'*64,False,None)
    def test_spatial_routes_queue_and_retrieve_pixel_analysis(self):
        result={'id':'e'*64,'status':'loading','processed':0}
        with patch.object(web_app.spatial_activity,'start',return_value=result) as operation:
            request=Request(self.base+'/api/spatial-activity',data=b'{}',headers={'Content-Type':'application/json'})
            with urlopen(request) as response:self.assertEqual(json.load(response),result)
            operation.assert_called_once_with({})
        with patch.object(web_app.spatial_activity,'get',return_value=result) as operation:
            with urlopen(self.base+'/api/spatial-activity/'+result['id']) as response:self.assertEqual(json.load(response),result)
            operation.assert_called_once_with(result['id'])
    def test_municipal_activity_endpoints_use_selected_city(self):
        result={'id':'d'*64,'status':'loading','points':[]}
        with patch.object(web_app.municipal_activity,'start',return_value=result) as operation:
            request=Request(self.base+'/api/soy-activity/municipality',data=json.dumps({'municipality_code':'5107925'}).encode(),headers={'Content-Type':'application/json'})
            with urlopen(request) as response:self.assertEqual(json.load(response),result)
            operation.assert_called_once_with({'municipality_code':'5107925'})
        with patch.object(web_app.municipal_activity,'get',return_value=result) as operation:
            with urlopen(self.base+'/api/soy-activity/municipality/'+result['id']) as response:self.assertEqual(json.load(response),result)
            operation.assert_called_once_with(result['id'])

    def test_soy_activity_endpoint_returns_temporal_assessment(self):
        payload={'geojson':{'type':'Feature','geometry':{'type':'Polygon','coordinates':[]},'properties':{'source':'MapBiomas','class_id':39}}}
        result={'points':[],'summary':{'status':'unknown'},'period':{'from':'2026-08-09','to':'2026-10-08'}}
        with patch.object(web_app.inactive_soy,'activity',return_value=result) as operation:
            request=Request(self.base+'/api/soy-activity',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with urlopen(request) as response:
                self.assertEqual(json.load(response),result)
            operation.assert_called_once_with(payload)

    def test_history_endpoint_resumes_interrupted_job(self):
        key='a'*64
        history={'id':key,'status':'loading','parameters':{'start_year':2018},'points':[]}
        storage.source_snapshot('history:'+key,history)
        try:
            with patch.object(research.POOL,'submit') as submit:
                with urlopen(self.base+'/api/research/history/'+key) as response:
                    self.assertEqual(json.load(response)['status'],'loading')
                with urlopen(self.base+'/api/research/history/'+key) as response:
                    response.read()
                submit.assert_called_once_with(research.build_history,key,history['parameters'])
        finally: research.RUNNING.discard(key)

    def test_research_status_does_not_expose_openai_secret(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-private-openai-secret'}):
            with urlopen(self.base+'/api/research/status') as response: body=response.read().decode()
        self.assertTrue(json.loads(body)['openai_configured'])
        self.assertNotIn('test-private-openai-secret',body)

    def test_research_status_uses_gemini_without_exposing_key(self):
        with patch.dict(os.environ,{'AI_PROVIDER':'gemini','GEMINI_API_KEY':'test-private-gemini-secret'}):
            with urlopen(self.base+'/api/research/status') as response: body=response.read().decode()
        config=json.loads(body)['assistant']
        self.assertEqual(config['provider'],'Gemini')
        self.assertTrue(config['configured'])
        self.assertNotIn('test-private-gemini-secret',body)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env_file = Path(self.temp.name) / ".env"
        self.env_file.write_text(
            'GOOGLE_MAPS_API_KEY="public-map-key"\nCDSE_CLIENT_ID=client\n'
            'CDSE_CLIENT_SECRET=private-secret\n', encoding="utf-8"
        )
        self.file_patch = patch.object(web_app, "APP_ENV", self.env_file)
        self.file_patch.start()
        self.db_patch = patch.object(storage, 'DB_PATH', Path(self.temp.name) / 'test.sqlite3')
        self.db_patch.start()
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.server = web_app.ThreadingHTTPServer(("127.0.0.1", 0), web_app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.file_patch.stop()
        self.db_patch.stop()
        self.env_patch.stop()
        self.temp.cleanup()

    def test_public_config_does_not_expose_oauth_secret(self):
        with urlopen(self.base + "/api/config") as response:
            body = response.read().decode()
        config = json.loads(body)
        self.assertEqual(config["google_maps_api_key"], "public-map-key")
        self.assertTrue(config["ndvi_configured"])
        self.assertNotIn("private-secret", body)
        self.assertNotIn("CDSE_CLIENT_SECRET", body)

    def test_starts_without_configuration_and_serves_local_map(self):
        self.env_file.unlink()
        with urlopen(self.base + "/api/config") as response:
            config = json.load(response)
        self.assertEqual(config["google_maps_api_key"], "")
        self.assertFalse(config["ndvi_configured"])
        for asset in ("/", "/alytha-logo.png", "/vendor/leaflet/leaflet.js", "/vendor/leaflet/leaflet.css"):
            with urlopen(self.base + asset) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())

    def test_process_environment_overrides_local_file(self):
        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "override"}):
            self.assertEqual(web_app.read_map_config()["google_maps_api_key"], "override")

    def test_missing_ndvi_credentials_consults_local_base_without_remote_calls(self):
        self.env_file.unlink()
        geometry = json.loads((ROOT / "data" / "sample-field.geojson").read_text())
        request = Request(self.base + "/api/ndvi-series", data=json.dumps({
            "geojson": geometry, "from": "2026-10-01", "to": "2026-10-07"
        }).encode(), headers={"Content-Type": "application/json"})
        with patch.object(web_app, 'request_ndvi_series') as provider:
            with urlopen(request) as response:
                result=json.load(response)
        provider.assert_not_called()
        self.assertEqual(result['mode'],'local_cache')
        self.assertEqual(result['status'],'unavailable')
        self.assertIn('Não há leituras NDVI salvas',result['message'])

    def test_invalid_search_does_not_call_provider(self):
        request = Request(self.base + "/api/search", data=b'{"geojson":null}',
                          headers={"Content-Type": "application/json"})
        with patch.object(web_app, "request_items") as provider:
            with self.assertRaises(HTTPError) as caught:
                urlopen(request)
            self.assertEqual(caught.exception.code, 400)
            self.assertIn("error", json.load(caught.exception))
            caught.exception.close()
            provider.assert_not_called()

    def test_locations_api_returns_provider_data(self):
        with patch('app.localities.fetch_ibge', return_value=[{"id": 51, "nome": "Mato Grosso"}]) as provider:
            with urlopen(self.base + '/api/locations/states') as response:
                self.assertEqual(json.load(response)[0]['id'], 51)
            provider.assert_called_once_with('/v1/localidades/estados?orderBy=nome')

    def test_invalid_boundary_code_does_not_call_provider(self):
        with patch('app.localities.fetch_ibge') as provider:
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.base + '/api/locations/boundaries/municipalities/51')
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
            provider.assert_not_called()

    def test_saved_area_survives_new_database_connection(self):
        geometry = json.loads((ROOT / 'data' / 'sample-field.geojson').read_text())
        area = storage.save_area({'name': 'Talhão teste', 'municipality': 'Sorriso/MT', 'crop': 'Não confirmada', 'season': '2026', 'geojson': geometry})
        with urlopen(self.base + f'/api/areas/{area["id"]}') as response:
            restored = json.load(response)
        self.assertEqual(restored['geometry'], geometry['geometry'])
        self.assertEqual(restored['name'], 'Talhão teste')

    def test_catalog_saved_with_parameters_and_result(self):
        geometry = json.loads((ROOT / 'data' / 'sample-field.geojson').read_text())
        area = storage.save_area({'name': 'Teste', 'municipality': 'Sorriso', 'crop': 'Soja declarada', 'season': '2026', 'geojson': geometry})
        data = {'geojson': geometry, 'area_id': area['id'], 'from': '2026-08-01', 'to': '2026-08-31', 'max_cloud': 40}
        result = {'type': 'FeatureCollection', 'features': []}
        with patch.object(web_app, 'request_items', return_value=result):
            with urlopen(Request(self.base + '/api/search', data=json.dumps(data).encode(), headers={'Content-Type':'application/json'})) as response:
                self.assertEqual(response.status, 200)
        restored = storage.history(area['id'])
        self.assertEqual(restored[0]['result'], result)
        self.assertEqual(restored[0]['parameters']['from'], '2026-08-01')
        self.assertEqual(restored[0]['kind'], 'catalog')

    def test_changed_geometry_cannot_be_added_to_saved_area(self):
        geometry = json.loads((ROOT / 'data' / 'sample-field.geojson').read_text())
        area = storage.save_area({'name':'Teste','municipality':'Sorriso','crop':'Soja','season':'2026','geojson':geometry})
        changed = json.loads(json.dumps(geometry['geometry']))
        changed['coordinates'][0][1][0] += 0.001
        with self.assertRaises(ValueError):
            storage.validate_analysis_area({'area_id':area['id']}, changed)
        self.assertEqual(storage.history(area['id']), [])


if __name__ == "__main__":
    unittest.main()
