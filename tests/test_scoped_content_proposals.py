"""Staged source extraction and exact repeated-quote addressing."""
from copy import deepcopy
import unittest
from tracker import graph_store, work_content_stages as stages, work_mentions, work_content_bindings as scoped
from tracker.adapters import normalize
from tracker.portable import chat_document
from tracker.schema import InputError, digest
from test_work_syntax_evidence import structural_case, recorded
from tracker import work_syntax_evidence as syntax


def case():
    """Authored source binding control; independent of local research archives."""
    text = ("It seems `pdflatex` is not installed. Let's install `texlive` to get "
            "`pdflatex` and convert the Markdown file to a PDF.")
    run = normalize(chat_document([dict(role='assistant', content=text)]))[0]
    graph = graph_store.build(run); event = run['events'][0]
    source = dict(event_id=event['id'], start=0, end=len(text), text=text)
    graph['nodes'].append(dict(id='unit', kind='unit', activity='orient', event_index=0,
        trajectory_id=event['trajectory_id'], properties=dict(
            kind='semantic', actor='agent', status='selected', source=source)))
    graph['counts']['nodes'] = len(graph['nodes'])
    graph.pop('id'); graph['id'] = 'graph-' + digest(graph)
    packet = work_mentions.packet(graph, ['unit'])
    body = dict(contents=[
        dict(id='absence', kind='state', mode='asserted', expression={'text': '`pdflatex` is not installed'}),
        dict(id='install', kind='operation', mode='proposed', expression={'text': 'install `texlive`'}),
        dict(id='available', kind='state', mode='proposed', expression={'text': 'get `pdflatex`'}),
        dict(id='convert', kind='operation', mode='proposed', expression={'text': 'convert the Markdown file to a PDF'})],
        features=[
            dict(id='hedge', type='hedge', form='literal', expression={'text': 'It seems'}, scopes=[['absence'], ['install']]),
            dict(id='negative', type='negation', form='literal', expression={'text': 'not'}, scopes=[['absence'], ['available']]),
            dict(id='intention', type='intent', form='literal', expression={'text': "Let's"}, scopes=[['install', 'available', 'convert'], ['install']])])
    req = scoped.request(packet, 'unit')
    bound = scoped.bind(packet, req, body, 'authored structural control')
    return packet, req, body, bound


