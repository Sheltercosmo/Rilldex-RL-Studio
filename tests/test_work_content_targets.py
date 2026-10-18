from copy import deepcopy
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from tracker import graph_store, work_mentions, work_content_bindings as scoped
from tracker import work_content_targets as targets, work_syntax_evidence as syntax
from tracker.adapters import normalize
from tracker.portable import chat_document
from tracker.schema import InputError, digest


def case(text='Switch to a metal watch, preferably white if available.\n\nContinue.',
         owner='Switch to a metal watch, preferably white if available',
         feature='if available'):
    prefix='Earlier 🔬. '
    run=normalize(chat_document([dict(role='assistant',content=prefix+text)]))[0]
    graph=graph_store.build(run); event=run['events'][0]
    source=dict(event_id=event['id'],start=len(prefix),end=len(prefix)+len(text),text=text)
    graph['nodes'].append(dict(id='unit',kind='unit',activity='orient',event_index=0,
        trajectory_id=event['trajectory_id'],properties=dict(kind='semantic',actor='agent',status='selected',source=source)))
    graph['counts']['nodes']=len(graph['nodes']); graph.pop('id'); graph['id']='graph-'+digest(graph)
    p=work_mentions.packet(graph,['unit'])
    body=dict(contents=[dict(id='switch',kind='operation',mode='proposed',expression=dict(text=owner))],
        features=[dict(id='condition',type='condition',form='literal',expression=dict(text=feature),scopes=[['switch']])])
    return p,scoped.bind(p,scoped.request(p,'unit'),body,'authored structural control, not semantic gold')


def proposed(p,b,*expressions):
    return targets.bind(p,b,'switch',[dict(expression=dict(text=s)) for s in expressions],producer='structural test')


def response(req, choice, *, low_margin=False):
    keys=list(req['questions']['target']['criteria'])
    weights={k:1 for k in keys}
    weights[choice]=1.01 if low_margin else 10
    total=sum(weights.values())
    answer=dict(type='choice',probabilities={k:v/total for k,v in weights.items()})
    if low_margin:
        # Provider convenience fields must not override the probability argmax.
        answer.update(choice='whole_content',confidence=1)
    return dict(model=req['model'],answers=dict(target=answer))


def parsed(p,b,text_heads):
    """Authored token-tree topology for boundary tests, not a parser reference."""
    source=p['units'][0]['source']; words=list(re.finditer(r'\w+|[^\w\s]|\n+',source['text']))
    tokens=[dict(id=i,text=m.group(),start=source['start']+m.start(),end=source['start']+m.end(),
        sentence=0,head=0,relation='ROOT' if i==0 else 'dep',pos='X') for i,m in enumerate(words)]
    for text,head,pos in text_heads:
        t=next(t for t in tokens if t['text']==text)
        t.update(head=next(t['id'] for t in tokens if t['text']==head),pos=pos)
    return syntax.bind(p,b,dict(source=source,tokens=tokens,parser=dict(name='authored',version='1',
        model='structural-control',model_version='1',language='en',label_scheme='structural test only')))


