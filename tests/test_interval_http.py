import json
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import test_generation_cohort_transport as transport
from rilldex import chat_document
from tracker.adapters import normalize
from tracker import monitoring


class IntervalHTTPTests(unittest.TestCase):
    setUp=transport.GenerationCohortTransportTests.setUp
    start_server=transport.GenerationCohortTransportTests.start_server
    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)

    def test_cross_run_case_capture_report_and_followup(self):
        for name,success in [('candidate',False),('reference',True)]:
            self.store.add(normalize(chat_document([dict(role='assistant',content='Attempt '+name)],
                metadata=dict(experiment=name,task_id='task',task_revision='1',environment='terminal',
                    environment_version='1',split='eval',reward_definition='check/1'),success=success)))
        endpoint=self.start_server()
        def call(path,body=None):
            req=Request(endpoint+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=20) as response:return json.load(response)
        self.assertEqual(len(call('/api/case-comparisons/scopes')['experiments']),2)
        saved=call('/api/investigations/cases',dict(reference={'experiment':'reference'},selected={'experiment':'candidate'}))
        from rilldex import Workspace
        later=Workspace(self.store.path,observer='source').monitor('Later code measure',version='test/1',description='Created after comparison')
        options=call('/api/investigations/'+saved['id']+'/measures')
        self.assertIn(later.id,[r['id'] for r in options['choices']])
        self.assertNotIn(later.id,[r['id'] for r in saved['snapshot']['behavior']['choices']])
        self.assertEqual(call('/api/investigations/'+saved['id']),saved)
        listing=call('/api/case-comparisons?investigation='+saved['id'])
        self.assertEqual(listing['counts'],{'regressed':1})
        revised=call('/api/investigations/follow-ups',dict(parent_id=saved['id'],action='plan',check=dict(
            title='Inspect regression',hypothesis='Different checks',procedure='Review saved checks',expected_result='A concrete check difference')))
        self.assertEqual(revised['snapshot'],saved['snapshot'])
        with urlopen(endpoint+'/api/investigations/'+revised['id']+'/report',timeout=20) as response:
            html=response.read().decode();self.assertIn('regressed',html);self.assertIn('candidate',html)
        with self.assertRaises(HTTPError) as error:
            call('/api/investigations/cases',dict(reference={'experiment':'reference'},selected={'experiment':'reference'}))
        self.assertEqual(error.exception.code,400)

    def test_full_http_capture_followup_history_and_assets(self):
        for step in range(4):
            run=normalize(chat_document([dict(role='assistant',content='Attempt '+str(step))],
                metadata=dict(experiment='http',training_step=step,training_clock='policy',training_step_basis='generation'),success=step<2))[0]
            self.store.add([run])
        monitor=monitoring.create(self.store,dict(name='Task success',kind='metric',metric='recorded_success',observer='source'))
        monitoring.sync(self.store);endpoint=self.start_server()
        def call(path,body=None):
            req=Request(endpoint+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=20) as response:return json.load(response)
        for path in ['/interval-investigation.js','/interval-investigation.css','/case-comparisons.js','/case-comparisons.css',
                     '/inspection-paths.js','/inspection-view.js','/inspection-paths.css','/case-behavior.js','/case-behavior.css','/measurement-case-links.js']:
            with urlopen(endpoint+path,timeout=10) as response:
                self.assertEqual(response.status,200);self.assertGreater(len(response.read()),100)
        presets = {q['id']: q for q in call('/api/monitoring/questions')['questions']}
        self.assertEqual(set(presets), {'self-revision', 'comparable-performance', 'selection-delay',
                                      'recovery', 'reward-outcomes', 'compute-progress'})
        from tracker.graph_store import catalog
        gid=catalog(self.store)['graphs'][0]['id']
        foundation=call('/api/map-foundation?graph='+gid)
        self.assertEqual(foundation['source_checks']['status'],'passed')
        self.assertEqual(foundation['semantic_review']['status'],'not_independently_validated')
        saved=call('/api/investigations/interval',dict(experiment='http',baseline=[0,1],current=[2,3],monitor_ids=[monitor['id']]))
        self.assertEqual(saved['snapshot']['panels'][0]['cohorts'][0]['delta'],-1)
        call('/api/experiment-history',dict(experiment='http',kind='restart',title='Restarted',detail='Restored from the last policy',step=3,clock='policy',basis='generation',investigation_id=saved['id']))
        self.assertEqual(len(call('/api/experiment-history?experiment=http')['events']),1)
        self.assertEqual(call('/api/investigations/'+saved['id']),saved)
        self.assertEqual(saved['snapshot']['history'],[])
        revised=call('/api/investigations/follow-ups',dict(parent_id=saved['id'],action='plan',check=dict(title='Repeat fixed eval',hypothesis='Real regression',procedure='Evaluate same tasks',expected_result='Drop repeats')))
        self.assertEqual(revised['snapshot'],saved['snapshot'])
        with self.assertRaises(HTTPError) as error:
            call('/api/investigations/interval',dict(experiment='http',baseline=[0,2],current=[2,3]))
        self.assertEqual(error.exception.code,400)


if __name__=='__main__':unittest.main()
