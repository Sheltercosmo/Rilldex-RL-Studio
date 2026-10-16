from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tracker import request_changes as rc
from tracker.schema import digest, InputError
from tracker.semantic_extraction import Pipeline, FileCandidates, read, write
from research.request_changes_trial import fixture, CASES


class RequestChangeTests(TestCase):
    def choose(self, req):
        stage=req['state']['stage'].removeprefix('requested_term_')
        return {'choice':{'value':{'support':'supported','scope':'same_undertaking','terms':'equivalent'}[stage]}},digest(req)

    def test_local_support_precedes_scope_and_term_comparison(self):
        run,doc=fixture(CASES[0]);original=deepcopy((run,doc));calls=[]
        def decide(req):calls.append(req);return self.choose(req)
        result=rc.build(run,doc,decide)
        self.assertEqual((run,doc),original)
        self.assertEqual([r['state']['stage'] for r in calls],['requested_term_support','requested_term_scope','requested_term_terms'])
        self.assertEqual(calls[2]['state']['earlier_decisions']['scope']['request'],digest(calls[1]))
        self.assertNotIn('WITHHELD_FUTURE_RESULT',str(calls))
        self.assertEqual(result['counts']['terms'],{'equivalent':1})
        self.assertEqual(result['records'][0]['status'],'recorded_operation')

    def test_unsupported_or_different_work_is_retained_without_forcing_comparison(self):
        run,doc=fixture(CASES[0])
        for at,value,expected_calls in [('support','unsupported',1),('support','unresolved',1),('scope','different_undertaking',2),('scope','unresolved',2)]:
            calls=[]
            def decide(req):
                calls.append(req)
                return ({'choice':{'value':value}},digest(req)) if req['state']['stage']=='requested_term_'+at else self.choose(req)
            result=rc.build(run,doc,decide);self.assertEqual(len(calls),expected_calls)
            self.assertEqual(result['records'][1]['selections'][at]['value'],value)
            self.assertNotIn('terms',result['records'][1]['selections'])

    def test_record_chain_and_terminal_snapshot_must_reconcile(self):
        for mode in ['before','after','previous_hash','flat_ledger','terminal','partial','duplicate']:
            run,doc=fixture(CASES[0]);w=doc['requested_work']
            if mode=='before':w['steps'][1]['changes'][0]['before']['text']='altered'
            elif mode=='after':w['steps'][1]['state_after']=[]
            elif mode=='previous_hash':w['steps'][1]['previous_state_hash']='changed'
            elif mode=='flat_ledger':w['changes']=[]
            elif mode=='terminal':w['records']=[]
            elif mode=='partial':w['status']='needs_work'
            else:w['steps'].append(deepcopy(w['steps'][-1]))
            with self.assertRaises(InputError,msg=mode):rc.build(run,doc,lambda r:self.fail('Invalid chain reached Jev'))

    def test_before_version_cannot_be_supported_by_later_source(self):
        run,doc=fixture(CASES[0]);future=doc['units'][-1]['source']
        for r in [doc['requested_work']['steps'][0]['state_after'][0],doc['requested_work']['steps'][0]['changes'][0]['after']]:
            r['evidence']=[future]
        with self.assertRaises(InputError):rc.build(run,doc,self.choose)

    def test_attribution_source_and_trajectory_are_not_optional(self):
        for mode in ['actor','trajectory','source','copied']:
            run,doc=fixture(CASES[0])
            if mode=='actor':doc['units'][1]['actor']='agent'
            elif mode=='trajectory':doc['units'][1]['trajectory_id']='elsewhere'
            elif mode=='source':doc['units'][1]['source']['text']='fiction'
            else:
                run['events'][1]['copied_context']=True
                doc['source_hash']=doc['requested_work']['source_hash']=digest(run)
            with self.assertRaises(InputError,msg=mode):rc.build(run,doc,self.choose)

    def test_context_budget_retains_uninspected_status_not_a_semantic_negative(self):
        run,doc=fixture(CASES[0])
        with patch.object(rc,'MAX_CHARS',1):result=rc.build(run,doc,lambda r:self.fail('Over-budget request'))
        self.assertEqual(result['records'][1]['status'],'needs_context_selection')
        self.assertEqual(result['counts']['terms'],{})

    def test_reconciled_but_forged_version_identity_is_rejected(self):
        run,doc=fixture(CASES[0]);work=doc['requested_work']
        for record in [work['steps'][-1]['changes'][0]['after'],work['steps'][-1]['state_after'][0],
                       work['changes'][-1]['after'],work['records'][0]]:
            record['version_id']='rvforged'
        with self.assertRaisesRegex(InputError,'identity'):rc.build(run,doc,lambda r:self.fail('Forged version reached model'))

    def test_raw_argmax_replay_ignores_provider_choice_and_confidence(self):
        run,doc=fixture(CASES[0]);calls=[]
        def transport(req):
            calls.append(req);winner=self.choose(req)[0]['choice']['value'];options=req['questions']['choice']['criteria']
            return {'model':req['model'],'answers':{'choice':{'type':'choice','choice':'unresolved','confidence':0,
                    'probabilities':{k:.4 if k==winner else .6/(len(options)-1) for k in options}}}}
        with TemporaryDirectory() as directory:
            engine=Pipeline(directory,FileCandidates(directory),transport)
            result,audit=rc.execute(run,doc,engine);self.assertTrue(audit['raw_argmax_replayed'])
            rc.execute(run,doc,engine);self.assertEqual(len(calls),3)
            self.assertEqual(result['records'][1]['selections']['terms']['value'],'equivalent')
            key=result['records'][1]['requests']['terms'];path=Path(directory)/'decisions'/f'{key}.json'
            altered=read(path);altered['answers']['choice']['value']='mixed_change';write(path,altered)
            with self.assertRaises(InputError):rc.audit(run,doc,result,directory)

    def test_missing_option_and_mutated_source_are_rejected(self):
        run,doc=fixture(CASES[0])
        with self.assertRaises(InputError):rc.build(run,doc,lambda req:({'choice':{'value':'invented'}},digest(req)))
        run['events'][0]['text']+='new'
        with self.assertRaises(InputError):rc.build(run,doc,self.choose)

    def engine(self, directory):
        def transport(req):
            winner=self.choose(req)[0]['choice']['value']
            return {'model':req['model'],'answers':{'choice':{'type':'choice',
                'probabilities':{k:1 if k==winner else 0 for k in req['questions']['choice']['criteria']}}}}
        return Pipeline(directory,FileCandidates(directory),transport)

    def test_historical_versions_and_original_units_survive_database_roundtrip(self):
        from tracker import graph_store as gs
        from tracker.store import Store
        run,doc=fixture(CASES[0]);original=deepcopy(doc)
        with TemporaryDirectory() as directory:
            result,_=rc.execute(run,doc,self.engine(directory))
            graph=rc.export_graph(run,doc,result,directory)
            self.assertEqual(doc,original)
            self.assertEqual({n['id'] for n in graph['nodes'] if n['kind']=='unit'},
                             {u['id'] for u in doc['units']})
            versions=[n for n in graph['nodes'] if n['kind']=='requested_work_version']
            self.assertEqual(len(versions),2)
            edge=next(e for e in graph['edges'] if e['type']=='updates_requested_version')
            change=result['records'][1]
            self.assertEqual(edge['source'],'requested-version:'+change['after']['version_id'])
            self.assertEqual(edge['target'],'requested-version:'+change['before']['version_id'])
            self.assertEqual(edge['properties']['requests'],change['requests'])
            self.assertEqual(edge['properties']['cutoff'],change['source'])
            store=Store(Path(directory)/'test.sqlite');store.add([run])
            with store.connect() as c:gs.save(c,graph)
            restored=gs.read(store,graph['id'])
            restored['nodes'].sort(key=lambda n:n['id'])
            self.assertEqual(restored,graph)
            self.assertEqual(rc.export_graph(run,doc,result,directory),graph)
            broken=deepcopy(result);broken['records'][1]['selections']['terms']['value']='mixed_change'
            with self.assertRaises(InputError):rc.export_graph(run,doc,broken,directory)

    def test_legacy_protocol_can_replay_without_new_context_fields(self):
        run,doc=fixture(CASES[0])
        with TemporaryDirectory() as directory:
            engine=self.engine(directory)
            result=rc.build(run,doc,engine.decide,rc.LEGACY)
            self.assertNotIn('context_before',result['records'][1])
            self.assertTrue(rc.audit(run,doc,result,directory)['raw_argmax_replayed'])
            key=result['records'][1]['requests']['support']
            self.assertNotIn('coexpressed_records',read(Path(directory)/'decisions'/f'{key}.json')['request']['state'])

    def test_cli_replays_cached_decisions_without_transport_and_persists_graph(self):
        import contextlib
        import io
        from tracker import graph_store as gs
        from tracker.store import Store
        run,doc=fixture(CASES[0])
        with TemporaryDirectory() as directory:
            root=Path(directory);rc.execute(run,doc,self.engine(root))
            write(root/'input.json',{'run':run,'document':doc})
            store=Store(root/'test.sqlite');store.add([run])
            argv=['requested-changes','--input',str(root/'input.json'),'--workspace',str(root),'--db',str(root/'test.sqlite')]
            with patch('sys.argv',argv),patch('tracker.jev.JevClient') as client,contextlib.redirect_stdout(io.StringIO()):
                client.return_value.transport.side_effect=AssertionError('Unexpected model call')
                rc.main()
            receipt=read(next((root/'executions').glob('*.json')))
            self.assertEqual(receipt['status'],'complete');self.assertEqual(receipt['new_requests'],0)
            self.assertEqual(gs.read(store,receipt['graph_id'])['semantic_context']['requested_changes']['schema'],rc.VERSION)
