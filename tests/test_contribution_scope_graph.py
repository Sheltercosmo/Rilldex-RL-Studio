from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tracker import contribution_scope_graph as scope, contribution_work as cw, graph_store, unit_reviews
from tracker.schema import InputError
from tracker.semantic_extraction import read
from tracker.store import Store
from test_unit_reviews import document as review_document


def fixture():
    folder=Path('research/contribution-target-pairs-2026-10-12')
    run,base,_=cw.load('research/contribution-work-mapped-2026-10-12/retrieval')
    packets=[]
    for case in read(folder/'manifest.json')['cases']:
        raw=read(folder/'decisions'/f"{case['request_hash']}.json")
        packets.append({'current':case['current'],'priors':case['priors'],'request':raw['request'],'response':raw['response']})
    return run,base,packets


class ContributionScopeGraphTests(unittest.TestCase):
    def test_real_saved_choices_produce_partial_relations_without_changing_units_or_groups(self):
        run,base,packets=fixture();original=deepcopy(base)
        graph=scope.fork(run,base,packets);graph_store.validate(graph)
        self.assertEqual(base,original);self.assertEqual(graph['nodes'],base['nodes'])
        layer=graph['semantic_context']['contribution_scope']
        self.assertEqual(layer['pair_count'],4);self.assertEqual(len(layer['replaced_edges']),1)
        self.assertNotIn('work_subjects',graph['semantic_context'])
        edges=[e for e in graph['edges'] if e['properties'].get('scope_layer')==scope.VERSION]
        self.assertEqual(len(edges),4)
        self.assertEqual(sum(e['type']=='same_work_target' for e in edges),1)
        self.assertEqual(sum(e['type']=='overlapping_work_scope' for e in edges),1)
        self.assertEqual(scope.fork(run,base,layer['receipts']),graph)

    def test_changed_endpoint_request_model_or_duplicate_pair_is_rejected(self):
        run,base,packets=fixture()
        for field in ('unit','request','model','duplicate'):
            altered=deepcopy(packets)
            if field=='unit':altered[0]['current']['content']['target']['text']='Different work'
            elif field=='request':altered[0]['request']['state']['comparison_rule']='Different criterion'
            elif field=='model':altered[0]['response']['model']='another model'
            else:altered.append(altered[0])
            with self.subTest(field=field),self.assertRaises(InputError):scope.fork(run,base,altered)

    def test_unit_repair_invalidates_scope_receipts_and_edges(self):
        run,base,packets=fixture();graph=scope.fork(run,base,packets)
        uid=packets[0]['current']['id']
        changed=unit_reviews.fork(run,graph,review_document(run,graph,uid,activity='report',text='Changed reported target'))
        self.assertNotIn('contribution_scope',changed['semantic_context'])
        self.assertIn('contribution_scope',changed['semantic_context']['unit_reviews']['impact']['invalidated_layers'])
        self.assertFalse(any(e['properties'].get('scope_layer')==scope.VERSION for e in changed['edges']))
        self.assertFalse(any(n.get('basis')==scope.VERSION for n in changed['semantic_context']['review_notes']))

    def test_registration_is_idempotent_and_retains_original_graph(self):
        run,base,packets=fixture()
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'test.sqlite');store.add([run])
            a=scope.register(store,run,base,packets);b=scope.register(store,run,base,packets)
            self.assertEqual(a,b)
            # The database returns nodes in event order; immutable graph identity
            # validates the same contents after canonical ordering.
            self.assertEqual(graph_store.read(store,base['id'])['id'],base['id'])
            self.assertEqual(graph_store.read(store,a['graph_id'])['id'],scope.fork(run,base,packets)['id'])


if __name__=='__main__':unittest.main()
