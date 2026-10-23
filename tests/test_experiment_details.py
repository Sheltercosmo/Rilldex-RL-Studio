from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from rilldex import Workspace
from tracker.store import Store
from tracker.trainer_telemetry import TrainerTelemetry
from tracker.execution_records import receive
from tracker.experiment_details import details
from tracker.telemetry_evidence import evidence
from tracker.investigation_workspace import annotate
from tracker.schema import InputError


class ExperimentDetailsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db.sqlite')

    def logger(self, producer='learner', session='session-a', environment='software', population='logged batch'):
        return TrainerTelemetry(self.store,experiment='job',producer=producer,session=session,
            environment=environment,population=population,framework='trl-grpo',framework_version='fixture',objective='grpo')

    def operation(self, identifier, *, producer='learner', experiment='job', revision=0, environment=None, config=None, refs=None, kind='configuration', state='completed'):
        record=dict(id=identifier,revision=revision,kind=kind,rollout=None,state=state,
            context={'environment':environment} if environment else {},evidence='authored control',
            timing=dict(clock='seconds',start=100,end=101 if state=='completed' else None))
        if config is not None:record['configuration']=config
        if refs is not None:record['telemetry']=refs
        receive(self.store,dict(schema='execution-records/2',producer=producer,experiment=experiment,records=[record]))

    def test_settings_latest_revision_is_scoped_and_does_not_merge_partial_snapshots(self):
        self.operation('update',kind='learner_update',state='running',config={'lr':0.01,'nested':{'temperature':1}})
        self.operation('update',kind='learner_update',revision=1,config={'lr':0.01,'nested':{'temperature':1}})
        self.operation('change',config={'lr':0.02})
        self.operation('other-env',environment='airline',config={'private_field':'airline'})
        self.operation('other-job',experiment='other',config={'private_field':'other'})
        data=details(self.store,experiment='job',environment='software')
        self.assertEqual(data['counts']['settings'],2)
        by_id={r['id']:r for r in data['rows']}
        self.assertEqual(by_id['update']['revision'],1)
        self.assertEqual(by_id['change']['record']['configuration'],{'lr':0.02})
        self.assertEqual(details(self.store,experiment='job',q='temperature')['total'],1)
        self.assertEqual(details(self.store,experiment='job',q='%')['total'],0)

    def test_sessions_producers_and_populations_are_separate(self):
        self.logger().log({'reward':1},step=40)
        self.logger().log({'reward':2},step=41)
        self.logger(session='session-b').log({'reward':3},step=0)
        self.logger(producer='rank-b').log({'reward':4},step=40)
        self.logger(population='heldout tasks').log({'reward':5},step=40)
        self.logger(environment='airline').log({'reward':6},step=40)
        data=details(self.store,experiment='job',environment='software',section='trainers',limit=2)
        self.assertEqual(data['total'],4)
        second=details(self.store,experiment='job',environment='software',section='trainers',limit=2,offset=2)
        self.assertEqual(sum(r['logs'] for r in data['rows']+second['rows']),5)
        old=next(r for r in data['rows']+second['rows'] if r['logs']==2)
        self.assertEqual((old['first_step'],old['last_step']),(40,41))

    def test_history_preserves_corrections_outside_page_and_other_clocks(self):
        raw=dict(experiment='job',kind='sampling',title='Temperature change',detail='recorded by researcher',step=40,clock='generation',basis='rollout_step')
        first=annotate(self.store,raw)
        from tracker.experiment_catalog import catalog
        self.assertEqual(catalog(self.store)['rows'][0]['experiment'],'job')
        self.assertEqual(catalog(self.store)['rows'][0]['history_events'],1)
        annotate(self.store,{**raw,'title':'Corrected event','supersedes':first['id'],'step':41})
        annotate(self.store,{**raw,'title':'Airline-only change','environment':'airline'})
        selected=details(self.store,experiment='job',environment='software',section='history',q='Temperature change',limit=1)
        self.assertEqual(selected['total'],1)
        self.assertTrue(selected['rows'][0]['superseded'])
        self.assertEqual(selected['rows'][0]['clock'],'generation')

    def test_exact_execution_refs_not_step_or_id_alone_link_to_point(self):
        self.logger().log({'reward':1},step=40,record_id='log-40')
        ref=[dict(producer='learner',id='log-40')]
        self.operation('linked',refs=ref,config={'precision':'bf16'})
        self.operation('same-id-other-producer',refs=[dict(producer='other',id='log-40')])
        self.operation('same-ref-other-experiment',experiment='other',refs=ref)
        self.operation('no-ref',config={'step':40})
        value=evidence(self.store,experiment='job',producer='learner',record_id='log-40')
        self.assertEqual(value['executions']['total'],1)
        self.assertEqual(value['executions']['records'][0]['id'],'linked')
        self.assertEqual(value['executions']['records'][0]['trainer_logs'][0]['step'],40)
        self.assertEqual(value['executions']['records'][0]['trainer_logs'][0]['session'],'session-a')
        self.assertEqual(value['run_ids'],[])

    def test_empty_validation_and_code_access(self):
        self.assertEqual(details(self.store,experiment='missing')['total'],0)
        for kwargs in [dict(experiment=None),dict(experiment='job',section='raw'),dict(experiment='job',limit=True),dict(experiment='job',offset=-1)]:
            with self.assertRaises(InputError):details(self.store,**kwargs)
        self.operation('config',config={'lr':0.01})
        ws=Workspace(self.store.path,experiment='job')
        self.assertEqual(ws.experiment_details()['rows'][0]['record']['configuration'],{'lr':0.01})


if __name__=='__main__':unittest.main()
