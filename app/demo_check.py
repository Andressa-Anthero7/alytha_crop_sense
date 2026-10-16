"""Read-only preparation report for a guided partner demonstration."""
import importlib.util
import json
import sqlite3
from collections import Counter
from pathlib import Path
from .web_app import read_app_env


def main():
    root = Path(__file__).resolve().parents[1]
    env = read_app_env()
    print('Alytha · preparação da demonstração (sem chamadas externas)')
    for module in ('numpy', 'rasterio', 'shapely', 'pandas', 'sklearn', 'joblib', 'cv2'):
        print(f"{'OK' if importlib.util.find_spec(module) else 'PENDENTE'} · dependência {module}")
    checks = {
        'NDVI Copernicus': all(env.get(k) for k in ('CDSE_CLIENT_ID', 'CDSE_CLIENT_SECRET')),
        'Google Maps (opcional; há Leaflet)': bool(env.get('GOOGLE_MAPS_API_KEY')),
        'Assistente selecionado': bool(env.get('GEMINI_API_KEY') if env.get('AI_PROVIDER') == 'gemini' or (not env.get('AI_PROVIDER') and env.get('GEMINI_API_KEY')) else env.get('OPENAI_API_KEY')),
    }
    for name, configured in checks.items():
        print(f"{'CONFIGURADO' if configured else 'PENDENTE'} · {name}")
    print('Configuração não comprova acesso, saldo ou disponibilidade dos fornecedores.')
    db_path = root / 'data' / 'monitoring.sqlite3'
    if not db_path.is_file():
        print('PENDENTE · banco local ainda não existe'); return
    with sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True) as db:
        print('Banco:', db.execute('PRAGMA quick_check').fetchone()[0])
        for table, label in [('areas', 'áreas salvas'), ('analyses', 'análises salvas'), ('field_events', 'registros de campo')]:
            print(f'{label}: {db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]}')
        statuses = Counter()
        for key, raw, fetched in db.execute('SELECT cache_key,result,fetched_at FROM source_snapshots'):
            value = json.loads(raw)
            prefix = key.split(':')[0]
            if isinstance(value, dict) and prefix in ('municipality', 'history', 'cv', 'municipal-activity', 'crop-map', 'regional-scan'):
                statuses[(prefix, value.get('status', 'sem estado'))] += 1
        for (source, status), count in sorted(statuses.items()):
            print(f'Cache {source}: {count} · {status}')
        pilot = db.execute("SELECT result FROM source_snapshots WHERE cache_key='research:sorriso:pilot'").fetchone()
        if pilot:
            value = json.loads(pilot[0]); history = db.execute('SELECT result FROM source_snapshots WHERE cache_key=?', ('history:' + value['dataset_id'],)).fetchone()
            if history:
                value = json.loads(history[0]); print('Referência Sorriso:', value['status'], '· corte', value['parameters']['as_of'], '·', len(value.get('points', [])), 'leituras')
    print('Antes da reunião: iniciar servidor, abrir Sorriso, conferir mapas/gráficos e testar uma pergunta ao assistente.')


if __name__ == '__main__':
    main()
