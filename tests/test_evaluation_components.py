from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker.adapters import normalize
from tracker import reward_records
from tracker.evaluation_components import CONTRACT, DEFINITIONS
from tracker.rollout_metrics import source_record, report, save, VERSION, metric_aggregation
from tracker.store import Store

FIXTURES = Path(__file__).parent/'fixtures/tau-bench'


def native(name='airline-3'):
    return normalize(json.loads((FIXTURES/(name+'.json')).read_text(encoding='utf-8')))[0]


def contract():
    return {'schema': CONTRACT, 'definition': 'example/1', 'aggregation': 'product', 'score': 0,
        'components': [{'id':'state','role':'reward','value':0}, {'id':'answer','role':'reward','value':1},
                       {'id':'policy','role':'diagnostic','value':0}],
        'checks': [{'id':'rule','component':'policy','description':'Recorded rule check','met':False}]}


def portable(doc=None):
    return normalize({'input':'task','output':'answer','score':0,'step':0,'reward_evaluation':contract() if doc is None else doc}, 'verl-generation')[0]


class EvaluationComponentTests(unittest.TestCase):
    def test_native_no_tool_error_does_not_establish_task_success(self):
        run=native(); before=deepcopy(run); evidence=reward_records.inspect(run); values=source_record(run)['metrics']
        self.assertEqual(evidence['status'],'complete')
        self.assertEqual(values['environment_tool_error_fraction']['value'],0)
        self.assertEqual(values['environment_tool_error_coverage']['value'],1)
        self.assertEqual(values['reward_component_zero_observed']['value'],1)
        self.assertEqual(values['reward_aggregation_gap']['value'],0)
        self.assertEqual(values['recorded_reward']['value'],0)
        self.assertIsNone(values['recorded_success']['value'])
        self.assertEqual(run,before)
        self.assertTrue(all(c['role']=='diagnostic' for c in evidence['criteria'] if c['component']=='NL_ASSERTION'))
        for m in evidence['metrics'].values():
            for pointer in m['evidence']:
                v=run['raw']
                for segment in pointer.split('/')[1:]:
                    segment=segment.replace('~1','/').replace('~0','~')
                    v=v[int(segment)] if isinstance(v,list) else v[segment]

    def test_user_side_error_flags_are_excluded_and_missing_is_not_false(self):
        run=native('telecom-4'); agent=[e for e in run['events'] if e['kind']=='feedback']
        for e in run['events']:
            if e['kind']=='external_feedback':e['reported_tool_error']=True
        for e in agent:e.pop('reported_tool_error',None)
        m=source_record(run)['metrics']; self.assertIsNone(m['environment_tool_error_fraction']['value'])
        self.assertEqual(m['environment_tool_error_coverage']['value'],0)
        agent[0]['reported_tool_error']=False
        m=source_record(run)['metrics'];self.assertEqual(m['environment_tool_error_fraction']['value'],0)
        self.assertEqual(m['environment_tool_error_coverage']['value'],1/len(agent))
        agent[0]['reported_tool_error']=True
        self.assertEqual(source_record(run)['metrics']['environment_tool_error_fraction']['value'],1)

    def test_reward_membership_is_explicit_not_inferred_from_check_result(self):
        doc=contract(); doc['components'][0]['value']=1;doc['score']=1
        result=reward_records.inspect(portable(doc));m=result['metrics']
        self.assertEqual(m['reward_component_zero_observed']['value'],0)
        self.assertEqual(m['reward_diagnostic_failure_observed']['value'],1)
        self.assertEqual(m['reward_aggregation_gap']['value'],0)
        doc['components'][2]['role']='reward';result=reward_records.inspect(portable(doc))
        self.assertEqual(result['metrics']['reward_component_zero_observed']['value'],1)
        self.assertIsNone(result['metrics']['reward_diagnostic_failure_observed']['value'])
        self.assertEqual(result['metrics']['reward_aggregation_gap']['value'],1)

    def test_incomplete_can_establish_positive_but_never_unobserved_negative(self):
        doc=contract();doc['components'][1]['value']=None;doc['checks'][0]['met']=None
        r=reward_records.inspect(portable(doc));self.assertEqual(r['status'],'partial')
        self.assertEqual(r['metrics']['reward_component_coverage']['value'],.5)
        self.assertEqual(r['metrics']['reward_component_zero_observed']['value'],1)
        self.assertIsNone(r['metrics']['reward_aggregation_gap']['value'])
        self.assertIsNone(r['metrics']['reward_diagnostic_failure_observed']['value'])
        doc['components'][0]['value']=1
        self.assertIsNone(reward_records.inspect(portable(doc))['metrics']['reward_component_zero_observed']['value'])

    def test_invalid_shapes_and_nonfinite_values_fail_closed(self):
        mutations=[lambda d:d['components'][0].update(value=True),lambda d:d['components'][0].update(role=[]),
                   lambda d:d['checks'][0].update(component={}),lambda d:d['checks'][0].update(met='false'),
                   lambda d:d['components'].append(deepcopy(d['components'][0])),lambda d:d.update(score='invalid'),
                   lambda d:d.update(components={}),lambda d:d.update(checks={})]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                run=portable();mutate(run['raw']['reward_evaluation']);r=reward_records.inspect(run)
                self.assertEqual(r['status'],'invalid')
                self.assertTrue(all(r['metrics'][k]['value'] is None for k in DEFINITIONS))
        run=native();run['raw']['simulation']['reward_info']['reward_basis']=[{}]
        self.assertEqual(reward_records.inspect(run)['status'],'invalid')

    def test_arbitrary_transform_not_guessed_and_criteria_can_be_omitted(self):
        doc=contract();doc['aggregation']='clip_then_mean'
        r=reward_records.inspect(portable(doc),include_criteria=False)
        self.assertIsNone(r['metrics']['reward_aggregation_gap']['value'])
        self.assertNotIn('source_fields',r);self.assertEqual(r['criteria'],[])
        self.assertEqual(metric_aggregation('reward_component_coverage'),'opportunity_ratio')
        self.assertEqual(metric_aggregation('environment_tool_error_fraction'),'opportunity_ratio')

    def test_v17_migration_preserves_semantic_identity_and_is_idempotent(self):
        with TemporaryDirectory() as root:
            store=Store(Path(root)/'workspace.sqlite');run=native();store.add([run])
            with store.connect() as c:
                c.execute('DELETE FROM rollout_measurements')
                for observer in ('source','human-reviewed'):
                    old=source_record(run);old.update(schema='rollout-behavior/17',observer=observer)
                    old['annotation_hash']='preserved';old['graph_id']='saved-graph'
                    for key in DEFINITIONS:old['metrics'].pop(key,None)
                    old['metrics'].pop('environment_tool_error_fraction',None)
                    save(c,old)
            rows=report(store)['rows'];self.assertEqual(len(rows),2)
            for row in rows:
                self.assertEqual(row['schema'],VERSION)
                self.assertEqual(row['metrics']['reward_component_zero_observed']['value'],1)
                self.assertEqual(row['metrics']['environment_tool_error_fraction']['value'],0)
            reviewed=next(r for r in rows if r['observer']=='human-reviewed')
            self.assertEqual(reviewed['annotation_hash'],'preserved');self.assertEqual(reviewed['graph_id'],'saved-graph')
            with store.connect() as c:n=c.execute('SELECT count(*) FROM rollout_measurements').fetchone()[0]
            report(store)
            with store.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM rollout_measurements').fetchone()[0],n)


if __name__=='__main__':unittest.main()
