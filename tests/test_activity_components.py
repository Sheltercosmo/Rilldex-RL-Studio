"""Source/provenance and comparison contracts; all labels here are fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tracker.activity import ActivityClient, units
from tracker.activity_context import visible_prefix
from tracker.activity_components import prepare_import, summary, compare
from tracker.activity_verification import isolated_verification_request
from tracker.jev import validate_answers, SELECTION_POLICY
from tracker.schema import digest, InputError
from tracker.store import Store
from test_activity import reasoning_run, response


def package(path, run=None):
    run=run or reasoning_run();subject=units(run)[0]
    original=ActivityClient().request(run,subject['id']);isolated=isolated_verification_request(original)
    cases=[{'case_id':'fixture','origin':'real','set':'development','run_id':run['id'],'source_hash':digest(run['raw']),
            'target':subject,'source_prefix':visible_prefix(run,subject),'domain':'synthetic-test-fixture',
            'requests':{'baseline':original,'repeat':copy.deepcopy(original),'isolated':isolated}}]
    manifest={'version':'synthetic-component-fixture/1','model':original['model'],'selection_policy':SELECTION_POLICY,
              'cases_hash':digest(cases),'variants':['baseline','repeat','isolated']}
    path.mkdir()
    for name,data in [('cases.json',cases),('manifest.json',manifest)]:
        (path/name).write_text(json.dumps(data),encoding='utf-8')
    for v,request in cases[0]['requests'].items():
        choices={'verify':'present' if v!='baseline' else 'absent'}
        result=validate_answers(response(request,choices),request)
        for answer in result.values():answer.pop('evidence',None)
        row={'case_id':'fixture','variant':v,'set':'development','model':original['model'],'selection_policy':SELECTION_POLICY,
             'request_hash':digest(request),'answers':result,'usage':{'input_tokens':12,'output_tokens':3},'elapsed_seconds':0.2}
        (path/(v+'-development.jsonl')).write_text(json.dumps(row)+'\n',encoding='utf-8')
    return run,subject


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'pack';self.run,self.subject=package(self.path)
        self.store=Store(self.root/'tracker.sqlite');self.store.add([self.run])

    def rewrite_case(self,mutate):
        cases=json.loads((self.path/'cases.json').read_text());mutate(cases[0])
        (self.path/'cases.json').write_text(json.dumps(cases))
        manifest=json.loads((self.path/'manifest.json').read_text());manifest['cases_hash']=digest(cases)
        (self.path/'manifest.json').write_text(json.dumps(manifest))
        for v,request in cases[0]['requests'].items():
            p=self.path/(v+'-development.jsonl');r=json.loads(p.read_text());r['request_hash']=digest(request);p.write_text(json.dumps(r)+'\n')

    def test_import_is_idempotent_and_never_changes_primary_observations(self):
        before=self.store.get(self.run['id'],raw=True)
        first=self.store.import_activity_components(self.path);second=self.store.import_activity_components(self.path)
        self.assertEqual(first['inserted_records'],3);self.assertEqual(second['inserted_records'],0)
        self.assertEqual(self.store.get(self.run['id'],raw=True),before)
        self.assertEqual(first['provider_calls'],0)
        catalog=self.store.activity_component_catalog(self.run['id'])
        self.assertEqual(catalog['collections'][0]['available_runs'][0]['units'],1)

    def test_identical_repeat_vs_separate_field_and_missing_is_not_negative(self):
        cid=self.store.import_activity_components(self.path)['collection_id']
        repeated=self.store.activity_component_comparison(cid,'baseline','repeat')['comparison']
        self.assertEqual(repeated['totals']['same_request_repeat_units'],1)
        self.assertEqual(repeated['totals']['changed_choices'],1)
        isolated=self.store.activity_component_comparison(cid,'baseline','isolated')
        self.assertEqual(isolated['comparison']['totals']['comparable_fields'],1)
        self.assertEqual(isolated['comparison']['totals']['reference_only_fields'],13)
        record=self.store.activity_component_record(isolated['comparison']['rows'][0]['candidate_id'])
        self.assertEqual(record['fields'],['verify'])
        self.assertEqual(record['source_prefix'],visible_prefix(self.run,self.subject))
        self.assertEqual(record['request']['state']['harness'],'activity-verify/0.1-experimental')

    def test_reuse_and_option_changes_are_separate_from_repeat_disagreement(self):
        _,docs=prepare_import(self.path,lambda _:self.run)
        rows=[summary(r) for r in docs]
        next(r for r in rows if r['variant']=='repeat')['reuse_basis']='Copied fixture result'
        result=compare(rows,'baseline','repeat')
        self.assertEqual(result['totals']['same_request_reuse_units'],1)
        right=next(r for r in rows if r['variant']=='isolated')
        right['questions']['verify']['criteria']['present']='A different meaning'
        result=compare(rows,'baseline','isolated')
        self.assertEqual(result['totals']['options_changed_fields'],1)
        self.assertEqual(result['totals'].get('comparable_fields',0),0)

    def test_same_unit_identifier_in_different_runs_is_not_joined(self):
        _,docs=prepare_import(self.path,lambda _:self.run);rows=[summary(r) for r in docs]
        duplicate=copy.deepcopy(rows);[r.update(run_id='another-run') for r in duplicate]
        result=compare(rows+duplicate,'baseline','repeat')
        self.assertEqual(result['totals']['paired_units'],2)

    def test_corrupt_source_prefix_and_subject_are_rejected_before_any_write(self):
        for change in (lambda c:c.update(source_hash='wrong'),
                       lambda c:c['source_prefix'].append({'id':'future'}),
                       lambda c:c['requests']['isolated']['state']['subject'].update(event_id='wrong')):
            with self.subTest(change=change):
                original={p:p.read_bytes() for p in self.path.iterdir()}
                self.rewrite_case(change)
                with self.assertRaises(InputError):self.store.import_activity_components(self.path)
                self.assertEqual(self.store.activity_component_catalog()['collections'],[])
                for p,b in original.items():p.write_bytes(b)

    def test_false_argmax_or_extra_owned_field_is_rejected(self):
        p=self.path/'isolated-development.jsonl';old=p.read_text();row=json.loads(old)
        row['answers']['verify']['value']='absent';p.write_text(json.dumps(row))
        with self.assertRaises(InputError):self.store.import_activity_components(self.path)
        row=json.loads(old);row['answers']['plan']=row['answers']['verify'];p.write_text(json.dumps(row))
        with self.assertRaises(InputError):self.store.import_activity_components(self.path)
        self.assertEqual(self.store.activity_component_catalog()['collections'],[])

    def test_invented_tool_contract_and_false_required_clipping_are_rejected(self):
        for change in (
            lambda c:c['requests']['isolated']['state']['subject'].update(tool_contract={
                'source_pointer':'/invented','definition_text':'An invented tool','source_characters':16}),
            lambda c:c['requests']['isolated']['state']['missingness'].update(required_truncated_event_ids=['invented']),
        ):
            with self.subTest(change=change):
                original={p:p.read_bytes() for p in self.path.iterdir()}
                self.rewrite_case(change)
                with self.assertRaises(InputError):self.store.import_activity_components(self.path)
                self.assertEqual(self.store.activity_component_catalog()['collections'],[])
                for p,b in original.items():p.write_bytes(b)

    def test_changed_existing_result_is_not_silently_replaced(self):
        self.store.import_activity_components(self.path)
        p=self.path/'repeat-development.jsonl';row=json.loads(p.read_text());row['elapsed_seconds']=99;p.write_text(json.dumps(row))
        with self.assertRaisesRegex(InputError,'immutable component result'):
            self.store.import_activity_components(self.path)
        self.assertEqual(self.store.activity_component_catalog()['collections'][0]['records'],3)

    def test_manifest_hash_and_unsafe_variant_path_are_rejected(self):
        p=self.path/'manifest.json';m=json.loads(p.read_text());m['cases_hash']='bad';p.write_text(json.dumps(m))
        with self.assertRaises(InputError):self.store.import_activity_components(self.path)
        m['cases_hash']=digest(json.loads((self.path/'cases.json').read_text()));m['variants']=['../outside'];p.write_text(json.dumps(m))
        with self.assertRaises(InputError):self.store.import_activity_components(self.path)


if __name__=='__main__':unittest.main()
