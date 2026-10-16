"""Authored projection controls, not independent semantic accuracy evidence."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from tracker import graph_store as gs, work_subjects as ws, work_navigation as nav, work_visits
from tracker import investigation_plans as plans
from tracker.schema import digest
from tracker.store import Store
from tests.test_work_subjects import fixture, annotation


def rehash(g):
    g.pop('id', None); g['nodes'].sort(key=lambda n:n['id']); g['edges'].sort(key=lambda e:e['id'])
    return {'id':'graph-'+digest(g), **g}


def edge(g, a, b, kind, **props):
    row = dict(source=a, target=b, type=kind, properties=props)
    row['id']='edge-'+digest(row); g['edges'].append(row); return row


def example(metadata=None):
    run, base, units = fixture(('First inspect the roots, then revise the result, then check it.',
        'The response reports two roots.', 'Use both roots instead of the first.',
        'Check the revised result.', 'Here is the result.'), tools=True)
    if metadata:
        run['metadata'].update(metadata); run['id']=digest(run)[:24]
    u = {x['id']:x for x in units}; plan = u['unit-0']; plan['activity']='plan'
    plan['plan_structure']={'schema':'local-plan-content/1','steps':[
        {'id':'inspect','text':'Inspect the roots.','evidence':[deepcopy(plan['source'])]},
        {'id':'revise','text':'Revise the result.','evidence':[deepcopy(plan['source'])]},
        {'id':'check','text':'Check it.','evidence':[deepcopy(plan['source'])]}]}
    request = next(e for e in run['events'] if e['actor']=='user')
    feedback = next(e for e in run['events'] if e['actor'] not in {'user','agent'})
    def unit(event, uid, kind):
        return dict(id=uid,kind=kind,actor=event['actor'],activity=None,
            source=dict(event_id=event['id'],start=0,end=len(event['text']),text=event['text'],source_pointer=event['source_pointer']))
    user = unit(request,'request-unit','semantic'); response = unit(feedback,'response-unit','feedback')
    g = gs.build(run,dict(observer={'id':'authored-context','label':'Authored context control'},
        document={'source_hash':digest(run),'units':[*units,user,response],'relations':[]}))
    g['nodes'].append(dict(id='scope-request',kind='work_scope',event_index=request['index'],
        properties={'scope_kind':'user_contribution','source':deepcopy(user['source']),'text':'Solve the problem.'}))
    g['nodes'].append(dict(id='scope-plan',kind='work_scope',event_index=1,
        properties={'scope_kind':'organized_plan','source':deepcopy(plan['source']),
                    'source_unit_ids':[plan['id']],'text':plan['source']['text']}))
    def relation(a,b,kind,**p):
        return edge(g,a,b,kind,basis='authored projection control',cutoff=deepcopy(u[a]['source']),**p)
    relation('unit-1','scope-request','in_work_scope')
    relation('unit-2','scope-plan','in_work_scope')
    relation('unit-1','unit-0','attempts_plan_step',plan_step_id='inspect')
    relation('unit-4','unit-0','checks_plan_step',plan_step_id='revise')
    relation('unit-2','response-unit','assesses',evidence=[deepcopy(u['unit-2']['source'])])
    edge(g,'response-unit','unit-1','feedback_for',basis='authored native pairing')
    relation('unit-3','unit-2','revises')
    relation('unit-5','request-unit','attempts_requested_work')
    g = rehash(g)
    d=annotation(g,units,('plan','inspect','revise','revise','check','deliver'))
    return run,ws.fork(g,d),units


class WorkRouteContextTests(unittest.TestCase):
    def test_preserves_visits_counts_measurements_and_source_graph(self):
        _,g,_=example(); before=deepcopy(g); base=ws.project(g); metric=work_visits.project(g)
        out=nav.project(g)
        self.assertEqual(g,before); self.assertEqual(out['counts'],base['counts'])
        self.assertEqual([v['id'] for v in out['visits']],[v['id'] for v in base['visits']])
        self.assertEqual(work_visits.project(g),metric)
        self.assertEqual(out['context']['relations'],7); self.assertEqual(out['context']['issues'],[])

    def test_feedback_connection_keeps_response_bridge_and_source_endpoints(self):
        _,g,_=example(); out=nav.project(g)
        r=next(e for e in out['links'] if e.get('relation_type')=='assesses')
        target=next(v for v in out['visits'] if v['id']==r['target'])
        self.assertEqual(target['unit_ids'],['unit-1'])
        self.assertEqual(r['label'],'Assesses feedback from')
        self.assertEqual(r['target_node_id'],'response-unit')
        self.assertEqual(set(r['node_ids']),{'unit-1','unit-2','response-unit'})
        self.assertEqual({e['type'] for e in g['edges'] if e['id'] in r['edge_ids']},{'assesses','feedback_for'})

    def test_shared_visit_does_not_spread_membership_or_create_transition(self):
        _,g,_=example(); out=nav.project(g)
        visit=next(v for v in out['visits'] if 'unit-2' in v['unit_ids'])
        self.assertEqual(visit['unit_ids'],['unit-2','unit-3'])
        self.assertEqual([m['unit_id'] for m in visit['scope_memberships']],['unit-2'])
        revision=next(e for e in out['links'] if e.get('relation_type')=='revises')
        self.assertTrue(revision['within_visit']); self.assertEqual(revision['source'],revision['target'])
        self.assertEqual(out['context']['within_visit'],1)

    def test_plan_stage_has_exact_contribution_and_role_not_completion(self):
        _,g,_=example(); out=nav.project(g)
        check=next(v for v in out['visits'] if 'unit-4' in v['unit_ids'])
        self.assertEqual(check['plan_stages'][0]['role'],'checks_plan_step')
        self.assertEqual(check['plan_stages'][0]['step_id'],'revise')
        self.assertEqual(check['plan_stages'][0]['unit_id'],'unit-4')
        self.assertFalse(any('complete' in e['type'] for e in out['links']))

    def test_request_anchor_reuses_exact_origin_and_is_not_an_activity(self):
        _,g,_=example(); out=nav.project(g)
        self.assertEqual(len(out['context_nodes']),1)
        self.assertEqual(set(out['context_nodes'][0]['source_node_ids']),{'request-unit','scope-request'})
        self.assertEqual(out['counts']['contributions'],6)

    def test_missing_invalid_or_future_plan_stage_is_not_lifted(self):
        for change in ['id','activity','evidence']:
            _,g,_=example()
            p=next(n['properties'] for n in g['nodes'] if n['id']=='unit-0')
            if change=='id':p['plan_structure']['steps'][0]['id']='other'
            elif change=='activity':p['activity']='orient'
            else:p['plan_structure']['steps'][0]['evidence']=[next(n['properties']['source'] for n in g['nodes'] if n['id']=='unit-5')]
            out=nav.project(g)
            self.assertFalse(any(e.get('relation_type')=='attempts_plan_step' for e in out['links']))
            self.assertTrue(out['context']['issues'])

    def test_future_or_misquoted_evidence_cannot_support_feedback_link(self):
        for change in ['future','misquote','context']:
            _,g,_=example(); e=next(e for e in g['edges'] if e['type']=='assesses')
            if change=='future':e['properties']['evidence']=[next(n['properties']['source'] for n in g['nodes'] if n['id']=='unit-5')]
            elif change=='misquote':e['properties']['evidence'][0]['text']='invented quote'
            else:
                rid=next(n['properties']['source']['event_id'] for n in g['nodes'] if n['id']=='response-unit')
                next(n['properties'] for n in g['nodes'] if n['kind']=='event' and n['properties']['id']==rid)['context_id']='not-visible-here'
            out=nav.project(g)
            self.assertFalse(any(e.get('relation_type')=='assesses' for e in out['links']))
            self.assertTrue(out['context']['issues'])

    def test_unlinked_or_ambiguous_feedback_is_not_attached_to_nearest_action(self):
        for ambiguous in [False,True]:
            _,g,_=example(); bridge=next(e for e in g['edges'] if e['type']=='feedback_for')
            if ambiguous:g['edges'].append(deepcopy(bridge))
            else:g['edges'].remove(bridge)
            out=nav.project(g)
            self.assertFalse(any(e.get('relation_type')=='assesses' for e in out['links']))

    def test_native_reference_retains_namespace_without_becoming_product_plan(self):
        _,g,_=example(); edge(g,'unit-4','unit-2','reasoningflow:backref:plan:proceed')
        out=nav.project(g); r=next(e for e in out['links'] if e.get('family')=='native')
        self.assertEqual(r['relation_type'],'reasoningflow:backref:plan:proceed')
        self.assertEqual(r['label'],'Native reference · plan:proceed')
        self.assertIsNone(r['step'])

    def test_native_context_actor_preserves_origin_without_inventing_user_role(self):
        _,g,_=example()
        for n in g['nodes']:
            if n['kind']=='event' and n['properties']['actor']=='user':
                n['properties'].update(actor='context',kind='context')
        out=nav.project(g)
        self.assertEqual(len(out['context_nodes']),1)
        origin=out['context_nodes'][0]
        self.assertEqual(origin['kind'],'source_context'); self.assertEqual(origin['source_actor'],'context')
        self.assertEqual(origin['source_spans'][0]['text'],'Solve the problem.')
        self.assertEqual(out['context']['relations'],7)

    def test_malformed_evidence_is_reported_without_breaking_other_connections(self):
        _,g,_=example(); e=next(e for e in g['edges'] if e['type']=='assesses')
        e['properties']['context_evidence']='not a source span list'
        out=nav.project(g)
        self.assertFalse(any(e.get('relation_type')=='assesses' for e in out['links']))
        self.assertEqual(out['context']['relations'],6)
        self.assertEqual(len(out['context']['issues']),1)

    def test_projection_and_receipt_cache_require_exact_graph(self):
        run,g,_=example()
        with tempfile.TemporaryDirectory() as tmp:
            s=Store(Path(tmp)/'context.sqlite');s.add([run])
            with s.connect() as c:gs.save(c,g)
            plan={'schema':plans.VERSION,'nodes':[{'name':'navigation','op':'work_navigation','inputs':[],
                'params':{'run_id':g['run_id'],'source_hash':g['source_hash'],'graph_id':g['id']}}]}
            first=plans.execute(s,plan);second=plans.execute(s,plan)
            self.assertEqual(first['outputs'],second['outputs'])
            self.assertEqual(second['execution']['cache_hits'],1)
            self.assertEqual(second['execution']['inference_calls'],0)

    def test_stated_work_from_an_orient_unit_reaches_work_map_without_becoming_plan(self):
        _, g, _ = example()
        declaration = next(n for n in g['nodes'] if n['id']=='unit-0')
        declaration['activity']=declaration['properties']['activity']='orient'
        declaration['properties'].pop('plan_structure')
        raw = edge(g,'unit-1','unit-0','attempts_declared_work', declared_work_id='work-one',
            to_item_id='item-one', work_text='Inspect the roots.', declaration_at_dispatch='commits')
        before=deepcopy(g); out=nav.project(g)
        link=next(e for e in out['links'] if e.get('relation_type')=='attempts_declared_work')
        self.assertEqual(link['label'],'Attempts stated work')
        self.assertEqual(link['source_form'],'recorded_dispatch')
        self.assertEqual(link['stated_work']['text'],'Inspect the roots.')
        self.assertEqual(link['stated_work']['declaration_unit_id'],'unit-0')
        self.assertEqual(link['edge_ids'],[raw['id']]); self.assertIsNone(link['step'])
        self.assertEqual(g,before)

    def test_stated_work_roles_and_attribution_survive_without_claiming_fulfillment(self):
        for role in ('attempts','prepares','checks'):
            for declaration in ('proposes','withdraws','reports_finished'):
                _, g, _ = example()
                edge(g,'unit-1','unit-0',role+'_declared_work', declared_work_id='work-one',
                    to_item_id='item-one', work_text='Inspect the roots.', declaration_at_dispatch=declaration)
                out=nav.project(g)
                link=next(e for e in out['links'] if e.get('relation_type')==role+'_declared_work')
                self.assertEqual(link['stated_work']['declaration'],declaration)
                self.assertNotIn('completion',link)

    def test_prose_cannot_become_a_stated_work_dispatch(self):
        _, g, _ = example()
        raw=edge(g,'unit-2','unit-0','attempts_declared_work',declared_work_id='work-one',
            to_item_id='item-one',work_text='Inspect the roots.',declaration_at_dispatch='commits')
        out=nav.project(g)
        self.assertFalse(any(e.get('relation_type')=='attempts_declared_work' for e in out['links']))
        self.assertTrue(any(i['edge_id']==raw['id'] for i in out['context']['issues']))
        self.assertIn(raw,g['edges'])

    def test_missing_stated_work_identity_is_visible_as_unprojected(self):
        for missing in ('declared_work_id','to_item_id','work_text','declaration_at_dispatch'):
            _,g,_=example()
            p=dict(declared_work_id='work-one',to_item_id='item-one',work_text='Inspect the roots.',declaration_at_dispatch='commits')
            p.pop(missing)
            raw=edge(g,'unit-1','unit-0','checks_declared_work',**p)
            out=nav.project(g)
            self.assertTrue(any(i['edge_id']==raw['id'] for i in out['context']['issues']))
            self.assertFalse(any(e.get('relation_type')=='checks_declared_work' for e in out['links']))

    def test_native_execution_is_textual_and_cannot_be_attached_to_tool_dispatch(self):
        _,g,_=example()
        edge(g,'unit-4','unit-2','reasoningflow:backref:reason:execute')
        raw=edge(g,'unit-1','unit-0','reasoningflow:backref:reason:execute')
        out=nav.project(g)
        selected=[e for e in out['links'] if e.get('relation_type')=='reasoningflow:backref:reason:execute']
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]['source_form'],'agent_prose')
        self.assertIn('does not establish a tool dispatch',selected[0]['interpretation_note'])
        self.assertTrue(any(i['edge_id']==raw['id'] for i in out['context']['issues']))

    def test_stated_work_within_one_visit_is_not_a_transition_or_new_return(self):
        run,base,units=fixture(('I will inspect the roots.','Then report.'),tools=True)
        raw=edge(base,units[1]['id'],units[0]['id'],'attempts_declared_work',declared_work_id='work-one',
            to_item_id='item-one',work_text='Inspect the roots.',declaration_at_dispatch='commits')
        base=rehash(base);g=ws.fork(base,annotation(base,units,('A','A','B')))
        old=work_visits.project(g);out=nav.project(g)
        link=next(e for e in out['links'] if e.get('relation_type')=='attempts_declared_work')
        self.assertTrue(link['within_visit']);self.assertEqual(link['source'],link['target'])
        self.assertEqual(work_visits.project(g),old)

    def test_action_only_route_keeps_statement_origin_without_inventing_a_visit(self):
        _,base,units=fixture(('I will inspect the roots.','Then report.'),tools=True)
        before=nav.project(base)
        raw=edge(base,units[1]['id'],units[0]['id'],'attempts_declared_work',declared_work_id='work-one',
            to_item_id='item-one',work_text='Inspect the roots.',declaration_at_dispatch='commits')
        base=rehash(base);out=nav.project(base)
        self.assertEqual(len(out['visits']),len(before['visits']))
        self.assertEqual(out['counts'],before['counts'])
        self.assertEqual(out['episodes'],before['episodes'])
        link=next(e for e in out['links'] if e.get('relation_type')=='attempts_declared_work')
        origin=next(c for c in out['context_nodes'] if c['id']==link['target'])
        self.assertEqual(origin['kind'],'stated_work')
        self.assertEqual(origin['label'],'Inspect the roots.')
        self.assertEqual(origin['source_node_ids'],[units[0]['id']])
        self.assertEqual(origin['source'],units[0]['source'])
        self.assertEqual(link['edge_ids'],[raw['id']])


if __name__=='__main__':unittest.main()
