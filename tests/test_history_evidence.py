from copy import deepcopy
from unittest import TestCase
from tracker import history_evidence as he
from tracker.schema import InputError,dumps


def query(quantifier='all'):
    return {'schema':he.VERSION,'name':'Selected IDs have recorded approval','target':{'tools':['use'],'values':'/ids/*'},
            'history':{'tools':['lookup'],'bindings':[{'target':'/account','history':'/account'}],
                       'result_bindings':[{'target':'/account','result':'/account'}]},
            'rows':'/items/*','key':'/id','checks':[{'pointer':'/approved','equals':True}],
            'quantifier':quantifier,'invalidate_on':['revoke']}


def source(steps):
    events=[]
    for tool,args,result in steps:
        eid='e'+str(len(events)+1)
        events.append({'id':eid,'index':len(events),'actor':'agent','kind':'action','trajectory_id':'main',
            'text':tool+'('+dumps(args)+')','source_pointer':'/steps/'+str(len(events)),'arguments':args,
            'arguments_available':True,'tool':tool,'call_id':eid,'parent_id':None,'copied_context':False})
        if result is not None:
            events.append({'id':'e'+str(len(events)+1),'index':len(events),'actor':'environment','kind':'feedback',
                'trajectory_id':'main','source_call_id':eid,'text':result if isinstance(result,str) else dumps(result),
                'source_pointer':'/steps/'+str(len(events)),'copied_context':False})
    return {'id':'test-run','adapter_version':'authored-history-fixture/1','metadata':{},'events':events}


def body(approved=True,account='A'):
    return {'account':account,'items':{'x':{'id':'x','approved':approved}}}


