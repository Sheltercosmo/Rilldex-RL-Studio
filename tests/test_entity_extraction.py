import copy
import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker.activity import ActivityClient, analyze
from tracker.entity_extraction import EntityClient, packet, candidate_packet, project, span_candidates, historical_summary
from tracker.jobs import Worker
from tracker.store import Store
from tracker.schema import InputError
from tracker.schema import dumps
from test_tracker import harbor, response_for


class EntityExtractionTests(unittest.TestCase):
    def setUp(self):
        doc=harbor();doc['steps'][1]['message']='Could you please inspect the 🧭 compass?\nLater words.'
        self.run=normalize(doc)[0];a=analyze(self.run)
        self.unit=next(u for u in a['units'] if u['kind']=='model_span')
        def transport(request):
            r=response_for(request)
            for k,a in r['answers'].items():
                value='present' if k=='coordinate' else 'requested' if k=='expression' else 'not_applicable' if k=='revision_target' else 'absent'
                a['probabilities']={choice:float(choice==value) for choice in a['probabilities']}
            return r
        self.base=ActivityClient(transport=transport).evaluate(self.run,self.unit['id'])
        self.activity=analyze(self.run,{self.unit['id']:self.base})

    def test_exact_local_unicode_candidates_and_no_later_or_resolved_references(self):
        p=candidate_packet(self.run,self.activity,self.unit['id']);s=p['state'];e=next(e for e in self.run['events'] if e['id']==self.unit['event_id'])
        self.assertNotIn('candidates',packet(self.run,self.activity,self.unit['id'])['state'])
        self.assertNotIn('Later words',str(p));self.assertNotIn('Fix parser',str(p))
        self.assertEqual(set(p['questions']),{'coordinate__requested_operation','coordinate__addressee_mention','coordinate__request_target'})
        self.assertIn('you',[c['text'] for c in s['candidates']]);self.assertIn('🧭 compass',[c['text'] for c in s['candidates']])
        self.assertIn('inspect the 🧭 compass',[c['text'] for c in s['candidates']])
        for c in s['candidates']:
            self.assertEqual(c['text'],e['text'][c['start']:c['end']])

    def test_structured_arguments_keep_values_and_normalized_pointers(self):
        action=next(e for e in self.run['events'] if e['kind']=='action');u=next(u for u in analyze(self.run)['units'] if u['event_id']==action['id'])
        values,_=span_candidates(u,action);args=[c for c in values if c['kind']=='structured_argument']
        self.assertEqual(args[0]['normalized_event_pointer'],'/arguments/path');self.assertEqual(args[0]['value'],'parser.py')

    def test_raw_argmax_extracts_span_and_upstream_change_invalidates_it(self):
        def transport(request):
            r=response_for(request)
            if request['state']['stage']=='field_presence':return r
            candidate=next(c['id'] for c in request['state']['candidates'] if c['text']=='you')
            for a in r['answers'].values():
                winner=candidate if candidate in a['probabilities'] else next(iter(a['probabilities']))
                n=len(a['probabilities']);a.update(confidence=0,choice='not_present')
                a['probabilities']={k: .2 if k==winner else .8/(n-1) for k in a['probabilities']}
            return r
        client=EntityClient(activity=self.activity,transport=transport);saved=client.evaluate(self.run,self.unit['id'])
        result=project(self.run,self.activity,self.unit['id'],saved)
        self.assertTrue(any(f['status']=='selected_span' and f['selected_candidate']['text']=='you' for r in result['routes'] for f in r['fields']))
        for r in result['routes']:
            for f in r['fields']:
                self.assertEqual(f['content_scope']['text'],self.unit['text'])
        changed=copy.deepcopy(self.activity);next(u for u in changed['units'] if u['id']==self.unit['id'])['observation']['_provenance']['packet_hash']='new-base'
        self.assertEqual(project(self.run,changed,self.unit['id'],saved)['extraction_status'],'stale')
        self.assertEqual(next(u for u in self.activity['units'] if u['id']==self.unit['id'])['activities'],['coordinate'])

    def test_candidate_gaps_absence_route_errors_and_multiplicity_stay_distinct(self):
        for choice in ('not_present','no_suitable_candidate','multiple_spans_needed','unresolved','route_not_applicable'):
            def transport(request):
                r=response_for(request)
                if request['state']['stage']=='field_presence':return r
                for a in r['answers'].values():a['probabilities']={k:float(k==choice) for k in a['probabilities']}
                return r
            saved=EntityClient(activity=self.activity,transport=transport).evaluate(self.run,self.unit['id'])
            result=project(self.run,self.activity,self.unit['id'],saved)
            self.assertTrue(all(f['status']==choice and f['selected_candidate'] is None for r in result['routes'] for f in r['fields']))

    def test_unobserved_base_does_not_launch_extraction(self):
        with self.assertRaises(InputError):packet(self.run,analyze(self.run),self.unit['id'])

    def test_history_decodes_original_field_names_without_reclassifying_them(self):
        saved=EntityClient(activity=self.activity,transport=response_for).evaluate(self.run,self.unit['id'])
        saved['_request']['questions']['old_recipient']=saved['_request']['questions'].pop('coordinate__addressee_mention')
        saved['old_recipient']=saved.pop('coordinate__addressee_mention')
        before=copy.deepcopy(saved)
        summary=historical_summary({'created_at':'prior','result':saved})
        self.assertIn('old_recipient',[f['field'] for f in summary['fields']])
        self.assertNotIn('coordinate__addressee_mention',[f['field'] for f in summary['fields']])
        self.assertEqual(saved,before)

    def test_entity_job_routes_only_classified_units_and_resumes_exact_cache(self):
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/'test.sqlite');store.add([self.run]);store.record_activity(self.run['id'],self.unit['id'],self.base)
            calls=[]
            def transport(p):calls.append(p);return response_for(p)
            w=Worker(store,entities=True,complete_run=True,autostart=False,client=EntityClient(transport=transport))
            try:
                jid=w.submit(self.run['id']);w._process(w._claim());row=next(j for j in w.list() if j['id']==jid)
                self.assertEqual((row['status'],row['total']),('complete',1))
                g=store.get(self.run['id'])['unit_graph'];u=next(u for u in g['nodes'] if u['id']==self.unit['id'])
                self.assertEqual(u['entity_extraction']['extraction_status'],'observed')
                self.assertEqual(g['coverage']['entity_observed_units'],1)
                history=store.get(self.run['id'],raw=True)['entity_observation_history']
                self.assertEqual(len(history),1)
                self.assertEqual(history[0]['result'],u['entity_extraction']['observation'])
                previous=copy.deepcopy(history[0]['result']);previous['_provenance'].update(harness='earlier-extraction',request_hash='earlier-request')
                with store.connect() as c:
                    c.execute('INSERT INTO entity_observations VALUES (?,?,?,?,?,?,?)',(self.run['id'],self.unit['id'],'earlier-extraction',w.client.model,'earlier-packet',dumps(previous),'2000-01-01'))
                current=store.get(self.run['id'])['unit_graph']
                self.assertEqual(current['coverage']['entity_observed_units'],1)
                current_unit=next(u for u in current['nodes'] if u['id']==self.unit['id'])
                self.assertEqual(len(current_unit['entity_extraction']['previous_observations']),1)
                w.submit(self.run['id']);w._process(w._claim());self.assertEqual(len(calls),2)
            finally:w.close()

    def test_implicit_and_absent_fields_do_not_trigger_span_calls(self):
        calls=[]
        def transport(request):
            calls.append(request);r=response_for(request)
            for k,a in r['answers'].items():
                choice='no_local_expression'
                a['probabilities']={v:float(v==choice) for v in a['probabilities']}
            return r
        saved=EntityClient(activity=self.activity,transport=transport).evaluate(self.run,self.unit['id'])
        self.assertEqual(len(calls),1);self.assertIsNone(saved['_span_request'])
        result=project(self.run,self.activity,self.unit['id'],saved)
        self.assertEqual(result['extraction_status'],'observed')
        self.assertEqual([f['status'] for f in result['routes'][0]['fields']],['no_local_expression','no_local_expression','no_local_expression'])

    def test_unstated_reference_is_not_offered_for_operations_or_propositions(self):
        p=packet(self.run,self.activity,self.unit['id'])
        self.assertNotIn('reference_unstated',p['questions']['coordinate__addressee_mention']['criteria'])
        self.assertNotIn('reference_unstated',p['questions']['coordinate__requested_operation']['criteria'])

    def test_low_probability_presence_winner_still_routes_to_span_selection(self):
        calls=[]
        def transport(request):
            calls.append(request['state']['stage']);r=response_for(request)
            if request['state']['stage']=='field_presence':
                for a in r['answers'].values():
                    n=len(a['probabilities']);a.update(confidence=0,choice='not_present')
                    a['probabilities']={v:.31 if v=='local_expression' else .69/(n-1) for v in a['probabilities']}
            return r
        saved=EntityClient(activity=self.activity,transport=transport).evaluate(self.run,self.unit['id'])
        self.assertEqual(calls,['field_presence','local_field_selection'])
        self.assertTrue(all(a['value']=='local_expression' for a in saved['_availability'].values()))

    def test_failed_second_stage_resumes_saved_presence_without_repeating_it(self):
        with tempfile.TemporaryDirectory() as t:
            store=Store(Path(t)/'test.sqlite');store.add([self.run]);store.record_activity(self.run['id'],self.unit['id'],self.base)
            calls=[]
            def transport(p):
                calls.append(p['state']['stage'])
                if len(calls)==2:raise RuntimeError('selection interrupted')
                return response_for(p)
            w=Worker(store,entities=True,complete_run=True,autostart=False,client=EntityClient(transport=transport))
            try:
                w.submit(self.run['id']);w._process(w._claim())
                u=next(u for u in store.get(self.run['id'])['unit_graph']['nodes'] if u['id']==self.unit['id'])
                self.assertEqual(u['entity_extraction']['extraction_status'],'partial')
                presence=copy.deepcopy(u['entity_extraction']['observation']['_availability'])
                w.submit(self.run['id']);w._process(w._claim())
                b=store.get(self.run['id'],raw=True);self.assertEqual(b['unit_graph']['coverage']['entity_observed_units'],1)
                self.assertEqual(len(b['entity_observation_history']),1)
                self.assertEqual(b['entity_observation_history'][0]['result']['_availability'],presence)
                self.assertEqual(calls,['field_presence','local_field_selection','local_field_selection'])
            finally:w.close()

    def test_presence_span_disagreement_retains_both_raw_winners(self):
        def transport(request):
            r=response_for(request)
            if request['state']['stage']=='local_field_selection':
                for a in r['answers'].values():a['probabilities']={v:float(v=='not_present') for v in a['probabilities']}
            return r
        saved=EntityClient(activity=self.activity,transport=transport).evaluate(self.run,self.unit['id'])
        result=project(self.run,self.activity,self.unit['id'],saved)
        for f in result['routes'][0]['fields']:
            self.assertEqual(f['presence_decision'],'local_expression');self.assertEqual(f['raw_choice'],'not_present');self.assertTrue(f['review_note'])


if __name__=='__main__':unittest.main()
