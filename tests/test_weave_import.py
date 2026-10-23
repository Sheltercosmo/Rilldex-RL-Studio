import base64
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tracker.adapters import normalize
from tracker.capabilities import links
from tracker.graph_store import build
from tracker.import_batch import preflight, read_bytes
from tracker.rollout_metrics import source_record
from tracker.schema import InputError
from tracker.store import Store


FIXTURE = Path(__file__).parent / 'fixtures/weave/public_openai_tool_call.json'


def call(identifier='root', parent=None, trace='trace', **values):
    return dict(id=identifier, project_id='team/project', trace_id=trace, parent_id=parent,
                op_name='weave:///team/project/op/workflow:v1',
                started_at='2026-10-21T00:00:00Z', ended_at='2026-10-21T00:00:10Z',
                inputs={'task':'Inspect the record'}, attributes={}) | values


def model(identifier='model', parent='root', trace='trace'):
    result = call(identifier, parent, trace)
    result.update(op_name='weave:///team/project/op/openai.chat.completions.create:v1',
                  inputs={'messages':[{'role':'user','content':'Inspect the record'}]},
                  output={'choices':[{'message':{'role':'assistant','content':'Inspecting it.'}}]})
    return result


def resolve(document, pointer):
    for part in pointer.split('/')[1:]:
        key = part.replace('~1','/').replace('~0','~')
        document = document[int(key)] if isinstance(document,list) else document[key]
    return document


