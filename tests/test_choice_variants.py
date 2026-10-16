from copy import deepcopy
import unittest
from tracker import choice_variants
from tracker.schema import InputError,dumps
from tracker.jev import validate_answers
from test_work_mentions import answer


class ChoiceVariants(unittest.TestCase):
    def request(self):
        return dict(model='jev-1.13.0',state=dict(text='Inspect the evidence.',cutoff_event_id='e0',missingness={'truncated_event_ids':[]}),
            questions={'q':dict(type='choice',instructions='Choose the applicable rule.',criteria={'supported':'Explicit support.','not_expressed':'Absent expressed relation.','unresolved':'Not decidable.'})})

    def test_only_option_identifiers_change_and_sorted_order_is_preserved(self):
        request=self.request();original=deepcopy(request);r=choice_variants.opaque(request);v=r['variant']
        self.assertEqual(request,original);self.assertEqual(v['state'],request['state'])
        self.assertEqual(v['questions']['q']['instructions'],request['questions']['q']['instructions'])
        self.assertEqual(list(v['questions']['q']['criteria'].values()),[request['questions']['q']['criteria'][k] for k in sorted(request['questions']['q']['criteria'])])
        self.assertEqual(choice_variants.opaque(request),r)

    def test_probabilities_and_argmax_are_bijective_not_thresholded(self):
        request=self.request();r=choice_variants.opaque(request);response=answer(r['variant'],{'q':'o001'})
        response['answers']['q']['probabilities']={'o000':.32,'o001':.35,'o002':.33}
        decoded=choice_variants.decode(request,r,response)
        self.assertEqual(validate_answers(decoded,request)['q']['value'],'supported')
        self.assertEqual(sorted(response['answers']['q']['probabilities'].values()),sorted(decoded['answers']['q']['probabilities'].values()))

    def test_mapping_or_missing_probability_cannot_silently_change_meaning(self):
        request=self.request();r=choice_variants.opaque(request)
        for mode in ('mapping','missing','model'):
            receipt=deepcopy(r);response=answer(r['variant'],{'q':'o001'})
            if mode=='mapping':receipt['mapping']['q']['o001']='unresolved'
            elif mode=='missing':response['answers']['q']['probabilities'].pop('o001')
            else:response['model']='other'
            with self.subTest(mode=mode),self.assertRaises(InputError):choice_variants.decode(request,receipt,response)

    def test_mixed_question_types_are_not_partially_transformed(self):
        req=self.request();req['questions']['q']['type']='score'
        with self.assertRaises(InputError):choice_variants.opaque(req)
