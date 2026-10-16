from copy import deepcopy
import unittest

from tracker.review_evidence import validate_spans,SPAN_BASIS
from tracker.schema import InputError


def case():
    return {'fields':{'plan':{},'reason':{}},
            'subject':{'id':'unit','text':'🧭 Now, for the formula; I will compare both.'},
            'source':{'id':'unit','text':'Earlier plan.'},
            'available_prefix':[{'id':'event','text':'Context. 🧭 Now, for the formula; I will compare both.'}]}


def citation(field='plan',target='subject',start=2,end=10):
    c=case();item=c['subject'] if target=='subject' else c['source'] if target=='source' else c['available_prefix'][0]
    return {'field':field,'target':target,'evidence_id':item['id'],'start':start,'end':end,
            'text':item['text'][start:end],'role':'label_evidence','basis':SPAN_BASIS}


class ReviewEvidenceTests(unittest.TestCase):
    def test_optional_legacy_citations_and_multi_field_multi_span_evidence(self):
        c=case();validate_spans({'evidence_ids':['unit']},c)
        row={'evidence_ids':['unit','event'],'evidence_spans':[citation(),citation(field='reason'),
             {**citation(target='prefix',start=0,end=7),'role':'context'}]}
        before=deepcopy(row);validate_spans(row,c);self.assertEqual(row,before)

    def test_unicode_and_explicit_target_disambiguate_same_id(self):
        c=case();a=citation(start=0,end=1);self.assertEqual(a['text'],'🧭')
        validate_spans({'evidence_ids':['unit'],'evidence_spans':[a,citation(target='source',start=0,end=7)]},c)
        a['target']='source'
        with self.assertRaises(InputError):validate_spans({'evidence_ids':['unit'],'evidence_spans':[a]},c)

    def test_bad_spans_fields_scope_and_types_rejected(self):
        c=case()
        changes=[{'field':'unknown'},{'target':'future'},{'target':[]},{'role':[]},{'role':'predicted'},
                 {'basis':'utf16'},{'start':True},{'start':0.5},{'start':-1},{'end':1000},
                 {'end':2},{'text':'fabricated quote'},{'evidence_id':'future-event'}]
        for change in changes:
            with self.subTest(change=change),self.assertRaises(InputError):
                validate_spans({'evidence_ids':['unit','event'],'evidence_spans':[{**citation(),**change}]},c)
        for value in (None,{},[citation()]*129):
            with self.assertRaises(InputError):validate_spans({'evidence_ids':['unit'],'evidence_spans':value},c)

    def test_duplicate_uncited_and_ambiguous_records_rejected(self):
        c=case();s=citation()
        for row in ({'evidence_ids':[],'evidence_spans':[s]}, {'evidence_ids':['unit'],'evidence_spans':[s,s]}):
            with self.assertRaises(InputError):validate_spans(row,c)
        c['available_prefix'].append(deepcopy(c['available_prefix'][0]))
        with self.assertRaises(InputError):validate_spans({'evidence_ids':['event'],'evidence_spans':[citation(target='prefix')]},c)


if __name__=='__main__':unittest.main()
