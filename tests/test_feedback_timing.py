import copy
import tempfile
import unittest
from pathlib import Path

from tracker import feedback_timing as ft, graph_store, analysis_metrics, monitoring, monitor_evidence
from tracker.adapters import normalize
from tracker.schema import digest, InputError
from tracker.semantic_map import evidence
from tracker.store import Store


def fixture():
    # Authored source/binding control; no simulated choice is semantic accuracy evidence.
    run=normalize({'trajectory_format':'devai/1','trajectory':[
        {'step':0,'user_message':'Complete the task.','agent':{'thought':None,'action':'Inspect status'},'environment':'Status: ready.'},
        {'step':1,'user_message':None,'agent':{'thought':'Proceed with the next operation.','action':'Prepare artifact'},'environment':'Prepared.'},
        {'step':2,'user_message':None,'agent':{'thought':'The earlier status result said ready.','action':'Write artifact'},'environment':'Written.'},
        {'step':3,'user_message':None,'agent':{'thought':'The earlier status result was ready.','action':None},'environment':None}]})[0]
    units=[]
    for e in run['events']:
        if e['kind'] not in {'action','reasoning','feedback'}:continue
        ref=evidence(run,e['id'])
        units.append(dict(id='unit-'+e['id'],actor=e['actor'],trajectory_id=e['trajectory_id'],source=ref,
            kind=e['kind'] if e['kind'] in {'action','feedback'} else 'semantic',status='selected',
            activity='construct' if e['kind']=='action' else 'orient',content={'summary':{'text':ref['text']}}))
    g=graph_store.build(run,{'observer':{'id':'timing-control','label':'Timing contract control'},'document':{
        'source_hash':digest(run),'units':units,'relations':[]}})
    for e in list(g['edges']):
        if e['type']=='response_to':add(g,'unit-'+e['source'][6:],'unit-'+e['target'][6:],'feedback_for',basis='source_binding')
    return run,g


def add(g,source,target,kind,**props):
    e=dict(source=source,target=target,type=kind,properties=props);e=dict(id='edge-'+digest(e),**e);g['edges'].append(e);return e


def event(g,kind,index=0):
    return sorted([n['properties'] for n in g['nodes'] if n['kind']=='event' and n['properties']['kind']==kind],key=lambda e:e['index'])[index]


def assess(g,which=1):
    r=event(g,'feedback');a=event(g,'reasoning',which)
    units={n['id']:n['properties'] for n in g['nodes'] if n['kind']=='unit'}
    return add(g,'unit-'+a['id'],'unit-'+r['id'],'assesses',basis='jev_raw_argmax',request='authored-control',
        evidence=[units['unit-'+a['id']]['source']],context_evidence=[units['unit-'+r['id']]['source']])


def first(g):
    return ft.project(g)['observations'][0]


