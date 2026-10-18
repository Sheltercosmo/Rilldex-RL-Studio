import json
import unittest

from tracker.diagnostic_excerpts import project
from tracker.schema import dumps


def setup(events):
    return {'task':'Task','trace':dumps(events)},{'events':events}


def ref(source,text,*,offset=0):
    start=source['trace'].index(text,offset)
    return dict(id='trace:'+str(start),origin='trace',start=start,end=start+len(text),text=text)


class DiagnosticExcerptTests(unittest.TestCase):
    def test_selected_span_not_full_message_and_exact_unit_links(self):
        e=dict(id='e',actor='agent',kind='reasoning',text='Long setup. A gap remains. Other content.')
        source,run=setup([e]);r=ref(source,'A gap remains.')
        graph={'nodes':[{'id':key,'properties':{'source':{'event_id':'e','start':a,'end':b}}} for key,a,b in [('before',0,10),('gap',12,26),('after',27,40)]]}
        p=project(source,[r],run,graph)[r['id']][0]
        self.assertEqual(p['text'],'A gap remains.');self.assertEqual(p['node_ids'],['gap'])
        self.assertEqual(e['text'][p['start']:p['end']],p['text'])
        self.assertEqual(p['serialized_start'],r['start']);self.assertEqual(p['serialized_end'],r['end'])

    def test_arguments_are_not_replaced_with_an_unrelated_event_message(self):
        source,run=setup([dict(id='e',actor='agent',kind='action',text='Editing file',arguments={'command':'write dummy payload'})])
        r=ref(source,'dummy payload');p=project(source,[r],run)[r['id']][0]
        self.assertEqual(p['field'],['arguments','command']);self.assertEqual(p['text'],'dummy payload')
        self.assertEqual(p['node_ids'],['event:e'])

    def test_nested_json_tool_output_decodes_once_per_structure_with_literal_backslashes(self):
        code='return "中文";\npath = r"C:\\new\\file";'
        source,run=setup([dict(id='e',actor='environment',kind='feedback',text=dumps({'output':code,'returncode':0}))])
        start=source['trace'].index('return ');end=source['trace'].rindex(';')+1
        r=dict(id='x',origin='trace',start=start,end=end,text=source['trace'][start:end])
        p=project(source,[r],run)['x'][0]
        self.assertEqual(p['field'],['text','$json','output'])
        self.assertEqual(p['text'],code)
        self.assertEqual(p['kind'],'feedback')

    def test_unicode_escape_boundaries_cover_whole_decoded_character(self):
        events=[dict(id='e',actor='agent',kind='message',text='A😀B\nC')]
        source={'task':'Task','trace':json.dumps(events,ensure_ascii=True)};run={'events':events}
        r=ref(source,'d83d\\ude');p=project(source,[r],run)[r['id']][0]
        self.assertEqual(p['text'],'😀')
        self.assertLess(p['serialized_start'],r['start']);self.assertGreater(p['serialized_end'],r['end'])
        r2=ref(source,'\\nC');self.assertEqual(project(source,[r2],run)[r2['id']][0]['text'],'\nC')

    def test_a_fragment_spanning_records_does_not_invent_a_single_event(self):
        source,run=setup([dict(id='one',actor='agent',kind='message',text='first'),dict(id='two',actor='tool',kind='feedback',text='second')])
        start=source['trace'].index('first');end=source['trace'].index('second')+6
        r=dict(id='pair',origin='trace',start=start,end=end,text=source['trace'][start:end])
        p=project(source,[r],run)['pair'];self.assertEqual([x['event_id'] for x in p],['one','two'])
        self.assertEqual([x['text'] for x in p],['first','second'])

    def test_mismatched_range_does_not_get_a_different_excerpt(self):
        source,run=setup([dict(id='e',actor='agent',kind='message',text='original')]);r=ref(source,'original');r['text']='changed'
        self.assertEqual(project(source,[r],run),{})


if __name__=='__main__':unittest.main()
