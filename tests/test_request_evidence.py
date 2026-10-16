"""Projection invariants over authored controls, not semantic accuracy labels."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import json
from urllib.request import urlopen

from tracker import check_correspondence, graph_store, request_evidence
from tracker.schema import digest, InputError
from tests.test_check_correspondence import fixture


def graph(dispatch='attempts', response='sufficient', with_review=True):
    run, local, work, users, actions = fixture()
    work['run_id']=run['id'];previous=[]
    for step in work['steps']:
        step.update(status='selected_update', previous_state_hash=digest(previous),
                    changes=[c for c in work['changes'] if c['source_unit_id']==step['unit_id']])
        previous=step['state_after']
    def choose(req):
        choice = response if req['state']['stage']=='requested_check_response' else dispatch
        return {key:{'value':choice} for key in req['questions']}, digest(req)
    checks = check_correspondence.build(run, local, work, choose, version=check_correspondence.ISOLATED_VERSION)
    document = {**local, 'requested_work':work, 'relations':deepcopy(checks['relations'])}
    if with_review: document['check_correspondence'] = checks
    result = graph_store.build(run, {'document':document,'observer':{'id':'authored','label':'Control'}})
    return run, result, document, actions


def rehash(value):
    value.pop('id', None)
    return {'id':'graph-'+digest(value), **value}


class RequestEvidenceTests(unittest.TestCase):
    def test_versions_keep_old_answer_separate_from_current_request(self):
        run,g,_,_ = graph()
        output=request_evidence.project(g); rows=output['rows']
        checks=[r for r in rows if r['clause']['kind']=='requested_check']
        self.assertEqual(len(checks),2)
        self.assertEqual([r['state'] for r in checks],['superseded','requested'])
        self.assertIn('card A',checks[0]['clause']['text'])
        self.assertIn('CARD_A_RESPONSE',checks[0]['responses'][0]['response']['text'])
        self.assertIn('CARD_B_RESPONSE',checks[1]['responses'][0]['response']['text'])
        self.assertTrue(all(r['coverage']=='complete_saved_review' for r in checks))
        self.assertTrue(all(r['evidence']=='sufficient_recorded_response' for r in checks))
        self.assertNotIn('passed',output['counts'])
        self.assertTrue(all(r['coverage']=='outside_check_observer' for r in rows if r['clause']['kind']!='requested_check'))

    def test_response_evidence_is_independent_from_dispatch_role(self):
        _,g,_,_=graph('none','sufficient')
        rows=[r for r in request_evidence.project(g)['rows'] if r['clause']['kind']=='requested_check']
        self.assertEqual(rows[0]['counts']['dispatch_choices'],{'none':1})
        self.assertEqual(rows[0]['evidence'],'sufficient_recorded_response')

    def test_cutoff_excludes_response_and_future_request(self):
        _,g,_,actions=graph()
        output=request_evidence.project(g,actions[0]['source']['event_id'])
        checks=[r for r in output['rows'] if r['clause']['kind']=='requested_check']
        self.assertEqual(len(checks),1);self.assertEqual(checks[0]['state'],'requested')
        self.assertEqual(checks[0]['responses'],[])
        self.assertEqual(checks[0]['attempts_without_recorded_response'],1)
        self.assertNotIn('CARD_A_RESPONSE',str(output));self.assertNotIn('FUTURE_CHANGE',str(output))

    def test_legacy_positive_links_do_not_invent_negative_coverage(self):
        _,g,_,_=graph(with_review=False)
        checks=[r for r in request_evidence.project(g)['rows'] if r['clause']['kind']=='requested_check']
        self.assertTrue(all(r['coverage']=='positive_links_only' for r in checks))
        self.assertTrue(all(r['evidence']=='sufficient_recorded_response' for r in checks))
        self.assertIsNone(request_evidence.project(g)['observation_schema'])

    def test_no_answer_and_unresolved_remain_different_from_absence(self):
        for response in ('no_answer','unresolved','partial'):
            _,g,_,_=graph(response=response)
            rows=[r for r in request_evidence.project(g)['rows'] if r['clause']['kind']=='requested_check']
            self.assertEqual(rows[0]['counts']['response_choices'],{response:1})
            self.assertEqual(rows[0]['counts']['response_unreviewed'],0)
        _,g,_,_=graph('none','no_answer',with_review=False)
        rows=[r for r in request_evidence.project(g)['rows'] if r['clause']['kind']=='requested_check']
        self.assertEqual(rows[0]['coverage'],'unreviewed')
        self.assertEqual(rows[0]['counts']['response_unreviewed'],1)

    def test_source_dependency_and_invalid_cutoff_are_rejected(self):
        run,g,document,_=graph();bad=deepcopy(document)
        bad['check_correspondence']['source_hash']='wrong'
        with self.assertRaises(InputError):graph_store.build(run,{'document':bad,'observer':{'id':'bad','label':'Bad'}})
        with self.assertRaises(InputError):request_evidence.project(g,'missing')

    def test_cross_action_response_cannot_supply_evidence(self):
        _,g,_,_=graph();bad=deepcopy(g)
        observations=bad['semantic_context']['requested_check_observations']['actions']
        observations[0]['responses'][0]['event_id']=observations[1]['responses'][0]['event_id']
        output=request_evidence.project(rehash(bad))
        self.assertTrue(output['excluded'])
        self.assertEqual(output['rows'][0]['responses'],[])
        self.assertEqual(output['rows'][0]['counts']['response_unreviewed'],1)

    def test_projection_does_not_mutate_source_and_survives_storage(self):
        from tracker.store import Store
        run,g,_,_=graph();before=deepcopy(g)
        result=request_evidence.project(g);self.assertEqual(g,before)
        with TemporaryDirectory() as directory:
            store=Store(Path(directory)/'test.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,g)
            self.assertEqual(result,request_evidence.project(graph_store.read(store,g['id'])))

    def test_wrong_feedback_unit_uses_native_event_pointer(self):
        _,g,_,_=graph();bad=deepcopy(g)
        saved=bad['semantic_context']['requested_check_observations']['actions']
        saved[0]['responses'][0]['feedback_unit_id']=saved[1]['action_unit_id']
        output=request_evidence.project(rehash(bad))
        response=output['rows'][0]['responses'][0]['response']
        self.assertEqual(response['node_id'],'event:'+response['event_id'])

    def test_duplicate_conflicting_choices_are_unresolved_not_double_counted(self):
        _,g,_,_=graph();bad=deepcopy(g)
        saved=bad['semantic_context']['requested_check_observations']['actions']
        duplicate=deepcopy(saved[0]);duplicate['responses'][0]['choices']={k:'no_answer' for k in duplicate['responses'][0]['choices']}
        saved.append(duplicate)
        row=request_evidence.project(rehash(bad))['rows'][0]
        self.assertEqual(len(row['responses']),1)
        self.assertEqual(row['responses'][0]['choice'],'unresolved')
        self.assertTrue(row['responses'][0]['conflicting_saved_choices'])

    def test_source_only_keeps_semantic_coverage_unknown(self):
        run,_,_,_=graph();out=request_evidence.project(graph_store.build(run))
        self.assertEqual(out['rows'],[])
        self.assertEqual(out['counts']['unrepresented_actions'],out['counts']['native_actions'])

    def test_database_access_is_scoped(self):
        from tracker.store import Store
        from tracker.workspace_analysis import Workspace
        run,g,_,_=graph()
        with TemporaryDirectory() as directory:
            path=Path(directory)/'test.sqlite';store=Store(path);store.add([run])
            with store.connect() as c:graph_store.save(c,g)
            for _ in range(2):self.assertEqual(Workspace(path,observer=g['observer']).request_evidence(g['id']),request_evidence.project(g))
            with self.assertRaises(InputError):Workspace(path,observer='other').request_evidence(g['id'])
            with self.assertRaises(InputError):Workspace(path).request_evidence(g['id'],limit=1)


from tests import test_generation_cohort_transport as transport


class RequestEvidenceHTTPTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def test_exact_graph_prefix_and_download_contract(self):
        run,g,_,actions=graph();self.store.add([run])
        with self.store.connect() as c:graph_store.save(c,g)
        endpoint=self.start_server()
        for suffix,expected in [('',request_evidence.project(g)),('&through='+actions[0]['source']['event_id'],request_evidence.project(g,actions[0]['source']['event_id']))]:
            with urlopen(endpoint+'/api/request-evidence?graph='+g['id']+suffix,timeout=10) as response:
                self.assertEqual(json.load(response),expected)
        with urlopen(endpoint+'/api/request-evidence?graph='+g['id']+'&download=1',timeout=10) as response:
            self.assertIn('request-evidence.json',response.headers['Content-Disposition'])
            self.assertEqual(json.load(response),request_evidence.project(g))
        with urlopen(endpoint+'/request-evidence.js',timeout=10) as response:
            self.assertIn('javascript',response.headers['Content-Type'])
            self.assertIn('window.RequestEvidence',response.read().decode())
        with urlopen(endpoint+'/semantic-map',timeout=10) as response:
            self.assertIn('src="/request-evidence.js"',response.read().decode())


if __name__=='__main__':unittest.main()
