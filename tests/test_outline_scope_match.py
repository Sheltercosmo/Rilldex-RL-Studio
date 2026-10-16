from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from tracker import outline_scope_match as match, work_outline as wo
from tracker.schema import InputError, digest
import test_outline_bindings as bindings

def fixture():
    graph,doc=bindings.fixture();return wo.fork(graph,doc)

def response(request,choice='same_scope'):
    return dict(model=request['model'],answers={key:dict(type='choice',choice='unresolved',confidence=0.00001,
        probabilities={k:0.3 if k==choice else 0.7/(len(q['criteria'])-1) for k in q['criteria']}) for key,q in request['questions'].items()})

class ScopeMatchTests(unittest.TestCase):
    def test_finite_inventory_keeps_all_pairs_including_nonlexical_candidates(self):
        g=fixture();before=deepcopy(g);p=match.prepare(g)
        self.assertEqual(p['candidate_pairs'],50)
        self.assertEqual(len({pair for packet in p['packets'] for pair in packet['pair_ids']}),50)
        self.assertTrue(all(len(packet['pair_ids'])<=12 for packet in p['packets']))
        self.assertEqual(g,before)

    def test_no_decisions_review_answers_results_or_future_text_in_request(self):
        p=match.prepare(fixture(),['report-approach','draft','convert'],[bindings.PLAN+':draft',bindings.PLAN+':convert'])
        self.assertEqual(len(p['packets']),1)
        state=p['packets'][0]['request']['state']
        self.assertEqual(set(r['event_id'] for r in state['source_records']),{'e65'})
        self.assertNotIn('bindings',state);self.assertNotIn('decisions',state);self.assertNotIn('revision',state)
        self.assertEqual(len(state['source_records'][0]['text']),408)
        self.assertEqual(state['source_cutoff'],{'event_id':'e65','end':408})
        for pair in state['pairs']:self.assertEqual(pair['evidence_cutoff']['end'],408)

    def test_different_prefixes_never_share_a_request(self):
        p=match.prepare(fixture(),['objective','draft'],['sab44075d05558c61e185'])
        self.assertEqual(len(p['packets']),2)
        self.assertEqual({packet['request']['state']['cutoff_event_id'] for packet in p['packets']},{'e2','e65'})
        early=next(p for p in p['packets'] if p['request']['state']['cutoff_event_id']=='e2')
        self.assertNotIn('e65',{r['event_id'] for r in early['request']['state']['source_records']})

    def test_review_only_revision_reuses_identical_model_requests(self):
        g=fixture();d=wo.template(g)['document'];d['revision']['note']='Different review wording';d['bindings']=[]
        changed=wo.fork(g,d)
        a,b=match.prepare(g),match.prepare(changed)
        self.assertNotEqual(a['base_graph_id'],b['base_graph_id'])
        self.assertEqual([p['request_hash'] for p in a['packets']],[p['request_hash'] for p in b['packets']])

    def test_argmax_is_the_only_selection_and_never_publishes_or_relabels(self):
        g=fixture();before=deepcopy(g);p=match.prepare(g,['draft'],[bindings.PLAN+':draft'])
        responses={packet['request_hash']:response(packet['request']) for packet in p['packets']}
        out=match.evaluate(g,p,responses)
        self.assertEqual(len(out['binding_candidates']),1);self.assertEqual(out['selection_policy'],'argmax/1')
        self.assertEqual(out['binding_candidates'][0]['status'],'proposed_not_reviewed')
        self.assertFalse(out['published']);self.assertEqual(g,before)

    def test_nonmatches_and_unresolved_are_retained_without_becoming_binding_candidates(self):
        g=fixture();p=match.prepare(g,['draft'],[bindings.PLAN+':draft'])
        for choice in set(match.CHOICES)-{'same_scope'}:
            raw={packet['request_hash']:response(packet['request'],choice) for packet in p['packets']}
            out=match.evaluate(g,p,raw)
            self.assertEqual(out['binding_candidates'],[]);self.assertEqual(out['observations'][0]['choice'],choice)

    def test_changed_source_candidates_requests_models_and_response_omissions_fail(self):
        g=fixture();p=match.prepare(g,['draft'],[bindings.PLAN+':draft'])
        raw={packet['request_hash']:response(packet['request']) for packet in p['packets']}
        for mutation in ['source','request','model','missing','extra']:
            packet=deepcopy(p);responses=deepcopy(raw)
            if mutation=='source':packet['base_graph_id']='different'
            if mutation=='request':packet['packets'][0]['request']['state']['comparison_rule']='accept everything'
            if mutation=='model':next(iter(responses.values()))['model']='different'
            if mutation=='missing':responses={}
            if mutation=='extra':next(iter(responses.values()))['answers']['extra']={}
            with self.subTest(mutation=mutation),self.assertRaises(InputError):match.evaluate(g,packet,responses)

    def test_invalid_inventory_and_batch_size_are_explicit(self):
        g=fixture()
        for items,scopes,size in [(['missing'],None,12),(['draft','draft'],None,12),([[]],None,12),(None,['missing'],12),(None,None,0),(None,None,13)]:
            with self.assertRaises(InputError):match.prepare(g,items,scopes,size)
        self.assertEqual(match.prepare(g,[])['packets'],[])

    def test_draft_requires_named_review_and_does_not_duplicate_existing_bindings(self):
        g=fixture();p=match.prepare(g,['draft'],[bindings.PLAN+':draft'])
        raw={packet['request_hash']:response(packet['request']) for packet in p['packets']}
        draft=match.review_template(g,p,raw)
        self.assertEqual(len(draft['document']['bindings']),3)
        with self.assertRaises(InputError):wo.validate(g,draft['document'])
        unbound=wo.template(g)['document'];unbound['bindings']=[];g=wo.fork(g,unbound)
        p=match.prepare(g,['draft'],[bindings.PLAN+':draft'])
        draft=match.review_template(g,p,raw)
        self.assertEqual(len(draft['document']['bindings']),1)
        self.assertEqual(draft['document']['bindings'][0]['note'],'')
        draft['document']['revision']={'author':'Authored review control','note':'Reviewed this scope in source.'}
        with self.assertRaises(InputError):wo.validate(g,draft['document'])
        draft['document']['bindings'][0]['note']='The same named report writing step.'
        wo.validate(g,draft['document'])

    def test_other_source_contexts_never_enter_model_request(self):
        from research.outline_scope_match_trial import control
        g=control();next(n for n in g['nodes'] if n['kind']=='event' and n['properties']['actor']=='user')['properties']['context_id']='separate'
        g.pop('id');g['id']='graph-'+digest(g)
        p=match.prepare(g)
        self.assertEqual(p['candidate_pairs'],0);self.assertEqual(len(p['excluded']),12);self.assertEqual(p['packets'],[])

    def test_file_handoff_is_replayable_and_stops_at_an_unreviewed_draft(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.json';source.write_text(json.dumps(fixture()),encoding='utf-8');out=root/'handoff'
            cmd=[sys.executable,'-m','tracker.outline_scope_match','prepare',str(source),str(out),'--items','draft','--scopes',bindings.PLAN+':draft']
            prepared=subprocess.run(cmd,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(prepared.stdout)['provider_calls'],0)
            p=json.loads((out/'prepared.json').read_text(encoding='utf-8'))
            responses={packet['request_hash']:response(packet['request']) for packet in p['packets']}
            raw=root/'responses.json';raw.write_text(json.dumps(responses),encoding='utf-8')
            cmd=[sys.executable,'-m','tracker.outline_scope_match','accept',str(out),str(raw)]
            first=subprocess.run(cmd,capture_output=True,text=True,check=True)
            second=subprocess.run(cmd,capture_output=True,text=True,check=True)
            self.assertEqual(first.stdout,second.stdout);self.assertFalse(json.loads(first.stdout)['published'])
            draft=json.loads((out/'review-draft.json').read_text(encoding='utf-8'))
            self.assertEqual(draft['document']['revision']['author'],'')

if __name__=='__main__':unittest.main()
