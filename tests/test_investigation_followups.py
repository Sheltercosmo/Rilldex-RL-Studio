import copy
import unittest

import test_training_investigations as training_fixture
import test_failure_investigations as failure_fixture
from test_continuation_studies import example
from test_training_lineage import record
from tracker import continuation_studies as cs, failure_investigations as saved
from tracker import graph_store, investigation_followups as follow, training_investigations, training_lineage
from tracker.schema import InputError, digest, dumps


class FollowupTests(unittest.TestCase):
    setUp = training_fixture.TrainingInvestigationTests.setUp
    source = training_fixture.TrainingInvestigationTests.source
    packet = training_fixture.TrainingInvestigationTests.packet
    add = training_fixture.TrainingInvestigationTests.add
    setup_comparison = training_fixture.TrainingInvestigationTests.setup_comparison
    run_fixture = failure_fixture.FailureInvestigationTests.run_fixture

    def base(self, training=False):
        if training:
            request, _ = self.setup_comparison()
            return training_investigations.save(self.store, request)
        run = self.run_fixture()
        snapshot = saved.snapshot(self.store, run=run['id'])
        return saved.save(self.store, {'controls': snapshot['controls'], 'snapshot_id': snapshot['snapshot_id'],
            'title': 'Authored workflow control', 'hypothesis': 'A possible explanation',
            'x': 'source:actions', 'y': 'source:recorded_reward'})

    def plan(self, parent, **extra):
        return follow.save(self.store, {'parent_id': parent['id'], 'action': 'plan', 'check': {
            'title': 'Audit the recorded evidence', 'hypothesis': 'Selection removes useful successes',
            'procedure': 'Inspect the same samples before and after the admission gate',
            'expected_result': 'The successful sample has a recorded rejection', **extra}})

    def finding(self, parent, **extra):
        return follow.save(self.store, {'parent_id': parent['id'], 'action': 'result', 'check': {
            'id': parent['follow_up']['checks'][0]['id'], 'assessment': 'inconclusive',
            'conclusion': 'Evidence is missing; no failure was imputed', 'evidence': [], **extra}})

    def test_three_workflows_reuse_one_schema_without_experiment_execution(self):
        root = self.base()
        cases = [('Selection audit', 'Inspect admission decisions', 'A recorded rejection'),
                 ('Reward rescore', 'Compare a fixed cohort with an independent verifier', 'Reward and independent criterion disagree'),
                 ('Recovery review', 'Inspect failure, feedback, revision and next comparable check', 'Relevant changes precede a passing recheck')]
        for title, procedure, expected in cases:
            parent = self.plan(root, title=title, procedure=procedure, expected_result=expected)
            result = self.finding(parent)
            self.assertEqual(result['snapshot'], root['snapshot'])
            self.assertEqual(result['follow_up']['checks'][0]['expected_result'], expected)
            self.assertEqual(result['follow_up']['checks'][0]['results'][0]['assessment'], 'inconclusive')
        self.assertNotIn('follow_up', saved.read(self.store, root['id']))

    def test_idempotent_retry_and_competing_revision_branches_do_not_overwrite(self):
        root = self.base(); a = self.plan(root)
        self.assertEqual(a, self.plan(root))
        b = self.plan(root, title='Check the verifier')
        self.assertEqual({r['id'] for r in follow.revisions(self.store, root['id'])['revisions']}, {a['id'], b['id']})
        self.assertEqual(a['follow_up']['root_id'], root['id'])
        self.assertEqual(saved.read(self.store, a['id']), a)

    def test_checks_can_branch_and_findings_append_without_rewriting_prediction(self):
        original = self.plan(self.base())
        one = self.finding(original)
        two = self.finding(one, conclusion='Further evidence is still missing', next_action='Capture verifier version')
        self.assertEqual(len(two['follow_up']['checks'][0]['results']), 2)
        self.assertEqual(self.finding(two, conclusion='Further evidence is still missing', next_action='Capture verifier version'), two)
        child = self.plan(two, follows_check=two['follow_up']['checks'][0]['id'], title='Check scorer provenance')
        self.assertEqual(child['follow_up']['checks'][1]['follows_check'], original['follow_up']['checks'][0]['id'])
        self.assertEqual(original['follow_up']['checks'][0]['results'], [])
        with self.assertRaises(InputError): self.plan(two, follows_check='outside-this-investigation')

    def test_support_requires_evidence_and_not_run_cannot_disguise_a_result(self):
        p = self.plan(self.base())
        for assessment in ['supports', 'contradicts', [], 'verified_cause']:
            with self.subTest(assessment=assessment), self.assertRaises(InputError):
                self.finding(p, assessment=assessment)
        not_run = self.finding(p, assessment='not_run', conclusion='Existing selection records answer the question; skip the probe')
        self.assertEqual(not_run['follow_up']['checks'][0]['results'][0]['assessment'], 'not_run')
        with self.assertRaises(InputError):
            self.finding(p, assessment='not_run', evidence=[{'kind':'investigation','id':p['id']}])

    def test_training_corrections_and_note_revisions_preserve_followups_and_original_cases(self):
        root = self.base(training=True); p = self.plan(root)
        self.add(record('selection', 'a', revision=1, decision='rejected'))
        result = self.finding(p, assessment='supports', conclusion='Recorded rejection in this selected cohort',
                              evidence=[{'kind':'investigation','id':root['id']}])
        revised = training_investigations.save(self.store, {'parent_id':result['id'], 'view':root['view'],
            'title':'Revised research question', 'hypothesis':'Test another explanation'})
        self.assertEqual(revised['snapshot'], root['snapshot'])
        self.assertEqual(revised['selected_samples'], root['selected_samples'])
        self.assertEqual(revised['follow_up'], result['follow_up'])
        self.assertEqual(revised['follow_up']['checks'][0]['basis_id'], root['id'])

    def test_result_comparison_is_an_exact_saved_reference_and_bundle_keeps_numbers(self):
        root = self.base(); p = self.plan(root)
        result = self.finding(p, assessment='contradicts', conclusion='Reviewed comparison contradicts the hypothesis',
                             evidence=[{'kind':'investigation','id':root['id']}])
        bundle = follow.bundle(self.store, result['id'])
        self.assertEqual(bundle['linked_comparisons'], [root])
        self.assertEqual(bundle['investigation'], result)
        self.assertEqual(root['id'], 'investigation-' + digest({k:v for k,v in bundle['linked_comparisons'][0].items() if k!='id'}))

    def test_live_continuation_corrections_require_review_and_old_attachment_is_unchanged(self):
        design, facts = example();cs.receive(self.store, design);training_lineage.receive(self.store, facts)
        study = cs.snapshot(self.store)['studies'][0];p = self.plan(self.base())
        ref = {'kind':'continuation','producer':study['producer'],'experiment':study['experiment'],
               'study_id':study['design']['id'],'snapshot_id':study['snapshot_id']}
        old = self.finding(p, assessment='supports', conclusion='The recorded difference supports further testing', evidence=[ref])
        corrected = copy.deepcopy(facts['records'][-1]);corrected['revision']=2;corrected['data']['value']=0
        training_lineage.receive(self.store, {**facts,'records':[corrected]})
        count = len(saved.saved(self.store))
        with self.assertRaisesRegex(InputError, 'changed'):
            self.finding(p, assessment='supports', evidence=[ref])
        self.assertEqual(len(saved.saved(self.store)), count)
        new_study = cs.snapshot(self.store)['studies'][0]
        new = self.finding(old, evidence=[{**ref,'snapshot_id':new_study['snapshot_id']}])
        values = [r['evidence'][0]['snapshot']['difference'] for r in new['follow_up']['checks'][0]['results']]
        self.assertEqual(values, [.875, .8125])
        self.assertEqual(saved.read(self.store, old['id']), old)

    def test_incomplete_continuation_evidence_keeps_unknowns(self):
        design, _ = example();cs.receive(self.store, design);study = cs.snapshot(self.store)['studies'][0]
        p = self.plan(self.base())
        r = self.finding(p, evidence=[{'kind':'continuation','producer':study['producer'],'experiment':study['experiment'],
            'study_id':study['design']['id'],'snapshot_id':study['snapshot_id']}])
        s = r['follow_up']['checks'][0]['results'][0]['evidence'][0]['snapshot']
        self.assertIsNone(s['difference']);self.assertEqual(s['arms']['before']['observed'],0)

    def test_unit_attachment_binds_graph_and_rejects_a_different_unit(self):
        run = self.run_fixture();event=next(e for e in run['events'] if e['actor']=='agent')
        unit={'id':'authored-unit','activity':'orient','actor':'agent','source':{'event_id':event['id'],
              'start':0,'end':len(event['text']),'text':event['text']}}
        graph = graph_store.build(run,{'document':{'source_hash':digest(run),'units':[unit],'relations':[]},
                                      'observer':{'id':'authored','label':'Authored unit control'}})
        with self.store.connect() as c: graph_store.save(c,graph)
        ref = {'kind':'unit','graph_id':graph['id'],'unit_id':unit['id']}
        receipt = follow.evidence(self.store,[ref])[0]
        self.assertEqual(receipt['unit']['properties'], unit);self.assertEqual(receipt['graph_digest'],graph['id'][6:])
        with self.assertRaises(InputError): follow.evidence(self.store,[{**ref,'unit_id':'not-in-graph'}])
        with self.assertRaisesRegex(InputError,'not units'): follow.evidence(self.store,[{**ref,'unit_id':'event:'+event['id']}])

    def test_invalid_and_forged_evidence_cannot_be_saved(self):
        p = self.plan(self.base());n=len(saved.saved(self.store))
        bad = [[{'kind':'unknown'}],[{'kind':'investigation','id':p['id'],'snapshot':{'forged':True}}],
               [{'kind':'investigation','id':p['id']}]*2, 'not-a-list', [{'kind':'investigation','id':[]}]]
        for refs in bad:
            with self.subTest(refs=refs), self.assertRaises(InputError): self.finding(p,evidence=refs)
        self.assertEqual(len(saved.saved(self.store)),n)

    def test_malformed_plans_and_cross_investigation_check_ids_are_rejected(self):
        root=self.base();p=self.plan(root)
        for fields in [{'title':'  '},{'hypothesis':[]},{'expected_result':''},{'title':'x'*161},{'snapshot':{}}]:
            with self.subTest(fields=fields), self.assertRaises(InputError): self.plan(root,**fields)
        with self.assertRaises(InputError): self.finding(p,id='unknown')
        with self.assertRaises(InputError): follow.save(self.store,{'parent_id':p['id'],'action':'result','check':{}})

    def test_tampered_parent_and_linked_comparison_are_rejected(self):
        root=self.base();p=self.plan(root)
        with self.store.connect() as c:c.execute('UPDATE failure_investigations SET document=? WHERE id=?',
            (dumps({**{k:v for k,v in root.items() if k!='id'},'hypothesis':'tampered'}),root['id']))
        with self.assertRaisesRegex(InputError,'identity mismatch'):self.plan(root)
        with self.assertRaisesRegex(InputError,'identity mismatch'):self.finding(p,evidence=[{'kind':'investigation','id':root['id']}])


if __name__ == '__main__': unittest.main()
