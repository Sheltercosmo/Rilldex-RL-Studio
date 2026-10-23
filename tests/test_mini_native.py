from copy import deepcopy
import unittest
from tracker.adapters import normalize
from tracker.capabilities import links
from tracker.mini_capture import MiniCapture, CaptureMixin
from tracker.schema import InputError


def source(messages):
    return {'trajectory_format':'mini-swe-agent-1.1','info':{'mini_version':'2.4.6','exit_status':''},
            'messages':[{'role':'system','content':'Task rules'},{'role':'user','content':'Fix the task'},*messages]}


def action(command='echo ok', cid=None):
    a={'command':command}
    if cid is not None:a['tool_call_id']=cid
    return a


def assistant(actions, **kwargs):
    return {'role':'assistant','content':'Next operation','extra':{'actions':actions},**kwargs}


def result(cid=None, **kwargs):
    return {'role':'tool' if cid else 'user','content':'returned','extra':{'raw_output':'returned','returncode':0},
            **({'tool_call_id':cid} if cid else {}),**kwargs}


class MiniNativeTests(unittest.TestCase):
    def test_native_model_and_agent_version_are_kept_without_inventing_checkpoints(self):
        doc=source([assistant([action()])])
        doc['info']['config']={'model':{'model_name':'provider/released-model'}}
        run=normalize(doc)[0]
        self.assertEqual(run['metadata']['model'],'provider/released-model')
        self.assertEqual(run['metadata']['agent_version'],'2.4.6')
        self.assertNotIn('checkpoint',run['metadata'])
        self.assertEqual(normalize(doc,meta={'model':'explicit-model'})[0]['metadata']['model'],'explicit-model')

    def test_parsed_actions_win_over_displayed_fences_and_bind_batch_results(self):
        doc=source([assistant([action('one','a'),action('two','b')],content='```bash\nwrong\n```'),result('b'),result('a')])
        run=normalize(doc)[0];calls=[e for e in run['events'] if e['kind']=='action']
        self.assertEqual([e['text'] for e in calls],['one','two']);self.assertEqual(len(links(run)['records']),2)
        self.assertEqual(links(run)['by_action'][calls[0]['id']][0]['native_call_id'],'a')
        self.assertEqual(run['adapter_version'],'mini-swe-agent/3');self.assertEqual(run['raw'],doc)

    def test_positional_text_results_and_interruption_do_not_become_goal_changes(self):
        doc=source([assistant([action('one'),action('two')]),result(),result(),
            {'role':'user','content':'invalid response','extra':{'interrupt_type':'FormatError'}},
            {'role':'user','content':'A real follow-up'}, {'role':'exit','content':'limit','extra':{'exit_status':'LimitsExceeded'}}])
        run=normalize(doc)[0];self.assertEqual(len(links(run)['records']),2)
        self.assertEqual(run['events'][-3]['kind'],'feedback');self.assertIsNone(run['events'][-3]['source_call_id'])
        self.assertEqual(run['events'][-2]['actor'],'user');self.assertEqual(run['events'][-2]['kind'],'instruction')
        self.assertEqual(run['events'][-1]['actor'],'environment')

    def test_submission_does_not_fabricate_execution_of_remaining_batch_actions(self):
        run=normalize(source([assistant([action('submit','a'),action('never','b')]),
            {'role':'exit','content':'Done','extra':{'exit_status':'Submitted','submission':'Done'}}]))[0]
        self.assertEqual(len(links(run)['records']),0);self.assertEqual(run['events'][-1]['actor'],'agent')
        self.assertTrue(all(e['execution']=='not_established' for e in run['events'] if e['kind']=='action'))

    def test_responses_api_items_preserve_text_media_actions_and_results(self):
        native={'object':'response','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'Check inputs'},{'type':'image','url':'image'}]},
            {'type':'function_call','call_id':'x','name':'bash','arguments':'{"command":"echo ok"}'}], 'extra':{'actions':[action(cid='x')]}}
        run=normalize(source([native,{'type':'function_call_output','call_id':'x','output':'ok','extra':{'raw_output':'ok','returncode':0}}]))[0]
        self.assertEqual(run['events'][2]['text'],'Check inputs');self.assertEqual(len(run['events'][2]['media']),1)
        self.assertEqual(len(links(run)['records']),1);self.assertEqual(run['events'][-1]['source_pointer'],'/messages/3/output')

    def test_ambiguous_duplicate_and_malformed_native_records_fail(self):
        for rows in [[assistant([action(cid='a'),action(cid='a')])], [assistant([action(cid='a')]),result('a'),result('a')],
                     [assistant([{'bad':'action'}])], [{'role':'unknown','content':'x'}], [{'role':'assistant','content':'x','extra':1}]]:
            with self.subTest(rows=rows),self.assertRaises(InputError):normalize(source(rows))
        run=normalize(source([assistant([action(cid='a')]),result('missing')]))[0]
        self.assertEqual(len(links(run)['records']),0)

    def test_legacy_identity_is_unchanged(self):
        doc=source([{'role':'assistant','content':'```bash\necho ok\n```'},{'role':'user','content':'ok'}]);doc['info'].pop('mini_version')
        run=normalize(doc)[0];self.assertEqual(run['adapter_version'],'adapters/1')
        self.assertEqual(len(links(run)['records']),1)


class Sink:
    def __init__(self):self.rows=[]
    def log(self,*args,**kwargs):self.rows.append(deepcopy((args,kwargs)));return 'queued'


class MiniCaptureTests(unittest.TestCase):
    def test_snapshots_keep_native_source_and_explicit_termination(self):
        sink=Sink();capture=MiniCapture(sink,rollout_id='r',context=lambda:{'task_id':'t'},on_error='raise')
        doc=source([assistant([action()]),result()]);before=deepcopy(doc)
        self.assertEqual(capture.record(doc),'queued');self.assertEqual(doc,before)
        doc['info']['exit_status']='LimitsExceeded';capture.record(doc)
        doc['info']['exit_status']='Submitted';capture.record(doc)
        doc['info']['exit_status']='RuntimeError';capture.record(doc)
        self.assertEqual([row[1]['state'] for row in sink.rows],['in_progress','complete','complete','failed'])
        self.assertEqual(capture.counts['queued'],4)

    def test_capture_failure_policy_and_enrichment_integrity(self):
        sink=Sink();capture=MiniCapture(sink,rollout_id='r',context=lambda:{},on_error='warn',
            enrich=lambda d:dict(d,messages=[]))
        with self.assertWarns(RuntimeWarning):capture.record(source([]))
        self.assertEqual(capture.counts['failed'],1);self.assertEqual(sink.rows,[])
        capture.on_error='raise'
        with self.assertRaises(InputError):capture.record(source([]))

    def test_public_save_hook_preserves_original_return_and_save_even_if_capture_fails(self):
        calls=[];doc=source([])
        class Native:
            def save(self,path,*extras):calls.append(path);return doc
        class Captured(CaptureMixin,Native):pass
        capture=MiniCapture(Sink(),rollout_id='r',context=lambda:[],on_error='raise')
        agent=Captured(capture=capture)
        with self.assertRaises(InputError):agent.save('native.json')
        self.assertEqual(calls,['native.json'])


if __name__=='__main__':unittest.main()
