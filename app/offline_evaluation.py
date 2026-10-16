"""Save an offline regression report and a real, local-only demonstration."""
import argparse
import io
import json
import unittest
from pathlib import Path
from . import assistant, storage

ROOT=Path(__file__).resolve().parents[1]


class EvidenceResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.cases=[]
    def addSuccess(self,test):
        super().addSuccess(test);self.cases.append({'id':test.id(),'status':'passed'})
    def addFailure(self,test,err):
        super().addFailure(test,err);self.cases.append({'id':test.id(),'status':'failed'})
    def addError(self,test,err):
        super().addError(test,err);self.cases.append({'id':test.id(),'status':'error'})


def run(output=None):
    root=Path(output or ROOT/'data/outputs/assistant');root.mkdir(parents=True,exist_ok=True)
    report={'version':1,'started_at':storage.now(),'purpose':'Regressão técnica; não validação agronômica.'}
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=EvidenceResult).run(suite)
    report['tests']={'total':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
                     'skipped':len(result.skipped),'passed':result.wasSuccessful(),'cases':result.cases}
    (root/'offline-tests.log').write_text(stream.getvalue(),encoding='utf-8')
    report['real_local_cases']=[]
    pilot=storage.source_snapshot('research:sorriso:pilot')
    if pilot:
        dataset=pilot['result']['dataset_id']
        conversation_id=None
        for question in ('Compare o histórico das safras anteriores','Qual a direção do esverdeamento?',
                         'Qual a janela de plantio declarada?', 'Faça uma síntese das hipóteses e alternativas'):
            response=assistant.ask({'prompt':question,'dataset_id':dataset,'conversation_id':conversation_id},{})
            conversation_id=response['conversation_id']
            report['real_local_cases'].append({'question':question,'response':response})
    report['finished_at']=storage.now()
    file=root/'offline-evaluation.json'
    file.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'report':str(file),'tests':result.testsRun,'passed':result.wasSuccessful(),
                      'real_local_cases':len(report['real_local_cases'])}))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args()
    report=run(args.output)
    raise SystemExit(0 if report['tests']['passed'] else 1)
