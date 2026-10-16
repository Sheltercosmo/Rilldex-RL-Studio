from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tracker import graph_store, work_scope_frames as frames
from tracker.adapters import normalize
from tracker.portable import chat_document
from tracker.schema import InputError, digest
from tracker.store import Store


def rekey(graph):
    graph.pop('id', None)
    graph['nodes'].sort(key=lambda n:n['id']); graph['edges'].sort(key=lambda e:e['id'])
    graph['id'] = 'graph-' + digest(graph)
    return graph


def fixture(count=1):
    run = normalize(chat_document([dict(role='assistant', content=f'I will create sample {i} to test implementation {i}.') for i in range(count)]))[0]
    graph = graph_store.build(run)
    for index, event in enumerate(run['events']):
        ref = dict(event_id=event['id'], start=0, end=len(event['text']), text=event['text'])
        graph['nodes'].append(dict(id=f'unit-{index}', kind='unit', activity='orient',
            event_index=index, trajectory_id=event['trajectory_id'], properties=dict(
                kind='semantic', actor='agent', status='selected', content_request='authored-control',
                source=ref, content=dict(
                    needed_work=dict(text=f'Create sample {index}.', evidence=[deepcopy(ref)]),
                    purpose=dict(text=f'Test implementation {index}.', evidence=[deepcopy(ref)])))))
    graph['counts']['nodes'] = len(graph['nodes'])
    return run, rekey(graph)


def response(req, choices=None):
    choices = choices or {}
    return dict(model=req['model'], answers={key:dict(type='choice', confidence=0,
        choice='unresolved', probabilities={c:float(c==choices.get(key,'distinct_purpose')) for c in spec['criteria']})
        for key,spec in req['questions'].items()})


