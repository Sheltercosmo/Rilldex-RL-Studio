from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import diagnostic_monitors as m
from tracker.adapters import normalize
from tracker.schema import digest,InputError
from tracker.semantic_extraction import read,write
from tracker.store import Store
from tracker.rollout_metrics import report,training_series


def source(**kw):
    return {'schema':'diagnostic-input/1','id':'r','task':'Fix issue','trace':'[agent dispatch] inspect code',
            'complete_recorded_text':True,'action_coverage':'recorded',**kw}


def transport(req):
    return {'model':req['model'],'answers':{k:{'type':'choice','choice':'ignored','confidence':0,
        'probabilities':{opt:(.4 if opt=='not_observed' else .2) for opt in q['criteria']}}
        for k,q in req['questions'].items()}}


class DiagnosticTests(unittest.TestCase):
    def test_raw_maximum_replay_and_tamper_rejection(self):
        with TemporaryDirectory() as d:
            s=source();r=m.execute(s,d,transport)
            self.assertTrue(m.audit(s,r,d)['exact_replay'])
            self.assertTrue(m.audit(read(Path(d)/'input.json'),read(Path(d)/'result.json'),d)['exact_replay'])
            self.assertTrue(all(x['value']==0 for x in r['metrics'].values()))
            self.assertEqual(m.execute(s,d,lambda _:self.fail('Should replay')),r)
            p=next((Path(d)/'decisions').glob('*.json'));saved=read(p)
            saved['answers']['online_reference_search']['value']='observed';write(p,saved)
            with self.assertRaises(InputError):m.audit(s,r,d)

    def test_incomplete_negatives_unavailable_and_positive_requires_anchor(self):
        def choose(req):return {k:{'value':'not_observed'} for k in req['questions']},digest(req)
        r=m.build(source(complete_recorded_text=False),choose)
        self.assertTrue(all(x['value'] is None for x in r['metrics'].values()))
        def positive(req):
            return {k:{'value':('none' if req['state'].get('stage') else 'observed')} for k in req['questions']},digest(req)
        r=m.build(source(),positive)
        self.assertTrue(all(x['selection']=='observed' and x['value'] is None for x in r['metrics'].values()))

    def test_unknown_is_not_zero_and_duplicate_or_mixed_versions_not_pooled(self):
        def choose(req):return {k:{'value':'unresolved'} for k in req['questions']},digest(req)
        r=m.build(source(),choose);a=m.summarize([r])['online_reference_search']
        self.assertEqual((a['unknown'],a['decidable'],a['incidence']),(1,0,None))
        with self.assertRaises(InputError):m.summarize([r,r])
        revision=deepcopy(r);revision['input_hash']='revised-snapshot'
        with self.assertRaises(InputError):m.summarize([r,revision])
        another=deepcopy(r);another['rollout_id']='x';another['protocol']['id']='v2'
        with self.assertRaises(InputError):m.summarize([r,another])

    def test_no_labels_or_silent_clipping(self):
        with self.assertRaises(InputError):m.request(source(expected='CHEATING'))
        with self.assertRaises(InputError):m.request(source(trace='x'*(m.MAX_CHARS+1)))
        s=source(trace='a'*5001);req=m.request(s)
        self.assertEqual(''.join(b['text'] for b in req['state']['recorded_trace_blocks']),s['trace'])
        self.assertNotIn('provenance',req['state'])

    def test_registration_and_training_are_source_bound(self):
        run=normalize({'trajectory_format':'devai/1','trajectory':[{'step':0,'agent':{'thought':'Read code','action':'cat file'},'environment':'code'}]})[0]
        run['metadata'].update(experiment='test',training_step=5)
        with TemporaryDirectory() as d:
            store=Store(Path(d)/'db');store.add([run]);s=m.from_run(run)
            result=m.execute(s,Path(d)/'pass',transport);registered=m.register(store,run,s,result,Path(d)/'pass')
            rpt=report(store);rows=[r for r in rpt['rows'] if r['observation_kind']=='diagnostics']
            self.assertEqual(len(rows),1)
            series=training_series(rpt,'diagnostic_online_reference_search',observer=registered['observer'])
            self.assertEqual(series['cohorts'][0]['points'][0]['value'],0)
            self.assertEqual(series['cohorts'][0]['bins'][0]['mean'],0)
            unknown=deepcopy(rpt);row=next(r for r in unknown['rows'] if r['observation_kind']=='diagnostics')
            row['metrics']['diagnostic_online_reference_search']['value']=None
            series=training_series(unknown,'diagnostic_online_reference_search',observer=registered['observer'])
            self.assertEqual(series['cohorts'],[])
            self.assertEqual(series['unknown_bins'][0]['unknown'],1)
            self.assertEqual(series['unknown_bins'][0]['start'],5)
            changed=deepcopy(run);changed['events'][0]['text']='different'
            with self.assertRaises(InputError):m.register(store,changed,s,result,Path(d)/'pass')


if __name__=='__main__':unittest.main()
