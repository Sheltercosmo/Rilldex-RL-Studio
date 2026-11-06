"""Historical role answers bind to question IDs, never saved dictionary order."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.evaluate_requirement_prior_panel import historical_terms
from tracker import requirement_diagnostics as detector
from tracker.jev import validate_answers
from tracker.schema import digest,dumps
from tracker.semantic_extraction import Pipeline,read


class HistoricalRequirementRoleTests(unittest.TestCase):
    def test_saved_json_lexical_order_does_not_reassign_term_answers(self):
        paragraphs=['Preserve the required target output.']+[f'Background paragraph number {i}.' for i in range(11)]
        source=dict(schema='diagnostic-input/1',id='role-order-control',task='See attributed instruction events in the trace.',
            trace=dumps([dict(id='u',actor='user',kind='instruction',text='\n\n'.join(paragraphs))]),
            complete_recorded_text=True,action_coverage='recorded')
        request=next(detector.term_requests(source,version=detector.HARNESS_VERSION));before=deepcopy(request)
        intended=next(iter(request['state']['instruction_paragraphs'].values()))
        def transport(req):
            return {'model':req['model'],'answers':{field:{'type':'choice','probabilities':{
                option:float(option==('task_requirement' if field=='term_0' else 'context')) for option in q['criteria']}}
                for field,q in req['questions'].items()}}
        with TemporaryDirectory() as temp:
            engine=Pipeline(temp,None,transport);answers,key=engine.decide(request)
            self.assertEqual(request,before)
            saved=read(Path(temp)/'decisions'/(key+'.json'))
            original_ids=list(request['state']['instruction_paragraphs'])
            persisted_ids=list(saved['request']['state']['instruction_paragraphs'])
            self.assertNotEqual(original_ids,persisted_ids)
            wrong=[t for i,t in enumerate(saved['request']['state']['instruction_paragraphs'].values())
                   if saved['answers']['term_'+str(i)]['value']=='task_requirement']
            correct=[row['term'] for row in historical_terms(saved) if row['selection']=='task_requirement']
            self.assertNotEqual(wrong,[intended]);self.assertEqual(correct,[intended])
            self.assertEqual(engine.decide(before)[0],answers)
            self.assertEqual(next(iter(before['state']['instruction_paragraphs'].values())),intended)

    def test_invalid_trial_retains_actual_responses_without_becoming_accuracy_evidence(self):
        frozen=read(Path(__file__).parent/'fixtures/requirement-prior-live.json')
        self.assertEqual(frozen['input_validity'],'invalid_historical_role_mapping')
        self.assertEqual(frozen['observed_score_summary']['reference_matches'],2)
        count=0
        for row in frozen['rows']:
            for packet in row['packets']:
                self.assertEqual(digest(packet['request']),packet['request_hash'])
                self.assertEqual(digest(packet['response']),packet['response_hash'])
                answers=validate_answers(packet['response'],packet['request'])
                self.assertEqual({k:a['value'] for k,a in answers.items()},
                    {k:a['selection'] for k,a in packet['answers'].items()})
                count+=1
        self.assertEqual(count,7)


if __name__=='__main__':unittest.main()
