"""Real TLS policy and persisted locality lookup regression, without external calls."""
import gzip
import io
import json
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from app import localities, storage, web_app

STATES_PATH='/v1/localidades/estados?orderBy=nome'
CITIES_PATH='/v1/localidades/municipios?orderBy=nome'
STATES=[{'id':51,'nome':'Mato Grosso','sigla':'MT'}]
CITIES=[{'id':5107925,'nome':'Sorriso'}]


class LocalityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        db=patch.object(storage,'DB_PATH',Path(self.temp.name)/'local.sqlite3')
        db.start();self.addCleanup(db.stop)

    def response(self,data,compressed=False):
        raw=json.dumps(data).encode()
        return io.BytesIO(gzip.compress(raw) if compressed else raw)

    def cache(self,path,data,old=False):
        key='ibge-response:v1:'+path
        storage.source_snapshot(key,{'data':data,'source':'IBGE','source_url':localities.BASE+path})
        if old:
            with storage.connect() as db:
                db.execute("UPDATE source_snapshots SET fetched_at='2020-01-01T00:00:00+00:00' WHERE cache_key=?",(key,))
        return key

    def test_sorriso_lookup_validates_tls_and_decodes_gzip(self):
        with patch.object(localities,'urlopen',side_effect=[self.response(STATES,True),self.response(CITIES,True)]) as remote:
            result=localities.search('sorriso')
        self.assertTrue(result['exact'])
        self.assertEqual(result['matches'],[{'kind':'municipality','code':'5107925','name':'Sorriso','uf':'MT'}])
        self.assertEqual(remote.call_count,2)
        for call in remote.call_args_list:
            context=call.kwargs['context']
            self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            self.assertTrue(call.args[0].full_url.startswith('https://servicodados.ibge.gov.br/api/'))

    def test_lookup_reuses_database_after_module_context_cache_is_cleared(self):
        self.cache(STATES_PATH,STATES);self.cache(CITIES_PATH,CITIES)
        localities.tls_context.cache_clear()
        with patch.object(localities,'urlopen',side_effect=AssertionError('No network after restart')):
            self.assertEqual(localities.search('Sorriso / MT')['matches'][0]['code'],'5107925')

    def test_expired_cache_survives_source_certificate_failure_without_disabling_tls(self):
        key=self.cache(STATES_PATH,STATES,old=True)
        with patch.object(localities,'urlopen',side_effect=URLError(ssl.SSLCertVerificationError('missing intermediate'))) as remote:
            result=localities.fetch_ibge(STATES_PATH)
        self.assertEqual(result,STATES);remote.assert_called_once()
        self.assertEqual(remote.call_args.kwargs['context'].verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(storage.source_snapshot(key)['fetched_at'].startswith('2020-'))

    def test_no_cache_certificate_failure_remains_an_error(self):
        with patch.object(localities,'urlopen',side_effect=URLError(ssl.SSLCertVerificationError('invalid certificate'))) as remote:
            with self.assertRaises(URLError):localities.fetch_ibge(STATES_PATH)
        remote.assert_called_once()
        self.assertIsNone(storage.source_snapshot('ibge-response:v1:'+STATES_PATH))

    def test_expired_response_is_refreshed_and_malformed_data_is_not_cached(self):
        key=self.cache(STATES_PATH,STATES,old=True)
        changed=[*STATES,{'id':52,'nome':'Goiás','sigla':'GO'}]
        with patch.object(localities,'urlopen',return_value=self.response(changed)):
            self.assertEqual(localities.fetch_ibge(STATES_PATH),changed)
        self.assertEqual(storage.source_snapshot(key)['result']['data'],changed)
        with patch.object(localities,'urlopen',return_value=self.response({'error':'upstream failure'})):
            with self.assertRaises(ValueError):localities.fetch_ibge(CITIES_PATH)
        self.assertIsNone(storage.source_snapshot('ibge-response:v1:'+CITIES_PATH))

    def test_compressed_and_plain_responses_have_bounded_size(self):
        for compressed in (True,False):
            with patch.object(localities,'MAX_RESPONSE_BYTES',100),patch.object(localities,'urlopen',return_value=self.response(['x'*1000],compressed)):
                with self.assertRaisesRegex(ValueError,'limite'):localities.fetch_ibge(CITIES_PATH)

    def test_sorriso_http_route_works_from_persisted_lists_during_source_outage(self):
        self.cache(STATES_PATH,STATES);self.cache(CITIES_PATH,CITIES)
        handler=object.__new__(web_app.Handler);handler.path='/api/locations/search?q=sorriso'
        with patch.object(localities,'urlopen',side_effect=AssertionError('No remote source')),patch.object(handler,'_send_json') as send:
            handler.do_GET()
        self.assertEqual(send.call_args.args[0]['matches'][0]['code'],'5107925')
        self.assertEqual(send.call_args.kwargs.get('status',200),200)

    def test_standard_library_fallback_keeps_certificate_and_hostname_verification(self):
        localities.tls_context.cache_clear();self.addCleanup(localities.tls_context.cache_clear)
        with patch.dict('sys.modules',{'truststore':None}):context=localities.tls_context()
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


if __name__=='__main__':unittest.main()
