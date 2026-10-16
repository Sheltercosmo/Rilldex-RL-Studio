"""Runner/scoring mechanics with authored responses, never semantic accuracy."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from research import native_path_selection as study
from tracker.schema import InputError,digest
from tracker.jev import DEFAULT_MODEL,SELECTION_POLICY


class NativePathSelectionTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.path=Path(folder.name)
        self.cases=[]
        for index in range(2):
            case={'case_id':'case-'+str(index),'doc_id':'authored','relation':'plan:verify' if index==0 else 'reason:execute',
                  'requests':{},'references':{}}
            for profile in study.PROFILES:
                case['requests'][profile]={'model':DEFAULT_MODEL,'state':{'subject':index,'profile':profile,'missingness':{},'cutoff_event_id':'authored'},'questions':{
                    'link_0':{'type':'choice','instructions':'Authored mechanics control','criteria':{'present':'Yes','absent':'No','unresolved':'Unknown'}}}}
                case['references'][profile]={'link_0':{'value':'present','basis':'authored','source_id':'source-'+str(index)}}
            self.cases.append(case)
        self.chains=[{'doc_id':'authored','anchors':[],'links':[{'case_id':c['case_id'],'source_id':'source-'+str(i)} for i,c in enumerate(self.cases)]}]
        self.freeze()
        self.env=patch.dict('os.environ',{'JEV_API_KEY':'fake-local-runner-test-secret'});self.env.start();self.addCleanup(self.env.stop)

    def freeze(self):
        study.write(self.path/'cases.json',self.cases);study.write(self.path/'chains.json',self.chains)
        study.write(self.path/'manifest.json',{'model':DEFAULT_MODEL,'selection_policy':SELECTION_POLICY,
            'cases_hash':digest(self.cases),'chains_hash':digest(self.chains),'code_sha256':{},'source_sha256':{},'limits':'Authored test'})

    def response(self,request,key):
        return {'model':DEFAULT_MODEL,'answers':{q:{'type':'choice','probabilities':{'present':.2,'absent':.7,'unresolved':.1},
            'choice':'present','confidence':1} for q in request['questions']},'usage':{'input_tokens':11,'output_tokens':1}}

    def test_zero_budget_makes_no_call_or_credential_prompt(self):
        with patch.object(study,'once') as call,patch.object(study.getpass,'getpass') as prompt:
            result=study.run(self.path,0,100000)
        self.assertEqual(result['status'],'budget_reached');call.assert_not_called();prompt.assert_not_called()

    def test_byte_budget_prevents_overshoot(self):
        with patch.object(study,'once') as call:
            result=study.run(self.path,100,1)
        self.assertEqual(result['calls'],0);call.assert_not_called()

    def test_resume_replays_exact_response_without_calling_or_confidence_filter(self):
        with patch.object(study,'once',side_effect=self.response) as call:
            self.assertEqual(study.run(self.path,1,100000)['calls'],1)
            self.assertEqual(study.run(self.path,0,100000)['calls'],0)
            self.assertEqual(call.call_count,1)
            self.assertEqual(study.run(self.path,3,100000)['status'],'complete')
            self.assertEqual(study.run(self.path,0,0)['status'],'complete');self.assertEqual(call.call_count,4)
        result=study.summarize(self.path)
        for profile in study.PROFILES:
            self.assertEqual(result[profile]['counts']['missed_positive'],2)
            self.assertEqual(result[profile]['counts']['transport_attempts'],2)
            self.assertEqual(result[profile]['usage']['input_tokens'],22)
            self.assertEqual(result[profile]['chain_counts']['both_links_selected'],0)

    def test_failed_transport_is_retained_and_cannot_be_silently_retried(self):
        with patch.object(study,'once',side_effect=InputError('Jev HTTP 451')) as call:
            result=study.run(self.path,2,100000)
            self.assertEqual(result['status'],'stopped_on_error')
            with self.assertRaises(InputError):study.run(self.path,2,100000)
            self.assertEqual(call.call_count,1)
        report=study.summarize(self.path)['hybrid12']
        self.assertEqual(report['counts']['failed_attempts'],1)
        self.assertEqual(report['counts']['attempts_without_reported_usage'],1)
        self.assertEqual(report['chain_counts']['requests_complete'],0)
        self.assertFalse(report['usage'])

    def test_wrong_provider_model_stays_invalid_on_resume(self):
        def wrong(request,key):return {**self.response(request,key),'model':'different-model'}
        with patch.object(study,'once',side_effect=wrong) as call:
            self.assertEqual(study.run(self.path,1,100000)['status'],'stopped_on_error')
            with self.assertRaises(InputError):study.run(self.path,1,100000)
            self.assertEqual(call.call_count,1)
        study.summarize(self.path)
        self.assertEqual(len(study.read(self.path/'summary.json')['unscored_responses']),1)

    def test_response_credential_echo_is_never_persisted(self):
        with patch.object(study,'once',side_effect=lambda request,key:{'unexpected':key}):
            self.assertEqual(study.run(self.path,1,100000)['status'],'stopped_on_error')
        contents=''.join(p.read_text(encoding='utf-8') for p in self.path.rglob('*.json'))
        self.assertNotIn('fake-local-runner-test-secret',contents)
        self.assertEqual(len(list((self.path/'wire').glob('*.json'))),1)

    def test_changed_packet_and_wrong_case_response_are_rejected(self):
        cases=copy.deepcopy(self.cases);cases[0]['requests']['hybrid12']['state']['subject']='changed'
        study.write(self.path/'cases.json',cases)
        with self.assertRaises(InputError):study.run(self.path,0,0)
        self.freeze()
        with patch.object(study,'once',side_effect=self.response):study.run(self.path,1,100000)
        path=next(p for p in (self.path/'wire').glob('*.json') if not p.name.endswith('.attempt.json'))
        saved=study.read(path);saved['case_id']='wrong-case';study.write(path,saved)
        with self.assertRaises(InputError):study.run(self.path,0,0)

    def test_unresolved_references_do_not_become_false_negatives_or_agreement(self):
        self.cases[0]['references']['hybrid12']['link_0']['value']=None;self.freeze()
        with patch.object(study,'once',side_effect=self.response):study.run(self.path,4,100000)
        report=study.summarize(self.path)['hybrid12']['counts']
        self.assertEqual(report['reference_unresolved'],1);self.assertEqual(report['scored_pairs'],1)
        self.assertEqual(report['missed_positive'],1)


if __name__=='__main__':unittest.main()