class HistoryEvidenceTests(TestCase):
    def evaluate(self,steps,spec=None):return he.evaluate(source(steps),spec or query())

    def test_multi_record_witness_has_arguments_lookup_reply_and_attribute(self):
        out=self.evaluate([('lookup',{'account':'A'},body()),('use',{'account':'A','ids':['x']},None)])
        row=out['observations'][0]
        self.assertIs(row['value'],True);self.assertEqual(row['history_action_id'],'e1');self.assertEqual(row['result_event_id'],'e2')
        self.assertEqual({f['event_id'] for f in row['facts']},{'e1','e2','e3'})
        self.assertEqual(row['action_result_link']['feedback_id'],'e2')
        self.assertEqual({e['type'] for e in row['witness_edges']},{'same_recorded_json_value','attribute_in_same_returned_record','same_recorded_scope_value'})

    def test_latest_returned_state_replaces_prior_approval(self):
        out=self.evaluate([('lookup',{'account':'A'},body(True)),('lookup',{'account':'A'},body(False)),('use',{'account':'A','ids':['x']},None)])
        row=out['observations'][0];self.assertIs(row['value'],False)
        self.assertEqual(row['history_action_id'],'e3');self.assertEqual(row['superseded_history_action_ids'],['e1'])
        self.assertEqual(out['metrics'],{'opportunities':1,'denominator':1,'numerator':0,'unknown':0,'value':0.0})

    def test_later_lookup_never_repairs_earlier_missing_evidence(self):
        out=self.evaluate([('use',{'account':'A','ids':['x']},None),('lookup',{'account':'A'},body())])
        self.assertIsNone(out['observations'][0]['value']);self.assertEqual(out['metrics']['unknown'],1)
        self.assertEqual(out['metrics']['denominator'],0);self.assertIsNone(out['metrics']['value'])

    def test_newer_failed_or_pending_lookup_does_not_fall_back_to_old_approval(self):
        for result in [None,{'error':'not available'}]:
            out=self.evaluate([('lookup',{'account':'A'},body()),('lookup',{'account':'A'},result),('use',{'account':'A','ids':['x']},None)])
            self.assertIsNone(out['observations'][0]['value'])
            self.assertEqual(out['observations'][0]['history_action_id'],'e3')

    def test_account_scope_and_returned_scope_both_must_match(self):
        for account,result in [('B',body(account='B')),('A',body(account='B'))]:
            out=self.evaluate([('lookup',{'account':account},result),('use',{'account':'A','ids':['x']},None)])
            self.assertIsNone(out['observations'][0]['value'])

    def test_unknown_later_scope_cannot_reuse_older_matching_lookup(self):
        out=self.evaluate([('lookup',{'account':'A'},body()),('lookup',{},body()),('use',{'account':'A','ids':['x']},None)])
        self.assertEqual(out['observations'][0]['reason'],'latest_lookup_scope_unknown')

    def test_configured_invalidation_is_unknown_not_proof_of_failed_requirement(self):
        out=self.evaluate([('lookup',{'account':'A'},body()),('revoke',{'account':'A'},{}),('use',{'account':'A','ids':['x']},None)])
        row=out['observations'][0];self.assertIsNone(row['value']);self.assertEqual(row['invalidating_action_ids'],['e3'])
        self.assertEqual(row['reason'],'lookup_invalidated_before_dispatch')

    def test_any_all_and_missing_fields_use_three_valued_logic(self):
        data={'account':'A','items':{'x':{'id':'x','approved':True},'y':{'id':'y'}}}
        steps=[('lookup',{'account':'A'},data),('use',{'account':'A','ids':['x','y']},None)]
        self.assertIs(self.evaluate(steps,query('any'))['observations'][0]['value'],True)
        self.assertIsNone(self.evaluate(steps)['observations'][0]['value'])
        data['items']['x']['approved']=False
        self.assertIs(self.evaluate(steps)['observations'][0]['value'],False)
        self.assertIsNone(self.evaluate(steps,query('any'))['observations'][0]['value'])

    def test_native_argument_missingness_does_not_parse_prose_as_a_replacement(self):
        run=source([('lookup',{'account':'A'},body()),('use',{'account':'A','ids':['x']},None)])
        run['events'][-1]['arguments_available']=False
        self.assertEqual(he.evaluate(run,query())['observations'][0]['reason'],'native_arguments_unavailable')

    def test_duplicate_identity_and_duplicate_json_keys_are_unknown(self):
        for result in [{'account':'A','items':[{'id':'x','approved':True},{'id':'x','approved':False}]},
                       '{"account":"A","items":{"x":{"id":"x","approved":true,"approved":false}}}']:
            out=self.evaluate([('lookup',{'account':'A'},result),('use',{'account':'A','ids':['x']},None)])
            self.assertIsNone(out['observations'][0]['value'])

    def test_no_cross_trajectory_or_copied_feedback(self):
        for field,value in [('trajectory_id','other'),('copied_context',True),('agent_visibility','not_established')]:
            run=source([('lookup',{'account':'A'},body()),('use',{'account':'A','ids':['x']},None)])
            run['events'][1][field]=value
            self.assertIsNone(he.evaluate(run,query())['observations'][0]['value'])

    def test_concurrent_order_is_not_guessed(self):
        run=source([('lookup',{'account':'A'},body()),('use',{'account':'A','ids':['x']},None)])
        run['events'][0]['batch_size']=2
        self.assertEqual(he.evaluate(run,query())['observations'][0]['reason'],'history_order_ambiguous')

    def test_json_pointer_escaping_and_typed_values(self):
        self.assertEqual(he.select({'a/b':{'~name':[9]}},'/a~1b/~0name/0'),([{'pointer':'/a~1b/~0name/0','value':9}],True))
        self.assertFalse(he.eq(True,1));self.assertFalse(he.eq('1',1))
        with self.assertRaises(InputError):he.tokens('/a~2')

    def test_query_definition_changes_identity_without_mutating_source(self):
        run=source([('lookup',{'account':'A'},body()),('use',{'account':'A','ids':['x']},None)]);old=deepcopy(run)
        q=query();a=he.evaluate(run,q);q['checks'][0]['equals']=False;b=he.evaluate(run,q)
        self.assertNotEqual(a['id'],b['id']);self.assertEqual(run,old)
        q['history']['bindings']=[]
        with self.assertRaises(InputError):he.evaluate(run,q)


