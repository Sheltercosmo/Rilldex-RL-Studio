import copy
import tempfile
import unittest
from pathlib import Path

from tracker.adapters import normalize
from tracker.activity import ActivityClient, analyze
from tracker.entity_extraction import EntityClient
from tracker.reference_resolution import ReferenceClient, packet, subjects, candidates, project_graph, relation_request
from tracker.jobs import Worker
from tracker.store import Store
from tracker.schema import InputError, digest
from test_tracker import harbor, response_for


def fixture():
    """Authored source/field projections for mechanism tests, not semantic labels."""
    rows=[('instruction','user','Inspect the compass.'),('message','agent','The compass points north.'),
          ('feedback','environment','Compass result: north.'),('message','agent','Could you inspect the compass?'),
          ('message','agent','Future evidence must stay out.')]
    events=[];nodes=[]
    for i,(kind,actor,text) in enumerate(rows):
        e={'id':f'e{i+1}','index':i,'text':text,'kind':kind,'actor':actor,'trajectory_id':'main','source_pointer':f'/messages/{i}'};events.append(e)
        nodes.append({'id':f'u{i+1}','event_id':e['id'],'event_index':i,'text':text,'source_event_kind':kind,'actor':actor,'trajectory_id':'main',
            'source_pointer':e['source_pointer'],'start':0,'end':len(text),'entity_extraction':{'routes':[],'extraction_status':'not_applicable'}})
    add_field(nodes[1],'inspect__information_target','compass')
    add_field(nodes[1],'report__reported_content',nodes[1]['text'])
    add_field(nodes[3],'coordinate__addressee_mention','you')
    add_field(nodes[3],'coordinate__request_target','compass')
    return {'id':'fixture','events':events},nodes


def add_field(n,key,text):
    activity,role=key.split('__');a=n['text'].index(text);b=a+len(text)
    c={'id':'x'+digest([n['id'],a,b])[:8],'text':text,'kind':'source_span','event_id':n['event_id'],'source_pointer':n['source_pointer'],'start':a,'end':b}
    f={'role':role,'status':'selected_span','raw_choice':c['id'],'selected_candidate':c,'expression_form':{'value':'asserted'}}
    routes=n['entity_extraction']['routes'];r=next((r for r in routes if r['activity']==activity),None)
    if not r:r={'activity':activity,'fields':[]};routes.append(r)
    r['fields'].append(f)
    n['entity_extraction'].update(extraction_status='observed',observation={'_provenance':{
        'harness':'authored-local-fields','model':'jev-1.13.0','packet_hash':'packet-'+n['id'],'request_hash':'request-'+n['id'],'selection_policy':'argmax/1'}})


