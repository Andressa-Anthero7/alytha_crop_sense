"""Separate unavailable sources, processing limits and genuinely missing references."""
from urllib.error import HTTPError,URLError


def failure(source,stage,exc):
    code=getattr(exc,'code',None)
    text=str(exc).lower() if isinstance(exc,ValueError) else ''
    reason='http_'+str(code) if isinstance(exc,HTTPError) else 'timeout' if isinstance(exc,TimeoutError) else 'connection' if isinstance(exc,URLError) else 'dependencies' if isinstance(exc,ImportError) else 'processing_limit' if any(term in text for term in ('pixels','excede o limite','recorte menor','limite de processamento')) else 'unspecified'
    messages={'timeout':'A fonte excedeu o tempo de resposta.','connection':'Não foi possível conectar à fonte.',
              'dependencies':'Dependência de processamento indisponível.','processing_limit':'Área excede o limite de processamento.',
              'http_401':'Credencial recusada (HTTP 401).','http_403':'Acesso recusado (HTTP 403).',
              'http_429':'Fonte limitou as consultas (HTTP 429).','unspecified':'Consulta falhou sem motivo técnico detalhado.'}
    return {'source':source,'stage':stage,'reason':reason,'message':messages.get(reason,'A fonte retornou HTTP '+str(code)+'.')}


def diagnose(city,dossier=None,activity=None,history=None):
    issues=[]
    def add(category,source,stage,message,detail=None):
        issues.append({'category':category,'source':source,'stage':stage,'message':message,**({'detail':detail} if detail else {})})
    sources=(dossier or city.get('dossier',{})).get('sources',{})
    for source,label in [('ibge','IBGE'),('conab','CONAB'),('mapbiomas','MapBiomas')]:
        value=sources.get(source,{})
        if value.get('status')=='error':
            detail=value.get('issue')
            category='processing_limit' if detail and detail.get('reason')=='processing_limit' else source+'_failure'
            add(category,label,'base municipal',value.get('note','Fonte indisponível.'),detail)
    if (dossier or {}).get('status')=='error' and not any(i['source']=='IBGE' for i in issues):
        add('ibge_failure','IBGE','limite municipal','Identidade ou limite municipal indisponível.',(dossier or {}).get('issue'))
    activity=activity or city.get('activity',{})
    history=history or city.get('history',{})
    if activity.get('status')=='error':
        detail=activity.get('issue');note=activity.get('error') or activity.get('note','Consulta municipal não concluída.')
        mapping=activity.get('phase')=='mapping'
        limit=(detail and detail.get('reason')=='processing_limit') or 'excede o limite' in note.lower()
        add('processing_limit' if limit else 'mapbiomas_failure' if mapping else 'sentinel_failure','MapBiomas' if mapping else 'Sentinel-2','identificação da soja' if mapping else 'atividade recente',note,detail)
    if activity.get('status')=='unavailable':
        add('credentials','Copernicus','configuração','Credenciais Copernicus ausentes; imagens não consultadas.')
    if activity.get('failure_count',0):
        grouped={}
        for item in activity.get('failures',[]):
            key=item['reason'];grouped.setdefault(key,{'reason':key,'message':item['message'],'count':0})['count']+=1
        add('sentinel_failure','Sentinel-2','atividade recente',f"Falha de consulta em {activity['failure_count']} recortes.",{'failures':list(grouped.values())})
    if history.get('status')=='error' and not history.get('id') and not history.get('years'):
        add('reference_blocked','Coleta','preparo do histórico',history.get('note','Não foi possível preparar a referência; fonte responsável não identificada.'))
    elif history.get('status') in ('partial','error'):
        years=[{'year':y['year'],'issue':y.get('issue')} for y in history.get('years',[]) if y['status']=='error']
        add('sentinel_failure','Sentinel-2','histórico do recorte','Anos sem consulta concluída: '+', '.join(str(y['year']) for y in years)+'.' if years else 'Histórico do recorte não foi concluído; registro antigo sem anos detalhados.',{'years':years})
    empty_years=[y['year'] for y in history.get('years',[]) if y['status']=='ready' and y.get('observations')==0]
    if empty_years:add('insufficient_readings','Sentinel-2','histórico do recorte','Consulta concluída sem leituras úteis nos anos: '+', '.join(map(str,empty_years))+'.')
    if activity.get('status')=='ready' and activity.get('total')==0:
        category='no_soy' if activity.get('total_soy_ha')==0 else 'no_reference'
        add(category,'MapBiomas','recorte de referência','Sem soja histórica no mapa consultado.' if category=='no_soy' else 'Sem recortes de soja histórica de pelo menos 5 ha para usar como referência.')
    elif history.get('status')=='not_applicable':
        add('no_soy','MapBiomas','recorte de referência','Sem soja histórica disponível; não foi criada uma referência artificial.')
    elif history.get('status')=='unavailable' and activity.get('status') not in ('unavailable','loading'):
        add('reference_blocked','MapBiomas','recorte de referência','Referência não disponível. Não é possível afirmar ausência de soja enquanto a identificação estiver incompleta.')
    summary=activity.get('summary',{})
    if activity.get('status')=='ready' and summary.get('unknown_ha',0)>0:
        add('insufficient_readings','Sentinel-2','classificação recente',f"{summary['unknown_ha']:.2f} ha sem classificação suficiente; não é confirmação de falha da fonte.")
    if city.get('learning',{}).get('status') in ('insufficient','error'):
        add('ml_pending','ML','perfis exploratórios',city['learning'].get('note','Perfis não disponíveis.'))
    if city.get('status') in ('partial','error') and not issues:add('undetailed','Coleta','registro antigo','Motivo não detalhado no resultado salvo; não é possível atribuir a falha a uma fonte.')
    return issues
