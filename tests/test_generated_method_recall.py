"""Replay real method/5 decisions and validate their downstream meaning."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import adaptation_patterns, graph_store, method_comparison, work_episodes, work_patterns
from tracker.schema import InputError, digest
from tracker.semantic_extraction import FileCandidates, Pipeline, write


class GeneratedMethodRecallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads((Path(__file__).parent/'fixtures/generated-generalization-method-recall.json').read_text(encoding='utf8'))['cases']
        cls.temporary=TemporaryDirectory();cls.root=Path(cls.temporary.name)
        cls.loaded={};cls.graphs={}
        for name,row in cls.cases.items():
            folder=cls.root/name
            for key,receipt in row['receipts'].items():write(folder/'decisions'/f'{key}.json',receipt)
            def unavailable(request):
                raise AssertionError('No live receipt matches current request '+digest(request))
            engine=Pipeline(folder,FileCandidates(folder),unavailable)
            before=deepcopy((row['source'],row['document']))
            result,audit=method_comparison.execute(row['source'],row['document'],engine,method_comparison.RELATED_VERSION)
            if result!=row['report']['result']:raise AssertionError('Method replay changed: '+name)
            if before!=(row['source'],row['document']):raise AssertionError('Changed upstream map: '+name)
            loaded=method_comparison.load(row['source'],row['document'],folder)
            cls.loaded[name]=loaded
            document={**deepcopy(row['document']),'method_comparison':loaded}
            cls.graphs[name]=graph_store.build(row['source'],dict(document=document,observer=dict(id='generated-method-recall',label='Generated method evidence')))

    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def test_real_gate_keeps_relatedness_separate_from_same_work(self):
        totals={key:sum(row['counts'][key] for row in self.loaded.values()) for key in
                ('candidate_pairs','same_work_pairs','different_work_pairs','unresolved_work_pairs')}
        self.assertEqual(totals,dict(candidate_pairs=9,same_work_pairs=1,different_work_pairs=8,unresolved_work_pairs=0))
        for name,row in self.cases.items():
            self.assertEqual(row['report']['missing_pairs'],[])
            self.assertEqual(row['report']['unexpected_pairs'],[])
            self.assertTrue(all(s['correct'] for s in row['report']['scores']))
            for observation in self.loaded[name]['observations']:
                self.assertIsNone(observation['group_id'])
                self.assertTrue(observation['candidate_relations'])
                if observation['work_instance']=='different_work':
                    self.assertEqual(observation['request'],observation['work_request'])
                    self.assertEqual(observation['stated_basis'],'not_inspected')
                    self.assertNotIn('procedure_input_characters',observation)

    def test_route_change_preserves_stated_reason_and_prior_feedback_without_future_result(self):
        case=self.cases['simulation'];units={u['id']:u for u in case['document']['units']}
        changed=next(r for r in self.loaded['simulation']['observations'] if r['work_instance']=='same_work_instance')
        self.assertEqual(changed['comparison'],'reconfigured_procedure')
        self.assertEqual(units[changed['stated_basis']]['source']['event_id'],'e6')
        self.assertIn('N2 is flooded',units[changed['stated_basis']]['source']['text'])
        source=case['source'];events={e['id']:e for e in source['events']}
        for receipt in case['receipts'].values():
            request=receipt['request'];cut=request['state']['cutoff']
            for ref in request['state']['source_ranges']:
                self.assertEqual(ref['text'],events[ref['event_id']]['text'][ref['start']:ref['end']])
                self.assertLessEqual((events[ref['event_id']]['index'],ref['end']),
                                     (events[cut['event_id']]['index'],cut['end']))
        request=case['receipts'][changed['request']]['request']
        supplied='\n'.join(r['text'] for r in request['state']['source_ranges'])
        self.assertIn('Stopped at N1',supplied)
        self.assertNotIn('Motion completed',supplied)
        self.assertNotIn('The sensor reports G',supplied)

    def test_new_pairs_do_not_rewrite_target_groups_or_invent_repeat_patterns(self):
        for name,row in self.cases.items():
            graph=self.graphs[name];graph_store.validate(graph)
            stored=graph['semantic_context']['work_observations']['method_observations']
            self.assertEqual(stored,self.loaded[name]['observations'])
            self.assertFalse(any(e['type']=='same_action_target' for e in graph['edges']))
            document={**deepcopy(row['document']),'method_comparison':self.loaded[name]}
            patterns=work_patterns.build(row['source'],document,include_returns=True)
            self.assertEqual(patterns['counts']['periodic_regions'],0)
            self.assertEqual(patterns['counts']['separated_returns'],0)
            episodes=work_episodes.project(graph)
            self.assertEqual(episodes['disputed_identity_units'],[])
            original_graph=graph_store.build(row['source'],dict(document=row['document'],observer=dict(id='original',label='Original groups')))
            self.assertEqual(episodes['paths'],work_episodes.project(original_graph)['paths'])
            if name=='simulation':
                self.assertEqual(len(episodes['episodes']),1)
                self.assertEqual(episodes['episodes'][0]['identity_basis'],'independent_work_instance')
                self.assertIsNone(episodes['episodes'][0]['group_id'])
            else:self.assertEqual(episodes['episodes'],[])

    def test_adaptation_exposes_route_change_without_promoting_other_related_pairs(self):
        for name,graph in self.graphs.items():
            view=adaptation_patterns.project(graph)
            if name=='simulation':
                self.assertEqual(len(view['records']),1)
                record=view['records'][0]
                self.assertEqual(record['procedure'],'reconfigured_procedure')
                self.assertEqual(record['stated_reason']['event_id'],'e6')
                self.assertEqual(record['stated_reason']['attribution'],'agent_expression')
                self.assertEqual(record['correction_location'],'not_established')
                self.assertEqual(view['procedure_change']['denominator'],1)
                self.assertEqual(view['procedure_change']['numerator'],1)
            else:self.assertEqual(view['records'],[])

    def test_related_negative_does_not_dispute_a_different_positive_pair(self):
        # Authored graph contract control, separate from live semantic evidence.
        from test_work_episodes import example, edge, method
        _,graph,actions=example(('A','B','A'))
        edge(graph,actions[2],actions[0],'same_action_target')
        baseline=work_episodes.project(graph)
        method(graph,actions[2],actions[1],comparison='different_work',
               status='selected',work_instance='different_work',group_id=None,
               candidate_basis=['different_work_same_subject'])
        graph['semantic_context']['work_observations']['method_schema']=method_comparison.RELATED_VERSION
        actual=work_episodes.project(graph)
        self.assertEqual(actual['paths'],baseline['paths'])
        self.assertEqual(actual['episodes'],baseline['episodes'])
        self.assertEqual(actual['disputed_identity_units'],[])

    def test_supplemental_episode_requires_its_recorded_pair_evidence(self):
        graph=deepcopy(self.graphs['simulation'])
        changed=next(r for r in self.loaded['simulation']['observations'] if r['work_instance']=='same_work_instance')
        graph['edges']=[e for e in graph['edges'] if not
            (e['source']==changed['current_unit_id'] and e['target']==changed['previous_unit_id'] and
             e['type']=='different_work_same_subject')]
        self.assertEqual(work_episodes.project(graph)['episodes'],[])
        self.assertEqual(adaptation_patterns.project(graph)['records'],[])

    def test_candidate_recall_deduplicates_and_rejects_wrong_scope_order_or_missing_evidence(self):
        original=self.cases['simulation'];source=original['source'];document=original['document']
        copied=deepcopy(document);copied['relations']+=deepcopy([r for r in copied['relations'] if r['type']=='different_work_same_subject'])
        self.assertEqual(len(method_comparison.candidate_pairs(source,copied,method_comparison.RELATED_VERSION)),3)
        for corrupt in ('actor','context','order','unordered','batch','evidence'):
            run,doc=deepcopy((source,document))
            edge=next(r for r in doc['relations'] if r['type']=='different_work_same_subject')
            old=next(u for u in doc['units'] if u['id']==edge['to'])
            if corrupt=='actor':old['actor']='another'
            elif corrupt=='context':next(e for e in run['events'] if e['id']==old['source']['event_id'])['context_id']='other'
            elif corrupt=='order':edge['from'],edge['to']=edge['to'],edge['from']
            elif corrupt=='unordered':next(e for e in run['events'] if e['id']==old['source']['event_id'])['order_known']=False
            elif corrupt=='batch':
                current=next(u for u in doc['units'] if u['id']==edge['from'])
                for event in run['events']:
                    if event['id'] in {old['source']['event_id'],current['source']['event_id']}:
                        event['source_message_index']=12345
            else:edge['evidence']=[]
            with self.subTest(corrupt=corrupt),self.assertRaises(InputError):
                method_comparison.candidate_pairs(run,doc,method_comparison.RELATED_VERSION)
