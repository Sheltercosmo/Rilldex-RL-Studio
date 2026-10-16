"""Source searches obey the same captured-context boundaries as maps."""
from copy import deepcopy
import unittest

from tracker.schema import InputError
from tracker.source_evidence import search
from test_source_evidence import chat, records_by_id


class EvidenceScopeTests(unittest.TestCase):
    def source(self):
        run = chat([dict(role='assistant', content='quasar evidence '+str(i)) for i in range(6)] +
                   [dict(role='assistant', content='Review quasar evidence.')])
        for e in run['events']:e['context_id'] = 'session-b'
        return run, dict(anchor={'event_id': run['events'][-1]['id']}, text='quasar', limit=2)

    def test_foreign_context_cannot_change_candidates_ranking_or_cursor(self):
        run, query = self.source()
        original = search(run, query)
        other = deepcopy(run['events'][0])
        other.update(id='other-context', index=-1, context_id='session-a', text='quasar '*100)
        run['events'].append(other)
        for strategy in ('source', 'source_and_calls'):
            before = search(dict(run, events=[e for e in run['events'] if e['id']!='other-context']), dict(query,strategy=strategy))
            after = search(run, dict(query,strategy=strategy))
            for field in ('matches','records','questions','pagination'):
                self.assertEqual(before[field], after[field])
            self.assertEqual(after['coverage']['excluded_source_records'],[
                dict(event_id='other-context', reason='different_recorded_context')])
        continued = search(run,dict(query,cursor=original['pagination']['next_cursor']))
        self.assertEqual(continued['pagination']['offset'],2)

    def test_unresolved_order_cannot_supply_previous_evidence(self):
        run, query = self.source()
        run['events'][0]['order_known'] = False
        result = search(run, query)
        self.assertNotIn(run['events'][0]['id'], records_by_id(result))
        self.assertIn(dict(event_id=run['events'][0]['id'],reason='unresolved_source_order'),
                      result['coverage']['excluded_source_records'])
        current = run['events'][-1]
        current.update(text='localneedle before selected contribution', order_known=False)
        result = search(run,dict(anchor={'event_id':current['id'],'start':19},text='localneedle'))
        self.assertEqual(set(records_by_id(result)),{current['id']})
        self.assertFalse(result['scope']['anchor_order_established'])
        self.assertEqual(result['scope']['earlier_records'],'unavailable')

    def test_anchor_context_and_order_changes_invalidate_continuation(self):
        run, query = self.source()
        first = search(run, query)
        for changes in (dict(context_id='new-session'),dict(order_known=False)):
            altered=deepcopy(run);altered['events'][-1].update(changes)
            with self.subTest(changes=changes),self.assertRaisesRegex(InputError,'changed'):
                search(altered,dict(query,cursor=first['pagination']['next_cursor']))

    def test_native_call_context_does_not_reuse_another_sessions_call_id(self):
        run=chat([
            dict(role='assistant',content='Read quasar archive',tool_calls=[dict(id='same-id',type='function',function=dict(name='read',arguments='{}'))]),
            dict(role='tool',tool_call_id='same-id',content='First result'),
            dict(role='assistant',content='Inspect current archive',tool_calls=[dict(id='new-id',type='function',function=dict(name='read',arguments='{}'))]),
            dict(role='tool',tool_call_id='new-id',content='Current result'),
            dict(role='assistant',content='Review current evidence')])
        boundary=next(e['index'] for e in run['events'] if e['text']=='Inspect current archive')
        for e in run['events']:
            e['context_id']='old' if e['index']<boundary else 'current'
            # Simulate a collector merging two native sessions whose local
            # invocation IDs restart. A single chat import rejects duplicates.
            if e.get('call_id')=='new-id':e['call_id']='same-id'
            if e.get('source_call_id')=='new-id':e['source_call_id']='same-id'
        query=dict(anchor={'event_id':run['events'][-1]['id']},strategy='source_and_calls',
                   questions=[dict(id='result',text='current archive',source_types=['feedback'])])
        result=search(run,query)
        self.assertEqual(len(result['matches']),1)
        self.assertEqual(next(e['text'] for e in run['events'] if e['id']==result['matches'][0]['event_id']),'Current result')
        self.assertTrue(all(next(e for e in run['events'] if e['id']==r['event_id'])['context_id']=='current' for r in result['records']))

    def test_unspecified_context_and_visible_copies_are_explicit(self):
        run, query=self.source()
        for e in run['events']:e.pop('context_id')
        run['events'][0]['copied_context']=True
        result=search(run,dict(query,limit=8))
        self.assertEqual(result['scope']['context_boundary'],'unspecified')
        self.assertTrue(records_by_id(result)[run['events'][0]['id']]['copied_context'])

    def test_later_or_copied_parent_cannot_supply_call_match(self):
        run=chat([dict(role='assistant',content='Inspect archive',tool_calls=[
            dict(id='lookup',type='function',function=dict(name='read',arguments='{}'))]),
            dict(role='tool',tool_call_id='lookup',content='Return code 0'),
            dict(role='assistant',content='Later claim: quasar.'),
            dict(role='assistant',content='Inspect this claim.')])
        action=next(e for e in run['events'] if e['kind']=='action')
        later=next(e for e in run['events'] if 'Later claim' in e['text'])
        action['parent_id']=later['id']
        query=dict(anchor={'event_id':run['events'][-1]['id']},strategy='source_and_calls',
            questions=[dict(id='q',text='quasar',source_types=['feedback'])])
        self.assertEqual(search(run,query)['matches'],[])
        action['parent_id']=run['events'][0]['id']
        run['events'][0].update(text='Copied quasar intention',copied_context=True)
        self.assertEqual(search(run,query)['matches'],[])


if __name__=='__main__':unittest.main()
