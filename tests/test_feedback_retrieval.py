import copy
import unittest

from tracker.adapters import normalize
from tracker.semantic_map import evidence
from tracker.schema import digest
from tracker.feedback_retrieval import FeedbackIndex,VERSION,HYBRID_VERSION,CONTEXT_VERSION,terms,chunks
from tracker.feedback_assessments import linked_feedback,candidates,build,INLINE_EVIDENCE,DIRECT_SET_RULE,SOURCE_LINKAGE


def example(pairs,situation):
    rows=[{'step':i,'user_message':'Inspect the recorded workflow.' if i==0 else None,
           'agent':{'thought':None,'action':action},'environment':response} for i,(action,response) in enumerate(pairs)]
    rows.append({'step':len(rows),'user_message':None,'agent':{'thought':situation,'action':None},'environment':None})
    run=normalize({'trajectory_format':'devai/1','trajectory':rows})[0];units=[]
    for event in run['events']:
        if event['kind'] not in {'action','reasoning'}:continue
        ref=evidence(run,event['id']);field={'status':'expressed','text':ref['text'],'evidence':[ref]}
        units.append({'id':'unit-'+digest(ref)[:20],'source':ref,'actor':event['actor'],'trajectory_id':event['trajectory_id'],
                      'kind':'action' if event['kind']=='action' else 'semantic','status':'selected',
                      'activity':'construct' if event['kind']=='action' else 'orient',
                      'content':{'summary':field,**({'situation':field} if event['kind']=='reasoning' else {})}})
    return run,{'run_id':run['id'],'units':units,'status':'complete_local_extraction','whole_run':True}


