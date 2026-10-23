import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError
from unittest.mock import patch

from rilldex import Run, Workspace
from tracker import run_records as rr
from tracker.schema import InputError
from tracker.store import Store
import test_generation_cohort_transport as transport


class TrainerContextTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.db=self.root/'study.sqlite';self.store=Store(self.db)

    def add(self,capture,*,producer='worker',experiment='run',config=None,links=None):
        payload=dict(name='Trial',project='Project',config=config or {},runtime={})
        if links is not None:payload['trainer_sessions']=links
        return rr.receive(self.store,dict(schema=rr.VERSION,producer=producer,experiment=experiment,
            records=[dict(id=capture,session=capture,kind='manifest',observed_at='2026-10-22T10:00:00Z',payload=payload)]))

    def context(self,session,**kwargs):return rr.trainer_context(self.store,experiment='run',producer='worker',session=session,**kwargs)

    def test_exact_links_and_no_prefix_timestamp_or_cross_worker_guess(self):
        self.add('process',links=['training/1']);self.add('training',links=['training/2'])
        self.add('wrong-worker',producer='other',links=['training/1'])
        self.add('wrong-run',experiment='elsewhere',links=['training/1'])
        result=self.context('training/1');self.assertEqual([r['session'] for r in result['capture_sessions']],['process'])
        self.assertEqual(result['capture_sessions'][0]['basis'],['declared_trainer_session'])
        self.assertEqual(self.context('training/3')['capture_sessions'],[])
        self.assertEqual(self.context('process')['capture_sessions'][0]['basis'],['same_session'])
        self.assertEqual(Workspace(self.db,experiment='run').trainer_context(producer='worker',session='training/1'),result)

    def test_ambiguous_capture_choices_and_late_link_cutoff(self):
        self.add('first',links=['learn']);old=self.context('learn')
        self.add('second',links=['learn'])
        self.assertEqual(len(self.context('learn')['capture_sessions']),2)
        self.assertEqual(self.context('learn',as_of=old['as_of']),old)
        self.assertEqual(self.context('learn',as_of=0)['capture_sessions'],[])
        with self.assertRaises(InputError):self.context('learn',as_of=True)

    def test_existing_native_sb3_explicit_link_and_stable_capture_ordinals(self):
        self.add('z',config={'trainer_session':'learn'})
        self.add('a')
        self.assertEqual(self.context('learn')['capture_sessions'][0]['session'],'z')
        rows=rr.records(self.store,experiment='run')['streams']
        self.assertEqual([(r['session'],r['ordinal']) for r in rows],[('z',1),('a',2)])
        self.assertEqual(rr.records(self.store,experiment='run',q='no match')['streams'],rows)

    def test_sdk_snapshots_are_immutable_and_link_subsessions(self):
        with patch('rilldex.run.runtime_context',return_value={}):
            run=Run('Trial',workspace=self.db,experiment='run',producer='worker',capture_console=False,hardware=False,config={'lr':.01})
        run.log_config({'lr':.002},trainer_session='learn/2');run.console('correct process')
        result=self.context('learn/2');self.assertEqual(result['capture_sessions'][0]['session'],run.session)
        self.assertEqual(result['capture_sessions'][0]['counts'],{'manifest':2,'console':1})
        rows=rr.records(self.store,experiment='run',kind='manifest')['rows']
        self.assertEqual([r['record']['payload']['config']['lr'] for r in rows],[.01,.002])
        for invalid in ('string',[None],['']):
            with self.subTest(invalid=invalid),self.assertRaises(InputError):self.add('invalid',links=invalid)
        self.assertEqual(rr.records(self.store,experiment='run',kind='manifest')['total'],2)
        run.close()

    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)
    def test_http_scope_and_validation(self):
        self.add('process',links=['learn'])
        endpoint=transport.GenerationCohortTransportTests.start_server(self)
        selection=dict(experiment='run',producer='worker',session='learn')
        with urlopen(endpoint+'/api/trainer-telemetry/context?'+urlencode(selection)) as response:
            self.assertEqual(json.load(response),self.context('learn'))
        with self.assertRaises(HTTPError) as error:urlopen(endpoint+'/api/trainer-telemetry/context?experiment=run')
        self.assertEqual(error.exception.code,400)


if __name__=='__main__':unittest.main()
