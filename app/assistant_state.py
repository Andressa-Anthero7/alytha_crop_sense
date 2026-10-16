"""State identity and saved evidence for map conversation; never infer statewide vigor."""
import json
from . import storage,data_sources

STATES={'11':('Rondônia','RO'),'12':('Acre','AC'),'13':('Amazonas','AM'),'14':('Roraima','RR'),
        '15':('Pará','PA'),'16':('Amapá','AP'),'17':('Tocantins','TO'),'21':('Maranhão','MA'),
        '22':('Piauí','PI'),'23':('Ceará','CE'),'24':('Rio Grande do Norte','RN'),'25':('Paraíba','PB'),
        '26':('Pernambuco','PE'),'27':('Alagoas','AL'),'28':('Sergipe','SE'),'29':('Bahia','BA'),
        '31':('Minas Gerais','MG'),'32':('Espírito Santo','ES'),'33':('Rio de Janeiro','RJ'),
        '35':('São Paulo','SP'),'41':('Paraná','PR'),'42':('Santa Catarina','SC'),
        '43':('Rio Grande do Sul','RS'),'50':('Mato Grosso do Sul','MS'),
        '51':('Mato Grosso','MT'),'52':('Goiás','GO'),'53':('Distrito Federal','DF')}


def context(code,year,crops):
    if not isinstance(code,str) or code not in STATES:raise ValueError('Estado inválido para a conversa.')
    if type(year) is not int or not 1985<=year<=2025:raise ValueError('Ano do mapa fora da referência disponível.')
    if not isinstance(crops,list) or any(type(c) is not int or c not in data_sources.CLASSES for c in crops):
        raise ValueError('Culturas selecionadas inválidas.')
    name,uf=STATES[code];evidence=[]
    with storage.connect() as db:
        row=db.execute("SELECT result FROM source_snapshots WHERE cache_key LIKE 'regional-scan:v1:%' AND json_extract(result,'$.parameters.kind')='state' AND json_extract(result,'$.parameters.code')=? ORDER BY fetched_at DESC LIMIT 1",(code,)).fetchone()
        learned=[json.loads(row['result']) for row in db.execute("SELECT result FROM source_snapshots WHERE cache_key LIKE ?",('ml:satellite:v1:'+code+'%',))]
    if row:
        job=json.loads(row['result']);cities=job.get('cities',[])
        evidence.append({'id':'state_collection','source':'CropSense · coleta regional salva','scope':'estado',
                         'state_code':code,'state_name':name,'status':job['status'],'as_of':job['parameters'].get('as_of'),
                         'updated_at':job.get('updated_at'),'processed':job.get('processed',0),'total':job.get('total',0),
                         'municipalities_with_reference':sum(bool(c.get('history',{}).get('id')) for c in cities),
                         'note':'Históricos pertencem a recortes de referência; não existe comparação estadual consolidada de vigor.'})
    usable=[m for m in learned if 'areas' in m and 'profiles' in m]
    if usable:
        evidence.append({'id':'state_learned_coverage','source':'CropSense · perfis municipais salvos','scope':'estado, somente recortes coletados',
                         'state_code':code,'municipalities':len(usable),'areas':sum(m['areas'] for m in usable),
                         'note':'Cobertura de treinamento; os modelos municipais não calculam vigor agregado do estado.'})
    return {'evidence':evidence,'model_status':{},'map':{'state_code':code,'state_name':name,'uf':uf,
            'municipality_code':None,'municipality_name':None,'year':year,'scope':'estado selecionado',
            'selected_crops':[data_sources.CLASSES[c] for c in crops],
            'crop_classes':{str(k):v for k,v in data_sources.CLASSES.items()}},
            'note':f'O usuário já selecionou {name}. Preserve esse contexto nas continuações. Não peça novamente a localidade. Comparação de vigor entre safras exige um recorte com histórico; não há comparação estadual consolidada.'}
