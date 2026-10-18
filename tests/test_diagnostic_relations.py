"""Recorded attribution and joins, not tests of model classification accuracy."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace

from tracker import diagnostic_context as context, diagnostic_search as search
from tracker.adapters import normalize
from tracker.diagnostic_monitors import from_run
from tracker.schema import dumps
from test_diagnostic_monitors import source
from test_tracker import harbor
from tracker import diagnostic_direct as direct, diagnostic_worker as worker
from tracker.semantic_extraction import read, write
from tracker.store import Store
from test_diagnostic_direct import wire


def interleaved():
    return source(trace=dumps([
        {'id':'ua','trajectory_id':'A','actor':'user','kind':'instruction','text':'Repair parser A.'},
        {'id':'ub','trajectory_id':'B','actor':'user','kind':'instruction','text':'Research browser B.'},
        {'id':'aa','trajectory_id':'A','actor':'agent','kind':'action','call_id':'same','tool':'read','text':'Read parser A.'},
        {'id':'ab','trajectory_id':'B','actor':'agent','kind':'action','call_id':'same','tool':'read','text':'Read browser B.'},
        {'id':'fb','trajectory_id':'B','actor':'environment','kind':'feedback','source_call_id':'same','text':'Browser B result.'},
        {'id':'fa','trajectory_id':'A','actor':'environment','kind':'feedback','source_call_id':'same','text':'Parser A result.'}]))


class RelationContextTests(unittest.TestCase):
    def test_capture_preserves_native_identity_without_changing_legacy_source(self):
        run=normalize(harbor(),'harbor')[0]
        legacy=from_run(run);fresh=search.source_from_run(run,search.SCOPED_VERSION)
        self.assertEqual(search.source_from_run(run,search.TASK_CONTEXT_VERSION),legacy)
        old=json.loads(legacy['trace']);new=json.loads(fresh['trace']);events={e['id']:e for e in run['events']}
        self.assertTrue(all('trajectory_id' not in row for row in old))
        for row in new:
            event=events[row['id']];self.assertEqual(row['trajectory_id'],event['trajectory_id'])
            for key in ('call_id','source_call_id','related_action_ids'):
                if key in event:self.assertEqual(row[key],event[key])

    def test_task_and_results_stay_in_the_native_trajectory_with_reused_ids(self):
        from tracker import diagnostic_relations as relations
        s=interleaved();fs=search.index(s,search.SCOPED_VERSION);a=[f for f in fs if f.get('event_id')=='aa']
        old=context.task(s,a);self.assertIn('browser B',old['text'])  # Reproduces v9 loss of scope.
        packet=relations.packet(s,a)
        self.assertEqual(packet['complete_recorded_task']['text'],'Repair parser A.')
        links=packet['recorded_result_links'];self.assertEqual(len(links),1)
        self.assertEqual((links[0]['action_event_id'],links[0]['feedback_event_id']),('aa','fa'))
        self.assertNotIn('Browser B result',dumps(packet))

    def test_one_page_can_bind_different_tasks_to_different_actions(self):
        from tracker import diagnostic_relations as relations
        s=interleaved();fs=search.index(s,search.SCOPED_VERSION);a=[f for f in fs if f.get('kind')=='action']
        packet=relations.packet(s,a)
        self.assertNotIn('complete_recorded_task',packet)
        for f in a:
            task=packet['recorded_tasks'][packet['candidate_task_ids'][f['id']]]
            self.assertIn('parser A' if f['event_id']=='aa' else 'browser B',task['text'])

    def test_future_and_ambiguous_returns_are_not_linked(self):
        from tracker import diagnostic_relations as relations
        rows=json.loads(interleaved()['trace']);rows[4]['trajectory_id']='A';rows[4]['source_call_id']='missing'
        rows.append({**rows[2],'id':'duplicate'})
        s=source(trace=dumps(rows));fs=search.index(s,search.SCOPED_VERSION)
        packet=relations.packet(s,[f for f in fs if f.get('kind')=='action'])
        self.assertFalse(packet['recorded_result_links'])
        rows=[rows[5],rows[2]];s=source(trace=dumps(rows));fs=search.index(s,search.SCOPED_VERSION)
        self.assertFalse(relations.packet(s,fs)['recorded_result_links'])

    def test_missing_call_ids_do_not_get_adjacent_result_links(self):
        from tracker import diagnostic_relations as relations
        rows=json.loads(interleaved()['trace'])
        for row in rows:row.pop('call_id',None);row.pop('source_call_id',None)
        s=source(trace=dumps(rows));self.assertFalse(relations.packet(s,search.index(s,search.SCOPED_VERSION))['recorded_result_links'])

    def test_single_recorded_action_reference_is_supported(self):
        from tracker import diagnostic_relations as relations
        rows=json.loads(interleaved()['trace']);rows[5].pop('source_call_id');rows[5]['related_action_ids']=['aa']
        s=source(trace=dumps(rows));fs=search.index(s,search.SCOPED_VERSION)
        packet=relations.packet(s,[f for f in fs if f.get('event_id')=='aa'])
        self.assertEqual(packet['recorded_result_links'][0]['basis'],'recorded_action_reference')

    def test_unbound_agent_does_not_inherit_another_agents_task(self):
        from tracker import diagnostic_relations as relations
        rows=json.loads(interleaved()['trace']);rows=[r for r in rows if r['id']!='ub']
        s=source(trace=dumps(rows));fs=search.index(s,search.SCOPED_VERSION)
        packet=relations.packet(s,[f for f in fs if f.get('kind')=='action'])
        self.assertNotIn('complete_recorded_task',packet)
        b=next(f for f in fs if f.get('event_id')=='ab')
        self.assertNotIn(b['id'],packet['candidate_task_ids'])

    def test_only_linked_partner_text_is_added_and_oversize_is_explicit(self):
        from tracker import diagnostic_relations as relations
        s=interleaved();fs=search.index(s,search.SCOPED_VERSION)
        packet=relations.packet(s,[f for f in fs if f.get('event_id')=='aa'])
        self.assertEqual([r['event_id'] for r in packet['linked_source_records']],['fa'])
        for r in packet['linked_source_records']:
            span=r['source'];raw=json.loads(s['trace'][span['start']:span['end']])
            self.assertEqual(r['text'],raw['text'])
        with patch.object(relations,'LINK_LIMIT',1):
            packet=relations.packet(s,[f for f in fs if f.get('event_id')=='aa'])
        self.assertFalse(packet['linked_source_records']);self.assertEqual(len(packet['omitted_linked_record_ids']),1)
        self.assertEqual(len(packet['recorded_result_links']),1)

    def test_new_worker_capture_publishes_and_replays_without_recalculating(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'db');run=normalize(harbor(),'harbor')[0]
            store.add([run]);selector=worker.selection(run_ids=[run['id']]);folder=root/'scoped'
            worker.initialize(store,folder,selector,'search')
            config=read(folder/'worker.json');config['protocol']=search.protocol(search.SCOPED_VERSION);write(folder/'worker.json',config)
            seen=[]
            def capture(req):seen.append(req);return wire(req)
            worker.execute(store,folder,capture,selector=selector,protocol_name='search',max_new_calls=10)
            self.assertTrue(seen);self.assertTrue(any(r['state']['recorded_result_links'] for r in seen))
            frozen=read(next(folder.glob('runs/*/*/input.json')))
            self.assertEqual(frozen,search.source_from_run(run,search.SCOPED_VERSION))
            self.assertTrue(worker.audit(store,folder)['runs'][0]['validation']['exact_replay'])
            result=worker.execute(store,folder,lambda _:self.fail('No repeated provider request'),selector=selector,protocol_name='search',max_new_calls=0)
            self.assertEqual(result['new_calls'],0)

    def test_native_scope_is_on_each_exact_source_fragment(self):
        s=interleaved();fs=search.index(s,search.SCOPED_VERSION)
        self.assertEqual(''.join(f['text'] for f in fs if f['origin']=='trace'),s['trace'])
        for f in fs:
            if f.get('event_id'):
                self.assertEqual(f['trajectory_id'],'A' if f['event_id'].endswith('a') else 'B')
        requests=list(direct.requests(s,search.SCOPED_VERSION))
        self.assertTrue(requests[0]['state']['candidate_task_ids'])

    def test_cli_new_capture_and_historical_resume_use_their_own_version(self):
        from tracker import diagnostic_cli as cli
        with TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'db');run=normalize(harbor(),'harbor')[0];store.add([run])
            old=root/'old';search.execute(search.source_from_run(run,search.TASK_CONTEXT_VERSION),old,wire,version=search.TASK_CONTEXT_VERSION)
            args=SimpleNamespace(run_id=run['id'],input=None,protocol='search',directory=str(old),audit_only=False,prompt_key=False)
            with redirect_stdout(StringIO()),patch('tracker.jev.JevClient._post',side_effect=AssertionError('Historical calls must stay cached')):
                cli.execute(args,store);args.audit_only=True;cli.execute(args,store)
            self.assertEqual(search.workspace_protocol(old)['schema'],search.TASK_CONTEXT_VERSION)
            args.directory=str(root/'new');args.audit_only=False
            with redirect_stdout(StringIO()),patch('tracker.jev.JevClient._post',side_effect=wire):cli.execute(args,store)
            self.assertEqual(read(root/'new/input.json'),search.source_from_run(run,search.SCOPED_VERSION))
            args.audit_only=True
            with redirect_stdout(StringIO()):cli.execute(args,store)

    def test_new_instruction_is_bound_only_to_subsequent_actions(self):
        from tracker import diagnostic_relations as relations
        rows=json.loads(interleaved()['trace']);rows=[r for r in rows if r['trajectory_id']=='A']
        rows.extend([{'id':'next','trajectory_id':'A','actor':'user','kind':'instruction','text':'Now repair the lexer.'},
                     {'id':'later','trajectory_id':'A','actor':'agent','kind':'action','text':'Edit lexer.'}])
        s=source(trace=dumps(rows));fs=[f for f in search.index(s,search.SCOPED_VERSION) if f.get('kind')=='action']
        packet=relations.packet(s,fs);self.assertNotIn('complete_recorded_task',packet)
        for f in fs:
            text=packet['recorded_tasks'][packet['candidate_task_ids'][f['id']]]['text']
            self.assertEqual('Now repair the lexer.' in text,f['event_id']=='later')


if __name__=='__main__':unittest.main()
