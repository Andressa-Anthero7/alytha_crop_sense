"""Small reviewed reference library; retrieval is separate from local observations."""
from .assistant_intents import normalize

SOIL_URL='https://bioinfo.cnpso.embrapa.br/seca/index.php?Itemid=478&id=75&option=com_content&view=article'
PHENOLOGY_URL='https://www.infoteca.cnptia.embrapa.br/bitstream/doc/697293/1/DOC2010103.pdf'
CARDS=[
    {'id':'agro_plantio_direto','source':'Embrapa Soja · Manejo do solo', 'url':SOIL_URL,
     'terms':['plantio direto','palhada','cobertura do solo','rotacao','preparo'],
     'text':'O sistema plantio direto combina pouco revolvimento, cobertura permanente e rotação de culturas. A palhada ajuda a proteger o solo e conservar água. A semeadura pode ocorrer sobre resíduos da cultura anterior.',
     'scope':'Conhecimento geral; não confirma o sistema de manejo da área selecionada.'},
    {'id':'agro_agua_solo','source':'Embrapa Soja · Manejo do solo', 'url':SOIL_URL,
     'terms':['seca','chuva','umidade','agua','raiz','raizes','compactacao','veranico'],
     'text':'A disponibilidade de água depende de infiltração, armazenamento no solo e acesso pelas raízes. Cobertura, estrutura do solo e crescimento radicular influenciam esse processo. Uma avaliação de estresse hídrico precisa considerar chuva e condições do solo.',
     'scope':'Conhecimento geral; o projeto não fornece diagnóstico meteorológico por esta referência.'},
    {'id':'agro_fenologia_soja','source':'Embrapa Agropecuária Oeste · Documentos 103 (2010), páginas 9–12', 'url':PHENOLOGY_URL,
     'terms':['fenologia','estadio','fase','florescimento','floracao','vagem','grao','maturacao','emergencia','r1','r5','vegetativo','reprodutivo'],
     'text':'A soja tem estádios vegetativos e reprodutivos. A fase vegetativa se inicia na emergência; os estádios reprodutivos descrevem florescimento, formação de vagens, desenvolvimento dos grãos e maturação. Identificar um estádio exige observar características das plantas.',
     'scope':'Referência conceitual de 2010; não usar suas cultivares ou calendários como recomendações atuais.'},
    {'id':'agro_ciclo_soja','source':'Embrapa Agropecuária Oeste · Documentos 103 (2010), páginas 9–10', 'url':PHENOLOGY_URL,
     'terms':['ciclo','dias','plantio','semeadura','colheita','temperatura','cultivar','fotoperiodo'],
     'text':'A duração do desenvolvimento varia com cultivar e ambiente, incluindo temperatura e comprimento do dia. Não existe uma duração única aplicável a toda lavoura. O acompanhamento precisa combinar datas de campo e condições locais.',
     'scope':'Conhecimento geral; não determina a data local de semeadura ou colheita.'},
]


def retrieve(question, limit=3):
    text=normalize(question)
    ranked=sorted(enumerate(CARDS),key=lambda pair:(-sum(term in text for term in pair[1]['terms']),pair[0]))
    return [{key:value for key,value in card.items() if key!='terms'} for _,card in ranked
            if any(term in text for term in card['terms'])][:limit]
