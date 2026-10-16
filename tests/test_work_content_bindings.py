from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tracker import work_content_bindings as scoped, work_content_stages as stages
from tracker.schema import InputError


ROOT = Path(__file__).resolve().parents[1]


def case():
    packet=json.loads((ROOT/'research/work-content-audit-2026-10-13/installation/packet.json').read_text(encoding='utf-8'))
    body=dict(contents=[
        dict(id='absence',kind='state',mode='asserted',expression={'text':'`pdflatex` is not installed'}),
        dict(id='install',kind='operation',mode='proposed',expression={'text':'install `texlive`'}),
        dict(id='available',kind='state',mode='proposed',expression={'text':'get `pdflatex`'}),
        dict(id='convert',kind='operation',mode='proposed',expression={'text':'convert the Markdown file to a PDF'})],
        features=[
            dict(id='hedge',type='hedge',form='literal',expression={'text':'It seems'},scopes=[['absence'],['install']]),
            dict(id='negative',type='negation',form='literal',expression={'text':'not'},scopes=[['absence'],['available']]),
            dict(id='intention',type='intent',form='literal',expression={'text':"Let's"},scopes=[['install','available','convert'],['install']])])
    req=scoped.request(packet,packet['units'][0]['unit_id'])
    bound=scoped.bind(packet,req,body,'authored structural control')
    return packet,req,body,bound


def response(req, choices=None):
    choices=choices or {}
    answers={}
    for key,q in req['questions'].items():
        chosen=choices.get(key,next(iter(q['criteria'])))
        others=[c for c in q['criteria'] if c!=chosen]
        # Deliberately low maximal probability and a contradictory provider choice.
        largest=.3 if len(others)>=3 else .51
        answers[key]=dict(type='choice',choice=others[0],confidence=0,
            probabilities={c:largest if c==chosen else (1-largest)/len(others) for c in q['criteria']})
    return dict(model=req['model'],answers=answers)


def selected_case(choices=None):
    p,q,b,c=case(); req=scoped.selection_request(p,c)
    decision=response(req,choices)
    return p,q,b,c,decision,scoped.select(p,c,decision)


