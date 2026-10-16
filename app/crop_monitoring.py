"""One-area monitoring: dated history, CV changes and learned vegetation profile."""
import csv
import json
import re
from datetime import date,timedelta
from pathlib import Path
from . import research,storage

OUTPUT_ROOT=Path(__file__).resolve().parents[1]/'data/outputs/monitoring'


def spatial_for(history, cutoff, job_id=None):
    area_id=research.fingerprint(history['parameters']['geometry'])
    if job_id:
        if not isinstance(job_id,str) or not re.fullmatch('[a-f0-9]{64}',job_id):raise ValueError('Consulta espacial inválida.')
        saved=storage.source_snapshot('cv:job:'+job_id)
        if not saved:raise ValueError('Consulta espacial não encontrada.')
        candidates=[saved['result']]
    else:
        with storage.connect() as db:
            candidates=[json.loads(row['result']) for row in db.execute("SELECT result FROM source_snapshots WHERE cache_key LIKE 'cv:job:%'")]
    matching=[]
    for candidate in candidates:
        params=candidate.get('parameters',{})
        valid=params.get('area_id')==area_id and params.get('algorithm_version',0)>=2 and params.get('as_of','9999')<=cutoff
        periods=candidate.get('periods',[])
        if periods:
            valid=valid and all(period['to']<=cutoff for period in periods) and periods[-1]['to']>=(date.fromisoformat(cutoff)-timedelta(days=15)).isoformat()
        if job_id and not valid:raise ValueError('A análise espacial precisa ser do mesmo recorte e de um período compatível com a data selecionada.')
        if valid and candidate.get('status') in ('ready','inconclusive') and periods:matching.append(candidate)
    return max(matching,key=lambda item:(item['parameters']['as_of'],item['parameters'].get('algorithm_version',0),item.get('updated_at',''))) if matching else None


