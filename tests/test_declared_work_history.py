from copy import deepcopy
import unittest
from tracker import declared_work_history as history
from tracker.schema import digest,InputError
from tests.test_work_declarations import fixture


def local(run,doc):
    return {'status':'complete','source_hash':digest(run),'base_map_hash':digest(doc),'observations':[
        {'unit_id':u['id'],'request':'local-'+u['id'],'items':[{'id':'w','work':'Produce report A.',
         'declaration':'commits' if i%2==0 else 'reports_finished','evidence':[u['source']]}]} for i,u in enumerate(doc['units'])]}


class DeclaredWorkHistoryTests(unittest.TestCase):
    def test_identity_connects_statements_without_claiming_task_state(self):
        run,doc=fixture(['I will write A.','A is done.','I will write A again.']);source=local(run,doc);requests=[]
        def same(req):
            requests.append(req);return {'choice':{'value':req['state']['prior_records'][0]['id']}},digest(req)
        result=history.build(run,doc,source,same)
        self.assertEqual(len(result['records']),1);self.assertEqual(len(result['relations']),2)
        self.assertEqual([u['declaration'] for u in result['records'][0]['updates']],['commits','reports_finished','commits'])
        self.assertNotIn('active',result['records'][0]);self.assertNotIn('completed',result['records'][0])
        self.assertNotIn('I will write A again.',str(requests[0]))
        self.assertEqual([r['type'] for r in result['relations']],['declares_same_work_as']*2)

    def test_multiple_work_items_in_one_unit_are_not_merged_into_each_other(self):
        run,doc=fixture(['I will write A and review B.']);source=local(run,doc)
        second=deepcopy(source['observations'][0]['items'][0]);second.update(id='b',work='Review B.')
        source['observations'][0]['items'].append(second)
        result=history.build(run,doc,source,lambda _:self.fail('No prior contribution exists'))
        self.assertEqual(len(result['records']),2);self.assertEqual(result['relations'],[])

    def test_unresolved_never_creates_new_work_or_cross_actor_identity(self):
        run,doc=fixture(['I will write A.','I will review something.']);source=local(run,doc)
        result=history.build(run,doc,source,lambda req:({'choice':{'value':'unresolved'}},digest(req)))
        self.assertEqual(len(result['records']),1);self.assertEqual(result['observations'][1]['status'],'unresolved')
        doc['units'][1]['trajectory_id']='different';source['base_map_hash']=digest(doc)
        result=history.build(run,doc,source,lambda _:self.fail('Other trajectory has no prior records'))
        self.assertEqual(len(result['records']),2)

    def test_future_or_changed_local_basis_rejected(self):
        run,doc=fixture(['I will write A.']);source=local(run,doc);source['base_map_hash']='changed'
        with self.assertRaisesRegex(InputError,'Complete local'):history.build(run,doc,source,lambda _:None)

    def test_pair_identity_uses_focal_item_and_retains_conflicting_matches(self):
        run,doc=fixture(['I will convert A.','I will install Pandoc, then convert A.','It is done.']);source=local(run,doc)
        source['observations'][1]['items'][0]['work']='Install Pandoc.'
        requests=[]
        def compare(req):
            requests.append(req)
            value='distinct_work' if req['state']['unit_id']=='u1' else 'same_whole_work'
            return {k:{'value':value} for k in req['questions']},digest(req)
        result=history.build(run,doc,source,compare,history.PAIR_VERSION)
        self.assertEqual(len(result['records']),2)
        self.assertEqual(result['observations'][-1]['status'],'unresolved')
        self.assertEqual(set(result['observations'][-1]['pair_choices'].values()),{'same_whole_work'})
        self.assertNotIn('prefix',requests[0]['state'])
        self.assertIn('Install Pandoc.',next(iter(requests[0]['questions'].values()))['instructions'])
        self.assertEqual(result['relations'],[])


if __name__=='__main__':unittest.main()
