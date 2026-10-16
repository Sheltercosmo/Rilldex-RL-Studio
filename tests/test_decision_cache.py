import copy
from pathlib import Path
import tempfile
import unittest
from tracker.schema import InputError,digest
from tracker.semantic_extraction import Pipeline,read,write,request,activity_choices,ACTIVITY_ROUTING,windows
from tracker import decision_cache
from tests.test_semantic_extraction import fixture,response


class ExactReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.target=self.root/'target'
        run=fixture();self.req=request(run,windows(run)[0],'activity','Choose the contribution',activity_choices(ACTIVITY_ROUTING))
        self.answers,self.key=Pipeline(self.source,None,response).decide(self.req)

    def test_exact_packet_reused_and_local_replay_survives_missing_origin(self):
        engine=Pipeline(self.target,None,lambda _:self.fail('Exact reuse must not call provider'),cache_directories=[self.source])
        self.assertEqual(engine.decide(self.req),(self.answers,self.key))
        self.assertEqual(engine.calls,0);self.assertEqual(engine.reused_decisions,{self.key})
        self.assertEqual(decision_cache.audit(self.target)['exact_reused_decisions'],1)
        (self.source/'decisions'/f'{self.key}.json').unlink()
        self.assertEqual(engine.decide(self.req),(self.answers,self.key))
        self.assertEqual(decision_cache.audit(self.target)['exact_reused_decisions'],1)

    def test_changed_context_or_choices_is_not_a_cache_hit(self):
        for field in ('context','choices'):
            req=copy.deepcopy(self.req)
            if field=='context':req['state']['prefix'][0]['text']+=' changed'
            else:req['questions']['choice']['criteria']['plan']+=' changed'
            observed=[]
            engine=Pipeline(self.target/field,None,lambda r:(observed.append(r) or response(r)),cache_directories=[self.source])
            engine.decide(req);self.assertEqual(len(observed),1);self.assertFalse(engine.reused_decisions)

    def test_wrong_model_and_modified_saved_argmax_are_rejected(self):
        original=read(self.source/'decisions'/f'{self.key}.json')
        for kind in ('model','argmax'):
            bad=copy.deepcopy(original)
            if kind=='model':bad['response']['model']='different'
            else:bad['answers']['choice']['value']='plan'
            write(self.source/'decisions'/f'{self.key}.json',bad)
            with self.assertRaises(InputError):
                Pipeline(self.target,None,lambda _:self.fail('Invalid cache must not be treated as a miss'),cache_directories=[self.source]).decide(self.req)
            self.assertFalse((self.target/'decisions'/f'{self.key}.json').exists())

    def test_conflicting_sources_do_not_select_by_directory_order(self):
        other=self.root/'other'
        def select(req):
            r=response(req);labels=req['questions']['choice']['criteria']
            r['answers']['choice']['probabilities']={k:0.9 if k=='plan' else 0.1/(len(labels)-1) for k in labels};return r
        Pipeline(other,None,select).decide(self.req)
        with self.assertRaisesRegex(InputError,'conflicting selected answers'):
            Pipeline(self.target,None,response,cache_directories=[self.source,other]).decide(self.req)
        self.assertFalse((self.target/'decisions'/f'{self.key}.json').exists())

    def test_local_cached_response_must_keep_the_requested_model(self):
        packet=read(self.source/'decisions'/f'{self.key}.json')
        packet['response']['model']='different'
        write(self.source/'decisions'/f'{self.key}.json',packet)
        with self.assertRaisesRegex(InputError,'model'):
            Pipeline(self.source,None,lambda _:self.fail('Corruption is not a cache miss')).decide(self.req)

    def test_read_only_lookup_validates_without_writing(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        path,saved,count=decision_cache.lookup(self.req,[self.source,self.root/'absent'])
        self.assertEqual(path,self.source/'decisions'/f'{self.key}.json')
        self.assertEqual(saved['answers'],self.answers);self.assertEqual(count,1)
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertIsNone(decision_cache.lookup({**self.req,'model':'different'},[self.source]))
