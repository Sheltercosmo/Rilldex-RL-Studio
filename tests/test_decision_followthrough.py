"""Window attribution controls; authored examples are not semantic accuracy gold."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tracker import decision_followthrough as df, work_hierarchy as wh, work_outline as wo
from test_work_hierarchy import graph, finish


def controls():
    g = graph()
    # Repeated dispatch cycle, with a second statement at record 4.
    for i, kind in enumerate(['message', 'action', 'feedback', 'message'], start=4):
        g['nodes'].append(dict(id='event:e'+str(i), kind='event', activity=None,
            trajectory_id='main', event_index=i, properties=dict(id='e'+str(i),
                actor='environment' if kind=='feedback' else 'agent', kind=kind, text='source '+str(i))))
    for old, new, index in [('action', 'action2', 5), ('feedback', 'feedback2', 6), ('review', 'review2', 7)]:
        n = deepcopy(next(n for n in g['nodes'] if n['id']==old))
        n.update(id=new, event_index=index)
        n['properties']['source'] = dict(event_id='e'+str(index), start=0, end=8, text='source '+str(index))
        g['nodes'].append(n)
    decisions = [dict(id='choose', type='pursue', event_index=0, evidence=dict(event_id='e0', start=0, end=8, text='source 0')),
                 dict(id='resume', type='resume', event_index=4, evidence=dict(event_id='e4', start=0, end=8, text='source 4'))]
    def row(a, f, r):
        return dict(action_id=a, roles=['attempts_plan_step'], memberships=[],
                    responses=[dict(node_id=f, link_ids=['response-'+f], assessments=[dict(node_id=r, link_id='assessment-'+r)])])
    execution = dict(scope='direct', binding_basis='reviewed_scopes', binding_ids=['binding'],
                     rows=[row('action','feedback','review'),row('action2','feedback2','review2')])
    outline = dict(cutoff_event_index=7, items=[dict(id='work', label='Work', decisions=decisions, execution_summary=execution)])
    return finish(g), outline


class DecisionFollowthroughTests(unittest.TestCase):
    def test_partition_and_exact_witnesses_without_changing_source(self):
        g, o = controls(); before = deepcopy(g); df.attach(g, o); windows = df.windows(o)
        self.assertEqual(g, before)
        self.assertEqual([w['counts']['actions'] for w in windows], [1, 1])
        self.assertEqual([w['counts']['with_assessment'] for w in windows], [1, 1])
        self.assertEqual(windows[0]['rows'][0]['responses'][0]['assessments'][0]['link_id'], 'assessment-review')
        self.assertEqual(windows[0]['window']['next_decision_ids'], ['resume'])
        self.assertEqual(windows[1]['window']['boundary'], 'observation_cutoff')
        again = deepcopy(o); df.attach(g, again); self.assertEqual(o, again)

    def test_later_feedback_and_assessment_do_not_leak_back(self):
        g, o = controls()
        row = o['items'][0]['execution_summary']['rows'][0]
        row['responses'][0]['assessments'][0]['node_id'] = 'review2'
        df.attach(g, o); first = df.windows(o)[0]
        self.assertEqual(first['counts']['with_feedback'], 1)
        self.assertEqual(first['counts']['with_assessment'], 0)
        row['responses'][0]['node_id'] = 'feedback2'
        df.attach(g, o); self.assertEqual(df.windows(o)[0]['counts']['with_feedback'], 0)

    def test_cutoff_progresses_without_calling_missing_feedback_failure(self):
        g, o = controls(); o['items'][0]['decisions'].pop()
        for cutoff, expected in [(0, (0,0,0)), (1,(1,0,0)), (2,(1,1,0)), (3,(1,1,1))]:
            current = deepcopy(o); current['cutoff_event_index'] = cutoff
            df.attach(g,current); w = df.windows(current)[0]
            self.assertEqual(tuple(w['counts'][k] for k in ['actions','with_feedback','with_assessment']), expected)
            self.assertNotIn('success',w); self.assertEqual(w['window']['boundary'],'observation_cutoff')

    def test_unmapped_conflicting_and_unordered_are_not_zero(self):
        for mode in ['unmapped','conflict','unordered']:
            g, o = controls()
            if mode=='unmapped': o['items'][0].pop('execution_summary')
            if mode=='conflict': o['items'][0]['decisions'].append(dict(o['items'][0]['decisions'][0],id='stop',type='stop'))
            if mode=='unordered': next(n for n in g['nodes'] if n['id']=='event:e0')['properties']['order_known']=False
            df.attach(g,o); w=df.windows(o)[0]
            self.assertIsNone(w['counts']); self.assertNotEqual(w['status'],'mapped')
            if mode=='conflict': self.assertEqual(len(df.windows(o)),2)

    def test_foreign_context_actor_and_ambiguous_same_record_excluded(self):
        for mode in ['context','actor','overlap','unknown_order']:
            g, o = controls(); event=next(n for n in g['nodes'] if n['id']=='event:e1')
            if mode=='context':event['properties']['context_id']='foreign'
            if mode=='actor':event['properties']['actor']='other'
            if mode=='unknown_order':event['properties']['order_known']=False
            if mode=='overlap':
                action=next(n for n in g['nodes'] if n['id']=='action');action['properties']['source']['event_id']='e0'
            df.attach(g,o);w=df.windows(o)[0]
            self.assertEqual(w['counts']['actions'],0)
            self.assertIn('action',w['unresolved']['actions'])

    def test_same_record_nonoverlap_uses_quote_offsets(self):
        g,o=controls(); event=next(n for n in g['nodes'] if n['id']=='event:e0');event['properties']['text']='source 0 then dispatch'
        action=next(n for n in g['nodes'] if n['id']=='action')
        action['properties']['source']=dict(event_id='e0',start=9,end=22,text='then dispatch')
        df.attach(g,o);self.assertEqual(df.windows(o)[0]['counts']['actions'],1)

    def test_real_saved_review_replay_keeps_unmapped_scopes_and_deduplicates(self):
        g=json.loads(Path('research/work-hierarchy-2026-10-13/software-evidence.json').read_text(encoding='utf-8'));g=g.get('graph',g)
        d=json.loads(Path('research/outline-bindings-2026-10-13/review.json').read_text(encoding='utf-8'))
        d['base_graph_id']=g['id'];derived=wo.fork(g,d);before=deepcopy(derived)
        h=wh.build(derived);w={x['label']:x for x in h['work_measures']['decision_windows']}
        self.assertEqual(len(w),6)
        self.assertEqual(w['Draft the report in Markdown']['counts']['attempts'],1)
        self.assertEqual(w['Convert the Markdown report to PDF']['counts']['attempts'],4)
        self.assertEqual(w['Implement the SVM regressor']['status'],'execution_unmapped')
        # The subsequent ls checks presence, not PDF correctness or task success.
        self.assertEqual(w['Produce a PDF report']['counts']['actions'],1)
        self.assertEqual(w['Produce a PDF report']['counts']['checks'],1)
        self.assertEqual(w['Produce a PDF report']['counts']['attempts'],0)
        self.assertEqual(derived,before)
        early=wh.build(derived,'e71')['work_measures']['decision_windows']
        self.assertEqual(next(x for x in early if x['label']=='Convert the Markdown report to PDF')['counts']['actions'],0)

    def test_plan_projection_excludes_cross_context_membership_feedback_and_review(self):
        for node, result in [('event:e1','action'),('event:e2','feedback'),('event:e3','assessment')]:
            g=graph();next(n for n in g['nodes'] if n['id']==node)['properties']['context_id']='foreign'
            h=wh.build(finish(g));row=h['stage_paths'][0]['rows']
            if result=='action':self.assertEqual(row,[])
            if result=='feedback':self.assertEqual(row[0]['responses'],[])
            if result=='assessment':self.assertEqual(row[0]['responses'][0]['assessments'],[])

    def test_plan_projection_rejects_feedback_before_dispatch(self):
        g=graph();next(n for n in g['nodes'] if n['id']=='feedback')['event_index']=0
        h=wh.build(finish(g));self.assertEqual(h['stage_paths'][0]['rows'][0]['responses'],[])


if __name__=='__main__':unittest.main()