class WeaveImportTests(unittest.TestCase):
    def test_json_jsonl_array_and_reordered_duplicate_exports_share_identity(self):
        calls = [call(), model(), call('other',trace='another')]
        runs = normalize({'calls':calls})
        self.assertEqual(runs, normalize(calls))
        raw = '\n'.join(json.dumps(x) for x in reversed(calls+[calls[0]])).encode()
        self.assertEqual(runs, read_bytes(raw,name='export.jsonl'))
        self.assertEqual(len(runs), 2)
        self.assertEqual(sum(r['metadata']['weave_capture']['calls'] for r in runs), 3)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'db.sqlite')
            store.add(runs); store.add(read_bytes(raw,name='again.jsonl'))
            self.assertEqual(len(store.list()), 2)

    def test_public_recorded_tool_request_retains_arguments_and_exact_pointers(self):
        original = json.loads(FIXTURE.read_text())
        run = normalize(original)[0]
        self.assertEqual(run['raw']['calls'][0], original)
        actions = [e for e in run['events'] if e['kind']=='action' and not e['copied_context']]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['tool'], 'cricket_player_names')
        self.assertEqual(actions[0]['arguments']['name'], 'Sachin Tendulkar')
        for event in run['events']:
            value = resolve(run['raw'], event['source_pointer'])
            if isinstance(value,str): self.assertEqual(value,event['text'])
            if event.get('tool_contract'):
                self.assertEqual(resolve(run['raw'],event['tool_contract']['source_pointer']),event['tool_contract']['definition'])
        self.assertEqual(links(run)['records'], [])
        self.assertEqual(source_record(run)['metrics']['actions']['value'], 1)

    def test_nested_wrappers_and_scorers_do_not_duplicate_agent_outputs(self):
        child=model(); root=call(output=child['output'])
        scorer=call('grader','root',attributes={'weave':{'kind':'scorer'}})
        nested=model('grader-llm','grader')
        run=normalize({'calls':[root,child,scorer,nested]})[0]
        self.assertEqual(run['metadata']['weave_capture']['model_output_calls'],1)
        self.assertEqual(sum(e['kind']=='message' and not e['copied_context'] for e in run['events']),1)
        edges=build(run)['edges']
        self.assertEqual(sum(e['type']=='contains_call' for e in edges),3)
        self.assertTrue(all(e['type'] not in {'assesses','revises','response_to'} for e in edges))
        self.assertEqual(run['outcome'],{})

    def test_repeated_input_history_stays_context(self):
        first=model(); first['output']['choices'][0]['message']['tool_calls']=[{
            'id':'tool-1','type':'function','function':{'name':'read','arguments':'{}'}}]
        second=model('second')
        second['inputs']['messages'] += [first['output']['choices'][0]['message'],
                                       {'role':'tool','tool_call_id':'tool-1','content':'A record'}]
        run=normalize({'calls':[call(),first,second]})[0]
        self.assertEqual(source_record(run)['metrics']['actions']['value'],1)
        self.assertEqual(links(run)['records'],[])
        self.assertEqual(len({e['trajectory_id'] for e in run['events'] if e['kind']=='message' and not e['copied_context']}),2)

    def test_multiple_choices_are_independent_and_unsupported_choice_remains_visible(self):
        item=model()
        item['output']['choices'] += [{'message':{'role':'assistant','content':'Another answer'}}, {'text':'Legacy output'}]
        run=normalize(item)[0]
        outputs=[e for e in run['events'] if e['kind']=='message' and not e['copied_context']]
        self.assertEqual(len({e['trajectory_id'] for e in outputs}),2)
        for output in outputs:
            self.assertTrue(any(e['copied_context'] and e['trajectory_id']==output['trajectory_id'] for e in run['events']))
        self.assertTrue(any(e['source_pointer'].endswith('/choices/2') for e in run['events']))

    def test_anthropic_native_blocks_and_unknown_outputs(self):
        item=model();item['op_name']='anthropic.Messages.create'
        item['output']={'role':'assistant','content':[{'type':'text','text':'Read it'},
            {'type':'tool_use','id':'t','name':'read','input':{'path':'x'}}]}
        item['inputs']['tools']=[{'name':'read','description':'Read a path','input_schema':{'type':'object'}}]
        run=normalize(item)[0]
        self.assertEqual(source_record(run)['metrics']['actions']['value'],1)
        for event in run['events']: resolve(run['raw'],event['source_pointer'])
        item['output']='weave:///team/project/object/reply:version'
        run=normalize(item)[0]
        self.assertEqual(run['metadata']['weave_capture']['model_output_calls'],0)
        self.assertTrue(any(e['kind']=='source_output' and e['text']==item['output'] for e in run['events']))

    def test_wandb_context_is_correlation_not_policy_or_consumption(self):
        run=normalize({'calls':[call(wb_run_id='team/project/train',wb_run_step=27),
                                       model()]})[0]
        m=run['metadata']
        self.assertEqual((m['experiment'],m['training_step'],m['training_step_basis']),
                         ('team/project/train',27,'weave_wb_run_step'))
        self.assertNotIn('checkpoint',m);self.assertNotIn('training_inclusion',m)
        self.assertEqual(preflight([run])['declared_training_coordinates'],1)
        run=normalize({'calls':[call(wb_run_id='a',wb_run_step=1),
                                call('child','root',wb_run_id='a',wb_run_step=2)]})[0]
        self.assertNotIn('training_step',run['metadata'])
        self.assertEqual(run['metadata']['weave_wb_run_steps'],[1,2])

    def test_missing_parent_unfinished_exception_and_deleted_are_retained(self):
        item=model(parent='absent');item['ended_at']=None;item['exception']='Timeout'
        run=normalize(item)[0];capture=run['metadata']['weave_capture']
        self.assertEqual(capture['missing_parent_ids'],['absent'])
        self.assertEqual(capture['unfinished_calls'],1)
        self.assertTrue(any(e['kind']=='source_exception' for e in run['events']))
        self.assertEqual(run['outcome'],{})
        item['deleted_at']='2026-10-21T00:00:20Z'
        self.assertEqual(normalize(item)[0]['metadata']['weave_capture']['model_output_calls'],0)

    def test_malformed_or_ambiguous_graphs_reject_atomically(self):
        conflicting=call();conflicting['output']='Changed'
        cases=[([call(),conflicting],'Conflicting'),
               ([call('a','b'),call('b','a')],'cycle'),
               ([call(),call('other','root','another')],'another trace'),
               ([dict(call(),wb_run_step=True)],'nonnegative'),
               ([dict(call(),started_at='2026-10-21')],'timezone'),
               ([dict(call(),ended_at='2026-10-20T00:00:00Z')],'precedes'),
               ([dict(call(),inputs=None)],'inputs')]
        for calls,pattern in cases:
            with self.subTest(pattern=pattern), self.assertRaisesRegex(InputError,pattern):normalize({'calls':calls})
        raw=(json.dumps(call())+'\n'+json.dumps({'messages':[]})).encode()
        with self.assertRaisesRegex(InputError,'line 2'):read_bytes(raw,name='calls.jsonl')

    def test_native_ids_escape_in_external_links(self):
        item=call('call?x#y');item['project_id']='team space/project#name'
        run=normalize(item)[0]
        self.assertEqual(run['metadata']['source_uri'],'https://wandb.ai/team%20space/project%23name/weave/calls/call%3Fx%23y')

    def test_deep_instrumentation_tree_does_not_require_python_recursion(self):
        calls=[call(str(i),str(i-1) if i else None) for i in range(1500)]
        run=normalize({'calls':calls})[0]
        graph=build(run)
        self.assertEqual(sum(e['type']=='contains_call' for e in graph['edges']),1499)
        self.assertEqual(run['metadata']['weave_capture']['calls'],1500)

    def test_later_export_updates_one_rollout_and_old_export_cannot_move_it_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            start=call();start['ended_at']=None
            first=normalize(start)[0];store.add([first])
            self.assertEqual(store.list()[0]['ingestion']['state'],'in_progress')
            final=normalize({'calls':[call(),model()]})[0];store.add([final])
            self.assertEqual(len(store.list()),1)
            self.assertEqual(store.list()[0]['id'],final['id'])
            self.assertEqual(store.list()[0]['ingestion']['state'],'complete')
            store.add([first])
            self.assertEqual(store.list()[0]['id'],final['id'])
            subset=normalize(call())[0]
            self.assertEqual(store.add([subset])[0]['id'],final['id'])
            self.assertEqual(len(store.list()),1)
            with store.connect() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM runs').fetchone()[0],2)
                self.assertEqual(c.execute('SELECT count(*) FROM rollout_revisions').fetchone()[0],2)
            modified=model();modified['output']='A changed completed result'
            with self.assertRaisesRegex(InputError,'finished result'):
                store.add(normalize({'calls':[call(),modified]}))
            self.assertEqual(store.list()[0]['id'],final['id'])

    def test_rejected_revision_rolls_back_the_whole_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');store.add(normalize({'calls':[call(),model()]}))
            changed=model();changed['inputs']={'task':'different'}
            records=normalize({'calls':[call('new',trace='a-new-trace'),call(),changed]})
            with self.assertRaises(InputError):store.add(records)
            self.assertEqual(len(store.list()),1)

    def test_cli_import_and_check_share_grouping(self):
        from tracker.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'calls.jsonl';db=Path(tmp)/'db.sqlite'
            path.write_text('\n'.join(json.dumps(c) for c in [call(),model()]))
            with patch('sys.argv',['rilldex','check',str(path)]),redirect_stdout(io.StringIO()) as output: main()
            self.assertEqual(json.loads(output.getvalue())['total_records'],1)
            with patch('sys.argv',['rilldex','--db',str(db),'import',str(path)]),redirect_stdout(io.StringIO()): main()
            self.assertEqual(len(Store(db).list()),1)

    def test_line_collector_cannot_publish_calls_as_complete_rollouts(self):
        from tracker.export_watch import ExportWatcher
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite')
            watcher=ExportWatcher(store,tmp,producer='test',metadata={'experiment':'test'})
            with self.assertRaisesRegex(InputError,'group the full export'):
                watcher._envelope(call(),'calls.jsonl',1)


