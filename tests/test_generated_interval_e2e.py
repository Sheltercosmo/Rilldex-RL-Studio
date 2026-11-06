"""Current target identities reach maps, episodes and behavior without extra guesses."""
from tests import test_generated_focused_e2e as focused
from tracker import adaptation_patterns, execution_reports, graph_store, repeated_work, work_episodes
from tracker.semantic_extraction import read


class GeneratedIntervalE2ETests(focused.GeneratedFocusedE2ETests):
    fixture_name='generated-generalization-interval.json'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name,row in cls.cases.items():
            result=read(execution_reports.path_for(cls.root/name,row['source']))
            cls.maps[name]=execution_reports.project(row['source'],cls.maps[name],result)
            cls.graphs[name]=graph_store.build(row['source'],cls.maps[name])

    def test_route_change_reaches_episode_feedback_and_adaptation_without_rewriting_identity(self):
        for name,graph in self.graphs.items():
            methods=self.maps[name]['document']['method_comparison'];episodes=work_episodes.project(graph)
            repeated=repeated_work.project(graph);adaptation=adaptation_patterns.project(graph)
            self.assertEqual(episodes['disputed_identity_units'],[])
            if name=='simulation':
                units={u['source']['event_id']:u for u in self.maps[name]['document']['units'] if u['kind']=='action'}
                identity=[e for e in graph['edges'] if e['type']=='same_action_target']
                self.assertEqual([(e['source'],e['target']) for e in identity],[(units['e8']['id'],units['e4']['id'])])
                self.assertEqual(methods['counts']['same_work_pairs'],1)
                episode=episodes['episodes'][0]
                self.assertEqual(episode['group_id'],units['e4']['id'])
                self.assertEqual(episodes['counts']['independent_work_comparisons'],0)
                self.assertEqual(len(repeated['rows']),1)
                self.assertEqual(len(adaptation['records']),1)
                record=adaptation['records'][0]
                self.assertEqual(record['procedure'],'reconfigured_procedure')
                self.assertEqual(record['stated_reason']['event_id'],'e6')
                self.assertEqual(record['correction_location'],'not_established')
                self.assertEqual(record['response_context']['previous']['records'][0]['event_id'],'e5')
                self.assertEqual(record['response_context']['current']['records'][0]['event_id'],'e9')
                self.assertEqual(record['error_followup']['previous']['status'],'not_reported')
                self.assertIn('not successful execution',record['error_followup']['limit'])
            else:
                self.assertFalse(any(e['type']=='same_action_target' for e in graph['edges']))
                self.assertEqual(methods['counts']['same_work_pairs'],0)
                self.assertEqual(episodes['episodes'],[])
                self.assertEqual(adaptation['records'],[])

    def test_current_target_protocol_preserves_unknown_outcomes_contexts_and_partial_scope(self):
        for row in self.cases.values():self.assertEqual(row['config']['action_target_version'],'action-target-correspondence/7')
        software=self.maps['software']['document'];actions={u['source']['event_id']:u for u in software['units'] if u['kind']=='action'}
        partial=[r for r in software['relations'] if r['type']=='overlapping_work_scope']
        self.assertEqual([(r['from'],r['to']) for r in partial],[(actions['e12']['id'],actions['e4']['id'])])
        airline=self.graphs['public_airline'];source=self.cases['public_airline']['source']
        self.assertEqual(source['events'][-1]['kind'],'action')
        self.assertFalse(any(e['type']=='response_to' and e['target']=='event:e14' for e in airline['edges']))
        self.assertFalse(any(e['type'] in {'succeeded','completed','recovered'} for e in airline['edges']))
        telecom=self.maps['public_telecom']['document'];read_line=next(u for u in telecom['units'] if u['source']['event_id']=='e12')
        self.assertIn('L1001',read_line['content']['target']['text'])
        self.assertNotIn('L1002',read_line['content']['target']['text'])
        self.assertEqual(self.cases['multiagent']['action_targets']['coverage']['compared_pairs'],0)
