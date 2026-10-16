from copy import deepcopy
import unittest

from tracker.prefix_encoding import compact,expand,audit,MARKER
from tracker.schema import InputError


def request():
    text='🧭 evidence with literal {"$same_as_event":"example"}. '*80
    tool={'definition':{'description':'A tool description. '*200,'name':'check'}}
    return {'state':{'prefix':[
        {'id':'a','event_index':0,'actor':'model','text':text,'tool_contract':tool},
        {'id':'b','event_index':2,'actor':'customer','text':text,'tool_contract':tool},
        {'id':'c','event_index':4,'actor':'model','text':text,'tool_contract':tool}],
        'source':{'text':text[2:21]},'cutoff_event_id':'c'},
        'model':'pinned-test','questions':{'tag':{'criteria':{'present':'yes','absent':'no'}}}}


class PrefixEncodingTests(unittest.TestCase):
    def test_round_trip_retains_unicode_events_attribution_questions_and_source(self):
        r=request();old=deepcopy(r);encoded=compact(r)
        self.assertEqual(r,old);self.assertEqual(expand(encoded),r)
        self.assertEqual(len(encoded['state']['prefix']),3)
        self.assertEqual(encoded['state']['prefix'][1]['actor'],'customer')
        self.assertEqual(encoded['state']['prefix'][2]['text'],{MARKER:'a'})
        self.assertEqual(encoded['questions'],r['questions'])
        self.assertEqual(encoded['state']['source'],r['state']['source'])
        proof=audit(r,encoded);self.assertEqual(len(proof['references']),4)
        self.assertLess(proof['encoded_characters'],proof['original_characters'])
        encoded['state']['source']['text']='tampered'
        with self.assertRaises(InputError):expand(encoded)

    def test_references_cannot_point_forward_cross_field_or_create_cycles(self):
        for anchor in ['c','missing',5]:
            encoded=compact(request());encoded['state']['prefix'][1]['text']={MARKER:anchor}
            with self.assertRaises(InputError):expand(encoded)
        encoded=compact(request());encoded['state']['prefix'][0].pop('tool_contract')
        with self.assertRaises(InputError):expand(encoded)
        encoded=compact(request());encoded['state']['prefix'][1]['text']['extra']='ignored?'
        with self.assertRaises(InputError):expand(encoded)

    def test_no_saving_is_exact_noop_and_near_matches_are_never_merged(self):
        r=request();r['state']['prefix']=r['state']['prefix'][:1]
        self.assertEqual(compact(r),r)
        r=request();r['state']['prefix'][1]['text']+='changed';r['state']['prefix'][2]['text']+='different'
        encoded=compact(r)
        self.assertIsInstance(encoded['state']['prefix'][1]['text'],str)
        self.assertIsInstance(encoded['state']['prefix'][2]['text'],str)
        self.assertEqual(expand(encoded),r)

    def test_unknown_encoding_duplicate_order_and_reserved_values_are_rejected(self):
        r=request();r['state']['prefix'][1]['id']='a'
        with self.assertRaises(InputError):compact(r)
        r=request();r['state']['prefix'][1]['event_index']=0
        with self.assertRaises(InputError):compact(r)
        r=request();r['state']['prefix'][0]['tool_contract']={MARKER:'literal'}
        with self.assertRaises(InputError):compact(r)
        r=compact(request());r['state']['prefix_encoding']['version']='unknown'
        with self.assertRaises(InputError):expand(r)
        with self.assertRaises(InputError):compact(compact(request()))


if __name__=='__main__':unittest.main()
