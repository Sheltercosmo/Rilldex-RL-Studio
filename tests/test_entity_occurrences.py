import copy
import json
import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker.activity import ActivityClient, analyze
from tracker.entity_extraction import EntityClient
from tracker.entity_occurrences import OccurrenceClient, eligible_fields, selections, project_graph
from tracker.reference_resolution import ReferenceClient, fields, subjects
from tracker.jobs import Worker
from tracker.store import Store
from tracker.schema import InputError, dumps
from test_tracker import response_for


def base_transport(req):
    r=response_for(req)
    for k,a in r['answers'].items():
        v='present' if k=='plan' else 'intended' if k=='expression' else 'not_applicable' if k=='revision_target' else 'absent'
        a['probabilities']={q:float(q==v) for q in a['probabilities']}
    return r


def local_transport(req):
    r=response_for(req)
    if req['state']['stage']!='field_presence':
        for k,a in r['answers'].items():
            v='multiple_spans_needed' if k.endswith('intended_target') else 'not_present'
            a['probabilities']={q:float(q==v) for q in a['probabilities']}
    return r


def occurrence_transport(req):
    if req['state'].get('stage')=='occurrence_boundaries':return response_for(req)
    r=response_for(req);cs={c['id']:c for c in req['state']['candidates']}
    for key,a in r['answers'].items():
        b=req['state']['question_bindings'][key]
        v='all_local_mentions_covered' if b['kind']=='coverage' else 'role_mention' if cs[b['candidate_id']]['text'] in {'report.csv','it'} else 'wrong_role'
        # The selected probability, not provider choice or confidence, controls.
        a.update(choice='unresolved',confidence=0,probabilities={q:float(q==v) for q in a['probabilities']})
    return r


def prepared_store(path):
    run=normalize({'schema_version':'ATIF-v1.7','session_id':'occurrence-test','agent':{'name':'fixture','version':'1'},
        'steps':[{'step_id':1,'source':'agent','message':'I will create a file called `report.csv` and then inspect it.'},
                 {'step_id':2,'source':'agent','message':'I will inspect `report.csv`.'}]})[0]
    store=Store(path);store.add([run])
    for u in analyze(run)['units']:
        if u['eligible']:store.record_activity(run['id'],u['id'],ActivityClient(transport=base_transport).evaluate(run,u['id']))
    w=Worker(store,entities=True,autostart=False,client=EntityClient(transport=local_transport))
    w.submit(run['id']);w._process(w._claim());w.close()
    return store,run


class OccurrenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store,self.run=prepared_store(Path(self.tmp.name)/'s.sqlite')
        self.bundle=self.store.get(self.run['id']);self.nodes=self.bundle['unit_graph']['nodes']
        self.n=next(n for n in self.nodes if eligible_fields(n));self.uid=self.n['id']

    def test_local_request_preserves_exact_candidates_and_excludes_later_text_and_old_winners(self):
        client=OccurrenceClient(nodes=self.nodes);r=client.request(self.run,self.uid)
        self.assertNotIn('_span_request',r['state']);self.assertNotIn('multiple_spans_needed',str(r['state'].get('upstream')))
        self.assertEqual(set(r['state']['fields']),{'plan__intended_target'})
        e=next(e for e in self.run['events'] if e['id']==self.n['event_id'])
        for c in r['state']['candidates']:self.assertEqual(e['text'][c['start']:c['end']],c['text'])
        self.assertEqual(r['state']['subject']['text'],self.n['text'])
        self.n['entity_extraction']['extraction_status']='partial'
        with self.assertRaises(InputError):client.request(self.run,self.uid)

    def test_multiple_occurrences_keep_raw_argmax_and_do_not_merge_identity(self):
        saved=OccurrenceClient(nodes=self.nodes,transport=occurrence_transport).evaluate(self.run,self.uid)
        groups=selections(saved);self.assertEqual(len(groups),1)
        self.assertEqual([d['candidate']['text'] for d in groups[0]['selected_occurrences']],['report.csv','it'])
        self.assertEqual(len(groups[0]['usable_occurrences']),2)
        self.assertTrue(all(d['decision']['confidence']==0 for d in groups[0]['selected_occurrences']))
        self.assertNotIn('entities',saved)

    def test_overlapping_positive_boundaries_are_retained_but_not_reference_inputs(self):
        def transport(req):
            r=occurrence_transport(req)
            if req['state'].get('stage')=='occurrence_boundaries':
                for a in r['answers'].values():a['probabilities']={k:float(k=='unresolved') for k in a['probabilities']}
            else:
                cs=req['state']['candidates'];name=next(c for c in cs if c['text']=='report.csv')
                long=next(c for c in cs if c['id']!=name['id'] and c['start']<=name['start']<c['end'])
                a=r['answers']['plan__intended_target__'+long['id']];a['probabilities']={k:float(k=='role_mention') for k in a['probabilities']}
            return r
        saved=OccurrenceClient(nodes=self.nodes,transport=transport).evaluate(self.run,self.uid)
        project_graph(self.run,self.bundle['unit_graph'],[{'event_id':self.uid,'result':saved}])
        n=next(n for n in self.bundle['unit_graph']['nodes'] if n['id']==self.uid)
        self.assertEqual(len(n['entity_occurrences']['fields'][0]['positive_candidates']),3)
        self.assertEqual(len(n['entity_occurrences']['fields'][0]['selected_occurrences']),1)
        self.assertEqual([f['selected_candidate']['text'] for f in subjects(n).values()],['it'])
        self.assertEqual(n['entity_extraction']['observation']['plan__intended_target']['value'],'multiple_spans_needed')

    def test_coverage_conflict_keeps_winners_without_silently_using_them(self):
        saved=OccurrenceClient(nodes=self.nodes,transport=occurrence_transport).evaluate(self.run,self.uid)
        saved['plan__intended_target__coverage']['value']='no_local_mention'
        group=selections(saved)[0]
        self.assertEqual(len(group['selected_occurrences']),2);self.assertEqual(group['usable_occurrences'],[])

    def test_boundary_cache_survives_canonical_storage_with_multiple_roles(self):
        extraction=self.n['entity_extraction'];plan=next(r for r in extraction['routes'] if r['activity']=='plan')
        target=copy.deepcopy(next(f for f in plan['fields'] if f['role']=='intended_target'));target['role']='request_target'
        extraction['routes'].append({'activity':'coordinate','fields':[target]})
        qs=extraction['observation']['_span_request']['questions'];qs['coordinate__request_target']=copy.deepcopy(qs['plan__intended_target'])
        def transport(req):
            r=occurrence_transport(req)
            if req['state'].get('stage')!='occurrence_boundaries':
                cs=req['state']['candidates'];name=next(c for c in cs if c['text']=='report.csv')
                extra=next(c for c in cs if c['id']!=name['id'] and c['start']<=name['start']<c['end'])
                for field in req['state']['fields']:
                    a=r['answers'][field+'__'+extra['id']];a['probabilities']={k:float(k=='role_mention') for k in a['probabilities']}
            return r
        client=OccurrenceClient(nodes=self.nodes,transport=transport);saved=client.evaluate(self.run,self.uid)
        self.assertEqual(len(saved['_boundary_request']['state']['groups']),2)
        restored=json.loads(dumps(saved));self.assertTrue(client.cache_matches(restored,self.run,self.uid))

    def test_upstream_changes_invalidate_occurrences_and_later_references(self):
        client=OccurrenceClient(nodes=self.nodes,transport=occurrence_transport);saved=client.evaluate(self.run,self.uid)
        self.assertTrue(client.cache_matches(saved,self.run,self.uid))
        self.n['entity_extraction']['observation']['_provenance']['span_request_hash']='changed'
        self.assertFalse(client.cache_matches(saved,self.run,self.uid))
        project_graph(self.run,self.bundle['unit_graph'],[{'event_id':self.uid,'result':saved}])
        self.assertEqual(self.n['entity_occurrences']['status'],'stale');self.assertFalse(subjects(self.n))

    def test_worker_persistence_resume_export_and_reference_consumption(self):
        before=copy.deepcopy(self.store.get(self.run['id'],raw=True)['entity_observation_history']);calls=[]
        def transport(req):calls.append(req);return occurrence_transport(req)
        w=Worker(self.store,occurrences=True,autostart=False,client=OccurrenceClient(transport=transport))
        self.addCleanup(w.close);w.submit(self.run['id']);w._process(w._claim())
        b=self.store.get(self.run['id'],raw=True)
        self.assertEqual(w.list()[0]['status'],'complete');self.assertEqual(len(b['occurrence_observation_history']),2)
        self.assertEqual(b['entity_observation_history'],before)
        ns=[n for n in b['unit_graph']['nodes'] if eligible_fields(n)]
        self.assertEqual(len(subjects(ns[0])),2);self.assertEqual(len(subjects(ns[1])),1)
        req=ReferenceClient(nodes=b['unit_graph']['nodes']).request(self.run,ns[1]['id'])
        q=next(iter(req['state']['fields'].values()))
        self.assertEqual({c['selection']['text'] for c in q['candidates']},{'report.csv','it'})
        self.assertTrue(all(c['upstream']['harness']=='category-mention-occurrences/0.2' for c in q['candidates']))
        w.submit(self.run['id']);w._process(w._claim());self.assertEqual(len(calls),2)

    def test_failed_boundary_call_resumes_saved_membership_in_persistent_worker(self):
        calls=[]
        def transport(req):
            calls.append(req)
            if len(calls)==2:raise InputError('simulated boundary failure')
            r=occurrence_transport(req)
            if req['state'].get('stage')!='occurrence_boundaries' and req['state']['subject']['id']==self.uid:
                cs=req['state']['candidates'];name=next(c for c in cs if c['text']=='report.csv')
                extra=next(c for c in cs if c['id']!=name['id'] and c['start']<=name['start']<c['end'])
                a=r['answers']['plan__intended_target__'+extra['id']];a['probabilities']={k:float(k=='role_mention') for k in a['probabilities']}
            return r
        w=Worker(self.store,occurrences=True,autostart=False,client=OccurrenceClient(transport=transport));self.addCleanup(w.close)
        w.submit(self.run['id']);w._process(w._claim())
        b=self.store.get(self.run['id'],raw=True);saved=b['occurrence_observation_history'][0]['result']
        self.assertEqual(saved['_provenance']['completion'],'awaiting_boundary')
        node=next(n for n in b['unit_graph']['nodes'] if n['id']==self.uid)
        self.assertEqual(node['entity_occurrences']['status'],'partial');self.assertFalse(subjects(node))
        first=copy.deepcopy(saved['_membership'])
        w.submit(self.run['id']);w._process(w._claim());b=self.store.get(self.run['id'],raw=True)
        self.assertEqual(w.list()[0]['status'],'complete');self.assertEqual(len(calls),4)
        record=next(r for r in b['occurrence_observation_history'] if r['event_id']==self.uid)
        self.assertEqual(record['result']['_membership'],first);self.assertEqual(record['result']['_provenance']['completion'],'complete')
        self.assertEqual(len(b['occurrence_observation_history']),2)


if __name__=='__main__':unittest.main()
