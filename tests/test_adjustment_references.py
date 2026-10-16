from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from shutil import copytree
from unittest import TestCase
from tracker import adjustment_references as ar
from tracker.schema import digest,InputError
from tracker.semantic_extraction import Pipeline,read

ROOT=Path(__file__).resolve().parents[1]/'research'

class AdjustmentReferenceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        work=ROOT/'work-items-complete-2026-10-08/software'
        cls.inputs=tuple(read(work/name) for name in ['source.json','base-map.json','complete.json','history.json','action-correspondence.json'])+(read(ROOT/'adjustment-effects-2026-10-08/software/local-adjustments.json'),)
        cls.events={u['id']:u['source']['event_id'] for u in cls.inputs[1]['units']}

    def test_candidates_require_prior_action_and_work_preparation_not_just_recency(self):
        rows=ar.candidates(*self.inputs);current={self.events[r['unit_id']]:r for r in rows}
        self.assertEqual(len(rows),5);self.assertEqual(current['e74']['candidates'],[])
        self.assertEqual([self.events[c['unit_id']] for c in current['e95']['candidates']],['e74','e80','e92'])
        changed=deepcopy(self.inputs);changed[4]['relations']=[r for r in changed[4]['relations'] if r['type']!='prepares_declared_work']
        self.assertTrue(all(not r['candidates'] for r in ar.candidates(*changed)))

    def test_all_candidates_require_selection_and_none_is_selected_by_nearness(self):
        requests=[]
        def reject(req):
            requests.append(req);return {q:{'value':'not_referenced'} for q in req['questions']},digest(req)
        result=ar.build(*self.inputs,reject)
        self.assertEqual(len(requests),4);self.assertEqual(result['relations'],[])
        self.assertEqual(result['observations'][0]['status'],'no_prior_graph_candidate')

    def test_current_item_context_does_not_contain_later_conversion(self):
        row=next(r for r in ar.candidates(*self.inputs) if self.events[r['unit_id']]=='e95')
        unit=next(u for u in self.inputs[1]['units'] if u['id']==row['unit_id'])
        req=ar.make_request(self.inputs[0],unit,row)
        self.assertEqual(set(req['questions']),{'c0','c1','c2'})
        text=str(req)
        for event in ['e96','e97','e98','e101']:
            self.assertNotIn("'event_id': '"+event+"'",text)
        self.assertIn('Update the Markdown report',text)

    def test_raw_argmax_audit_and_changed_dependencies(self):
        def transport(req):
            return {'model':req['model'],'answers':{q:{'type':'choice','choice':'not_referenced','confidence':0,
                'probabilities':{c:float(c=='references') for c in spec['criteria']}} for q,spec in req['questions'].items()}}
        with TemporaryDirectory() as folder:
            engine=Pipeline(folder,None,transport)
            result,validation=ar.execute(*self.inputs,engine)
            self.assertEqual(engine.calls,4);self.assertEqual(len(result['relations']),7)
            self.assertTrue(validation['argmax_replayed'])
            cached=Pipeline(folder,None,lambda _:self.fail('No replay transport'))
            self.assertEqual(ar.build(*self.inputs,cached.decide),result)
            broken=deepcopy(result);broken['relations'].pop()
            with self.assertRaises(InputError):ar.audit(*self.inputs,broken,folder)
        broken=deepcopy(self.inputs);broken[5]['work_items_hash']='changed'
        with self.assertRaises(InputError):ar.candidates(*broken)

    def test_registered_reference_snapshot_is_audited_and_does_not_change_earlier_map(self):
        from tracker import adjustment_graph,semantic_catalog
        from tracker.store import Store
        from tracker.semantic_extraction import write
        with TemporaryDirectory() as folder:
            folder=Path(folder);references=folder/'references';copytree(ROOT/'adjustment-effects-2026-10-08/references',references)
            store=Store(folder/'tracker.sqlite');store.add([self.inputs[0]])
            work=ROOT/'work-items-complete-2026-10-08/software';effects=ROOT/'adjustment-effects-2026-10-08/software'
            earlier=adjustment_graph.register(store,work,effects,'Local effects')
            before=semantic_catalog.load(self.inputs[0],earlier['observer'],store)['document']
            current=adjustment_graph.register(store,work,effects,'Effects and references',reference_directory=references)
            view=semantic_catalog.load(self.inputs[0],current['observer'],store)['document']
            self.assertEqual(view['units'],before['units'])
            edges=[r for r in view['relations'] if r['type']=='uses_correction_from']
            self.assertEqual([(self.events[r['from']],self.events[r['to']]) for r in edges],[('e77','e74'),('e83','e80'),('e95','e92')])
            self.assertFalse(any(r['type']=='attempts_local_adjustment' and self.events.get(r['from'])=='e96' for r in view['relations']))
            self.assertEqual(view['adjustment_graph']['metrics'],before['adjustment_graph']['metrics'])
            changed=read(references/'adjustment-references.json');changed['relations'][0]['to']='altered';write(references/'adjustment-references.json',changed)
            with self.assertRaises(InputError):semantic_catalog.load(self.inputs[0],current['observer'],store)
            self.assertEqual(semantic_catalog.load(self.inputs[0],earlier['observer'],store)['document'],before)