import test_generation_cohort_transport as transport


class WeaveHTTPTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def test_import_preflight_readiness_graph_and_repeat_import(self):
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        endpoint=self.start_server()
        def request(path,body=None):
            req=Request(endpoint+path,data=json.dumps(body).encode() if body is not None else None,
                        headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=20) as response:return json.load(response)
        raw='\n'.join(json.dumps(c) for c in [call(wb_run_id='team/project/train',wb_run_step=8), model()]).encode()
        body={'file':{'name':'weave.jsonl','base64':base64.b64encode(raw).decode()}}
        checked=request('/api/import-file/check',body)
        self.assertEqual(checked['total_rollouts'],1)
        self.assertEqual(checked['declared_training_coordinates'],1)
        self.assertEqual(checked['runs'][0]['functions'][0]['name'],'Weave call export')
        self.assertEqual(self.store.list(),[])
        receipt=request('/api/import-file',body)
        self.assertTrue(receipt['runs'][0]['imported'])
        self.assertIn('readiness',receipt)
        self.assertFalse(request('/api/import-file',body)['runs'][0]['imported'])
        from tracker.graph_store import catalog
        graph=catalog(self.store)['graphs'][0]
        stored=request('/api/graphs/'+graph['id'])
        self.assertEqual(sum(e['type']=='contains_call' for e in stored['edges']),1)
        audit=request('/api/map-foundation?graph='+graph['id'])
        self.assertEqual(audit['source_checks']['status'],'passed')
        malformed=deepcopy(body);malformed['file']['base64']=base64.b64encode(raw+b'\n{}').decode()
        with self.assertRaises(HTTPError) as error:request('/api/import-file',malformed)
        self.assertEqual(error.exception.code,400)
        self.assertEqual(len(self.store.list()),1)


if __name__=='__main__':unittest.main()
