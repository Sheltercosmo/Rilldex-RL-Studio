from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from tracker import work_content_stages as stages, work_mentions
from tracker.schema import InputError
from test_work_scope_frames import fixture
from test_work_mentions import proposal, answer


class ContentStagesTests(unittest.TestCase):
    def case(self):
        _, graph = fixture(2)
        packet = work_mentions.packet(graph, ['unit-0', 'unit-1'])
        old = proposal(packet)['readings'][0]['candidates'][0]
        body = dict(mentions=[{k:v for k,v in m.items() if k != 'id'} for m in old['mentions']])
        req = stages.content_request(packet, 'unit-0')
        contents = stages.bind_contents(packet, req, body, 'authored content control')
        link_req = stages.relationship_request(packet, contents)
        links = dict(links=[dict(source=contents['mentions'][0]['id'], target=contents['mentions'][1]['id'],
            type='purpose', evidence=old['links'][0]['evidence'])], content_issues=[])
        return graph, packet, req, body, contents, link_req, links

    def test_contents_stage_is_one_source_without_activity_or_relationship_generation(self):
        _, packet, req, body, contents, _, _ = self.case()
        self.assertEqual(req['unit']['unit_id'], 'unit-0')
        self.assertNotIn('units', req); self.assertNotIn('activity', req['unit'])
        self.assertEqual(set(req['response_format']), {'mentions'})
        self.assertEqual(contents['raw_response'], body)
        self.assertNotIn('links', contents)
        self.assertEqual(packet['units'][1]['unit_id'], 'unit-1')

    def test_host_assigned_ids_are_stable_across_order_but_bound_to_meaning(self):
        _, p, q, b, c, _, _ = self.case()
        reversed_body = dict(mentions=list(reversed(b['mentions'])))
        reversed_contents = stages.bind_contents(p, q, reversed_body, 'authored content control')
        self.assertEqual([m['id'] for m in c['mentions']], list(reversed([m['id'] for m in reversed_contents['mentions']])))
        changed = deepcopy(b); changed['mentions'][0]['label'] = 'Different work'
        self.assertNotEqual(stages.bind_contents(p,q,changed,'authored content control')['mentions'][0]['id'],c['mentions'][0]['id'])

    def test_content_fields_quotes_duplicate_contents_and_request_mutation_fail(self):
        _, p, q, b, _, _, _ = self.case()
        bad = deepcopy(b); bad['mentions'][0]['id'] = 'generated'
        with self.assertRaises(InputError): stages.bind_contents(p,q,bad,'control')
        bad = deepcopy(b); bad['mentions'][0]['evidence'] = {'text':'Not in source'}
        with self.assertRaises(InputError): stages.bind_contents(p,q,bad,'control')
        with self.assertRaises(InputError): stages.bind_contents(p,q,dict(mentions=[b['mentions'][0]]*2),'control')
        changed = deepcopy(q); changed['unit']['source']['text'] = 'Changed'
        with self.assertRaises(InputError): stages.bind_contents(p,changed,b,'control')

    def test_bad_relationship_does_not_mutate_or_recalculate_bound_contents(self):
        _, p, q, b, c, lr, links = self.case(); before = deepcopy(c)
        bad = deepcopy(links); bad['links'][0]['evidence'] = {'text':'stitched fabricated quote'}
        with self.assertRaises(InputError): stages.assemble(p,c,lr,bad,'control')
        self.assertEqual(c,before)
        self.assertEqual(stages.bind_contents(p,q,b,'authored content control'),before)
        self.assertEqual(stages.relationship_request(p,c),lr)

    def test_changed_contents_or_stale_relationship_request_fail(self):
        _, p, _, _, c, lr, links = self.case()
        for field in ['label','mode']:
            changed = deepcopy(c); changed['mentions'][0][field] = 'changed'
            with self.subTest(field=field),self.assertRaises(InputError): stages.relationship_request(p,changed)
        changed = deepcopy(lr); changed['contents_hash'] = 'different'
        with self.assertRaises(InputError): stages.assemble(p,c,changed,links,'control')
        bad = deepcopy(links); bad['links'][0]['target'] = 'foreign-unit'
        with self.assertRaises(InputError): stages.assemble(p,c,lr,bad,'control')

    def test_content_issue_prevents_selectable_candidate_without_implicit_repair(self):
        _, p, _, _, c, lr, links = self.case()
        links['content_issues'] = [dict(mention_ids=[], evidence={'text':p['units'][0]['source']['text']},issue='An intended effect needs review.')]
        with self.assertRaisesRegex(InputError,'content review required'): stages.assemble(p,c,lr,links,'control')
        links['content_issues'][0]['mention_ids'] = ['foreign']
        with self.assertRaisesRegex(InputError,'invalid issue referent'): stages.assemble(p,c,lr,links,'control')

    def test_staged_candidate_reuses_existing_argmax_selector_and_unchanged_base_units(self):
        g, p, _, _, c, lr, links = self.case(); before=deepcopy(g)
        built=stages.assemble(p,c,lr,links,'authored relationship control')
        self.assertEqual(len(built['selection_request']['state']['units']),1)
        decision=answer(built['selection_request'])
        # The fixture's textual choice disagrees with probability argmax.
        rows=work_mentions.selected(built['packet'],built['bound'],decision)
        self.assertEqual(rows[0]['choice'],'c0')
        out=work_mentions.fork(g,built['packet'],built['proposal'],built['bound']['producer'],decision)
        work_mentions.audit(out)
        self.assertEqual(g,before)
        self.assertEqual([n for n in g['nodes'] if n['kind']=='unit'],[n for n in out['nodes'] if n['kind']=='unit'])

    def test_empty_contents_are_possible_but_cannot_have_dangling_links(self):
        _, p, q, _, _, _, _=self.case()
        c=stages.bind_contents(p,q,dict(mentions=[]),'control');lr=stages.relationship_request(p,c)
        built=stages.assemble(p,c,lr,dict(links=[],content_issues=[]),'control')
        self.assertEqual(built['bound']['readings'][0]['candidates'][0]['mentions'],[])
        with self.assertRaises(InputError):stages.assemble(p,c,lr,dict(links=[dict(source='m1',target='m2',type='purpose',evidence={'text':'x'})],content_issues=[]),'control')

    def test_files_replay_identical_deliveries_without_new_calls(self):
        _, packet, _, body, _, _, links = self.case()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); directory = root/'stages'
            self.assertFalse(stages.prepare_files(packet,'unit-0',directory)['reused'])
            self.assertTrue(stages.prepare_files(packet,'unit-0',directory)['reused'])
            response = root/'response.json'
            raw = json.dumps(body, ensure_ascii=False, indent=3)
            response.write_bytes(raw.encode('utf-8'))
            first = stages.accept_contents(directory,response,'authored content control','fixture/content')
            self.assertFalse(first['reused']); self.assertEqual(first['new_provider_calls'],0)
            second = stages.accept_contents(directory,response,'authored content control','fixture/content')
            self.assertTrue(second['reused'])
            self.assertEqual(json.loads((directory/'content-delivery.json').read_text(encoding='utf-8'))['raw_output'],raw)
            from tracker import work_content_audit
            from test_work_content_audit import response as audit_response
            audit_request = json.loads((directory/'content-audit-request.json').read_text(encoding='utf-8'))
            response.write_text(json.dumps(audit_response(audit_request)),encoding='utf-8')
            audited=work_content_audit.accept_files(directory,response,'authored content audit','fixture/audit')
            self.assertTrue(audited['ready_for_relationships'])
            response.write_text(json.dumps(links),encoding='utf-8')
            final = stages.accept_relationships(directory,response,'authored relationships','fixture/links')
            self.assertFalse(final['reused']); self.assertEqual(final['links'],1)
            self.assertTrue(stages.accept_relationships(directory,response,'authored relationships','fixture/links')['reused'])
            self.assertTrue((directory/'selection-request.json').exists())

    def test_file_conflicts_preflight_before_new_delivery_is_written(self):
        _, packet, _, body, _, _, _ = self.case()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); directory=root/'stages'; response=root/'response.json'
            stages.prepare_files(packet,'unit-0',directory)
            response.write_text(json.dumps(body),encoding='utf-8')
            (directory/'bound-contents.json').write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(InputError,'artifact differs'):
                stages.accept_contents(directory,response,'control','fixture/content')
            self.assertFalse((directory/'content-delivery.json').exists())
            self.assertFalse((directory/'relationship-request.json').exists())

    def test_changed_file_content_cannot_be_silently_linked(self):
        _, packet, _, body, _, _, links = self.case()
        for target in ['content-delivery.json','bound-contents.json','relationship-request.json','content-request.json']:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); directory=root/'stages'; response=root/'response.json'
                stages.prepare_files(packet,'unit-0',directory)
                response.write_text(json.dumps(body),encoding='utf-8')
                stages.accept_contents(directory,response,'authored content control','fixture/content')
                artifact=directory/target
                value=json.loads(artifact.read_text(encoding='utf-8'))
                if target=='content-delivery.json': value['raw_output']='{}'
                elif target=='bound-contents.json': value['mentions'][0]['label']='Invented'
                else: value['unit']['source']['text']='Changed'
                artifact.write_text(json.dumps(value),encoding='utf-8')
                response.write_text(json.dumps(links),encoding='utf-8')
                with self.assertRaises(InputError):
                    stages.accept_relationships(directory,response,'control','fixture/links')
                self.assertFalse((directory/'relationship-delivery.json').exists())
                self.assertFalse((directory/'selection-request.json').exists())

    def test_invalid_external_response_leaves_stage_retryable(self):
        _, packet, _, body, _, _, _ = self.case()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); directory=root/'stages'; response=root/'response.json'
            stages.prepare_files(packet,'unit-0',directory)
            for bad in [b'\xff',b'x'*128001,b'{}']:
                response.write_bytes(bad)
                with self.assertRaises(InputError): stages.accept_contents(directory,response,'control','fixture/content')
                self.assertFalse((directory/'content-delivery.json').exists())
            response.write_text(json.dumps(body),encoding='utf-8')
            self.assertFalse(stages.accept_contents(directory,response,'control','fixture/content')['reused'])


if __name__ == '__main__': unittest.main()
