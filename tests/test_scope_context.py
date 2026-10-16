from copy import deepcopy
import unittest

from tracker.scope_context import build
from tracker.schema import InputError


def fixture():
    events=[{'id':'e'+str(i),'index':i} for i in range(8)]
    units=[{'id':str(i),'trajectory_id':'main','source':{'event_id':'e'+str(i),'start':0,'end':10}}
           for i in range(8)]
    def record(version):
        return {'id':'task','version_id':version,'kind':'work','status':'requested',
                'trajectory_id':'main','text':version}
    old,new=record('original'),record('changed')
    steps=[{'unit_id':'0','status':'selected_update','state_after':[old],
            'changes':[{'record_id':'task','operation':'introduce','before':None,'after':old}]},
           {'unit_id':'3','status':'selected_update','state_after':[new],
            'changes':[{'record_id':'task','operation':'revise','before':old,'after':new}]},
           {'unit_id':'6','status':'unchanged','state_after':[new],'changes':[]}]
    return {'events':events},{'units':units,'requested_work':{'status':'complete','steps':steps}}


class ScopeContextTests(unittest.TestCase):
    def test_changed_terms_are_compared_at_dispatch_without_future_updates(self):
        run,doc=fixture();original=deepcopy(doc)
        result=build(run,doc,doc['units'][1],doc['units'][5])
        self.assertTrue(result['version_state_changed'])
        self.assertEqual(result['previous']['record_versions'][0]['version_id'],'original')
        self.assertEqual(result['current']['record_versions'][0]['version_id'],'changed')
        self.assertEqual([r['source_unit_id'] for r in result['updates']],['3'])
        self.assertEqual(doc,original)

    def test_unchanged_contribution_is_not_a_version_change(self):
        run,doc=fixture();result=build(run,doc,doc['units'][4],doc['units'][7])
        self.assertFalse(result['version_state_changed']);self.assertEqual(result['updates'],[])
        self.assertEqual(result['previous']['source_unit_id'],'3')
        self.assertEqual(result['current']['source_unit_id'],'6')

    def test_same_event_cutoff_uses_completed_request_before_action_start(self):
        run,doc=fixture();doc['units'][3]['source'].update(event_id='e5',start=0,end=5)
        doc['units'][5]['source'].update(start=5,end=10)
        result=build(run,doc,doc['units'][1],doc['units'][5])
        self.assertTrue(result['version_state_changed'])
        doc['units'][3]['source']['end']=6
        result=build(run,doc,doc['units'][1],doc['units'][5])
        self.assertFalse(result['version_state_changed']);self.assertEqual(result['updates'],[])

    def test_other_trajectory_and_missing_history_do_not_imply_unchanged_scope(self):
        run,doc=fixture();doc['units'][3]['trajectory_id']='other'
        result=build(run,doc,doc['units'][1],doc['units'][5])
        self.assertFalse(result['version_state_changed'])
        del doc['requested_work']
        self.assertFalse(build(run,doc,doc['units'][1],doc['units'][5])['available'])

    def test_inconsistent_scope_dependencies_are_rejected(self):
        run,doc=fixture();doc['requested_work']['steps'][0]['state_after'][0]['trajectory_id']='other'
        with self.assertRaises(InputError):build(run,doc,doc['units'][1],doc['units'][5])
        run,doc=fixture();doc['requested_work']['steps'][0]['unit_id']='missing'
        with self.assertRaises(InputError):build(run,doc,doc['units'][1],doc['units'][5])


if __name__=='__main__':unittest.main()
