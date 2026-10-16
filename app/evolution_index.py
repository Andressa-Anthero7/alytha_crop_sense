"""Auditable evidence scores, without calibrated management probabilities."""
import math
from datetime import date
from . import storage, research

WEIGHTS={'temporal':25,'spatial':25,'direction':20,'historical':15,'calendar':5,'quality':10}
LABELS={'temporal':'Tendência recente do NDVI','spatial':'Extensão e predominância da mudança',
        'direction':'Sequência espacial','historical':'Soja histórica no recorte',
        'calendar':'Janela de plantio declarada','quality':'Qualidade e atualidade das leituras'}


def bounded(value):
    return max(0,min(1,float(value))) if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else 0


def historical_cover(history,cutoff):
    code=history['parameters'].get('municipality_code')
    saved=storage.source_snapshot('municipal-soy:v1:'+str(code))
    if not saved:return None
    data=saved['result']
    if type(data.get('year')) is not int or data['year']>=date.fromisoformat(cutoff).year:return None
    from shapely.geometry import shape,mapping
    from shapely.ops import unary_union
    from rasterio.warp import transform_geom
    geometry=history['parameters']['geometry'];area=shape(geometry)
    intersections=[]
    for feature in data.get('features',[]):
        candidate=shape(feature['geometry'])
        if candidate.intersects(area):intersections.append(candidate.intersection(area))
    projected=shape(transform_geom('EPSG:4326','EPSG:6933',geometry)).area
    if not projected:return None
    overlap=shape(transform_geom('EPSG:4326','EPSG:6933',mapping(unary_union(intersections)))).area if intersections else 0
    return {'fraction':bounded(overlap/projected),'year':data['year'],'source':'MapBiomas · recortes municipais de soja histórica','note':'Recortes históricos disponíveis de pelo menos 5 ha; não confirma a cultura atual.'}


def planting_window(history,data,cutoff):
    key='evolution-window:v1:'+research.fingerprint(history['parameters']['geometry'])
    if 'planting_window' in data:
        supplied=data['planting_window']
        if not isinstance(supplied,dict):raise ValueError('Informe início e fim da janela de plantio.')
        try:first=date.fromisoformat(supplied['from']);last=date.fromisoformat(supplied['to'])
        except (ValueError,KeyError,TypeError):raise ValueError('Datas da janela de plantio inválidas.') from None
        if not 0<=(last-first).days<=180:raise ValueError('A janela de plantio precisa ter início e fim em até 180 dias.')
        record={'from':first.isoformat(),'to':last.isoformat(),'source':'Janela declarada pelo usuário, sem verificação externa','declared_at':storage.now()}
        storage.source_snapshot(key,record)
    saved=storage.source_snapshot(key)
    if not saved:return None
    record=saved['result']
    if record['declared_at'][:10]>cutoff:return None
    return record


def calculate(history,cutoff,comparison,spatial,cover=None,window=None):
    current=comparison.get('current',{});usable=bool(current.get('usable'))
    spatial_ready=bool(spatial and spatial.get('status')=='ready')
    progression=(spatial or {}).get('progression',{})
    result={'name':'Índice de Evidências de Evolução Vegetal','version':1,'scale':[0,100],
            'as_of':cutoff,'status':'ready' if usable and spatial_ready else 'partial' if usable else 'insufficient',
            'experimental':True,'is_probability':False,'scope':'mesmo recorte e data de acompanhamento',
            'historical_cover':cover,'planting_window':window,'scores':{},
            'note':'Pontos de evidências, não porcentagem de chance, área plantada ou produtividade. Pesos e faixas experimentais, ainda sem validação agronômica. Fatores correlacionados não representam confirmações independentes.'}
    for signal,title in [('vegetation_gain','Expansão da vegetação'),('vegetation_loss','Redução da vegetação')]:
        direction=1 if signal=='vegetation_gain' else -1
        factors=[]
        def add(key,available,value,reason):
            factors.append({'id':key,'label':LABELS[key],'weight':WEIGHTS[key],'available':bool(available),
                            'points':round(WEIGHTS[key]*bounded(value),1) if available else 0,'reason':reason})
        add('temporal',usable,direction*current.get('slope_day',0)/.006,
            f"{current.get('observations',0)} observações; tendência {current.get('trend','não informada')}." if usable else 'Série recente insuficiente ou antiga.')
        observed=(spatial or {}).get('observed_area_ha',0)
        gain=(spatial or {}).get('vegetation_gain_ha',0);loss=(spatial or {}).get('vegetation_loss_ha',0)
        add('spatial',spatial_ready,direction*(gain-loss)/observed/.25 if observed else 0,
            f'Ganho: {gain:.2f} ha; redução: {loss:.2f} ha; área observada: {observed:.2f} ha.' if spatial_ready else 'Falta comparação espacial válida.')
        fronts=[f for f in progression.get('fronts',[]) if f['signal']==signal]
        amount=sum(f['affected_area_ha'] for f in fronts)
        order=sum(f['spatial_order_r2']*f['affected_area_ha'] for f in fronts)/amount if amount else 0
        add('direction',spatial_ready and progression.get('status') in ('detected','not_detected'),
            bounded(amount/observed/.25)*bounded(order/.75) if observed else 0,
            f'{len(fronts)} frentes; {amount:.2f} ha em sequência.' if progression else 'Direção não avaliada nesta versão da análise.')
        add('historical',cover is not None,cover['fraction']/.8 if cover else 0,
            f"{cover['fraction']*100:.1f}% do recorte intersecta soja histórica de {cover['year']}." if cover else 'Sem cobertura de soja histórica verificada para este recorte e data.')
        in_window=bool(window and window['from']<=cutoff<=window['to'])
        add('calendar',window is not None and signal=='vegetation_gain',1 if in_window else 0,
            f"Janela declarada: {window['from']} a {window['to']}; {'dentro' if in_window else 'fora'} na data de corte." if window and signal=='vegetation_gain' else 'Calendário de colheita não avaliado.' if signal=='vegetation_loss' else 'Janela regional não inferida; informe uma janela conhecida.')
        age=(date.fromisoformat(cutoff)-date.fromisoformat(current['last_observation'])).days if current.get('last_observation') else 15
        quality=bounded(current.get('mean_observed_fraction',0))*bounded(current.get('observations',0)/6)*bounded(1-max(0,age)/30)
        add('quality',usable,quality,'Combina cobertura válida, número de leituras e idade da última observação.' if usable else 'Leituras recentes insuficientes.')
        total=round(sum(f['points'] for f in factors),1) if usable else None
        available=sum(f['weight'] for f in factors if f['available'])
        result['scores'][signal]={'label':title,'value':total,'available_weight':available,'factors':factors,
            'level':'insuficiente' if total is None else 'limitada' if total<40 else 'moderada' if total<70 else 'elevada',
            'hypothesis':'Possível estabelecimento/desenvolvimento vegetal; plantio não confirmado.' if signal=='vegetation_gain' else 'Possível redução por colheita, dessecação, senescência ou outros eventos; operação não confirmada.'}
    return result


def build(history,cutoff,comparison,spatial,data):
    try:cover=historical_cover(history,cutoff)
    except (ValueError,KeyError,ImportError):cover=None
    window=planting_window(history,data,cutoff)
    return calculate(history,cutoff,comparison,spatial,cover,window)
