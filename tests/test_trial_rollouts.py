"""Trial receipts → exact rollout sources → saved behavior → map evidence."""
from copy import deepcopy
import unittest

import test_investigation_trials as fixture
from tests.test_work_episodes import edge
from tests.test_adaptation_patterns import comparison as procedure_comparison, saved_graph
from tracker import case_comparisons, failure_investigations, findings_report, graph_store, investigation_followups as follow
from tracker import investigation_trials as trials, monitoring, trial_rollouts, execution_reports
from tracker.adapters import normalize
from rilldex import chat_document
from tracker.schema import InputError, digest


def monitors(store):
    ids=[monitoring.create(store,dict(name=name,group='Behavior',kind='analysis',observer='test',analysis=dict(measure=measure)))['id']
        for name,measure in [('Procedure change','procedure_change_fraction'),('Errors on repeated work','error_report_repeat_fraction')]]
    ids.extend(monitoring.create(store,dict(name=name,group='Training',kind='metric',observer='source',metric=metric))['id']
        for name,metric in [('Reward','recorded_reward'),('Recorded task outcome','recorded_success')])
    return ids


def returned(store,job):
    reference=job['arm']=='Reference'
    reports=['reported']*4 if reference else ['reported','not_reported']
    steps=[dict(thought='Rerun the parser check' if reference or i==0 else 'Use ISO parsing explicitly',
                action='python parser_checks.py --mode='+('legacy' if reference or i==0 else 'iso'),
                observation='ERROR: parsed timestamp lost its timezone' if flag=='reported' else 'PASS: timezone and ISO format preserved')
           for i,flag in enumerate(reports)]
    run=normalize(dict(instance_id='parser',trajectory=steps),'swe-agent',dict(experiment='trial-returned',task_id='parser',
        task_revision='1',environment='terminal',environment_version='1',split='train',reward_definition='tests/v1',
        seed=str(job['seed']),trial_job_id=job['id']))[0]
    run['outcome']=dict(recorded_reward=1,verified_success=not reference)
    units=[]
    for e in run['events']:
        if not e['text']:continue
        units.append(dict(id='u'+e['id'],actor=e['actor'],kind=e['kind'],trajectory_id=e['trajectory_id'],
            activity='execute' if e['kind']=='action' else 'orient',
            source=dict(event_id=e['id'],source_pointer=e['source_pointer'],start=0,end=len(e['text']),text=e['text']),
            content=dict(target=dict(text='Verify ISO parsing'))))
    graph=graph_store.build(run,dict(observer=dict(id='test',label='Authored parser observations'),
        document=dict(schema='semantic-unit-map/1',source_hash=digest(run),units=units,relations=[])))
    actions=[u for u in units if u['kind']=='action']
    for earlier,later in zip(actions,actions[1:]):
        edge(graph,later,earlier,'same_action_target');procedure_comparison(graph,later,earlier,'same_procedure' if reference else 'reconfigured_procedure')
    flags={response['id']:reports[i] for i,(_,response) in enumerate(execution_reports.bound_responses(run))}
    graph['semantic_context']['execution_reports']=execution_reports.build(run,lambda request:(
        dict(error=dict(value=flags[request['state']['cutoff_event_id']]),warning=dict(value='not_reported')),'authored-report'))
    graph=saved_graph(graph);store.add([run])
    with store.connect() as c:graph_store.save(c,graph)
    return dict(job_id=job['id'],status='completed',metrics=dict(success=int(not reference)),applied=fixture.applied(job),
        experiment='trial-returned',rollout_ids=[run['id']]),run,graph


