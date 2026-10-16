"""Source-field comparison controls, not strategy or recovery ground truth."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker import action_comparison as ac, graph_store, work_hierarchy
from tracker.adapters import normalize
from tracker.portable import chat_document
from tests.test_work_hierarchy import finish
from tests.test_evidence import swe


def graph(before,after,tools=('query','query')):
    messages=[{'role':'user','content':'Authored comparison control'}]
    for i,(args,tool) in enumerate(zip((before,after),tools)):
        messages.append(dict(role='assistant',content='',tool_calls=[dict(id='call-'+str(i),type='function',
            function=dict(name=tool,arguments=args if isinstance(args,str) else json.dumps(args)))]))
        messages.append(dict(role='tool',tool_call_id='call-'+str(i),content='Recorded response'))
    run=normalize(chat_document(messages))[0];g=graph_store.build(run)
    ids=[n['id'] for n in g['nodes'] if n['kind']=='event' and n['properties']['kind']=='action']
    return g,ids


class ActionComparisonTests(unittest.TestCase):
    def test_field_comparison_keeps_missing_null_types_and_pointer_escapes(self):
        g,ids=graph({'filter':{'a/b':None},'enabled':True,'gone':None},
                    {'filter':{'a/b':'x'},'enabled':1,'added':None})
        out=ac.compare(g,*ids);changes={r['path']:r for r in out['changes']}
        self.assertEqual(out['basis'],'recorded_fields');self.assertEqual(out['status'],'changed')
        self.assertEqual(set(changes),{'/arguments/filter/a~1b','/arguments/enabled','/arguments/gone','/arguments/added'})
        self.assertFalse(changes['/arguments/gone']['after']['present'])
        self.assertEqual(changes['/arguments/added']['after']['preview'],'null')
        self.assertEqual(changes['/arguments/enabled']['before']['type'],'bool')

    def test_key_order_is_ignored_but_list_order_is_preserved(self):
        g,ids=graph('{"x":1,"y":2}','{ "y":2, "x":1 }')
        self.assertEqual(ac.compare(g,*ids)['status'],'unchanged')
        g,ids=graph({'items':[1,2]},{'items':[2,1]})
        self.assertEqual([r['path'] for r in ac.compare(g,*ids)['changes']],['/arguments/items'])

    def test_changed_tool_is_visible_separately_from_arguments(self):
        g,ids=graph({'id':1},{'id':1},('read','write'))
        self.assertEqual([r['path'] for r in ac.compare(g,*ids)['changes']],['/tool'])

    def test_changed_text_span_keeps_exact_offsets_including_unicode(self):
        before='run α.md -o α.pdf';after=before+' --engine=latex'
        g,ids=graph({'command':before},{'command':after});c=ac.compare(g,*ids)['changes'][0]
        span=c['text_span'];self.assertEqual(span['before']['preview'],'')
        self.assertEqual(span['after']['preview'],' --engine=latex')
        self.assertEqual(after[span['after_start']:span['after_end']],span['after']['preview'])

    def test_same_call_does_not_infer_same_environment(self):
        g,ids=graph({'command':'build'},{'command':'build'});out=ac.compare(g,*ids)
        self.assertEqual(out['status'],'unchanged');self.assertIn('changed files',out['limits'])
        self.assertNotIn('success',out);self.assertNotIn('strategy',out)

    def test_invalid_or_duplicate_json_never_becomes_structured_equality(self):
        for raw in ['{broken','{"x":1,"x":2}']:
            g,ids=graph(raw,{'x':2});out=ac.compare(g,*ids)
            self.assertEqual(out['basis'],'recorded_text');self.assertEqual(out['status'],'changed')

    def test_missing_arguments_do_not_become_empty_object_equality(self):
        g,ids=graph({},{});first=next(n for n in g['nodes'] if n['id']==ids[0])
        first['properties']['arguments_available']=False
        out=ac.compare(g,*ids);self.assertEqual(out['basis'],'recorded_text')
        self.assertIn('at least one endpoint',out['basis_note'])

    def test_siblings_and_cross_context_are_unavailable(self):
        g,ids=graph({'q':'a'},{'q':'b'});a,b=[next(n['properties'] for n in g['nodes'] if n['id']==id) for id in ids]
        b['parent_id']=a['parent_id']
        self.assertIn('Sibling',ac.compare(g,*ids)['reason'])
        b['parent_id']='another';b['context_id']='other-context'
        self.assertIn('different actors or source contexts',ac.compare(g,*ids)['reason'])
        b.pop('context_id');self.assertIn('earlier source',ac.compare(g,*ids[::-1])['reason'])

    def test_source_unit_needs_exact_grounding_and_matching_quote(self):
        g,ids=graph({'q':'a'},{'q':'b'});node=next(n for n in g['nodes'] if n['id']==ids[0]);p=node['properties']
        g['nodes'].append(dict(id='unit',kind='unit',trajectory_id=node['trajectory_id'],event_index=node['event_index'],
            properties=dict(actor=p['actor'],kind='action',source=dict(event_id=p['id'],start=0,end=len(p['text']),text=p['text']))))
        self.assertEqual(ac.compare(g,'unit',ids[1])['status'],'unavailable')
        g['edges'].append(dict(type='grounded_in',source='unit',target=ids[0]))
        self.assertEqual(ac.compare(g,'unit',ids[1])['status'],'changed')
        g['nodes'][-1]['properties']['source']['text']='Wrong source'
        self.assertEqual(ac.compare(g,'unit',ids[1])['status'],'unavailable')

    def test_large_values_and_many_fields_have_explicit_bounds(self):
        g,ids=graph({'body':'x'*1000},{'body':'y'*1000});out=ac.compare(g,*ids)
        self.assertTrue(out['changes'][0]['before']['truncated'])
        self.assertEqual(out['changes'][0]['before']['characters'],1000)
        g,ids=graph({str(i):0 for i in range(80)},{str(i):1 for i in range(80)})
        out=ac.compare(g,*ids);self.assertEqual(len(out['changes']),64);self.assertTrue(out['changes_truncated'])
        g,ids=graph({'body':'x'*ac.MAX_BYTES},{'body':'y'*ac.MAX_BYTES})
        self.assertEqual(ac.compare(g,*ids)['status'],'unavailable')

    def test_real_harbor_exports_retain_comparable_recorded_fields(self):
        for filename in ['hello-world-timeout.trajectory.json','mini-swe-agent-trajectory.json']:
            path=Path('tests/fixtures/harbor')/filename;original=path.read_bytes()
            run=normalize(json.loads(original))[0];g=graph_store.build(run)
            ids=[n['id'] for n in sorted(g['nodes'],key=lambda n:n.get('event_index',-1)) if n['kind']=='event' and n['properties']['kind']=='action']
            out=ac.compare(g,*ids[:2]);self.assertEqual(out['basis'],'recorded_fields')
            self.assertEqual(out['status'],'changed');self.assertEqual(path.read_bytes(),original)

    def test_swe_agent_command_fields_use_the_same_comparator(self):
        run=swe([dict(action='pytest -q',observation='failed'),dict(action='pytest -x',observation='failed')])
        g=graph_store.build(run);ids=[n['id'] for n in g['nodes'] if n['kind']=='event' and n['properties']['kind']=='action']
        out=ac.compare(g,*ids);self.assertEqual(out['changes'][0]['path'],'/arguments/command')
        self.assertEqual(out['changes'][0]['text_span']['after']['preview'],'x')

    def test_public_plan_returns_show_changed_text_and_unchanged_call_after_edit(self):
        raw=json.loads(Path('research/work-hierarchy-2026-10-13/software-evidence.json').read_text(encoding='utf8'))
        g=raw.get('graph',raw);before=deepcopy(g);out=work_hierarchy.build(g)
        path=next(p for p in out['stage_paths'] if p['stage_id'].endswith(':convert'))
        by_pair={tuple(r['event_index']+1 for r in x['comparison']['sources']):x for x in path['return_comparisons']}
        self.assertEqual(len(by_pair),3)
        first=by_pair[(78,84)];self.assertEqual(first['comparison']['basis'],'recorded_text')
        self.assertEqual(first['comparison']['changes'][0]['text_span']['after']['preview'],' --pdf-engine=pdflatex')
        last=by_pair[(90,96)];self.assertEqual(last['comparison']['status'],'unchanged')
        self.assertEqual([r['event_index']+1 for r in last['intervening']],[93])
        self.assertIn('absolute',last['intervening'][0]['label'].lower())
        self.assertTrue(last['intervening'][0]['linked_to_step'])
        self.assertEqual(g,before);self.assertEqual(work_hierarchy.build(g),out)

    def test_cutoff_and_unassigned_context_do_not_invent_step_membership(self):
        raw=json.loads(Path('research/work-hierarchy-2026-10-13/software-evidence.json').read_text(encoding='utf8'));g=raw.get('graph',raw)
        out=work_hierarchy.build(g,'e90');path=next(p for p in out['stage_paths'] if p['stage_id'].endswith(':convert'))
        self.assertEqual(len(path['return_comparisons']),2)
        self.assertTrue(all(r['event_index']<90 for c in path['return_comparisons'] for r in c['intervening']))
        edit=next(n['id'] for n in g['nodes'] if n['kind']=='unit' and n['event_index']==92)
        g['edges']=[e for e in g['edges'] if not(e['type']=='prepares_plan_step' and e['source']==edit)]
        out=work_hierarchy.build(finish(g));path=next(p for p in out['stage_paths'] if p['stage_id'].endswith(':convert'))
        row=next(n for c in path['return_comparisons'] for n in c['intervening'] if n['id']==edit)
        self.assertFalse(row['linked_to_step']);self.assertIn(edit,out['unassigned_action_ids'])


if __name__=='__main__':unittest.main()
