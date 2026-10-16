from copy import deepcopy
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tracker.schema import digest,InputError
from tracker.method_comparison import build,pair_request,audit,execute,load,STAGED_VERSION,DISPATCH_VERSION
from tracker.semantic_extraction import Pipeline,FileCandidates
from research.method_comparison_trial import fixture,CASES


class MethodComparisonTests(TestCase):
    def choose(self,req):
        return {k:{'value':'same_procedure' if k=='comparison' else 'no_expressed_basis'} for k in req['questions']},digest(req)

    def test_cutoff_and_source_preservation(self):
        run,doc=fixture(CASES[0]);before=deepcopy((run,doc));calls=[]
        def choose(req):calls.append(req);return self.choose(req)
        result=build(run,doc,choose)
        self.assertEqual((run,doc),before)
        self.assertNotIn('WITHHELD_FUTURE_RESULT',str(calls))
        self.assertEqual(result['counts']['selected_pairs'],1)
        self.assertNotIn('relations',result)
        self.assertIn('Temporary timeout.',str(calls))

    def test_operation_and_announced_method_remain_separate(self):
        run,doc=fixture(CASES[5]);actions=[u for u in doc['units'] if u['kind']=='action']
        req=pair_request(run,doc,actions[0]['id'],actions[1]['id'])
        self.assertIn('browser.fill_and_submit',req['state']['current']['content']['summary']['text'])
        self.assertTrue(any('switch to the API' in r['text'] for r in req['state']['source_ranges']))
        self.assertEqual(len(req['state']['rationale_candidates']),1)

    def test_missing_text_remains_source_not_invented_units(self):
        run,doc=fixture(CASES[0]);prose=next(u for u in doc['units'] if u['source']['text']==CASES[0]['thought'])
        doc['units'].remove(prose);doc['relations']=[r for r in doc['relations'] if r['from']!=prose['id']]
        actions=[u for u in doc['units'] if u['kind']=='action']
        req=pair_request(run,doc,actions[0]['id'],actions[1]['id'])
        self.assertIn(prose['source'],req['state']['local_extraction_gaps'])
        self.assertIn(prose['source']['text'],str(req['state']['source_ranges']))
        self.assertEqual(req['state']['rationale_candidates'],[])

    def test_future_content_evidence_is_rejected(self):
        run,doc=fixture(CASES[0]);actions=[u for u in doc['units'] if u['kind']=='action']
        future=doc['units'][-1]['source']
        actions[-1]['content']['summary']['evidence'].append(future)
        with self.assertRaisesRegex(InputError,'Future evidence'):build(run,doc,self.choose)

    def test_other_trajectory_cannot_be_compared(self):
        run,doc=fixture(CASES[0]);actions=[u for u in doc['units'] if u['kind']=='action']
        actions[0]['trajectory_id']='other'
        with self.assertRaises(InputError):build(run,doc,self.choose)

    def test_wrong_group_and_duplicate_pair_are_rejected(self):
        for corrupt in ['group','duplicate']:
            run,doc=fixture(CASES[0]);history=doc['work_history']
            if corrupt=='group':history['streams'][0]['groups'][0]['occurrences'].reverse()
            else:history['recurrences']*=2
            with self.assertRaises(InputError):build(run,doc,self.choose)

    def test_limits_preserve_missingness_instead_of_negative_choices(self):
        run,doc=fixture(CASES[0])
        for setting,status in [('MAX_CHARS','needs_context_selection'),('MAX_RATIONALES','needs_rationale_retrieval')]:
            with patch('tracker.method_comparison.'+setting,0):
                result=build(run,doc,lambda req:self.fail('Limit must stop the call'))
            self.assertEqual(result['observations'][0]['status'],status)
            self.assertEqual(result['counts']['not_inspected_pairs'],1)
            self.assertEqual(result['counts']['comparisons'],{})

    def test_grouping_disagreement_is_retained(self):
        run,doc=fixture(CASES[4])
        def choose(req):return {'comparison':{'value':'different_work'},'stated_basis':{'value':'no_expressed_basis'}},digest(req)
        result=build(run,doc,choose)
        self.assertEqual(result['counts']['comparisons'],{'different_work':1})
        self.assertEqual(doc['relations'][-1]['type'],'same_action_target')

    def test_future_map_metadata_is_not_prompt_evidence(self):
        run,doc=fixture(CASES[0]);doc['work_lineage']={'latest_text':'FUTURE_TERMS'};calls=[]
        def choose(req):calls.append(req);return self.choose(req)
        build(run,doc,choose)
        self.assertNotIn('FUTURE_TERMS',str(calls))

    def test_unknown_selection_or_changed_source_is_rejected(self):
        run,doc=fixture(CASES[0])
        with self.assertRaises(InputError):build(run,doc,lambda r:({'comparison':{'value':'guessed'}},'x'))
        run['events'][0]['text']+='changed'
        with self.assertRaisesRegex(InputError,'source differs'):build(run,doc,self.choose)

    def test_instance_decision_precedes_procedure_and_replays_raw_argmax(self):
        run,doc=fixture(CASES[0]);calls=[]
        def transport(req):
            calls.append(req);answers={}
            for key,q in req['questions'].items():
                winner={'work_instance':'same_work_instance','comparison':'same_procedure','stated_basis':'no_expressed_basis'}[key]
                answers[key]={'type':'choice','choice':'unresolved','confidence':0,
                    'probabilities':{c:.4 if c==winner else .6/(len(q['criteria'])-1) for c in q['criteria']}}
            return {'model':req['model'],'answers':answers}
        with TemporaryDirectory() as d:
            engine=Pipeline(d,FileCandidates(d),transport)
            result,validation=execute(run,doc,engine,STAGED_VERSION)
            self.assertTrue(validation['argmax_replayed']);self.assertEqual(len(calls),2)
            self.assertEqual(list(calls[0]['questions']),['work_instance'])
            self.assertEqual(calls[1]['state']['work_instance_selection']['request'],digest(calls[0]))
            self.assertEqual(result['observations'][0]['comparison'],'same_procedure')
            self.assertNotIn('WITHHELD_FUTURE_RESULT',str(calls))
            self.assertEqual(build(run,doc,engine.decide,STAGED_VERSION),result)
            self.assertEqual(len(calls),2)
            view=load(run,doc,d)
            self.assertEqual(view['observations'][0]['comparison'],'same_procedure')
            self.assertTrue(view['observations'][0]['inspector_context']['source_ranges'])
            modified=deepcopy(doc);modified['review_notes']=[{'text':'new version'}]
            self.assertFalse(load(run,modified,d)['available'])

    def test_incomparable_instance_never_runs_method_or_basis_selection(self):
        run,doc=fixture(CASES[4]);calls=[]
        def choose(req):calls.append(req);return {'work_instance':{'value':'different_work'}},digest(req)
        result=build(run,doc,choose,STAGED_VERSION)
        self.assertEqual(len(calls),1);self.assertEqual(result['observations'][0]['comparison'],'different_work')
        self.assertEqual(result['observations'][0]['stated_basis'],'not_inspected')

    def test_earlier_scope_cannot_import_later_terms(self):
        run,doc=fixture(CASES[0]);actions=[u for u in doc['units'] if u['kind']=='action']
        later=next(u for u in doc['units'] if u['source']['text']==CASES[0]['thought'])
        doc['work_context']={'frames':[{'id':'frame','kind':'user_contribution','text':'Later terms','source':later['source']}],
            'observations':[{'unit_id':actions[0]['id'],'frame_ids':['frame']}]}
        with self.assertRaisesRegex(InputError,'Future evidence'):build(run,doc,self.choose,DISPATCH_VERSION)
