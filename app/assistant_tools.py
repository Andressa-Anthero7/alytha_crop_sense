"""Bounded assistant commands. Only an explicit current request authorizes navigation."""
import re
from .assistant_intents import normalize, CROPS
from . import localities


def retry_map(prompt,data,conversation):
    text=normalize(prompt)
    if not re.search(r'\b(?:nao apareceu|nao apareceu nada|nao (?:destacou|destaco|destaca|mostrou|carregou)|mapa vazio)\b',text):return None
    if re.search(r'\b(?:nao mostre|nao destaque|nao carregue|nao tente)\b',text):return None
    if not (data.get('state_code') or data.get('municipality_code')):return None
    classes=data.get('crop_class_ids',[])
    if not classes:
        for turn in reversed(conversation):
            prior=normalize(turn['question'])
            classes=[c for c,p in CROPS.items() if re.search(p,prior)]
            if classes:break
    if not isinstance(classes,list) or any(type(c) is not int or c not in (39,20,40,62,41,46,47,35,48) for c in classes):raise ValueError('Culturas selecionadas inválidas.')
    if not classes:return None
    return {'kind':'filter_crops','class_ids':classes}


def bare_location(prompt, data):
    """An exact official place name is a navigation request, not a monitoring question."""
    text=normalize(prompt)
    if not 2<=len(text)<=100 or not re.fullmatch(r'[a-z ]+(?:\s*/\s*[a-z]{2})?',text):return None
    if len(text.split())>7:return None
    if re.search(r'\b(?:nao|nunca|como|por|porque|qual|quais|onde|explique|resuma|resumindo|sim|ok|ola|teste|depois|isso|mapa|producao|produtividade|soja|vigor|vegetacao|lavoura|plantio|colheita|safra|dados|historico|modelo|modelos|obrigado)\b',text):return None
    result=localities.search(text)
    if not result.get('exact') or not result['matches']:return None
    classes=data.get('crop_class_ids',[])
    if not isinstance(classes,list) or any(type(c) is not int or c not in (39,20,40,62,41,46,47,35,48) for c in classes):raise ValueError('Culturas selecionadas inválidas.')
    return {'kind':'select_region','query':text,'class_ids':classes,'resolved_result':result}


def command(prompt):
    text=normalize(prompt)
    if re.search(r'\b(?:nao|nunca|evite)\b',text):return None
    if re.match(r'(?:como|por que|porque|explique|o que)\b',text):return None
    # Short crop + place is itself a map request, including the common dropped s.
    short=re.fullmatch(r'(?:soja|oja|cana(?: de acucar)?|arroz|algodao|cafe|citros|citrus|laranja|dende)\s+(?:em|no estado de|na cidade de)\s+(.+?)[.!?]*',text)
    if short:
        crop_text='soja' if text.startswith('oja ') else text
        return {'kind':'select_region','query':short.group(1).strip(),
                'class_ids':[code for code,pattern in CROPS.items() if re.search(pattern,crop_text)],
                'requested_kind':'municipality' if 'na cidade de' in text else None}
    if re.search(r'\b(?:mostre|mostra|mostrar|abra|ver|veja)\b.*\b(?:baixo vigor|atividade vegetativa|atividade da soja)\b',text):
        return {'kind':'show_activity','class_ids':[]}
    if re.search(r'\b(?:abra|abrir|mostre|mostra|ver|veja)\b.*\b(?:coleta|treinamento|modelos treinados)\b',text):
        return {'kind':'show_collection','class_ids':[]}
    if re.search(r'\b(?:analise|analisar|consulte|consultar|abra|abrir|mostre|mostra|ver)\b.*\bhistorico\b',text):
        return {'kind':'analyze_area','class_ids':[]}
    if re.search(r'\b(?:atualize|atualizar)\b.*\b(?:acompanhamento|vegetacao|area|lavoura)\b',text):
        return {'kind':'update_monitoring','class_ids':[]}
    # City requests use IBGE identity, never provider-generated coordinates.
    match=re.match(r'(?:va para|ir para|abra|abrir|busque|buscar|pesquise|pesquisar|localize|localizar|mostre|mostrar|mostra|destaque|destacar|destaca|onde tem)(?:\s+(?:a cidade de|o municipio de|o mapa de|a cidade|o municipio))?\s+(.+?)[.!?]*$',text)
    if not match:return None
    query=match.group(1).strip()
    classes=[code for code,pattern in CROPS.items() if re.search(pattern,query)]
    if classes:
        place=re.search(r'\b(?:em|no municipio de|na cidade de)\s+(.+)',query)
        if not place:return None
        query=place.group(1)
    elif re.search(r'\b(?:soja|milho|sorgo|mapa|area|talhao|mancha|vigor|vegetacao|producao|historico|dados|lavoura|plantio|colheita|seca|risco|dano|culturas)\b',query):return None
    return {'kind':'select_region','query':query,'class_ids':classes,
            'requested_kind':'municipality' if re.search(r'\b(?:cidade|municipio)\b',text) else None}