class HistoryEvidencePlanTests(TestCase):
    def setUp(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from tracker.store import Store
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db.sqlite')
        self.run=source([('lookup',{'account':'A'},body()),('use',{'account':'A','ids':['x']},None)])
        with self.store.connect() as c:c.execute('INSERT INTO runs VALUES (?,?,?,?)',(self.run['id'],'test',dumps(self.run),'{}'))

    def plan(self):
        from tracker import investigation_plans as ip
        from tracker.schema import digest
        return {'schema':ip.VERSION,'nodes':[{'name':'evidence','op':'history_evidence','inputs':[],
                'params':{'run_id':self.run['id'],'source_hash':digest(self.run),'query':query()}}]}

    def test_cached_query_persists_full_evidence_graph(self):
        from tracker import investigation_plans as ip,graph_store as gs
        first=ip.execute(self.store,self.plan());second=ip.execute(self.store,self.plan())
        self.assertEqual(first['outputs'],second['outputs']);self.assertEqual(second['execution']['cache_hits'],1)
        result=second['outputs']['evidence'];g=gs.read(self.store,result['graph_id']);gs.validate(g)
        self.assertEqual(len([n for n in g['nodes'] if n['kind']=='event']),len(self.run['events']))
        self.assertTrue(any(e['type']=='attribute_in_same_returned_record' for e in g['edges']))
        self.assertEqual(ip.read_output(self.store,result['id']),result)
        with self.store.connect() as c:
            self.assertGreater(c.execute('SELECT count(*) FROM graph_edges WHERE graph_id=? AND type=?',(g['id'],'same_recorded_json_value')).fetchone()[0],0)

    def test_changed_query_has_its_own_cache_and_graph(self):
        from tracker import investigation_plans as ip
        p=self.plan();first=ip.execute(self.store,p);p['nodes'][0]['params']['query']['checks'][0]['equals']=False
        second=ip.execute(self.store,p)
        self.assertEqual(second['execution']['computed'],1);self.assertNotEqual(first['outputs']['evidence']['graph_id'],second['outputs']['evidence']['graph_id'])
        self.assertEqual(second['outputs']['evidence']['metrics']['value'],0)

    def test_source_binding_is_checked_even_when_cache_exists(self):
        from tracker import investigation_plans as ip
        p=self.plan();ip.execute(self.store,p);changed=deepcopy(self.run);changed['events'][1]['text']=dumps(body(False))
        with self.store.connect() as c:c.execute('UPDATE runs SET document=? WHERE id=?',(dumps(changed),changed['id']))
        with self.assertRaisesRegex(InputError,'source binding mismatch'):ip.execute(self.store,p)

    def test_forged_result_cannot_be_materialized(self):
        result=he.evaluate(self.run,query());result['observations'][0]['value']=False
        with self.assertRaisesRegex(InputError,'source replay'):he.graph(self.run,result)

    def test_batch_command_keeps_each_rollout_and_unknown_denominator_separate(self):
        from tracker import history_query
        missing=deepcopy(self.run);missing['id']='missing-source';missing['events'][-1]['arguments_available']=False
        with self.store.connect() as c:c.execute('INSERT INTO runs VALUES (?,?,?,?)',(missing['id'],'test',dumps(missing),'{}'))
        out=history_query.execute(self.store,query(),[self.run['id'],missing['id']])
        self.assertEqual([r['run_id'] for r in out['rollouts']],[self.run['id'],missing['id']])
        self.assertEqual(out['rollouts'][0]['result']['metrics']['value'],1)
        self.assertIsNone(out['rollouts'][1]['result']['metrics']['value'])
        self.assertEqual(out['rollouts'][1]['result']['metrics']['unknown'],1)
        with self.assertRaisesRegex(InputError,'distinct'):history_query.execute(self.store,query(),[self.run['id']]*2)