class FeedbackTimingTests(unittest.TestCase):
    def test_counts_intervening_actions_for_earliest_saved_link_not_text_length(self):
        _,g=fixture();assess(g);r=first(g)
        self.assertTrue(r['value']);self.assertEqual(r['intervening_dispatches'],1)
        self.assertEqual(r['intervening_action_event_ids'],[event(g,'action',1)['id']])
        assess(g,0);r=first(g);self.assertFalse(r['value']);self.assertEqual(r['intervening_dispatches'],0)
        self.assertEqual(r['supported_assessment_count'],2)

    def test_missing_links_stay_unknown_even_with_closed_trace_and_later_actions(self):
        _,g=fixture();out=ft.project(g)
        self.assertEqual(out['metrics'],dict(value=None,numerator=0,denominator=0,opportunities=3,unknown=3))
        self.assertIn('no_supported_saved_assessment',out['observations'][0]['unknown_reasons'])

    def test_source_opportunities_survive_omitted_units(self):
        run,_=fixture();out=ft.project(graph_store.build(run))
        self.assertEqual((out['metrics']['opportunities'],out['metrics']['unknown']),(3,3))

    def test_each_response_counts_once_with_multiple_later_assessments(self):
        _,g=fixture();assess(g);assess(g,2);out=ft.project(g)
        self.assertEqual((out['metrics']['numerator'],out['metrics']['denominator'],out['metrics']['unknown']),(1,1,2))
        self.assertEqual(out['observations'][0]['intervening_dispatches'],1)

    def test_fabricated_future_hidden_and_cross_actor_evidence_cannot_produce_timing(self):
        for mode in ('quote','future','hidden','actor','trajectory','unselected','provenance'):
            with self.subTest(mode=mode):
                _,g=fixture();link=assess(g);u=next(n['properties'] for n in g['nodes'] if n['id']==link['source']);e=event(g,'reasoning',1)
                if mode=='quote':link['properties']['evidence']=[{**u['source'],'text':'fiction'}]
                elif mode=='future':link['properties']['evidence'].append(evidence({'events':[event(g,'reasoning',2)]},event(g,'reasoning',2)['id']))
                elif mode=='hidden':e['agent_visibility']='not_established'
                elif mode=='actor':u['actor']=e['actor']='another-agent'
                elif mode=='trajectory':u['trajectory_id']=e['trajectory_id']='other'
                elif mode=='unselected':u['status']='unresolved'
                else:link['properties']['basis']='unknown'
                out=ft.project(g);self.assertIsNone(out['metrics']['value']);self.assertEqual(len(out['coverage']['excluded_links']),1)

    def test_ambiguous_response_origin_and_context_change_stay_unknown(self):
        _,g=fixture();assess(g);r=event(g,'feedback');a=event(g,'action',1)
        # Also point to a second earlier dispatch to create an ambiguous native origin.
        a['index']=event(g,'action')['index'];add(g,'event:'+r['id'],'event:'+a['id'],'response_to')
        self.assertIn('response_origin_ambiguous',first(g)['unknown_reasons'])
        _,g=fixture();assess(g);event(g,'reasoning',1)['context_id']='new-context'
        out=ft.project(g)
        self.assertIsNone(out['metrics']['value'])
        self.assertIn('cross_context_or_trajectory',{row['reason'] for row in out['coverage']['excluded_links']})

    def test_complete_parallel_group_is_counted_without_inventing_sibling_order(self):
        _,g=fixture();assess(g,2)
        for i in (1,2):event(g,'action',i).update(parent_id='batch',batch_size=2)
        row=first(g);self.assertEqual(row['intervening_dispatches'],2)
        self.assertTrue(row['parallel_groups'][0]['complete']);self.assertEqual(row['parallel_groups'][0]['mutual_order'],'unknown')
        event(g,'action',2)['batch_size']=3
        self.assertIsNone(first(g)['value']);self.assertIn('parallel_group_crosses_interval_or_is_incomplete',first(g)['unknown_reasons'])

    def test_batch_crossing_response_or_assessment_boundary_is_not_serial_delay(self):
        _,g=fixture();assess(g)
        for i in (0,1):event(g,'action',i).update(parent_id='batch',batch_size=2)
        self.assertIsNone(first(g)['value'])
        _,g=fixture();assess(g);event(g,'action',1)['parent_id']=event(g,'reasoning',1)['id']
        self.assertIn('dispatch_shares_assessment_message',first(g)['unknown_reasons'])

    def test_copied_action_and_context_mismatch_are_not_valid_delay_counts(self):
        _,g=fixture();assess(g);event(g,'action',1)['copied_context']=True
        self.assertIsNone(first(g)['value'])

    def test_no_tool_response_is_unavailable_not_zero_and_projection_is_immutable(self):
        run,g=fixture();before=copy.deepcopy(g);ft.project(g);self.assertEqual(g,before)
        g['edges']=[e for e in g['edges'] if e['type']!='response_to']
        self.assertEqual(ft.project(g)['metrics']['opportunities'],0);self.assertIsNone(ft.project(g)['metrics']['value'])

    def test_a_citation_to_another_part_of_the_same_message_is_not_a_unit_witness(self):
        _,g=fixture();link=assess(g);u=next(n['properties'] for n in g['nodes'] if n['id']==link['source'])
        # Keep the shortened source unit valid, but its edge still cites the entire message.
        u['source']=copy.deepcopy(u['source']);u['source']['start']=4;u['source']['text']=u['source']['text'][4:]
        self.assertIsNone(first(g)['value'])
        self.assertEqual(ft.project(g)['coverage']['excluded_links'][0]['reason'],'assessment_evidence_unestablished')

    def test_exact_named_review_can_supply_or_withdraw_the_assessment(self):
        from tracker import relation_reviews
        _,g=fixture();link=assess(g)
        g.pop('id');g['edges'].sort(key=lambda e:e['id']);g['counts']['edges']=len(g['edges']);g['id']='graph-'+digest(g)
        body=dict(schema=relation_reviews.VERSION,base_graph_id=g['id'],revision={'author':'Test reviewer','note':'Authored mechanics control'},reviews=[{
            'from':link['source'],'to':link['target'],'type':'assesses','status':'present',
            'provenance':{'author':'Test reviewer','note':'The text names the earlier status result.'}}])
        reviewed=relation_reviews.fork(g,body)
        self.assertTrue(first(reviewed)['value'])
        self.assertEqual(first(reviewed)['supported_assessment_count'],1)
        for status in ('absent','unresolved'):
            body['base_graph_id']=reviewed['id'];body['reviews'][0]['status']=status
            withdrawn=relation_reviews.fork(reviewed,body)
            self.assertIsNone(first(withdrawn)['value'])
            self.assertEqual(first(withdrawn)['supported_assessment_count'],0)

    def test_monitor_receipt_replays_exact_graph_and_reconciles_unknowns(self):
        run,g=fixture();assess(g)
        g.pop('id');g['edges'].sort(key=lambda e:e['id']);g['counts']['edges']=len(g['edges']);g['id']='graph-'+digest(g)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,g)
            monitor=monitoring.create(store,dict(name='Feedback timing',kind='analysis',group='Behavior',observer='timing-control',
                analysis={'measure':'feedback_assessment_after_actions'}))
            monitoring.sync(store);v=monitoring.values(store,monitor['id'],{run['id']})[run['id']]
            self.assertEqual((v['value'],v['numerator'],v['denominator'],v['unknown']),(1,1,1,2))
            receipt=monitor_evidence.read(store,v['id']);cases=receipt['explanation']['analysis_cases']
            self.assertEqual(len(cases),3);self.assertTrue(cases[0]['feedback_timing'])
            self.assertTrue(cases[0]['record']['intervening_action_event_ids'])
            self.assertEqual(monitoring.sync(store)['inserted'],0)
            changed=copy.deepcopy(v);changed['analysis']['measurement']['cases'][0]['taken']=False
            with self.assertRaises(InputError):analysis_metrics.receipt(store,changed,monitor)
            old=v
            assess(g,0);g.pop('id');g['edges'].sort(key=lambda e:e['id']);g['counts']['edges']=len(g['edges']);g['id']='graph-'+digest(g)
            with store.connect() as c:graph_store.save(c,g)
            monitoring.sync(store);current=monitoring.values(store,monitor['id'],{run['id']})[run['id']]
            self.assertEqual(current['value'],0)
            frozen=monitor_evidence.read(store,old['id']);self.assertEqual(frozen['explanation']['value'],1)
            self.assertFalse(frozen['freshness']['current_measurement'])


if __name__=='__main__':unittest.main()
