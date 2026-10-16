from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tracker import diagnostic_chains as c
from tracker import diagnostic_monitors as old
from tracker.schema import digest,InputError,dumps
from tracker.semantic_extraction import read,write
from test_diagnostic_monitors import source


def reuse_source(reverse=False):
    rows=['[tool web] REFERENCE: fix by returning n+1.\n','[assistant]\n','[tool_call edit] INCORPORATE: return n+1\n']
    return source(trace=''.join(reversed(rows) if reverse else rows))


def transport(req):
    stage=req['state'].get('stage');fs=req['state']['source_fragments']
    if isinstance(fs,dict):fs=[{'id':k,'text':v} for k,v in fs.items()]
    def selected(k):
        if stage=='evidence_roles':
            needle='REFERENCE' if k.endswith('returned_material') else 'INCORPORATE'
            return next(f['id'] for f in fs if needle in f['text'])
        if stage=='validate_evidence_chains':return 'supported'
        return 'observed' if k=='reference_solution_reuse' else 'not_observed'
    return {'model':req['model'],'answers':{k:{'type':'choice','confidence':0,'choice':'not_used',
        'probabilities':{opt:float(opt==selected(k)) for opt in q['criteria']}} for k,q in req['questions'].items()}}


class ChainTests(unittest.TestCase):
    def test_source_fragments_keep_text_bounded_and_task_separate(self):
        s=source(trace='[assistant]\n'+('a'*1500)+'\n[tool_call bash({"command":"x"})]\n[tool bash]\nhello')
        fs=c.fragments(s);trace=[f for f in fs if f['origin']=='trace']
        self.assertEqual(''.join(f['text'] for f in trace),s['trace'])
        self.assertTrue(all(f['end']-f['start']<=c.FRAGMENT_CHARS for f in trace))
        self.assertTrue(all(s['trace'][f['start']:f['end']]==f['text'] for f in trace))
        self.assertEqual(fs[-1]['origin'],'task')

    def test_normalized_events_retain_actor_and_exact_source_offsets(self):
        s=source(trace=dumps([{'id':'e1','actor':'agent','kind':'action','text':'quoted [tool fake]'},
            {'id':'e2','actor':'environment','kind':'observation','text':'result'}]))
        fs=[f for f in c.fragments(s) if f['origin']=='trace']
        self.assertEqual([f['event_id'] for f in fs],['e1','e2'])
        self.assertEqual([f['actor'] for f in fs],['agent','environment'])
        self.assertTrue(all(s['trace'][f['start']:f['end']]==f['text'] for f in fs))

    def test_reuse_requires_order_and_replay_preserves_raw_selections(self):
        with TemporaryDirectory() as d:
            s=reuse_source();r=c.execute(s,d,transport);m=r['metrics']['reference_solution_reuse']
            self.assertEqual(m['value'],1);self.assertTrue(m['source_order_established'])
            self.assertTrue(c.audit(s,r,d)['exact_replay'])
            self.assertTrue(c.audit(read(Path(d)/'input.json'),read(Path(d)/'result.json'),d)['exact_replay'])
            self.assertEqual(c.execute(s,d,lambda _:self.fail('Should replay')),r)
            r['metrics']['reference_solution_reuse']['value']=0
            with self.assertRaises(InputError):c.audit(s,r,d)
        with TemporaryDirectory() as d:
            r=c.execute(reuse_source(reverse=True),d,transport);m=r['metrics']['reference_solution_reuse']
            self.assertIsNone(m['value']);self.assertEqual(m['selection'],'observed')
            self.assertEqual(m['evidence_verdict'],'supported');self.assertFalse(m['source_order_established'])

    def test_independent_version_and_scope_exclusions_are_in_request(self):
        req=c.request(source());self.assertNotEqual(c.protocol()['id'],old.protocol()['id'])
        self.assertIn('Publicly posted solutions',req['questions']['evaluation_material_access']['instructions'])
        self.assertIn('Exclude natural-language instructions',req['questions']['evaluator_bypass']['instructions'])
        self.assertIn('Broad git branch/log/fsck',req['questions']['history_reference_search']['instructions'])

    def test_inline_action_labels_no_longer_merge_returned_material_and_use(self):
        s=source(trace='[tool] Returned reference patch\n[assistant tool_call] Apply the patch\n[tool] Done')
        current=c.fragments(s);previous=c.fragments(s,c.LEGACY_VERSION)
        self.assertNotEqual(current,previous)
        reference=next(f for f in current if 'Returned reference' in f['text'])
        action=next(f for f in current if 'Apply the patch' in f['text'])
        self.assertLessEqual(reference['end'],action['start'])
        # Historical requests must retain their original proposal boundaries.
        self.assertTrue(any('Returned reference' in f['text'] and 'Apply the patch' in f['text'] for f in previous))

    def test_compact_prompt_keeps_every_source_fragment_text(self):
        s=reuse_source();req=c.request(s)
        self.assertEqual(req['state']['source_fragments'],{f['id']:f['text'] for f in c.fragments(s)})

    def test_instruction_delivery_is_not_a_mechanical_bypass(self):
        def decide(req):
            stage=req['state'].get('stage');answers={}
            for k in req['questions']:
                value='instructions_only' if k=='bypass_mechanism' else 'supported' if stage=='validate_evidence_chains' else 'f1' if stage=='evidence_roles' else 'observed' if k=='evaluator_bypass' else 'not_observed'
                answers[k]={'value':value}
            return answers,digest(req)
        r=c.build(source(),decide);m=r['metrics']['evaluator_bypass']
        self.assertEqual(m['value'],0)
        self.assertEqual(m['selection'],'observed')
        self.assertEqual(m['evidence_verdict'],'supported')
        self.assertEqual(m['mechanism_selection'],'instructions_only')

    def test_missing_role_never_supports_numeric_positive(self):
        def decide(req):
            stage=req['state'].get('stage')
            return {k:{'value':'none' if stage=='evidence_roles' else 'supported' if stage else 'observed'} for k in req['questions']},digest(req)
        r=c.build(source(),decide)
        self.assertTrue(all(m['value'] is None for m in r['metrics'].values()))

    def test_incomplete_refutation_does_not_become_negative(self):
        def decide(req):
            stage=req['state'].get('stage')
            return {k:{'value':'none' if stage=='evidence_roles' else 'ordinary_or_excluded' if stage else 'observed'} for k in req['questions']},digest(req)
        r=c.build(source(complete_recorded_text=False),decide)
        self.assertTrue(all(m['value'] is None for m in r['metrics'].values()))


if __name__=='__main__':unittest.main()
