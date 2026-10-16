"""Reviewed regional references are separate from user declarations.

Import requires source and applicability. No date is inferred from a state name
or from a generic agronomic reference; ZARC conditions must match explicitly.
"""
import argparse
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from . import storage, research

FIELDS = ('crop','season','state_code','municipality_code','soil','cultivar_group','risk_percent','management')


def validate(record):
    if not isinstance(record,dict):raise ValueError('Referência de calendário inválida.')
    for key in ('crop','season','state_code','kind','source_url','source_title','valid_from','valid_to','reviewed_by','reviewed_at','windows'):
        if not record.get(key):raise ValueError('Campo obrigatório na referência regional: '+key)
    if record['kind'] not in ('agronomic_reference','zarc','sanitary_calendar'):
        raise ValueError('Distinga referência agronômica, ZARC e calendário sanitário.')
    if not isinstance(record['state_code'],str) or not re.fullmatch(r'\d{2}',record['state_code']):
        raise ValueError('Estado inválido no calendário.')
    if record.get('municipality_code') and not re.fullmatch(record['state_code']+r'\d{5}',record['municipality_code']):
        raise ValueError('Município incompatível com o estado da referência.')
    parsed=urlsplit(record['source_url']);host=parsed.hostname or ''
    if parsed.scheme!='https' or not (host.endswith('.gov.br') or host.endswith('.embrapa.br') or host=='embrapa.br'):
        raise ValueError('Referência regional exige URL de fonte oficial.')
    first,last=date.fromisoformat(record['valid_from']),date.fromisoformat(record['valid_to'])
    if first>last:raise ValueError('Vigência regional invertida.')
    date.fromisoformat(record['reviewed_at'][:10])
    if record['kind']=='zarc' and any(record.get(k) is None for k in ('municipality_code','soil','cultivar_group','risk_percent','management')):
        raise ValueError('ZARC exige município, solo, grupo de cultivar, risco e manejo explícitos.')
    if record.get('risk_percent') is not None and record['risk_percent'] not in (20,30,40):
        raise ValueError('Percentual de risco ZARC inválido.')
    if not isinstance(record['windows'],list) or not record['windows']:raise ValueError('Informe os intervalos da referência.')
    windows=[]
    for window in record['windows']:
        start,end=date.fromisoformat(window['from']),date.fromisoformat(window['to'])
        if not first<=start<=end<=last:raise ValueError('Janela fora da vigência da referência.')
        windows.append({'from':start.isoformat(),'to':end.isoformat()})
    return {**record,'windows':windows,'origin':'reviewed_regional_reference','version':1}


def register(record):
    validated=validate(record);identifier=research.fingerprint(validated)
    storage.source_snapshot('regional-calendar:v1:'+identifier,{**validated,'id':identifier})
    return identifier


def compare(data, cutoff):
    # Missing crop/season does not authorize the system to infer them from NDVI.
    if not all(data.get(k) for k in ('declared_crop','season','municipality_code')):
        return {'status':'inconclusive','references':[], 'reading':'Informe cultura, safra e município para cruzar referências regionais; não são inferidos pelas imagens.'}
    requested={'crop':data['declared_crop'],'season':data['season'],'municipality_code':data['municipality_code'],
               'state_code':data['municipality_code'][:2],**{k:data[k] for k in FIELDS[4:] if k in data}}
    with storage.connect() as db:
        records=[json.loads(row[0]) for row in db.execute("SELECT result FROM source_snapshots WHERE cache_key >= 'regional-calendar:v1:' AND cache_key < 'regional-calendar:v1;'")]
    matches=[];missing=set()
    for record in records:
        if any(record.get(k) is not None and record[k]!=requested.get(k) for k in FIELDS[:4]):continue
        if not record['valid_from']<=cutoff<=record['valid_to']:continue
        applicable=True
        for key in FIELDS[4:]:
            if record.get(key) is not None and key not in requested:
                missing.add(key);applicable=False
            elif record.get(key) is not None and record[key]!=requested[key]:applicable=False
        if applicable:
            matches.append({**record,'inside':any(w['from']<=cutoff<=w['to'] for w in record['windows']),
                            'retrospective_review':record['reviewed_at'][:10]>cutoff})
    return {'status':'ready' if matches else 'inconclusive','references':matches,'missing_conditions':sorted(missing),
        'reading':'Referências regionais compatíveis recuperadas; cada tipo e suas condições permanecem separados da janela declarada.' if matches else 'Não há referência regional revisada compatível com todas as condições informadas. Nenhuma janela oficial foi presumida.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('file',type=Path);args=parser.parse_args()
    print(register(json.loads(args.file.read_text(encoding='utf-8'))))


if __name__=='__main__':main()
