"""Bounded live search of the official Embrapa publications portal.

Search results and fetched titles are data, never model instructions. Search is
not a review of the full paper and never turns a title into a field diagnosis.
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from . import storage, research
from .assistant_intents import normalize

BASE = 'https://www.embrapa.br'
OPENER = None


def allowed(url):
    try:
        parsed = urlsplit(url)
        return parsed.scheme == 'https' and parsed.hostname == 'www.embrapa.br' and parsed.port in (None,443) and not parsed.username
    except ValueError:return False


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise ValueError('Redirecionamento de referência fora do portal permitido.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    if not allowed(url): raise ValueError('Endereço de referência não permitido.')
    request = Request(url, headers={'User-Agent':'AlythaCropSense/1.0', 'Accept':'text/html'})
    with (OPENER or build_opener(SafeRedirect())).open(request, timeout=15) as response:
        if not allowed(response.url): raise ValueError('Origem da referência inválida.')
        binary = response.read(2_000_001)
        if len(binary) > 2_000_000: raise ValueError('Página de referência acima do limite de leitura.')
        if 'text/html' not in response.headers.get('Content-Type', ''):
            raise ValueError('A referência não é uma página HTML.')
    return binary.decode('utf-8', errors='replace'), hashlib.sha256(binary).hexdigest()


class Publications(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = {}; self.current = None; self.text = []; self.title = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('property') == 'og:title':
            self.title = values.get('content')
        if tag == 'a':
            href = urljoin(BASE, values.get('href', ''))
            if allowed(href) and re.fullmatch(r'/busca-de-publicacoes/-/publicacao/\d+/[^/?#]+', urlsplit(href).path):
                self.current = href; self.text = []

    def handle_data(self, data):
        if self.current: self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.current:
            text = ' '.join(' '.join(self.text).split())
            if len(text) > 8: self.links.setdefault(self.current, text[:500])
            self.current = None


def terms_for(prompt):
    text = normalize(prompt)
    match = re.search(r'\b(?:sobre|por|para)\s+(.+)', text)
    terms = match.group(1) if match else text
    terms = re.sub(r'\b(?:pesquise|busque|consulte|referencias?|publicacoes?|artigos?|embrapa|fontes|na|da|de|e|web|internet)\b', ' ', terms)
    terms = ' '.join(re.findall(r'[a-z0-9]+', terms))
    if not 3 <= len(terms) <= 160: raise ValueError('Informe um tema de pesquisa de 3 a 160 caracteres.')
    return terms


def requested(prompt):
    text = normalize(prompt)
    return bool(re.search(r'\b(?:pesquise|busque|consulte|encontre)\b', text)
                and re.search(r'\b(?:referencias?|publicacoes?|artigos?|embrapa|fontes|web|internet)\b', text)
                and not re.match(r'(?:nao|nunca)\b', text))


def search(prompt):
    terms = terms_for(prompt)
    key = 'reference-search:embrapa:v1:' + research.fingerprint(terms)
    cached = storage.source_snapshot(key)
    if cached and datetime.now(timezone.utc)-datetime.fromisoformat(cached['fetched_at']) < timedelta(days=7):
        return {**cached['result'], 'cache_hit':True}
    url = BASE + '/busca-de-publicacoes/-/publicacao/busca/' + quote(terms.replace(' ', '+'), safe='+')
    html, digest = fetch(url); parser = Publications(); parser.feed(html)
    results, issues = [], []
    for link, indexed_title in list(parser.links.items())[:3]:
        try:
            body, fingerprint = fetch(link); page = Publications(); page.feed(body)
            title = page.title or indexed_title
            # Short title extracts, with no generated account of unread full text.
            title = ' '.join(title.split()[:24])
            results.append({'id':'reference_' + research.fingerprint(link), 'source':'Embrapa · publicação recuperada',
                            'url':link, 'title':title, 'retrieved_at':storage.now(), 'sha256':fingerprint,
                            'contract_version':1,'kind':'publication_metadata','area_key':None,'period':None,
                            'scope':'conhecimento publicado; sem observação do recorte',
                            'provenance':{'resource':link,'method':'official_portal_retrieval','version':1},
                            'quality':{'page_retrieved':True,'full_text_reviewed':False},
                            'content_role':'untrusted_reference_data', 'full_text_reviewed':False})
        except (ValueError, OSError):
            issues.append({'url':link,'reason':'Página da publicação indisponível; não citada como recuperada.'})
    result = {'query':terms, 'search_url':url, 'searched_at':storage.now(), 'search_sha256':digest,
              'results':results, 'issues':issues, 'status':'ready' if results else 'inconclusive', 'cache_hit':False,
              'scope':'Busca na web restrita ao portal oficial Embrapa; até três páginas por consulta.'}
    storage.source_snapshot(key,result)
    return result


def reply(data):
    identifier = secrets.token_hex(32); started = storage.now()
    try:
        result = search(data['prompt'])
        items = result['results']
        answer = ('Encontrei estas publicações no portal da Embrapa:\n' + '\n'.join('- ' + item['title'] for item in items)
                  if items else 'Não consegui recuperar publicações para esse tema no portal da Embrapa. Tente termos mais específicos.')
        response = {'answer':answer + '\n\nRecuperei as páginas de referência; o texto completo e a aplicabilidade ao talhão ainda precisam de revisão.',
                    'evidence_ids':[item['id'] for item in items], 'sources':items,
                    'limitations':[result['scope'], 'Publicações recuperadas não confirmam cultura, manejo ou causa de mudanças no recorte.'],
                    'research':result, 'action':{'kind':'none','class_ids':[]},
                    'provider':'CropSense','model':'embrapa-search-v1','intent':'reference_search'}
        status = result['status']
    except (ValueError, OSError):
        response = {'answer':'A busca no portal da Embrapa ficou pendente por indisponibilidade da fonte.',
                    'evidence_ids':[], 'sources':[], 'limitations':[], 'action':{'kind':'none','class_ids':[]},
                    'provider':'CropSense','model':'embrapa-search-v1','intent':'reference_search'}
        status = 'error'
    job = {'id':identifier, 'tool':'reference_search', 'version':1, 'status':status,
           'started_at':started,'finished_at':storage.now(),'mode':'external_references'}
    storage.source_snapshot('assistant-work:v1:' + identifier, {**job, 'prompt':data['prompt'],'result':response})
    response['work'] = job
    return response
