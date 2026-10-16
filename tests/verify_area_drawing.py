"""Draw with real map clicks; inspect image/NDVI payloads without satellite calls."""
import argparse
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    base = parser.parse_args().url.rstrip('/')
    calls, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()

        def route(r):
            path = urlsplit(r.request.url).path
            if not r.request.url.startswith(base + '/'):
                r.abort(); return
            if not path.startswith('/api/'):
                r.continue_(); return
            body = []
            if path == '/api/config':
                body = {'google_maps_api_key': '', 'ndvi_configured': True}
            elif path == '/api/locations/states':
                body = [{'id': 51, 'nome': 'Mato Grosso', 'sigla': 'MT'}]
            elif path == '/api/research/status':
                body = {'ml': {'events': 0, 'areas': 0, 'model': None}, 'satellite': None,
                        'assistant': {'configured': False, 'provider': 'Gemini'}}
            elif path == '/api/sources/status':
                body = {'satveg_configured': False}
            elif path in ('/api/search', '/api/ndvi-series'):
                calls.append((path, r.request.post_data_json))
                body = {'type': 'FeatureCollection', 'features': []} if path == '/api/search' else {'points': []}
            r.fulfill(json=body)

        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/*', route)
        page.goto(base, wait_until='domcontentloaded')
        page.wait_for_function('mapReady')

        def start():
            page.locator('#pen-tool').click()
            page.wait_for_timeout(150)
            assert page.locator('#draw-controls').is_visible()
            assert not page.locator('#ai-prompt-panel').is_visible()
            assert page.locator('#search').is_visible()
            page.evaluate("map.setView([-12,-55],14,{animate:false})")

        def point(x, y, double=False):
            canvas = page.locator('#map').bounding_box()
            position = {'x': canvas['width'] * x, 'y': canvas['height'] * y}
            if double:
                page.locator('#map').dblclick(position=position)
            else:
                page.locator('#map').click(position=position)

        def search_and_check(expected):
            count = len(calls)
            page.locator('#search').click()
            page.wait_for_function("document.getElementById('status').textContent.includes('Consulta concluída')")
            assert len(calls) == count + 1
            path, payload = calls[-1]
            ring = payload['geojson']['geometry']['coordinates'][0]
            assert path == '/api/search' and ring == expected + [expected[0]]
            assert page.evaluate('fieldLoaded && !drawingArea')
            assert not page.locator('#draw-controls').is_visible()
            assert payload['from'] and payload['to'] and payload['max_cloud'] == 40

        start()
        point(.5, .45); point(.7, .45)
        page.locator('#search').click()
        assert calls == [] and '3 pontos' in page.locator('#drawing-hint').inner_text()
        point(.7, .72)
        page.locator('#undo-point').click()
        assert page.evaluate('drawingPoints.length') == 2
        point(.7, .72)
        expected = page.evaluate('drawingPoints')
        search_and_check(expected)
        original = page.evaluate('uploadedGeojson')

        # An unfinished replacement must not query the previously selected polygon.
        start(); point(.48, .48); point(.65, .48)
        count = len(calls)
        page.locator('#search').click()
        assert len(calls) == count and page.evaluate('drawingArea')
        page.locator('#cancel-drawing').click()
        assert page.evaluate('uploadedGeojson') == original
        assert page.evaluate('map.doubleClickZoom.enabled()')

        start(); point(.5, .45); point(.7, .45); point(.7, .72)
        expected = page.evaluate('drawingPoints')
        page.locator('#ndvi-button').click()
        try:
            page.wait_for_function("document.getElementById('ndvi-status').textContent.includes('Não foi possível avaliar')")
        except Exception:
            print(page.evaluate("({drawingArea,drawingPoints,fieldLoaded,ndvi:document.getElementById('ndvi-status').textContent,hint:document.getElementById('drawing-hint').textContent,status:document.getElementById('status').textContent})"), expected, calls, errors)
            raise
        assert calls[-1][0] == '/api/ndvi-series'
        assert calls[-1][1]['geojson']['geometry']['coordinates'][0] == expected + [expected[0]]
        page.locator('#ndvi-panel').evaluate("panel=>panel.classList.remove('visible')")

        start(); point(.5, .45); point(.7, .45); point(.7, .72)
        expected = page.evaluate('drawingPoints')
        page.locator('#finish-drawing').click()
        search_and_check(expected)

        start(); point(.5, .45); point(.7, .45); point(.7, .72, double=True)
        assert page.evaluate('fieldLoaded && !drawingArea')
        assert len(page.evaluate('uploadedGeojson.geometry.coordinates[0]')) == 4

        start(); point(.45, .6); point(.6, .6); point(.75, .6)
        count = len(calls)
        page.locator('#search').click()
        assert len(calls) == count
        assert 'mesma linha' in page.locator('#drawing-hint').inner_text()
        page.locator('#cancel-drawing').click()
        page.locator('#clear-area').click()
        assert not page.evaluate('fieldLoaded')
        assert not page.locator('body').evaluate("body=>body.classList.contains('has-analysis-area')")

        page.set_viewport_size({'width': 390, 'height': 844})
        start(); point(.25, .45); point(.7, .45); point(.7, .65)
        assert page.locator('#side-panel').evaluate("panel=>panel.classList.contains('closed')")
        assert page.locator('#finish-drawing').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        expected = page.evaluate('drawingPoints')
        output = Path('data/outputs/drawing'); output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / 'mobile-sketch.png'))
        search_and_check(expected)
        assert not errors, errors
        browser.close()
    print('PASS: pen clicks, image/NDVI payloads, finish, double-click, undo, cancel, invalid sketches and mobile drawing. No satellite requests.')


if __name__ == '__main__':
    main()
