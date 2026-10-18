from copy import deepcopy
import json
from pathlib import Path
import re
import unittest

from tracker import graph_store, work_mentions, work_content_bindings as scoped
from tracker import work_feature_membership as membership, work_syntax_evidence as syntax
from tracker.adapters import normalize
from tracker.portable import chat_document
from tracker.schema import InputError, digest


ROOT=Path(__file__).parent/'fixtures/feature-membership'


def recorded(name='shared-method'):
    controls=json.loads((ROOT/'recorded-controls.json').read_text(encoding='utf-8'))['cases']
    records=json.loads((ROOT/'syntax-context.json').read_text(encoding='utf-8'))['cases']
    case=next(c for c in controls if c['case']==name)
    record=next(c for c in records if c['case']==name)
    return case,record


def structural_case():
    prefix='Earlier text. ';text='🔬 Alpha. Beta.'
    run=normalize(chat_document([dict(role='assistant',content=prefix+text)]))[0]
    graph=graph_store.build(run);event=run['events'][0]
    source=dict(event_id=event['id'],start=len(prefix),end=len(prefix)+len(text),text=text)
    graph['nodes'].append(dict(id='unit',kind='unit',activity='orient',event_index=0,
        trajectory_id=event['trajectory_id'],properties=dict(kind='semantic',actor='agent',status='selected',source=source)))
    graph['counts']['nodes']=len(graph['nodes']);graph.pop('id');graph['id']='graph-'+digest(graph)
    p=work_mentions.packet(graph,['unit'])
    body=dict(contents=[dict(id='alpha',kind='state',mode='proposed',expression=dict(text='Alpha.')),
                        dict(id='beta',kind='state',mode='proposed',expression=dict(text='Beta.'))],
              features=[dict(id='feature',type='method',form='literal',expression=dict(text='🔬'),scopes=[['alpha']])])
    b=scoped.bind(p,scoped.request(p,'unit'),body,'structural test only')
    tokens=[dict(id=i,text=m.group(),start=source['start']+m.start(),end=source['start']+m.end(),
                 sentence=0,head=0,relation='ROOT' if i==0 else 'dep',pos='X')
            for i,m in enumerate(re.finditer(r'\S+',text))]
    parsed=dict(source=source,tokens=tokens,parser=dict(name='test',version='1',model='authored',
        model_version='1',language='en',label_scheme='structural test tokens, not a linguistic parse'))
    return p,b,parsed


def selected(p,b,fid):
    req=membership.request(p,b,fid)
    raw=dict(model=req['model'],answers={key:dict(type='choice',probabilities={
        value:float(value==('separable' if key=='scope_shape' else 'attached'))
        for value in question['criteria']}) for key,question in req['questions'].items()})
    return membership.resolve(p,b,fid,raw)


