from copy import deepcopy
from unittest import TestCase
from tracker import request_dispatch as rd, work_correspondence as wc
from tracker.schema import digest, InputError
from test_work_correspondence import fixture as source_fixture


def fixture():
    run,local,work,users,actions=source_fixture()
    work.update(schema='requested-work-records/1',run_id=run['id'])
    previous=[]
    for step in work['steps']:
        step.update(previous_state_hash=digest(previous),status='selected_update',
                    changes=[c for c in work['changes'] if c['source_unit_id']==step['unit_id']])
        previous=step['state_after']
    def decide(req):
        records=req['state']['candidate_work_records']
        return {r['version_id']:{'value':'none' if r['status']=='withdrawn' else 'attempts'} for r in records},digest(req)
    correspondence=wc.build(run,local,work,decide)
    doc={'source_hash':digest(run),'units':local['units'],'requested_work':work,
         'work_correspondence':correspondence,'relations':deepcopy(correspondence['relations'])}
    return run,doc,actions


class RequestDispatchTests(TestCase):
    def test_latest_prior_state_keeps_conditions_and_withdrawal_without_later_approval(self):
        run,doc,actions=fixture();original=deepcopy(doc);value=rd.build(run,doc);row=value['actions'][1]
        self.assertEqual(row['action_unit_id'],actions[1]['id'])
        self.assertIn('Use the draft address.',str(row))
        self.assertNotIn('FUTURE_APPROVAL',str(row));self.assertNotIn('FUTURE_RESPONSE',str(row))
        self.assertEqual(next(r['status'] for r in row['records'] if r['id']=='b'),'withdrawn')
        self.assertEqual(len(row['links']),1);self.assertEqual(row['links'][0]['requested_work_id'],'a')
        self.assertEqual(doc,original)

    def test_snapshot_and_exported_edge_corruption_are_rejected(self):
        for mode in ['later_state','negative_edge','role','version','source_state','request','coverage','hash']:
            run,doc,actions=fixture();cor=doc['work_correspondence'];row=cor['actions'][1]
            if mode=='later_state':row['state_at_dispatch']=cor['actions'][-1]['state_at_dispatch']
            elif mode=='negative_edge':row['choices'][next(iter(row['choices']))]='none'
            elif mode=='role':row['choices'][next(iter(row['choices']))]='invented'
            elif mode=='version':cor['relations'][0]['requested_work_version_id']='later'
            elif mode=='source_state':row['source_state_unit_id']='wrong'
            elif mode=='request':row['requests']=[]
            elif mode=='coverage':cor['actions'].pop()
            else:cor['requested_work_hash']='changed'
            with self.assertRaises(InputError,msg=mode):rd.build(run,doc)

    def test_missing_correspondence_keeps_context_but_no_inferred_work_role(self):
        run,doc,_=fixture();doc.pop('work_correspondence');doc['relations']=[]
        value=rd.build(run,doc)
        self.assertTrue(all(r['correspondence_status']=='uninspected' for r in value['actions']))
        self.assertTrue(all(not r['choices'] and not r['links'] for r in value['actions']))
        self.assertEqual(value['counts']['positive_work_links'],0)

    def test_negative_judgments_also_need_decision_references(self):
        run,doc,actions=fixture();cor=doc['work_correspondence'];row=cor['actions'][1]
        row['choices']={k:'none' for k in row['choices']};row['requests']=[]
        cor['relations']=[r for r in cor['relations'] if r['from']!=actions[1]['id']]
        doc['relations']=deepcopy(cor['relations'])
        with self.assertRaisesRegex(InputError,'decision references'):rd.build(run,doc)

    def test_unrepresented_source_action_remains_a_coverage_gap(self):
        run,doc,actions=fixture();doc.pop('work_correspondence');doc['relations']=[]
        doc['units']=[u for u in doc['units'] if u['id']!=actions[1]['id']]
        result=rd.build(run,doc)
        self.assertEqual(result['unrepresented_action_event_ids'],[actions[1]['source']['event_id']])
        self.assertEqual(result['counts']['recorded_actions'],3)
        self.assertEqual(result['counts']['represented_actions'],2)

    def test_source_actor_and_trajectory_are_checked(self):
        for field,value in [('trajectory_id','other'),('actor','user')]:
            run,doc,actions=fixture();actions[0][field]=value
            with self.assertRaises(InputError):rd.build(run,doc)

    def test_state_and_version_edges_are_persistent_objects_not_added_activities(self):
        from tracker import graph_store as gs
        run,doc,actions=fixture();graph=gs.build(run,{'observer':{'id':'test','label':'Test'},'document':doc})
        versions={r['version_id']:r for c in doc['requested_work']['changes'] for r in (c['before'],c['after']) if r}
        for key,record in versions.items():graph['nodes'].append({'id':'requested-version:'+key,'kind':'requested_work_version','properties':record})
        rd.materialize(run,doc,graph)
        unit_ids={n['id'] for n in graph['nodes'] if n['kind']=='unit'}
        self.assertEqual(unit_ids,{u['id'] for u in doc['units']})
        edge=next(e for e in graph['edges'] if e['type']=='request_context_at_dispatch' and e['source']==actions[1]['id'])
        state=next(n for n in graph['nodes'] if n['id']==edge['target'])
        self.assertEqual(state['properties']['state_hash'],doc['work_correspondence']['actions'][1]['requested_state_hash'])
        bound={e['target'] for e in graph['edges'] if e['source']==state['id'] and e['type']=='contains_requested_version'}
        self.assertEqual(bound,{'requested-version:'+r['version_id'] for r in doc['requested_work']['steps'][1]['state_after']})
        self.assertEqual(len([e for e in graph['edges'] if e['type']=='corresponds_to_requested_version']),4)
