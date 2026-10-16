from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tracker import graph_store, work_mentions as mentions
from tracker.schema import InputError,digest
from tracker.store import Store
from test_work_scope_frames import fixture,rekey


def proposal(packet):
    return dict(readings=[dict(unit_id=u['unit_id'],candidates=[dict(reading='Two linked local work contents.',mentions=[
        dict(id='create',label='Create a sample.',kind='operation',mode='proposed',evidence={'text':u['source']['text']}),
        dict(id='test',label='Test the implementation.',kind='operation',mode='proposed',evidence={'text':u['source']['text']})],
        links=[dict(source='create',target='test',type='purpose',evidence={'text':u['source']['text']})])]) for u in packet['units']])


def answer(request,values=None):
    values=values or {}
    return dict(model=request['model'],answers={q:dict(type='choice',choice='no_suitable_candidate',confidence=0,
        probabilities={k:float(k==values.get(q,'c0')) for k in value['criteria']}) for q,value in request['questions'].items()})


class WorkMentionTests(unittest.TestCase):
    def setup_case(self,count=1):
        run,graph=fixture(count);packet=mentions.packet(graph,['unit-'+str(i) for i in range(count)])
        response=proposal(packet);bound=mentions.bind(packet,response,'authored control');req=mentions.selection_request(packet,bound)
        return run,graph,packet,response,bound,req

    def test_exact_binding_and_unchanged_base_units(self):
        _,g,p,r,b,req=self.setup_case()
        original=deepcopy(g);out=mentions.fork(g,p,r,'authored control',answer(req));report=mentions.audit(out)
        self.assertEqual(report['rows'][0]['choice'],'c0')
        self.assertEqual(g,original)
        self.assertEqual([n for n in out['nodes'] if n['kind']=='unit'],[n for n in g['nodes'] if n['kind']=='unit'])
        self.assertEqual(out['source_hash'],g['source_hash'])
        self.assertEqual(len([e for e in out['edges'] if e['type']=='local_work_purpose']),1)
        self.assertFalse(any(e['type'] in {'part_of','same_work_target'} for e in out['edges']))

    def test_rejection_and_unresolved_keep_unit_coverage_without_mentions(self):
        _,g,p,r,b,req=self.setup_case(3)
        out=mentions.fork(g,p,r,'authored control',answer(req,{'u1':'no_suitable_candidate','u2':'unresolved'}))
        rows=mentions.audit(out)['rows']
        self.assertEqual([x['choice'] for x in rows],['c0','no_suitable_candidate','unresolved'])
        self.assertEqual([x['reading'] for x in rows[1:]],[None,None])
        self.assertEqual(out['coverage']['work_mentions'],dict(requested_units=3,selected_units=1,mentions=2))

    def test_missing_duplicate_or_foreign_unit_fails(self):
        _,_,p,r,_,_=self.setup_case(2)
        for rows in (r['readings'][:1],[r['readings'][0]]*2,[dict(unit_id='other',candidates=r['readings'][0]['candidates'])]):
            with self.subTest(rows=rows),self.assertRaises(InputError):mentions.bind(p,dict(readings=rows),'test')

    def test_invented_quote_and_cross_unit_link_fail(self):
        _,_,p,r,_,_=self.setup_case()
        bad=deepcopy(r);bad['readings'][0]['candidates'][0]['mentions'][0]['evidence']['text']='No such wording.'
        with self.assertRaises(InputError):mentions.bind(p,bad,'test')
        bad=deepcopy(r);bad['readings'][0]['candidates'][0]['links'][0]['target']='external-unit'
        with self.assertRaises(InputError):mentions.bind(p,bad,'test')

    def test_ambiguous_quote_needs_relative_start_and_keeps_unicode_offsets(self):
        unit=dict(source=dict(event_id='e',start=10,end=24,text='😀 go then go'))
        with self.assertRaises(InputError):mentions.quote({'text':'go'},unit)
        self.assertEqual(mentions.quote({'text':'go','start':10},unit),dict(event_id='e',start=20,end=22,text='go'))
        with self.assertRaises(InputError):mentions.quote({'text':'go','start':3},unit)

    def test_protocol_and_changed_packet_cannot_reuse_selection(self):
        _,g,p,r,b,req=self.setup_case()
        wrong=answer(req);wrong['model']='other'
        with self.assertRaises(InputError):mentions.fork(g,p,r,'authored control',wrong)
        changed=deepcopy(p);changed['units'][0]['source']['text']='Changed'
        with self.assertRaises(InputError):mentions.fork(g,changed,r,'authored control',answer(req))

    def test_tampered_label_or_relation_fails_replay(self):
        _,g,p,r,b,req=self.setup_case();out=mentions.fork(g,p,r,'authored control',answer(req))
        for mode in ['label','edge']:
            changed=deepcopy(out)
            if mode=='label':next(n for n in changed['nodes'] if n['kind']=='work_mention')['properties']['label']='Invented'
            else:next(e for e in changed['edges'] if e['type']=='local_work_purpose')['type']='local_work_before'
            rekey(changed)
            with self.assertRaises(InputError):mentions.audit(changed)

    def test_source_limits_and_attribution_are_explicit(self):
        _,g,p,_,_,_=self.setup_case()
        for ids in ([],['unit-0']*2,['absent'],[[]]):
            with self.assertRaises(InputError):mentions.packet(g,ids)
        changed=deepcopy(g);next(n for n in changed['nodes'] if n['kind']=='unit')['properties']['actor']='user';rekey(changed)
        with self.assertRaises(InputError):mentions.packet(changed,['unit-0'])

    def test_save_reuses_identity_and_rejects_updated_source(self):
        run,g,p,r,b,req=self.setup_case();decision=answer(req)
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'db.sqlite');store.add([run])
            with store.connect() as c:graph_store.save(c,g)
            saved=mentions.save_selected(store,p,r,'authored control',decision)
            self.assertEqual(saved,mentions.save_selected(store,p,r,'authored control',decision))
            self.assertEqual(len(mentions.audit(graph_store.read(store,saved['graph_id']))['rows']),1)
            run['metadata']['changed']='yes'
            with store.connect() as c:c.execute('UPDATE runs SET document=? WHERE id=?',(json.dumps(run),run['id']))
            with self.assertRaises(InputError):mentions.save_selected(store,p,r,'authored control',decision)

    def test_projection_distinguishes_unobserved_rejected_and_selected_empty(self):
        _,g,_,_,_,_=self.setup_case(4)
        p=mentions.packet(g,['unit-0','unit-1','unit-2']);r=proposal(p)
        r['readings'][0]['candidates'][0]['mentions']=[]
        r['readings'][0]['candidates'][0]['links']=[]
        b=mentions.bind(p,r,'test');req=mentions.selection_request(p,b)
        out=mentions.fork(g,p,r,'test',answer(req,{'u1':'no_suitable_candidate','u2':'unresolved'}))
        rows=mentions.project(out)['rows']
        self.assertEqual([r['status'] for r in rows],['selected','no_suitable_candidate','unresolved'])
        self.assertEqual(rows[0]['reading']['mentions'],[])
        self.assertIsNone(rows[1]['reading'])
        self.assertEqual(mentions.project(out,'unit-3')['rows'][0]['status'],'unobserved')
        self.assertEqual(mentions.project(out)['counts'],dict(observed_units=3,selected_units=1,published_units=1))
        self.assertFalse(mentions.project(g)['available'])
        with self.assertRaises(InputError):mentions.project(out,'not-a-unit')
        changed=deepcopy(out)
        changed['semantic_context']['work_mentions']['proposal']['readings'][0]['candidates'][0]['reading']='Changed'
        rekey(changed)
        with self.assertRaises(InputError):mentions.project(changed)

    def test_malformed_external_proposal_references_are_input_errors(self):
        _,_,p,r,_,_=self.setup_case()
        for field in ['id','kind','mode']:
            bad=deepcopy(r);bad['readings'][0]['candidates'][0]['mentions'][0][field]={}
            with self.subTest(field=field),self.assertRaises(InputError):mentions.bind(p,bad,'test')
        for field in ['source','target','type']:
            bad=deepcopy(r);bad['readings'][0]['candidates'][0]['links'][0][field]=[]
            with self.subTest(field=field),self.assertRaises(InputError):mentions.bind(p,bad,'test')

    def test_review_withholds_bad_readings_without_rewriting_raw_selection(self):
        _,g,p,r,b,req=self.setup_case(2);response=answer(req)
        review=dict(author='Development reviewer',basis='Not independent validation',units=[
            dict(unit_id='unit-0',decision='include',reason='Reviewed against source'),
            dict(unit_id='unit-1',decision='withhold',reason='Wrong purpose target')])
        out=mentions.fork(g,p,r,'authored control',response,review)
        self.assertEqual(out['semantic_context']['work_mentions']['response'],response)
        self.assertEqual(out['coverage']['work_mentions']['selected_units'],2)
        self.assertEqual(out['coverage']['work_mentions']['visible_units'],1)
        rows=mentions.project(out)['rows']
        self.assertEqual([row['status'] for row in rows],['selected','withheld'])
        self.assertEqual(rows[1]['choice'],'c0');self.assertIsNone(rows[1]['reading'])
        self.assertFalse(any(n['kind']=='work_mention' and n['properties']['unit_id']=='unit-1' for n in out['nodes']))
        reject=answer(req,{'u0':'no_suitable_candidate'})
        with self.assertRaises(InputError):mentions.fork(g,p,r,'authored control',reject,review)
        changed=deepcopy(out);changed['semantic_context']['work_mentions']['review']['units'][1]['decision']='include';rekey(changed)
        with self.assertRaises(InputError):mentions.audit(changed)


if __name__=='__main__':unittest.main()
