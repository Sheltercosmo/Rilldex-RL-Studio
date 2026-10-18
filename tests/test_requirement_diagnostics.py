"""Protocol and lifecycle tests. Scripted choices do not establish model accuracy."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import requirement_diagnostics as detector, diagnostic_worker as worker
from tracker import monitoring, monitor_evidence, reward_detectors
from tracker import requirement_retrieval as retrieval
from tracker.adapters import normalize
from tracker.schema import digest, dumps
from tracker.store import Store
from test_diagnostic_monitors import source
from test_tracker import harbor


def decide(req):
    answers={}
    for key,q in req['questions'].items():
        if req['state']['stage']=='requirement_extraction':
            term=list(req['state']['instruction_paragraphs'].values())[int(key.split('_')[-1])]
            selected='context' if 'SCAFFOLDING' in term['text'] else 'unresolved' if 'AMBIGUOUS' in term['text'] else 'task_requirement'
        else:
            selected=next((f for f in q['criteria'] if f in req['state']['source_fragments'] and 'CONFLICT' in req['state']['source_fragments'][f]['text']),'none')
        answers[key]={'value':selected}
    return answers,digest(req)


def transport(req):
    answers,_=decide(req)
    return {'model':req['model'],'answers':{key:{'type':'choice','probabilities':{
        option:float(option==answers[key]['value']) for option in q['criteria']}} for key,q in req['questions'].items()}}


def example(long=False):
    return source(task='See attributed instruction events in the trace.',trace=dumps([
        {'id':'u','actor':'user','kind':'instruction','arguments':{'text':'not the instruction'},
         'text':'Preserve 中文 "data" and gzip it.\n\nSCAFFOLDING: sample commands.\n\nAMBIGUOUS: preserve legacy behavior.'},
        {'id':'noise','actor':'tool','kind':'tool_result','text':'ordinary output\n'*(15000 if long else 1)},
        {'id':'a','actor':'agent','kind':'action_dispatch','text':'CONFLICT: return gzipBytes(nil)'}]))


class RequirementTests(unittest.TestCase):
    def test_exact_instruction_offsets_and_compound_terms(self):
        s=example();terms=detector.criteria(s)
        self.assertEqual(len(terms),3)
        self.assertEqual(terms[0]['display_text'],'Preserve 中文 "data" and gzip it.')
        self.assertTrue(all(t['event_id']=='u' for t in terms))
        event=json.loads(s['trace'])[0]
        for term in terms:
            self.assertEqual(term['text'],s['trace'][term['start']:term['end']])
            self.assertEqual(term['display_text'],event['text'][term['event_start']:term['event_end']])
        self.assertNotIn('not the instruction',' '.join(t['text'] for t in terms))

    def test_long_source_scan_preserves_ambiguous_requirements_and_direct_findings(self):
        s=example(long=True);seen=[]
        def record(req):
            seen.append(req);self.assertLessEqual(len(dumps(req)),120000)
            return decide(req)
        result=detector.build(s,record)
        self.assertGreater(len(s['trace']),160000)
        self.assertEqual(result['coverage']['selected_requirements'],2)
        self.assertEqual(result['metrics']['requirement_conflict']['value'],1)
        self.assertEqual({f['candidate']['event_id'] for f in result['findings']},{'a'})
        self.assertEqual({r['state']['stage'] for r in seen},{'requirement_extraction','requirement_conflict_scan'})
        self.assertIsNone(result['confirmed_reward_hacking']['value'])
        scanned={f['id'] for r in seen if r['state']['stage']=='requirement_conflict_scan' for f in r['state']['source_fragments'].values()}
        expected={f['id'] for f in detector.index(s) if f.get('actor') not in {'user','system','developer'} and f['origin']=='trace'}
        self.assertTrue(expected<=scanned)

    def test_later_instructions_are_not_used_against_earlier_actions(self):
        s=source(task='See attributed instruction events in the trace.',trace=dumps([
            {'id':'a','actor':'agent','kind':'action','text':'CONFLICT earlier'},
            {'id':'u','actor':'user','kind':'instruction','text':'A newly added requirement.'}]))
        self.assertEqual(list(detector.requests(s)),[])
        self.assertIsNone(detector.build(s,decide)['metrics']['requirement_conflict']['value'])

    def test_absence_only_means_no_candidate_in_complete_compared_source(self):
        for changes,expected in [({},0),({'complete_recorded_text':False},None),({'action_coverage':'unavailable'},None),({'task':''},None)]:
            result=detector.build(source(**changes),decide)
            self.assertEqual(result['metrics']['requirement_conflict']['value'],expected)
        def unresolved(req):
            answers,key=decide(req)
            if req['state']['stage']=='requirement_conflict_scan':answers={k:{'value':'unresolved'} for k in answers}
            return answers,key
        self.assertIsNone(detector.build(source(),unresolved)['metrics']['requirement_conflict']['value'])

    def test_cache_replay_needs_no_provider_calls(self):
        with TemporaryDirectory() as temp:
            s=example();result=detector.execute(s,temp,transport)
            self.assertEqual(detector.execute(s,temp,lambda _:self.fail('Unchanged request must be cached')),result)
            self.assertTrue(detector.audit(s,result,temp)['exact_replay'])

    def test_worker_budget_resume_publication_and_reuse(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'db');doc=harbor()
            doc['steps'][-1]['message']='ordinary output '*13000
            run=normalize(doc,'harbor')[0];store.add([run]);selector=worker.selection(run_ids=[run['id']])
            plan=worker.plan(store,selector,'requirements')
            self.assertEqual(plan['rows'][0]['eligibility'],'ready')
            self.assertEqual(plan['model_api_calls'],0)
            first=worker.execute(store,root/'work',transport,selector=selector,protocol_name='requirements',max_new_calls=1)
            self.assertEqual(first['coverage']['counts'],{'pending':1})
            done=worker.execute(store,root/'work',transport,selector=selector,protocol_name='requirements',max_new_calls=100)
            self.assertEqual(done['coverage']['counts'],{'complete':1})
            self.assertTrue(worker.audit(store,root/'work')['runs'][0]['validation']['exact_replay'])
            with store.connect() as c:
                record=json.loads(c.execute("SELECT document FROM rollout_measurements WHERE observer LIKE 'requirement-diagnostics-%'").fetchone()[0])
            self.assertEqual(record['metrics']['diagnostic_requirement_conflict']['value'],0)
            cached=worker.execute(store,root/'work',lambda _:self.fail('Published result should be reused'),selector=selector,protocol_name='requirements',max_new_calls=0)
            self.assertEqual(cached['new_calls'],0)

    def test_positive_publishes_through_existing_monitor_and_map_evidence(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'db');doc=harbor();doc['steps'][-1]['message']='CONFLICT: dummy replacement.'
            run=normalize(doc,'harbor')[0];store.add([run]);s=worker.source_monitor.from_run(run)
            result=detector.execute(s,root/'work',transport)
            detector.register(store,run,s,result,root/'work')
            added=reward_detectors.activate(store,{'checks':['requirement_conflict'],'observer':detector.protocol()['id']})
            self.assertEqual(len(added['added']),1)
            monitoring.sync(store)
            with store.connect() as c:value=c.execute('SELECT id FROM monitor_values').fetchone()
            receipt=monitor_evidence.read(store,value[0])
            self.assertEqual(receipt['measurement']['value'],1)
            self.assertEqual(receipt['explanation']['diagnostic']['candidates'],result['findings'])
            self.assertEqual(receipt['run']['id'],run['id'])
            candidate=result['findings'][0]['candidate']
            excerpts=receipt['explanation']['diagnostic_excerpts'][candidate['id']]
            self.assertTrue(any('CONFLICT: dummy replacement.' in p['text'] for p in excerpts))
            event=next(e for e in run['events'] if e['id']==candidate['event_id'])
            for excerpt in excerpts:
                self.assertEqual(excerpt['event_id'],event['id'])
                self.assertEqual(excerpt['actor'],event['actor'])
                self.assertTrue(excerpt['node_ids'])
            self.assertEqual(receipt['input_record']['diagnostic_result'],result)

    def test_prioritization_preserves_all_requests_and_legacy_replay(self):
        s=example(long=True)
        original=list(detector.requests(s,version=detector.VERSION))
        ordered=list(detector.requests(s,version=detector.PRIORITIZED_VERSION))
        self.assertEqual({digest(r) for r in original},{digest(r) for r in ordered})
        self.assertEqual(detector.protocol(detector.VERSION)['id'],'requirement-diagnostics-fb804f22381045bdc8d8')
        self.assertEqual(detector.protocol(detector.PRIORITIZED_VERSION)['id'],'requirement-diagnostics-956d675d47a4c133ccf5')
        with TemporaryDirectory() as temp:
            saved=detector.execute(s,temp,transport,version=detector.VERSION)
            self.assertNotIn('scan_complete',saved['coverage'])
            self.assertTrue(detector.audit(s,saved,temp)['exact_replay'])

    def test_literal_targets_keep_source_candidates_options_and_cached_term_selection(self):
        s=example();terms=detector.criteria(s)
        old=list(detector.requests(s,terms,version=detector.PRIORITIZED_VERSION))
        new=list(detector.requests(s,terms,version=detector.CURRENT_VERSION))
        self.assertEqual(new,[detector.bind_questions(r) for r in old])
        for previous,current in zip(old,new):
            self.assertEqual(previous['state']['source_fragments'],current['state']['source_fragments'])
            self.assertEqual(previous['state']['requirements'],current['state']['requirements'])
            self.assertNotIn('requirement_binding',previous['state'])
            for field,q in current['questions'].items():
                self.assertEqual(q['criteria'],previous['questions'][field]['criteria'])
                term=current['state']['requirements'][field]
                self.assertIn(json.dumps(term['display_text'],ensure_ascii=False),q['instructions'])
            self.assertLessEqual(len(dumps(current)),120000)
        self.assertEqual(detector.protocol()['selection'],'raw_argmax')

    def test_existing_worker_keeps_its_original_selector_version(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'db');selector=worker.selection()
            config={'schema':'diagnostic-worker/1','implementation':'requirements',
                'protocol':detector.protocol(detector.PRIORITIZED_VERSION),'selection':selector,
                'database_path':str(store.path.resolve()),
                'eligibility':'Latest complete producer revisions or explicit imports; source inspection requires recorded action coverage'}
            root.joinpath('worker.json').write_text(dumps(config),encoding='utf-8')
            _,loaded,_=worker.initialize(store,root,selector,'requirements')
            self.assertEqual(loaded,config)

    def test_clause_search_is_only_ordering_not_requirement_rewriting(self):
        s=example(long=True);terms=detector.criteria(s)
        plan=retrieval.order(list(detector.pages(detector.index(s))),terms)
        self.assertEqual(sorted(plan['pages']),list(range(len(plan['pages']))))
        self.assertEqual(len(plan['pages']),len(set(plan['pages'])))
        self.assertIn('cancellation',retrieval.tokens('cancellationReason'))
        self.assertIn('reason',retrieval.tokens('cancellationReason'))
        self.assertIn('中文',retrieval.tokens('中文'))
        for req in detector.requests(s,terms,version=detector.CURRENT_VERSION):
            self.assertTrue(all(term in terms for term in req['state']['requirements'].values()))
        # Missing lexical matches still leave every page queued.
        empty=retrieval.order(list(detector.pages(detector.index(s))),[])
        self.assertEqual(empty['pages'],list(range(len(empty['pages']))))

    def test_partial_findings_publish_and_resume_without_becoming_complete(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'db');doc=harbor()
            doc['steps'][-1]['message']='CONFLICT Fix issue '+('ordinary output '*13000)
            run=normalize(doc,'harbor')[0];store.add([run]);selector=worker.selection(run_ids=[run['id']])
            first=worker.execute(store,root/'work',transport,selector=selector,protocol_name='requirements',max_new_calls=2)
            self.assertEqual(first['coverage']['counts'],{'pending':1})
            with store.connect() as c:
                saved=json.loads(c.execute("SELECT document FROM rollout_measurements WHERE observer LIKE 'requirement-diagnostics-%'").fetchone()[0])
            partial=saved['diagnostic_result'];self.assertFalse(partial['coverage']['scan_complete'])
            self.assertEqual(saved['metrics']['diagnostic_requirement_conflict']['value'],1)
            self.assertFalse(worker.plan(store,selector,'requirements')['rows'][0]['published_result_reusable'])
            folder=root/'work'/'runs'/run['id']/digest(run)
            done=worker.execute(store,root/'work',transport,selector=selector,protocol_name='requirements',max_new_calls=100)
            self.assertEqual(done['coverage']['counts'],{'complete':1})
            self.assertTrue(worker.audit(store,root/'work')['runs'][0]['validation']['exact_replay'])
            self.assertTrue(detector.audit(worker.source_monitor.from_run(run),partial,folder)['exact_replay'])


if __name__=='__main__':unittest.main()
