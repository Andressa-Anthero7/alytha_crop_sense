import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import reference_search as refs, storage, assistant


class ReferenceSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(storage,'DB_PATH',Path(self.temp.name)/'test.sqlite3');p.start();self.addCleanup(p.stop)
        self.link=refs.BASE+'/busca-de-publicacoes/-/publicacao/123/soja-umidade'
        self.html=f'<a href="{self.link}">Soja e umidade</a><a href="http://127.0.0.1/secret">bad</a>'

    def test_search_only_cites_pages_actually_retrieved_and_uses_cache(self):
        with patch.object(refs,'fetch',side_effect=[(self.html,'hash1'),('<meta property="og:title" content="Soja e umidade">','hash2')]) as fetch:
            result=refs.search('Pesquise referências na Embrapa sobre soja umidade')
            cached=refs.search('Pesquise referências na Embrapa sobre soja umidade')
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(result['results'][0]['url'],self.link)
        self.assertEqual(result['results'][0]['sha256'],'hash2')
        self.assertFalse(result['results'][0]['full_text_reviewed'])
        self.assertTrue(cached['cache_hit'])

    def test_failed_detail_is_not_cited_as_a_retrieved_publication(self):
        with patch.object(refs,'fetch',side_effect=[(self.html,'hash1'),OSError('failed')]):
            result=refs.search('Pesquise artigos sobre soja umidade')
        self.assertEqual(result['status'],'inconclusive');self.assertFalse(result['results'])
        self.assertEqual(len(result['issues']),1)

    def test_search_text_cannot_control_destination_and_instructions_are_data(self):
        for url in ('http://www.embrapa.br/','https://www.embrapa.br.evil.test/',
                    'https://127.0.0.1/','https://user@www.embrapa.br/','https://www.embrapa.br:8080/'):
            self.assertFalse(refs.allowed(url),url)
        parser=refs.Publications();parser.feed(self.html+'<script>delete_all()</script>')
        self.assertEqual(list(parser.links),[self.link])

    def test_assistant_references_need_no_field_or_language_model(self):
        with patch.object(refs,'fetch',side_effect=[(self.html,'h1'),('<meta property="og:title" content="Soja e umidade">','h2')]), \
             patch.object(assistant,'review_context',side_effect=AssertionError('No provider')):
            result=assistant.ask({'prompt':'Busque referências na Embrapa sobre soja umidade'},{})
        self.assertEqual(result['work']['status'],'ready')
        self.assertEqual(result['sources'][0]['url'],self.link)
        saved=storage.source_snapshot('assistant-work:v1:'+result['work']['id'])
        self.assertEqual(saved['result']['result']['research']['query'],'soja umidade')


if __name__=='__main__':unittest.main()