class ScopedProposalTests(unittest.TestCase):
    def token_case(self):
        p,b,parsed=structural_case()
        c=stages.bind_scoped_contents(p,stages.scoped_content_request(p,b['unit_id']),
            {'contents':b['raw_response']['contents']},'frozen')
        s=syntax.bind(p,c,parsed)
        req=stages.scoped_feature_request(p,c,syntax=s)
        body={'features':[dict(id='symbol',type='method',form='literal',
            expression=dict(token_start=0,token_end=1),scopes=[['alpha']])]}
        return p,c,s,req,body

    def test_token_proposal_keeps_exact_unicode_offsets_and_frozen_work(self):
        p,c,s,req,body=self.token_case();before=deepcopy((p,c,s,req,body))
        b=stages.bind_scoped_features(p,c,req,body,'token proposer',syntax=s)
        self.assertEqual(b['features'][0]['expression'],dict(text='🔬',start=14,end=15,
            event_id=req['unit']['source']['event_id']))
        self.assertEqual(b['contents'],c['contents'])
        self.assertEqual((p,c,s,req,body),before)
        scoped.checked(p,b)

    def test_token_ranges_retain_original_spacing(self):
        p,c,s,req,body=self.token_case()
        body['features'][0]['expression']={'token_start':0,'token_end':3}
        b=stages.bind_scoped_features(p,c,req,body,'token proposer',syntax=s)
        self.assertEqual(b['features'][0]['expression']['text'],'🔬 Alpha. Beta.')

    def test_invalid_token_ranges_are_not_repaired(self):
        p,c,s,req,body=self.token_case()
        for value in [{'token_start':-1,'token_end':1},{'token_start':1,'token_end':1},
                      {'token_start':False,'token_end':1},{'token_start':0,'token_end':4},
                      {'token_start':0.0,'token_end':1},{'text':'Alpha.'}]:
            body['features'][0]['expression']=value
            with self.subTest(value=value),self.assertRaises(InputError):
                stages.bind_scoped_features(p,c,req,body,'token proposer',syntax=s)

    def test_token_request_cannot_be_rebound_without_or_with_changed_syntax(self):
        p,c,s,req,body=self.token_case()
        with self.assertRaises(InputError):stages.bind_scoped_features(p,c,req,body,'token proposer')
        changed=deepcopy(s);changed['parsed']['tokens'][0]['text']='other'
        with self.assertRaises(InputError):
            stages.bind_scoped_features(p,c,req,body,'token proposer',syntax=changed)

    def test_parser_groups_are_options_not_accepted_attachments(self):
        fixture,record=recorded();p,b=fixture['packet'],fixture['bound']
        c=stages.bind_scoped_contents(p,stages.scoped_content_request(p,b['unit_id']),
            {'contents':b['raw_response']['contents']},'frozen')
        req=stages.scoped_feature_request(p,c,syntax=record['syntax'])
        self.assertEqual([g['content_ids'] for g in req['candidate_groups']],[['inspect','validate']])
        self.assertFalse(c['features'])

    def test_two_stages_reuse_the_existing_bound_representation(self):
        p, _, body, _ = case(); uid=p['units'][0]['unit_id']
        content_req=stages.scoped_content_request(p,uid)
        content=stages.bind_scoped_contents(p,content_req,{'contents':body['contents']},'content proposer')
        frozen=deepcopy(content)
        req=stages.scoped_feature_request(p,content)
        combined=stages.bind_scoped_features(p,content,req,{'features':body['features']},'feature proposer')
        self.assertEqual(combined,scoped.bind(p,scoped.request(p,uid),body,'feature proposer'))
        self.assertEqual(content,frozen)
        self.assertEqual(req['contents'],content['contents'])
        self.assertEqual(set(content_req['response_format']),{'contents'})
        self.assertEqual(set(req['response_format']),{'features'})

    def test_feature_stage_cannot_replace_contents_or_use_another_request(self):
        p, _, body, _=case(); uid=p['units'][0]['unit_id']
        c=stages.bind_scoped_contents(p,stages.scoped_content_request(p,uid),{'contents':body['contents']},'one')
        req=stages.scoped_feature_request(p,c)
        with self.assertRaises(InputError):
            stages.bind_scoped_features(p,c,req,body,'two')
        altered=deepcopy(req);altered['unit']['source']['text']='another source'
        with self.assertRaises(InputError):
            stages.bind_scoped_features(p,c,altered,{'features':body['features']},'two')

    def test_surrounding_quote_locates_a_repeated_expression_without_offset_guessing(self):
        unit={'source':{'text':'α🙂 Read item. Then edit item.','event_id':'e1','start':100}}
        raw={'text':'item','within':'edit item'}
        out=work_mentions.quote(raw,unit)
        self.assertEqual(out,{'text':'item','event_id':'e1','start':124,'end':128})
        self.assertEqual(raw,{'text':'item','within':'edit item'})
        self.assertEqual(work_mentions.quote({'text':'item','start':24},unit),out)

    def test_ambiguous_or_fabricated_surroundings_are_not_repaired(self):
        unit={'source':{'text':'item then item. item then item.','event_id':'e1','start':0}}
        for raw in ({'text':'item','within':'item then item.'},
                    {'text':'item','within':unit['source']['text']},
                    {'text':'item','within':'invented item'},
                    {'text':'missing','within':unit['source']['text']},
                    {'text':'item','within':'','start':0},
                    {'text':'item','within':None}):
            with self.subTest(raw=raw),self.assertRaises(InputError):work_mentions.quote(raw,unit)

    def test_same_word_in_different_source_contexts_remains_distinct(self):
        p, req, body, _=case()
        body['features'] += [
            dict(id='first',type='subject',form='literal',expression={'text':'`pdflatex`','within':'`pdflatex` is not installed'},scopes=[['absence']]),
            dict(id='second',type='subject',form='literal',expression={'text':'`pdflatex`','within':'get `pdflatex`'},scopes=[['available']])]
        b=scoped.bind(p,req,body,'repeated subjects')
        self.assertNotEqual(b['features'][-1]['expression']['start'],b['features'][-2]['expression']['start'])
        scoped.checked(p,b)


if __name__=='__main__':unittest.main()