def execute(action, data):
    kind=action['kind']
    if kind=='show_activity' and not data.get('municipality_code'):
        return {'answer':'Informe uma cidade e UF para abrir a atividade vegetativa no mapa.',
                'action':{'kind':'none','class_ids':[]},'evidence_ids':[],'limitations':[]}
    if kind=='select_region':
        result=action.get('resolved_result') or localities.search(action['query'])
        if action.get('requested_kind'):
            result={**result,'matches':[m for m in result['matches'] if m['kind']==action['requested_kind']]}
        elif result['exact']:
            states=[m for m in result['matches'] if m.get('kind')=='state']
            if len(states)==1:result={**result,'matches':states}
        if not result['exact'] or len(result['matches'])!=1:
            options=', '.join(f"{m['name']} / {m['uf']}" for m in result['matches'][:5])
            return {'answer':('Encontrei mais de uma localidade: '+options+'. Informe o nome completo e a UF.' if result['matches'] else 'Não encontrei essa localidade no IBGE. Informe o nome da cidade e a UF.'),
                    'action':{'kind':'none','class_ids':[]},'evidence_ids':[],'limitations':[]}
        region=result['matches'][0]
        return {'answer':f"Vou abrir {region['name']} / {region['uf']} no mapa"+(' e carregar as culturas solicitadas.' if action['class_ids'] else '.'),
                'action':{'kind':kind,'class_ids':action['class_ids'],'region':region},'evidence_ids':[], 'limitations':[]}
    if kind=='analyze_area' and not data.get('area_geojson'):
        return {'answer':'Selecione uma mancha no mapa ou desenhe o talhão para consultar o histórico dessa área.',
                'action':{'kind':'none','class_ids':[]},'evidence_ids':[],'limitations':[]}
    if kind=='update_monitoring' and not data.get('dataset_id'):
        return {'answer':'Abra o histórico da área selecionada para atualizar o acompanhamento.',
                'action':{'kind':'analyze_area' if data.get('area_geojson') else 'none','class_ids':[]},'evidence_ids':[],'limitations':[]}
    answers={'show_collection':'Vou abrir o mapa da coleta e dos municípios com modelos treinados.',
             'filter_crops':'Vou tentar carregar novamente a camada solicitada. O resultado será confirmado após o mapa responder.',
             'show_activity':'Vou abrir as classes de atividade vegetativa da soja histórica, incluindo baixo vigor. A tela mostrará a data e o andamento da consulta.',
             'analyze_area':'Vou iniciar a consulta do histórico da área selecionada.',
             'update_monitoring':'Vou solicitar a atualização do acompanhamento desta área.'}
    return {'answer':answers[kind],'action':action,'evidence_ids':[],'limitations':[]}


def read_reply(prompt, grounded):
    """Render common local summaries from computed evidence, without inferred causes."""
    text=normalize(prompt)
    city=grounded.get('map',{}).get('municipality_name') or 'o município selecionado'
    mapping=grounded.get('map',{})
    if mapping.get('state_code') and not mapping.get('municipality_code') and re.search(r'\b(?:compar|melhor|pior|vigor|vegetacao)',text) and re.search(r'\b(?:safra anterior|ano anterior|ano passado|outra safra|entre anos)\b',text):
        name=mapping['state_name'];crops=mapping.get('selected_crops',[])
        subject=' e '+', '.join(crops).lower() if crops else ''
        return {'answer':f"Continuamos em {name}{subject}. Ainda não temos uma comparação estadual consolidada de vigor com a safra anterior. Para comparar a mesma área entre anos, clique em uma mancha no mapa de {name} e abra seu histórico; os recortes de referência municipais também podem ser usados, cada um em sua própria escala.",
                'evidence_ids':[],'limitations':[],'action':{'kind':'none','class_ids':[]}}
    if re.search(r'\bmodelos?\b.*\b(?:treinad|consegu|dize|aprend)',text):
        item=next((e for e in grounded['evidence'] if e['id']=='municipal_learned_profiles'),None)
        if item:
            m=item['data']
            answer=f"Em {city}, os modelos agrupam {m['areas']} recortes em {len(m['profiles'])} perfis de vegetação, com dados até {m['period']['to']}."
            answer+=f" Há {m['atypical_areas']} recortes com comportamento diferente dentro da base usada no treino, úteis para priorizar investigação. Os perfis não confirmam plantio, colheita ou cultura atual."
            return {'answer':answer,'evidence_ids':[item['id']],'limitations':[], 'action':{'kind':'none','class_ids':[]}}
    if re.search(r'\bcomo esta\b.*\bvegetacao\b',text) and not re.search(r'\b(?:talhao|recorte|mancha|area selecionada)\b',text):
        item=next((e for e in grounded['evidence'] if e['id'] in ('municipal_vegetation','cached_municipal_vegetation')),None)
        if item and item.get('points'):
            p=item['points'][-1]
            if not all(type(p.get(k)) in (int,float) for k in ('possible_inactive_ha','unknown_ha','pending_ha')):return None
            def ha(value):return f'{value:,.0f}'.replace(',','.')+' ha'
            answer=f"Na consulta salva de {city}, até {p['date']}, {ha(p['possible_inactive_ha'])} de soja histórica tiveram baixo vigor persistente; {ha(p['unknown_ha'])} ficaram sem leitura conclusiva e {ha(p['pending_ha'])} ainda não foram avaliados."
            answer+=' Essa leitura não identifica preparo, pousio ou avanço do plantio. Para investigar uma lavoura, selecione a mancha e consulte seu histórico.'
            return {'answer':answer,'evidence_ids':[item['id']],'limitations':[], 'action':{'kind':'none','class_ids':[]}}
    return None
