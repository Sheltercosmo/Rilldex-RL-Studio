"""Native frozen public trace regressions plus explicitly authored schema controls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tracker.adapters import normalize
from tracker.capabilities import links
from tracker import declared_plans, graph_store, monitoring, monitor_evidence, measurement_reviews
from tracker.schema import InputError
from tracker.store import Store

ROOT=Path(__file__).parent/'fixtures'/'nebius-openhands'


def source():return json.loads((ROOT/'jbradberry-universe.json').read_text(encoding='utf-8'))


class NativeOpenHandsTests(unittest.TestCase):
    def test_frozen_native_calls_text_and_exact_source_pointers(self):
        manifest=json.loads((ROOT/'source.json').read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256((ROOT/'jbradberry-universe.json').read_bytes()).hexdigest(),manifest['fixture_sha256'])
        raw=source();run=normalize(raw)[0];self.assertEqual(run['adapter'],'nebius-openhands');self.assertEqual(run['raw'],raw)
        calls=[c for m in raw['trajectory'] for c in m.get('tool_calls') or []]
        actions=[e for e in run['events'] if e['kind']=='action'];self.assertEqual(len(actions),len(calls))
        self.assertEqual(len(actions),55)
        for e,c in zip(actions,calls):
            self.assertEqual((e['call_id'],e['tool'],e['raw_arguments']),(c['id'],c['function']['name'],c['function']['arguments']))
            pointer=e['source_pointer'].split('/');self.assertEqual(raw['trajectory'][int(pointer[2])]['tool_calls'][int(pointer[4])],c)
        for i,m in enumerate(raw['trajectory']):
            e=next(e for e in run['events'] if e['source_pointer']==f'/trajectory/{i}/content')
            self.assertEqual(e['text'],m['content'] or '')
        paired=links(run)['by_action']
        for e in actions:
            original=next((m for m in raw['trajectory'] if m['role']=='tool' and m['tool_call_id']==e['call_id']),None)
            self.assertEqual([f['text'] for f in paired.get(e['id'],[])],[original['content']] if original else [])

    def test_legacy_selector_dispatches_native_schema_and_incomplete_rows_fail(self):
        raw=source();a=normalize(raw)[0];self.assertEqual(normalize(raw,'nebius')[0],a)
        bundle={'rows':[{'row_idx':14,'row':raw,'truncated_cells':[]}]}
        for fmt in ('auto','nebius','nebius-openhands'):
            run=normalize(bundle,fmt)[0];self.assertEqual(run['adapter'],'nebius-openhands');self.assertEqual(run['metadata']['dataset_row'],14)
        del raw['trajectory_id']
        with self.assertRaisesRegex(InputError,'Structured chat trajectory'):normalize(raw)
        bundle['rows'][0]['truncated_cells']=['trajectory']
        with self.assertRaisesRegex(InputError,'truncated'):normalize(bundle)

    def test_outcome_does_not_become_agent_context_or_training_clock(self):
        raw=source();run=normalize(raw)[0]
        self.assertIs(run['outcome']['verified_success'],bool(raw['resolved']))
        self.assertEqual(run['outcome']['success_source_pointer'],'/resolved')
        self.assertNotIn('recorded_reward',run['outcome'])
        for key in ('training_step','checkpoint','policy_version'):self.assertFalse(run['metadata'].get(key))
        changed=deepcopy(raw);changed.update(model_patch='PRIVATE_PATCH_SENTINEL',resolved=1-raw['resolved'],gen_tests_correct=99)
        self.assertEqual(normalize(changed)[0]['events'],run['events'])
        changed['resolved']=True
        with self.assertRaisesRegex(InputError,'resolved'):normalize(changed)

    def test_native_plan_ids_and_receipts_retain_real_targets(self):
        run=normalize(source())[0];projection=declared_plans.project(run)
        self.assertEqual((len(projection['snapshots']),len(projection['issues'])),(5,0))
        self.assertTrue(all(s['identity']=='native_id' for s in projection['snapshots']))
        self.assertEqual(projection['metrics'],dict(value=0,numerator=0,denominator=6,opportunities=6,unknown=0))
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db.sqlite');store.add([run])
            monitor=monitoring.create(store,dict(name='Native reported reopenings',kind='analysis',observer='source',analysis={'measure':'declared_plan_reopen_fraction'},group='Behavior'))
            monitoring.sync(store);value=monitoring.values(store,monitor['id'],{run['id']})[run['id']]
            receipt=monitor_evidence.read(store,value['id'])
            self.assertEqual(value['denominator'],6)
            self.assertEqual(sum(e['type']=='retains_declared_plan_id' for e in receipt['graph']['edges']),16)
            self.assertFalse(any(n['kind']=='unit' for n in receipt['graph']['nodes']))
            self.assertEqual(receipt['explanation']['analysis_cases'][0]['declared_plan_change']['identity'],'native_id')

    def test_native_id_rename_reuse_and_duplicates_are_not_guessed(self):
        run=normalize(source())[0];events=[e for e in run['events'] if e['kind']=='action' and e['tool']=='task_tracker' and e['arguments']['command']=='plan']
        # Authored modifications of the captured payload, explicitly not new public labels.
        before,after=deepcopy(events[1:3]);before['arguments']['task_list']=before['arguments']['task_list'][:1]
        after['arguments']['task_list']=after['arguments']['task_list'][:1];after['arguments']['task_list'][0]['status']='todo'
        def measured(a,b):return declared_plans.project({**run,'events':[a,b]})
        self.assertEqual(measured(before,after)['metrics']['value'],1)
        rename=deepcopy(after);rename['arguments']['task_list'][0]['title']='A different requirement'
        self.assertEqual(measured(before,rename)['records'][0]['reason'],'item_text_changed')
        replaced=deepcopy(after);replaced['arguments']['task_list'][0]['id']='new-id'
        self.assertEqual(measured(before,replaced)['records'][0]['reason'],'item_not_retained')
        duplicate=deepcopy(after);duplicate['arguments']['task_list']*=2
        self.assertEqual(measured(before,duplicate)['records'][0]['reason'],'duplicate_item_id')
        unknown=deepcopy(after);unknown.pop('tool_contract')
        self.assertEqual(measured(before,unknown)['coverage']['invalid_declarations'],1)

    def test_review_identifies_the_exact_entry_when_cases_share_a_list(self):
        run=normalize(source())[0];projection=declared_plans.project(run)
        cases=declared_plans.measure(projection,'initial_completed')['cases']
        subjects=[measurement_reviews.structured_subject(case,run['events']) for case in cases]
        self.assertEqual([s['value']['id'] for s in subjects],['fix-1','fix-2','fix-3','fix-4'])
        self.assertEqual(len({s['event_id'] for s in subjects}),1)
        self.assertEqual(len({s['argument_pointer'] for s in subjects}),4)
        broken=deepcopy(cases[0]);broken['initial_item']['argument_pointer']='/task_list/99'
        with self.assertRaises(InputError):measurement_reviews.structured_subject(broken,run['events'])


if __name__=='__main__':unittest.main()