class ReferenceResolutionTests(unittest.TestCase):
    def test_planned_target_becomes_anchor_only_after_local_selection(self):
        run,nodes=fixture()
        nodes[1]['entity_extraction']['routes']=[]
        add_field(nodes[1],'plan__intended_target','compass')
        f=nodes[1]['entity_extraction']['routes'][0]['fields'][0]
        f['expression_form']={'value':'intended'}
        req=packet(run,nodes,'u4')
        anchors=req['state']['fields']['coordinate__request_target']['candidates']
        self.assertEqual(len(anchors),1)
        self.assertEqual(anchors[0]['field'],'plan__intended_target')
        self.assertEqual(anchors[0]['expression_form'],{'value':'intended'})
        self.assertEqual(anchors[0]['relation'],'entity_anchor')
        f['selected_candidate']=None
        self.assertEqual(packet(run,nodes,'u4')['state']['fields']['coordinate__request_target']['candidates'],[])

    def test_subjects_require_completed_selected_fields_and_preserve_conflicts(self):
        run,nodes=fixture();n=nodes[3]
        n['entity_extraction']['routes'][0]['fields'][0]['review_note']='stage disagreement'
        self.assertEqual(set(subjects(n)),{'coordinate__request_target'})
        n['entity_extraction']['extraction_status']='partial'
        with self.assertRaises(InputError):packet(run,nodes,n['id'])

    def test_reference_families_have_distinct_anchors_and_no_future_context(self):
        run,nodes=fixture();p=packet(run,nodes,'u4')
        self.assertNotIn('Future evidence',str(p))
        fs=p['state']['fields']
        self.assertEqual({c['kind'] for c in fs['coordinate__addressee_mention']['candidates']},{'recorded_participant'})
        self.assertEqual({c['relation'] for c in fs['coordinate__request_target']['candidates']},{'entity_anchor'})
        self.assertEqual(fs['coordinate__request_target']['candidates'][0]['selection']['text'],'compass')
        add_field(nodes[3],'assess__feedback_referent','compass')
        p=packet(run,nodes,'u4');relations={c['relation'] for c in p['state']['fields']['assess__feedback_referent']['candidates']}
        self.assertEqual(relations,{'content_anchor','feedback_anchor'})

    def test_hidden_external_copied_and_cross_trajectory_records_are_not_evidence(self):
        for mutation in ({'kind':'external_feedback'},{'agent_visibility':'not_established'},{'copied_context':True},{'trajectory_id':'child'}):
            run,nodes=fixture();add_field(nodes[3],'assess__feedback_referent','compass')
            run['events'][2].update(mutation)
            if 'trajectory_id' in mutation:nodes[2]['trajectory_id']='child'
            p=packet(run,nodes,'u4')
            ids=[c['unit_id'] for c in p['state']['fields']['assess__feedback_referent']['candidates']]
            self.assertNotIn('u3',ids)
            self.assertNotIn('u3',[n['id'] for n in p['state']['prior_context']])

    def test_same_event_later_words_are_excluded_and_exact_offsets_retained(self):
        run,nodes=fixture();subject=nodes[3]
        later=copy.deepcopy(nodes[1]);later.update(id='later',event_id=subject['event_id'],event_index=subject['event_index'],start=subject['end']+1,end=subject['end']+20,text='Later sentinel')
        nodes.append(later);p=packet(run,nodes,'u4')
        self.assertNotIn('Later sentinel',str(p))
        for f in p['state']['fields'].values():
            c=f['subject_field']['selection'];e=next(e for e in run['events'] if e['id']==c['event_id'])
            self.assertEqual(e['text'][c['start']:c['end']],c['text'])

    def test_retrieval_omissions_are_explicit_and_not_negative_answers(self):
        run,nodes=fixture();f=subjects(nodes[3])['coordinate__addressee_mention']
        offered,coverage=candidates(run,nodes,nodes[3],'coordinate__addressee_mention',f,limit=1)
        self.assertEqual((len(offered),coverage['eligible'],len(coverage['omitted_candidate_ids'])),(1,2,1))
        p=packet(run,nodes,'u4');self.assertIn('no_suitable_candidate',p['questions']['coordinate__addressee_mention']['criteria'])

    def test_argmax_ignores_confidence_and_projection_never_merges_entities(self):
        run,nodes=fixture();before=copy.deepcopy(nodes)
        def transport(req):
            r=response_for(req)
            for k,a in r['answers'].items():
                winner=next(iter(req['questions'][k]['criteria']));count=len(a['probabilities'])
                a.update(confidence=0,choice='unresolved',probabilities={v:.3 if v==winner else .7/(count-1) for v in a['probabilities']})
            return r
        client=ReferenceClient(nodes=nodes,transport=transport);saved=client.evaluate(run,'u4')
        self.assertTrue(all(a['value']!='unresolved' for k,a in saved.items() if not k.startswith('_')))
        graph={'nodes':nodes,'pipeline':{},'coverage':{},'entities':[{'id':'original'}],'edges':[]}
        project_graph(run,graph,[{'event_id':'u4','result':saved}])
        self.assertEqual(graph['entities'],[{'id':'original'}]);self.assertEqual(graph['edges'],[])
        self.assertEqual(len(graph['reference_links']),2)
        self.assertEqual([n['entity_extraction'] for n in nodes],[n['entity_extraction'] for n in before])

    def test_upstream_candidate_change_invalidates_cache_but_future_does_not(self):
        run,nodes=fixture();client=ReferenceClient(nodes=nodes,transport=response_for);saved=client.evaluate(run,'u4')
        self.assertTrue(client.cache_matches(saved,run,'u4'))
        nodes[4]['text']='Different future';self.assertTrue(client.cache_matches(saved,run,'u4'))
        nodes[1]['entity_extraction']['observation']['_provenance']['request_hash']='changed-extraction'
        self.assertFalse(client.cache_matches(saved,run,'u4'))

    def test_explicit_alternatives_are_retained_without_reference_links(self):
        run,nodes=fixture()
        for value in ['unresolved','no_earlier_match','multiple_referents','no_suitable_candidate','local_extraction_problem']:
            def transport(req):
                r=response_for(req)
                for a in r['answers'].values():a['probabilities']={v:float(v==value) for v in a['probabilities']}
                return r
            saved=ReferenceClient(nodes=nodes,transport=transport).evaluate(run,'u4')
            graph={'nodes':copy.deepcopy(nodes),'pipeline':{},'coverage':{}}
            project_graph(run,graph,[{'event_id':'u4','result':saved}])
            self.assertEqual(graph['reference_links'],[])
            self.assertEqual({f['status'] for f in graph['nodes'][3]['reference_resolution']['fields']},{value})

    def test_worker_persists_separate_history_and_resumes_without_provider_calls(self):
        with tempfile.TemporaryDirectory() as t:
            doc=harbor();doc['steps'][1]['message']='Could you inspect the compass?'
            run=normalize(doc)[0];store=Store(Path(t)/'test.sqlite');store.add([run]);unit=next(u for u in analyze(run)['units'] if u['kind']=='model_span')
            def base_transport(req):
                r=response_for(req)
                for k,a in r['answers'].items():
                    v='present' if k=='coordinate' else 'requested' if k=='expression' else 'not_applicable' if k=='revision_target' else 'absent'
                    a['probabilities']={q:float(q==v) for q in a['probabilities']}
                return r
            store.record_activity(run['id'],unit['id'],ActivityClient(transport=base_transport).evaluate(run,unit['id']))
            def local_transport(req):
                r=response_for(req)
                if req['state']['stage']=='field_presence':return r
                for k,a in r['answers'].items():
                    text='you' if k.endswith('addressee_mention') else 'the compass' if k.endswith('request_target') else 'inspect the compass'
                    v=next(iter(a['probabilities'])) if k.endswith('requested_operation') else next(c['id'] for c in req['state']['candidates'] if c['text']==text)
                    a['probabilities']={q:float(q==v) for q in a['probabilities']}
                return r
            w=Worker(store,entities=True,autostart=False,client=EntityClient(transport=local_transport))
            w.submit(run['id']);w._process(w._claim())
            self.assertEqual(w.list()[0]['status'],'complete')
            before=store.get(run['id'],raw=True)['entity_observation_history'];self.assertEqual(len(before),1)
            calls=[]
            def transport(req):
                calls.append(req)
                if len(calls)==2:raise InputError('simulated relation-stage failure')
                return response_for(req)
            r=Worker(store,references=True,complete_run=True,autostart=False,client=ReferenceClient(transport=transport))
            jid=r.submit(run['id']);r._process(r._claim());self.assertEqual(next(j for j in r.list() if j['id']==jid)['status'],'failed')
            partial=store.get(run['id'],raw=True)['reference_observation_history'];self.assertEqual(len(partial),1)
            self.assertEqual(partial[0]['result']['_provenance']['completion'],'awaiting_relationship')
            jid=r.submit(run['id']);r._process(r._claim());self.assertEqual(next(j for j in r.list() if j['id']==jid)['status'],'complete')
            b=store.get(run['id'],raw=True);self.assertEqual(len(b['reference_observation_history']),1)
            self.assertEqual(b['reference_observation_history'][0]['result']['_provenance']['completion'],'complete')
            self.assertEqual(calls[1],calls[2])
            self.assertEqual(b['entity_observation_history'],before)
            r.submit(run['id']);r._process(r._claim());self.assertEqual(len(calls),3)
            self.assertEqual(b['unit_graph']['coverage']['reference_observed_units'],1)
            r.close();w.close()

    def test_second_stage_uses_only_selected_targets_and_preserves_rejection(self):
        run,nodes=fixture();calls=[]
        def transport(req):
            calls.append(req);r=response_for(req)
            if req['state']['stage']=='relationship_classification':
                for a in r['answers'].values():a['probabilities']={k:float(k=='unrelated_or_different') for k in a['probabilities']}
            return r
        client=ReferenceClient(nodes=nodes,transport=transport);saved=client.evaluate(run,'u4')
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1],relation_request(calls[0],saved['_target_choices']))
        for k,pair in calls[1]['state']['pairs'].items():self.assertEqual(pair['earlier']['id'],saved['_target_choices'][k]['value'])
        graph={'nodes':nodes,'pipeline':{},'coverage':{}};project_graph(run,graph,[{'event_id':'u4','result':saved}])
        self.assertEqual({e['type'] for e in graph['reference_links']},{'unrelated_or_different'})
        for f in nodes[3]['reference_resolution']['fields']:
            self.assertEqual(f['raw_choice'],saved['_target_choices'][f['field']]['value'])
            self.assertEqual(f['relationship_status'],'unrelated_or_different')

    def test_relation_failure_resumes_exact_first_stage_and_partial_is_not_complete(self):
        run,nodes=fixture();calls=[];checkpoints=[]
        def transport(req):
            calls.append(req)
            if len(calls)==2:raise InputError('simulated second-stage failure')
            return response_for(req)
        client=ReferenceClient(nodes=nodes,transport=transport)
        with self.assertRaises(InputError):client.evaluate(run,'u4',checkpoint=lambda s:checkpoints.append(copy.deepcopy(s)) or True)
        partial=checkpoints[0];self.assertEqual(partial['_provenance']['completion'],'awaiting_relationship')
        self.assertTrue(client.targets_match(partial,run,'u4'));self.assertFalse(client.cache_matches(partial,run,'u4'))
        graph={'nodes':copy.deepcopy(nodes),'pipeline':{},'coverage':{}};project_graph(run,graph,[{'event_id':'u4','result':partial}])
        self.assertEqual(graph['coverage']['reference_observed_units'],0);self.assertEqual(graph['nodes'][3]['reference_resolution']['status'],'partial')
        saved=client.evaluate(run,'u4',resume=partial)
        self.assertEqual(len(calls),3);self.assertEqual(calls[1],calls[2]);self.assertEqual(saved['_target_choices'],partial['_target_choices'])
        self.assertTrue(client.cache_matches(saved,run,'u4'))

    def test_no_target_winner_does_not_invent_relationship_request(self):
        run,nodes=fixture();calls=[]
        def transport(req):
            calls.append(req);r=response_for(req)
            for a in r['answers'].values():a['probabilities']={k:float(k=='no_earlier_match') for k in a['probabilities']}
            return r
        saved=ReferenceClient(nodes=nodes,transport=transport).evaluate(run,'u4')
        self.assertEqual(len(calls),1);self.assertIsNone(saved['_relation_request']);self.assertEqual(saved['_relation_choices'],{})
        self.assertEqual(saved['_provenance']['completion'],'complete')


if __name__ == '__main__': unittest.main()