class FeedbackRetrievalTests(unittest.TestCase):
    def test_context_protocol_excludes_other_sessions_before_lexical_ranking(self):
        run,ex=example([('Read local status.','Status: ready.')]+[(f'Read foreign status {i}.','Status: failed.') for i in range(15)],'The status is ready.')
        for e in run['events']:
            e['context_id']='local' if e['index']<=3 or e['kind']=='reasoning' else 'foreign'
        records=linked_feedback(run,ex,SOURCE_LINKAGE);u=ex['units'][-1];cutoff=run['events'][-1]['index']
        with FeedbackIndex(records,run['events']) as index:
            chosen,report=index.select(u,cutoff,version=CONTEXT_VERSION)
            legacy=index.select(u,cutoff,version=HYBRID_VERSION)
            self.assertEqual(index.select(u,cutoff,version=CONTEXT_VERSION),(chosen,report))
        self.assertEqual([r['event']['id'] for r in chosen],['e3'])
        self.assertEqual(report['eligible_prior_responses'],1)
        self.assertTrue(any(r['event']['context_id']=='foreign' for r in legacy[0]))
        with FeedbackIndex(records[:1],run['events']) as index:
            self.assertEqual(index.select(u,cutoff,version=CONTEXT_VERSION),(chosen,report))
        seen=[]
        build(run,ex,lambda req:(seen.append(req) or 'f0',digest(req)),evidence_layout=INLINE_EVIDENCE,
              reference_rule=DIRECT_SET_RULE,linkage_version=SOURCE_LINKAGE,retrieval_version=CONTEXT_VERSION)
        self.assertEqual([c['feedback_event_id'] for c in seen[0]['state']['feedback_candidates']],['e3'])
        source={e['id']:e for e in run['events']}
        self.assertTrue(all(source[e['id']]['context_id']=='local' for e in seen[0]['state']['prefix']))

    def test_new_context_protocol_preserves_prefixes_and_exposes_only_prior_invalid_sources(self):
        from tracker.schema import InputError
        run,ex=example([('Read status.','Status: ready.')],'The status is ready.');u=ex['units'][-1];cutoff=run['events'][-1]['index']
        records=linked_feedback(run,ex,SOURCE_LINKAGE)
        with FeedbackIndex(records,run['events']) as index:
            expected=index.select(u,cutoff,version=CONTEXT_VERSION)
            with self.assertRaises(InputError):index.select(u,cutoff+1,version=CONTEXT_VERSION)
        future=copy.deepcopy(records[0]);future['event'].update(id='future',index=999,copied_context=True)
        with FeedbackIndex([*records,future],run['events']) as index:
            self.assertEqual(index.select(u,cutoff,version=CONTEXT_VERSION),expected)
        records[0]['event']['order_known']=False
        with FeedbackIndex(records,run['events']) as index:
            selected,report=index.select(u,cutoff,version=CONTEXT_VERSION)
        self.assertEqual(selected,[]);self.assertEqual(report['excluded_source_event_ids'],['e3'])
        with FeedbackIndex(records) as index:
            with self.assertRaises(InputError):index.select(u,cutoff,version=CONTEXT_VERSION)

    def test_hybrid_preserves_recent_pool_and_adds_bounded_older_hits(self):
        run,ex=example([('Read north pressure.','North pressure: 10 kPa.'),('Read south pressure.','South pressure: 20 kPa.')]+
                       [(f'Read invoice {i}.','Invoice is paid.') for i in range(12)],
                       'The north and south pressure readings differ by 10 kPa.')
        unit=ex['units'][-1];old,_=candidates(run,ex,unit,SOURCE_LINKAGE)
        with FeedbackIndex(linked_feedback(run,ex,SOURCE_LINKAGE)) as index:
            selected,report=index.select(unit,run['events'][-1]['index'],version=HYBRID_VERSION)
        ids={r['event']['id'] for r in selected}
        self.assertTrue({r['event']['id'] for r in old}|{'e3','e5'}<=ids)
        self.assertEqual(len(selected),5);self.assertEqual(report['candidate_limit'],5)
        self.assertEqual(sum(r['method']=='retained_recent' for r in report['selected']),3)
        seen=[]
        result=build(run,ex,lambda req:(seen.append(req) or 'none_of_these',digest(req)),
                     evidence_layout=INLINE_EVIDENCE,reference_rule=DIRECT_SET_RULE,linkage_version=SOURCE_LINKAGE,retrieval_version=HYBRID_VERSION)
        self.assertEqual(seen[0]['state']['retrieval_scope']['limit'],5)
        self.assertEqual(len(seen[0]['questions']['choice']['criteria']),33)
        self.assertEqual(result['observations'][0]['status'],'none_of_these')

    def test_distant_result_is_retrieved_with_bounded_candidates_and_no_model(self):
        run,ex=example([('Check connectivity.','Connection refused.')]+[(f'Read item {i}.',f'Item {i} is blue.') for i in range(40)],
                       'The initial connectivity check returned connection refused.')
        unit=ex['units'][-1];records=linked_feedback(run,ex,SOURCE_LINKAGE)
        self.assertNotIn('e3',[r['event']['id'] for r in candidates(run,ex,unit,SOURCE_LINKAGE)[0]])
        with FeedbackIndex(records) as index:
            selected,report=index.select(unit,run['events'][-1]['index'])
        self.assertIn('e3',[r['event']['id'] for r in selected]);self.assertEqual(len(selected),3)
        self.assertEqual(report['eligible_prior_responses'],41);self.assertEqual(report['omitted_responses'],38)

    def test_future_statistics_other_actors_and_rewind_cannot_change_a_prefix(self):
        run,ex=example([('Read engine state.','Engine temperature high.'),('Read battery state.','Battery temperature low.'),('Read room state.','Room temperature normal.')],
                       'Engine temperature is high.')
        records=linked_feedback(run,ex,SOURCE_LINKAGE);unit=ex['units'][-1]
        early_cutoff=records[1]['event']['index']
        with FeedbackIndex(records[:1]) as base:expected=base.select(unit,early_cutoff)
        changed=copy.deepcopy(records)
        changed[-1]['event']['text']='Engine temperature high. '*100
        hidden=copy.deepcopy(changed[-1]);hidden['action']['actor']='another-agent';changed.append(hidden)
        with FeedbackIndex(changed) as index:
            self.assertEqual(index.select(unit,early_cutoff),expected)
            index.select(unit,run['events'][-1]['index'])
            self.assertEqual(index.select(unit,early_cutoff),expected)

    def test_matching_middle_passage_reaches_actual_request_and_exact_source_evidence(self):
        text='Progress tick.\n'*1300+'CRITICAL quartz checksum mismatch at shard 9.\n'+'Progress tick.\n'*1300
        run,ex=example([('Inspect execution log.',text)]+[(f'List directory {i}.','Directory is empty.') for i in range(5)],
                       'The quartz checksum mismatch was reported for shard 9.')
        seen=[]
        def choose(req):
            seen.append(req);choice=next(c['id'] for c in req['state']['feedback_candidates'] if c['feedback_event_id']=='e3')
            return choice,digest(req)
        result=build(run,ex,choose,evidence_layout=INLINE_EVIDENCE,reference_rule=DIRECT_SET_RULE,linkage_version=SOURCE_LINKAGE,retrieval_version=VERSION)
        self.assertEqual(len(result['relations']),1)
        self.assertIn('CRITICAL quartz checksum mismatch',str(seen[0]['questions']))
        edge=result['relations'][0]
        self.assertTrue(any('CRITICAL quartz checksum mismatch' in r['text'] for r in edge['context_evidence']))
        original=next(e['text'] for e in run['events'] if e['id']=='e3')
        self.assertTrue(all(original[r['start']:r['end']]==r['text'] for r in edge['context_evidence']))
        self.assertTrue(edge['omitted_feedback_ranges'])
        self.assertLess(sum(len(r['text']) for r in edge['context_evidence']),6000)

    def test_media_and_query_syntax_are_not_search_instructions(self):
        text='Before data:image/png;base64,SECRETNEEDLE After'
        self.assertNotIn('SECRETNEEDLE',''.join(c[2] for c in chunks(text)))
        self.assertTrue(all('"' not in t and '*' not in t for t in terms('" OR NEAR(*); DROP TABLE evidence; --')))
        run,ex=example([('Look at the picture.',text)],'SECRETNEEDLE')
        with FeedbackIndex(linked_feedback(run,ex,SOURCE_LINKAGE)) as index:
            selected,report=index.select(ex['units'][-1],run['events'][-1]['index'])
        self.assertEqual(report['lexically_matched_responses'],0)
        self.assertEqual(report['selected'][0]['method'],'recent_fallback')
        self.assertNotIn('retrieval_ranges',selected[0])

    def test_joint_old_targets_remain_distinct_from_intervening_work(self):
        pairs=[('Read north pressure.','North pressure: 10 kPa.'),('Read south pressure.','South pressure: 20 kPa.')]
        pairs += [(f'Read invoice {i}.',f'Invoice {i}: paid.') for i in range(8)]
        run,ex=example(pairs,'The north and south pressure readings differ by 10 kPa.')
        with FeedbackIndex(linked_feedback(run,ex,SOURCE_LINKAGE)) as index:
            selected,_=index.select(ex['units'][-1],run['events'][-1]['index'])
        self.assertTrue({'e3','e5'}<={r['event']['id'] for r in selected})


if __name__=='__main__':unittest.main()
