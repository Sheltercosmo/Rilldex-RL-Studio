import copy
import json
from pathlib import Path
import tempfile
import unittest

from tracker.schema import InputError
from tracker.source_study import compare
from tracker.store import Store
from tests.test_source_study import episode,study


class SourceInvestigationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'tracker.sqlite')
        self.rows=[episode('a',0,'g',0),episode('b',0,'g',1),episode('a',1,'h',1),episode('b',1,'h',0)]
        self.study=study(self.rows);self.store.add_study(self.study,self.rows)
        self.comparison=compare(self.study,'a','b')
        self.request={'reference':'a','checkpoint':'b','metric':'rate','task_id':'g',
                      'episode_ids':{'before':self.rows[0]['id'],'after':self.rows[1]['id']},
                      'note':'Counterexample, not an independent semantic reference.',
                      'expected_comparison_id':self.comparison['comparison_id'],
                      'view':{'filter':'g','direction':'positive'}}

    def test_export_contains_exact_comparison_source_episodes_and_note(self):
        receipt=self.store.save_investigation(self.study['id'],self.request)
        saved=self.store.investigation(self.study['id'],receipt['id'])
        self.assertEqual(saved['comparison'],self.comparison)
        self.assertEqual(saved['episodes'],{'before':self.rows[0],'after':self.rows[1]})
        self.assertEqual(saved['selection']['view'],self.request['view'])
        self.assertEqual(saved['note'],self.request['note'])
        self.assertEqual(saved['annotation_status'],'investigation_note_not_reference_label')
        self.assertEqual(len(saved['comparison']['tasks']),2) # Filter never changes cohort.
        self.assertEqual(self.store.save_investigation(self.study['id'],self.request),receipt)
        self.assertEqual(len(self.store.investigations(self.study['id'])),1)

    def test_note_edit_creates_new_version_preserving_prior_evidence(self):
        old=self.store.save_investigation(self.study['id'],self.request)
        changed={**self.request,'note':'A revised interpretation <script> remains text.'}
        new=self.store.save_investigation(self.study['id'],changed)
        self.assertNotEqual(old['id'],new['id'])
        self.assertEqual(self.store.investigation(self.study['id'],old['id'])['note'],self.request['note'])
        self.assertEqual(len(self.store.investigations(self.study['id'])),2)

    def test_stale_comparison_wrong_game_side_or_metric_and_partial_pair_are_rejected(self):
        mutations=[{'expected_comparison_id':'old'}, {'metric':'invented'}, {'task_id':'outside'},
                   {'episode_ids':{'before':self.rows[1]['id'],'after':self.rows[0]['id']}},
                   {'episode_ids':{'before':self.rows[0]['id'],'after':self.rows[3]['id']}},
                   {'episode_ids':{'before':self.rows[0]['id']}}, {'task_id':None},
                   {'view':{'filter':'','direction':'invented'}}, {'note':42}, {'delta':99}]
        for changes in mutations:
            with self.subTest(changes=changes),self.assertRaises(InputError):
                self.store.save_investigation(self.study['id'],{**self.request,**changes})
        self.assertEqual(self.store.investigations(self.study['id']),[])

    def test_cohort_note_has_no_selected_episodes(self):
        request={**self.request,'task_id':None,'episode_ids':{}}
        result=self.store.save_investigation(self.study['id'],request)
        saved=self.store.investigation(self.study['id'],result['id'])
        self.assertIsNone(saved['selected_game']);self.assertEqual(saved['episodes'],{})
        self.assertEqual(len(saved['comparison']['tasks']),2)

    def test_changed_raw_evidence_is_rejected_but_saved_snapshot_stays_reproducible(self):
        receipt=self.store.save_investigation(self.study['id'],self.request)
        row=copy.deepcopy(self.rows[0]);row['raw']['evidence']=100
        with self.store.connect() as c:
            c.execute('UPDATE study_episodes SET document=? WHERE id=?',(json.dumps(row),row['id']))
        with self.assertRaisesRegex(InputError,'episode evidence changed'):
            self.store.save_investigation(self.study['id'],self.request)
        self.assertEqual(self.store.investigation(self.study['id'],receipt['id'])['episodes']['before'],self.rows[0])

    def test_saved_receipt_tampering_is_detected_on_read_and_listing(self):
        receipt=self.store.save_investigation(self.study['id'],self.request)
        saved=self.store.investigation(self.study['id'],receipt['id']);saved['note']='changed in storage'
        with self.store.connect() as c:c.execute('UPDATE source_investigations SET document=? WHERE id=?',(json.dumps(saved),receipt['id']))
        with self.assertRaisesRegex(InputError,'identity differs'):self.store.investigation(self.study['id'],receipt['id'])
        with self.assertRaisesRegex(InputError,'identity differs'):self.store.investigations(self.study['id'])


if __name__=='__main__':unittest.main()