class BindingTests(unittest.TestCase):
    def test_scopes_use_raw_argmax_without_confidence_and_keep_raw_response(self):
        p,_,_,b,raw,s=selected_case()
        self.assertTrue(s['ready_for_relationships'])
        self.assertEqual(s['response'],raw)
        self.assertEqual(s['bindings'][0]['content_ids'],['absence'])
        self.assertEqual(s['selection_policy'],'argmax/1')
        self.assertEqual(scoped.select(p,b,raw),s)

    def test_display_carries_qualifications_and_relationship_request_uses_structured_contents(self):
        p,_,_,b,_,s=selected_case()
        view=scoped.project(p,b,s)
        absence=view['contents'][0]
        self.assertEqual(absence['display_text'],'`pdflatex` is not installed')
        self.assertEqual([f['type'] for f in absence['features']],['hedge','negation'])
        self.assertEqual(absence['features'][0]['expression']['text'],'It seems')
        self.assertEqual(absence['execution_status'],'not_established_by_prose')
        req=scoped.relationship_request(p,b,s)
        self.assertEqual(req['contents'],view['contents'])
        self.assertNotIn('label',req['contents'][0])

    def test_missing_candidate_and_inventory_defect_block_only_this_experiment(self):
        for choices in [{'f0':'no_suitable_candidate'},{'f1':'unresolved'},
                        {'inventory':'incomplete'},{'inventory':'incorrect'}]:
            p,_,_,b,_,s=selected_case(choices)
            before=deepcopy(b)
            self.assertFalse(s['ready_for_relationships'])
            with self.assertRaisesRegex(InputError,'relationships blocked'):
                scoped.relationship_request(p,b,s)
            self.assertEqual(b,before)

    def test_invalid_scope_endpoints_duplicates_and_foreign_expressions_fail(self):
        p,q,body,_=case()
        variants=[]
        for scopes in [[[]],[['foreign']],[['absence','absence']],[['absence'],['absence']]]:
            bad=deepcopy(body);bad['features'][0]['scopes']=scopes;variants.append(bad)
        bad=deepcopy(body);bad['features'][0]['expression']={'text':'invented hedge'};variants.append(bad)
        bad=deepcopy(body);bad['contents'][0]['label']='invented paraphrase';variants.append(bad)
        bad=deepcopy(body);bad['contents'][0]['mode']='executed';variants.append(bad)
        bad=deepcopy(body);bad['features'].append(dict(**body['features'][0],));bad['features'][-1]['id']='other';variants.append(bad)
        for bad in variants:
            with self.subTest(bad=bad),self.assertRaises(InputError):scoped.bind(p,q,bad,'control')

    def test_repeated_quotes_require_offset_and_absolute_spans_respect_unit_start(self):
        p,q,b,_=case();p=deepcopy(p)
        p['units'][0]['source'].update(start=80,end=209)
        q=scoped.request(p,p['units'][0]['unit_id'])
        b['features'][0]['expression']={'text':'`pdflatex`'}
        with self.assertRaisesRegex(InputError,'exactly once'):scoped.bind(p,q,b,'control')
        b['features'][0]['expression']['start']=14
        bound=scoped.bind(p,q,b,'control')
        self.assertEqual(bound['features'][0]['expression']['start'],94)

    def test_bound_fields_source_and_selection_tampering_is_rejected(self):
        p,q,body,b,raw,s=selected_case()
        variants=[]
        for field,value in [('request_hash','other'),('packet_hash','other')]:
            bad=deepcopy(b);bad[field]=value;variants.append(bad)
        bad=deepcopy(b);bad['features'][0]['expression']['text']='perhaps';variants.append(bad)
        for bad in variants:
            with self.assertRaises(InputError):scoped.selection_request(p,bad)
        stale=deepcopy(p);stale['source_hash']='new-revision'
        with self.assertRaises(InputError):scoped.selection_request(stale,b)
        changed=deepcopy(s);changed['bindings'][0]['content_ids']=['install']
        with self.assertRaises(InputError):scoped.relationship_request(p,b,changed)
        raw['model']='other'
        with self.assertRaises(InputError):scoped.select(p,b,raw)

    def test_same_exact_quotes_do_not_establish_scope_correctness(self):
        # Deliberately wrong scope is structurally valid. Only evaluation can
        # detect this semantic error; no claim of a deterministic accuracy fix.
        p,_,_,b,_,s=selected_case({'f0':'s1'})
        view=scoped.project(p,b,s)
        self.assertEqual(view['contents'][1]['features'][0]['type'],'hedge')
        self.assertEqual(view['contents'][1]['features'][0]['expression']['text'],'It seems')

    def test_focused_review_preserves_source_and_never_overwrites_original_selection(self):
        p,_,_,b,_,s=selected_case({'f0':'s1'});before=deepcopy(s)
        req=scoped.focused_scope_request(p,b,'hedge')
        self.assertEqual(set(req['questions']),{'scope'})
        self.assertEqual(req['state']['unit']['source'],p['units'][0]['source'])
        self.assertNotIn('features',req['state'])
        result=scoped.focused_scope_result(p,b,'hedge',response(req))
        self.assertEqual(result['content_ids'],['absence'])
        self.assertEqual(s,before)
        self.assertNotEqual(result['content_ids'],s['bindings'][0]['content_ids'])
        with self.assertRaisesRegex(InputError,'unknown feature'):
            scoped.focused_scope_request(p,b,'other')

    def test_single_content_closure_recovers_missing_candidate_without_mutating_proposal(self):
        p,q,body,_=case();body['features'][0]['scopes']=[['install'],['available','convert']]
        b=scoped.bind(p,q,body,'missing-candidate control');before=deepcopy(b)
        cs=scoped.scope_candidates(p,b,'hedge',scoped.INCLUDE_SINGLE_CONTENTS)
        self.assertEqual(cs[:2],[dict(content_ids=['install'],origin='supplied'),
                               dict(content_ids=['available','convert'],origin='supplied')])
        self.assertEqual([c['content_ids'] for c in cs],[['install'],['available','convert'],['absence'],['available'],['convert']])
        req=scoped.focused_scope_request(p,b,'hedge',candidate_policy=scoped.INCLUDE_SINGLE_CONTENTS)
        raw=response(req,{'scope':'s2'})
        selected=scoped.focused_scope_result(p,b,'hedge',raw,candidate_policy=scoped.INCLUDE_SINGLE_CONTENTS)
        self.assertEqual(selected['content_ids'],['absence'])
        self.assertEqual(selected['selected_candidate_origin'],'enumerated_single_content')
        self.assertFalse(req['state']['scope_candidate_coverage']['all_multi_content_scopes'])
        self.assertEqual(b,before)
        with self.assertRaises(InputError):scoped.focused_scope_result(p,b,'hedge',raw)

    def test_closure_does_not_claim_to_recover_missing_content_or_arbitrary_shared_scope(self):
        p,q,body,_=case();body['features']=[body['features'][2]]
        body['features'][0]['scopes']=[['install']]
        b=scoped.bind(p,q,body,'missing-group control')
        cs=scoped.scope_candidates(p,b,'intention',scoped.INCLUDE_SINGLE_CONTENTS)
        self.assertNotIn(['available','convert','install'],[c['content_ids'] for c in cs])
        req=scoped.focused_scope_request(p,b,'intention',candidate_policy=scoped.INCLUDE_SINGLE_CONTENTS)
        result=scoped.focused_scope_result(p,b,'intention',response(req,{'scope':'no_suitable_candidate'}),candidate_policy=scoped.INCLUDE_SINGLE_CONTENTS)
        self.assertIsNone(result['content_ids'])
        self.assertIsNone(result['selected_candidate_origin'])
        with self.assertRaises(InputError):scoped.scope_candidates(p,b,'intention','arbitrary-all-powerset')

    def test_existing_focused_requests_and_results_remain_exactly_replayable(self):
        root=ROOT/'research/semantic-reconstruction-2026-10-16'
        read=lambda p:json.loads(p.read_text(encoding='utf-8'))
        p=read(root/'scoped-trial/reasoning/packet.json');b=read(root/'scoped-trial/reasoning/bound-contents.json')
        self.assertEqual(scoped.focused_scope_request(p,b,'method'),read(root/'focused-diagnostic/request.json'))
        self.assertEqual(scoped.focused_scope_result(p,b,'method',read(root/'focused-diagnostic/response.json')),
                         read(root/'focused-diagnostic/result.json'))

    def test_explicit_staged_expansion_preserves_singletons_through_links(self):
        p,q,body,_=case();body['features']=[body['features'][0]]
        body['features'][0]['scopes']=[['install']]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory=root/'new';completion=root/'response.json'
            manifest=stages.prepare_scoped_files(p,p['units'][0]['unit_id'],directory,candidate_policy=scoped.INCLUDE_SINGLE_CONTENTS)
            self.assertEqual(manifest['scope_candidate_policy'],scoped.INCLUDE_SINGLE_CONTENTS)
            def read(name):return json.loads((directory/name).read_text(encoding='utf-8'))
            def accept(stage,value):
                completion.write_text(json.dumps(value),encoding='utf-8')
                return stages.accept_scoped_files(directory,stage,completion,'control','control/'+stage)
            accept('contents',body)
            request=read('scope-selection-request.json')
            self.assertEqual(set(request['questions']['f0']['criteria']),{'s0','s1','s2','s3','no_suitable_candidate','unresolved'})
            accept('scopes',response(request,{'f0':'s1'}))
            selected=read('selected-contents.json')
            self.assertEqual(selected['bindings'][0]['content_ids'],['absence'])
            self.assertEqual(selected['bindings'][0]['candidate_origin'],'enumerated_single_content')
            self.assertEqual(read('relationship-request.json')['contents'][0]['features'][0]['type'],'hedge')
            accept('links',dict(links=[],content_issues=[]))
            accept('link-selection',response(read('link-selection-request.json')))
            self.assertEqual(read('observation.json')['contents'][0]['features'][0]['expression']['text'],'It seems')
            # Policy cannot be silently changed to reinterpret saved distributions.
            with self.assertRaisesRegex(InputError,'artifact differs'):
                stages.prepare_scoped_files(p,p['units'][0]['unit_id'],directory,candidate_policy=scoped.SUPPLIED_SCOPES)

    def test_legacy_stage_policy_is_preserved_and_malformed_policy_cannot_create_files(self):
        p,_,_,_=case();uid=p['units'][0]['unit_id']
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);legacy=root/'old'
            first=stages.prepare_scoped_files(p,uid,legacy,candidate_policy=scoped.SUPPLIED_SCOPES)
            second=stages.prepare_scoped_files(p,uid,legacy)
            self.assertNotIn('scope_candidate_policy',first)
            self.assertNotIn('scope_candidate_policy',second)
            self.assertTrue(second['reused'])
            with self.assertRaises(InputError):stages.prepare_scoped_files(p,uid,root/'invalid',candidate_policy=[])
            self.assertFalse((root/'invalid').exists())
            new=stages.prepare_scoped_files(p,uid,root/'new-default')
            self.assertNotIn('scope_candidate_policy',new)

    def test_maximum_candidate_set_is_bounded_without_silently_dropping_contents(self):
        p,q,_,_=case();p=deepcopy(p)
        source=' '.join('target'+str(i) for i in range(12))+' maybe'
        p['units'][0]['source'].update(text=source,start=0,end=len(source))
        q=scoped.request(p,p['units'][0]['unit_id'])
        body=dict(contents=[dict(id='c'+str(i),kind='state',mode='asserted',expression={'text':'target'+str(i),'start':source.index('target'+str(i))}) for i in range(12)],
            features=[dict(id='f',type='hedge',form='literal',expression={'text':'maybe'},scopes=[['c0','c1'],['c2','c3'],['c4','c5'],['c6','c7']])])
        b=scoped.bind(p,q,body,'bounded inventory control')
        candidates=scoped.scope_candidates(p,b,'f',scoped.INCLUDE_SINGLE_CONTENTS)
        self.assertEqual(len(candidates),16)
        self.assertEqual(sum(c['origin']=='enumerated_single_content' for c in candidates),12)
        self.assertEqual(candidates[-1]['content_ids'],['c11'])

    def test_scope_comparison_uses_content_ids_not_option_positions(self):
        p,q,body,b=case()
        left=scoped.focused_scope_result(p,b,'hedge',response(scoped.focused_scope_request(p,b,'hedge')))
        reordered=deepcopy(body);reordered['features'][0]['scopes'].reverse()
        other=scoped.bind(p,q,reordered,'reordered control')
        right=scoped.focused_scope_result(p,other,'hedge',response(scoped.focused_scope_request(p,other,'hedge'),{'scope':'s1'}))
        comparison=scoped.compare_scope_results(p,'hedge',b,left,other,right)
        self.assertEqual(comparison['status'],'agreement')
        self.assertTrue(comparison['candidate_change']['same_set_reordered'])
        self.assertEqual(comparison['affected_content_ids'],[])
        self.assertEqual(comparison['resolution'],'not_adjudicated')

    def test_scope_comparison_retains_disagreement_and_never_elects_a_winner(self):
        p,_,_,b=case();before=deepcopy(b)
        req=scoped.focused_scope_request(p,b,'hedge')
        a=scoped.focused_scope_result(p,b,'hedge',response(req))
        closed=scoped.focused_scope_request(p,b,'hedge',candidate_policy=scoped.INCLUDE_SINGLE_CONTENTS)
        z=scoped.focused_scope_result(p,b,'hedge',response(closed,{'scope':'s1'}),candidate_policy=scoped.INCLUDE_SINGLE_CONTENTS)
        comparison=scoped.compare_scope_results(p,'hedge',b,a,b,z)
        self.assertEqual(comparison['status'],'disagreement')
        self.assertEqual(comparison['affected_content_ids'],['absence','install'])
        self.assertEqual(comparison['candidate_change']['added'],[['available'],['convert']])
        self.assertNotIn('winner',comparison)
        self.assertEqual(b,before)
        unknown=scoped.focused_scope_result(p,b,'hedge',response(req,{'scope':'unresolved'}))
        self.assertEqual(scoped.compare_scope_results(p,'hedge',b,unknown,b,unknown)['status'],'unresolved')

    def test_scope_comparison_refuses_changed_semantics_and_tampered_receipts(self):
        p,q,body,b=case();req=scoped.focused_scope_request(p,b,'hedge')
        a=scoped.focused_scope_result(p,b,'hedge',response(req))
        changed=deepcopy(body);changed['contents'][0]['mode']='hypothetical'
        other=scoped.bind(p,q,changed,'different reading')
        z=scoped.focused_scope_result(p,other,'hedge',response(scoped.focused_scope_request(p,other,'hedge')))
        with self.assertRaisesRegex(InputError,'identical source, content and feature'):
            scoped.compare_scope_results(p,'hedge',b,a,other,z)
        z=deepcopy(a);z['content_ids']=['install']
        with self.assertRaisesRegex(InputError,'receipt changed'):
            scoped.compare_scope_results(p,'hedge',b,a,b,z)

    def test_scope_expansion_budget_stops_before_huge_request_without_losing_source(self):
        p,_,_,_=case();p=deepcopy(p)
        texts=['part'+str(i)+':'+chr(65+i)*1500 for i in range(8)]
        source=' '.join(texts)+' '+' '.join('qualifier'+str(i) for i in range(20))
        p['units'][0]['source'].update(start=0,end=len(source),text=source)
        q=scoped.request(p,p['units'][0]['unit_id'])
        body=dict(contents=[dict(id='c'+str(i),kind='state',mode='asserted',expression={'text':text}) for i,text in enumerate(texts)],
            features=[dict(id='f'+str(i),type='hedge',form='literal',expression={'text':'qualifier'+str(i),'start':source.index('qualifier'+str(i))},scopes=[['c0']]) for i in range(20)])
        b=scoped.bind(p,q,body,'budget control');before=deepcopy(b)
        scoped.selection_request(p,b)
        with self.assertRaisesRegex(InputError,'scope selection exceeds byte budget'):
            scoped.selection_request(p,b,candidate_policy=scoped.INCLUDE_SINGLE_CONTENTS)
        focused=scoped.focused_scope_request(p,b,'f0',candidate_policy=scoped.INCLUDE_SINGLE_CONTENTS)
        self.assertEqual(focused['state']['unit']['source']['text'],source)
        self.assertEqual(len(focused['questions']['scope']['criteria']),10)
        self.assertEqual(b,before)

    def test_links_keep_unsupported_candidates_and_explicit_coverage(self):
        p,_,_,b,_,s=selected_case()
        req=scoped.relationship_request(p,b,s)
        raw=dict(links=[dict(source='install',target='available',type='purpose',
            evidence={'text':"Let's install `texlive` to get `pdflatex`"}),
            dict(source='install',target='absence',type='purpose',evidence={'text':req['unit']['source']['text']})],content_issues=[])
        links=scoped.bind_links(p,b,s,req,raw,'control')
        lr=scoped.link_selection_request(p,b,s,links)
        result=scoped.observation(p,b,s,links,response(lr,{'l1':'unsupported','coverage':'incomplete'}))
        self.assertEqual(result['supported_links'],['l0'])
        self.assertEqual(result['links'][1]['choice'],'unsupported')
        self.assertEqual(result['relationship_coverage'],'incomplete')
        self.assertEqual(result['publication'],'shadow_only')
        self.assertEqual(len(result['contents']),4)

    def test_content_issue_blocks_links_and_stale_link_candidate_fails(self):
        p,_,_,b,_,s=selected_case();req=scoped.relationship_request(p,b,s)
        with self.assertRaisesRegex(InputError,'content review'):
            scoped.bind_links(p,b,s,req,dict(links=[],content_issues=[{'issue':'missing aim'}]),'control')
        links=scoped.bind_links(p,b,s,req,dict(links=[],content_issues=[]),'control')
        links['selection_hash']='other'
        with self.assertRaises(InputError):scoped.link_selection_request(p,b,s,links)

    def test_empty_inventory_does_not_invent_negative_relationship_coverage(self):
        p,q,_,_=case();b=scoped.bind(p,q,dict(contents=[],features=[]),'control')
        s=scoped.select(p,b,response(scoped.selection_request(p,b)))
        req=scoped.relationship_request(p,b,s)
        links=scoped.bind_links(p,b,s,req,dict(links=[],content_issues=[]),'control')
        lr=scoped.link_selection_request(p,b,s,links)
        self.assertEqual(set(lr['questions']),{'coverage'})
        self.assertEqual(scoped.observation(p,b,s,links,response(lr,{'coverage':'unresolved'}))['relationship_coverage'],'unresolved')

    def _files(self,root):
        p,_,body,_=case();directory=root/'experiment'
        stages.prepare_scoped_files(p,p['units'][0]['unit_id'],directory)
        file=root/'completion.json'
        def accept(stage,value):
            file.write_text(json.dumps(value),encoding='utf-8')
            return stages.accept_scoped_files(directory,stage,file,'authored control','fixture/'+stage)
        accept('contents',body)
        return directory,accept

    def test_file_pipeline_replays_all_receipts_and_never_publishes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory,accept=self._files(root)
            read=lambda name:json.loads((directory/name).read_text(encoding='utf-8'))
            raw=response(read('scope-selection-request.json'))
            self.assertTrue(accept('scopes',raw)['ready_for_relationships'])
            self.assertTrue(accept('scopes',raw)['reused'])
            accept('links',dict(links=[],content_issues=[]))
            final=accept('link-selection',response(read('link-selection-request.json'),{'coverage':'incomplete'}))
            self.assertEqual(final['new_provider_calls'],0)
            self.assertEqual(read('observation.json')['publication'],'shadow_only')
            self.assertFalse((directory/'assembled.json').exists())
            # Old files are not silently upgraded into the new protocol.
            with self.assertRaises(InputError):stages._load_files(directory)

    def test_rejected_scopes_saved_without_creating_relationship_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory,accept=self._files(root)
            req=json.loads((directory/'scope-selection-request.json').read_text(encoding='utf-8'))
            self.assertFalse(accept('scopes',response(req,{'f0':'unresolved'}))['ready_for_relationships'])
            self.assertFalse((directory/'relationship-request.json').exists())
            with self.assertRaisesRegex(InputError,'relationships blocked'):
                accept('links',dict(links=[],content_issues=[]))

    def test_conflicting_files_preflight_without_overwriting_original_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory,accept=self._files(root)
            req=json.loads((directory/'scope-selection-request.json').read_text(encoding='utf-8'))
            (directory/'selected-contents.json').write_text('{}',encoding='utf-8')
            with self.assertRaisesRegex(InputError,'artifact differs'):accept('scopes',response(req))
            self.assertFalse((directory/'scopes-delivery.json').exists())
            self.assertFalse((directory/'relationship-request.json').exists())

    def test_cli_exposes_opt_in_without_changing_old_commands(self):
        result=subprocess.run([sys.executable,'-m','tracker.work_content_stages','--help'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for command in ['prepare-scoped','accept-scopes','accept-link-selection','accept-audit','accept-relationships']:
            self.assertIn(command,result.stdout)


if __name__=='__main__':unittest.main()
