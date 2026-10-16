import copy
import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker.activity import analyze as activity, ActivityClient
from tracker.unit_graph import units, packet, build, RelationClient
from tracker.jobs import Worker
from tracker.store import Store
from test_tracker import harbor, response_for


class UnitGraphTests(unittest.TestCase):
    def setUp(self):
        self.run=normalize(harbor())[0]

    def test_every_source_record_and_exact_span_is_preserved(self):
        graph=build(self.run,activity(self.run));events={e['id']:e for e in self.run['events']}
        self.assertEqual({u['event_id'] for u in graph['nodes']},set(events))
        for u in graph['nodes']:
            self.assertEqual(u['text'],events[u['event_id']]['text'][u['start']:u['end']])
        for m in graph['mentions']:
            if 'text' in m:self.assertEqual(m['text'],events[m['event_id']]['text'][m['start']:m['end']])
        self.assertFalse(any(e['basis']=='jev' for e in graph['edges']))

    def test_result_links_follow_call_ids_not_result_order(self):
        graph=build(self.run,activity(self.run));by={u['id']:u for u in graph['nodes']}
        linked=[(by[e['source']]['text'],by[e['target']]['text']) for e in graph['edges'] if e['type']=='result_of']
        self.assertEqual(len(linked),3)
        for call,result in linked:self.assertEqual('parser.py' in call,'parser content'==result)

    def test_non_programming_mentions_have_exact_sources_without_inferred_identity(self):
        run=copy.deepcopy(self.run)
        run['events'][0]['text']='The SIM card is loose.'
        run['events'][1]['text']='Please reseat the SIM card.'
        graph=build(run,activity(run))
        phrase=next(e for e in graph['entities'] if e['type']=='repeated_phrase' and e['label']=='sim card')
        self.assertEqual(phrase['basis'],'literal_casefold_match_not_coreference')
        mentions=[m for m in graph['mentions'] if m['entity_id']==phrase['id']]
        self.assertTrue(all(m['text']=='SIM card' for m in mentions))
        self.assertFalse(any(e['basis']=='jev' for e in graph['edges']))

    def test_future_external_and_other_trajectory_records_are_not_candidates(self):
        run=copy.deepcopy(self.run);subject=next(u for u in units(run) if u['eligible'])
        current=next(e for e in run['events'] if e['id']==subject['event_id'])
        current['text']+='\n\nFUTURE_SECRET';run['events'][0]['text']='CURRENT_TASK'
        for i,(kind,trajectory,text) in enumerate([('external_feedback','main','EXTERNAL_SECRET'),('instruction','elsewhere','OTHER_SECRET')]):
            run['events'].append({'id':'extra'+str(i),'index':-1,'kind':kind,'trajectory_id':trajectory,'actor':'user','text':text,'source_pointer':'/extra'})
        subject=next(u for u in units(run) if u['event_id']==current['id'] and u['eligible'] and 'FUTURE_SECRET' not in u['text'])
        p=packet(run,subject['id']);text=str(p)
        self.assertNotIn('FUTURE_SECRET',text);self.assertNotIn('EXTERNAL_SECRET',text);self.assertNotIn('OTHER_SECRET',text)

    def test_independent_low_probability_winners_and_multiple_links_remain(self):
        subject=[u for u in units(self.run) if u['eligible']][-1]
        def transport(request):
            r=response_for(request)
            for answer in r['answers'].values():answer.update(probabilities={'present':.34,'absent':.33,'unresolved':.33},choice='absent',confidence=0)
            return r
        client=RelationClient(transport=transport);result=client.evaluate(self.run,subject['id'])
        graph=build(self.run,activity(self.run),{subject['id']:result})
        edges=[e for e in graph['edges'] if e['basis']=='jev']
        self.assertEqual(len(edges),len(result['_request']['questions']))
        self.assertTrue(all(e['raw_choice']=='present' for e in edges))
        changed=copy.deepcopy(result);changed['_provenance']['packet_hash']='changed'
        stale=build(self.run,activity(self.run),{subject['id']:changed})
        self.assertFalse(any(e['basis']=='jev' for e in stale['edges']))

    def test_whole_rollout_jobs_finish_and_reuse_saved_units(self):
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/'test.sqlite');store.add([self.run]);calls=[]
            def transport(p):calls.append(p);return response_for(p)
            for mode,client in [('activity',ActivityClient(transport=transport)),('relations',RelationClient(transport=transport))]:
                worker=Worker(store,client=client,max_actions=1,complete_run=True,autostart=False,**{mode:True})
                try:
                    jid=worker.submit(self.run['id']);worker._process(worker._claim())
                    row=next(r for r in worker.list() if r['id']==jid)
                    self.assertEqual(row['status'],'complete');self.assertGreater(row['progress'],1)
                    count=len(calls);worker.submit(self.run['id']);worker._process(worker._claim());self.assertEqual(len(calls),count)
                finally:worker.close()
            graph=store.get(self.run['id'])['unit_graph'];c=graph['coverage']
            self.assertEqual(c['activity_observed'],c['eligible_agent_units']);self.assertEqual(c['relation_observed'],c['eligible_agent_units'])


if __name__=='__main__':unittest.main()
