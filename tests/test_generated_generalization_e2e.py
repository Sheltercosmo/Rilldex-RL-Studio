"""Replay fresh model proposals and real Jev selections through the full graph path.

Exact replay and source checks are software evidence, not independent truth
labels. Semantic limitations found during review remain separately recorded.
"""
from collections import Counter
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import graph_store, semantic_workspace as workspace
from tracker.capabilities import recorded_scope
from tracker.schema import digest
from tracker.semantic_extraction import read, write, load_extraction


class GeneratedGeneralizationE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads((Path(__file__).parent/'fixtures/generated-generalization-e2e.json').read_text(encoding='utf8'))['cases']
        cls.temporary=TemporaryDirectory();cls.root=Path(cls.temporary.name)
        cls.replayed={};cls.bundles={};cls.graphs={};cls.calls={}
        for name,row in cls.cases.items():
            folder=cls.root/name;source=row['source'];config=row['config']
            write(folder/'workspace.json',config)
            write(folder/'runs'/f'{source["id"]}.json',source)
            for key,response in row['candidates'].items():write(folder/'candidates/responses'/f'{key}.json',response)
            seen=[]
            def transport(request):
                key=digest(request);seen.append(key)
                if key not in row['responses']:
                    raise AssertionError('Current request has no saved live response: '+name+' '+key)
                return deepcopy(row['responses'][key])
            workspace.execute(folder,transport)
            cls.calls[name]=seen
            cls.replayed[name]=read(folder/'results'/f'{source["id"]}.json')
            bundle=load_extraction(source,folder,action_target_version=config['action_target_version'],
                                   plan_relation_version=config['plan_relation_version'])
            bundle['observer']=dict(id='generated-e2e',label='Generated evaluation')
            cls.bundles[name]=bundle;cls.graphs[name]=graph_store.build(source,bundle)
        from scripts.evaluate_generated_generalization import downstream
        responses={key:value for row in cls.cases.values() for key,value in row['responses'].items()}
        with redirect_stdout(io.StringIO()):
            downstream(cls.root,lambda request:deepcopy(responses[digest(request)]))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_complete_pipeline_replays_actual_generated_contents_and_links(self):
        self.assertEqual(Counter(r['origin'] for r in self.cases.values()),
                         dict(authored_scenario=4,selected_public_trace=2))
        self.assertEqual(sum(len(r['units']) for r in self.replayed.values()),36)
        for name,row in self.cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.replayed[name],row['selected'])
                self.assertTrue(self.calls[name])
                self.assertEqual(read(self.root/name/'plan-relation-progress.json'),row['plan_relations'])
                self.assertEqual(read(self.root/name/'action-target-progress.json'),row['action_targets'])
                graph_store.validate(self.graphs[name])

    def test_observed_identity_and_missing_results_survive_the_graph(self):
        telecom=self.replayed['public_telecom']['units']
        read_line=next(u for u in telecom if u['source']['event_id']=='e12')
        self.assertIn('L1001',read_line['content']['target']['text'])
        self.assertNotIn('L1002',read_line['content']['target']['text'])
        airline=self.graphs['public_airline']
        source=self.cases['public_airline']['source']
        final_call=next(e for e in source['events'] if e['id']=='e14')
        self.assertEqual(final_call['kind'],'action')
        self.assertFalse(any(e['type']=='response_to' and e['target']=='event:e14' for e in airline['edges']))
        self.assertFalse(any(e['type'] in {'succeeded','completed','recovered'} for e in airline['edges']))

    def test_mixed_repair_outcome_and_declared_plan_stages_stay_distinct(self):
        result=self.replayed['software'];units={u['source']['event_id']:u for u in result['units']}
        reported=units['e14']['content']['result']['text']
        self.assertIn('pass',reported);self.assertIn('fail',reported);self.assertIn('incomplete',reported)
        self.assertEqual(units['e12']['activity'],'verify')
        links=self.cases['software']['plan_relations']['relations']
        self.assertTrue(any(r['from']==units['e12']['id'] and r['plan_step_id']=='p2' and
                            r['type']=='attempts_plan_step' for r in links))
        self.assertEqual(len(units['e2']['plan_structure']['steps']),3)
        self.assertFalse(any('completed' in r['type'] for r in links))

    def test_multiagent_and_reset_do_not_gain_invented_continuity(self):
        graph=self.graphs['multiagent'];nodes={n['id']:n for n in graph['nodes']}
        for edge in graph['edges']:
            if edge['type'] not in {'next_record','response_to'}:continue
            self.assertEqual(recorded_scope(nodes[edge['source']]['properties']),
                             recorded_scope(nodes[edge['target']]['properties']))
        self.assertEqual(self.cases['multiagent']['action_targets']['coverage']['candidate_pairs'],0)
        reset=next(u for u in self.replayed['multiagent']['units'] if u['source']['event_id']=='e13')
        self.assertEqual(reset['activity'],'coordinate')
        request=read(self.root/'multiagent/decisions'/f'{reset["activity_request"]}.json')['request']
        self.assertTrue(all(e.get('context_id')=='reset' for e in request['state']['prefix']))

    def test_reading_a_value_to_check_an_expectation_is_verify(self):
        for name in ('simulation','service'):
            action=next(u for u in self.replayed[name]['units'] if u['source']['event_id']=='e12')
            self.assertEqual(action['activity'],'verify')

    def test_downstream_replay_keeps_reports_separate_from_success_and_identity(self):
        from tracker import execution_reports
        for name,row in self.cases.items():
            result=read(self.root/name/'downstream.json')
            self.assertEqual(result,row['downstream'])
            projected=execution_reports.project(row['source'],self.bundles[name],result['execution_reports'])
            graph_store.validate(graph_store.build(row['source'],projected))
            self.assertEqual(projected['document']['execution_returns'],[])
        airline=self.cases['public_airline']['downstream']['execution_reports']
        self.assertFalse(any(r['action_event_id']=='e14' for r in airline['observations']))
        simulation=self.cases['simulation']['downstream']
        self.assertEqual(simulation['method_comparison']['counts']['eligible_pairs'],0)
        # Preserve the diagnosed upstream grouping gap. An explicit diagnostic
        # pair is not silently published as an already established graph link.
        probe=simulation['explicit_pair_probes'][0]
        self.assertEqual(probe['work_instance'],'same_work_instance')
        self.assertEqual(probe['comparison'],'reconfigured_procedure')
