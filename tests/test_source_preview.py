import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker.connections import preview, recent_receipts, create, Service
from tracker.integrations import inspect
from tracker.graph_store import build
from tracker.portable import chat_document, generation_document
from tracker.source_preview import EVENT_LIMIT, TEXT_LIMIT
from tracker.store import Store
from test_portable import conversation
from test_connections import MonitorStub


class SourcePreviewTests(unittest.TestCase):
    def test_parallel_results_link_by_identity_and_match_source_map(self):
        run = normalize(conversation())[0]
        result = inspect(run)['source_preview']
        events = {event['id']: event for event in result['events']}
        self.assertTrue(any(e['child_counts']=={'reasoning':1,'action':2} for e in events.values()))
        for relation in result['relations']:
            self.assertEqual(events[relation['action_id']]['text'],
                             'read({"id": "' + events[relation['feedback_id']]['text'][-1].lower() + '"})')
        graph = build(run)
        self.assertEqual({(edge['source'].removeprefix('event:'), edge['target'].removeprefix('event:'))
                          for edge in graph['edges'] if edge['type'] == 'response_to'},
                         {(edge['feedback_id'], edge['action_id']) for edge in result['relations']})

    def test_long_content_is_bounded_without_silent_relation_loss(self):
        document = conversation()
        document['messages'][1]['content'] = '<script>raw source</script>' + 'x' * 10000
        document['messages'] += [message for _ in range(20) for message in copy.deepcopy(document['messages'][2:])]
        # Distinct call IDs prevent the deliberately long fixture making ambiguous joins.
        for index, message in enumerate(document['messages']):
            if message.get('tool_calls'):
                for call in message['tool_calls']:
                    old = call['id']; call['id'] = f'{index}-{old}'
                for result in document['messages'][index+1:index+3]:
                    if result.get('tool_call_id'):
                        result['tool_call_id'] = f"{index}-{result['tool_call_id']}"
        run = normalize(document)[0]
        result = inspect(run)['source_preview']
        self.assertEqual(len(result['events']), EVENT_LIMIT)
        self.assertGreater(result['omitted_events'], 80)
        self.assertGreater(result['omitted_relations'], 0)
        self.assertTrue(all(len(e['text']) <= TEXT_LIMIT for e in result['events']))
        long = result['events'][1]
        self.assertEqual(long['omitted_characters'], len(document['messages'][1]['content']) - TEXT_LIMIT)
        self.assertTrue(long['text'].startswith('<script>'))  # Escaping belongs to DOM textContent.
        visible = {e['id'] for e in result['events']}
        self.assertTrue(all(r['action_id'] in visible and r['feedback_id'] in visible for r in result['relations']))

    def test_missing_ambiguous_and_cross_timeline_links_are_not_inferred(self):
        for mode in ('missing', 'duplicate', 'future', 'cross_timeline', 'copied'):
            run = normalize(conversation())[0]
            actions = [e for e in run['events'] if e['kind'] == 'action']
            responses = [e for e in run['events'] if e['kind'] == 'feedback']
            if mode == 'missing':
                for response in responses: response['source_call_id'] = 'unrecorded'
            elif mode == 'duplicate':
                for action in actions: action['call_id'] = 'a'
            elif mode == 'future':
                for action in actions: action['index'] = 999
            elif mode == 'cross_timeline':
                for response in responses: response['trajectory_id'] = 'other'
            else:
                for action in actions: action['copied_context'] = True
            result = inspect(run)['source_preview']
            self.assertEqual(result['relations'], [], mode)
            self.assertEqual(sum(e['unlinked_response'] for e in result['events']), 2, mode)

    def test_media_and_empty_messages_do_not_become_empty_or_semantic_cards(self):
        run = normalize(chat_document([{'role': 'user', 'content': 'Inspect the image'},
            {'role': 'assistant', 'content': [{'type': 'image_url', 'image_url': {'url': 'fixture.png'}}]}]))[0]
        result = inspect(run)['source_preview']
        self.assertEqual(result['events'][-1]['media_count'], 1)
        self.assertEqual(result['events'][-1]['text'], '')
        self.assertNotIn('activity', result['events'][-1])

    def test_directory_preview_selects_latest_sampled_revision_and_never_ingests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); store = Store(root/'db.sqlite')
            envelope = dict(producer='p', rollout_id='a', revision=0, state='in_progress',
                            document=generation_document('Question', 'Draft'))
            second = {**envelope, 'revision': 1, 'state': 'complete',
                      'document': generation_document('Question', 'Revised answer')}
            (root/'output.jsonl').write_text(json.dumps(envelope)+'\n'+json.dumps(second)+'\n', encoding='utf-8')
            with store.connect() as c: before = list(c.iterdump())
            result = preview(store, dict(root=str(root), mode='exports', producer='p', metadata={'experiment':'a'}))
            self.assertEqual(len(result['samples']), 2)
            content = result['coverage']['runs'][0]['source_preview']
            self.assertEqual(content['delivery'], {'revision':1, 'state':'complete'})
            self.assertEqual(content['events'][-1]['text'], 'Revised answer')
            with store.connect() as c: self.assertEqual(before, list(c.iterdump()))

    def test_receipt_scope_survives_other_workers_and_restart_and_preserves_experiments(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); store=Store(root/'db.sqlite')
            cid=create(store,dict(root=str(root), producer='quiet'))['id']
            doc=generation_document('Q','A')
            envelope=dict(producer='quiet',rollout_id='a',revision=0,state='in_progress',document=doc,metadata={'experiment':'one'})
            store.ingest(envelope)
            current=store.ingest({**envelope,'revision':1,'state':'complete'})['id']
            store.ingest({**envelope,'rollout_id':'b','metadata':{'experiment':'two'}})
            for index in range(35):
                store.ingest({**envelope,'producer':'busy','rollout_id':str(index)})
            reopened=Store(store.path)
            with reopened.connect() as c:
                self.assertTrue(all(row['producer']=='busy' for row in recent_receipts(c)))
                scoped=recent_receipts(c,producer='quiet',limit=3)
            self.assertEqual(len(scoped),2)
            self.assertEqual({r['experiment'] for r in scoped},{'one','two'})
            self.assertEqual(next(r for r in scoped if r['rollout_id']=='a')['run_id'],current)
            service=Service(reopened,MonitorStub())
            try:
                saved=next(r for r in service.snapshot()['connections'] if r['id']==cid)
                self.assertEqual(saved['recent_rollouts'],scoped)
            finally: service.close()


if __name__=='__main__': unittest.main()
