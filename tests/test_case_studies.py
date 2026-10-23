import copy
import tempfile
import unittest
from pathlib import Path

from tracker import case_studies as studies, case_comparisons as cases, failure_investigations, findings_report, investigation_cases
from tracker.schema import InputError, digest
from tracker.store import Store
from test_case_comparisons import CaseComparisonTests


class CaseStudyTests(unittest.TestCase):
    add = CaseComparisonTests.add

    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.store=Store(Path(directory.name)/'study.sqlite');self.serial=0

    def capture(self, **changes):
        return studies.save(self.store,dict(reference={'experiment':'reference'},selected={'experiment':'selected'},**changes))

    def test_same_step_across_runs_matches_tasks_and_keeps_frozen_sources(self):
        a=self.add(10,False,1,experiment='reference');b=self.add(10,True,0,experiment='selected')
        saved=self.capture();pair=cases.pair(self.store,saved['id'],a['id'],b['id'])
        self.assertEqual(pair['status'],'improved')
        self.add(10,False,experiment='selected')
        self.assertEqual(cases.listing(self.store,saved['id'])['source_counts'],{'baseline':1,'current':1})
        self.assertEqual(cases.pair(self.store,saved['id'],a['id'],b['id']),pair)
        self.assertEqual(investigation_cases.population(saved),{a['id']:'reference',b['id']:'focus'})

    def test_no_coordinates_are_needed_for_whole_run_or_checkpoint_selection(self):
        a=self.add(None,True,experiment='reference',checkpoint='first');b=self.add(None,False,experiment='selected',checkpoint='second')
        saved=self.capture()
        self.assertEqual(cases.pair(self.store,saved['id'],a['id'],b['id'])['status'],'regressed')
        same=studies.save(self.store,dict(reference={'experiment':'selected','checkpoint':'second'},
            selected={'experiment':'reference','checkpoint':'first'}))
        self.assertEqual(cases.listing(self.store,same['id'])['counts'],{'improved':1})

    def test_ranges_use_each_sides_exact_clock_and_basis(self):
        a=self.add(5,experiment='reference');self.add(5,experiment='reference',training_clock='learner')
        b=self.add(5,experiment='selected',training_clock='other-policy')
        self.add(5,experiment='selected',training_clock='other-policy',training_step_basis='optimizer')
        saved=studies.save(self.store,dict(reference=dict(experiment='reference',steps=[5,5],clock='policy',basis='generation'),
            selected=dict(experiment='selected',steps=[5,5],clock='other-policy',basis='generation')))
        self.assertEqual(saved['snapshot']['population'],{'baseline':[a['id']],'current':[b['id']]})
        with self.assertRaisesRegex(InputError,'clock and basis'):
            studies.selection(dict(experiment='selected',steps=[5,5]))

    def test_overlap_empty_and_invalid_selectors_are_rejected(self):
        self.add(1,experiment='reference');self.add(2,experiment='selected')
        for reference,selected in [({'experiment':'reference'},{'experiment':'reference'}),
                                   ({'experiment':'absent'},{'experiment':'selected'})]:
            with self.assertRaises(InputError): studies.save(self.store,dict(reference=reference,selected=selected))
        for raw in [None,{},dict(experiment='reference',typo=True),dict(experiment='reference',steps=[True,2],clock='x',basis='y')]:
            with self.assertRaises(InputError): studies.selection(raw)

    def test_catalog_preserves_checkpoint_and_coordinate_choices(self):
        self.add(7,experiment='reference',checkpoint='one');self.add(9,experiment='reference',checkpoint='two')
        self.add(None,experiment='reference',checkpoint=None)
        group=studies.catalog(self.store)['experiments'][0]
        self.assertEqual(group['checkpoints'],['one','two']);self.assertEqual(group['rollouts'],3)
        self.assertEqual(group['coordinates'],[dict(clock='policy',basis='generation',first=7,last=9,rollouts=2)])

    def test_complete_task_context_can_match_across_capture_adapters_and_old_captures_stay_fixed(self):
        a=self.add(1,True,experiment='reference');b=self.add(1,False,experiment='selected')
        # Authored alternate exporter; this checks identity rules, not an adapter.
        b=copy.deepcopy(b);b['adapter']='authored-other-export';b['id']=digest(b)[:24];self.store.add([b])
        saved=self.capture();self.assertEqual(cases.listing(self.store,saved['id'])['counts'],{'choose_rollouts':1})
        self.assertIn('capture_adapter',[r['field'] for r in cases.pair(self.store,saved['id'],a['id'],b['id'])['configuration_changes']])
        old=copy.deepcopy(saved);old.pop('id');old['snapshot']['case_evidence']['version']='case-comparison/1'
        old=failure_investigations.persist(self.store,old)
        with self.assertRaises(InputError): cases.pair(self.store,old['id'],a['id'],b['id'])

    def test_reports_include_cases_and_scopes_without_invented_metric_panels(self):
        self.add(0,True,experiment='reference');self.add(1,False,experiment='selected')
        saved=self.capture();report=findings_report.summary(saved)
        self.assertIn('reference',report['scope']);self.assertIn('selected',report['scope'])
        self.assertIn('regressed',report['measures']);self.assertNotIn('KL',report['measures'])
        self.assertEqual(findings_report.collect(self.store,saved['id'])['bundle']['investigation']['id'],saved['id'])

    def test_public_workspace_api_saves_the_same_inspectable_comparison(self):
        from rilldex import Workspace
        self.add(None,True,experiment='reference');self.add(None,False,experiment='selected')
        workspace=Workspace(self.store.path,experiment='selected')
        saved=workspace.compare_rollouts(reference={'experiment':'reference'},selected={'experiment':'selected'})
        self.assertEqual(failure_investigations.read(self.store,saved['id']),saved)
        self.assertEqual(cases.listing(self.store,saved['id'])['counts'],{'regressed':1})

    def test_external_verdicts_are_selected_frozen_and_do_not_replace_trace_outcomes(self):
        from tracker import evaluation_receipts as evaluations
        from test_evaluation_receipts import report
        a=self.add(None,True,experiment='reference');b=self.add(None,False,experiment='selected')
        left=report(a,verdict='failed');right=report(b,verdict='passed')
        left['performed_at']=right['performed_at']=None
        for raw in (left,right): evaluations.receive(self.store,raw)
        selected={k:left[k] for k in ('label','producer','purpose')}
        def save(): return studies.save(self.store,dict(reference=dict(experiment='reference',evaluation=selected),selected=dict(experiment='selected',evaluation=selected)))
        saved=save();pair=cases.pair(self.store,saved['id'],a['id'],b['id'])
        self.assertEqual(pair['status'],'improved')
        self.assertTrue(pair['reference']['run']['outcome']['verified_success'])
        self.assertFalse(pair['reference']['run']['comparison_outcome']['verified_success'])
        self.assertEqual(pair['reference']['run']['outcome_evaluation']['records'][0]['performed_at'],None)
        self.assertEqual(studies.catalog(self.store)['experiments'][0]['evaluations'],[dict(selected,rollouts=1)])
        self.assertIn('Selected evaluator reports',findings_report.summary(saved)['scope'])
        self.assertEqual(cases.listing(self.store,saved['id'])['counts'],{'improved':1})
        # Another valid report is a separate assessment, not an automatic latest winner.
        evaluations.receive(self.store,dict(right,summary='New result',verdict='failed'))
        self.assertEqual(cases.listing(self.store,save()['id'])['counts'],{'unresolved':1})
        self.assertEqual(cases.pair(self.store,saved['id'],a['id'],b['id']),pair)

    def test_missing_or_incomplete_evaluations_never_fall_back_to_trace_success(self):
        from tracker import evaluation_receipts as evaluations
        from test_evaluation_receipts import report
        a=self.add(None,True,experiment='reference');b=self.add(None,True,experiment='selected')
        raw=report(a);raw.update(execution='error',verdict='unknown',score=None)
        evaluations.receive(self.store,raw);selector={k:raw[k] for k in ('label','producer','purpose')}
        saved=studies.save(self.store,dict(reference=dict(experiment='reference',evaluation=selector),selected=dict(experiment='selected',evaluation=selector)))
        pair=cases.pair(self.store,saved['id'],a['id'],b['id'])
        self.assertEqual(pair['status'],'unresolved')
        self.assertEqual(pair['reference']['run']['outcome_evaluation']['status'],'error')
        self.assertEqual(pair['selected']['run']['outcome_evaluation']['status'],'missing')
        self.assertIsNone(pair['selected']['run']['comparison_outcome']['verified_success'])
        with self.assertRaises(InputError): studies.selection(dict(experiment='x',evaluation={'label':'x'}))


if __name__=='__main__': unittest.main()
