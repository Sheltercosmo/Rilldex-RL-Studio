"""Installed candidate HTTP workflow with authored semantic decisions."""
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
import unittest

from rilldex import models
from tracker import execution_reports as reports
from tracker.adapters import normalize
from tracker.schema import digest
from tracker.semantic_extraction import Pipeline,read,write
from tracker.semantic_budget import BudgetReached
from tracker.semantic_catalog import load
from tracker.store import Store
from tests import test_installed_models as installed
from tests.test_plan_scope_pages import transport as plan_transport
from tests.test_execution_reports import answer


def fixture():
    rows=[
        ('First write a report in Markdown, then convert it to PDF.','Create report.md','Empty file created'),
        (None,'Write report.md','Text inserted'),
        (None,'Convert report.md to report.pdf','ERROR: converter unavailable'),
        (None,'Read archived build.log','ERROR: converter unavailable'),
        (None,'Convert report.md to report.pdf','PDF written')]
    return normalize({'trajectory_format':'devai/1','trajectory':[
        dict(step=i,user_message=None,agent=dict(thought=t,action=a),environment=r) for i,(t,a,r) in enumerate(rows)]})[0]


def transport(req):
    stage=req['state']['stage']
    if stage=='method_comparison':
        from tests.test_method_comparison import native_response
        # The sole repeated pair in this fixture converts the same report twice.
        return native_response(req)
    if stage=='executor_reports':
        # Authored fixture decisions, not a production error-word detector.
        action=req['state']['action']['text'];response=req['state']['response']['text']
        return answer(req,'reported' if action.startswith('Convert') and response.startswith('ERROR') else 'not_reported')
    if stage=='action_target_scope_pairs':
        current=req['state']['current_action']['content']['summary']['text']
        choices={p['id']:'same_work_target' if p['content']['summary']['text']==current else 'unrelated' for p in req['state']['prior_actions']}
        return dict(model=req['model'],answers={k:dict(type='choice',probabilities={v:float(v==choices[k]) for v in q['criteria']}) for k,q in req['questions'].items()})
    return plan_transport(req)


