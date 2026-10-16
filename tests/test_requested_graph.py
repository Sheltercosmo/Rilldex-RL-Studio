"""Requested clauses are historical objects, not activities or verified facts."""
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase

from tracker import request_changes as rc, requested_work as rw
from tracker.schema import digest, InputError
from test_work_correspondence import fixture as source_fixture


def fixture():
    run,local,_,users,actions=source_fixture()
    records=[];steps=[];ledger=[]
    def clause(u,cid,kind,text):
        return {'id':cid,'kind':kind,'text':text,'evidence':[u['source']]}
    for i,u in enumerate(users):
        before=deepcopy(records)
        if i==0:
            clauses=[clause(u,'wait','requirement','Wait for approval before writing.'),
                     clause(u,'check','requested_check','Confirm the destination.'),
                     clause(u,'claim','attributed_claim','The user says the destination is current.')]
            retired=[]
        else:
            clauses=deepcopy(records[0]['clauses'])
            retired=[]
            if i==1:
                clauses[1]=clause(u,'check','requested_check','Confirm the draft destination.')
            else:
                retired=[{'id':'claim','reason':'The user replaces the destination.', 'evidence':[u['source']]}]
                clauses=[c for c in clauses if c['id']!='claim']
        edit={'op':'introduce' if i==0 else 'revise','record_id':'conditions','kind':'condition',
              'text':u['source']['text'],'evidence':[u['source']], 'clauses':clauses,'retired_clauses':retired}
        records,delta=rw.apply_edits(run,u,records,[edit],rw.CLAUSE_VERSION)
        ledger.extend(delta)
        steps.append({'unit_id':u['id'],'previous_state_hash':digest(before),'status':'selected_update',
                      'changes':delta,'state_after':deepcopy(records)})
    work={'schema':rw.CLAUSE_VERSION,'status':'complete','run_id':run['id'],'source_hash':digest(run),
          'extraction_hash':digest(local),'steps':steps,'changes':ledger,'records':records}
    return run,{'source_hash':digest(run),'units':local['units'],'requested_work':work,'relations':[]},actions


def rewrite_record_chain(work, mutate):
    """Reconcile enclosing hashes so the test probes clause semantics/integrity."""
    states=[];ledger=[]
    for step in work['steps']:
        step['previous_state_hash']=digest(states)
        for change in step['changes']:
            before=deepcopy(next((r for r in states if r['id']==change['record_id']),None))
            change['before']=before;after=change['after'];mutate(after,change)
            after['version_id']='rv'+digest({'record':{k:v for k,v in after.items() if k!='version_id'},
                                           'previous_version':before['version_id'] if before else None})[:20]
            states=[r for r in states if r['id']!=after['id']]+[deepcopy(after)]
            ledger.append(deepcopy(change))
        step['state_after']=deepcopy(states)
    work['records']=states;work['changes']=ledger


class RequestedGraphTests(TestCase):
    def test_record_hash_alone_cannot_legitimize_a_forged_clause(self):
        for field,value in [('version_id','cvforged'),('source_unit_id','unknown'),('kind','unsupported_role')]:
            run,doc,_=fixture()
            def corrupt(after,change):after['clauses'][0][field]=value
            rewrite_record_chain(doc['requested_work'],corrupt)
            with self.assertRaises(InputError,msg=field):rc.changes(run,doc)

    def test_clause_cannot_disappear_without_a_retirement(self):
        run,doc,_=fixture()
        def corrupt(after,change):
            if change['operation']=='revise':
                after['clauses']=[c for c in after['clauses'] if c['id']!='wait']
        rewrite_record_chain(doc['requested_work'],corrupt)
        with self.assertRaisesRegex(InputError,'silently dropped'):rc.changes(run,doc)

    def test_retirement_cannot_rewrite_the_previous_clause(self):
        run,doc,_=fixture()
        def corrupt(after,change):
            for retired in change.get('retired_clauses',[]):retired['previous']['text']='Invented previous clause'
        rewrite_record_chain(doc['requested_work'],corrupt)
        with self.assertRaises(InputError):rc.changes(run,doc)

    def test_clauses_have_shared_identity_membership_and_explicit_retirement(self):
        from tracker import requested_graph as rg
        run,doc,actions=fixture();original=deepcopy(doc);graph=rg.export_graph(run,doc)
        nodes={n['id']:n for n in graph['nodes']};edges=graph['edges']
        clauses=[n for n in nodes.values() if n['kind']=='requested_clause_version']
        self.assertEqual(len(clauses),4)
        waiting=next(n for n in clauses if n['properties']['id']=='wait')
        self.assertEqual(sum(e['type']=='contains_requested_clause' and e['target']==waiting['id'] for e in edges),3)
        self.assertEqual(sum(e['type']=='updates_requested_clause' for e in edges),1)
        retirement=next(e for e in edges if e['type']=='retires_requested_clause')
        self.assertEqual(nodes[retirement['target']]['properties']['kind'],'attributed_claim')
        self.assertEqual(retirement['properties']['reason'],'The user replaces the destination.')
        self.assertFalse(any(e['type'] in {'satisfies','violates','completed'} for e in edges))
        self.assertEqual(doc,original)
        self.assertEqual({n['id'] for n in nodes.values() if n['kind']=='unit'},{u['id'] for u in doc['units']})
        self.assertEqual(graph,rg.export_graph(run,doc))

    def test_dispatch_links_keep_prior_clauses_and_exclude_later_retirement(self):
        from tracker import requested_graph as rg, request_dispatch as rd
        run,doc,actions=fixture();graph=rg.export_graph(run,doc);p=rd.build(run,doc)
        record=p['actions'][1]['records'][0]
        self.assertIn('claim',{c['id'] for c in record['clauses']})
        self.assertNotIn('FUTURE_APPROVAL',str(record))
        self.assertEqual(p['actions'][1]['correspondence_status'],'uninspected')
        self.assertEqual(graph['semantic_context']['requested_history']['term_comparison'],'uninspected')

    def test_graph_roundtrip_and_legacy_missing_clauses_stay_explicit(self):
        from tracker import requested_graph as rg, graph_store as gs
        from tracker.store import Store
        from test_request_dispatch import fixture as legacy_fixture
        run,doc,_=legacy_fixture();graph=rg.export_graph(run,doc)
        self.assertGreater(graph['semantic_context']['requested_history']['counts']['condition_versions_without_clauses'],0)
        self.assertFalse(any(n['kind']=='requested_clause_version' for n in graph['nodes']))
        with TemporaryDirectory() as directory:
            store=Store(Path(directory)/'test.sqlite');store.add([run])
            with store.connect() as connection:gs.save(connection,graph)
            restored=gs.read(store,graph['id']);gs.validate(restored)
            self.assertEqual(restored['semantic_context'],graph['semantic_context'])

    def test_normal_graph_build_includes_complete_conditions_without_changing_observer(self):
        from tracker import graph_store as gs
        run,doc,actions=fixture()
        graph=gs.build(run,{'observer':{'id':'original-observer','label':'Existing observer'},'document':doc})
        self.assertEqual(graph['observer'],'original-observer')
        self.assertEqual(sum(n['kind']=='requested_clause_version' for n in graph['nodes']),4)
        self.assertEqual(sum(e['type']=='request_context_at_dispatch' for e in graph['edges']),len(actions))
        self.assertEqual(graph['semantic_context']['requested_history']['term_comparison'],'uninspected')
        gs.validate(graph)
