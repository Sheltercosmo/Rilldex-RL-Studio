import copy
import tempfile
import unittest
from pathlib import Path

from tracker import failure_investigations as saved, graph_store, investigation_cases as cases
from tracker import investigation_followups as follow, training_investigations
from tracker.schema import digest, InputError
from tracker.store import Store
import test_work_episodes as episodes
import test_recovery_windows as recovery
import test_training_investigations as training


class CaseTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.store=Store(Path(tmp.name)/'db.sqlite')

    def save_run(self,run,graph=None):
        self.store.add([run])
        if graph:
            graph['nodes'].sort(key=lambda n:n['id']);graph['edges'].sort(key=lambda e:e['id'])
            graph['id']='graph-'+digest({k:v for k,v in graph.items() if k!='id'})
            with self.store.connect() as c:graph_store.save(c,graph)
        snapshot=saved.snapshot(self.store,run=run['id'],observer=graph['observer'] if graph else 'source')
        return saved.save(self.store,{'controls':snapshot['controls'],'snapshot_id':snapshot['snapshot_id'],
            'title':'Case retrieval control','hypothesis':'Inspect recorded behavior','x':'source:actions','y':'source:recorded_reward'})

    def example(self,linked=True,notes=()):
        run,g,a=episodes.example(('A','B','A','A'))
        g.setdefault('semantic_context',{})['review_notes']=list(notes)
        if linked:
            episodes.edge(g,a[2],a[0],'same_action_target');episodes.edge(g,a[3],a[2],'same_action_target')
        return self.save_run(run,g)

    def test_cases_are_not_rollouts_and_filters_keep_the_denominator_visible(self):
        doc=self.example();all_cases=cases.search(self.store,doc['id'])
        self.assertEqual((all_cases['total_cases'],all_cases['matched_cases'],all_cases['matched_rollouts']),(2,2,1))
        self.assertEqual(all_cases['facets'],{'returned':1,'continued':1})
        filtered=cases.search(self.store,doc['id'],status='returned',q=' a ')
        self.assertEqual((filtered['total_cases'],filtered['matched_cases'],filtered['matched_rollouts']),(2,1,1))
        self.assertEqual(filtered['cases'][0]['status'],'returned')
        self.assertNotIn('case',filtered['cases'][0])

    def test_missing_links_are_unestablished_not_negative_behavior(self):
        doc=self.example(linked=False);result=cases.search(self.store,doc['id'])
        self.assertEqual(result['total_cases'],0)
        self.assertEqual(result['coverage']['first_or_unresolved_actions'],4)
        self.assertEqual(result['coverage']['projected_rollouts'],1)
        linked=self.example();r=cases.search(self.store,linked['id'],feedback='unestablished')
        self.assertEqual(r['matched_cases'],2)
        self.assertIn('not evidence of ignored feedback',r['interpretation'])

    def test_empty_reference_population_is_not_a_missing_focus_graph(self):
        doc=self.example();result=cases.search(self.store,doc['id'],cohort='reference')
        self.assertEqual(result['coverage']['scope_rollouts'],0)
        self.assertEqual(result['coverage']['missing_projection_rollouts'],0)
        self.assertEqual(result['cases'],[])

    def test_paging_has_stable_membership_and_invalid_filters_are_rejected(self):
        doc=self.example();a=cases.search(self.store,doc['id'],limit=1);b=cases.search(self.store,doc['id'],limit=1,offset=1)
        self.assertNotEqual(a['cases'][0]['id'],b['cases'][0]['id'])
        self.assertEqual(a['matched_cases'],b['matched_cases'])
        self.assertEqual(cases.search(self.store,doc['id'],offset=99)['cases'],[])
        for options in [{'family':[]},{'cohort':'later'},{'status':'exploration'},{'feedback':'ignored'},
                        {'q':'x'*241},{'limit':True},{'offset':-1},{'limit':101}]:
            with self.subTest(options=options),self.assertRaises(InputError):cases.search(self.store,doc['id'],**options)

    def test_duplicate_or_conflicting_annotation_versions_cannot_inflate_cases(self):
        doc=self.example();value={k:copy.deepcopy(v) for k,v in doc.items() if k!='id'}
        records=value['snapshot']['process']['episodes']['records'];records.append(copy.deepcopy(records[0]))
        duplicate=saved.persist(self.store,value)
        self.assertEqual(cases.search(self.store,duplicate['id'])['total_cases'],2)
        records[-1]['observer']='another-annotation-version'
        ambiguous=saved.persist(self.store,value);r=cases.search(self.store,ambiguous['id'])
        self.assertEqual(r['total_cases'],0);self.assertEqual(r['coverage']['ambiguous_projection_rollouts'],1)
        self.assertEqual(r['coverage']['missing_projection_rollouts'],1)

    def test_frozen_projection_does_not_adopt_new_graph_or_annotation_versions(self):
        doc=self.example();before=cases.search(self.store,doc['id'])
        self.example(linked=False)
        self.assertEqual(cases.search(self.store,doc['id']),before)
        value={k:copy.deepcopy(v) for k,v in doc.items() if k!='id'}
        value['snapshot']['process']['episodes']['schema']='work-episodes/unknown'
        unsupported=saved.persist(self.store,value);r=cases.search(self.store,unsupported['id'])
        self.assertEqual(r['availability'],'not_recorded');self.assertEqual(r['coverage']['missing_projection_rollouts'],1)

    def test_recovery_retrieval_keeps_complete_negatives_and_unknown_windows_separate(self):
        doc=self.save_run(recovery.captured([recovery.check(),recovery.check(),recovery.check(),recovery.check()]))
        result=cases.search(self.store,doc['id'],family='recovery')
        self.assertEqual(result['facets'],{'not_recovered_in_window':1,'unknown':3})
        unknown=cases.search(self.store,doc['id'],family='recovery',status='unknown')
        self.assertEqual((unknown['total_cases'],unknown['matched_cases'],unknown['matched_rollouts']),(4,3,1))
        ref={'kind':'behavior_case','investigation_id':doc['id'],'family':'recovery','case_id':unknown['cases'][0]['id']}
        evidence=cases.resolve(self.store,ref)
        self.assertIsNone(evidence['record']['case']['value'])
        self.assertIn('window_not_fully_observed',evidence['record']['case']['unknown_reasons'])

    def test_attach_case_and_export_retain_its_original_projection_and_source_comparison(self):
        doc=self.example();row=cases.search(self.store,doc['id'])['cases'][0]
        ref={'kind':'behavior_case','investigation_id':doc['id'],'family':'recurrence','case_id':row['id']}
        p=follow.save(self.store,{'parent_id':doc['id'],'action':'plan','check':{'title':'Inspect a return',
            'hypothesis':'The agent returns to the same work','procedure':'Inspect the linked cases','expected_result':'Earlier and later attempts have a recorded work identity'}})
        r=follow.save(self.store,{'parent_id':p['id'],'action':'result','check':{'id':p['follow_up']['checks'][0]['id'],
            'assessment':'supports','conclusion':'There is a recorded recurrence witness','evidence':[ref]}})
        attached=r['follow_up']['checks'][0]['results'][0]['evidence'][0]
        self.assertEqual(attached['record']['case']['id'],row['id'])
        self.assertEqual(attached['record']['projection_schema'],'work-episodes/3')
        self.assertEqual(follow.bundle(self.store,r['id'])['linked_comparisons'],[doc])
        with self.assertRaises(InputError):cases.resolve(self.store,{**ref,'case_id':'outside'})
        with self.assertRaises(InputError):cases.resolve(self.store,{**ref,'case':{'forged':True}})

    def test_training_comparisons_do_not_invent_behavior_cases_from_sample_counts(self):
        fixture=training.TrainingInvestigationTests();fixture.store=self.store
        request,_=fixture.setup_comparison();doc=training_investigations.save(self.store,request)
        result=cases.search(self.store,doc['id'])
        self.assertEqual(result['availability'],'not_recorded')
        self.assertEqual(result['coverage']['scope_rollouts'],1) # Two selected samples; one has no bound source.
        self.assertEqual(result['coverage']['projected_rollouts'],0)
        self.assertEqual(result['cases'],[])

    def test_retained_graph_review_notes_follow_the_case_without_newer_annotation_leakage(self):
        notes=[{'text':'Known feedback-reference error; inspect the source.', 'unit_ids':['reviewed-unit']}]
        doc=self.example(notes=notes);row=cases.search(self.store,doc['id'])['cases'][0]
        ref={'kind':'behavior_case','investigation_id':doc['id'],'family':'recurrence','case_id':row['id']}
        self.example(notes=[{'text':'A newer annotation has different review notes.'}])
        receipt=cases.resolve(self.store,ref)
        self.assertEqual(receipt['annotation_review']['notes'],notes)
        self.assertEqual(receipt['annotation_review']['graph_id'],row['graph_id'])
        self.assertIn('Actions',row['location'])


if __name__=='__main__':unittest.main()
