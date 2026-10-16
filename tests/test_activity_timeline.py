"""Aggregation safeguards; synthetic choices are not semantic references."""
import copy
import unittest

from tracker.activity import ActivityClient, analyze, units
from tracker.activity_timeline import build
from tracker.adapters import normalize
from tracker.schema import InputError
from test_activity import reasoning_run, response


class ActivityTimelineTests(unittest.TestCase):
    def test_overlapping_tags_keep_unobserved_positions_in_denominator(self):
        run=reasoning_run();source=units(run)
        client=ActivityClient(transport=lambda r:response(r,{'plan':'present','reason':'present'}))
        saved={source[0]['id']:client.evaluate(run,source[0]['id'])}
        saved[source[-1]['id']]=ActivityClient(transport=response).evaluate(run,source[-1]['id'])
        observed=analyze(run,saved);stream=observed['timeline']['streams'][0]
        self.assertEqual([u['id'] for u in stream['units']],[u['id'] for u in source])
        counts=stream['views'][0]['windows'][0]['fields']
        for field in ('plan','reason'):
            self.assertEqual([counts[field][k] for k in ('present','absent','unknown','denominator')],[1,1,4,6])
            self.assertEqual(counts[field]['unknown_reasons'],{'unobserved':4})
        self.assertEqual(stream['units'][1]['states']['plan']['value'],None)
        # A source window is based on all units, never just those with labels.
        timeline=build(observed['units'],observed['taxonomy'],{},window_size=2)
        self.assertEqual([(w['start'],w['end']) for w in timeline['streams'][0]['views'][0]['windows']],[(0,2),(2,4),(4,6)])

    def test_evidence_and_link_limits_keep_raw_winners(self):
        run=reasoning_run();run['events'][1]['text']='x'*5001;source=units(run)
        client=ActivityClient(transport=lambda r:response(r,{'plan':'present'}))
        result=client.evaluate(run,source[0]['id']);before=copy.deepcopy(result)
        timeline=analyze(run,{source[0]['id']:result})['timeline'];stream=timeline['streams'][0]
        state=stream['units'][0]['states']['plan']
        self.assertEqual((state['value'],state['availability']),('present','evidence_limited'))
        counts=stream['views'][0]['windows'][0]['fields']['plan']
        self.assertEqual(counts['present'],0);self.assertEqual(counts['selected_options']['present'],1)
        self.assertEqual(counts['unknown_reasons']['evidence_limited'],1)
        self.assertEqual(result,before)
        run=reasoning_run();source=units(run)[3]
        result=ActivityClient(transport=lambda r:response(r,{'revise':'present','revision_target':'no_suitable_candidate'})).evaluate(run,source['id'])
        stream=analyze(run,{source['id']:result})['timeline']['streams'][0]
        state=next(u for u in stream['units'] if u['id']==source['id'])['states']['revise']
        self.assertEqual((state['value'],state['availability']),('present','link_limited'))

    def test_observer_versions_never_pool_and_stale_results_are_not_current(self):
        run=reasoning_run();source=units(run);saved={}
        for unit,model in zip(source[:2],('jev-1.13.0','jev-synthetic-profile')):
            client=ActivityClient(model=model,transport=lambda r:response(r,{'plan':'present'}))
            saved[unit['id']]=client.evaluate(run,unit['id'])
        stream=analyze(run,saved)['timeline']['streams'][0]
        self.assertEqual(len(stream['views']),2)
        for view in stream['views']:
            counts=view['windows'][0]['fields']['plan']
            self.assertEqual((counts['present'],counts['unknown'],counts['denominator']),(1,5,6))
            self.assertEqual(counts['unknown_reasons'],{'other_profile':1,'unobserved':4})
            self.assertEqual(counts['selected_options'],{'present':1,'unobserved':5})
        changed=copy.deepcopy(run);changed['events'][0]['text']='Different initial instruction.'
        stream=analyze(changed,saved)['timeline']['streams'][0]
        self.assertIsNone(stream['views'][0]['profile_id'])
        self.assertEqual(stream['views'][0]['windows'][0]['fields']['plan']['unknown_reasons'],{'stale':2,'unobserved':4})

    def test_actors_kinds_and_source_linked_payloads_stay_separate(self):
        run=normalize({'trajectory':[{'role':'user','text':'Check it.'},{'role':'assistant','text':'I will check.\n```bash\npytest\n```\nThen report.'}]},'nebius')[0]
        event=copy.deepcopy(next(e for e in run['events'] if e['kind']=='message'))
        event.update(id='other-actor-message',trajectory_id='other-actor',index=99,text='A separate response.')
        run['events'].append(event);observed=analyze(run)
        streams=observed['timeline']['streams']
        self.assertEqual(len(streams),3)
        self.assertEqual(sorted(len(s['units']) for s in streams),[1,1,2])
        self.assertEqual(sum(len(s['units']) for s in streams),sum(u['eligible'] for u in observed['units']))
        payloads={u['id'] for u in observed['units'] if u['kind']=='action_payload'}
        self.assertFalse(payloads & {u['id'] for s in streams for u in s['units']})

    def test_dynamic_taxonomy_empty_sources_and_window_validation(self):
        observed=analyze(reasoning_run())
        timeline=build(list(reversed(observed['units'])),{'new_category':{}},{},window_size=3)
        self.assertEqual(list(timeline['streams'][0]['views'][0]['windows'][0]['fields']),['new_category'])
        self.assertEqual([u['id'] for u in timeline['streams'][0]['units']],[u['id'] for u in observed['units']])
        self.assertEqual(build([],{},{} )['streams'],[])
        for value in (0,101,True,1.5):
            with self.assertRaises(InputError):build([],{}, {},window_size=value)


if __name__=='__main__':unittest.main()
