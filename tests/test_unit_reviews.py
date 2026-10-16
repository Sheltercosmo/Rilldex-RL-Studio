"""Authored correction controls; not independent semantic accuracy evidence."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import unit_reviews as ur, semantic_extraction as sem, graph_store, monitoring, monitor_evidence
from tracker import feedback_opportunities as fo, relation_reviews as rr, work_subjects
from tracker.schema import InputError, digest
from tracker.store import Store
from test_feedback_opportunities import control, graph
from test_relationship_reviews import document as relationship_document, row as relationship_row, rehash
from test_work_return_references import graph as work_graph


def unit_item(run, ref, activity='orient', text='Immediate work described in the source.'):
    fields={key:{'status':'not_expressed'} for key in sem.generation_request(run,ref,activity)['field_contract']}
    for key in ('summary','work_target'):
        if key in fields: fields[key]={'status':'expressed','text':text,'evidence':[deepcopy(ref)]}
    return dict(start=ref['start'],end=ref['end'],activity=activity,fields=fields)


def document(run,g,uid,activity='orient',text='Immediate work described in the source.'):
    unit=next(n['properties'] for n in g['nodes'] if n['id']==uid)
    ref=unit['source'];w=next(w for w in sem.windows(run) if w['event_id']==ref['event_id'] and w['start']<=ref['start']<ref['end']<=w['end'])
    units=[ur.editable(run,n['properties']) for n in ur.in_window(g,w)]
    for i,item in enumerate(units):
        if (item['start'],item['end'])==(ref['start'],ref['end']):units[i]=unit_item(run,ref,activity,text)
    return dict(schema=ur.VERSION,base_graph_id=g['id'],window_id=w['id'],
        revision={'author':'Authored test annotation','note':'Test mechanics, not semantic gold.'},units=units)


class UnitReviewTests(unittest.TestCase):
    def fixture(self,texts=None,choice='f0'):
        run,ex,result=control(choice=choice,**({'texts':texts} if texts else {}));g=graph(run,ex,result)
        units=sorted([n for n in g['nodes'] if n['kind']=='unit' and n['properties'].get('kind')=='semantic'],key=lambda n:n['event_index'])
        return run,g,units

    def store(self,run,g):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        store=Store(Path(tmp.name)/'tracker.sqlite');store.add([run])
        with store.connect() as c:graph_store.save(c,g)
        return store

    def test_local_announcement_is_reviewable_as_one_orient_with_readable_target(self):
        run,g,units=self.fixture(('Since the reproduction code does not use the decorator, we need to add it to the class to replicate the issue.',))
        before=deepcopy(g);d=document(run,g,units[0]['id'],text='Reproduce the issue with the decorator applied to the class.')
        revised=ur.fork(run,g,d);graph_store.validate(revised)
        n=next(n for n in revised['nodes'] if n['id'] in revised['semantic_context']['unit_reviews']['impact']['new_unit_ids'])
        self.assertEqual(n['activity'],'orient');self.assertEqual(n['properties']['content']['work_target']['text'],d['units'][0]['fields']['work_target']['text'])
        self.assertEqual(n['properties']['source'],units[0]['properties']['source']);self.assertNotIn('activity_request',n['properties'])
        self.assertEqual(g,before);self.assertEqual(revised['source_hash'],g['source_hash'])
        self.assertFalse(any(n['kind']=='plan_step' for n in revised['nodes']))

    def test_boundary_split_merge_unicode_and_unchanged_units(self):
        run,g,units=self.fixture(('Inspect 🌍 first. Then report.', 'Other work.'))
        d=document(run,g,units[0]['id']);ref=units[0]['properties']['source'];cut=ref['text'].index('Then')
        refs=sem.partition(run,sem.windows(run)[1],[{'start':0,'end':cut},{'start':cut,'end':ref['end']}])
        d['units']=[unit_item(run,r,text=r['text']) for r in refs]
        revised=ur.fork(run,g,d);ids=revised['semantic_context']['unit_reviews']['impact']['new_unit_ids']
        self.assertEqual(len(ids),2);self.assertIn(units[1],revised['nodes'])
        self.assertEqual([next(n['properties']['source']['text'] for n in revised['nodes'] if n['id']==uid) for uid in ids],[r['text'] for r in refs])
        merge={**d,'base_graph_id':revised['id'],'units':[unit_item(run,ref,text='Merged contribution.')]}
        merged=ur.fork(run,revised,merge);self.assertEqual(merged['observer'],revised['observer'])
        self.assertEqual(len(merged['semantic_context']['unit_reviews']['impact']['new_unit_ids']),1)

    def test_partition_gaps_overlap_empty_and_unknown_activities_rejected(self):
        run,g,units=self.fixture();base=document(run,g,units[0]['id'])
        cases=[]
        for key,val in [('start',1),('end',base['units'][0]['end']-1),('activity','assess')]:
            d=deepcopy(base);d['units'][0][key]=val;cases.append(d)
        d=deepcopy(base);d['units']*=2;cases.append(d)
        d=deepcopy(base);d['units']=[];cases.append(d)
        for d in cases:
            with self.subTest(d=d),self.assertRaises(InputError):ur.fork(run,g,d)

    def test_action_dispatch_cannot_split_and_native_feedback_rebinds(self):
        run,g,_=self.fixture();action=next(n for n in g['nodes'] if n['kind']=='unit' and n['properties'].get('kind')=='action')
        d=document(run,g,action['id'],'inspect');bad=deepcopy(d);bad['units'][0]['end']-=1
        with self.assertRaisesRegex(InputError,'indivisible'):ur.fork(run,g,bad)
        revised=ur.fork(run,g,d);nid=revised['semantic_context']['unit_reviews']['impact']['new_unit_ids'][0]
        self.assertTrue(any(e['type']=='feedback_for' and e['target']==nid and e['properties']['basis']=='native_response_to' for e in revised['edges']))
        self.assertEqual([e for e in g['edges'] if e['type']=='response_to'],[e for e in revised['edges'] if e['type']=='response_to'])

    def test_evidence_rejects_future_private_and_wrong_quote(self):
        run,g,units=self.fixture();base=document(run,g,units[0]['id'])
        for ref in [units[-1]['properties']['source'],{**units[0]['properties']['source'],'text':'not the source'}]:
            d=deepcopy(base);d['units'][0]['fields']['summary']['evidence']=[ref]
            with self.assertRaises(InputError):ur.fork(run,g,d)
        # Same event source binding is intact, but a different prior context is
        # not a permissible referent for newly reviewed meaning.
        prior=next(e for e in run['events'] if e['kind']=='feedback');changed=deepcopy(run)
        next(e for e in changed['events'] if e['id']==prior['id'])['context_id']='private-context'
        altered=deepcopy(g);altered['source_hash']=digest(changed);altered=rehash(altered)
        d=document(changed,altered,units[0]['id']);d['units'][0]['fields']['summary']['evidence']=[sem.evidence(changed,prior['id'])]
        with self.assertRaisesRegex(InputError,'context'):ur.fork(changed,altered,d)

    def test_plan_requires_expressed_structure_and_can_be_corrected_to_orient(self):
        run,g,units=self.fixture(('First inspect the cause. Next build the fix. Finally test the behavior.',))
        d=document(run,g,units[0]['id'],'plan')
        with self.assertRaises(InputError):ur.fork(run,g,d)
        ref=units[0]['properties']['source'];d['units'][0]['plan_structure']={
            'schema':'local-plan-content/1','organization':'staged','steps':[
                {'id':'s1','text':'Inspect the cause.','target':'Cause of the failure','evidence':[ref]},
                {'id':'s2','text':'Build the fix.','target':'Repair the behavior','evidence':[ref]}],
            'links':[{'from':'s1','to':'s2','kind':'precedes','evidence':[ref]}],
            'completion_criterion':{'status':'not_expressed'}}
        plan=ur.fork(run,g,d);self.assertEqual(sum(n['kind']=='plan_step' for n in plan['nodes']),2)
        uid=plan['semantic_context']['unit_reviews']['impact']['new_unit_ids'][0]
        revised=ur.fork(run,plan,document(run,plan,uid,'orient'))
        self.assertFalse(any(n['kind']=='plan_step' for n in revised['nodes']))

    def test_changed_unit_drops_relationship_and_negative_coverage_without_claiming_absence(self):
        run,g,units=self.fixture(choice='none_of_these');self.assertEqual(fo.project(g)['metrics']['value'],0)
        revised=ur.fork(run,g,document(run,g,units[0]['id']))
        self.assertIsNone(fo.project(revised)['metrics']['value']);self.assertEqual(fo.project(revised)['metrics']['unknown'],1)
        self.assertNotIn('feedback_observations',revised['semantic_context'])
        self.assertIn('feedback_observations',revised['semantic_context']['unit_reviews']['impact']['invalidated_layers'])

    def test_named_work_and_relationship_layers_are_pruned_and_stay_composable(self):
        run,g,units=work_graph(('A','B','A'))
        g=rr.fork(g,relationship_document(g,[relationship_row(units[2]['id'],units[0]['id'],kind='revises')]))
        revised=ur.fork(run,g,document(run,g,units[0]['id']))
        impact=revised['semantic_context']['unit_reviews']['impact'];self.assertTrue(impact['removed_work_subject_ids'])
        self.assertEqual(len(impact['removed_relationship_reviews']),1);self.assertEqual(rr.checked(revised),{})
        work_subjects.validate(revised,{**revised['semantic_context']['work_subjects']['document'],'base_graph_id':revised['id']})
        self.assertNotIn(units[0]['id'],[r['unit_id'] for r in revised['semantic_context']['work_subjects']['document']['bindings']])
        uid=impact['new_unit_ids'][0];again=ur.fork(run,revised,document(run,revised,uid,text='More precise reviewed target.'))
        self.assertEqual(again['observer'],revised['observer']);graph_store.validate(again)

    def test_source_only_event_can_gain_units_and_template_fixes_overlap(self):
        run,g,units=self.fixture();source=graph_store.build(run);store=self.store(run,source)
        event_id=units[0]['properties']['source']['event_id'];t=ur.template(store,source['id'],'event:'+event_id)
        self.assertEqual(t['document']['units'][0]['activity'],'unresolved');self.assertTrue(t['issue'])
        d=t['document'];d['revision']={'author':'Control','note':'Initial coherent annotation.'};d['units']=[unit_item(run,units[0]['properties']['source'])]
        got=ur.receive(store,d);self.assertEqual(len(got['impact']['new_unit_ids']),1)
        duplicate=deepcopy(units[0]);duplicate['id']+='-overlap';duplicate['properties']['id']=duplicate['id'];g['nodes'].append(duplicate);g=rehash(g)
        with store.connect() as c:graph_store.save(c,g)
        self.assertIsNotNone(ur.template(store,g['id'],units[0]['id'])['issue'])

    def test_preview_idempotency_stale_edits_and_prior_measurement_preservation(self):
        run,g,units=self.fixture();store=self.store(run,g)
        original=monitoring.create(store,dict(name='Feedback reference',kind='analysis',observer=g['observer'],analysis={'measure':'feedback_reference'}))
        monitoring.sync(store);old=monitoring.values(store,original['id'],[run['id']])[run['id']]
        d=document(run,g,units[0]['id']);preview=ur.preview(store,d)
        with self.assertRaises(KeyError):graph_store.read(store,preview['graph_id'])
        saved=ur.receive(store,d);self.assertEqual(saved,preview);self.assertEqual(saved,ur.receive(store,d))
        monitor=ur.continue_monitor(store,saved['graph_id'],original['id'])['monitor'];monitoring.sync(store)
        new=monitoring.values(store,monitor['id'],[run['id']])[run['id']]
        self.assertEqual(monitor['analysis'],original['analysis'])
        self.assertNotEqual(monitor['id'],original['id']);self.assertEqual(monitor_evidence.read(store,old['id'])['measurement']['value'],1)
        current=graph_store.read(store,saved['graph_id']);nid=saved['impact']['new_unit_ids'][0]
        second=ur.receive(store,document(run,current,nid,text='Changed again.'));self.assertEqual(second['observer'],saved['observer'])
        with self.assertRaisesRegex(InputError,'latest'):ur.receive(store,document(run,current,nid,text='Stale concurrent edit.'))
        self.assertEqual(rehash(graph_store.read(store,g['id'])),rehash(g))
        self.assertEqual(monitor_evidence.read(store,new['id'])['review_context']['graph_id'],saved['graph_id'])

    def test_unchanged_review_and_derived_graph_are_rejected(self):
        run,g,units=self.fixture();store=self.store(run,g);d=ur.template(store,g['id'],units[0]['id'])['document'];d['revision']={'author':'Control','note':'No actual change.'}
        with self.assertRaisesRegex(InputError,'No unit'):ur.fork(run,g,d)
        bad=deepcopy(g);bad['nodes'].append({'id':'derived','kind':'artifact_snapshot','properties':{}});bad=rehash(bad)
        with self.assertRaisesRegex(InputError,'original'):ur.fork(run,bad,{**d,'base_graph_id':bad['id']})

    def test_recovery_receipt_opens_input_and_review_changes_evidence_not_recorded_outcome(self):
        from test_recovery_windows import captured,check,change
        from tracker import work_state,recovery_windows
        run=captured([check(),change(text='The check failed; I will update the record.'),check('passed')])
        units=[]
        for w in sem.windows(run):
            e=sem.checked_span(run,w);ref=sem.evidence(run,e['id'],start=w['start'],end=w['end'])
            units.append(dict(id='u-'+w['id'],source=ref,actor=e['actor'],trajectory_id=e['trajectory_id'],
                kind='action' if w['kind']=='action_dispatch' else 'semantic',activity='construct' if w['kind']=='action_dispatch' else 'orient',status='selected',content={}))
        g=graph(run,dict(units=units),dict(relations=[],observations=[]))
        state=work_state.derive(run);initial=recovery_windows.project(state,g)
        failed=initial['records'][0]['failure_result_event_id']
        target=next(n['id'] for n in g['nodes'] if n['kind']=='unit' and n['properties'].get('kind')=='feedback' and n['properties']['source']['event_id']==failed)
        uid=next(u['id'] for u in units if u['kind']=='semantic' and u['source']['text'].startswith('The check failed;'))
        g=rr.fork(g,relationship_document(g,[relationship_row(uid,target)]));store=self.store(run,g)
        mon=monitoring.create(store,dict(name='Recovery control',kind='analysis',observer=g['observer'],analysis={'measure':'criterion_recovery_window'}))
        monitoring.sync(store);old=monitoring.values(store,mon['id'],[run['id']])[run['id']]
        receipt=monitor_evidence.read(store,old['id'])
        self.assertEqual(receipt['review_context']['graph_id'],g['id']);self.assertNotEqual(receipt['graph']['id'],g['id'])
        saved=ur.receive(store,document(run,g,uid,text='Update the record after the failed check.'))
        revised=graph_store.read(store,saved['graph_id']);after=recovery_windows.project(state,revised)
        self.assertEqual(after['metrics']['value'],1);self.assertEqual(after['records'][0]['feedback_reference_edge_ids'],[])
        newuid=saved['impact']['new_unit_ids'][0]
        restored=rr.receive(store,relationship_document(revised,[relationship_row(newuid,target)]))
        self.assertEqual(restored['observer'],saved['observer'])
        final=graph_store.read(store,restored['graph_id']);result=recovery_windows.project(state,final)
        self.assertEqual(len(result['records'][0]['feedback_reference_edge_ids']),1)
        reviewed_mon=ur.continue_monitor(store,final['id'],mon['id'])['monitor'];monitoring.sync(store)
        value=monitoring.values(store,reviewed_mon['id'],[run['id']])[run['id']]
        self.assertEqual(value['value'],1);self.assertEqual(monitor_evidence.read(store,old['id'])['measurement']['value'],1)


if __name__=='__main__':unittest.main()