class PilotExecutionTests(unittest.TestCase):
    setUp=installed.InstalledModelTests.setUp

    def test_error_inspection_resume_maps_metrics_and_old_map_stability(self):
        run=fixture();store=Store(self.root/'reports.sqlite');store.add([run]);directory=self.root/'pilot'
        seen=[]
        def decide(req):seen.append(req['state']['stage']);return transport(req)
        baseline=models.pilot(store,self.root/'baseline',run['id'],candidate_calls=100,decision_calls=100,input_bytes=5000000,transport=decide)
        self.assertEqual(baseline['status'],'complete_local_extraction',baseline)
        before_reports=seen.index('executor_reports');total=len(seen)
        partial=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=before_reports+3,input_bytes=5000000,transport=decide)
        self.assertEqual(partial['status'],'budget_reached')
        self.assertFalse(partial['execution_reports_available'])
        coverage=partial['layers']['execution_reports']['coverage']
        self.assertEqual((coverage['inspected_pairs'],coverage['pending_pairs'],coverage['error_reports']),(3,2,1))
        partial_observer=parse_qs(urlsplit(partial['map_url']).query)['observer'][0]
        partial_map=load(run,partial_observer,store)
        self.assertNotIn('execution_reports',partial_map['document'])
        candidate_calls=len(self.calls);seen.clear()
        complete=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=total,input_bytes=5000000,transport=decide)
        self.assertEqual(seen,['executor_reports','executor_reports','method_comparison','method_comparison'])
        self.assertEqual(len(self.calls),candidate_calls)
        self.assertTrue(complete['execution_reports_available'])
        observer=parse_qs(urlsplit(complete['map_url']).query)['observer'][0]
        self.assertNotEqual(observer,partial_observer)
        selected=load(run,observer,store)
        from tracker.semantic_catalog import profile
        self.assertEqual(profile(observer,store)['map_hash'],digest(selected['document']))
        observations=selected['document']['execution_reports']['observations']
        self.assertEqual([o['error'] for o in observations],['not_reported','not_reported','reported','not_reported','not_reported'])
        returns=selected['document']['execution_returns']
        self.assertEqual(len(returns),1)
        self.assertEqual(returns[0]['type'],'revisits_after_error_report')
        self.assertNotIn('success',returns[0])
        from tracker.rollout_metrics import semantic_record
        metrics=semantic_record(run,selected)['metrics']
        self.assertEqual(metrics['execution_report_coverage']['value'],1)
        self.assertEqual(metrics['execution_error_report_fraction']['value'],0.2)
        self.assertEqual(metrics['target_revisit_after_error_count']['value'],1)
        self.assertEqual(load(run,partial_observer,store),partial_map)
        # A new service sees the same durable coverage after process restart.
        from tracker.model_pilot import ModelPilotService
        service=ModelPilotService(store)
        service.current=read(directory/'pilot-result.json')
        self.assertEqual(service.status()['pilot']['execution_reports']['coverage']['pending_pairs'],0)
        models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=total,input_bytes=5000000,
                     transport=lambda _:self.fail('Completed report selections must be reused'))

    def test_progress_keeps_uninspected_pairs_separate_from_negative_results(self):
        run=fixture();root=self.root/'reports';calls=[]
        def decide(req):
            if len(calls)==3:raise BudgetReached({'limit':'jev_requests'})
            calls.append(digest(req));return transport(req)
        engine=Pipeline(root,None,decide)
        progress=root/'execution-report-progress.json'
        with self.assertRaises(BudgetReached):reports.execute(run,engine,progress=lambda r:write(progress,r))
        state=reports.status(root,run,reports.VERSION)
        self.assertEqual(state['status'],'running')
        self.assertEqual(state['coverage']['pending_pairs'],2)
        self.assertFalse(reports.path_for(root,run).exists())
        engine.transport=transport
        result,_=reports.execute(run,engine,progress=lambda r:write(progress,r))
        self.assertEqual(reports.status(root,run,reports.VERSION)['status'],'complete')
        self.assertEqual(result,reports.build(run,engine.decide))

    def test_existing_pilot_can_add_feedback_without_recalculating_annotations(self):
        from rilldex import candidate
        from tracker.jev import DEFAULT_MODEL
        from tracker.action_targets import PAGED_VERSION as WORK
        from tracker.plan_relations import PAGED_VERSION as PLAN
        run=fixture();store=Store(self.root/'upgrade.sqlite');store.add([run]);directory=self.root/'upgrade'
        config=candidate.settings()
        write(directory/'model.json',dict(adapter=candidate.VERSION,endpoint=config['endpoint'],model=config['model'],
            decision_model=DEFAULT_MODEL,action_target_version=WORK,plan_relation_version=PLAN))
        original=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=100,input_bytes=5000000,transport=transport)
        self.assertEqual(original['layers']['execution_reports']['status'],'not_requested')
        used=original['provider_usage']['providers']['jev']['attempts'];calls=len(self.calls)
        before=read(directory/'extraction/results'/f"{run['id']}.json")
        def only_reports(req):
            self.assertEqual(req['state']['stage'],'executor_reports')
            return transport(req)
        stopped=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=used,input_bytes=5000000,
            transport=only_reports,inspect_feedback=True)
        self.assertEqual(stopped['status'],'budget_reached')
        upgraded=models.pilot(store,directory,run['id'],candidate_calls=100,decision_calls=used+5,input_bytes=5000000,
            transport=only_reports)
        self.assertTrue(upgraded['execution_reports_available'])
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(read(directory/'extraction/results'/f"{run['id']}.json"),before)
        self.assertEqual(len(list((directory/'extraction/configuration-history').glob('*.json'))),1)
        old=parse_qs(urlsplit(original['map_url']).query)['observer'][0]
        self.assertNotIn('execution_reports',load(run,old,store)['document'])


if __name__=='__main__':unittest.main()
