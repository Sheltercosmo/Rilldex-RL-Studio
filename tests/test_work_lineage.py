from copy import deepcopy
from unittest import TestCase,main

from tracker.schema import InputError
from tracker.work_lineage import build
from tracker.requested_work import apply_edits
from tracker.semantic_map import evidence
from research.work_purpose_trial import fixture,CASES


def sample(index=1):
    run,local,work=fixture(CASES[index])
    return run,{'units':local['units'],'requested_work':work,'relations':[],'review_notes':[]}


def link(doc,record_id,version=None):
    action=next(u for u in doc['units'] if u['kind']=='action')
    record=version or next(r for r in doc['requested_work']['records'] if r['id']==record_id)
    return {'from':action['id'],'to':record['source_unit_id'],'type':'attempts_requested_work',
            'requested_work_id':record_id,'requested_work_version_id':record['version_id'],'request_hash':'decision'}


class WorkLineageTests(TestCase):
    def test_revision_retains_identity_and_inputs(self):
        run,doc=sample();before=deepcopy(doc);result=build(run,doc)
        self.assertEqual(doc,before)
        row=next(r for r in result['records'] if r['record_id']=='reservation')
        self.assertEqual([v['operation'] for v in row['versions']],['introduce','revise'])
        self.assertEqual(row['versions'][1]['previous_version_id'],row['versions'][0]['version_id'])
        self.assertEqual(result['counts']['work_records'],2)
        self.assertNotIn('progress',row);self.assertNotIn('completed',row)

    def test_shared_scope_never_spreads_a_passenger_specific_action(self):
        run,doc=sample(6);doc['relations']=[link(doc,'alex')]
        user=next(u for u in doc['units'] if u['actor']=='user')
        doc['work_context']={'frames':[{'id':'scope','source':user['source'],'unit_ids':[user['id']]}],
            'observations':[{'status':'selected','frame_ids':['scope']}]}
        rows={r['record_id']:r for r in build(run,doc)['records']}
        self.assertEqual(rows['alex']['counts']['linked_dispatches'],1)
        self.assertEqual(rows['blair']['counts']['linked_dispatches'],0)
        self.assertEqual(rows['alex']['versions'][0]['context_frame_ids'],['scope'])
        self.assertEqual(rows['blair']['versions'][0]['context_frame_ids'],['scope'])

    def test_withdrawal_and_later_attempt_remain_distinct(self):
        run,doc=sample(5);doc['relations']=[link(doc,'a')]
        row=build(run,doc)['records'][0]
        self.assertEqual(row['latest_status'],'withdrawn')
        self.assertEqual([v['operation'] for v in row['versions']],['introduce','withdraw'])
        self.assertEqual(row['counts']['linked_dispatches'],1)

    def test_superseded_version_at_dispatch_is_rejected(self):
        run,doc=sample();old=next(c['after'] for c in doc['requested_work']['changes'] if c['record_id']=='reservation')
        doc['relations']=[link(doc,'reservation',old)]
        with self.assertRaisesRegex(InputError,'superseded'):build(run,doc)

    def test_chain_and_final_state_must_match_saved_history(self):
        run,doc=sample();doc['requested_work']['changes'][-1]['before']['text']='other terms'
        with self.assertRaisesRegex(InputError,'before-version'):build(run,doc)
        run,doc=sample();doc['requested_work']['records'][0]['text']='invented final state'
        with self.assertRaisesRegex(InputError,'final versions'):build(run,doc)

    def test_unique_dispatch_denominator_and_exact_relation_review(self):
        run,doc=sample(6);a,b=link(doc,'alex'),link(doc,'blair');doc['relations']=[a,deepcopy(a),b]
        doc['review_notes']=[{'text':'Disputed','relation_ref':{k:a[k] for k in ('from','to','type','requested_work_version_id')}}]
        result=build(run,doc);rows={r['record_id']:r for r in result['records']}
        self.assertEqual(result['counts']['unique_linked_dispatches'],1)
        self.assertEqual(rows['alex']['counts']['reviewed_correspondences'],1)
        self.assertEqual(rows['blair']['counts']['reviewed_correspondences'],0)

    def test_late_request_update_is_kept_without_fabricating_an_action(self):
        run,doc=sample(3);source=next(e for e in run['events'] if e['actor']=='user')
        event={**source,'id':'late','index':max(e['index'] for e in run['events'])+1,
               'text':'Use expedited shipping for shipment B.','source_pointer':'/later-user-input'}
        run['events'].append(event);ref=evidence(run,'late')
        unit={**next(u for u in doc['units'] if u['actor']=='user'),'id':'late-unit','source':ref}
        doc['units'].append(unit);work=doc['requested_work']
        work['records'],delta=apply_edits(run,unit,work['records'],[{'op':'revise','record_id':'shipment','text':event['text'],'evidence':[ref]}])
        work['changes'].extend(delta)
        row=next(r for r in build(run,doc)['records'] if r['record_id']=='shipment')
        self.assertEqual(row['versions'][-1]['source_unit_id'],'late-unit')
        self.assertEqual(row['versions'][-1]['context_frame_ids'],[])
        self.assertEqual(row['later_recorded_dispatch_event_ids'],[])
        self.assertEqual(row['counts']['linked_dispatches'],0)

    def test_wrong_instance_or_trajectory_link_is_rejected(self):
        for field,value in [('requested_work_id','other'),('to','other')]:
            run,doc=sample(6);relation=link(doc,'alex');relation[field]=value;doc['relations']=[relation]
            with self.assertRaisesRegex(InputError,'wrong source'):build(run,doc)

    def test_absence_is_explicit_and_not_zero_work(self):
        run,doc=sample();doc.pop('requested_work');result=build(run,doc)
        self.assertFalse(result['available']);self.assertNotIn('counts',result)

    def test_same_record_name_in_another_trajectory_is_a_distinct_history(self):
        run,doc=sample();original=next(e for e in run['events'] if e['actor']=='user')
        event={**original,'id':'other-user','index':max(e['index'] for e in run['events'])+1,
               'trajectory_id':'other','text':'Update reservation B.','source_pointer':'/other-user'}
        run['events'].append(event);ref=evidence(run,event['id'])
        unit={**next(u for u in doc['units'] if u['actor']=='user'),'id':'other-unit','trajectory_id':'other','source':ref}
        doc['units'].append(unit)
        new,changes=apply_edits(run,unit,[],[{'op':'introduce','record_id':'reservation','kind':'work','text':event['text'],'evidence':[ref]}])
        doc['requested_work']['records'].extend(new);doc['requested_work']['changes'].extend(changes)
        result=build(run,doc);rows=[r for r in result['records'] if r['record_id']=='reservation']
        self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['id'],rows[1]['id'])
        doc['relations']=[link(doc,'reservation',new[0])]
        with self.assertRaisesRegex(InputError,'wrong source'):build(run,doc)


if __name__=='__main__':main()
