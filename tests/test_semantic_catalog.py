import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tracker import semantic_catalog
from tracker.schema import InputError,digest
from tracker.semantic_extraction import Pipeline,read,write,partition_request
from tests.test_plan_relations import Provider,fixture,transport


class Store:
    def __init__(self,run):self.run=run
    def get(self,rid,raw=False):
        if rid!=self.run['id']:raise InputError('Unknown run')
        return {'run':self.run}


class SemanticCatalogTests(unittest.TestCase):
    def test_only_complete_source_bound_results_are_listed_and_loads_remain_audited(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=fixture();store=Store(run)
            engine=Pipeline(root,Provider(root/'candidates'),transport);x=engine.run(run)
            profiles={'test':{'kind':'extraction','directory':root,'label':'Test observer'}}
            with patch.object(semantic_catalog,'PROFILES',profiles):
                rows=semantic_catalog.catalog(store)['maps'];self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['source_hash'],digest(run))
                self.assertEqual(semantic_catalog.load(run,'test')['observer']['label'],'Test observer')
                loaded=semantic_catalog.load(run,'test');exported=semantic_catalog.export_payload(loaded)
                self.assertEqual(exported['map'],loaded['document'])
                self.assertEqual(exported['observer']['extraction_hash'],digest(x))
                self.assertEqual(loaded['export_digest'],digest(exported))
                altered=copy.deepcopy(loaded);altered['document']['review_notes'].append({'text':'Changed review'})
                self.assertNotEqual(digest(semantic_catalog.export_payload(altered)),loaded['export_digest'])
                changed=copy.deepcopy(x);changed['source_hash']='different';write(root/'results'/f'{run["id"]}.json',changed)
                self.assertEqual(semantic_catalog.catalog(store)['maps'],[])
                with self.assertRaisesRegex(InputError,'source changed'):semantic_catalog.load(run,'test')
                changed=copy.deepcopy(x);changed['status']='needs_work';write(root/'results'/f'{run["id"]}.json',changed)
                self.assertEqual(semantic_catalog.catalog(store)['maps'],[])
                with self.assertRaisesRegex(InputError,'Unknown semantic observer'):semantic_catalog.load(run,'../../secrets')

    def test_boundary_refactor_preserves_exact_saved_legacy_request(self):
        saved=read('research/semantic-extraction-2026-10-07/decisions/d1ed3ddd0e95eb396c803b7fa2a567708e3bf9309b4ec42dd1541e8d4c8af2bc.json')['request']
        run=read('research/semantic-extraction-2026-10-07/runs/d8c0e38f633a068fbc7aed74.json')
        s=saved['state']
        self.assertEqual(partition_request(run,s['subject'],s['partitions'],s['context_policy'],s['partition_standard']),saved)
        with self.assertRaisesRegex(InputError,'partition standard'):
            partition_request(run,s['subject'],s['partitions'],s['context_policy'],'unknown')


if __name__=='__main__':unittest.main()
