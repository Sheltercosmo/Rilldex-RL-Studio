"""Contract and temporal controls for reviewed work structure, not semantic gold."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tracker import graph_store, work_hierarchy, work_outline as wo
from tracker.adapters import normalize
from tracker.portable import chat_document
from tracker.schema import InputError, digest
from tracker.store import Store


def fixture():
    texts=[('user','Estimate the integral and explain the result.'),
        ('assistant','Try an analytical derivation using symmetry.'),
        ('assistant','Alternatively, estimate the same integral numerically.'),
        ('assistant','Defer the analytical route while checking numerical stability.'),
        ('assistant','The numerical route failed at this precision.'),
        ('assistant','Resume the analytical derivation.'),
        ('assistant','Replace the numerical route with the analytical route.')]
    run=normalize(chat_document([dict(role=r,content=t) for r,t in texts]))[0]
    g=graph_store.build(run)
    refs=[dict(event_id=e['id'],start=0,end=len(e['text']),text=e['text']) for e in run['events']]
    d=dict(schema=wo.VERSION,base_graph_id=g['id'],revision=dict(author='Authored test control',note='Temporal and referential control only.'),
        items=[dict(id='goal',kind='objective',label='Estimate the integral',evidence=refs[0]),
            dict(id='analytic',kind='approach',label='Analytical derivation',evidence=refs[1]),
            dict(id='numeric',kind='approach',label='Numerical estimate',evidence=refs[2])],
        links=[dict(**{'from':'analytic','to':'goal'},type='part_of',evidence=refs[1]),
            dict(**{'from':'numeric','to':'goal'},type='part_of',evidence=refs[2]),
            dict(**{'from':'numeric','to':'analytic'},type='alternative_to',evidence=refs[2])],
        decisions=[dict(item_id='analytic',type='defer',evidence=refs[3]),
            dict(item_id='numeric',type='reported_failed',evidence=refs[4]),
            dict(item_id='analytic',type='resume',evidence=refs[5])])
    return run,g,d,refs


class WorkOutlineTests(unittest.TestCase):
    def test_cutoff_and_scoped_decisions_do_not_propagate_to_parent(self):
        _,g,d,_=fixture();derived=wo.fork(g,d)
        def states(cutoff):return {x['label']:x['state'] for x in wo.project(derived,cutoff)['items']}
        self.assertEqual(len(states(1)),2)
        self.assertEqual(states(3)['Analytical derivation'],'Explicitly deferred')
        self.assertEqual(states(4)['Numerical estimate'],'Reported failed')
        self.assertEqual(states(5)['Analytical derivation'],'Explicitly resumed')
        self.assertEqual(states(6)['Estimate the integral'],'No decision recorded')

    def test_same_record_conflicting_decisions_are_not_last_write_wins(self):
        _,g,d,refs=fixture();d['decisions'].append(dict(item_id='numeric',type='reported_complete',evidence=refs[4]))
        out=wo.project(wo.fork(g,d),4)
        self.assertEqual(next(x['state'] for x in out['items'] if x['label']=='Numerical estimate'),'Conflicting decisions')

    def test_exact_citations_and_no_cross_context_or_future_binding(self):
        _,g,d,refs=fixture()
        for mutation in ('quote','future','actor','context'):
            value=deepcopy(d);graph=deepcopy(g)
            if mutation=='quote':value['items'][0]['evidence']['text']='wrong'
            if mutation=='future':value['links'][1]['evidence']=refs[0]
            if mutation=='actor':value['decisions'][0]['evidence']=refs[0]
            if mutation=='context':
                next(n for n in graph['nodes'] if n['id']=='event:'+refs[2]['event_id'])['properties']['context_id']='other'
            with self.subTest(mutation=mutation),self.assertRaises(InputError):wo.validate(graph,value)

    def test_user_request_cannot_become_agent_approach(self):
        _,g,d,_=fixture();d['items'][0]['kind']='approach'
        with self.assertRaises(InputError):wo.validate(g,d)

    def test_dependency_and_parent_cycles_rejected_without_rejecting_shared_child(self):
        _,g,d,refs=fixture()
        for kind in ('part_of','depends_on'):
            v=deepcopy(d);v['links']=[dict(**{'from':a,'to':b},type=kind,evidence=refs[6]) for a,b in [('analytic','numeric'),('numeric','analytic')]]
            with self.subTest(kind=kind),self.assertRaises(InputError):wo.validate(g,v)
        d['links'].append(dict(**{'from':'numeric','to':'analytic'},type='part_of',evidence=refs[2]))
        self.assertEqual(len(wo.validate(g,d)['links']),4)

    def test_alternative_scale_and_replacement_chronology_checked(self):
        _,g,d,refs=fixture();d['links'][-1]['to']='goal'
        with self.assertRaises(InputError):wo.validate(g,d)
        _,g,d,refs=fixture();d['links'].append(dict(**{'from':'analytic','to':'numeric'},type='replaces',evidence=refs[6]))
        # An old approach can explicitly replace a newer one; declaration age
        # does not determine the direction of a later choice.
        self.assertEqual(len(wo.validate(g,d)['links']),4)

    def test_materialization_never_changes_source_units_or_old_graph(self):
        _,g,d,_=fixture();before=deepcopy(g);derived=wo.fork(g,d)
        self.assertEqual(g,before)
        self.assertEqual([n for n in derived['nodes'] if not n['kind'].startswith('work_outline_')],g['nodes'])
        self.assertTrue(set(e['id'] for e in g['edges'])<=set(e['id'] for e in derived['edges']))
        graph_store.validate(derived)

    def test_projection_attaches_outline_to_existing_plan_workspace(self):
        _,g,d,_=fixture();result=work_hierarchy.build(wo.fork(g,d))
        self.assertTrue(result['available']);self.assertEqual(result['counts']['roots'],1)
        self.assertEqual(result['counts']['visible_actions'],0)
        self.assertEqual(len(result['work_outline']['items']),3)
        self.assertEqual(result['work_outline']['cutoff_event_index'],result['cutoff_event_index'])

    def test_new_revision_replaces_only_overlay_and_preserves_history(self):
        _,g,d,_=fixture();one=wo.fork(g,d);old=deepcopy(one);edited=wo.template(one)['document']
        edited['items'][1]['label']='Analytical route';edited['decisions']=[]
        two=wo.fork(one,edited)
        self.assertEqual(one,old);self.assertNotEqual(one['id'],two['id'])
        self.assertEqual(one['observer'],two['observer'])
        self.assertEqual([n['id'] for n in one['nodes'] if n['kind']=='work_outline_item'],[n['id'] for n in two['nodes'] if n['kind']=='work_outline_item'])
        self.assertEqual(sum(n['kind']=='work_outline_item' for n in two['nodes']),3)
        self.assertFalse(any(n['kind']=='work_outline_decision' for n in two['nodes']))

    def test_graph_edits_cannot_disagree_with_the_review_document(self):
        _,g,d,_=fixture();derived=wo.fork(g,d)
        next(n for n in derived['nodes'] if n['kind']=='work_outline_item')['properties']['label']='Tampered label'
        with self.assertRaises(InputError):wo.project(derived,99)

    def test_real_source_outline_has_no_premature_completion(self):
        g=json.loads(Path('research/work-hierarchy-2026-10-13/software-evidence.json').read_text(encoding='utf8'));g=g.get('graph',g)
        d=json.loads(Path('research/work-outline-2026-10-13/review.json').read_text(encoding='utf8'))
        derived=wo.fork(g,d);early=wo.project(derived,64);late=wo.project(derived,97)
        self.assertFalse(any(n['decisions'] for n in early['items']))
        self.assertEqual(sum(n['state']=='Reported complete' for n in late['items']),1)
        self.assertEqual(next(n['state'] for n in late['items'] if n['work_kind']=='objective'),'No decision recorded')
        by_id={n['id']:n['label'] for n in early['items']}
        requested=[by_id[e['source']] for e in early['links'] if by_id[e['target']]=='Build and evaluate an SVM drug-response predictor']
        self.assertEqual(requested[:2],['Prepare GDSC data and select features','Implement the SVM regressor'])

    def test_storage_retries_and_stale_review_protection(self):
        run,g,d,_=fixture()
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'db.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,g)
            one=wo.receive(store,d);self.assertEqual(one,wo.receive(store,d))
            stale=deepcopy(d);stale['items'][0]['label']='changed stale'
            with self.assertRaises(InputError):wo.receive(store,stale)
            latest=graph_store.read(store,one['graph_id']);current=wo.template(latest)['document'];current['revision']['note']='Current edit'
            self.assertNotEqual(wo.receive(store,current)['graph_id'],one['graph_id'])

    def test_unchanged_review_reuses_the_same_saved_graph(self):
        run,g,d,_=fixture()
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'db.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,g)
            result=wo.receive(store,d);saved=graph_store.read(store,result['graph_id'])
            self.assertEqual(wo.receive(store,wo.template(saved)['document']),result)


if __name__=='__main__':unittest.main()
