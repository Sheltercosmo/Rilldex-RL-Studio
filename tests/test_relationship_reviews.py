"""Executable review/correction mechanics; authored labels are not accuracy evidence."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import relation_reviews as rr, feedback_opportunities as fo, graph_store, monitoring, analysis_metrics
from tracker import work_subjects, work_return_references
from tracker.schema import digest, InputError
from tracker.store import Store
from test_feedback_opportunities import control, graph
from test_work_return_references import graph as work_graph, query


def rehash(g):
    g=deepcopy(g);g.pop('id',None);g['nodes'].sort(key=lambda n:n['id']);g['edges'].sort(key=lambda e:e['id'])
    return {'id':'graph-'+digest(g),**g}


def document(g, rows):
    return dict(schema=rr.VERSION, base_graph_id=g['id'], reviews=rows,
                revision={'author':'Authored control','note':'Mechanics test, not independent human review.'})


def row(a,b,status='present',kind='assesses'):
    return {'from':a,'to':b,'type':kind,'status':status,
            'provenance':{'author':'Authored control','note':'Explicit test annotation.'}}


class RelationshipReviewTests(unittest.TestCase):
    def fixture(self,choice='none_of_these',texts=None):
        run,ex,result=control(choice=choice,**({'texts':texts} if texts is not None else {}))
        g=graph(run,ex,result)
        units=[n['id'] for n in g['nodes'] if n['kind']=='unit' and n['properties'].get('kind')=='semantic']
        units.sort(key=lambda uid:next(n['event_index'] for n in g['nodes'] if n['id']==uid))
        target=next(n['id'] for n in g['nodes'] if n['kind']=='unit' and n['properties'].get('kind')=='feedback')
        return run,g,units,target

    def test_present_reference_works_without_changing_units_or_activity(self):
        _,g,units,target=self.fixture(texts=('Status is ready.',));before=deepcopy(g)
        revised=rr.fork(g,document(g,[row(units[0],target)]));result=fo.project(revised)
        self.assertEqual(result['metrics']['numerator'],1)
        self.assertEqual(g,before);self.assertEqual(revised['nodes'],g['nodes'])
        self.assertEqual(revised['source_hash'],g['source_hash']);self.assertEqual(result['metrics']['unknown'],0)
        self.assertEqual(len(rr.checked(revised)),1)
        edge=next(e for e in revised['edges'] if e['properties'].get('basis')==rr.VERSION)
        self.assertNotIn('request',edge['properties']);self.assertIn(edge['id'],result['observations'][0]['edge_ids'])

    def test_absent_reviews_override_originals_and_removal_restores_them(self):
        _,g,units,target=self.fixture('f0')
        rows=[row(u,target,'absent') for u in units]
        revised=rr.fork(g,document(g,rows));self.assertEqual(fo.project(revised)['metrics']['value'],0)
        self.assertFalse(any(e['type']=='assesses' for e in revised['edges']))
        restored=rr.fork(revised,document(revised,[]))
        self.assertEqual(restored['observer'],revised['observer'])
        self.assertEqual(fo.project(restored)['metrics']['value'],1)
        self.assertEqual(restored['edges'],g['edges'])
        self.assertEqual(fo.project(g)['metrics']['value'],1)

    def test_partial_and_unresolved_reviews_cannot_become_a_negative_window(self):
        _,g,units,target=self.fixture();g['semantic_context']['feedback_observations']={};g=rehash(g)
        partial=rr.fork(g,document(g,[row(units[0],target,'absent')]))
        self.assertIsNone(fo.project(partial)['metrics']['value'])
        complete=rr.fork(partial,document(partial,[row(u,target,'absent') for u in units]))
        self.assertEqual(fo.project(complete)['metrics']['value'],0)
        uncertain=rr.fork(complete,document(complete,[row(u,target,'unresolved' if i==0 else 'absent') for i,u in enumerate(units)]))
        self.assertIsNone(fo.project(uncertain)['metrics']['value'])
        _,g,units,target=self.fixture(texts=('Proceed.',))
        short=rr.fork(g,document(g,[row(units[0],target,'absent')]))
        self.assertIn('window_not_fully_observed',fo.project(short)['observations'][0]['unknown_reasons'])

    def test_reviewed_revision_updates_macro_measure_and_composes_with_work_review(self):
        _,g,units=work_graph(('A','B','A'))
        d=document(g,[row(units[2]['id'],units[0]['id'],kind='revises')]);r=rr.fork(g,d)
        self.assertEqual(work_return_references.evaluate(r,query())['value'],1)
        wd=work_subjects.template(r)['document'];wd['bindings'][0]['note']='Updated work rationale.'
        w=work_subjects.fork(r,wd)
        self.assertEqual(w['observer'],r['observer']);self.assertEqual(len(rr.checked(w)),1)
        self.assertEqual(work_return_references.evaluate(w,query())['value'],1)
        absent=rr.fork(w,document(w,[row(units[2]['id'],units[0]['id'],'absent','revises')]))
        self.assertEqual(absent['observer'],r['observer'])
        self.assertEqual(work_return_references.evaluate(absent,query())['value'],0)

    def test_work_binding_after_first_relation_review_has_stable_composite_observer(self):
        _,g,units=work_graph(('A','B','A'))
        g['semantic_context'].pop('work_subjects');g['observer']='authored-units'
        ids={n['id'] for n in g['nodes'] if n['kind']=='work_subject'}
        g['nodes']=[n for n in g['nodes'] if n['id'] not in ids]
        g['edges']=[e for e in g['edges'] if e['source'] not in ids and e['target'] not in ids];g=rehash(g)
        reviewed=rr.fork(g,document(g,[row(units[2]['id'],units[0]['id'],kind='uses_evidence')]))
        wd=work_subjects.template(reviewed)['document']
        once=work_subjects.fork(reviewed,wd)
        twice=work_subjects.fork(once,work_subjects.template(once)['document'])
        self.assertEqual(once['observer'],twice['observer']);rr.checked(twice)

    def test_future_cross_context_and_invisible_referents_are_rejected(self):
        _,g,units=work_graph(('A','B','A'))
        with self.assertRaises(InputError):rr.fork(g,document(g,[row(units[0]['id'],units[2]['id'],kind='revises')]))
        for field,value in [('context_id','hidden-lane'),('agent_visibility','not_established'),('copied_context',True)]:
            broken=deepcopy(g);eid=units[0]['source']['event_id']
            next(n['properties'] for n in broken['nodes'] if n['kind']=='event' and n['properties']['id']==eid)[field]=value
            broken=rehash(broken)
            with self.subTest(field=field),self.assertRaises(InputError):
                rr.fork(broken,document(broken,[row(units[2]['id'],units[0]['id'],kind='revises')]))

    def test_native_correspondence_and_complete_response_cannot_be_invented(self):
        _,g,units,target=self.fixture()
        broken=deepcopy(g);broken['edges']=[e for e in broken['edges'] if e['type']!='response_to'];broken=rehash(broken)
        with self.assertRaises(InputError):rr.fork(broken,document(broken,[row(units[0],target)]))
        broken=deepcopy(g);s=next(n['properties']['source'] for n in broken['nodes'] if n['id']==target)
        s['end']-=1;s['text']=s['text'][:-1];broken=rehash(broken)
        with self.assertRaises(InputError):rr.fork(broken,document(broken,[row(units[0],target,'absent')]))

    def test_materialized_edge_tampering_is_detected(self):
        _,g,units,target=self.fixture();revised=rr.fork(g,document(g,[row(units[0],target)]))
        next(e for e in revised['edges'] if e['properties'].get('basis')==rr.VERSION)['properties']['context_evidence']=[]
        with self.assertRaises(InputError):fo.project(rehash(revised))

    def test_invalid_review_document_and_native_edge_types_are_rejected(self):
        _,g,units,target=self.fixture();r=row(units[0],target)
        for rows in [[r,r],[{**r,'status':'likely'}],[{**r,'type':'response_to'}],[{**r,'provenance':{'author':'','note':'No author'}}]]:
            with self.subTest(rows=rows),self.assertRaises(InputError):rr.fork(g,document(g,rows))

    def test_recovery_reuses_reviewed_feedback_without_changing_criterion_outcome(self):
        from test_recovery_windows import captured,check,change
        from tracker import work_state,recovery_windows
        from tracker.semantic_map import evidence
        run=captured([check(),change(text='The check failed; I will update the record.'),check('passed')])
        units=[]
        for e in run['events']:
            if e['actor']!='agent' or not e['text'].strip():continue
            units.append(dict(id='review-unit-'+e['id'],source=evidence(run,e['id']),actor='agent',
                trajectory_id=e['trajectory_id'],kind='action' if e['kind']=='action' else 'semantic',
                status='selected',activity='execute' if e['kind']=='action' else 'orient',content={}))
        g=graph(run,dict(units=units),dict(relations=[],observations=[]))
        state=work_state.derive(run);before=recovery_windows.project(state,g)
        fail=before['records'][0]['failure_result_event_id']
        target=next(n['id'] for n in g['nodes'] if n['kind']=='unit' and n['properties'].get('kind')=='feedback' and n['properties']['source']['event_id']==fail)
        source=next(u['id'] for u in units if u['source']['text'].startswith('The check failed;'))
        reviewed=rr.fork(g,document(g,[row(source,target)]));after=recovery_windows.project(state,reviewed)
        self.assertEqual(before['metrics'],after['metrics']);self.assertEqual(after['metrics']['value'],1)
        self.assertEqual(before['records'][0]['feedback_reference_edge_ids'],[])
        self.assertEqual(len(after['records'][0]['feedback_reference_edge_ids']),1)

    def test_persistent_correction_updates_monitors_but_preserves_receipts(self):
        run,g,units,target=self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'tracker.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,g)
            d=document(g,[row(units[0],target)]);first=rr.receive(store,d)
            self.assertEqual(rr.receive(store,d),first)
            mon=monitoring.create(store,{'name':'Reviewed feedback','kind':'analysis','observer':first['observer'],'analysis':{'measure':'feedback_reference'}})
            monitoring.sync(store)
            values=monitoring.values(store,mon['id'],[run['id']]);old=values[run['id']]
            self.assertEqual(old['value'],1)
            current=graph_store.read(store,first['graph_id'])
            second=rr.receive(store,document(current,[row(u,target,'absent') for u in units]))
            monitoring.sync(store);latest=monitoring.values(store,mon['id'],[run['id']])[run['id']]
            self.assertEqual(latest['value'],0);self.assertNotEqual(latest['id'],old['id'])
            self.assertEqual(analysis_metrics.receipt(store,old,mon)[2]['value'],1)
            self.assertEqual(rehash(graph_store.read(store,g['id'])),rehash(g))
            with self.assertRaises(InputError):rr.receive(store,document(current,[row(units[1],target,'unresolved')]))
            self.assertEqual(first['observer'],second['observer'])


if __name__=='__main__':unittest.main()
