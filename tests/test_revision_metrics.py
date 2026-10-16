from copy import deepcopy
from unittest import TestCase
from tracker import attempt_revision as ar, revision_metrics as rm, operation_outcomes as oo
from tracker.schema import digest
from research.attempt_revision_trial import fixture,CASES


def sample():
    run,doc=fixture(CASES[0])
    def decide(req):
        choice='procedure_change' if req['state']['stage']=='declared_change' else req['state']['current']['unit_id']
        return {k:{'value':choice} for k in req['questions']},digest(req)
    doc['attempt_revisions']=ar.build(run,doc,decide)
    doc['operation_outcomes']={'schema':oo.VERSION,'source_hash':digest(run),'observations':[
        {'action_event_id':a['id'],'response_event_id':r['id'],'outcome':'failed' if i==0 else 'completed',
         'complete_readable_response':True,'complete_readable_dispatch':True} for i,(a,r) in enumerate(oo.bound_responses(run))]}
    return run,doc


class RevisionMetricsTests(TestCase):
    def test_complete_chain_and_duplicate_declarations_count_retry_once(self):
        run,doc=sample();row=doc['attempt_revisions']['observations'][0];row['declarations']*=2
        value=rm.inspect(run,doc);m=value['metrics']['enacted_revision_completion_fraction']
        self.assertEqual((m['numerator'],m['denominator']),(1,1))
        self.assertIn('e7',m['evidence']);self.assertEqual(len(value['episodes']),1)

    def test_promise_without_dispatch_and_state_assessment_never_count_as_enacted(self):
        for selected in ('no_matching_action','unresolved_execution'):
            run,doc=sample();doc['attempt_revisions']['observations'][0]['declarations'][0]['executions']['procedure_change']['selection']=selected
            self.assertEqual(rm.inspect(run,doc)['episodes'],[])
        run,doc=sample();doc['attempt_revisions']['observations'][0]['declarations'][0]['selection']='prerequisite_state'
        self.assertEqual(rm.inspect(run,doc)['episodes'],[])

    def test_unknown_result_stays_outside_completion_denominator(self):
        run,doc=sample();doc['operation_outcomes']['observations'].pop()
        m=rm.inspect(run,doc)['metrics'];self.assertEqual(m['enacted_revision_completion_fraction']['denominator'],0)
        self.assertEqual(m['enacted_revision_unknown_fraction']['numerator'],1)

    def test_failure_observed_after_declaration_is_not_adaptation_to_that_feedback(self):
        run,doc=sample();run['events'][3]['index']=run['events'][4]['index']+.5
        doc['operation_outcomes']['source_hash']=digest(run)
        self.assertEqual(rm.inspect(run,doc)['episodes'],[])

    def test_partial_result_is_known_but_not_completed(self):
        run,doc=sample();doc['operation_outcomes']['observations'][-1]['outcome']='partial'
        m=rm.inspect(run,doc)['metrics']['enacted_revision_completion_fraction']
        self.assertEqual((m['numerator'],m['denominator']),(0,1))

    def test_changed_work_and_uninspected_pair_cannot_supply_chain(self):
        for attr,value in [('status','unknown'),('work_instance','different_work')]:
            run,doc=sample();doc['attempt_revisions']['observations'][0][attr]=value
            self.assertEqual(rm.inspect(run,doc)['episodes'],[])