class SyntaxEvidenceTests(unittest.TestCase):
    def test_recorded_local_parser_output_replays_without_optional_dependencies(self):
        for name in ['shared-method','state-hedge','shared-negation','joint-negation']:
            with self.subTest(name=name):
                case,stored=recorded(name);p,b=case['packet'],case['bound']
                record=syntax.bind(p,b,stored['syntax']['parsed'])
                self.assertEqual(record,stored['syntax'])
                result=syntax.review(p,b,case['feature_id'],case['arms']['membership']['result'],record)
                self.assertEqual(digest(result),stored['review_hash'])
                self.assertEqual(result['verdict'],'not_assessed')
                self.assertEqual(result['publication'],'review_only')

    def test_paths_preserve_predicted_direction_and_source_words(self):
        case,stored=recorded();p,b=case['packet'],case['bound']
        result=syntax.review(p,b,'attachment',case['arms']['membership']['result'],stored['syntax'])
        validate=next(pair for pair in result['pairs'] if pair['content_id']=='validate')
        path=validate['dependency_paths'][0]
        self.assertEqual([result['tokens'][i]['text'] for i in path['token_ids']],['Using','inspect','validate'])
        self.assertEqual([(edge['relation'],edge['direction']) for edge in path['edges']],
                         [('advcl','to_head'),('conj','to_child')])
        publish=next(pair for pair in result['pairs'] if pair['content_id']=='publish')
        self.assertEqual(publish['status'],'separate_sentences')
        self.assertEqual(publish['dependency_paths'],[])
        self.assertEqual(publish['review_flags'],[])

    def test_flagged_positive_is_not_published_or_reclassified(self):
        case,stored=recorded('shared-negation');p,b=case['packet'],case['bound']
        decision=case['arms']['membership']['result'];before=deepcopy((p,b,decision,stored))
        result=syntax.review(p,b,'attachment',decision,stored['syntax'])
        listing=next(pair for pair in result['pairs'] if pair['content_id']=='list')
        self.assertEqual(listing['membership_choice'],'attached')
        self.assertIsNone(listing['selected_scope_member'])
        self.assertEqual(listing['review_flags'],['positive_across_predicted_sentences'])
        self.assertEqual((p,b,decision,stored),before)
        self.assertEqual(result['verdict'],'not_assessed')

    def test_changed_scope_options_reuse_syntax_and_identical_membership_request(self):
        case,stored=recorded();p,b=case['packet'],case['bound']
        body=deepcopy(b['raw_response']);body['features'][0]['scopes']=[['publish']]
        changed=scoped.bind(p,scoped.request(p,b['unit_id']),body,'alternate candidate scopes')
        self.assertEqual(membership.request(p,b,'attachment'),membership.request(p,changed,'attachment'))
        decision=membership.resolve(p,changed,'attachment',case['arms']['membership']['response'])
        result=syntax.review(p,changed,'attachment',decision,stored['syntax'])
        self.assertEqual(result['syntax_id'],stored['syntax']['id'])
        self.assertEqual(decision['content_ids'],['inspect','validate'])

    def test_unicode_offsets_remain_absolute_source_codepoints(self):
        p,b,parsed=structural_case();record=syntax.bind(p,b,parsed)
        self.assertEqual(record['parsed']['tokens'][0]['end']-record['parsed']['tokens'][0]['start'],1)
        result=syntax.review(p,b,'feature',selected(p,b,'feature'),record)
        self.assertEqual(result['feature']['expression']['start'],len('Earlier text. '))
        self.assertEqual(result['feature']['status'],'aligned')
        wrong=deepcopy(parsed);wrong['tokens'][0]['end']+=1
        with self.assertRaises(InputError):syntax.bind(p,b,wrong)

    def test_partial_token_quotes_are_not_silently_expanded(self):
        p,b,parsed=structural_case();body=deepcopy(b['raw_response'])
        body['features'][0]['expression']={'text':'Alpha'}
        changed=scoped.bind(p,scoped.request(p,'unit'),body,'partial token control')
        record=syntax.bind(p,changed,parsed)
        result=syntax.review(p,changed,'feature',selected(p,changed,'feature'),record)
        self.assertEqual(result['feature']['status'],'unaligned_token_boundary')
        self.assertTrue(all(pair['status']=='unaligned_token_boundary' for pair in result['pairs']))
        self.assertTrue(all(not pair['dependency_paths'] for pair in result['pairs']))
        self.assertEqual(result['feature']['expression']['text'],'Alpha')

    def test_multiple_sentence_scope_stays_explicit(self):
        case,stored=recorded();p,b=case['packet'],case['bound'];body=deepcopy(b['raw_response'])
        body['features'][0]['expression']={'text':p['units'][0]['source']['text']}
        changed=scoped.bind(p,scoped.request(p,b['unit_id']),body,'wide expression control')
        result=syntax.review(p,changed,'attachment',selected(p,changed,'attachment'),stored['syntax'])
        self.assertTrue(all(pair['status']=='multiple_sentence_span' for pair in result['pairs']))
        self.assertTrue(all(not pair['dependency_paths'] for pair in result['pairs']))

    def test_missing_altered_or_overlapping_text_is_rejected(self):
        p,b,parsed=structural_case()
        for alteration in ['omitted','text','overlap','source','tail']:
            bad=deepcopy(parsed)
            if alteration=='omitted':bad['tokens'].pop(0)
            if alteration=='text':bad['tokens'][1]['text']='Other.'
            if alteration=='overlap':bad['tokens'][1]['start']=bad['tokens'][0]['start']
            if alteration=='source':bad['source']['text']='Changed.'
            if alteration=='tail':bad['tokens'].pop()
            with self.subTest(alteration=alteration),self.assertRaises(InputError):syntax.bind(p,b,bad)

    def test_invalid_or_cyclic_dependency_topology_is_rejected(self):
        p,b,parsed=structural_case()
        for alteration in ['foreign','boolean','cycle','two_roots','no_root','cross_sentence']:
            bad=deepcopy(parsed)
            if alteration=='foreign':bad['tokens'][1]['head']=100
            if alteration=='boolean':bad['tokens'][1]['head']=True
            if alteration=='cycle':bad['tokens'][1]['head']=2;bad['tokens'][2]['head']=1
            if alteration=='two_roots':bad['tokens'][1]['head']=1
            if alteration=='no_root':bad['tokens'][0]['head']=1
            if alteration=='cross_sentence':bad['tokens'][2]['sentence']=1
            with self.subTest(alteration=alteration),self.assertRaises(InputError):syntax.bind(p,b,bad)

    def test_parser_identity_and_receipts_are_required(self):
        p,b,parsed=structural_case()
        for field in parsed['parser']:
            bad=deepcopy(parsed);bad['parser'].pop(field)
            with self.subTest(field=field),self.assertRaises(InputError):syntax.bind(p,b,bad)
        record=syntax.bind(p,b,parsed);record['parsed']['parser']['version']='other'
        with self.assertRaisesRegex(InputError,'receipt or source changed'):
            syntax.review(p,b,'feature',selected(p,b,'feature'),record)
        record=syntax.bind(p,b,parsed);decision=selected(p,b,'feature')
        decision['content_ids']=[]
        with self.assertRaisesRegex(InputError,'membership receipt changed'):syntax.review(p,b,'feature',decision,record)

    def test_adapter_rejects_unparsed_documents_before_accessing_tokens(self):
        p,b,parsed=structural_case()
        class Document:
            text=parsed['source']['text']
            def has_annotation(self, name, *, require_complete=False):return not require_complete
        with self.assertRaisesRegex(InputError,'requires dependency'):
            syntax.from_spacy(p,b,Document(),library_version='1',model='test',model_version='1')


if __name__=='__main__':unittest.main()
