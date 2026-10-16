import copy
import tempfile
import unittest
from pathlib import Path

from tracker import work_episodes as we, graph_store as gs, investigation_plans as plans
from tracker.schema import digest, InputError
from tracker.store import Store
from tracker.adapters import normalize


def example(names=('A','B','A')):
    run=normalize({'instance_id':'episodes','trajectory':[
        {'thought':'Consider '+name,'action':name,'observation':'Returned '+name} for name in names]},'swe-agent')[0]
    units=[];actions=[]
    for e in run['events']:
        if not e['text']:continue
        u={'id':'u'+e['id'],'actor':e['actor'],'kind':e['kind'],'activity':'execute' if e['kind']=='action' else 'orient',
           'source':{'event_id':e['id'],'start':0,'end':len(e['text']),'text':e['text']},
           'content':{'target':{'text':e['text']}}}
        units.append(u)
        if e['kind']=='action':actions.append(u)
    g=gs.build(run,{'observer':{'id':'test','label':'Test'},'document':{'schema':'semantic-unit-map/1','source_hash':digest(run),'units':units,'relations':[]}})
    return run,g,actions


def edge(g,a,b,kind,**properties):
    a=a['id'] if isinstance(a,dict) else a;b=b['id'] if isinstance(b,dict) else b
    e={'id':'edge-'+digest([a,b,kind,properties]),'source':a,'target':b,'type':kind,'properties':properties}
    g['edges'].append(e);return e


def unit_at(g,eid):
    return next(n['properties'] for n in g['nodes'] if n['kind']=='unit' and n['properties']['source']['event_id']==eid)


def method(g,a,b,comparison='same_procedure',**kw):
    m={'current_unit_id':a['id'],'previous_unit_id':b['id'],'comparison':comparison,'cutoff':a['source'],**kw}
    g.setdefault('semantic_context',{}).setdefault('work_observations',{}).setdefault('method_observations',[]).append(m)
    return m


