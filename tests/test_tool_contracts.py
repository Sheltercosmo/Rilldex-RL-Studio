from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tracker.adapters import normalize
from tracker import tool_contracts as tc


def document(schema=None, raw='{"query":["term"]}'):
    return {'trajectory_format': 'chat-messages/1',
            'messages': [{'role': 'user', 'content': 'Find evidence.'},
                         {'role': 'assistant', 'content': '', 'tool_calls': [
                             {'id': 'c1', 'type': 'function', 'function': {'name': 'search', 'arguments': raw}}]}],
            'tools': [{'type': 'function', 'function': {'name': 'search', 'parameters': schema if schema is not None else
                {'type': 'object', 'properties': {'query': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['query']}}}]}


def inspect(doc):
    return tc.inspect(normalize(doc)[0])


@unittest.skipUnless(importlib.util.find_spec('jsonschema'), 'Install .[contracts] for the schema observer tests')
class ToolContractsTests(unittest.TestCase):
    def test_wrong_envelope_is_localized_before_response_and_does_not_repair(self):
        doc = document(raw='["first", "second"]'); before = deepcopy(doc)
        result = inspect(doc); call = result['calls'][0]
        self.assertEqual(result['counts']['invalid'], 1)
        self.assertEqual(call['source_message_index'], 1)
        self.assertEqual(call['issues'][0]['keyword'], 'type')
        self.assertEqual(call['source_pointer'], '/messages/1/tool_calls/0')
        self.assertEqual(call['contract_pointer'], '/tools/0/function/parameters')
        self.assertEqual(doc, before)

    def test_json_types_required_additional_and_no_default_insertion(self):
        schema = {'type': 'object', 'properties': {'n': {'type': 'integer', 'default': 3}},
                  'required': ['n'], 'additionalProperties': False}
        for raw in ('{}', '{"n":true}', '{"n":3,"extra":1}', '{"n":"3"}'):
            with self.subTest(raw=raw): self.assertEqual(inspect(document(schema, raw))['counts']['invalid'], 1)
        self.assertEqual(inspect(document(schema, '{"n":3.0}'))['counts']['conformant'], 1)

    def test_bfcl_projection_is_explicit_and_does_not_rewrite_source(self):
        from test_chat_messages import source
        doc = source(); doc['data_source'] = 'bfcl_multi_turn_base'
        definition = doc['tools'][0]['function']
        definition['parameters'] = {'type': 'dict', 'properties': {'order': {'type': 'float'}}}
        doc['tools'] = [definition]; before = deepcopy(doc)
        row = inspect(doc)['calls'][0]
        self.assertEqual(row['status'], 'conformant')
        self.assertEqual(row['projection'], 'bfcl-json-parameters/1')
        self.assertEqual(doc, before)
        definition['parameters']['properties']['order']['type'] = 'integer'
        doc['messages'][3]['tool_calls'][0]['function']['arguments'] = '{"order":42.0}'
        self.assertEqual(inspect(doc)['counts']['invalid'], 1)

    def test_natural_language_precondition_is_not_a_machine_assertion(self):
        schema = {'type': 'object', 'properties': {'path': {'type': 'string', 'description': 'Cannot contain a path separator.'}}}
        self.assertEqual(inspect(document(schema, '{"path":"a/b"}'))['counts']['conformant'], 1)

    def test_local_references_nullable_and_escaped_property_names(self):
        schema = {'type': 'object', '$defs': {'value': {'anyOf': [{'type': 'integer'}, {'type': 'null'}]}},
                  'properties': {'a/b': {'$ref': '#/$defs/value'}}}
        self.assertEqual(inspect(document(schema, '{"a/b":null}'))['counts']['conformant'], 1)
        row = inspect(document(schema, '{"a/b":false}'))['calls'][0]
        self.assertEqual(row['issues'][0]['argument_pointer'], '/a~1b')

    def test_unsupported_or_invalid_declarations_are_unknown_without_network(self):
        schemas = [{'$ref': 'https://example.com/schema'}, {'$ref': '#'},
                   {'$ref': '#/$defs/missing'}, {'type': 'object', 'format': 'made-up'},
                   {'type': 'object', 'customConstraint': True}, {'type': 'string', 'pattern': '(a+)+$'},
                   {'type': 'object', 'required': 'bad'}, {'$schema': 'unknown'},
                   {'type': 'object', 'dependencies': {'x': {'$ref': 'https://example.com/'}}}]
        with patch('urllib.request.urlopen', side_effect=AssertionError('No network')):
            for schema in schemas:
                with self.subTest(schema=schema):
                    result = inspect(document(schema))
                    self.assertEqual(result['counts']['unavailable'], 1)
                    self.assertEqual(result['metrics']['tool_contract_violation_count']['value'], None)

    def test_explicit_draft7_tuple_items_and_bool_schema(self):
        schema = {'$schema': 'http://json-schema.org/draft-07/schema#', 'type': 'object',
                  'properties': {'x': {'type': 'array', 'items': [{'type': 'integer'}], 'additionalItems': False}}}
        self.assertEqual(inspect(document(schema, '{"x":[1,2]}'))['counts']['invalid'], 1)
        self.assertEqual(inspect(document(False))['counts']['invalid'], 1)

    def test_malformed_arguments_and_duplicates_are_distinct(self):
        for raw in ('{', '{"query":NaN}'):
            row = inspect(document(raw=raw))['calls'][0]
            self.assertEqual(row['status'], 'invalid')
            self.assertEqual(row['issues'][0]['keyword'], 'json')
        self.assertEqual(inspect(document(raw='{"query":[],"query":[]}'))['counts']['unavailable'], 1)

    def test_other_actors_copy_context_missing_schemas_and_plain_text(self):
        doc = document(); doc['messages'].append({'role': 'user', 'content': '', 'tool_calls': [
            {'id': 'external', 'type': 'function', 'function': {'name': 'search', 'arguments': '[]'}}]})
        run = normalize(doc)[0]
        result = tc.inspect(run)
        self.assertEqual(result['counts']['native_calls'], 1)
        call = next(e for e in run['events'] if e['kind'] == 'action')
        call.pop('tool_contract')
        self.assertEqual(tc.inspect(run)['counts']['unavailable'], 1)
        call['copied_context'] = True
        self.assertEqual(tc.inspect(run)['counts']['native_calls'], 0)
        prose = document(); prose['messages'][1] = {'role': 'assistant', 'content': 'search({"query":[]})'}
        self.assertEqual(inspect(prose)['counts']['native_calls'], 0)

    def test_source_size_and_depth_are_explicitly_unknown(self):
        with patch.object(tc, 'MAX_ARGUMENT_BYTES', 10):
            self.assertEqual(inspect(document())['counts']['unavailable'], 1)
        schema = {'type': 'object'}
        for _ in range(40): schema = {'properties': {'child': schema}}
        self.assertEqual(inspect(document(schema))['counts']['unavailable'], 1)

    def test_register_replay_metrics_old_rows_and_training_coordinates(self):
        from tracker.store import Store
        from tracker.rollout_metrics import report, training_series, metric_view
        run = normalize(document(raw='[]'), meta={'experiment': 'fixture', 'training_step': 7})[0]
        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db'); store.add([run])
            first = tc.register(store, run); second = tc.register(store, run)
            self.assertEqual(first['measurement_id'], second['measurement_id'])
            evidence = tc.read_saved(store, run['id'], first['observer'])
            self.assertEqual(evidence['calls'], first['inspection']['calls'])
            self.assertEqual(evidence['measurement_id'], first['measurement_id'])
            from tracker.schema import InputError
            with self.assertRaises(InputError): tc.read_saved(store, run['id'], 'other-observer')
            with self.assertRaises(InputError): tc.read_saved(store, run['id'], None)
            # A pre-extension stored source row still has explicit unavailable values in the read projection.
            with store.connect() as con:
                row = con.execute("SELECT id,document FROM rollout_measurements WHERE observer='source'").fetchone()
                doc = json.loads(row['document'])
                for key in tc.DEFINITIONS: doc['metrics'].pop(key, None)
                con.execute('UPDATE rollout_measurements SET document=? WHERE id=?', (json.dumps(doc), row['id']))
            rpt = report(store)
            projected = metric_view(rpt, 'tool_contract_violation_fraction')
            source = next(r for r in projected['rows'] if r['observer'] == 'source')
            self.assertIsNone(source['metrics']['tool_contract_violation_fraction']['value'])
            series = training_series(rpt, 'tool_contract_violation_fraction', observer=first['observer'])
            self.assertEqual(series['cohorts'][0]['points'][0]['value'], 1)
            self.assertEqual(series['cohorts'][0]['points'][0]['training_step'], 7)

    def test_no_training_clock_is_imputed(self):
        from tracker.store import Store
        from tracker.rollout_metrics import report, training_series
        run = normalize(document())[0]
        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db'); store.add([run]); result = tc.register(store, run)
            series = training_series(report(store), 'tool_contract_violation_fraction', observer=result['observer'])
            self.assertEqual(series['cohorts'], [])
            self.assertEqual(series['excluded']['missing_training_coordinates'], 1)

    def test_reward_and_process_labels_do_not_affect_checks(self):
        run=normalize(document(raw='[]'))[0];original=tc.inspect(run)
        run['outcome']={'recorded_reward':1,'verified_success':True,'source_process_annotation':{'labels':{'1':1}}}
        changed=tc.inspect(run)
        self.assertNotEqual(original['source_hash'],changed['source_hash'])
        self.assertEqual(original['calls'],changed['calls'])
        self.assertEqual(original['metrics'],changed['metrics'])