class WorkScopeFrameTests(unittest.TestCase):
    def test_purpose_roles_separate_attachment_from_work_identity(self):
        _,g=fixture(5);p=frames.packet(g,version=frames.PURPOSE_VERSION);req=frames.request(p)
        choices=dict(zip(req['questions'],frames.PURPOSE_CHOICES))
        out=frames.fork(g,p,response(req,choices))
        report=frames.audit(out)
        self.assertEqual([r['choice'] for r in report['rows']],list(frames.PURPOSE_CHOICES))
        self.assertEqual(len([e for e in out['edges'] if e['type']=='has_expressed_purpose']),1)
        self.assertFalse(any(e['type'] in {'serves_expressed_purpose','part_of','same_work_target'} for e in out['edges']))
        self.assertEqual(out['coverage']['work_scope_frames']['component_purpose'],1)
        self.assertEqual([n for n in g['nodes'] if n['kind']=='unit'],[n for n in out['nodes'] if n['kind']=='unit'])

    def test_purpose_request_deduplicates_exact_source_without_activity_or_outline(self):
        _,g=fixture();p=frames.packet(g,version=frames.PURPOSE_VERSION);req=frames.request(p)
        self.assertEqual(len(req['state']['sources']),1)
        self.assertNotIn('activity',req['state']['pairs'][0])
        self.assertNotIn('work_outline',json.dumps(req))
        self.assertEqual(req['state']['pairs'][0]['work'],p['pairs'][0]['work']['text'])
        self.assertEqual(next(iter(req['state']['sources'].values()))['text'],p['pairs'][0]['source']['text'])

    def test_purpose_protocol_changes_cannot_reuse_old_response(self):
        _,g=fixture();old=frames.packet(g);new=frames.packet(g,version=frames.PURPOSE_VERSION)
        with self.assertRaises(InputError):frames.selected(g,new,response(frames.request(old)))
        with self.assertRaises(InputError):frames.packet(g,version='other')

    def test_purpose_role_tampering_rejected(self):
        _,g=fixture();p=frames.packet(g,version=frames.PURPOSE_VERSION);req=frames.request(p)
        out=frames.fork(g,p,response(req,{k:'whole_work_purpose' for k in req['questions']}))
        edge=next(e for e in out['edges'] if e['type']=='has_expressed_purpose');edge['type']='part_of';rekey(out)
        with self.assertRaises(InputError):frames.audit(out)

    def test_reuses_exact_fields_and_lists_missing_without_generation(self):
        _,g=fixture(2); unit=next(n for n in g['nodes'] if n['id']=='unit-1')
        unit['properties']['content']['purpose']={'text':'Not expressed','evidence':[]};rekey(g)
        p=frames.packet(g)
        self.assertEqual(len(p['pairs']),1);self.assertEqual(len(p['omitted']),1)
        self.assertEqual(p['pairs'][0]['work']['text'],'Create sample 0.')
        self.assertNotIn('instructions',p['pairs'][0])
        self.assertEqual(p['pairs'][0]['field_origin'],dict(work='needed_work',purpose='purpose'))

    def test_explicit_subset_does_not_silently_include_other_units(self):
        _,g=fixture(2);p=frames.packet(g,['unit-0'])
        self.assertEqual([r['unit_id'] for r in p['pairs']],['unit-0'])
        with self.assertRaises(InputError):frames.packet(g,['unit-0','unit-0'])
        with self.assertRaises(InputError):frames.packet(g,['missing'])

    def test_future_and_cross_context_citations_fail(self):
        for mode in ('future','context'):
            _,g=fixture(2);a=next(n for n in g['nodes'] if n['id']=='unit-0');b=next(n for n in g['nodes'] if n['id']=='unit-1')
            if mode=='future':a['properties']['content']['purpose']['evidence']=[b['properties']['source']]
            else:
                b['properties']['content']['purpose']['evidence']=[a['properties']['source']]
                next(n for n in g['nodes'] if n['kind']=='event' and n['event_index']==0)['properties']['context_id']='other-context'
            rekey(g)
            with self.subTest(mode=mode),self.assertRaises(InputError):frames.packet(g)

    def test_only_raw_distinct_choice_creates_purpose_edges(self):
        _,g=fixture(4);p=frames.packet(g);req=frames.request(p)
        choices={key:choice for key,choice in zip(req['questions'],frames.CHOICES)}
        selected=frames.fork(g,p,response(req,choices))
        self.assertEqual(len([e for e in selected['edges'] if e['type']=='serves_expressed_purpose']),1)
        self.assertEqual(len(frames.audit(selected)['rows']),4)
        self.assertEqual([r['choice'] for r in frames.audit(selected)['rows']],list(frames.CHOICES))

    def test_retains_units_and_never_merges_cross_unit_identity(self):
        _,g=fixture(2);original=deepcopy(g);p=frames.packet(g);out=frames.fork(g,p,response(frames.request(p)))
        self.assertEqual(original,g)
        self.assertEqual({n['id']:n for n in g['nodes'] if n['kind']=='unit'},
                         {n['id']:n for n in out['nodes'] if n['kind']=='unit'})
        self.assertEqual(out['source_hash'],g['source_hash'])
        self.assertEqual(len({n['properties']['frame'] for n in out['nodes'] if n['kind']=='work_scope_term'}),2)

    def test_changed_fields_and_response_model_are_rejected(self):
        _,g=fixture();p=frames.packet(g);req=frames.request(p)
        changed=deepcopy(p);changed['pairs'][0]['work']['text']='Invented work'
        with self.assertRaises(InputError):frames.selected(g,changed,response(req))
        wrong=response(req);wrong['model']='other-model'
        with self.assertRaises(InputError):frames.selected(g,p,wrong)

    def test_tampered_terms_and_missing_edges_fail_replay(self):
        _,g=fixture();p=frames.packet(g);out=frames.fork(g,p,response(frames.request(p)))
        for mode in ('term','edge'):
            value=deepcopy(out)
            if mode=='term':next(n for n in value['nodes'] if n['kind']=='work_scope_term')['properties']['text']='Invented'
            else:value['edges']=[e for e in value['edges'] if e['type']!='serves_expressed_purpose']
            rekey(value)
            with self.subTest(mode=mode),self.assertRaises(InputError):frames.audit(value)

    def test_capacity_never_truncates_uninspected_units(self):
        _,g=fixture(33)
        with self.assertRaisesRegex(InputError,'32 pairs'):frames.packet(g)
        self.assertEqual(len(frames.packet(g,['unit-0'])['pairs']),1)

    def test_saving_is_replayable_and_refuses_changed_source(self):
        run,g=fixture();p=frames.packet(g);reply=response(frames.request(p))
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'db.sqlite');store.add([run])
            with store.connect() as connection:graph_store.save(connection,g)
            result=frames.save_selected(store,p,reply)
            self.assertEqual(result,frames.save_selected(store,p,reply))
            self.assertEqual(len(frames.audit(graph_store.read(store,result['graph_id']))['rows']),1)
            changed=deepcopy(run);changed['metadata']['edited']='Source changed'
            with store.connect() as connection:
                connection.execute('UPDATE runs SET document=? WHERE id=?',(json.dumps(changed),run['id']))
            with self.assertRaisesRegex(InputError,'rollout changed'):
                frames.save_selected(store,p,reply)


if __name__=='__main__':unittest.main()
