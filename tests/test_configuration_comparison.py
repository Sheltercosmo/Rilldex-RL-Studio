import json
from pathlib import Path
import tempfile
import unittest
from rilldex import Workspace
from tracker.store import Store
from tracker.schema import InputError
from tracker.run_records import receive
from tracker.configuration_comparison import compare
from tracker.experiment_catalog import catalog
import test_experiment_details as helpers


class ConfigurationComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'study.sqlite')

    def manifest(self,experiment,config,session='first'):
        receive(self.store,dict(schema='run-records/1',producer='worker',experiment=experiment,records=[dict(
            id=session,session=session,kind='manifest',observed_at='2026-10-23T00:00:00Z',
            payload=dict(name=experiment,project='study',config=config,runtime={}))]))

    operation=helpers.ExperimentDetailsTests.operation

    def test_typed_nested_values_missing_null_false_and_escaped_paths(self):
        self.manifest('a',{'enabled':False,'value':None,'zero':0,'nested':{'lr':1e-6},'nested.lr':4,'a/b':{'~key':[]}})
        self.manifest('b',{'enabled':0,'value':'null','zero':0,'nested':{'lr':1e-5},'nested.lr':4})
        result=Workspace(self.store.path).compare_settings(['a','b'])
        rows={r['path']:r for r in result['rows']}
        self.assertEqual(result['differences'],4)
        self.assertEqual(rows['/enabled']['cells'][0]['type'],'boolean')
        self.assertEqual(rows['/enabled']['cells'][1]['type'],'number')
        self.assertEqual(rows['/a~1b/~0key']['cells'][1],{'present':False})
        self.assertEqual(result['fields'],6)
        all_rows=compare(self.store,experiments=['a','b'],differences_only=False)['rows']
        self.assertIn('/nested.lr',[r['path'] for r in all_rows])

    def test_snapshot_choices_preserve_restart_and_late_arrivals(self):
        self.manifest('a',{'lr':1});self.manifest('b',{'lr':2})
        old=compare(self.store,experiments=['a','b']);picks={r['experiment']:r['selected']['id'] for r in old['runs']}
        self.manifest('a',{'lr':2},'restarted')
        self.assertEqual(compare(self.store,experiments=['a','b'])['differences'],0)
        held=compare(self.store,experiments=['a','b'],sources=picks)
        self.assertEqual(held['differences'],1)
        self.assertEqual(held['runs'][0]['selected']['session'],'first')
        self.assertEqual(held['runs'][0]['source_count'],2)

    def test_manifest_and_partial_operation_are_not_merged(self):
        self.manifest('a',{'lr':1,'batch':32});self.manifest('b',{'lr':1,'batch':32})
        self.operation('update',experiment='a',kind='learner_update',config={'lr':2})
        default=compare(self.store,experiments=['a','b'])
        self.assertEqual(default['differences'],0)
        operation=next(c for c in default['runs'][0]['choices'] if c['kind'].startswith('Operation'))
        result=compare(self.store,experiments=['a','b'],sources={'a':operation['id']})
        self.assertEqual(result['runs'][0]['selected']['config'],{'lr':2})
        self.assertEqual(result['differences'],2)

    def test_execution_revision_and_environment_scope(self):
        self.operation('config',experiment='a',config={'temperature':1},environment='software',state='running')
        self.operation('config',experiment='b',config={'temperature':1},environment='software')
        result=compare(self.store,experiments=['a','b'],environment='software')
        old=result['runs'][0]['selected']['id']
        self.operation('config',experiment='a',config={'temperature':1},environment='software',revision=1)
        self.operation('changed',experiment='a',config={'temperature':2},environment='software')
        self.assertEqual(compare(self.store,experiments=['a','b'],environment='software')['differences'],1)
        self.assertEqual(compare(self.store,experiments=['a','b'],environment='software',sources={'a':old})['differences'],0)
        with self.assertRaises(InputError):compare(self.store,experiments=['a','b'],sources={'b':old})
        with self.assertRaises(InputError):compare(self.store,experiments=['a','b'],environment='airline',sources={'a':old})

    def test_paging_search_and_empty_snapshots(self):
        self.manifest('a',{str(i):i for i in range(250)});self.manifest('b',{})
        result=compare(self.store,experiments=['a','b'],limit=100,offset=200)
        self.assertEqual((result['fields'],result['total'],len(result['rows'])),(251,251,51))
        self.assertEqual(compare(self.store,experiments=['a','b'],q='false')['total'],0)
        self.assertEqual(compare(self.store,experiments=['a','b'],q='/249')['total'],1)
        empty=compare(self.store,experiments=['a','missing'],sources={'a':None})
        self.assertEqual(empty['fields'],0);self.assertIsNone(empty['runs'][1]['selected'])
        self.manifest('missing',{'late':1})
        held=compare(self.store,experiments=['a','missing'],sources={'a':None,'missing':None})
        self.assertEqual(held['fields'],0)

    def test_old_pick_outside_recent_inventory_still_resolves(self):
        self.manifest('a',{'seed':0});self.manifest('b',{'seed':1})
        old=compare(self.store,experiments=['a','b'])['runs'][0]['selected']['id']
        for i in range(55):self.manifest('a',{'seed':i+1},str(i))
        result=compare(self.store,experiments=['a','b'],sources={'a':old})
        self.assertEqual(result['runs'][0]['source_count'],56)
        self.assertEqual(len(result['runs'][0]['choices']),50)
        self.assertEqual(result['runs'][0]['selected']['config'],{'seed':0})

    def test_configuration_search_uses_settings_not_runtime_and_keeps_filters(self):
        self.manifest('a',{'policy':'Qwen','mode':'baseline_100%'});self.manifest('b',{'policy':'other'})
        self.assertEqual(catalog(self.store,q='Qwen')['total'],0)
        self.assertEqual(catalog(self.store,q='Qwen',search_in='settings')['rows'][0]['experiment'],'a')
        self.assertEqual(catalog(self.store,q='%',search_in='settings')['total'],1)
        self.assertEqual(catalog(self.store,q='Qwen',search_in='settings',project='missing')['total'],0)
        self.operation('config',experiment='c',environment='software',state='running',config={'policy':'unique'})
        self.operation('config',experiment='c',environment='software',revision=1,config={'policy':'unique'})
        self.assertEqual(catalog(self.store,q='unique',search_in='settings',environment='software')['total'],1)
        self.assertEqual(catalog(self.store,q='unique',search_in='settings',environment='airline')['total'],0)

    def test_invalid_requests(self):
        for extra in [dict(sources=[]),dict(sources={'outside':'x'}),dict(sources={'a':'[]'}),dict(limit=0),dict(differences_only=1),dict(offset=-1)]:
            with self.subTest(extra=extra),self.assertRaises(InputError):compare(self.store,experiments=['a','b'],**extra)
        with self.assertRaises(InputError):compare(self.store,experiments=['a'])
        with self.assertRaises(InputError):catalog(self.store,search_in='unknown')


if __name__=='__main__':unittest.main()
