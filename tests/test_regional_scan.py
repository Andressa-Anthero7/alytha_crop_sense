import copy
import tempfile
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from pathlib import Path
from unittest.mock import patch
from app import localities, regional_scan as scan, storage, municipalities, research, web_app, municipal_activity, satellite_learning


class RegionalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=patch.object(storage,'DB_PATH',Path(self.temp.name)/'db.sqlite3');self.db.start()
        self.pool=patch.object(scan.POOL,'submit');self.submit=self.pool.start()
        scan.RUNNING.clear();scan.STOP.clear()

    def tearDown(self):
        scan.RUNNING.clear();scan.STOP.clear();self.pool.stop();self.db.stop();self.temp.cleanup()

    def test_names_accents_uf_and_ambiguous_cities(self):
        states=[{'id':51,'nome':'Mato Grosso','sigla':'MT'},{'id':35,'nome':'São Paulo','sigla':'SP'}]
        cities=[{'id':5107925,'nome':'Sorriso'},{'id':5100010,'nome':'Bom Jesus'},{'id':3500010,'nome':'Bom Jesus'},{'id':3550308,'nome':'São Paulo'}]
        def fetch(path):return states if '/estados?' in path else cities
        with patch.object(localities,'fetch_ibge',side_effect=fetch):
            self.assertEqual(localities.search('mt')['matches'][0]['kind'],'state')
            self.assertEqual(localities.search('Sorriso / MT')['matches'][0]['code'],'5107925')
            self.assertEqual(len(localities.search('Bom Jesus')['matches']),2)
            self.assertEqual({x['kind'] for x in localities.search('Sao Paulo')['matches']},{'state','municipality'})
            self.assertFalse(localities.search('Sor')['exact'])

    def test_invalid_region_never_schedules(self):
        for data in [None,{}, {'kind':'state','code':'../51'},{'kind':'municipality','code':'51'}]:
            with self.assertRaises(ValueError):scan.start(data)
        self.submit.assert_not_called()

    def test_deduplicates_and_resumes_once_after_restart(self):
        job=scan.start({'kind':'municipality','code':'5107925'})
        self.assertEqual(scan.start({'kind':'municipality','code':'5107925'})['id'],job['id'])
        self.submit.assert_called_once()
        scan.RUNNING.clear();self.submit.reset_mock()
        scan.get(job['id']);scan.get(job['id']);self.submit.assert_called_once()

    def test_queue_is_bounded_and_failed_submission_is_retryable(self):
        with patch.object(scan,'MAX_PENDING',0):
            with self.assertRaisesRegex(ValueError,'andamento'):scan.start({'kind':'state','code':'51'})
        self.submit.side_effect=RuntimeError('private details')
        with self.assertRaisesRegex(ValueError,'iniciar'):scan.start({'kind':'state','code':'51'})
        self.assertFalse(scan.RUNNING)
        self.submit.side_effect=None
        self.assertEqual(scan.start({'kind':'state','code':'51'})['status'],'loading')

    def test_state_visits_all_cities_and_preserves_independent_failure(self):
        job=scan.start({'kind':'state','code':'51'})
        def collect(city,job):
            if city['code']=='5100010':raise RuntimeError('private source error')
            city['status']='ready'
        cities=[{'id':5100010,'nome':'A'},{'id':5107925,'nome':'Sorriso'}]
        with patch.object(scan,'fetch_ibge',return_value=cities),patch.object(scan,'collect_city',side_effect=collect) as collect_mock:
            scan.build(job['id'])
        result=scan.get(job['id'])
        self.assertEqual(collect_mock.call_count,2)
        self.assertEqual(result['status'],'partial');self.assertEqual(result['processed'],2)
        self.assertNotIn('private',str(result))
        self.assertEqual(result['cities'][1]['status'],'ready')

    def test_retry_preserves_ready_city(self):
        job=scan.start({'kind':'state','code':'51'})
        job.update(status='partial',cities=[{'code':'5100010','name':'A','status':'ready'},{'code':'5107925','name':'Sorriso','status':'error'}]);scan.persist(job)
        scan.RUNNING.clear();scan.start({'kind':'state','code':'51'})
        with patch.object(scan,'collect_city',side_effect=lambda city,job:city.update(status='ready')) as collect:
            scan.build(job['id'])
        self.assertEqual(collect.call_count,1)
        self.assertEqual(collect.call_args.args[0]['code'],'5107925')
        self.assertEqual(scan.get(job['id'])['status'],'ready')

    def test_missing_credentials_keeps_dossier_without_satellite_calls(self):
        job=scan.start({'kind':'municipality','code':'5107925'})
        city={'code':'5107925','name':'Sorriso','status':'queued'};job['cities']=[city]
        storage.source_snapshot(municipalities.key(city['code']),{'status':'ready','boundary':{},'sources':{}})
        # A nonempty boundary is available but no credentials are configured.
        storage.source_snapshot(municipalities.key(city['code']),{'status':'ready','boundary':{'features':[]},'sources':{}})
        with patch.object(municipalities,'request'),patch.object(web_app,'read_app_env',return_value={}),patch.object(municipal_activity,'start') as satellite:
            scan.collect_city(city,job)
        self.assertEqual(city['status'],'partial');satellite.assert_not_called()
        self.assertEqual(city['dossier']['status'],'ready')

    def test_full_pipeline_records_child_ids_and_reference_scope(self):
        code='5107925';job=scan.start({'kind':'municipality','code':code})
        city={'code':code,'name':'Sorriso','status':'queued'};job['cities']=[city]
        storage.source_snapshot(municipalities.key(code),{'status':'ready','boundary':{'features':[]},'sources':{}})
        feature={'geometry':{'type':'Polygon','coordinates':[]},'properties':{'area_ha':6}}
        storage.source_snapshot('municipal-soy:v1:'+code,{'features':[feature]})
        activity={'id':'a'*64,'status':'ready','phase':'complete','processed':12,'total':12,'parameters':{'as_of':'2026-10-13'}}
        history={'id':'b'*64,'status':'ready','points':[{}]*40,'processed':9,'total':9,'parameters':{'as_of':'2026-10-13'}}
        with patch.object(municipalities,'request'),patch.object(web_app,'read_app_env',return_value={'CDSE_CLIENT_ID':'x','CDSE_CLIENT_SECRET':'x'}),patch.object(municipal_activity,'start',return_value=activity),patch.object(municipal_activity,'get',return_value=activity),patch.object(research,'start_history',return_value=history) as historical,patch.object(research,'restore_history',return_value=history),patch.object(satellite_learning,'train',side_effect=ValueError('insufficient')):
            scan.collect_city(city,job)
        self.assertEqual(city['status'],'ready')
        self.assertEqual(city['history']['scope'],'reference');self.assertEqual(city['history']['observations'],40)
        self.assertEqual(historical.call_args.args[0]['municipality_code'],code)
        self.assertEqual(city['learning']['status'],'insufficient')

    def test_shutdown_preserves_pending_scan(self):
        job=scan.start({'kind':'state','code':'51'})
        job['cities']=[{'code':'5107925','name':'Sorriso','status':'queued'}];scan.persist(job)
        scan.STOP.set();scan.build(job['id'])
        saved=storage.source_snapshot(scan.key(job['id']))['result']
        self.assertEqual(saved['status'],'loading');self.assertEqual(saved['phase'],'interrupted')

    def test_history_supports_other_city_and_checks_its_boundary(self):
        geometry={'type':'Polygon','coordinates':[[[-55,-12],[-54.999,-12],[-54.999,-11.999],[-55,-11.999],[-55,-12]]]}
        boundary={'features':[{'geometry':geometry}]}
        code='5107909'
        try:
            with patch.object(municipalities,'boundary',return_value=boundary) as boundary_mock,patch.object(research.POOL,'submit'):
                result=research.start_history({'geojson':geometry,'municipality_code':code,'start_year':2025})
                self.assertEqual(result['parameters']['municipality_code'],code)
                boundary_mock.assert_called_once_with(code)
                outside=copy.deepcopy(geometry)
                outside['coordinates']=[[[x+1,y] for x,y in ring] for ring in geometry['coordinates']]
                with self.assertRaisesRegex(ValueError,'município'):
                    research.start_history({'geojson':outside,'municipality_code':code,'start_year':2025})
        finally:research.RUNNING.clear()

    def test_http_search_and_scan_routes(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),web_app.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_address[1]}'
        job={'id':'a'*64,'status':'loading'}
        try:
            with patch.object(web_app,'search_localities',return_value={'matches':[],'exact':False}) as lookup,patch.object(scan,'start',return_value=job) as start,patch.object(scan,'get',return_value=job):
                with urlopen(base+'/api/locations/search?q=Sinop%20MT') as response:self.assertEqual(json.load(response)['matches'],[])
                lookup.assert_called_once_with('Sinop MT')
                payload={'kind':'state','code':'51'}
                request=Request(base+'/api/regional-scans',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                with urlopen(request) as response:self.assertEqual(response.status,202)
                start.assert_called_once_with(payload)
                with urlopen(base+'/api/regional-scans/'+job['id']) as response:self.assertEqual(json.load(response)['id'],job['id'])
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
