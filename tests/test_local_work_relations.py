"""Local relationship contracts and retained live development failures."""
from copy import deepcopy
from pathlib import Path
import json
import unittest
from rilldex import Workspace
from tracker import work_content_bindings as links, work_content_stages as stages, work_content_results, local_order
from tracker import graph_store, work_mentions
from tracker.schema import InputError, dumps
from tracker.jev import validate_answers
from tracker.semantic_extraction import read, write
from tracker.semantic_budget import ExecutionBudget, summary
from tracker.schema import digest
import test_work_content_results as saved_results


def answer(request,selected=()):
    return dict(model=request['model'],answers={key:dict(type='choice',choice='unresolved',confidence=0,
        probabilities={value:float(value==('supported' if key in selected else ('unsupported' if 'unsupported' in spec['criteria'] else 'unrelated')))
                      for value in spec['criteria']}) for key,spec in request['questions'].items()})


class LocalRelationTests(unittest.TestCase):
    def setUp(self):
        self.case=saved_results.WorkContentResultTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def decide(self,request):
        if request['state']['harness']==local_order.VERSION:
            self.case.calls.append('order');return answer(request)
        if 'candidates' not in request['state']:return self.case.decide(request)
        self.case.calls.append('relations')
        selected=[row['id'] for row in request['state']['candidates']
            if (row['source'],row['target'],row['type'])==('c1','c2','purpose')]
        return answer(request,selected)

    def extract(self,**options):
        return self.case.extract(decision_transport=self.decide,**options)

    def test_extend_saved_extraction_without_rebilling_and_preserve_partial_progress(self):
        prior=self.extract();self.assertEqual(prior['status'],'complete')
        original=graph_store.read(self.case.store,self.case.graph['id'])
        partial=self.extract(relations=True,decision_calls=3)
        self.assertEqual(partial['stage'],'relationships');self.assertEqual(partial['status'],'budget_reached')
        self.assertEqual(partial['relations']['counts']['pending'],8)
        self.assertEqual(self.case.workspace.sql('SELECT COUNT(*) n FROM work_content_relations WHERE status=?',['pending']).rows[0]['n'],8)
        completed=self.extract(decision_calls=4)
        self.assertEqual(completed['relations']['counts'],dict(supported=1,unsupported=5,unresolved=0,pending=2))
        completed=self.extract(decision_calls=5)
        self.assertEqual(completed['relations']['counts'],dict(supported=1,unsupported=7,unresolved=0,pending=0))
        self.assertEqual(completed['review']['receipts'][-1]['status'],'unresolved')
        self.assertEqual(self.case.calls,['contents','features','f1','f2','f3','relations','order'])
        self.assertEqual(completed['saved']['id'],prior['saved']['id'])
        self.case.seen=[];self.extract(decision_calls=5)
        self.assertTrue(all(row['view']['relations']['counts']['supported']==1 for row in self.case.seen))
        self.assertEqual(self.case.calls,['contents','features','f1','f2','f3','relations','order'])
        self.assertEqual(graph_store.read(self.case.store,self.case.graph['id']),original)
        with self.assertRaises(InputError):self.extract(relations=False,decision_calls=5)
        rows=self.case.workspace.table('work_content_relations').rows
        export=self.case.root/'export.sqlite';self.case.workspace.data.database(export)
        self.assertEqual(rows,Workspace(export).table('work_content_relations').rows)
        self.assertEqual(Workspace(self.case.store.path,observer='other').table('work_content_relations').rows,[])

    def test_relation_receipt_cannot_be_transplanted_or_edited(self):
        result=self.extract(relations=True,decision_calls=4)
        packet=work_mentions.packet(self.case.graph,['unit-0'])
        result['relations']['links'][0]['status']='unsupported'
        with self.assertRaises(InputError):work_content_results.save(self.case.store,self.case.graph,packet,result)

    def test_previous_relationship_protocol_resumes_cached_results_without_billing(self):
        for policy in (links.PREVIOUS_LOCAL_RELATIONS,links.CONTRAST_LOCAL_RELATIONS):
            with self.subTest(policy=policy):
                self.case=saved_results.WorkContentResultTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
                self.cached_policy(policy)

    def cached_policy(self,policy):
        result=self.extract()
        packet=work_mentions.packet(self.case.graph,['unit-0'])
        root=self.case.root/'pilot'
        requests=links.local_relation_requests(packet,result['bound'],policy=policy)
        budget=ExecutionBudget(root,'previous-version',dict(jev_requests=1,candidate_requests=0,input_bytes=1000000))
        responses={}
        for page,request in requests.items():
            responses[page]=budget.invoke('jev',request,lambda:self.decide(request))
            write(root/'responses'/'jev'/(digest(request)+'.json'),dict(
                request=request,model_hash=digest(read(root/'model.json')),response=responses[page]))
        result.update(relation_policy=policy,relations=links.local_relation_review(packet,result['bound'],responses,policy=policy),usage=summary(root))
        write(root/'result.json',result)
        work_content_results.save(self.case.store,self.case.graph,packet,result)
        before=list(self.case.calls)
        final=self.extract(decision_calls=4)
        self.assertEqual(self.case.calls,before)
        self.assertEqual(final['relation_policy'],policy)
        self.assertEqual(final['relations'],result['relations'])
        saved=self.case.workspace.work_contents(self.case.graph['id'],'unit-0')[0]
        self.assertEqual(saved['view']['relations']['schema'],policy)
        # A different interpretation protocol cannot relabel the same receipt.
        changed=deepcopy(final);changed['relation_policy']=links.LOCAL_RELATIONS
        with self.assertRaises(InputError):work_content_results.save(self.case.store,self.case.graph,packet,changed)

    def test_empty_inventory_skips_relationship_calls(self):
        self.case.contents=[]
        result=self.extract(relations=True)
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['relations']['links'],[])
        self.assertEqual(result['relations']['pages'],dict(total=0,inspected=0))
        self.assertEqual(self.case.calls,['contents'])

    def test_large_content_quotes_reduce_page_size_without_losing_source(self):
        from tracker.adapters import normalize
        from tracker.portable import chat_document
        from tracker.semantic_map import evidence
        from tracker.schema import digest
        pieces=[f'operation {i}: '+chr(65+i)*1400 for i in range(10)]
        run=normalize(chat_document([dict(role='assistant',content='; '.join(pieces))]))[0]
        event=run['events'][0]
        unit=dict(id='u',kind='semantic',actor=event['actor'],activity='orient',trajectory_id=event['trajectory_id'],status='selected',source=evidence(run,event['id']),content={})
        graph=graph_store.build(run,dict(document=dict(source_hash=digest(run),units=[unit],relations=[]),observer=dict(id='control',label='Control')))
        packet=work_mentions.packet(graph,['u']);req=stages.scoped_content_request(packet,'u')
        bound=stages.bind_scoped_contents(packet,req,dict(contents=[dict(id='c'+str(i),kind='operation',mode='proposed',expression=dict(text=p)) for i,p in enumerate(pieces)]),'large control')
        requests=links.local_relation_requests(packet,bound)
        self.assertGreater(len(requests),12)
        self.assertEqual(sum(len(q['questions']) for q in requests.values()),315)
        self.assertEqual(len(links.local_relation_review(packet,bound,{})['links']),360)
        for q in requests.values():
            source=q['state'].get('source',q['state'].get('unit',{}).get('source',{}).get('text'))
            self.assertEqual(source,run['events'][0]['text'])
            self.assertLessEqual(len(dumps(q).encode()),links.MAX_SELECTION_BYTES)

    def test_complete_source_and_all_pairs_survive_page_boundaries(self):
        data=json.loads((Path(__file__).parent/'fixtures/scoped_content_granularity.json').read_text(encoding='utf-8'))
        row=next(r for r in data['cases'] if r['case']=='fresh-7');arm=row['arms']['granularity'];packet=row['packet']
        bound=stages.bind_scoped_contents(packet,arm['request'],arm['response'],'replay',content_policy=stages.SEPARATE_WORK)
        requests=links.local_relation_requests(packet,bound)
        self.assertEqual(len(requests),3)
        expected={(a['id'],b['id'],kind) for a in bound['contents'] for b in bound['contents'] if a!=b for kind in work_mentions.LINKS}
        actual=[]
        for req in requests.values():
            source=req['state'].get('source',req['state'].get('unit',{}).get('source',{}).get('text'))
            self.assertEqual(source,packet['units'][0]['source']['text'])
            self.assertLessEqual(len(dumps(req).encode()),links.MAX_SELECTION_BYTES)
        actual=[(row['source'],row['target'],row['type']) for row in links.local_relation_review(packet,bound,{})['links']]
        self.assertEqual(set(actual),expected);self.assertEqual(len(actual),80)
        partial=links.local_relation_review(packet,bound,{'page-0':answer(requests['page-0'])})
        self.assertEqual(partial['counts']['unsupported'],32);self.assertEqual(partial['counts']['pending'],48)
        with self.assertRaises(InputError):links.local_relation_review(packet,bound,{'page-99':{}})
        bad=answer(requests['page-1']);bad['answers'].pop(next(iter(bad['answers'])))
        with self.assertRaises(InputError):links.local_relation_review(packet,bound,{'page-1':bad})

    def test_live_replay_keeps_failures_and_version_specific_requests(self):
        data=json.loads((Path(__file__).parent/'fixtures/local_work_relations.json').read_text(encoding='utf-8'))
        totals={}
        for arm in data['arms']:
            fp=fn=0
            for row in arm['cases']:
                observed=[]
                for receipt in row['review']['receipts']:
                    req=row['requests'][receipt['page']];answers=validate_answers(receipt['response'],req)
                    observed.extend((r['source'],r['target'],r['type']) for r in req['state']['candidates'] if answers[r['id']]['value']=='supported')
                expected={tuple(v) for v in row['positive']}
                fp+=len(set(observed)-expected);fn+=len(expected-set(observed))
                if arm['name']=='balanced':self.assertEqual(links.local_relation_requests(row['packet'],row['bound'],policy=links.PREVIOUS_LOCAL_RELATIONS),row['requests'])
            totals[arm['name']]=dict(false_positive=fp,false_negative=fn)
        self.assertEqual(totals,data['reference_counts'])
        self.assertEqual(totals['baseline'],dict(false_positive=6,false_negative=1))
        self.assertEqual(totals['balanced'],dict(false_positive=2,false_negative=0))


if __name__=='__main__':unittest.main()
