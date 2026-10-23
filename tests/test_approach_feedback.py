from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from tracker import execution_reports as er,graph_store as gs,adaptation_patterns as ap,analysis_metrics as am,monitoring,monitor_evidence
from tracker.schema import digest,InputError
from tracker.store import Store
from tests.test_work_episodes import example,edge
from tests.test_adaptation_patterns import comparison,saved_graph


def fixture(statuses=('reported','reported')):
    run,g,actions=example(('A','A'));edge(g,actions[1],actions[0],'same_action_target')
    comparison(g,actions[1],actions[0],'reconfigured_procedure')
    pairs=er.bound_responses(run);out=er.build(run,lambda req:({'error':{'value':statuses[next(i for i,(a,r) in enumerate(pairs) if r['id']==req['state']['cutoff_event_id'])]},'warning':{'value':'not_reported'}},'authored-report'))
    g['semantic_context']['execution_reports']=out
    return run,g,actions,out


class ApproachFeedbackTests(unittest.TestCase):
    def test_error_persistence_is_independent_of_procedure_and_not_success(self):
        for after,category,value in [('reported','reported_again',1),('not_reported','no_reported_error',0),('unresolved','followup_unknown',None)]:
            run,g,actions,reports=fixture(('reported',after));before=deepcopy(g)
            projection=ap.project(g);row=projection['records'][0]
            self.assertEqual(row['procedure'],'reconfigured_procedure')
            self.assertEqual(row['error_followup']['category'],category)
            measured=am.measure(projection,am.catalog()['error_report_repeat_fraction'])
            self.assertEqual(measured['value'],value);self.assertEqual(measured['opportunities'],1)
            self.assertEqual(measured['unknown'],int(value is None))
            self.assertIn('event:'+reports['observations'][1]['response_event_id'],measured['cases'][0]['node_ids'])
            self.assertEqual(g,before);self.assertNotIn('success',row)

    def test_missing_reports_and_unknown_membership_stay_visible(self):
        for missing,category in [(0,'unknown'),(1,'followup_unknown')]:
            _,g,_,reports=fixture();reports['observations'].pop(missing)
            out=ap.project(g);self.assertEqual(out['records'][0]['error_followup']['category'],category)
            measured=am.measure(out,am.catalog()['error_report_repeat_fraction'])
            self.assertEqual((measured['denominator'],measured['opportunities'],measured['unknown']),(0,1,1))
        _,g,_,_=fixture(('not_reported','reported'))
        measured=am.measure(ap.project(g),am.catalog()['error_report_repeat_fraction'])
        self.assertEqual(measured['opportunities'],0)
        self.assertEqual(measured['coverage']['error_followup']['no_prior_error'],1)

    def test_missing_legacy_or_different_source_never_becomes_no_error(self):
        for change in ('absent','old','source','duplicate'):
            _,g,_,reports=fixture()
            if change=='absent':g['semantic_context'].pop('execution_reports')
            elif change=='old':reports['schema']='execution-reports/0'
            elif change=='source':reports['source_hash']='wrong'
            else:reports['observations'].append(deepcopy(reports['observations'][0]))
            self.assertEqual(ap.project(g)['records'][0]['error_followup']['category'],'unknown',change)

    def test_partial_absence_is_unknown_but_reported_error_is_retained(self):
        for selected,category in [('not_reported','followup_unknown'),('reported','reported_again')]:
            _,g,_,reports=fixture(('reported',selected));reports['observations'][1]['complete_readable_response']=False
            self.assertEqual(ap.project(g)['records'][0]['error_followup']['category'],category)

    def test_reports_do_not_require_a_known_procedure_comparison(self):
        _,g,_,_=fixture();g['semantic_context']['work_observations']['method_observations']=[]
        out=ap.project(g);self.assertEqual(out['records'][0]['procedure'],'unresolved')
        self.assertEqual(am.measure(out,am.catalog()['error_report_repeat_fraction'])['value'],1)

    def test_feedback_unit_navigation_keeps_all_annotations_without_inflating_counts(self):
        _,g,_,reports=fixture();eid=reports['observations'][1]['response_event_id']
        original=next(n for n in g['nodes'] if n['kind']=='unit' and n['properties']['source']['event_id']==eid)
        alias=deepcopy(original);alias['id']='another-annotation';alias['properties']['id']=alias['id'];g['nodes'].append(alias)
        edge(g,alias,'event:'+eid,'grounded_in')
        out=ap.project(g);observed=out['records'][0]['error_followup']['current']['observations']
        self.assertEqual(len(observed),1);self.assertEqual(set(observed[0]['unit_ids']),{original['id'],alias['id']})
        self.assertEqual(am.measure(out,am.catalog()['error_report_repeat_fraction'])['denominator'],1)

    def test_every_bound_response_is_needed_to_establish_absence(self):
        _,g,actions,reports=fixture(('reported','not_reported'))
        response=deepcopy(next(n for n in g['nodes'] if n['id']=='event:'+reports['observations'][1]['response_event_id']))
        response['id']='event:extra';response['properties']['id']='extra';response['event_index']+=1;response['properties']['index']+=1
        g['nodes'].append(response);edge(g,response,'event:'+actions[1]['source']['event_id'],'response_to')
        self.assertEqual(ap.project(g)['records'][0]['error_followup']['category'],'followup_unknown')
        later=deepcopy(reports['observations'][1]);later['response_event_id']='extra';later['error']='reported';reports['observations'].append(later)
        self.assertEqual(ap.project(g)['records'][0]['error_followup']['category'],'reported_again')

    def test_late_previous_response_and_unbound_current_response_cannot_close_pair(self):
        for change in ('late','unbound'):
            _,g,actions,reports=fixture()
            if change=='late':next(n for n in g['nodes'] if n['id']=='event:'+reports['observations'][0]['response_event_id'])['event_index']=999
            else:g['edges']=[e for e in g['edges'] if not(e['type']=='response_to' and e['target']=='event:'+actions[1]['source']['event_id'])]
            self.assertEqual(ap.project(g)['records'][0]['error_followup']['category'],'unknown' if change=='late' else 'followup_unknown')

    def test_graph_preserves_reports_and_rejects_misbound_source(self):
        run,g,_,reports=fixture();bundle={'observer':{'id':'test','label':'Test'},'document':{'source_hash':digest(run),'execution_reports':reports}}
        result=gs.build(run,bundle);self.assertEqual(result['semantic_context']['execution_reports'],reports)
        old=deepcopy(bundle);old['document'].pop('execution_reports');self.assertNotEqual(gs.build(run,old)['id'],result['id'])
        for change in ('source','duplicate','binding','quote'):
            bad=deepcopy(reports)
            if change=='source':bad['source_hash']='wrong'
            elif change=='duplicate':bad['observations'].append(bad['observations'][0])
            elif change=='binding':bad['observations'][0]['action_event_id']=bad['observations'][1]['action_event_id']
            else:bad['observations'][0]['evidence'][0]['text']='invented'
            with self.assertRaises(InputError):gs.build(run,{**bundle,'document':{**bundle['document'],'execution_reports':bad}})

    def test_monitor_receipts_keep_original_report_evidence_after_restart(self):
        run,g,_,reports=fixture();g=saved_graph(g)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'study.sqlite');store.add([run])
            with store.connect() as c:gs.save(c,g)
            monitor=monitoring.create(store,dict(name='Errors on repeated work',kind='analysis',observer='test',analysis={'measure':'error_report_repeat_fraction'}))
            self.assertEqual(monitoring.sync(store,[monitor['id']])['errors'],0)
            value=monitoring.values(store,monitor['id'],[run['id']])[run['id']]
            self.assertEqual((value['value'],value['denominator']),(1,1));before=monitor_evidence.read(store,value['id'])
            changed=deepcopy(g);changed['semantic_context']['execution_reports']['observations'][1]['error']='not_reported';changed=saved_graph(changed)
            with store.connect() as c:gs.save(c,changed)
            store=Store(store.path);monitoring.sync(store,[monitor['id']])
            self.assertEqual(monitoring.values(store,monitor['id'],[run['id']])[run['id']]['value'],0)
            after=monitor_evidence.read(store,value['id'])
            self.assertFalse(after['freshness']['current_measurement'])
            self.assertEqual({k:v for k,v in after.items() if k!='freshness'},{k:v for k,v in before.items() if k!='freshness'})
