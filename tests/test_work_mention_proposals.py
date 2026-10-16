from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tracker import work_mentions as mentions, work_mention_proposals as proposals
from tracker.schema import InputError, digest
from test_work_mentions import proposal, answer
from test_work_scope_frames import fixture


class WorkProposalTests(unittest.TestCase):
    def case(self, count=1):
        _, graph=fixture(count)
        packet=mentions.packet(graph,['unit-'+str(i) for i in range(count)])
        candidates=proposal(packet)
        bodies={r['unit_id']:dict(candidate=r['candidates'][0], inventory=[dict(
            role='operation',evidence={'text':packet['units'][i]['source']['text']},
            mention_ids=['create','test'],link_indices=[0],note='Authored mechanical control, not a completeness annotation.')])
            for i,r in enumerate(candidates['readings'])}
        return graph,packet,bodies

    def test_each_request_has_only_its_selected_source_no_inherited_tags(self):
        _,p,_=self.case(2);q=proposals.request(p,'unit-1')
        self.assertEqual(q['unit'],p['units'][1])
        self.assertNotIn('units',q);self.assertNotIn('base_graph_id',q)
        self.assertNotIn('activity',q['unit']);self.assertNotIn('candidates',q)
        q['link_meanings']['purpose']='modified'
        self.assertNotEqual(mentions.LINKS['purpose'],'modified')

    def test_inventory_is_source_bound_but_not_published_as_tags(self):
        g,p,bodies=self.case();before=deepcopy(g)
        assembled=proposals.assemble(p,bodies,'control')
        bound=assembled['bound'];req=mentions.selection_request(p,bound)
        out=mentions.fork(g,p,assembled['response'],'control',answer(req))
        mentions.audit(out)
        self.assertEqual(g,before)
        self.assertEqual([n for n in out['nodes'] if n['kind']=='unit'],[n for n in g['nodes'] if n['kind']=='unit'])
        self.assertNotIn('construction',out['semantic_context']['work_mentions'])
        self.assertIn('not independent',assembled['construction'][0]['limit'])

    def test_changed_source_or_instructions_fail_before_binding(self):
        _,p,b=self.case();q=proposals.request(p,'unit-0')
        for key in ['construction','local_work_rule']:
            bad=deepcopy(q);bad[key]='different'
            with self.subTest(key=key),self.assertRaises(InputError):proposals.bind(p,bad,b['unit-0'],'control')
        q['unit']['source']['text']='changed'
        with self.assertRaises(InputError):proposals.bind(p,q,b['unit-0'],'control')

    def test_inventory_quote_must_be_exact(self):
        _,p,b=self.case();b['unit-0']['inventory'][0]['evidence']['text']='invented source'
        with self.assertRaises(InputError):proposals.assemble(p,b,'control')

    def test_inventory_cannot_map_unknown_ids_bool_indices_or_duplicate_mappings(self):
        _,p,b=self.case()
        for key,value in [('mention_ids',['missing']),('mention_ids',['create','create']),('link_indices',[True]),('link_indices',[2]),('link_indices',[0,0])]:
            bad=deepcopy(b);bad['unit-0']['inventory'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(InputError):proposals.assemble(p,bad,'control')

    def test_proposed_contents_cannot_bypass_the_inventory(self):
        _,p,b=self.case()
        for key,value in [('mention_ids',['create']),('link_indices',[])]:
            bad=deepcopy(b);bad['unit-0']['inventory'][0][key]=value
            with self.subTest(key=key),self.assertRaises(InputError):proposals.assemble(p,bad,'control')

    def test_unrepresented_inventory_requires_a_recorded_explanation_not_fake_work(self):
        _,p,b=self.case();item=dict(role='non_work_content',evidence={'text':p['units'][0]['source']['text']},mention_ids=[],link_indices=[],note='No additional independently referable operation in this phrase.')
        b['unit-0']['inventory'].append(item)
        result=proposals.assemble(p,b,'control')
        self.assertEqual(result['construction'][0]['unmapped_inventory'],[1])
        self.assertEqual(len(result['bound']['readings'][0]['candidates'][0]['mentions']),2)
        item['note']=''
        with self.assertRaises(InputError):proposals.assemble(p,b,'control')

    def test_missing_or_extra_unit_responses_fail(self):
        _,p,b=self.case(2)
        missing=deepcopy(b);missing.pop('unit-1')
        with self.assertRaises(InputError):proposals.assemble(p,missing,'control')
        extra=deepcopy(b);extra['unknown']=b['unit-1']
        with self.assertRaises(InputError):proposals.assemble(p,extra,'control')

    def test_file_roundtrip_reuses_exact_outputs_and_never_overwrites_changes(self):
        _,p,b=self.case(2)
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)/'study';manifest=proposals.prepare_files(p,directory)
            self.assertEqual(manifest['new_provider_calls'],0)
            for row in manifest['requests']:
                proposals.write_new(directory/'responses'/f"{row['request_hash']}.json",b[row['unit_id']])
            first=proposals.assemble_files(directory,'control')
            content=(directory/'assembled.json').read_bytes()
            self.assertEqual(first,proposals.assemble_files(directory,'control'))
            self.assertEqual(content,(directory/'assembled.json').read_bytes())
            with self.assertRaises(InputError):proposals.prepare_files(p,directory)
            with self.assertRaises(InputError):proposals.write_new(directory/'assembled.json',{'changed':True})
            self.assertEqual(content,(directory/'assembled.json').read_bytes())

    def test_file_assembly_rejects_tampered_request_and_duplicate_manifest(self):
        _,p,b=self.case(2)
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)/'study';m=proposals.prepare_files(p,directory)
            for row in m['requests']:proposals.write_new(directory/'responses'/f"{row['request_hash']}.json",b[row['unit_id']])
            row=m['requests'][0];path=directory/'requests'/f"{row['request_hash']}.json"
            path.write_text('{}')
            with self.assertRaises(InputError):proposals.assemble_files(directory,'control')
            path.write_text(json.dumps(proposals.request(p,row['unit_id'])))
            m['requests'][1]=m['requests'][0]
            (directory/'manifest.json').write_text(json.dumps(m))
            with self.assertRaises(InputError):proposals.assemble_files(directory,'control')

    def test_empty_candidate_and_explicit_unrepresented_source_remain_proposals(self):
        _,p,b=self.case();b['unit-0']={'candidate':{'reading':'No local work proposed.','mentions':[],'links':[]},'inventory':[{
            'role':'non_work_content','evidence':{'text':p['units'][0]['source']['text']},'mention_ids':[],'link_indices':[],'note':'Mechanical empty example only.'}]}
        result=proposals.assemble(p,b,'control')
        self.assertEqual(result['construction'][0]['unmapped_inventory'],[0])
        self.assertEqual(result['bound']['readings'][0]['candidates'][0]['mentions'],[])

    def test_external_delivery_is_bound_locally_replayable_and_attributed(self):
        _,p,b=self.case()
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)/'study';m=proposals.prepare_files(p,directory);key=m['requests'][0]['request_hash']
            raw=Path(root)/'completion.txt';raw.write_text(json.dumps(b['unit-0']),encoding='utf-8')
            result=proposals.accept_file(directory,key,raw,'External control','completion-1')
            self.assertFalse(result['reused']);self.assertEqual(result['new_provider_calls'],0)
            self.assertTrue(proposals.accept_file(directory,key,raw,'External control','completion-1')['reused'])
            self.assertEqual(proposals.assemble_files(directory,'External control')['mentions'],2)
            receipt=json.loads((directory/'deliveries'/f'{key}.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['raw_output'],raw.read_text(encoding='utf-8'))
            self.assertEqual(receipt['completion_ref'],'completion-1')
            with self.assertRaises(InputError):proposals.accept_file(directory,key,raw,'External control','completion-2')
            changed=deepcopy(b['unit-0']);changed['candidate']['reading']='Silently replaced interpretation'
            (directory/'responses'/f'{key}.json').write_text(json.dumps(changed),encoding='utf-8')
            with self.assertRaises(InputError):proposals.assemble_files(directory,'External control')

    def test_invalid_delivery_never_creates_an_accepted_response(self):
        _,p,b=self.case()
        for mode in ('non_json','wrong_quote','wrong_request','changed_request','too_large'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as root:
                directory=Path(root)/'study';m=proposals.prepare_files(p,directory);key=m['requests'][0]['request_hash']
                body=deepcopy(b['unit-0']);raw=Path(root)/'completion.txt'
                if mode=='wrong_quote':body['inventory'][0]['evidence']['text']='Invented content'
                raw.write_text('Invalid JSON' if mode=='non_json' else ' '*128001 if mode=='too_large' else json.dumps(body),encoding='utf-8')
                if mode=='changed_request':(directory/'requests'/f'{key}.json').write_text('{}')
                with self.assertRaises(InputError):proposals.accept_file(directory,'../outside' if mode=='wrong_request' else key,raw,'control','completion-1')
                self.assertFalse((directory/'responses').exists());self.assertFalse((directory/'deliveries').exists())


if __name__=='__main__':unittest.main()
