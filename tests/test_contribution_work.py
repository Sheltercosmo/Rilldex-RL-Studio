from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import contribution_work as cw, graph_store, work_subjects as ws, unit_reviews
from tracker.schema import InputError, digest
from tracker.semantic_extraction import read
from tracker.store import Store
from test_work_subjects import fixture
from test_work_target_refinement import choose
from test_unit_reviews import document as review_document


def source(texts=('Compute the roots.', 'Check the sign.', 'Report the roots.'), tools=False):
    run, _, units = fixture(texts, one_event=not tools, tools=tools)
    for i, unit in enumerate(units):
        unit['content'] = {k: {'status': 'expressed', 'text': unit['source']['text'], 'evidence': [deepcopy(unit['source'])]}
                           for k in ('summary', 'work_target')}
    graph = graph_store.build(run, {'observer': {'id': 'test-base', 'label': 'Authored units'},
        'document': {'source_hash': digest(run), 'schema': 'semantic-unit-map/1', 'units': units, 'relations': []}})
    return run, graph, units


class ContributionWorkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.out = self.root/'observer'

    def selected(self):
        run, graph, units = source(); cw.initialize(self.out, run, graph)
        calls = []
        def transport(req):
            calls.append(req)
            return choose('w0' if len(calls) == 3 else 'new_target')(req)
        result = cw.execute(self.out, transport, max_calls=3)
        return run, graph, units, result, read(self.out/'graph.json'), calls

    def test_prose_membership_reaches_existing_return_projection_and_raw_argmax_replay(self):
        run, base, units, result, graph, calls = self.selected()
        self.assertEqual(result['status'], 'complete'); self.assertEqual(result['counts']['returned'], 1)
        self.assertEqual(result['counts']['contributions'], 3)
        self.assertEqual(result['budget_used']['candidate_requests'], 0)
        self.assertTrue(result['validation']['argmax_replayed'])
        self.assertEqual([n['properties'] for n in base['nodes'] if n['kind']=='unit'],
                         [n['properties'] for n in graph['nodes'] if n['kind']=='unit'])
        self.assertNotIn('Report the roots.', str(calls[0]))
        self.assertEqual(cw.execute(self.out, lambda _: self.fail('cache only'))['budget_used']['jev_requests'], 0)

    def test_budget_checkpoint_and_source_freezing(self):
        run, graph, units = source(); cw.initialize(self.out, run, graph)
        result = cw.execute(self.out, choose('new_target'), max_calls=1)
        self.assertEqual(result['status'], 'budget_reached')
        self.assertEqual(len(read(self.out/'checkpoint.json')['bindings']), 1)
        self.assertFalse((self.out/'graph.json').exists())
        again = cw.execute(self.out, choose('new_target'), max_calls=2)
        self.assertEqual(again['status'], 'complete')
        changed = deepcopy(graph); changed['observer_label'] = 'Changed'; changed.pop('id'); changed['id']='graph-'+digest(changed)
        with self.assertRaises(InputError): cw.initialize(self.out, run, changed)

    def test_tampered_decision_binding_label_and_input_fail(self):
        _, base, _, _, graph, _ = self.selected()
        original = read(self.out/'document.json')
        for field in ('binding', 'label', 'input', 'probability'):
            doc = deepcopy(original)
            if field == 'binding': doc['bindings'][2]['subject_id'] = doc['subjects'][1]['id']
            if field == 'label': doc['subjects'][0]['label'] = 'Different work'
            if field == 'input': doc['selection']['units'][0]['source']['text'] = 'Forged'
            if field == 'probability':
                ps = doc['selection']['decisions'][2]['response']['answers']['choice']['probabilities']
                ps['w0'], ps['new_target'] = ps['new_target'], ps['w0']
            with self.subTest(field=field), self.assertRaises(InputError): ws.fork(base, doc)

    def test_manual_binding_review_remains_possible_and_unit_edit_invalidates_model_layer(self):
        run, _, units, _, graph, _ = self.selected()
        doc = ws.template(graph)['document']
        doc['bindings'][2].update(status='unresolved',subject_id=None,note='Named reviewer cannot establish identity.',
            provenance={'kind':'review','author':'researcher','protocol':'work-subject-review/1'})
        reviewed = ws.fork(graph, doc)
        self.assertEqual(ws.project(reviewed)['counts']['returned'], 0)
        change = review_document(run, graph, units[0]['id'], text='Corrected immediate target.')
        fixed = unit_reviews.fork(run, graph, change)
        self.assertIn('automatic_work_membership',fixed['semantic_context']['unit_reviews']['impact']['invalidated_layers'])
        self.assertEqual(ws.project(fixed)['counts'].get('bound',0),0)

    def test_missing_targets_and_capacity_remain_explicit_gaps(self):
        run, _, units = source(); units[1]['content'].pop('work_target')
        def choice(req): return 'new_target', digest(req)
        result = cw.build(run, units, choice)
        self.assertEqual(result['bindings'][1]['status'],'unresolved')
        self.assertIsNone(result['observations'][1]['request'])
        from unittest.mock import patch
        with patch.object(cw,'LIMIT',1): result = cw.build(run, source()[2], choice)
        self.assertEqual(result['bindings'][-1]['status'],'unresolved')
        self.assertIn('capacity',result['bindings'][-1]['note'])

    def test_no_cross_lane_or_same_batch_predecessors(self):
        run, _, units = source(tools=True)
        action = next(u for u in units if u['kind']=='action')
        current = deepcopy(action); current['id']='later'
        events = {e['id']:e for e in run['events']}
        later = deepcopy(events[action['source']['event_id']]); later['id']='later-event';later['index']+=1
        later['parent_id']=events[action['source']['event_id']]['parent_id']
        run['events'].append(later);current['source']['event_id']=later['id']
        self.assertFalse(cw.ordered_before(run,action,current))
        later['parent_id']='different'; later['trajectory_id']='other'
        self.assertFalse(cw.ordered_before(run,action,current))

    def test_registration_uses_existing_graph_store(self):
        run, _, _, _, graph, _ = self.selected()
        store=Store(self.root/'store.sqlite');store.add([run])
        first=cw.register(store,self.out);second=cw.register(store,self.out)
        self.assertEqual(first,second);self.assertEqual(graph_store.read(store,first['graph_id']),graph)

    def test_actual_map_content_shape_produces_selected_work_and_legacy_gaps_replay(self):
        run,graph,units=source()
        for node in graph['nodes']:
            if node['kind']!='unit':continue
            fields=node['properties']['content'];fields['target']=fields.pop('work_target')
            for field in fields.values():field.pop('status',None)
        graph.pop('id');graph['id']='graph-'+digest(graph)
        cw.initialize(self.out,run,graph)
        result=cw.execute(self.out,choose('new_target'),max_calls=3)
        self.assertEqual(result['counts']['bound'],3)
        self.assertEqual(result['validation']['requests'],3)
        # Older input contracts remain replayable instead of changing past gaps.
        legacy=cw.build(run,cw.inputs(graph),lambda _:self.fail('legacy shape has no typed work_target'))
        self.assertTrue(all(r['status']=='unresolved' for r in legacy['bindings']))

    def test_preflight_is_read_only_and_execution_reuses_exact_external_cache(self):
        run, base, _, _, original_graph, _ = self.selected()
        target = self.root/'new-workspace'; cw.initialize(target,run,base)
        before = {str(p.relative_to(target)): p.read_bytes() for p in target.rglob('*') if p.is_file()}
        plan = cw.preflight(target,cache_directories=[self.out])
        self.assertEqual(plan['status'],'fully_replayable')
        self.assertEqual(plan['provider_calls'],0)
        self.assertEqual(plan['cached_requests'],3)
        self.assertEqual(plan['external_cached_requests'],3)
        self.assertEqual(plan['remaining_units_upper_bound'],0)
        self.assertEqual(before,{str(p.relative_to(target)): p.read_bytes() for p in target.rglob('*') if p.is_file()})
        result = cw.execute(target,lambda _:self.fail('Unchanged requests must not be billed again'),cache_directories=[self.out])
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['reused_decisions'],3)
        self.assertEqual(result['budget_used']['jev_requests'],0)
        self.assertEqual(read(target/'graph.json'),original_graph)

    def test_changed_unit_replays_unaffected_prefix_and_stops_at_first_missing_decision(self):
        run,base,units,_,_,_ = self.selected()
        for n in base['nodes']:
            if n['id']==units[-1]['id']:
                n['properties']['content']['work_target']['text']='Report a different conclusion.'
        base.pop('id');base['id']='graph-'+digest(base)
        target=self.root/'changed';cw.initialize(target,run,base)
        plan=cw.preflight(target,cache_directories=[self.out])
        self.assertEqual(plan['status'],'needs_new_decision')
        self.assertEqual(plan['cached_requests'],2)
        self.assertEqual(plan['completed_prefix_units'],2)
        self.assertEqual(plan['first_uncached_request']['unit_id'],units[-1]['id'])
        self.assertEqual(plan['remaining_units_upper_bound'],1)
        result=cw.execute(target,lambda _:self.fail('Zero budget must stop before the changed request'),cache_directories=[self.out])
        self.assertEqual(result['status'],'budget_reached')
        self.assertEqual(result['budget_used']['jev_requests'],0)
        calls=[]
        result=cw.execute(target,lambda r:(calls.append(r) or choose('new_target')(r)),max_calls=1,cache_directories=[self.out])
        self.assertEqual(result['status'],'complete');self.assertEqual(len(calls),1)

    def test_preflight_cli_does_not_construct_client_or_prompt_for_key(self):
        import argparse,contextlib,io,json
        from unittest.mock import patch
        from tracker import semantic_cli
        self.selected()
        parser=argparse.ArgumentParser();semantic_cli.configure(parser.add_subparsers(dest='command'))
        args=parser.parse_args(['semantic','bind-work',str(self.out),'--preflight','--prompt-key'])
        out=io.StringIO()
        with patch('tracker.jev.JevClient',side_effect=AssertionError('Preflight must stay offline')),contextlib.redirect_stdout(out):
            semantic_cli.execute(args,Store(self.root/'cli.sqlite'))
        self.assertEqual(json.loads(out.getvalue())['provider_calls'],0)


if __name__=='__main__': unittest.main()
