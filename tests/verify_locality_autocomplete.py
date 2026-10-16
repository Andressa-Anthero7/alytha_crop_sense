"""Exercise live-search interactions with isolated IBGE fixtures and no collection."""
import argparse
import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    base = parser.parse_args().url.rstrip('/')
    states = [{'id': 51, 'nome': 'Mato Grosso', 'sigla': 'MT'}]
    sorriso = {'kind': 'municipality', 'code': '5107925', 'name': 'Sorriso', 'uf': 'MT'}
    sinop = {'kind': 'municipality', 'code': '5107909', 'name': 'Sinop', 'uf': 'MT'}
    state = {'kind': 'state', 'code': '51', 'name': 'Mato Grosso', 'uf': 'MT'}
    boundary = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {},
        'geometry': {'type': 'Polygon', 'coordinates': [[[-55, -12], [-54.99, -12],
            [-54.99, -11.99], [-55, -11.99], [-55, -12]]]}}]}
    calls, starts, errors, failed_requests = [], [], [], []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 1366, 'height': 768})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('requestfailed', lambda request: failed_requests.append((urlsplit(request.url).path, request.failure)))

        async def route(r):
            url = r.request.url
            path = urlsplit(url).path
            if not url.startswith(base + '/'):
                await r.abort()
                return
            if not path.startswith('/api/'):
                await r.continue_()
                return
            body = []
            if path == '/api/config':
                body = {'google_maps_api_key': '', 'ndvi_configured': False}
            elif path == '/api/locations/search':
                term = parse_qs(urlsplit(url).query)['q'][0]
                calls.append(term)
                if term == 'sor':
                    await asyncio.sleep(.8)
                if term == 'falha':
                    await r.fulfill(status=502, json={'error': 'IBGE temporariamente indisponível.'})
                    return
                matches = ([state] if term.lower() in ('ma', 'mt') else
                           [sinop] if term == 'sin' else
                           [sorriso, sinop] if term == 's' * 2 else
                           [] if term == 'inexistente' else [sorriso])
                body = {'matches': matches, 'exact': term.lower() in ('sorriso', 'mt')}
            elif path == '/api/locations/states':
                body = states
            elif path == '/api/locations/states/51/municipalities':
                body = [{'id': 5107925, 'nome': 'Sorriso'}, {'id': 5107909, 'nome': 'Sinop'}]
            elif path.startswith('/api/locations/boundaries/'):
                body = boundary
            elif path == '/api/regional-scans':
                payload = r.request.post_data_json
                starts.append(payload)
                body = {'id': 'a' * 64, 'status': 'ready', 'processed': 0, 'total': 0,
                        'cities': [], 'parameters': {**payload, 'as_of': '2026-10-15'}}
            elif path.startswith('/api/municipalities/'):
                body = {'status': 'ready', 'name': 'Sorriso', 'uf': 'MT', 'sources': {}}
            elif path == '/api/research/status':
                body = {'ml': {'events': 0, 'areas': 0, 'model': None}, 'satellite': None,
                        'assistant': {'configured': False, 'provider': 'Gemini'}}
            elif path == '/api/sources/status':
                body = {'satveg_configured': False}
            await r.fulfill(json=body)

        await page.route('**/*', route)
        await page.goto(base, wait_until='domcontentloaded')
        await page.wait_for_function('mapReady')
        search = page.locator('#location-search')
        choices = page.locator('#location-matches')

        async def suggestions(term, text):
            await search.fill(term)
            await page.wait_for_function("text => !document.getElementById('location-matches').hidden && document.getElementById('location-matches').textContent.includes(text)", arg=text)

        await search.fill('s')
        await page.wait_for_timeout(350)
        assert calls == [] and not await choices.is_visible()
        for term in ('so', 'sor', 'sorr'):
            await search.fill(term)
        try:
            await page.wait_for_function("document.querySelector('#location-options button')?.textContent.includes('Sorriso')")
        except Exception:
            print({'calls': calls, 'errors': errors, 'failed_requests': failed_requests,
                   'ui': await page.evaluate("({active:document.activeElement.id,value:document.getElementById('location-search').value,status:document.getElementById('location-search-status').textContent,handler:typeof window.handleOfficialRegionKeydown})")})
            raise
        assert calls == ['sorr'], calls
        assert starts == [] and 'municipio=' not in page.url
        assert await search.get_attribute('aria-expanded') == 'true'
        output = Path('data/outputs/localities')
        output.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(output / 'autocomplete.png'))

        await suggestions('Sorriso', 'Sorriso / MT')
        assert starts == [], 'Typing an exact name must not select a region.'
        await page.locator('#location-options button').click()
        await page.wait_for_function("document.getElementById('municipality-select').value==='5107925' && document.getElementById('region-status').textContent.includes('Limite IBGE exibido')")
        await page.wait_for_function("document.getElementById('regional-scan-status').textContent.includes('0/0')")
        assert len(starts) == 1 and starts[-1]['code'] == '5107925'
        assert await search.get_attribute('aria-expanded') == 'false'

        await suggestions('ma', 'Mato Grosso / MT')
        await search.press('ArrowDown')
        assert await search.get_attribute('aria-activedescendant')
        await search.press('Enter')
        await page.wait_for_function("new URL(location.href).searchParams.get('estado')==='51' && document.getElementById('regional-scan-status').textContent.includes('0/0')")
        assert len(starts) == 2 and starts[-1]['kind'] == 'state'

        async with page.expect_request(lambda request: urlsplit(request.url).path == '/api/locations/search' and parse_qs(urlsplit(request.url).query).get('q') == ['sor']):
            await search.fill('sor')
        await suggestions('sin', 'Sinop / MT')
        await page.wait_for_timeout(900)
        assert 'Sinop' in await choices.inner_text() and 'Sorriso' not in await choices.inner_text()
        assert len(starts) == 2
        await search.press('Escape')
        assert not await choices.is_visible()

        await suggestions('ss', 'Sorriso / MT')
        assert await page.locator('#location-options button').count() == 2
        await search.press('ArrowUp')
        assert await page.locator('#location-options button').nth(1).get_attribute('aria-selected') == 'true'
        await search.press('Escape')
        await suggestions('inexistente', 'Nenhuma localidade')
        await suggestions('falha', 'IBGE temporariamente indisponível')
        await suggestions('sin', 'Sinop / MT')
        await page.locator('#location-search-button').focus()
        await page.locator('#ai-prompt').click()
        assert not await choices.is_visible()

        await search.fill('sin')
        await page.wait_for_function("document.querySelector('#location-options button')?.textContent.includes('Sinop') && !document.getElementById('location-matches').hidden")
        await search.fill('')
        assert not await choices.is_visible()
        previous = len(calls)
        await search.fill('-12.5, -55.2')
        await page.wait_for_timeout(350)
        assert len(calls) == previous and not await choices.is_visible()
        await search.press('Enter')
        await page.wait_for_function("document.getElementById('status').textContent.includes('Mapa centralizado nas coordenadas')")

        await page.set_viewport_size({'width': 390, 'height': 844})
        await suggestions('sin', 'Sinop / MT')
        box = await choices.bounding_box()
        assert box and 0 <= box['x'] and box['x'] + box['width'] <= 390
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors, errors
        await browser.close()
    print('PASS: debounce, IBGE suggestions, click/keyboard selection, stale responses, dismissal, errors, coordinates and mobile layout.')


if __name__ == '__main__':
    asyncio.run(main())
