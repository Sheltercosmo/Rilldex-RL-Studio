"""Projection invariants; authored controls do not establish semantic accuracy."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker.schema import digest, InputError
from tracker.work_hierarchy import build
from tracker import declared_plans
from tracker.adapters import normalize
from test_declared_plans import fixture


def graph():
    nodes=[];edges=[]
    for i,kind in enumerate(['message','action','feedback','message']):
        nodes.append(dict(id='event:e'+str(i),kind='event',activity=None,trajectory_id='main',event_index=i,
            properties=dict(id='e'+str(i),actor='agent' if kind!='feedback' else 'environment',kind=kind,text='source '+str(i))))
    def unit(id,i,kind,activity,**props):
        nodes.append(dict(id=id,kind='unit',activity=activity,trajectory_id='main',event_index=i,
            properties=dict(actor='agent' if kind!='feedback' else 'environment',kind=kind,
                source=dict(event_id='e'+str(i),start=0,end=8,text='source '+str(i)),content={'target':{'text':id}},**props)))
        edges.append(dict(id='ground-'+id,source=id,target='event:e'+str(i),type='grounded_in',properties={}))
    steps=[dict(id=k,text=label,target=label,evidence=[dict(event_id='e0',start=0,end=8,text='source 0')]) for k,label in [('a','Make artifact'),('b','Check artifact')]]
    unit('plan',0,'semantic','plan',plan_structure={'steps':steps,'links':[],'completion_criterion':{'status':'not_expressed'}})
    for step in steps:
        nodes.append(dict(id='plan:'+step['id'],kind='plan_step',activity=None,trajectory_id='main',event_index=0,properties=step))
        edges.append(dict(id='step-'+step['id'],source='plan',target='plan:'+step['id'],type='contains_plan_step',properties={}))
    unit('action',1,'action','construct');unit('feedback',2,'feedback',None);unit('review',3,'semantic','orient')
    edges.extend([dict(id='attempt',source='action',target='plan',type='attempts_plan_step',properties={'plan_step_id':'a','cutoff':{'event_id':'e1'}}),
        dict(id='response',source='feedback',target='action',type='feedback_for',properties={}),
        dict(id='review',source='review',target='feedback',type='assesses',properties={})])
    return finish(dict(schema='authored',run_id='r',source_hash='authored-source',nodes=nodes,edges=edges))


def finish(g):
    g=deepcopy(g);g.pop('id',None);g['nodes'].sort(key=lambda n:n['id']);g['edges'].sort(key=lambda e:e['id'])
    return {'id':'graph-'+digest(g),**g}


def split_action(g):
    """Two nonoverlapping annotations of the same captured dispatch."""
    g = deepcopy(g)
    original = next(n for n in g['nodes'] if n['id'] == 'action')
    second = deepcopy(original)
    original['properties']['source'].update(end=6, text='source')
    second['id'] = 'action-fragment'
    second['properties']['source'].update(start=7, text='1')
    g['nodes'].append(second)
    g['edges'].extend([
        dict(id='ground-fragment', source='action-fragment', target='event:e1', type='grounded_in', properties={}),
        dict(id='attempt-fragment', source='action-fragment', target='plan', type='attempts_plan_step', properties={'plan_step_id': 'a'}),
    ])
    return finish(g)


class WorkHierarchyTests(unittest.TestCase):
    def test_split_annotations_preserve_cards_but_count_one_dispatch(self):
        out = build(split_action(graph()))
        self.assertEqual(out['counts']['linked_actions'], 1)
        self.assertEqual(out['counts']['visible_actions'], 1)
        step = next(n for n in out['nodes'] if n['id'] == 'plan:a')
        self.assertEqual(step['state'], '1 attempt')
        path = next(p for p in out['stage_paths'] if p['stage_id'] == 'plan:a')
        self.assertEqual(path['counts']['actions'], 1)
        self.assertEqual(path['counts']['attempts'], 1)
        self.assertEqual(path['retry_summary']['attempts'], 1)
        self.assertEqual({r['action_id'] for r in path['rows']}, {'action', 'action-fragment'})

    def test_duplicate_role_witnesses_do_not_inflate_stage_state(self):
        g = graph()
        g['edges'].append({**deepcopy(next(e for e in g['edges'] if e['id'] == 'attempt')), 'id': 'attempt-copy'})
        out = build(finish(g))
        self.assertEqual(next(n for n in out['nodes'] if n['id'] == 'plan:a')['state'], '1 attempt')
        self.assertEqual(len(out['stage_paths'][0]['rows'][0]['role_link_ids']), 2)

    def test_same_text_in_distinct_source_calls_remains_two_dispatches(self):
        g = split_action(graph())
        original = deepcopy(next(n for n in g['nodes'] if n['id'] == 'event:e1'))
        original.update(id='event:e4', event_index=4)
        original['properties']['id'] = 'e4'
        g['nodes'].append(original)
        fragment = next(n for n in g['nodes'] if n['id'] == 'action-fragment')
        fragment['event_index'] = 4
        fragment['properties']['source']['event_id'] = 'e4'
        next(e for e in g['edges'] if e['id'] == 'ground-fragment')['target'] = 'event:e4'
        out = build(finish(g))
        self.assertEqual(out['counts']['linked_actions'], 2)
        self.assertEqual(out['stage_paths'][0]['counts']['attempts'], 2)

    def test_structure_preserves_plan_stage_action_feedback_and_assessment(self):
        out=build(graph());nodes={n['id']:n for n in out['nodes']}
        self.assertEqual(out['counts'],dict(plans=1,roots=1,plan_steps=2,linked_actions=1,visible_actions=1,unassigned_actions=0))
        self.assertEqual(nodes['plan:a']['state'],'1 attempt')
        self.assertEqual(nodes['plan:b']['state'],'No linked attempt observed')
        self.assertEqual(nodes['plan']['criterion'],{'status':'not_expressed'})
        self.assertEqual(nodes['feedback']['state'],'Response recorded')
        self.assertIn(('review','feedback','assesses'),[(e['source'],e['target'],e['type']) for e in out['links']])
        self.assertFalse(any('complete' in n['state'].lower() for n in nodes.values()))

    def test_cutoff_hides_future_actions_feedback_and_reviews(self):
        g=graph();a=build(g,'e0');b=build(g,'e1');c=build(g,'e2')
        self.assertEqual(a['counts']['linked_actions'],0)
        self.assertNotIn('feedback',{n['id'] for n in b['nodes']})
        self.assertNotIn('review',{n['id'] for n in c['nodes']})
        self.assertNotEqual(a['id'],b['id'])

    def test_later_evidence_cutoff_cannot_leak_an_early_endpoint_relation(self):
        g=graph();next(e for e in g['edges'] if e['id']=='attempt')['properties']['evidence']=[{'event_id':'e3','text':'later'}];g=finish(g)
        self.assertEqual(build(g,'e2')['counts']['linked_actions'],0)
        self.assertEqual(build(g)['counts']['linked_actions'],1)

    def test_cutoff_must_be_a_real_record_and_graph_hash_must_match(self):
        with self.assertRaises(InputError):build(graph(),'absent')
        g=graph();g['source_hash']='changed'
        with self.assertRaises(InputError):build(g)

    def test_same_action_can_support_two_stages_without_double_counting_execution(self):
        g=graph();g['edges'].append(dict(id='second-role',source='action',target='plan',type='checks_plan_step',properties={'plan_step_id':'b'}))
        out=build(finish(g));self.assertEqual(out['counts']['linked_actions'],1)
        self.assertEqual(len([e for e in out['links'] if e['target']=='action']),2)

    def test_cross_actor_link_is_excluded_and_remains_unassigned(self):
        g=graph();next(n for n in g['nodes'] if n['id']=='action')['properties']['actor']='other';out=build(finish(g))
        self.assertEqual(out['counts']['linked_actions'],0);self.assertEqual(out['unassigned_action_ids'],['action'])
        self.assertIn('incompatible_plan_actor_or_trajectory',{row['type'] for row in out['issues']})

    def test_membership_and_sequence_do_not_become_plan_attempts(self):
        g=graph();next(e for e in g['edges'] if e['id']=='attempt')['type']='in_work_context';out=build(finish(g))
        self.assertEqual(out['counts']['linked_actions'],0);self.assertEqual(out['counts']['unassigned_actions'],1)

    def test_stated_order_is_not_converted_to_dependency(self):
        g=graph();p=next(n for n in g['nodes'] if n['id']=='plan')
        p['properties']['plan_structure']['links']=[{'from':'a','to':'b','kind':'precedes','evidence':[]}]
        out=build(finish(g));self.assertEqual(len([e for e in out['links'] if e['type']=='precedes']),1)
        self.assertFalse(any(e['type']=='requires' for e in out['links']))

    def native(self,lists):
        run=fixture(lists);return declared_plans.evidence_graph(run,declared_plans.project(run))

    def test_native_pending_active_complete_are_reported_history_not_executed_work(self):
        g=self.native([[('Fix','pending')],[('Fix','in_progress')],[('Fix','completed')]])
        result=build(g);item=next(n for n in result['nodes'] if n['kind']=='declared_item')
        self.assertEqual(item['state'],'Reported complete');self.assertEqual([r['status'] for r in item['history']],['pending','active','completed'])
        self.assertEqual(result['counts']['linked_actions'],0)
        earlier=build(g,item['history'][0]['event_id']);item=next(n for n in earlier['nodes'] if n['kind']=='declared_item')
        self.assertEqual(item['state'],'Reported pending');self.assertEqual(len(item['history']),1)

    def test_removed_native_item_is_not_called_ignored_or_abandoned(self):
        result=build(self.native([[('A','completed'),('B','pending')],[('B','pending')]]))
        a=next(n for n in result['nodes'] if n['label']=='A');self.assertEqual(a['state'],'Not in latest declaration')

    def test_invalid_intervening_declaration_prevents_identity_merge(self):
        result=build(self.native([[('A','completed')],{'todos':'bad'},[('A','pending')]]))
        items=[n for n in result['nodes'] if n['kind']=='declared_item'];self.assertEqual(len(items),2)
        self.assertEqual([len(n['history']) for n in items],[1,1])

    def test_public_native_capture_preserves_four_items_over_five_declarations(self):
        raw=json.loads(Path('tests/fixtures/nebius-openhands/jbradberry-universe.json').read_text(encoding='utf-8'))
        run=normalize(raw)[0];g=declared_plans.evidence_graph(run,declared_plans.project(run));out=build(g)
        items=[n for n in out['nodes'] if n['kind']=='declared_item'];self.assertEqual(len(items),4)
        self.assertEqual([len(n['history']) for n in items],[5]*4)
        self.assertEqual({n['state'] for n in items},{'Reported complete'})
        self.assertEqual(out['counts']['linked_actions'],0)

    def test_source_graph_is_immutable_and_repeat_projection_is_stable(self):
        g=graph();before=deepcopy(g);a=build(g);b=build(g);self.assertEqual(a,b);self.assertEqual(g,before)


if __name__=='__main__':unittest.main()
