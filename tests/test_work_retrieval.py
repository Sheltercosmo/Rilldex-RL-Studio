from copy import deepcopy
import unittest

from tracker import work_retrieval as retrieval, contribution_work as cw, scope_membership, graph_store
from tracker.schema import InputError,digest
from test_contribution_work import source
from test_scope_membership import fixture as paired


class WorkRetrievalTests(unittest.TestCase):
    def test_old_matching_work_survives_recent_distractors(self):
        run,_,units=source(('Inspect the archival invoice for customer Horizon.',
            'Measure CPU temperatures.', 'Update the parser grammar.', 'Check memory allocations.',
            'Revisit the archival invoice for customer Horizon.'))
        original=deepcopy(units)
        with retrieval.WorkIndex(run,units) as index:
            found,report=index.select(units[-1]['id'],limit=2,recent=1)
        self.assertEqual({u['id'] for u in found},{units[0]['id'],units[-2]['id']})
        self.assertEqual(report['omitted_priors'],2)
        self.assertEqual(units,original)
        self.assertNotIn('same_work_target',report)

    def test_future_units_do_not_change_prefix_ranking_or_statistics(self):
        run,_,units=source(('Inspect cobalt ledger.','Inspect archive ledger.',
            'Revisit cobalt ledger.','Cobalt cobalt cobalt.'))
        with retrieval.WorkIndex(run,units[:3]) as left,retrieval.WorkIndex(run,units) as right:
            a=left.select(units[2]['id'],2,0)
            right.select(units[3]['id'],2,0)  # Then query backwards.
            b=right.select(units[2]['id'],2,0)
            self.assertEqual(a,b)

    def test_excluded_saved_pairs_free_slots_without_becoming_negatives(self):
        run,_,units=source(('Find cobalt ledger.','Check syntax.','Check parser.','Find cobalt ledger again.'))
        with retrieval.WorkIndex(run,units) as index:
            found,report=index.select(units[-1]['id'],2,1,[units[0]['id']])
            self.assertEqual({u['id'] for u in found},{units[1]['id'],units[2]['id']})
            self.assertEqual(report['already_observed_priors'],1)
            self.assertEqual(report['omitted_priors'],0)
            with self.assertRaises(InputError):index.select(units[0]['id'],exclude=[units[1]['id']])

    def test_scope_order_matches_selector_including_parallel_siblings(self):
        run,_,units=source(('Inspect cobalt ledger.','Inspect archive ledger.','Find cobalt ledger.'),tools=True)
        events={e['id']:e for e in run['events']}
        events[units[-1]['source']['event_id']]['context_id']='separate'
        with retrieval.WorkIndex(run,units) as index:
            for current in units:
                found,report=index.select(current['id'],limit=16)
                expected={p['id'] for p in units if cw.ordered_before(run,p,current)}
                self.assertEqual({p['id'] for p in found},expected)
                self.assertEqual(report['eligible_priors'],len(expected))
        # A declared shared action batch makes both calls ineligible predecessors.
        for u in units:
            u['kind']='action';events[u['source']['event_id']]['kind']='action'
            events[u['source']['event_id']]['parent_id']='same-batch'
            events[u['source']['event_id']].pop('context_id',None)
        with retrieval.WorkIndex(run,units) as index:
            self.assertEqual(index.select(units[-1]['id'])[1]['eligible_priors'],0)

    def test_empty_lexical_query_falls_back_to_recent_without_deciding_identity(self):
        run,_,units=source(('Inspect cobalt.','Inspect invoice.','This is it.'))
        with retrieval.WorkIndex(run,units) as index:
            found,report=index.select(units[-1]['id'],1,0)
        self.assertEqual(found[0]['id'],units[-2]['id'])
        self.assertEqual(report['selected'][0]['method'],'recent_fallback')

    def test_missing_only_preparation_preserves_unresolved_choices_and_grouping(self):
        run,graph,units=paired({(1,0):'unresolved'},count=4)
        before=deepcopy(graph);groups=scope_membership.derive(run,graph)
        out=retrieval.prepare(run,graph,limit=1,recent=1)
        self.assertEqual(out['counts']['already_observed_pairs'],1)
        self.assertEqual(out['counts']['selected_pairs'],2)
        self.assertEqual(out['counts']['omitted_pairs'],3)
        self.assertEqual(out['provider_calls'],0)
        self.assertEqual(graph,before)
        self.assertEqual(scope_membership.derive(run,graph),groups)
        for request in out['requests']:
            self.assertNotEqual((request['current']['id'],request['priors'][0]['id']),(units[1]['id'],units[0]['id']))

    def test_invalid_source_or_budget_fails_before_retrieval(self):
        run,graph,units=source()
        with retrieval.WorkIndex(run,units) as index:
            for limit,recent in [(0,0),(17,2),(2,3),(True,0),(2,-1)]:
                with self.assertRaises(InputError):index.select(units[-1]['id'],limit,recent)
        changed=deepcopy(run);changed['metadata']['different']=True
        with self.assertRaises(InputError):retrieval.prepare(changed,graph)
        units[0]['source']['text']='Invented'
        with self.assertRaises(InputError):retrieval.WorkIndex(run,units)

    def test_request_and_byte_limits_defer_work_without_dropping_coverage(self):
        run,graph,_=source(tuple('Work '+str(i) for i in range(8)))
        for kwargs in [dict(max_requests=1),dict(max_bytes=0)]:
            out=retrieval.prepare(run,graph,limit=3,**kwargs)
            counts=out['counts']
            self.assertGreater(counts['deferred_pairs'],0)
            self.assertEqual(counts['selected_pairs'],counts['prepared_pairs']+counts['deferred_pairs']+counts['unavailable_pairs'])
            self.assertEqual(counts['eligible_pairs'],counts['selected_pairs']+counts['already_observed_pairs']+counts['omitted_pairs'])
            if 'max_requests' in kwargs:self.assertEqual(counts['requests'],1)
            else:self.assertEqual(counts['request_bytes'],0)

    def test_unreadable_prior_does_not_block_the_other_comparisons(self):
        run,_,units=source(('Read the target.','Hello there.','Revisit the target.'))
        units[1]['content']['work_target']={'text':'Not expressed','status':'not_expressed','evidence':[]}
        graph=graph_store.build(run,{'observer':{'id':'control','label':'Target availability'},
            'document':{'source_hash':digest(run),'schema':'semantic-unit-map/1','units':units,'relations':[]}})
        out=retrieval.prepare(run,graph,limit=3,recent=1)
        self.assertEqual(out['counts']['prepared_pairs'],1)
        self.assertEqual(out['counts']['unavailable_pairs'],2)
        self.assertEqual(out['requests'][0]['current']['id'],units[-1]['id'])
        self.assertEqual(out['requests'][0]['priors'][0]['id'],units[0]['id'])

    def test_unit_filter_limits_queries_without_hiding_their_history(self):
        run,graph,units=source()
        out=retrieval.prepare(run,graph,unit_ids=[units[-1]['id']])
        self.assertEqual(len(out['searches']),1)
        self.assertEqual(out['counts']['eligible_pairs'],2)
        self.assertEqual(out['requests'][0]['current']['id'],units[-1]['id'])
        for ids in [['unknown'],[units[0]['id'],units[0]['id']]]:
            with self.assertRaises(InputError):retrieval.prepare(run,graph,unit_ids=ids)


if __name__=='__main__':unittest.main()