class EpisodeTests(unittest.TestCase):
    def test_recurrence_and_intervening_operations(self):
        for names,expected in [(('A','A'),'continued'),(('A','B','A'),'returned')]:
            with self.subTest(names=names):
                _,g,a=example(names);edge(g,a[-1],a[0],'same_action_target')
                r=we.project(g);self.assertEqual(len(r['episodes']),1);self.assertEqual(r['episodes'][0]['category'],expected)
                self.assertEqual(r['counts']['first_or_unresolved'],len(a)-1)

    def test_no_identity_link_does_not_infer_novelty_or_repetition(self):
        _,g,a=example(('A','A'));r=we.project(g)
        self.assertEqual(r['episodes'],[]);self.assertEqual(r['counts']['first_or_unresolved'],2)

    def test_cutoff_is_a_boundary_not_necessarily_a_quoted_span(self):
        _,g,a=example();edge(g,a[2],a[0],'same_action_target',cutoff={k:a[2]['source'][k] for k in ('event_id','end')},evidence=[a[0]['source'],a[2]['source']])
        self.assertEqual(len(we.project(g)['episodes']),1)

    def test_missing_and_partial_actions_do_not_bridge_gap(self):
        for mode in ('missing','partial','overlap','parallel'):
            _,g,a=example();edge(g,a[2],a[0],'same_action_target')
            n=next(n for n in g['nodes'] if n['id']==a[1]['id'])
            if mode=='missing':g['nodes'].remove(n)
            elif mode=='partial':n['properties']['source']['start']=1;n['properties']['source']['text']=''
            elif mode=='overlap':other=copy.deepcopy(n);other['id']='other';g['nodes'].append(other)
            else:next(n for n in g['nodes'] if n['kind']=='event' and n['properties']['id']==a[1]['source']['event_id'])['properties']['batch_size']=2
            self.assertEqual(we.project(g)['episodes'][0]['category'],'interrupted',mode)

    def test_identity_rejects_future_misquoted_cross_stream_and_conflicting_evidence(self):
        for mode in ('future','misquoted','cross_stream','conflict'):
            _,g,a=example(('A','B','A','C'))
            e=edge(g,a[2],a[0],'same_action_target')
            if mode=='future':e['properties']['evidence']=[a[3]['source']]
            elif mode=='misquoted':e['properties']['evidence']=[{**a[0]['source'],'text':'fiction'}]
            elif mode=='conflict':edge(g,a[2],a[1],'same_action_target')
            else:next(n for n in g['nodes'] if n['kind']=='event' and n['properties']['id']==a[0]['source']['event_id'])['properties']['trajectory_id']='other'
            self.assertEqual(we.project(g)['episodes'],[],mode)

    def test_feedback_assessment_is_specific_and_before_recurrence(self):
        run,g,a=example();edge(g,a[2],a[0],'same_action_target')
        ev=run['events'];i=next(i for i,e in enumerate(ev) if e['id']==a[0]['source']['event_id'])
        feedback=unit_at(g,ev[i+1]['id']);assessment=unit_at(g,ev[i+2]['id'])
        edge(g,feedback,a[0],'feedback_for');edge(g,assessment,feedback,'assesses')
        episode=we.project(g)['episodes'][0]
        self.assertEqual(episode['assessment_unit_ids'],[assessment['id']])
        # A note about another result cannot count for this earlier attempt.
        g['edges']=[e for e in g['edges'] if e['type']!='feedback_for']
        edge(g,feedback,a[1],'feedback_for')
        self.assertEqual(we.project(g)['episodes'][0]['assessment_unit_ids'],[])

    def test_adjustment_relation_points_to_previous_and_can_execute_at_retry(self):
        for current in (False,True):
            run,g,a=example();edge(g,a[2],a[0],'same_action_target')
            at=a[2] if current else a[1];i=next(i for i,e in enumerate(run['events']) if e['id']==at['source']['event_id'])
            declaration=unit_at(g,run['events'][i-1]['id'])
            e=edge(g,declaration,a[0],'adjustment_before_retry',retry_unit_id=a[2]['id'],via_action=at['id'],cutoff=a[2]['source'],work_text='Try the correction')
            adjustment=we.project(g)['episodes'][0]['adjustments'][0]
            self.assertEqual(adjustment['timing'],'at_recurrence' if current else 'before_recurrence')
            e['properties']['via_action']='missing'
            self.assertEqual(we.project(g)['episodes'][0]['adjustments'],[])

    def test_method_is_exact_pair_not_transitive(self):
        _,g,a=example(('A','A','A'));edge(g,a[1],a[0],'same_action_target');edge(g,a[2],a[0],'same_action_target')
        method(g,a[1],a[0]);method(g,a[2],a[0],'reconfigured_procedure')
        r=we.project(g);self.assertEqual(r['episodes'][0]['method']['comparison'],'same_procedure');self.assertIsNone(r['episodes'][1]['method'])

    def test_later_dispute_preserves_earlier_episode(self):
        _,g,a=example(('A','A','A'));edge(g,a[1],a[0],'same_action_target');edge(g,a[2],a[1],'same_action_target')
        baseline=we.project(g)['episodes'][0];method(g,a[2],a[1],upstream_identity_disputed=True)
        r=we.project(g);self.assertEqual(len(r['episodes']),1);self.assertEqual(r['episodes'][0],baseline)

    def test_method_cannot_read_future_context(self):
        _,g,a=example(('A','A','B'));edge(g,a[1],a[0],'same_action_target')
        method(g,a[1],a[0],inspector_context={'source_ranges':[a[2]['source']]})
        self.assertIsNone(we.project(g)['episodes'][0]['method'])

    def test_snapshot_persists_independent_observations(self):
        run,_,a=example();m={'current_unit_id':a[-1]['id'],'comparison':'different_work'}
        g=gs.build(run,{'observer':{'id':'test','label':'Test'},'document':{'schema':'semantic-unit-map/1','source_hash':digest(run),'units':a,'relations':[],
            'method_comparison':{'schema':'test/1','observations':[m]},'action_target_review':[{'action_unit_id':a[0]['id'],'status':'no_prior_selected_action'}]}})
        self.assertEqual(g['semantic_context']['work_observations']['method_observations'],[m])

    def test_old_graph_has_unknown_review_coverage(self):
        _,g,a=example();edge(g,a[2],a[0],'same_action_target');g.pop('semantic_context',None)
        r=we.project(g);self.assertEqual(r['counts']['identity_reviewed'],0);self.assertEqual(len(r['episodes']),1)

    def test_comparison_coverage_and_cache_replay(self):
        run,g,a=example();edge(g,a[2],a[0],'same_action_target');g.pop('id');g['edges'].sort(key=lambda e:e['id']);g={'id':'graph-'+digest(g),**g}
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'store.sqlite');store.add([run])
            with store.connect() as c:gs.save(c,g)
            p={'schema':plans.VERSION,'nodes':[
                {'name':'e','op':'work_episodes','inputs':[],'params':{'graph_id':g['id'],'run_id':run['id'],'source_hash':digest(run)}},
                {'name':'c','op':'compare_episodes','inputs':['e'],'params':{'focus':[run['id']],'reference':['unobserved']}}]}
            first=plans.execute(store,p);second=plans.execute(store,p)
            self.assertEqual(first['id'],second['id']);self.assertEqual(second['execution']['cache_hits'],2)
            r=second['outputs']['c'];self.assertEqual(r['groups']['reference']['graphs'],0);self.assertEqual(r['groups']['reference']['rollouts'],1)

    def test_investigation_counts_and_drilldowns_share_the_projection(self):
        from tracker import failure_investigations as f
        run,g,a=example();edge(g,a[2],a[0],'same_action_target');g.pop('id');g['edges'].sort(key=lambda e:e['id']);g={'id':'graph-'+digest(g),**g}
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'store.sqlite');store.add([run])
            with store.connect() as c:gs.save(c,g)
            result=f.snapshot(store,run=run['id'],observer='test',signal='episode:returned',operator='ge',threshold=1)
            m=next(m for m in result['metrics'] if m['id']=='episode:returned')
            episode=result['process']['episodes']['records'][0]['episodes'][0]
            self.assertEqual(m['values'][run['id']]['episode_ids'],[episode['id']]);self.assertEqual(m['focus']['mean'],1)
            self.assertEqual(result['signal_positive'],1)


if __name__=='__main__':unittest.main()
