import unittest
from urllib.error import HTTPError
from app.collection_issues import diagnose,failure


class IssueTests(unittest.TestCase):
    def test_old_annual_failures_list_years_without_inventing_reason(self):
        issues=diagnose({'status':'partial'},history={'id':'x','status':'partial','years':[{'year':2018,'status':'error'},{'year':2019,'status':'ready','observations':4}]})
        self.assertEqual(issues[0]['category'],'sentinel_failure')
        self.assertEqual(issues[0]['detail']['years'],[{'year':2018,'issue':None}])
    def test_mapping_limit_is_not_sentinel_failure_or_absence(self):
        issues=diagnose({'status':'partial','history':{'status':'unavailable'}},activity={'status':'error','phase':'mapping','error':'Município excede o limite de processamento.'})
        self.assertEqual(issues[0]['category'],'processing_limit')
        self.assertEqual(issues[0]['source'],'MapBiomas')
        self.assertNotIn('no_soy',{i['category'] for i in issues})
    def test_empty_success_and_small_reference_are_distinct(self):
        result=diagnose({'status':'ready'},activity={'status':'ready','total':0,'total_soy_ha':0})
        self.assertEqual(result[0]['category'],'no_soy')
        result=diagnose({'status':'partial'},activity={'status':'ready','total':0,'total_soy_ha':3})
        self.assertEqual(result[0]['category'],'no_reference')
    def test_insufficient_reads_are_not_source_failure(self):
        result=diagnose({'status':'ready'},activity={'status':'ready','total':5,'summary':{'unknown_ha':50}})
        self.assertEqual(result[0]['category'],'insufficient_readings')
    def test_multiple_sources_preserve_stages(self):
        result=diagnose({'status':'partial'},dossier={'sources':{'mapbiomas':{'status':'error'},'conab':{'status':'error'}}})
        self.assertEqual({i['category'] for i in result},{'mapbiomas_failure','conab_failure'})
    def test_http_details_do_not_include_url_or_credentials(self):
        issue=failure('Sentinel-2','histórico',HTTPError('https://private/token?secret=abc',429,'private message',{},None))
        self.assertEqual(issue['reason'],'http_429');self.assertNotIn('secret',str(issue));self.assertNotIn('private',str(issue))
    def test_reference_preparation_error_is_not_automatically_sentinel(self):
        issues=diagnose({'status':'partial','history':{'status':'error','note':'Geometria incompatível.'}})
        self.assertEqual(issues[0]['category'],'reference_blocked')
    def test_undetailed_record_is_explicit(self):
        self.assertEqual(diagnose({'status':'partial'})[0]['category'],'undetailed')
    def test_failures_aggregate_causes_instead_of_oversized_payload(self):
        issue={'reason':'http_429','message':'HTTP 429'}
        result=diagnose({'status':'partial'},activity={'status':'ready','failure_count':100,'failures':[issue]*100})
        self.assertEqual(result[0]['detail']['failures'][0]['count'],100)
        self.assertEqual(len(result[0]['detail']['failures']),1)


if __name__=='__main__':unittest.main()
