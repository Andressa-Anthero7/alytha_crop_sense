"""Export cached pilot observations; automatic signals never become field labels."""
import argparse
import csv
import hashlib
import json
import shutil
import uuid
from datetime import date,timedelta
from pathlib import Path
from . import storage,research,municipalities,inactive_soy,spatial_activity

OUTPUT_ROOT=Path(__file__).resolve().parents[1]/'data/outputs/ml'

def export_dataset(code='5107925',output_root=None):
    municipalities.key(code)
    # One database snapshot prevents an advancing municipal job from mixing versions.
    with storage.connect() as db:
        db.execute('BEGIN')
        snapshots={r['cache_key']:json.loads(r['result']) for r in db.execute("SELECT cache_key,result FROM source_snapshots WHERE cache_key LIKE 'municipal-activity:%' OR cache_key LIKE 'municipal-soy:%' OR cache_key LIKE 'inactive-evidence:%' OR cache_key LIKE 'cv:job:%'")}
        labels=[dict(r) for r in db.execute('SELECT * FROM field_events')]
    jobs=[v for k,v in snapshots.items() if k.startswith('municipal-activity:') and v['parameters']['municipality_code']==code]
    if not jobs:raise ValueError('Inicie a leitura da cidade no mapa antes de exportar a base.')
    job=max(jobs,key=lambda v:v['parameters']['as_of'])
    historical=snapshots.get('municipal-soy:v1:'+code)
    if not historical:raise ValueError('O levantamento das áreas de soja ainda não terminou. Aguarde e exporte novamente.')
    end=date.fromisoformat(job['parameters']['as_of'])
    period={'from':(end-timedelta(days=60)).isoformat(),'to':end.isoformat()}
    observations=[];windows=[];areas=[];collected=0;with_readings=0
    labels_by_area={}
    for label in labels:labels_by_area.setdefault(label['area_key'],[]).append(label)
    for feature in historical['features']:
        area_id=research.fingerprint(feature['geometry'])
        origin={'area_id':area_id,'municipality_code':code,'area_ha':feature['properties']['area_ha'],'historical_year':2025,'historical_class':'soja','source':'Sentinel-2 L2A'}
        areas.append({**feature,'properties':{**feature['properties'],'area_id':area_id,'municipality_code':code}})
        key='inactive-evidence:'+hashlib.sha256(json.dumps([feature['geometry'],period],sort_keys=True).encode()).hexdigest()
        series=snapshots.get(key)
        if series is None:continue
        collected+=1
        points=sorted([p for p in series.get('points',[]) if period['from']<=p['date']<=period['to']],key=lambda p:p['date'])
        if points:with_readings+=1
        for index,p in enumerate(points):
            available=min(end,date.fromisoformat(p['date'])+timedelta(days=4)).isoformat()
            observations.append({**origin,'date_from':p['date'],'date_to':available,'ndvi_mean':p['ndvi_mean'],'valid_pixels':p.get('valid_pixels'),'valid_fraction':p.get('valid_fraction'),
                                 'quality_usable':p.get('valid_pixels',0)>=50 and p.get('valid_fraction',0)>=.5})
            past=points[:index+1]
            try:vector=research.features(past,available)
            except ValueError:continue
            matched=[label for label in labels_by_area.get(area_id,[]) if label['date_from']<=available<=label['date_to']]
            label=matched[0] if len(matched)==1 else None
            windows.append({**origin,'date_to':available,'group_id':area_id,**dict(zip(research.FEATURE_NAMES,vector)),
                            'automatic_signal':inactive_soy.classify(past,date.fromisoformat(available))['status'],
                            'target_stage':label['stage'] if label else '',
                            'label_source':'registro_de_campo' if label else '',
                            'field_reference':label['note'] if label else ''})
    folder=Path(output_root or OUTPUT_ROOT)/f'{code}-{end.isoformat()}-{uuid.uuid4().hex[:8]}'
    folder.mkdir(parents=True)
    def write_csv(name,rows,fields):
        with (folder/name).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    common=['area_id','municipality_code','area_ha','historical_year','historical_class','source']
    write_csv('observacoes.csv',observations,common+['date_from','date_to','ndvi_mean','valid_pixels','valid_fraction','quality_usable'])
    write_csv('janelas_ml.csv',windows,common+['date_to','group_id']+research.FEATURE_NAMES+['automatic_signal','target_stage','label_source','field_reference'])
    # Spatial observations remain separately dated; never join a future image
    # to an earlier temporal window or turn the CV threshold into a true label.
    area_ids={feature['properties']['area_id'] for feature in areas}
    spatial_rows={}
    for key,value in snapshots.items():
        if not key.startswith('cv:job:') or value.get('status')!='ready' or not value.get('ml_features'):continue
        area_id=value['parameters']['area_id'];first=value['periods'][0]['from'];last=value['periods'][-1]['to']
        if area_id not in area_ids or not period['from']<=first<=last<=period['to']:continue
        row={'area_id':area_id,'municipality_code':code,'date_from':first,'date_to':last,**value['ml_features']}
        spatial_rows[(area_id,first,last)]=row
    write_csv('caracteristicas_espaciais.csv',list(spatial_rows.values()),['area_id','municipality_code','date_from','date_to']+spatial_activity.FEATURE_NAMES)
    write_csv('referencias_campo.csv',[{'area_id':f['properties']['area_id'],'municipality_code':code,'date_from':'','date_to':'','stage':'','reference':''} for f in areas],['area_id','municipality_code','date_from','date_to','stage','reference'])
    (folder/'areas.geojson').write_text(json.dumps({'type':'FeatureCollection','features':areas},ensure_ascii=False),encoding='utf-8')
    labeled=sum(bool(row['target_stage']) for row in windows)
    manifest={'schema_version':1,'municipality_code':code,'created_at':storage.now(),'period':period,
              'municipal_job_id':job['id'],'municipal_job_status':job['status'],
              'collection_complete':job['status']=='ready','candidate_areas':len(areas),'cached_areas':collected,
              'areas_with_readings':with_readings,'areas_without_cached_series':len(areas)-collected,
              'observations':len(observations),'usable_feature_windows':len(windows),'field_labeled_windows':labeled,
              'spatial_feature_rows':len(spatial_rows),
              'supervised_training_ready':False,
              'note':'Base observacional para exploração e preparação de ML. Não representa comparação entre safras. Sinais automáticos não são rótulos confirmados de manejo. Prontidão para treino supervisionado exige revisão dos rótulos e validação espacial/temporal independente.'}
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'LEIA-ME.md').write_text('''# Base municipal de leituras por satélite

`observacoes.csv`: leituras reais do satélite e qualidade das imagens.
`janelas_ml.csv`: características de vegetação calculadas somente com imagens disponíveis até a data indicada. Janelas sem leituras suficientes são excluídas.
`caracteristicas_espaciais.csv`: observações de cv2 com geometria idêntica à base municipal e datas inteiramente dentro do período exportado. Pode estar vazio. Para combinar com uma janela temporal, exija a mesma área e data final espacial não posterior à data da janela. O agrupamento atual usa características temporais; estas observações espaciais ficam preparadas para a próxima etapa de ML.
`areas.geojson`: recortes de soja histórica com identificadores estáveis; não são talhões confirmados.
`referencias_campo.csv`: ficha opcional em branco para quem possui informações de manejo confirmado. Não é necessária para o aprendizado exploratório por satélite. Preencher essa ficha não importa os rótulos automaticamente no aplicativo.
`manifest.json`: período, andamento da coleta e quantidades presentes nesta exportação.

O campo `automatic_signal` é uma hipótese de triagem. Nunca o utilize como resposta correta para treinar um classificador de manejo. `target_stage` permanece vazio quando não há um registro de campo para a mesma geometria e data. A classe histórica de soja também não confirma a cultura atual.

Execute `python -m app.satellite_learning` para aprender perfis de vegetação e destacar comportamentos diferentes sem registros de campo. Separe áreas espacialmente independentes e safras diferentes para avaliação. Recortes vizinhos ou originados da mesma mancha podem vazar informação entre treino e teste; `group_id` sozinho não resolve esse problema. Sem rótulos confirmados, a base serve para exploração e agrupamento, não para demonstrar acurácia agronômica.

Se a coleta estiver em andamento, esta exportação é parcial. Execute novamente `python -m app.ml_dataset` após a conclusão para gerar um novo pacote. O exportador lê apenas o cache local e não faz novas consultas ao satélite.
''',encoding='utf-8')
    archive=Path(shutil.make_archive(str(folder),'zip',folder))
    return {'folder':str(folder),'archive':str(archive),**manifest}

def main():
    parser=argparse.ArgumentParser(description='Exporta leituras locais das cidades piloto para preparação de ML.')
    parser.add_argument('--municipality',default='5107925',help='Código IBGE; padrão Sorriso/MT.')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:result=export_dataset(args.municipality,args.output)
    except ValueError as exc:parser.error(str(exc))
    print(json.dumps(result,ensure_ascii=True,indent=2))

if __name__=='__main__':main()
