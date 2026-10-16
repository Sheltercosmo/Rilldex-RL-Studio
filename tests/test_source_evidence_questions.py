"""Question coverage, native dependencies and visibility are separate contracts."""
from copy import deepcopy
import unittest

from tracker.schema import InputError
from tracker.source_evidence import search
from test_source_evidence import chat, basic_run, records_by_id


class QuestionEvidenceTests(unittest.TestCase):
    def test_independent_questions_share_slots_without_score_comparison(self):
        run = chat([{'role': 'assistant', 'content': 'compile failure repeated explanation'} for _ in range(10)] + [
            {'role': 'assistant', 'content': 'Archive fingerprint changed.'},
            {'role': 'assistant', 'content': 'Review the work.'}])
        result = search(run, dict(anchor={'event_id': run['events'][-1]['id']}, limit=2, questions=[
            dict(id='failure', text='compile failure'), dict(id='version', text='archive fingerprint')]))
        self.assertEqual(len(result['matches']), 2)
        self.assertTrue(all(q['retained_match_event_ids'] for q in result['questions']))
        self.assertTrue(all(q['status'] == 'candidates_retained' for q in result['questions']))
        self.assertLessEqual(result['coverage']['source_text_chars'], 16000)
        self.assertNotIn('answered', str(result['questions']))

    def test_recorded_parent_exposes_child_call_and_result_with_no_lexical_match(self):
        run = chat([
            {'role': 'assistant', 'content': 'Inspect the archive fingerprint.', 'tool_calls': [
                {'id': 'call-a', 'type': 'function', 'function': {'name': 'execute', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'call-a', 'content': 'REJECTED: digest differs.'},
            {'role': 'assistant', 'content': 'Review the work.'}])
        result = search(run, dict(anchor={'event_id': run['events'][-1]['id']}, text='archive fingerprint', limit=1))
        action = next(e for e in run['events'] if e['kind'] == 'action')
        response = next(e for e in run['events'] if e['kind'] == 'feedback')
        by_id = records_by_id(result)
        self.assertIn('recorded_child_dispatch', [r['kind'] for r in by_id[action['id']]['reasons']])
        self.assertIn('recorded_response', [r['kind'] for r in by_id[response['id']]['reasons']])
        self.assertNotIn('outcome', by_id[response['id']])

    def test_source_type_filter_retrieves_responses_instead_of_repeated_claims(self):
        run = chat([{'role': 'assistant', 'content': 'checksum accepted claim'} for _ in range(12)] + [
            {'role': 'assistant', 'content': '', 'tool_calls': [
                {'id': 'call-b', 'type': 'function', 'function': {'name': 'check', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'call-b', 'content': 'checksum actually differs'},
            {'role': 'assistant', 'content': 'Review the work.'}])
        result = search(run, dict(anchor={'event_id': run['events'][-1]['id']}, limit=1,
            questions=[dict(id='receipt', text='checksum', source_types=['feedback'])]))
        self.assertEqual(result['matches'][0]['source_type'], 'feedback')
        self.assertEqual(result['questions'][0]['lexically_matched_events'], 1)
        self.assertEqual(len(result['questions'][0]['retained_match_event_ids']), 1)

    def test_context_search_labels_indirect_match_and_returns_the_recorded_chain(self):
        run = chat([
            {'role': 'assistant', 'content': 'Inspect the archive fingerprint.', 'tool_calls': [
                {'id': 'call-a', 'type': 'function', 'function': {'name': 'execute', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'call-a', 'content': 'REJECTED: digest differs.'},
            {'role': 'assistant', 'content': 'Review the work.'}])
        query = dict(anchor={'event_id': run['events'][-1]['id']}, limit=1,
                     questions=[dict(id='returned', text='archive fingerprint', source_types=['feedback'])])
        direct = search(run, query)
        self.assertEqual(direct['questions'][0]['status'], 'no_lexical_matches')
        linked = search(run, dict(query, strategy='source_and_calls'))
        match = linked['matches'][0]
        self.assertEqual(match['match_basis'], 'recorded_context')
        self.assertEqual(linked['questions'][0]['context_only_match_event_ids'], [match['event_id']])
        records = records_by_id(linked)
        self.assertEqual(len(records), 3)
        self.assertIn('recorded_context_match', [r['kind'] for r in records[match['event_id']]['reasons']])
        self.assertTrue(any(r['kind'] == 'recorded_parent' for row in records.values() for r in row['reasons']))
        self.assertTrue(any('archive fingerprint' in f['text'] for row in records.values() for f in row['fragments']))

    def test_distant_question_match_cannot_be_satisfied_by_another_excerpt(self):
        text = 'alphaone ' + 'background ' * 650 + 'betatwo ' + 'background ' * 100
        run = chat([{'role': 'assistant', 'content': text}, {'role': 'assistant', 'content': 'Inspect.'}])
        result = search(run, dict(anchor={'event_id': run['events'][-1]['id']}, max_chars=2000,
            questions=[dict(id='a', text='alphaone'), dict(id='b', text='betatwo')]))
        self.assertEqual(result['questions'][0]['status'], 'candidates_retained')
        self.assertEqual(result['questions'][1]['status'], 'candidates_retained')
        self.assertTrue(result['questions'][1]['retained_match_event_ids'])
        self.assertLessEqual(result['coverage']['source_text_chars'],2000)
        for question in result['questions']:
            span=question['retained_match_ranges'][0]
            self.assertIn(question['text'],text[span['start']:span['end']])
            self.assertTrue(any(f['start']<=span['start'] and f['end']>=span['end']
                for f in records_by_id(result)[span['event_id']]['fragments']))
        self.assertTrue(result['coverage']['deferred'])
        records=records_by_id(result)
        for omitted in result['coverage']['deferred']:
            self.assertEqual(omitted['omitted_source_chars'],sum(r['end']-r['start'] for r in omitted['omitted_ranges']))
            for r in omitted['omitted_ranges']:
                self.assertFalse(any(max(r['start'],f['start'])<min(r['end'],f['end'])
                    for f in records.get(omitted['event_id'],{}).get('fragments',[])))
        larger = search(run, dict(result['query'], max_chars=4000))
        self.assertEqual(larger['questions'][1]['status'], 'candidates_retained')

    def test_question_passage_priority_does_not_claim_all_passages_fit(self):
        words=['firstneedle','secondneedle','thirdneedle','fourthneedle','fifthneedle','sixthneedle','seventhneedle','eighthneedle']
        text=(' background '*700).join(words)
        run=chat([dict(role='assistant',content=text),dict(role='assistant',content='Inspect.')])
        result=search(run,dict(anchor={'event_id':run['events'][-1]['id']},max_chars=2000,
            questions=[dict(id=str(i),text=word) for i,word in enumerate(words)]))
        self.assertLessEqual(result['coverage']['source_text_chars'],2000)
        self.assertTrue(any(q['status']=='candidates_retained' for q in result['questions']))
        self.assertTrue(any(q['status']=='candidates_omitted' for q in result['questions']))
        for q in result['questions']:
            found=any(q['text'] in f['text'] for r in result['records'] for f in r['fragments'])
            self.assertEqual(bool(q['retained_match_event_ids']),found)

    def test_empty_search_is_not_budget_omission_or_evidence_of_absence(self):
        run = basic_run()
        result = search(run, dict(anchor={'event_id': 'e7'}, questions=[
            dict(id='unknown', text='neverpresenttoken')]))
        self.assertEqual(result['questions'][0]['status'], 'no_lexical_matches')
        self.assertNotIn('absent', result['questions'][0])

    def test_future_and_other_trajectory_do_not_change_question_rankings_or_context(self):
        run = basic_run()
        query = dict(anchor={'event_id': 'e7'}, questions=[
            dict(id='q1', text='quasarneedle', source_types=['feedback']),
            dict(id='q2', text='inspect')])
        query['strategy'] = 'source_and_calls'
        before = search(run, query)
        other = deepcopy(run['events'][2])
        other.update(id='other', trajectory_id='other', index=0, text='quasarneedle inspect')
        future = deepcopy(other)
        future.update(id='future', trajectory_id='main', index=100)
        changed = deepcopy(run)
        changed['events'].extend([other, future])
        after = search(changed, query)
        self.assertEqual(before['questions'], after['questions'])
        self.assertEqual(before['matches'], after['matches'])
        self.assertEqual(before['records'], after['records'])

    def test_same_event_suffix_and_parallel_actions_cannot_enter_dependency_context(self):
        run = basic_run()
        current = run['events'][6]
        current['text'] = 'earlierword selectedsuffix'
        sibling = deepcopy(current)
        sibling.update(id='sibling', index=5.5, text='earlierword')
        run['events'].append(sibling)
        result = search(run, dict(anchor={'event_id': current['id'], 'start': 12},
            questions=[dict(id='a', text='earlierword'), dict(id='b', text='selectedsuffix')]))
        self.assertEqual(result['questions'][1]['status'], 'no_lexical_matches')
        self.assertNotIn('sibling', records_by_id(result))
        self.assertNotIn('selectedsuffix', str(result['records']))

    def test_question_validation_is_strict(self):
        run = basic_run()
        bad = [[], [dict(id='a', text=' ')], [dict(id='a', text='x', extra=1)],
               [dict(id='a', text='x'), dict(id='a', text='y')],
               [dict(id='x y', text='x')], [dict(id='a', text='x', source_types=[])],
               [dict(id='a', text='x', source_types=['semantic'])],
               [dict(id='a', text='x', source_types=['action', 'action'])],
               [dict(id='a', text='data:image/png;base64,QUJD')],
               [dict(id=str(i), text='x') for i in range(9)]]
        for questions in bad:
            with self.subTest(questions=questions), self.assertRaises(InputError):
                search(run, dict(anchor={'event_id': 'e7'}, questions=questions))
        with self.assertRaises(InputError):
            search(run, dict(anchor={'event_id': 'e7'}, limit=1,
                             questions=[dict(id='a', text='x'), dict(id='b', text='y')]))
        with self.assertRaises(InputError):
            search(run, dict(anchor={'event_id': 'e7'}, strategy='invented'))


if __name__ == '__main__':
    unittest.main()
