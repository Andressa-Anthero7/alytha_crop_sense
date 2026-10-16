"""Reproducible live smoke evaluation; saved responses still require human review."""
import argparse
import json
from pathlib import Path
from . import assistant, storage
from .web_app import read_app_env

CASES=[
    {'id':'plantio_direto','prompt':'O que é plantio direto e por que a palhada importa?',
     'review':'Explicar cobertura, rotação e mínimo revolvimento; citar Embrapa; não diagnosticar um talhão.'},
    {'id':'fenologia','prompt':'O que significam os estádios vegetativos e reprodutivos da soja?',
     'review':'Distinguir desenvolvimento vegetativo, florescimento, vagens, grãos e maturação sem identificar fase local.'},
    {'id':'municipal','prompt':'Como está a vegetação de Sorriso nos dados disponíveis?', 'municipality_code':'5107925',
     'review':'Usar a data real e a escala municipal coletada; não inventar dados atuais ou extrapolar recortes.'},
    {'id':'modelos','prompt':'O que os modelos treinados em Sorriso já conseguem dizer sobre a lavoura?', 'municipality_code':'5107925',
     'review':'Usar perfis salvos; diferenciar agrupamento de manejo confirmado e dados de treino de imagens atuais.'},
    {'id':'causa','prompt':'O baixo vigor deste município prova seca ou falta de adubação?', 'municipality_code':'5107925',
     'review':'Não confirmar causa; explicar observações de campo e clima necessárias sem recomendar doses.'},
]


def run(destination=None):
    env=read_app_env()
    config=assistant.configuration(env)
    root=Path(destination or Path(__file__).resolve().parents[1]/'data/outputs/assistant')
    root.mkdir(parents=True,exist_ok=True)
    output=root/('evaluation-'+storage.now().replace(':','-')+'.json')
    report={'started_at':storage.now(),'configuration':config,'cases':[],
            'note':'Avaliação técnica de respostas reais. Revisão humana agronômica pendente; sucesso técnico não mede acurácia.'}
    for case in CASES:
        try:
            response=assistant.ask({key:value for key,value in case.items() if key in ('prompt','municipality_code')},env)
            report['cases'].append({**case,'status':'answered','response':response,'human_review':'pending'})
            print(case['id']+': answered',flush=True)
        except (ValueError,OSError) as exc:
            report['cases'].append({**case,'status':'error','reason':str(exc)})
            print(case['id']+': error',flush=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    report['finished_at']=storage.now()
    report['answered']=sum(c['status']=='answered' for c in report['cases'])
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(output),'answered':report['answered'],'total':len(CASES)}))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    run(args.output)
