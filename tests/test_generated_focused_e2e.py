"""Whole-pipeline replay after independently controlled purpose, Plan and recall fixes."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import adaptation_patterns, graph_store, method_comparison, repeated_work, semantic_workspace as workspace, work_episodes
from tracker.schema import digest
from tracker.semantic_extraction import load_extraction, read, write


class GeneratedFocusedE2ETests(unittest.TestCase):
    fixture_name='generated-generalization-focused.json'
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads((Path(__file__).parent/'fixtures'/cls.fixture_name).read_text(encoding='utf8'))['cases']
        cls.temporary=TemporaryDirectory();cls.root=Path(cls.temporary.name);cls.maps={};cls.graphs={}
        for name,row in cls.cases.items():
            folder=cls.root/name;source=row['source'];config=row['config']
            write(folder/'workspace.json',config);write(folder/'runs'/f'{source["id"]}.json',source)
            for key,response in row['candidates'].items():write(folder/'candidates/responses'/f'{key}.json',response)
            def transport(request):
                key=digest(request)
                if key not in row['responses']:raise AssertionError('Unrecorded current request: '+name+' '+key)
                return deepcopy(row['responses'][key])
            workspace.execute(folder,transport)
            bundle=load_extraction(source,folder,action_target_version=config['action_target_version'],plan_relation_version=config['plan_relation_version'])
            bundle['document']['method_comparison']=method_comparison.load(source,bundle['document'],folder)
            bundle['observer']=dict(id='generated-focused-e2e',label='Generated pipeline evidence')
            cls.maps[name]=bundle;cls.graphs[name]=graph_store.build(source,bundle)

    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def test_all_six_fresh_sources_complete_current_actual_pipeline(self):
        self.assertEqual(len(self.cases),6)
        for name,row in self.cases.items():
            self.assertEqual(row['config']['activity_routing'],'work-organization-activity/2')
            self.assertEqual(row['config']['plan_relation_version'],'plan-stage-correspondence/5')
            self.assertEqual(row['config']['method_comparison_version'],'work-method-comparison/5')
            self.assertEqual(read(self.root/name/'results'/f'{row["source"]["id"]}.json'),row['selected'])
            self.assertEqual(read(self.root/name/'plan-relation-progress.json'),row['plan_relations'])
            self.assertEqual(read(self.root/name/'action-target-progress.json'),row['action_targets'])
            graph_store.validate(self.graphs[name])
            status=workspace.status(self.root/name)
            for layer in ('action_targets','plan_relations','execution_reports','method_comparison'):
                self.assertEqual(status['layers'][layer]['status'],'complete')

    def test_retest_both_enacts_declared_test_stage_and_checks_saved_repair(self):
        doc=self.maps['software']['document'];units={u['source']['event_id']:u for u in doc['units']}
        links={(r['type'],r['plan_step_id']) for r in doc['relations'] if
               r['from']==units['e12']['id'] and r.get('plan_step_id') is not None}
        self.assertIn(('checks_plan_step','p1'),links)
        self.assertIn(('attempts_plan_step','p2'),links)
        self.assertNotIn(('attempts_plan_step','p0'),links)
        self.assertEqual(units['e12']['activity'],'verify')
        self.assertIn('incomplete',units['e14']['content']['result']['text'])
        self.assertFalse(any(e['type'] in {'succeeded','completed','recovered'} for e in self.graphs['software']['edges']))

    def test_route_change_reaches_episode_feedback_and_adaptation_without_rewriting_identity(self):
        for name,graph in self.graphs.items():
            methods=self.maps[name]['document']['method_comparison'];episodes=work_episodes.project(graph)
            repeated=repeated_work.project(graph);adaptation=adaptation_patterns.project(graph)
            self.assertEqual(episodes['disputed_identity_units'],[])
            self.assertFalse(any(e['type']=='same_action_target' for e in graph['edges']))
            if name=='simulation':
                self.assertEqual(methods['counts']['same_work_pairs'],1)
                episode=episodes['episodes'][0]
                self.assertEqual(episode['identity_basis'],'independent_work_instance')
                self.assertIsNone(episode['group_id'])
                self.assertEqual(len(repeated['rows']),1)
                record=adaptation['records'][0]
                self.assertEqual(record['procedure'],'reconfigured_procedure')
                self.assertEqual(record['stated_reason']['event_id'],'e6')
                self.assertEqual(record['correction_location'],'not_established')
                self.assertEqual(record['response_context']['previous']['records'][0]['event_id'],'e5')
                self.assertEqual(record['response_context']['current']['records'][0]['event_id'],'e9')
            else:
                self.assertEqual(methods['counts']['same_work_pairs'],0)
                self.assertEqual(episodes['episodes'],[])
                self.assertEqual(adaptation['records'],[])