def report(data, analysis=None):
    history=research.dataset(data.get('dataset_id'))
    cutoff=data.get('date') or history['parameters']['as_of']
    if not isinstance(cutoff,str) or not date(2018,1,1)<=date.fromisoformat(cutoff)<=date.fromisoformat(history['parameters']['as_of']):
        raise ValueError('Data de acompanhamento fora do histórico disponível.')
    analysis=analysis or research.analyze(history['id'],cutoff)
    spatial=spatial_for(history,cutoff,data.get('spatial_job_id'))
    comparison=analysis.get('historical_comparison',{})
    patterns=analysis.get('vegetation_patterns')
    profile=None
    if patterns:
        groups=sorted(patterns['groups'],key=lambda group:group['mean_ndvi'])
        rank=next((index for index,group in enumerate(groups) if group['id']==patterns['current_group']),None)
        if rank is not None:
            label='menor presença de vegetação' if rank==0 else 'maior presença de vegetação' if rank==len(groups)-1 else 'presença intermediária de vegetação'
            profile={'kind':'unsupervised','group_id':patterns['current_group'],'rank':rank+1,'groups':len(groups),'windows':patterns['windows'],
                     'reading':f'O comportamento recente se aproxima de um padrão histórico de {label}. Esse perfil não identifica a cultura ou o manejo.'}
    changed=comparison.get('reading','Ainda não há histórico suficiente para comparar este período.')
    priority='acompanhar a continuidade da vegetação'
    next_signal='Acompanhar se o crescimento da vegetação se mantém nos próximos períodos, sem antecipar uma previsão de produção.'
    where='Falta uma comparação espacial compatível deste recorte para localizar as mudanças.'
    geojson={'type':'FeatureCollection','features':[]}
    spatial_summary={'status':'unavailable'}
    progression={'status':'unavailable','fronts':[],'geojson':{'type':'FeatureCollection','features':[]}}
    features={}
    current=comparison.get('current',{})
    if current.get('usable'):
        features.update({f'temporal_{key}':current[key] for key in ('mean_ndvi','latest_ndvi','amplitude','slope_day','mean_observed_fraction','observations')})
        features['temporal_from']=current['from']
    reference=comparison.get('reference',{})
    if reference:
        features.update(historical_years=reference['years'],historical_difference=reference['difference_from_median'])
    if spatial:
        spatial_summary={key:spatial[key] for key in ('status','periods','analysis_area_ha','observed_area_ha','unobserved_area_ha','common_coverage')}
        spatial_summary['job_id']=spatial['id']
        progression=spatial.get('progression',progression)
        if spatial['status']=='ready':
            low=spatial['persistent_low_ha'];gain=spatial['vegetation_gain_ha'];loss=spatial['vegetation_loss_ha']
            spatial_summary.update(persistent_low_ha=low,vegetation_gain_ha=gain,vegetation_loss_ha=loss)
            gain_text=f'{gain:.2f}'.replace('.',',');loss_text=f'{loss:.2f}'.replace('.',',');low_text=f'{low:.2f}'.replace('.',',')
            where=f'Na parte acompanhada do recorte: {gain_text} ha com ganho de vegetação, {loss_text} ha com redução e {low_text} ha com baixo vigor persistente. As manchas aparecem no mapa; o restante não recebeu esses sinais.'
            geojson=spatial['change_geojson']
            features.update({f'spatial_{key}':value for key,value in spatial['ml_features'].items()})
            features.update(spatial_from=spatial['periods'][0]['from'],spatial_to=spatial['periods'][-1]['to'])
            if loss>0:
                priority='revisar as manchas de redução da vegetação'
                next_signal='Acompanhar se a redução permanece nas mesmas manchas ou se há recuperação. Essa mudança ainda não identifica colheita, dessecação ou dano à lavoura.'
            elif gain>0:
                priority='acompanhar as manchas de ganho de vegetação'
                next_signal='Acompanhar se o ganho se mantém e se amplia no recorte. Isso fortalece a hipótese de estabelecimento vegetal, sem confirmar soja ou semeadura.'
            elif low>0:
                priority='acompanhar as manchas de baixo vigor'
                next_signal='Acompanhar se a vegetação começa a aumentar nas manchas de baixo vigor. A condição atual não permite afirmar se houve semeadura, preparo ou pousio.'
        else:
            where='A comparação espacial ficou inconclusiva: falta acompanhar os mesmos pontos em pelo menos metade do recorte. Nenhuma mancha foi atribuída à área sem leitura.'
            priority='ampliar o acompanhamento do recorte'
    from . import evolution_index
    index=evolution_index.build(history,cutoff,comparison,spatial,data)
    for signal,score in index['scores'].items():
        if score['value'] is not None:features['evolution_index_'+signal]=score['value']
    result={'dataset_id':history['id'],'area_id':research.fingerprint(history['parameters']['geometry']),
            'municipality_code':history['parameters'].get('municipality_code','5107925'),'as_of':cutoff,
            'scope':'recorte específico; não representa toda a cidade','geometry':history['parameters']['geometry'],
            'status':'ready' if spatial and spatial['status']=='ready' else 'partial',
            'what_changed':changed,'where_changed':where,'next_signal':next_signal,'priority':priority,
            'historical_comparison':comparison,'learned_profile':profile,'spatial':spatial_summary,'geojson':geojson,
            'progression':progression,
            'evolution_index':index,
            'combined_features':{'area_id':research.fingerprint(history['parameters']['geometry']),'as_of':cutoff,**features},
            'note':'Sinais de monitoramento, sem confirmação de cultura, operação de manejo ou produtividade. O perfil aprendido serve como referência de comportamento e não prevê a produção.'}
    result['id']=research.fingerprint([history['id'],cutoff,comparison,spatial['id'] if spatial else None,features,index,2])
    return result


def export(result):
    folder=OUTPUT_ROOT/result['id'];folder.mkdir(parents=True,exist_ok=True)
    (folder/'acompanhamento.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (folder/'mudancas.geojson').write_text(json.dumps(result['geojson'],ensure_ascii=False),encoding='utf-8')
    (folder/'direcao.geojson').write_text(json.dumps(result['progression']['geojson'],ensure_ascii=False),encoding='utf-8')
    row=result['combined_features']
    with (folder/'caracteristicas_combinadas_ml.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    return str(folder)


def create(data):
    result=report(data)
    export(result)
    return result


def evidence(result):
    evidence={key:value for key,value in result.items() if key not in ('geojson','geometry','combined_features','historical_comparison','progression')}
    if 'progression' in result:evidence['progression']={key:value for key,value in result['progression'].items() if key!='geojson'}
    return evidence
