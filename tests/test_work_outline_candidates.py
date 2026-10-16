from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import graph_store, work_outline, work_outline_candidates as candidates
from tracker.schema import InputError, digest
from tracker.store import Store
from test_work_outline import fixture


def response_for(document):
    row={k:deepcopy(document[k]) for k in ('items','links','decisions')}
    for key in row:
        for value in row[key]:value['evidence']={k:value['evidence'][k] for k in ('event_id','text')}
    return {'candidates':[dict(reading='Authored control, not a semantic accuracy reference.',**row)]}


def decision(req, values=None, provider_choice='unresolved'):
    keys=list(req['questions']['choice']['criteria'])
    probabilities=values or {key:float(i==0) for i,key in enumerate(keys)}
    return {'model':req['model'],'answers':{'choice':{'type':'choice','probabilities':probabilities,
        'choice':provider_choice,'confidence':0}}}


class WorkOutlineCandidateTests(unittest.TestCase):
    def setup_case(self):
        _,graph,document,refs=fixture();packet=candidates.request(graph)
        response=response_for(document);bound=candidates.bind(graph,packet,response,'authored-test/1')
        req=candidates.selection_request(packet,bound)
        return graph,packet,response,req,refs

    def test_prefix_contains_no_future_or_inherited_labels(self):
        graph,_,_,_,refs=self.setup_case();packet=candidates.request(graph,refs[2]['event_id'])
        self.assertEqual(len(packet['records']),3)
        self.assertNotIn('activity',packet['records'][1]);self.assertNotIn('work_outline',str(packet))
        self.assertEqual(packet['cutoff_event_index'],2)

    def test_missing_future_quote_cannot_be_bound(self):
        graph,_,response,_,refs=self.setup_case();packet=candidates.request(graph,refs[2]['event_id'])
        with self.assertRaises(InputError):candidates.bind(graph,packet,response,'authored-test/1')

    def test_bad_quote_identifies_candidate_and_row_before_selection(self):
        graph,packet,response,_,_=self.setup_case()
        response['candidates'][0]['decisions'][1]['evidence']['text']='Not present in the source'
        with self.assertRaisesRegex(InputError,r'Candidate 0, decisions\[1\]'):
            candidates.bind(graph,packet,response,'authored-test/1')

    def test_changed_packet_is_rejected(self):
        graph,packet,response,_,_=self.setup_case();packet['records'][0]['text']='Changed request'
        with self.assertRaises(InputError):candidates.bind(graph,packet,response,'authored-test/1')

    def test_raw_argmax_ignores_reported_choice_and_confidence(self):
        graph,packet,response,req,_=self.setup_case()
        doc,choice,_,_=candidates.selected_document(graph,packet,response,'authored-test/1',decision(req))
        self.assertEqual(choice,'c0');self.assertEqual(len(doc['items']),3)

    def test_rejection_cannot_materialize_an_outline(self):
        graph,packet,response,req,_=self.setup_case()
        result=decision(req,{'c0':.1,'no_suitable_candidate':.8,'unresolved':.1},'c0')
        with self.assertRaises(InputError):candidates.fork_selected(graph,packet,response,'authored-test/1',result)

    def test_selected_outline_replays_and_keeps_units_unchanged(self):
        graph,packet,response,req,_=self.setup_case();original=deepcopy(graph)
        result=candidates.fork_selected(graph,packet,response,'authored-test/1',decision(req))
        self.assertEqual(candidates.audit_selection(result)['choice'],'c0')
        self.assertEqual(work_outline.project(result,6)['basis'],'model_selected')
        self.assertEqual([n for n in result['nodes'] if not n['kind'].startswith('work_outline_')],graph['nodes'])
        self.assertEqual(graph,original)

    def test_tampered_receipt_and_annotation_cannot_pass_audit(self):
        graph,packet,response,req,_=self.setup_case()
        result=candidates.fork_selected(graph,packet,response,'authored-test/1',decision(req))
        result['semantic_context']['work_outline']['selection']['choice']='unresolved'
        with self.assertRaises(InputError):work_outline.checked(result)

    def test_review_of_selection_has_separate_attribution(self):
        graph,packet,response,req,_=self.setup_case()
        result=candidates.fork_selected(graph,packet,response,'authored-test/1',decision(req))
        draft=work_outline.template(result)['document'];self.assertEqual(draft['revision']['author'],'')
        draft['revision']={'author':'Researcher','note':'Independently reviewed the supplied annotations.'}
        reviewed=work_outline.fork(result,draft)
        self.assertNotIn('selection',reviewed['semantic_context']['work_outline'])
        self.assertEqual(work_outline.project(reviewed,6)['basis'],'reviewed')

    def test_ambiguous_quote_and_invalid_relations_are_rejected(self):
        graph,packet,response,_,_=self.setup_case()
        response['candidates'][0]['links'][0]['from']='missing'
        with self.assertRaises(InputError):candidates.bind(graph,packet,response,'authored-test/1')
        with self.assertRaises(InputError):candidates.bind_quote({'event_id':'e','text':'same'},{'e':{'text':'same same'}})

    def test_unknown_usage_stays_unknown_and_bad_usage_is_rejected(self):
        graph,packet,response,_,_=self.setup_case()
        self.assertIsNone(candidates.bind(graph,packet,response,'authored-test/1')['reported_usage'])
        response['usage']={'total_tokens':True}
        with self.assertRaises(InputError):candidates.bind(graph,packet,response,'authored-test/1')

    def test_saved_selection_reuses_identity_and_retains_original_graph(self):
        run,graph,document,_=fixture();packet=candidates.request(graph);response=response_for(document)
        req=candidates.selection_request(packet,candidates.bind(graph,packet,response,'authored-test/1'))
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'db.sqlite');store.add([run])
            with store.connect() as connection:graph_store.save(connection,graph)
            first=candidates.save_selected(store,packet,response,'authored-test/1',decision(req))
            self.assertEqual(first,candidates.save_selected(store,packet,response,'authored-test/1',decision(req)))
            self.assertEqual(graph_store.read(store,graph['id']),graph)
            work_outline.checked(graph_store.read(store,first['graph_id']))


if __name__=='__main__':unittest.main()
