from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.schema import InputError
from tracker.state_capture import WorkStateRecorder, source_ref, call_ref, file_versions, object_version
from tracker.work_state import derive, capture
from tests.test_investigation_process import captured


def source():
    raw = deepcopy(captured()['raw']); raw.pop('work_state')
    return raw


def recorded(raw, stable=True):
    r = WorkStateRecorder(environment='controlled-env/1')
    a = lambda i: source_ref(f'/trajectory/{i}/action', kind='action')
    b = lambda i: source_ref(f'/trajectory/{i}/observation', kind='feedback')
    first = r.snapshot(a(0), {'app': 'v1', 'test': 'v1'})
    fixed = r.snapshot(b(1), {'app': 'v2', 'test': 'v1'})
    final = r.snapshot(b(3), {'app': 'v3', 'test': 'v1'})
    for index, snap, result in [(0, first, 'failed'), (2, fixed, 'passed')]:
        r.check(a(index), b(index), snapshot=snap, criterion_id='acceptance', criterion_version='v1',
                required_objects=['app','test'], outcome=result, state_stable=stable)
    r.edit(a(1), b(1), before=first, after=fixed)
    r.edit(a(3), b(3), before=fixed, after=final)
    r.deliver(a(4), snapshot=final, requirements=[{'criterion_id':'acceptance','criterion_version':'v1','basis':'task'}])
    return r


class StateCaptureTests(unittest.TestCase):
    def test_native_source_binding_retains_events_and_distinguishes_recovery_from_final_verification(self):
        raw = source(); original = deepcopy(raw); recorder = recorded(raw)
        attached = recorder.attach(raw, format='swe-agent')
        run = normalize(attached,'swe-agent')[0]; facts = derive(run)
        self.assertEqual(raw,original)
        self.assertEqual(run['events'],normalize(raw,'swe-agent')[0]['events'])
        self.assertEqual(facts['episodes'][0]['status'],'recovered')
        self.assertEqual(facts['deliveries'][0]['status'],'changed_inputs')
        self.assertEqual(attached,recorder.attach(raw,format='swe-agent'))
        with self.assertRaisesRegex(InputError,'overwrite'): recorder.attach(attached,format='swe-agent')

    def test_matching_hashes_never_invent_input_stability(self):
        raw=source(); recorder=recorded(raw,stable=None)
        facts=derive(normalize(recorder.attach(raw,format='swe-agent'),'swe-agent')[0])
        self.assertEqual(facts['metrics']['check_binding']['value'],1)
        self.assertIsNone(facts['metrics']['recovery']['value'])
        self.assertEqual(facts['deliveries'][0]['status'],'unknown')

    def test_portable_chat_native_call_ids_do_not_depend_on_internal_event_numbers(self):
        from tracker.portable import chat_document
        messages=[{'role':'user','content':'Check this record.'},
                  {'role':'assistant','content':'Checking','tool_calls':[{'id':'check-1','type':'function','function':{'name':'validate','arguments':'{}'}}]},
                  {'role':'tool','tool_call_id':'check-1','content':'failed'},
                  {'role':'assistant','content':'The check failed.'}]
        raw=chat_document(messages=messages)
        recorder=WorkStateRecorder(environment='orders/1')
        snap=recorder.snapshot(call_ref('check-1'),{'order':object_version({'paid':False})})
        recorder.check(call_ref('check-1'),call_ref('check-1',result=True),snapshot=snap,
                       criterion_id='paid',criterion_version='1',required_objects=['order'],outcome='failed')
        before=recorder.attach(raw)
        raw['messages'].insert(0,{'role':'system','content':'Validate recorded orders.'})
        after=recorder.attach(raw)
        self.assertNotEqual(before['work_state']['checks'][0]['action_id'],after['work_state']['checks'][0]['action_id'])
        self.assertEqual(derive(normalize(after)[0])['checks'][0]['result'],'failed')

    def test_missing_ambiguous_wrong_kind_and_future_references_fail_atomically(self):
        raw=source()
        for ref in [source_ref('/absent'),source_ref('/trajectory/0/action',kind='feedback')]:
            recorder=recorded(raw);recorder.snapshots[next(iter(recorder.snapshots))]['at']=ref
            with self.subTest(ref=ref),self.assertRaises(InputError):recorder.attach(raw,format='swe-agent')
            self.assertNotIn('work_state',raw)
        recorder=recorded(raw);recorder.snapshots[next(iter(recorder.snapshots))]['at']=source_ref('/trajectory/4/action')
        with self.assertRaisesRegex(InputError,'Future'):recorder.attach(raw,format='swe-agent')

    def test_mismatched_result_and_invalid_scope_are_rejected(self):
        raw=source();r=recorded(raw);r.checks[0]['result_ref']=source_ref('/trajectory/2/observation')
        with self.assertRaisesRegex(InputError,'result link'):r.attach(raw,format='swe-agent')
        r=recorded(raw);r.checks[0]['result']='passed'
        with self.assertRaisesRegex(InputError,'contradicts'):r.attach(raw,format='swe-agent')
        with self.assertRaisesRegex(InputError,'input scope'):
            r.check(source_ref('/a'),source_ref('/b'),snapshot=next(iter(r.snapshots)),criterion_id='x',
                    criterion_version='1',required_objects=['missing'],outcome='unknown')

    def test_file_versions_bound_paths_bytes_absence_and_json_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'app.py').write_bytes(b'old');(root/'empty').write_bytes(b'')
            initial=file_versions(root,['app.py','missing','empty'])
            self.assertEqual(initial['missing'],'absent');self.assertTrue(initial['app.py'].startswith('sha256:'))
            (root/'app.py').write_bytes(b'new')
            self.assertNotEqual(initial['app.py'],file_versions(root,['app.py'])['app.py'])
            for paths in [['../outside'],[str(root/'app.py')],['app.py','app.py'],['.']]:
                with self.subTest(paths=paths),self.assertRaises(InputError):file_versions(root,paths)
            with self.assertRaisesRegex(InputError,'byte limit'):file_versions(root,['app.py'],max_bytes=2)
            self.assertEqual(len(file_versions(root,['empty'],max_bytes=0)),1)
            self.assertEqual(object_version({'a':1,'b':2}),object_version({'b':2,'a':1}))
            self.assertNotEqual(object_version(None),object_version('null'))

    def test_recorder_freezes_values_and_keeps_actor_checks_at_collector_boundary(self):
        objects={'app':'v1'};r=WorkStateRecorder(environment='env')
        sid=r.snapshot(source_ref('/trajectory/0/action'),objects);objects['app']='v2'
        self.assertEqual(r.snapshots[sid]['objects']['app'],'v1')
        run=captured();action=next(e for e in run['events'] if e['kind']=='action')
        action['actor']='user'
        with self.assertRaisesRegex(InputError,'agent action'):capture(run)
        run['raw'].pop('work_state')
        facts=derive(run)
        self.assertNotIn(action['id'],[q['action_id'] for q in facts['checks']])
        self.assertNotIn(action['id'],[q['event_id'] for q in facts['operations']])


if __name__=='__main__':unittest.main()