class TrialRolloutTests(unittest.TestCase):
    setUp=fixture.TrialTests.setUp
    study=fixture.TrialTests.study
    execute=fixture.TrialTests.execute

    def prepared(self):
        raw=fixture.design(self.run);raw['seeds']=[0,1]
        doc,check,study=self.study(raw);ids=monitors(self.store)
        return doc,check,study,ids

    def attach(self,doc,check,results):
        return follow.save(self.store,dict(parent_id=doc['id'],action='trial_results',check=dict(id=check['id'],results=results)))

    def complete(self):
        doc,check,study,ids=self.prepared()
        reports=[returned(self.store,j)[0] for j in study.manifest['jobs']]
        monitoring.sync(self.store)
        saved=self.attach(doc,check,reports)
        return saved,check,study,ids

    def compare(self,doc,check,**extra):
        return trial_rollouts.comparison(self.store,dict(investigation_id=doc['id'],check_id=check['id'],arm='Context correction',**extra))

    def test_saved_measures_keep_exact_trial_sources_and_open_both_maps(self):
        doc,check,study,ids=self.complete();captured=doc['follow_up']['checks'][0]['trial_evidence']
        self.assertEqual((captured['available'],captured['declared']),(4,4))
        saved=self.compare(doc,check)
        panels={p['monitor']['name']:p for p in saved['snapshot']['behavior']['panels']}
        self.assertEqual(panels['Procedure change']['delta'],1)
        self.assertEqual(panels['Errors on repeated work']['delta'],-1)
        self.assertEqual(panels['Reward']['delta'],0)
        self.assertEqual(panels['Recorded task outcome']['delta'],1)
        self.assertEqual(panels['Errors on repeated work']['baseline']['denominator'],6)
        self.assertEqual(panels['Errors on repeated work']['current']['denominator'],2)
        self.assertEqual(panels['Errors on repeated work']['same_tasks']['contexts'],1)
        a,b=(saved['snapshot']['population'][side][0] for side in ('baseline','current'))
        pair=case_comparisons.pair(self.store,saved['id'],a,b,observer='test')
        for side in ('reference','selected'):
            graph=graph_store.read(self.store,pair[side]['graph']['id'])
            self.assertEqual(graph['run_id'],pair[side]['run']['id'])
        self.assertIn('Errors on repeated work',findings_report.summary(saved)['measures'])
        changed=self.compare(doc,check,parent_id=saved['id'],monitor_ids=[ids[1]])
        self.assertEqual(len(changed['snapshot']['behavior']['panels']),1)
        self.assertEqual(failure_investigations.read(self.store,saved['id']),saved)

    def test_late_trace_does_not_enter_paired_selection_until_refresh(self):
        doc,check,study,ids=self.prepared();reports=[]
        for j in study.manifest['jobs']:
            r,_,_=returned(self.store,j);reports.append(r)
        late=normalize(chat_document([dict(role='assistant',content='Late captured trace')]),'chat-messages',dict(experiment='trial-returned',task_id='parser'))[0]
        # One completed job declares two traces, but only one has arrived.
        reports[-1]['rollout_ids'].append(late['id'])
        monitoring.sync(self.store);saved=self.attach(doc,check,reports)
        first=self.compare(saved,check)
        self.assertEqual(first['snapshot']['trial_selection']['seeds'],[0])
        self.assertEqual(first['snapshot']['population']['current'],reports[1]['rollout_ids'])
        all_rows=self.compare(saved,check,selection='returned')
        self.assertEqual(len(all_rows['snapshot']['population']['current']),2)
        self.store.add([late])
        still=self.compare(saved,check);self.assertEqual(still['snapshot']['trial_selection']['seeds'],[0])
        refreshed=study.refresh_rollouts(self.store.path,investigation_id=saved['id'])
        later=study.compare_behavior(self.store.path,investigation_id=refreshed['id'],arm='Context correction')
        self.assertEqual(later['snapshot']['trial_selection']['seeds'],[0,1])
        self.assertEqual(len(later['snapshot']['population']['current']),3)
        self.assertEqual(failure_investigations.read(self.store,first['id']),first)
        self.assertEqual(study.refresh_rollouts(self.store.path,investigation_id=refreshed['id']),refreshed)

    def test_no_guess_from_experiment_or_nearby_time(self):
        doc,check,study,ids=self.prepared();reports=[]
        for j in study.manifest['jobs']:
            r,_,_=returned(self.store,j);r.pop('rollout_ids');reports.append(r)
        saved=self.attach(doc,check,reports)
        self.assertEqual(saved['follow_up']['checks'][0]['trial_evidence']['declared'],0)
        with self.assertRaisesRegex(InputError,'No returned rollouts'):self.compare(saved,check)

    def test_wrong_job_experiment_and_seed_stay_visible_without_cross_binding(self):
        doc,check,study,ids=self.prepared();reports=[returned(self.store,j)[0] for j in study.manifest['jobs']]
        reports[0]['rollout_ids']=reports[-1]['rollout_ids'];reports[1]['experiment']='another-experiment'
        saved=self.attach(doc,check,reports);evidence=saved['follow_up']['checks'][0]['trial_evidence']
        self.assertEqual(evidence['jobs'][0]['rollouts'][0]['status'],'mismatch')
        self.assertIn('Different recorded trial job',evidence['jobs'][0]['rollouts'][0]['reasons'])
        self.assertIn('Different recorded seed',evidence['jobs'][0]['rollouts'][0]['reasons'])
        self.assertIn('Different experiment',evidence['jobs'][1]['rollouts'][0]['reasons'])
        compared=self.compare(saved,check)
        self.assertEqual(compared['snapshot']['trial_selection']['seeds'],[1])

    def test_rescoring_shared_source_does_not_appear_as_behavior_change(self):
        raw=fixture.design(self.run,'evaluate');raw['through_event_id']=self.run['events'][-1]['id'];raw['seeds']=[0]
        raw['variants']=[dict(name='Context correction',parameters=dict(grader='independent'))]
        doc,check,study=self.study(raw);reports=[]
        for j in study.manifest['jobs']:
            reports.append(dict(job_id=j['id'],status='completed',metrics=dict(success=int(j['arm']=='Reference')),applied=fixture.applied(j),rollout_ids=[self.run['id']]))
        saved=self.attach(doc,check,reports);compared=self.compare(saved,check)
        self.assertEqual(compared['snapshot']['trial_selection']['shared_run_ids'],[self.run['id']])
        self.assertEqual(compared['snapshot']['population'],dict(baseline=[],current=[]))

    def test_receipt_retries_preserve_old_links_and_select_latest_attempt(self):
        doc,check,study,ids=self.complete();old=deepcopy(doc['follow_up']['checks'][0]['trial_evidence'])
        j=study.manifest['jobs'][0];result=dict(job_id=j['id'],status='error',note='Retry failed before capture')
        newer=self.attach(doc,check,[result]);current=newer['follow_up']['checks'][0]['trial_evidence']
        self.assertFalse(current['jobs'][0]['rollouts'])
        self.assertEqual(failure_investigations.read(self.store,doc['id'])['follow_up']['checks'][0]['trial_evidence'],old)
        self.assertEqual(self.compare(newer,check)['snapshot']['trial_selection']['seeds'],[1])

    def test_unknown_measurements_keep_coverage_and_do_not_become_zero(self):
        doc,check,study,ids=self.prepared();reports=[returned(self.store,j)[0] for j in study.manifest['jobs']]
        saved=self.attach(doc,check,reports);before=self.compare(saved,check)
        panel=before['snapshot']['behavior']['panels'][0]
        self.assertIsNone(panel['delta']);self.assertEqual(panel['baseline']['measured'],0)
        monitoring.sync(self.store);after=self.compare(saved,check)
        self.assertTrue(any(p['delta'] is not None for p in after['snapshot']['behavior']['panels']))
        self.assertEqual(failure_investigations.read(self.store,before['id']),before)

    def test_bad_or_duplicate_rollout_ids_rejected_by_offline_contract(self):
        _,check,study,_=self.prepared();job=study.manifest['jobs'][0]
        for ids in ([1],['a','a'],['a']*65,'not-a-list'):
            with self.subTest(ids=ids),self.assertRaises(InputError):trials.receipt(None,check,dict(job_id=job['id'],status='completed',rollout_ids=ids))


if __name__=='__main__':unittest.main()
