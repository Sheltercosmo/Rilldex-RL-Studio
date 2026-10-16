import copy
import unittest
from tracker.reference_encoding import compact, expand, MARKER
from tracker.schema import InputError, dumps


class ReferenceEncodingTests(unittest.TestCase):
    def request(self):
        scope={'id':'source','text':'Exact source words 🧭 '*80,'start':0,'end':1600}
        anchor={'id':'a','scope':scope,'selection':{'text':'source','start':6,'end':12},'provenance':{'request_hash':'hash'}}
        return {'model':'pinned','state':{'fields':{str(i):{'candidates':[copy.deepcopy(anchor)],'scope':copy.deepcopy(scope)} for i in range(4)},'missingness':{},'cutoff_event_id':'e2'},
                'questions':{'q':{'type':'choice','criteria':{'a':'Candidate a','unresolved':'Unknown'}}}}
    def test_exact_round_trip_smaller_wire_and_unchanged_choices(self):
        request=self.request();before=copy.deepcopy(request);wire=compact(request)
        self.assertEqual(expand(wire),request);self.assertEqual(request,before)
        self.assertLess(len(dumps(wire)),len(dumps(request)));self.assertEqual(wire['questions'],request['questions'])
    def test_tampered_registry_and_cycles_fail(self):
        wire=compact(self.request());key=next(iter(wire['state']['evidence_values']))
        for value in ['modified',{MARKER:key}]:
            altered=copy.deepcopy(wire);altered['state']['evidence_values'][key]=value
            with self.assertRaises(InputError):expand(altered)
    def test_source_marker_collision_stays_literal(self):
        request=self.request();request['state']['literal']={MARKER:'user-provided'}
        self.assertEqual(compact(request),request);self.assertEqual(expand(request),request)


if __name__=='__main__':unittest.main()
