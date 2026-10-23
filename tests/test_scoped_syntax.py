from copy import deepcopy
import json
import tempfile
import unittest

from rilldex.scopes import extract
from tracker import work_content_bindings as scopes,work_content_stages as stages,work_syntax_evidence as syntax
from tracker.schema import InputError
from test_work_syntax_evidence import recorded,structural_case
from test_scoped_workflow import decision


class ScopedSyntaxTests(unittest.TestCase):
    def setUp(self):
        case,record=recorded()
        self.p,self.b,self.s=case['packet'],case['bound'],record['syntax']
        self.uid=self.b['unit_id']

    def test_structure_preserves_sentences_tokens_and_fixed_unit(self):
        before=deepcopy(self.p)
        plain=stages.scoped_content_request(self.p,self.uid)
        assisted=stages.scoped_content_request(self.p,self.uid,syntax=self.s)
        self.assertEqual(plain['unit'],assisted['unit'])
        hints=assisted['source_structure'];tokens=self.s['parsed']['tokens']
        self.assertEqual(hints['syntax_id'],self.s['id'])
        self.assertEqual([t['text'] for t in hints['tokens']],[t['text'] for t in tokens])
        self.assertGreater(len(hints['sentences']),1)
        self.assertIn('inspect',[tokens[i]['text'] for i in hints['predicate_token_ids']])
        self.assertEqual(self.p,before)
        bound=stages.bind_scoped_contents(self.p,assisted,dict(contents=self.b['raw_response']['contents']),'test',syntax=self.s)
        self.assertEqual(len(bound['contents']),len(self.b['contents']))
        with self.assertRaises(InputError):
            stages.bind_scoped_contents(self.p,assisted,dict(contents=[]),'test')

    def test_context_keeps_all_candidates_and_does_not_override_argmax(self):
        fid=self.b['features'][0]['id'];context=syntax.attachment_context(self.p,self.b,fid,self.s)
        self.assertEqual({p['content_id'] for p in context['pairs']},{c['id'] for c in self.b['contents']})
        self.assertTrue(any(p['paths'] for p in context['pairs']))
        self.assertTrue(any(p['path_status']=='not_comparable' for p in context['pairs']))
        plain=scopes.membership_scope_request(self.p,self.b,fid,argument_rule='direct_owner')
        enriched=scopes.membership_scope_request(self.p,self.b,fid,argument_rule='direct_owner',syntax=self.s)
        self.assertEqual(plain['state']['contents'],enriched['state']['contents'])
        result=scopes.membership_scope_result(self.p,self.b,fid,decision(enriched),argument_rule='direct_owner',syntax=self.s)
        self.assertEqual(result['supported_content_ids'],sorted(c['id'] for c in self.b['contents']))
        self.assertEqual(result['syntax_id'],self.s['id'])
        scopes.project_membership_scope(self.p,self.b,result,syntax=self.s)
        with self.assertRaises(InputError):scopes.project_membership_scope(self.p,self.b,result)

    def test_syntax_source_or_topology_change_is_rejected(self):
        bad=deepcopy(self.s);bad['parsed']['tokens'][0]['text']='Changed'
        with self.assertRaises(InputError):stages.scoped_content_request(self.p,self.uid,syntax=bad)
        with self.assertRaises(InputError):syntax.attachment_context(self.p,self.b,'missing',self.s)

    def test_unicode_absolute_offsets_in_sentence_hints(self):
        p,b,parsed=structural_case();record=syntax.bind(p,b,parsed)
        hints=syntax.outline(p,b,record)
        self.assertEqual(hints['sentences'][0]['text'],'🔬 Alpha. Beta.')
        self.assertEqual(hints['sentences'][0]['start'],len('Earlier text. '))

    def test_assisted_generation_token_features_resume_and_version_pin(self):
        calls=[]
        def propose(payload):
            request=payload['request'];calls.append(request['stage'])
            if request['stage']=='contents':
                self.assertEqual(request['source_structure']['syntax_id'],self.s['id'])
                body=dict(contents=self.b['raw_response']['contents'])
            else:
                self.assertEqual(request['syntax_id'],self.s['id'])
                self.assertNotIn('candidate_groups',request)
                self.assertNotIn('scopes',request['response_format']['features'][0])
                features=[]
                for feature in self.b['features']:
                    tokens=[t for t in self.s['parsed']['tokens'] if feature['expression']['start']<=t['start']<t['end']<=feature['expression']['end']]
                    f={k:deepcopy(v) for k,v in feature.items() if k!='expression'}
                    if 'scopes' not in request['response_format']['features'][0]:f.pop('scopes')
                    f['expression']=dict(token_start=tokens[0]['id'],token_end=tokens[-1]['id']+1)
                    features.append(f)
                body=dict(features=features)
            return dict(raw_output=json.dumps(body),usage={})
        with tempfile.TemporaryDirectory() as root:
            options=dict(candidate_transport=propose,candidate_identity='recorded-structure/1',decision_transport=decision,
                candidate_calls=2,decision_calls=0,input_bytes=1000000,syntax=self.s)
            first=extract(self.p,self.uid,root,**options)
            self.assertEqual(first['status'],'budget_reached')
            self.assertEqual(first['review']['pending_feature_ids'],[f['id'] for f in self.b['features']])
            options['decision_calls']=32
            final=extract(self.p,self.uid,root,**options)
            self.assertEqual(final['status'],'complete')
            self.assertEqual(calls,['contents','features'])
            self.assertTrue(all(r['syntax_id']==self.s['id'] for r in final['review']['receipts']))
            extract(self.p,self.uid,root,**options)
            self.assertEqual(calls,['contents','features'])
            options['syntax']=None
            with self.assertRaises(InputError):extract(self.p,self.uid,root,**options)


if __name__=='__main__':unittest.main()