class ContentTargetTests(unittest.TestCase):
    def test_recorded_development_controls_replay_without_parser_or_transport(self):
        fixture=Path(__file__).parent/'fixtures/feature-membership/content-detail-targets.json'
        cases=json.loads(fixture.read_text(encoding='utf-8'))['cases']
        self.assertEqual(len(cases),4)
        with patch('tracker.jev.JevClient._post',side_effect=AssertionError('offline replay')):
            for c in cases:
                with self.subTest(case=c['case']):
                    p,b,t,f=c['packet'],c['bound'],c['targets'],c['feature_id']
                    self.assertEqual(targets.request(p,b,f,t),c['request'])
                    self.assertEqual(digest(c['request']),c['receipt']['request_hash'])
                    self.assertEqual(digest(c['response']),c['receipt']['response_hash'])
                    if c['case']!='retail-missing-detail':
                        self.assertEqual(targets.from_syntax(p,b,c['content_id'],c['syntax']),t)
                    decision=targets.resolve(p,b,f,t,c['response'])
                    self.assertEqual(decision,c['result'])
                    self.assertEqual(targets.project(p,b,f,t,decision),c['projection'])
                    if 'status' in c['reference']:
                        self.assertEqual(decision['status'],c['reference']['status'])
                    else:
                        self.assertEqual(decision['detail']['expression']['text'],c['reference']['text'])

    def test_detail_preserves_work_and_source_without_creating_actions(self):
        p,b=case(); t=proposed(p,b,'preferably white if available','a metal watch')
        before=deepcopy((p,b,t)); req=targets.request(p,b,'condition',t)
        part=next(r for r in t['parts'] if r['expression']['text']=='preferably white if available')
        decision=targets.resolve(p,b,'condition',t,response(req,part['id'],low_margin=True))
        view=targets.project(p,b,'condition',t,decision)
        self.assertEqual(view['content'],b['contents'][0])
        self.assertEqual(view['source'],p['units'][0]['source'])
        self.assertEqual(view['qualification']['target']['expression'],part['expression'])
        self.assertEqual(view['qualification']['target']['kind'],'content_detail')
        self.assertEqual(view['qualification']['propagation'],'none')
        self.assertEqual(view['qualification']['execution_status'],'not_established_by_prose')
        self.assertEqual(view['new_work_items'],[]); self.assertEqual(view['new_base_units'],[])
        self.assertEqual(view['publication'],'review_only')
        self.assertEqual((p,b,t),before)

    def test_whole_missing_outside_and_ambiguous_targets_remain_distinct(self):
        p,b=case(); t=proposed(p,b); req=targets.request(p,b,'condition',t)
        for choice in ['whole_content','missing_detail','outside_content','unresolved']:
            with self.subTest(choice=choice):
                decision=targets.resolve(p,b,'condition',t,response(req,choice))
                view=targets.project(p,b,'condition',t,decision)
                self.assertEqual(view['status'],choice)
                if choice=='whole_content':
                    self.assertEqual(view['qualification']['target']['expression'],b['contents'][0]['expression'])
                else:
                    self.assertIsNone(view['qualification'])

    def test_details_cannot_be_whole_owner_outside_or_duplicate(self):
        p,b=case()
        for expressions in [(b['contents'][0]['expression']['text'],),('Continue',),('white','white')]:
            with self.subTest(expressions=expressions),self.assertRaises(InputError):proposed(p,b,*expressions)

    def test_unicode_and_repeated_quotes_require_exact_occurrence(self):
        p,b=case('Check 🔬 then check 🔬 if available.','Check 🔬 then check 🔬','if available')
        with self.assertRaisesRegex(InputError,'exactly once'):proposed(p,b,'🔬')
        start=p['units'][0]['source']['text'].rindex('🔬')
        t=targets.bind(p,b,'switch',[dict(expression=dict(text='🔬',start=start))],producer='explicit occurrence')
        span=t['parts'][0]['expression']
        self.assertEqual(span['start'],len('Earlier 🔬. ')+start)
        self.assertEqual(span['end']-span['start'],1)

    def test_changed_candidate_provenance_or_receipt_is_rejected(self):
        p,b=case(); t=proposed(p,b,'preferably white if available'); req=targets.request(p,b,'condition',t)
        decision=targets.resolve(p,b,'condition',t,response(req,t['parts'][0]['id']))
        for field,value in [('producer','other'),('content_id','unknown'),('parts',[])]:
            changed=deepcopy(t); changed[field]=value
            with self.subTest(field=field),self.assertRaises(InputError):targets.request(p,b,'condition',changed)
        changed=deepcopy(decision); changed['status']='whole_content'
        with self.assertRaises(InputError):targets.project(p,b,'condition',t,changed)
        rebuilt=targets.bind(p,b,'switch',t['raw_parts'],producer='different proposer')
        with self.assertRaises(InputError):targets.project(p,b,'condition',rebuilt,decision)
        raw=response(req,'whole_content'); raw['model']='other-model'
        with self.assertRaises(InputError):targets.resolve(p,b,'condition',t,raw)

    def test_syntax_trims_only_boundary_whitespace(self):
        p,b=case('Switch preferably white if available\n\nContinue.',
                 'Switch preferably white if available')
        record=parsed(p,b,[('white','Switch','ADJ'),('preferably','white','ADV'),
            ('available','white','ADJ'),('if','available','SCONJ'),('\n\n','available','SPACE')])
        t=targets.from_syntax(p,b,'switch',record)
        self.assertIn('preferably white if available',[part['expression']['text'] for part in t['parts']])
        # An out-of-owner content token cannot be clipped as if it were blank.
        raw=deepcopy(record['parsed']); tokens=raw['tokens']
        next(t for t in tokens if t['text']=='Continue')['head']=next(t['id'] for t in tokens if t['text']=='available')
        other=targets.from_syntax(p,b,'switch',syntax.bind(p,b,raw))
        self.assertNotIn('preferably white if available',[part['expression']['text'] for part in other['parts']])

    def test_syntax_does_not_trim_punctuation_outside_owner(self):
        p,b=case('Switch white if available.','Switch white if available')
        record=parsed(p,b,[('white','Switch','ADJ'),('available','white','ADJ'),
            ('if','available','SCONJ'),('.','available','PUNCT')])
        t=targets.from_syntax(p,b,'switch',record)
        self.assertEqual(t['parts'],[])

    def test_discontinuous_subtree_is_not_expanded_over_unrelated_tokens(self):
        p,b=case('Switch white or red if available.','Switch white or red if available')
        record=parsed(p,b,[('white','Switch','ADJ'),('red','white','ADJ')])
        t=targets.from_syntax(p,b,'switch',record)
        self.assertNotIn('white or red',[part['expression']['text'] for part in t['parts']])

    def test_local_syntax_receipt_cannot_be_altered(self):
        p,b=case(); record=parsed(p,b,[('white','Switch','ADJ')])
        record['parsed']['parser']['model_version']='changed'
        with self.assertRaisesRegex(InputError,'receipt or source changed'):targets.from_syntax(p,b,'switch',record)

    def test_parts_are_stable_when_candidate_order_changes(self):
        p,b=case()
        a=proposed(p,b,'preferably white if available','a metal watch')
        z=proposed(p,b,'a metal watch','preferably white if available')
        self.assertEqual(a['parts'],z['parts'])
        self.assertEqual(targets.request(p,b,'condition',a),targets.request(p,b,'condition',z))


if __name__=='__main__':unittest.main()
