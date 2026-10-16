"""Resolve explicit navigation and short crop-statistics requests in the map app."""
import re
import unicodedata

CROPS={39:r'\bsoja\b',20:r'\bcana(?: de acucar)?\b',40:r'\barroz\b',62:r'\balgodao\b',46:r'\bcafe\b',47:r'\b(?:citros|citrus|laranja)\b',35:r'\bdende\b'}


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.lower()) if not unicodedata.combining(c)).strip()


def resolve(question, conversation):
    text=normalize(question)
    direct_map=bool(re.search(r'\bonde\b|\bno mapa\b|\b(?:mostr[ae]|mostrar|exib[ae]|exibir|marqu[ae]|marcar|destaqu[ae]|destacar|localiz[ae]|localizar|veja|ver)\b',text))
    # A short continuation is a new instruction, with its crop resolved from
    # the nearest user question. Assistant prose never authorizes a map action.
    followup=bool(re.fullmatch(r'(?:sim[, ]+)?(?:no mapa|mostra no mapa|mostrar no mapa|mostre no mapa|quero ver no mapa|isso no mapa)[.!?\s]*',text))
    reference=text
    if followup:
        for turn in reversed(conversation):
            prior=normalize(turn['question'])
            if any(re.search(pattern,prior) for pattern in CROPS.values()) or re.search(r'\b(?:milho|sorgo)\b',prior):
                reference=prior;break
            if not re.fullmatch(r'(?:no mapa|mostra no mapa|mostrar no mapa|mostre no mapa)[.!?\s]*',prior):break
    classes=[code for code,pattern in CROPS.items() if re.search(pattern,reference)]
    negated=bool(re.search(r'\b(?:nao|nunca|evite|sem)\b',text))
    explanatory=bool(re.match(r'(?:por que|porque|como|o que|qual|quais|explique)\b',text))
    other_topic=bool(re.search(r'\b(?:comprar|compra|vender|venda|preco|cotacao|vigor|baixo|ganho|reducao|dano|emergencia|produtividade|colheita)\b',text))
    if (direct_map or followup) and not negated and not explanatory and not other_topic:
        if classes:return {'kind':'crop_map','class_ids':classes,'continuation':followup}
        if re.search(r'\b(?:milho|sorgo)\b',reference):return {'kind':'unsupported_crop_map','class_ids':[]}
    if re.fullmatch(r'(?:a |dados (?:de |da )?|qual (?:e |a )?)?producao (?:de |da )?soja[.!?\s]*',text):
        return {'kind':'soy_production','class_ids':[]}
    return {'kind':'conversation','class_ids':[]}


def focus(question):
    text=normalize(question)
    if re.search(r'\b(?:producao|produtividade|toneladas|conab|sacas)\b',text) and not re.search(r'\b(?:talhao|recorte|mancha|vigor|ndvi|vegetacao)\b',text):return 'production'
    return 'monitoring'


def reply(intent, grounded):
    evidence=grounded['evidence'];mapping=grounded.get('map',{})
    city=mapping.get('municipality_name') or mapping.get('state_name') or 'a cidade pesquisada'
    if intent['kind']=='crop_map':
        labels=[mapping['crop_classes'][str(code)] for code in intent['class_ids']]
        return {'answer':f"Vou destacar as áreas mapeadas com {', '.join(labels).lower()} em {city} ({mapping['year']}).",
                'evidence_ids':[],'limitations':['Mapeamento histórico; a cultura da safra atual ainda precisa ser confirmada.'],
                'action':{'kind':'filter_crops','class_ids':intent['class_ids']}}
    if intent['kind']=='unsupported_crop_map':
        return {'answer':'Milho e sorgo não têm uma camada individual neste mapa. Posso ajudar com os dados de produção regional disponíveis.',
                'evidence_ids':[],'limitations':[],'action':{'kind':'none','class_ids':[]}}
    if intent['kind']=='soy_production':
        conab=next((item for item in evidence if item['id']=='conab_state'),None)
        records=conab.get('records',{}).get('SOJA',[]) if conab else []
        usable=[row for row in records if isinstance(row.get('production_t'),(int,float)) and not isinstance(row['production_t'],bool)]
        if usable:
            row=max(usable,key=lambda record:record['season'])
            tonnes=f"{row['production_t']:,.0f}".replace(',','.')
            answer=f"Na base CONAB disponível, a produção de soja de {conab['uf']} na safra {row['season']} é de {tonnes} toneladas. Esse total é estadual. Quer localizar as áreas de soja no mapa de {city}?"
            ids=['conab_state']
        else:
            answer=f'Você quer consultar os números da produção regional ou localizar as áreas de soja no mapa de {city}?'
            ids=[]
        return {'answer':answer,'evidence_ids':ids,'limitations':[],'action':{'kind':'none','class_ids':[]}}
    return None
