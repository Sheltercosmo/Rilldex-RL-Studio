"""Exact query phrases must not be reduced to unrelated individual words."""
from copy import deepcopy
import unittest

from tracker.source_evidence import search
from test_source_evidence import chat


class LiteralRetrievalTests(unittest.TestCase):
    def find(self, messages, text, **options):
        run=chat([dict(role='assistant',content=m) for m in messages]+[
            dict(role='assistant',content='Inspect prior evidence.')])
        result=search(run,dict(anchor={'event_id':run['events'][-1]['id']},text=text,limit=1,**options))
        return run,result

    def test_negated_phrase_beats_short_positive_keyword_match(self):
        run,result=self.find(['installed', 'Setup output: '+'background '*60+'pdflatex is not installed.'],
                             '"not installed"')
        self.assertEqual(result['matches'][0]['event_id'],run['events'][1]['id'])
        self.assertEqual(result['matches'][0]['match_basis'],'source_literal')
        self.assertEqual(result['questions'][0]['literal_phrases'],['not installed'])

    def test_literal_identifier_preserves_punctuation_and_word_boundaries(self):
        run,result=self.find(['reward scored py', 'reward_score.pyc reward_score.py.bak',
                             'Read /project/reward_score.py before evaluating.'],'`reward_score.py`')
        self.assertEqual(result['matches'][0]['event_id'],run['events'][2]['id'])
        literal=result['matches'][0]['literal_matches'][0]
        self.assertEqual(run['events'][2]['text'][literal['start']:literal['end']],literal['text'])

    def test_all_stopwords_and_unicode_offsets(self):
        run,result=self.find(['no', '☃ Straße: NOT NOW, please.'],'“not now”')
        self.assertEqual(result['questions'][0]['query_terms'],['now'])
        self.assertEqual(result['matches'][0]['event_id'],run['events'][1]['id'])
        run,result=self.find(['it', 'The instruction was: not now, not here.'],'"not"')
        self.assertEqual(result['questions'][0]['query_terms'],[])
        self.assertEqual(result['matches'][0]['match_basis'],'source_literal')

    def test_absent_phrase_keeps_loose_candidates_without_exact_claim(self):
        _,result=self.find(['installed on the host'],'"not installed"')
        self.assertEqual(result['matches'][0]['match_basis'],'source_text')
        self.assertNotIn('literal_matches',result['matches'][0])

    def test_default_anchor_quotes_do_not_silently_become_user_search_constraints(self):
        run=chat([dict(role='assistant',content='alpha beta'),dict(role='assistant',content='alpha "beta"')])
        result=search(run,dict(anchor={'event_id':run['events'][-1]['id']}))
        self.assertEqual(result['questions'][0]['literal_phrases'],[])
        self.assertTrue(all(m['match_basis']=='source_text' for m in result['matches']))

    def test_long_literal_respects_budget_and_paginates_without_skipping(self):
        literal=' '.join('word'+str(i) for i in range(400))
        run,result=self.find([literal, 'unrelated note'], '"'+literal+'"',max_chars=2000)
        self.assertEqual(len(result['matches']),1)
        self.assertLessEqual(result['coverage']['source_text_chars'],2000)
        self.assertEqual(result['questions'][0]['status'],'candidates_omitted')
        self.assertEqual(result['questions'][0]['literal_matched_events'],1)
        self.assertEqual(result['questions'][0]['retained_literal_event_ids'],[])
        self.assertTrue(result['coverage']['deferred'])
        self.assertIsNone(result['pagination']['next_cursor'])
        for record in result['records']:
            for f in record['fragments']:
                self.assertEqual(f['text'],run['events'][0]['text'][f['start']:f['end']])

    def test_phrase_matching_obeys_scope_cutoff_and_excludes_media(self):
        run,result=self.find(['safe text'],'`secretneedle`')
        before=deepcopy(result)
        template=run['events'][0]
        for eid,updates in [('foreign',dict(context_id='another',index=0)),
                            ('future',dict(index=999)),('media',dict(index=.5,text='data:image/png;base64,secretneedle'))]:
            run['events'].append(dict(template,id=eid,text='secretneedle',**{k:v for k,v in updates.items() if k!='text'}))
            if 'text' in updates:run['events'][-1]['text']=updates['text']
        after=search(run,before['query'])
        self.assertEqual(after['matches'],before['matches'])
        self.assertEqual(after['records'],before['records'])

    def test_literal_priority_survives_source_type_diversity(self):
        messages=[dict(role='assistant',content='needle only') for _ in range(5)]+[
            dict(role='assistant',content='exact needle phrase') for _ in range(3)]+[
            dict(role='assistant',content='Inspect.')]
        run=chat(messages)
        result=search(run,dict(anchor={'event_id':run['events'][-1]['id']},text='"exact needle phrase"',limit=3))
        self.assertEqual(len(result['matches']),3)
        self.assertTrue(all(m['match_basis']=='source_literal' for m in result['matches']))


if __name__=='__main__': unittest.main()
