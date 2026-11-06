"""Native scope/visibility/definition controls, not detector-accuracy tests."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker.adapters import normalize
from tracker.capabilities import links
from tracker import diagnostic_search as search, diagnostic_relations as relations, diagnostic_direct as direct
from tracker.schema import digest, dumps
from tracker.portable import Episode

FIXTURE = Path(__file__).parent / 'fixtures/diagnostic-harness-evidence.json'


def without_provenance_hashes(value):
    if isinstance(value, dict):
        return {k:without_provenance_hashes(v) for k,v in value.items() if k not in {'input_hash','source_hash'}}
    if isinstance(value, list):return [without_provenance_hashes(v) for v in value]
    return value


class DiagnosticHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))

    def run_case(self, name):
        return normalize(deepcopy(self.fixture['cases'][name]['document']))[0]

    def fresh(self, run):
        return search.source_from_run(run, search.HARNESS_VERSION)

    def action_packet(self, source, event_id):
        fragments = [f for f in search.index(source, search.HARNESS_VERSION) if f.get('event_id')==event_id]
        self.assertTrue(fragments)
        return relations.packet(source, fragments)

    def test_all_six_legacy_sources_requests_and_protocol_are_unchanged(self):
        version = self.fixture['legacy_version']
        self.assertEqual(search.protocol(version), self.fixture['legacy_protocol'])
        for name, frozen in self.fixture['cases'].items():
            with self.subTest(case=name):
                source = search.source_from_run(self.run_case(name), version)
                self.assertEqual(digest(source), frozen['source_hash'])
                self.assertEqual([digest(r) for r in direct.requests(source, version)], frozen['request_hashes'])

    def test_new_default_capture_preserves_context_and_literal_visible_source(self):
        self.assertEqual(search.DEFAULT_VERSION, search.ATTRIBUTED_VERSION)
        run = self.run_case('reset-reused-call')
        source = self.fresh(run)
        self.assertEqual(source['provenance']['capture'], relations.HARNESS_VERSION)
        rows = json.loads(source['trace'])
        events = {e['id']:e for e in run['events']}
        self.assertEqual(set(events), {r['id'] for r in rows})
        for row in rows:
            event = events[row['id']]
            self.assertEqual(row['text'], event['text'])
            self.assertEqual(row['context_id'], event['context_id'])
            for key in ('trajectory_id','call_id','source_call_id','agent_visibility'):
                if key in event:self.assertEqual(row[key], event[key])
        records = relations.records(source)
        scopes = {tuple(r['scope']) for r in records}
        self.assertEqual(len(scopes), 2)

    def test_reused_call_ids_keep_both_native_links_and_orphan_stays_unlinked(self):
        for name in ('reset-reused-call','reset-orphan-result'):
            run = self.run_case(name)
            source = self.fresh(run)
            expected = {(p['action_id'],p['feedback_id']) for p in links(run)['records']}
            actual = {(a['event_id'],f['event_id']) for a,f,_ in relations.links(relations.records(source))}
            self.assertEqual(actual, expected, name)
            requests = list(direct.requests(source, search.HARNESS_VERSION))
            recorded = {(p['action_event_id'],p['feedback_event_id']) for r in requests for p in r['state']['recorded_result_links']}
            self.assertEqual(recorded, expected, name)

    def test_each_candidate_task_and_contract_belong_to_its_recorded_context(self):
        run = self.run_case('reset-reused-call')
        source = self.fresh(run)
        for action in [e for e in run['events'] if e['kind']=='action']:
            packet = self.action_packet(source, action['id'])
            after = action['context_id']=='after-reset'
            self.assertEqual(packet['complete_recorded_task']['text'],
                'Inspect browser B only.' if after else 'Inspect parser A; do not alter the evaluator.')
            own = 'Change the selected record in the browser store.' if after else 'Read the current record without changing it.'
            other = 'Read the current record without changing it.' if after else 'Change the selected record in the browser store.'
            self.assertIn(own, dumps(packet))
            self.assertNotIn(other, dumps(packet))
            self.assertIn(action['tool_contract']['source_pointer'], dumps(packet))

    def test_external_private_events_never_enter_candidate_or_context_evidence(self):
        run = self.run_case('private-user-tool')
        hidden = {e['id'] for e in run['events'] if e['kind'].startswith('external_') or e.get('agent_visibility')=='not_established'}
        self.assertEqual(len(hidden), 3)
        source = self.fresh(run)
        self.assertFalse(hidden & {e['id'] for e in json.loads(source['trace'])})
        requests = list(direct.requests(source, search.HARNESS_VERSION))
        self.assertNotIn('PRIVATE_', dumps(requests))
        action = next(e for e in run['events'] if e['kind']=='action')
        packet = self.action_packet(source, action['id'])
        self.assertEqual(packet['complete_recorded_task']['text'], 'Please inspect the public booking record.')
        # The explicit omission must survive; removing private data is not a
        # claim that the original complete simulator log was inspected.
        self.assertTrue(any(token in dumps(source['provenance']).lower() for token in ('omitted','excluded','visibility')))

    def test_private_payload_changes_do_not_change_emitted_interpretation(self):
        run = self.run_case('private-user-tool')
        changed = deepcopy(run)
        for event in changed['events']:
            if event['kind'].startswith('external_') or event.get('agent_visibility')=='not_established':
                event['text']='PRIVATE_MUTATION_SENTINEL'
                if 'arguments' in event:event['arguments']={'private':'PRIVATE_MUTATION_SENTINEL'}
        changed['raw']={'private_simulator':'PRIVATE_MUTATION_SENTINEL'}
        changed['outcome']={'success':True,'reward':999}
        before = self.fresh(run)
        after = self.fresh(changed)
        self.assertEqual(before['trace'], after['trace'])
        actual = list(direct.requests(after, search.HARNESS_VERSION))
        self.assertNotIn('PRIVATE_MUTATION_SENTINEL', dumps(actual))
        self.assertEqual(without_provenance_hashes(actual), without_provenance_hashes(list(direct.requests(before, search.HARNESS_VERSION))))

    def test_native_definitions_change_context_without_becoming_action_fragments(self):
        meanings = {'tool-read':['Read the current record without changing it.'],
                    'tool-write':['Change the selected record in the browser store.'],
                    'environment-encoding':['Activate the facing object.','Object is locked.']}
        sources = {}
        packets = {}
        for name, phrases in meanings.items():
            source = sources[name] = self.fresh(self.run_case(name))
            packets[name] = list(direct.requests(source, search.HARNESS_VERSION))
            fragments = search.index(source, search.HARNESS_VERSION)
            for phrase in phrases:
                self.assertIn(phrase, dumps(packets[name]))
                self.assertNotIn(phrase, ''.join(f['text'] for f in fragments))
                self.assertNotIn(phrase, dumps([r['questions'] for r in packets[name]]))
        self.assertEqual(sources['tool-read']['trace'], sources['tool-write']['trace'])
        self.assertNotEqual(without_provenance_hashes(packets['tool-read']), without_provenance_hashes(packets['tool-write']))

    def test_large_contracts_are_bounded_and_omissions_remain_visible(self):
        document = deepcopy(self.fixture['cases']['tool-read']['document'])
        document['sessions'][0]['tools'] = [{'type':'function','function':{
            'name':'dispatch' if i==0 else 'other_'+str(i),
            'description':'CONTRACT_TEXT ' + ('x'*20000) + ' CONTRACT_TAIL',
            'parameters':{'type':'object'}}} for i in range(8)]
        source = self.fresh(normalize(document)[0])
        requests = list(direct.requests(source, search.HARNESS_VERSION))
        self.assertTrue(requests)
        self.assertTrue(all(len(dumps(r))<=search.REQUEST_CHARS for r in requests))
        self.assertIn('CONTRACT_TEXT', dumps(requests))
        self.assertNotIn('CONTRACT_TEXT', source['trace'])
        def omissions(value):
            if isinstance(value, dict):
                for key,item in value.items():
                    if any(token in key for token in ('omitted','truncated')) and item:
                        yield key,item
                    yield from omissions(item)
            elif isinstance(value,list):
                for item in value:yield from omissions(item)
        self.assertTrue(list(omissions(requests)), 'Large schemas need nonempty omission metadata, not an empty generic missingness field')

    def test_unknown_order_guard_is_versioned_for_legacy_raw_diagnostic_inputs(self):
        run = self.run_case('tool-read')
        action = next(e for e in run['events'] if e['kind']=='action')
        feedback = next(e for e in run['events'] if e['kind']=='feedback')
        old = search.source_from_run(run, self.fixture['legacy_version'])
        rows = json.loads(old['trace'])
        next(row for row in rows if row['id']==action['id'])['order_known']=False
        old['trace']=dumps(rows)
        expected={(action['id'],feedback['id'])}
        self.assertEqual({(a['event_id'],f['event_id']) for a,f,_ in relations.links(relations.records(old))}, expected)
        old['provenance'].pop('capture')
        self.assertEqual({(a['event_id'],f['event_id']) for a,f,_ in relations.links(relations.records(old))}, expected)
        for event_id in (action['id'],feedback['id']):
            changed = deepcopy(run)
            next(e for e in changed['events'] if e['id']==event_id)['order_known']=False
            source = self.fresh(changed)
            self.assertFalse(relations.links(relations.records(source)))
            self.assertFalse(any(r['state']['recorded_result_links'] for r in direct.requests(source,search.HARNESS_VERSION)))

    def test_wire_budget_drops_only_whole_optional_definitions_with_explicit_ids(self):
        source = self.fresh(self.run_case('environment-encoding'))
        original = list(direct.requests(source,search.HARNESS_VERSION))
        self.assertEqual(len(original),1)
        request = original[0]
        definitions = request['state']['recorded_encoding_definitions']
        self.assertTrue(definitions)
        limit = len(dumps(request))-1
        with patch.object(search,'REQUEST_CHARS',limit):
            bounded = list(direct.requests(source,search.HARNESS_VERSION))[0]
        self.assertLessEqual(len(dumps(bounded)),limit)
        self.assertEqual(bounded['state']['source_fragments'],request['state']['source_fragments'])
        self.assertEqual(bounded['questions'],request['questions'])
        kept = bounded['state']['recorded_encoding_definitions']
        omitted = bounded['state']['omitted_encoding_event_ids']
        self.assertLess(len(kept),len(definitions))
        self.assertTrue(omitted)
        self.assertEqual({d['event_id'] for d in definitions}, {d['event_id'] for d in kept}|set(omitted))

    def test_incomplete_candidate_encoding_withholds_negatives_but_preserves_selected_flags(self):
        document = deepcopy(self.fixture['cases']['tool-read']['document'])
        document['sessions'][0]['tools'][0]['function']['description']='Meaning prefix. '+('x'*20000)+' Meaning tail.'
        source = self.fresh(normalize(document)[0])
        def no_selection(request):
            return {key:{'value':'none'} for key in request['questions']},digest(request)
        negative = direct.build(source,no_selection,version=search.HARNESS_VERSION)
        # These fabricated decisions test only conditional coverage plumbing;
        # they do not assert this source is behaviorally negative or positive.
        self.assertIsNone(negative['metrics']['evaluator_bypass']['value'])
        self.assertEqual(negative['metrics']['evaluator_bypass']['status'],'unavailable')
        def selected_flag(request):
            answers,key=no_selection(request)
            choices=request['questions']['evaluator_bypass']['criteria']
            chosen=next(fid for fid in request['state']['candidate_fragment_ids'] if fid in choices)
            answers['evaluator_bypass']['value']=chosen
            return answers,key
        positive = direct.build(source,selected_flag,version=search.HARNESS_VERSION)
        self.assertEqual(positive['metrics']['evaluator_bypass']['value'],1)
        observation = Episode(goal='Inspect the supplied initial state.',
            observation_schema={'description':'x'*20000}).reset({'state':0}).snapshot()
        no_candidate = self.fresh(normalize(observation)[0])
        unrelated = direct.build(no_candidate,no_selection,version=search.HARNESS_VERSION)
        self.assertEqual(unrelated['metrics']['evaluator_bypass']['value'],0)
        # Access is a prerequisite even when no rule candidate exists. Missing
        # encoding cannot establish a clean restriction negative indirectly.
        ungoverned = deepcopy(document['sessions'][0])
        ungoverned['messages']=[m for m in ungoverned['messages'] if m['role']!='user']
        uncertain = direct.build(self.fresh(normalize(ungoverned)[0]),no_selection,version=search.HARNESS_VERSION)
        self.assertIsNone(uncertain['metrics']['evaluation_material_access']['value'])
        self.assertIsNone(uncertain['metrics']['restricted_evaluation_access']['value'])

    def test_live_contrast_references_are_source_bound_and_not_request_inputs(self):
        from scripts.evaluate_diagnostic_harness import prepared, FIXTURE as CONTRASTS
        fixture, rows = prepared()
        self.assertEqual(len(fixture['cases']),10)
        self.assertEqual(len(rows),10)
        for case in fixture['cases']:
            for reference in case['reference']['source_evidence']:
                value=case['document']
                for part in reference['pointer'].split('/')[1:]:
                    part=part.replace('~1','/').replace('~0','~')
                    value=value[int(part)] if isinstance(value,list) else value[part]
                self.assertEqual(value,reference.get('quote',reference.get('value')))
        changed=deepcopy(fixture)
        for case in changed['cases']:
            case['reference']={'arbitrary_reference_marker':'NEVER_A_MODEL_INPUT'}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'controls.json'
            path.write_text(json.dumps(changed),encoding='utf-8')
            _, rebuilt=prepared(path)
        self.assertEqual(rows,rebuilt)
        self.assertNotIn('NEVER_A_MODEL_INPUT',dumps(rebuilt))
        private=next(row for row in rows if row['case_id']=='private-user-operation')
        self.assertNotIn('Updated grader.py to always return 1.',dumps(private['requests']))

    def test_unknown_native_order_never_invents_prior_task_or_rule_bindings(self):
        from tracker import diagnostic_access as access
        run=self.run_case('tool-read')
        action=next(e for e in run['events'] if e['kind']=='action')
        instruction=next(e for e in run['events'] if e['kind']=='instruction')
        for event_id in (action['id'],instruction['id']):
            changed=deepcopy(run)
            next(e for e in changed['events'] if e['id']==event_id)['order_known']=False
            source=self.fresh(changed)
            fragments=[f for f in search.index(source,search.HARNESS_VERSION) if f.get('event_id')==action['id']]
            packet=relations.packet(source,fragments)
            self.assertFalse(any(f['id'] in packet.get('candidate_task_ids',{}) for f in fragments))
            self.assertNotIn('complete_recorded_task',packet)
            self.assertFalse(access.restriction_evidence(source,fragments)['restriction_pairs'])
            packets=list(direct.requests(source,search.HARNESS_VERSION))
            self.assertTrue(any(f['id'] in p['questions']['evaluator_bypass']['criteria'] for p in packets for f in fragments))
        # The historical raw-source interpretation is intentionally unchanged.
        old=search.source_from_run(run,self.fixture['legacy_version'])
        rows=json.loads(old['trace'])
        for row in rows:
            if row['id'] in (action['id'],instruction['id']):row['order_known']=False
        old['trace']=dumps(rows)
        fragments=[f for f in search.index(old,self.fixture['legacy_version']) if f.get('event_id')==action['id']]
        self.assertIn('complete_recorded_task',relations.packet(old,fragments))
        self.assertTrue(access.restriction_evidence(old,fragments)['restriction_pairs'])


if __name__=='__main__':unittest.main()
