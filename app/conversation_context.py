"""Opaque server-side conversation continuity; the current selection wins."""
import re
import secrets
from datetime import datetime, timedelta, timezone
from . import storage

FIELDS = ('dataset_id', 'area_geojson', 'municipality_code', 'state_code', 'map_date',
          'map_year', 'crop_class_ids', 'season', 'declared_crop')


def restore(data):
    token = data.get('conversation_id')
    prior = {}
    if token:
        if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{64}', token):
            raise ValueError('Identificador de conversa inválido.')
        saved = storage.source_snapshot('conversation:v1:' + token)
        if saved and datetime.fromisoformat(saved['fetched_at']) >= datetime.now(timezone.utc) - timedelta(hours=24):
            prior = saved['result']
    # Presence (including explicit null) means the current map made a decision.
    changed = any(key in data and data[key] != prior.get(key)
                  for key in ('dataset_id', 'area_geojson', 'municipality_code', 'state_code'))
    if changed:
        prior = {}
    merged = {**prior, **data}
    from .assistant_intents import normalize
    prompt = normalize(data.get('prompt','')) if isinstance(data.get('prompt'),str) else ''
    if re.search(r'\b(?:nao|nunca)\b',prompt):prompt=''
    season = re.search(r'\bsafra\s+(20\d{2})\s*/\s*(20\d{2}|\d{2})\b',prompt)
    if season:
        first,last=season.groups();last=last if len(last)==4 else first[:2]+last
        if int(last) not in (int(first),int(first)+1):raise ValueError('Safra declarada inválida.')
        merged['season']=first+'/'+last
    crop = re.search(r'\bcultura\s+(?:declarada\s+)?(?:e\s+)?(soja|milho|sorgo|algodao|arroz|cana|cafe)\b',prompt)
    if crop:merged['declared_crop']=crop.group(1)
    cutoff = re.search(r'\b(?:ate|data de corte|analise em)\s+(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\b',prompt)
    if cutoff:
        from .analytical_assistant import _date
        merged['map_date']=_date(cutoff.group(1))
    for key in ('season', 'declared_crop'):
        if merged.get(key) is not None and (not isinstance(merged[key], str) or len(merged[key]) > 200):
            raise ValueError('Cultura ou safra declarada inválida.')
    return merged


def save(data, response):
    token = secrets.token_hex(32)
    state = {key: data[key] for key in FIELDS if data.get(key) is not None}
    action = response.get('action', {})
    if action.get('kind') == 'select_region' and action.get('region'):
        region = action['region']
        state = {'state_code': region['code'][:2], 'map_year': data.get('map_year', 2025)}
        if region['kind'] == 'municipality':
            state['municipality_code'] = region['code']
    storage.source_snapshot('conversation:v1:' + token, state)
    response['conversation_id'] = token
    response['conversation_context'] = {key: state[key] for key in FIELDS if key in state and key != 'area_geojson'}
    return response
