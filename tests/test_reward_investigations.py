import copy
import unittest

from tracker import reward_investigations as rewards, training_investigations, training_comparisons
from tracker import training_health, monitoring, failure_investigations
from tracker.schema import InputError
from tracker.reward_relationships import assign_patterns
import test_training_lineage as fixtures
from test_training_lineage import record


class RewardInvestigationTests(unittest.TestCase):
    setUp=fixtures.TrainingLineageTests.setUp
    add=fixtures.TrainingLineageTests.add
    packet=fixtures.TrainingLineageTests.packet
    source=fixtures.TrainingLineageTests.source

    def prepare(self):
        for name,x,y,length in [('a',0,0,1),('b',0,2,3),('c',2,0,5),('d',2,2,7)]:
            self.source(name,'x'*length)
            self.add(record('sample',name,group_size=4,task_id='task'),
                     record('score',name,identifier='x/'+name,component='x',definition='x/1',value=x),
                     record('score',name,identifier='y/'+name,component='y',definition='y/1',value=y))
        self.monitor=monitoring.create(self.store,{'name':'Response length','kind':'metric','observer':'source','metric':'agent_text_chars'})
        monitoring.sync(self.store)
        scope={'experiment':'exp','monitor':self.monitor['id']}
        health=training_health.snapshot(self.store,**scope);c=health['cohorts'][0];pair=c['reward_relationships']
        # Set X/Y explicitly, independently of the automatic coverage ordering.
        x=next(k['id'] for k in pair['components'] if k['component']=='x');y=next(k['id'] for k in pair['components'] if k['component']=='y')
        health=training_health.snapshot(self.store,**scope,reward_x=x,reward_y=y)
        self.request={'scope':scope,'snapshot_id':health['snapshot_id'],'cohort_id':c['id'],'reward_x':x,'reward_y':y,
                      'title':'Authored reward-pattern investigation','hypothesis':''}
        self.cohort=c['cohort']
        return rewards.save(self.store,self.request)

    def spec(self):
        return {'cohort':self.cohort,'focus':{'kind':'reward_pattern','value':'x_above_y_below'},
                'reference':{'kind':'reward_pattern','value':'both_above'},'monitors':[self.monitor['id']]}

    def test_shared_population_and_explicit_patterns_connect_to_behavior(self):
        parent=self.prepare();context=parent['reward_comparison']
        self.assertEqual(context['evidence']['patterns'],{'both_above':1,'x_above_y_below':1,'x_below_y_above':1,'both_below':1,'at_mean':0,'unavailable':0})
        got=training_comparisons.preview(self.store,{'parent_id':parent['id'],'spec':self.spec()})
        self.assertEqual((len(got['focus_ids']),len(got['reference_ids'])),(1,1))
        self.assertEqual(got['metrics'][0]['difference'],-2)
        self.assertEqual(got['metrics'][0]['within_group']['mean_group_difference'],-2)
        self.assertEqual(got['inference_calls'],0)
        self.assertEqual(got['reward_context']['health_snapshot_id'],self.request['snapshot_id'])
        for sample in got['samples']:
            self.assertIn('reward_evidence',sample)

    def test_corrected_live_scores_do_not_reclassify_saved_cases(self):
        parent=self.prepare();before=training_comparisons.preview(self.store,{'parent_id':parent['id'],'spec':self.spec()})
        self.add(record('score','c',identifier='x/c',revision=1,component='x',definition='x/1',value=-99))
        self.assertEqual(before,training_comparisons.preview(self.store,{'parent_id':parent['id'],'spec':self.spec()}))
        with self.assertRaisesRegex(InputError,'Reward evidence changed'):rewards.save(self.store,self.request)

    def test_scheduler_change_requires_refresh_without_rewriting_saved_investigation(self):
        from tracker import generation_cohorts
        parent=self.prepare()
        generation_cohorts.receive(self.store,dict(schema=generation_cohorts.VERSION,producer='scheduler',experiment='exp',
            cohorts=[dict(id='pending-batch',revision=0,label='Pending batch',coordinate=dict(clock='generation',basis='batch',index=1),
                context={},sealed=True,members=[dict(producer='worker',rollout_id='not-arrived',generation_state='admitted',context={})],
                evidence='Scheduler declaration after the displayed reward snapshot')]))
        with self.assertRaisesRegex(InputError,'Reward evidence changed'):rewards.save(self.store,self.request)
        self.assertEqual(failure_investigations.read(self.store,parent['id']),parent)

    def test_duplicate_save_and_hypothesis_revision_preserve_reward_context(self):
        parent=self.prepare();self.assertEqual(parent,rewards.save(self.store,self.request))
        child=training_investigations.save(self.store,{'parent_id':parent['id'],'view':parent['view'],
            'title':'Revised question','hypothesis':'Inspect task mix before interpreting a difference.'})
        self.assertEqual(child['reward_comparison'],parent['reward_comparison'])
        self.assertEqual(child['live_url'],parent['live_url'])
        self.assertEqual(child['source_graphs'],parent['source_graphs'])

    def test_point_selection_keeps_original_complete_group_baselines(self):
        parent=self.prepare()
        selected=rewards.save(self.store,{**self.request,'step':0})
        self.assertEqual(selected['view']['selection']['step'],0)
        self.assertEqual(selected['reward_comparison'],parent['reward_comparison'])
        for step in (-1,True,99):
            with self.assertRaises(InputError):rewards.save(self.store,{**self.request,'step':step})

    def test_rejects_client_replacement_evidence_and_foreign_pair(self):
        parent=self.prepare()
        for change in ({'records':[]},{'snapshot_id':'forged'},{'reward_y':'missing'},{'cohort_id':'missing'},
                       {'scope':{'selection':'fake'}},{'title':''},{'hypothesis':None}):
            with self.assertRaises(InputError):rewards.save(self.store,self.request|change)
        self.assertEqual(len(failure_investigations.saved(self.store)),1)

    def test_reward_selector_requires_saved_context_and_its_cohort(self):
        parent=self.prepare();spec=self.spec()
        foreign=copy.deepcopy(parent);foreign.pop('reward_comparison')
        with self.assertRaises(InputError):training_comparisons.validate(foreign,spec)
        foreign=copy.deepcopy(parent);foreign['reward_comparison']['cohort']={'split':'evaluation'}
        with self.assertRaises(InputError):training_comparisons.validate(foreign,spec)
        spec['focus']['value']='reward_hacking'
        with self.assertRaises(InputError):training_comparisons.validate(parent,spec)

    def test_saved_behavior_comparison_preserves_pattern_evidence(self):
        parent=self.prepare();spec=self.spec()
        preview=training_comparisons.preview(self.store,{'parent_id':parent['id'],'spec':spec})
        saved=training_comparisons.save(self.store,{'parent_id':parent['id'],'spec':spec,'preview_id':preview['id']})
        self.assertEqual(saved['reward_comparison'],parent['reward_comparison'])
        self.assertEqual(saved['measure_comparison'],preview)
        self.assertEqual(failure_investigations.read(self.store,saved['id']),saved)

    def test_same_mean_and_missing_group_do_not_acquire_direction(self):
        rows=[{'x':{'value':x},'y':{'value':y},'group_status':'complete','group_id':'g'} for x,y in [(0,2),(1,1),(2,0)]]
        rows.append({'group_status':'scores_incomplete','group_id':'missing'})
        assign_patterns(rows)
        self.assertEqual([r['reward_pattern'] for r in rows],['x_below_y_above','at_mean','x_above_y_below','unavailable'])
        constant=[{'x':{'value':.1},'y':{'value':i},'group_status':'complete','group_id':'c'} for i in range(7)]
        assign_patterns(constant)
        self.assertTrue(all(r['reward_pattern']=='at_mean' for r in constant))

    def test_independent_samples_keep_identity_and_unique_source_weight(self):
        from test_training_samples import record as independent_record
        from tracker import training_lineage, training_samples
        for name, text in [('shared','x'*9),('other','x'),('third','xxx')]:
            self.source(name,text)
        records=[]
        for name,source,value in [('a','shared',2),('b','shared',2),('c','other',0),('d','third',0)]:
            records.append(independent_record('sample',name,group_size=4,
                source={'producer':'worker','rollout_id':source,'revision':0}))
            for component in ('x','y'):
                records.append(independent_record('score',name,identifier=component+'/'+name,
                    component=component,definition=component+'/1',value=value))
        training_lineage.receive(self.store,{'schema':training_samples.VERSION,'producer':'learner-export','experiment':'exp','records':records})
        # Same textual ID in the legacy sample contract cannot enter this cohort.
        self.add(record('sample','a'),record('score','a',component='x',value=99))
        monitor=monitoring.create(self.store,{'name':'Length','kind':'metric','observer':'source','metric':'agent_text_chars'})
        monitoring.sync(self.store);scope={'experiment':'exp','monitor':monitor['id']}
        health=training_health.snapshot(self.store,**scope)
        cohort=next(c for c in health['cohorts'] if c['cohort'].get('sample_identity_schema'))
        pair=cohort['reward_relationships']
        parent=rewards.save(self.store,{'scope':scope,'snapshot_id':health['snapshot_id'],'cohort_id':cohort['id'],
            'reward_x':pair['selected']['x']['id'],'reward_y':pair['selected']['y']['id'],
            'title':'Independent sample control','hypothesis':''})
        result=training_comparisons.preview(self.store,{'parent_id':parent['id'],'spec':{
            'cohort':cohort['cohort'],'focus':{'kind':'reward_pattern','value':'both_above'},
            'reference':{'kind':'reward_pattern','value':'both_below'},'monitors':[monitor['id']]}})
        self.assertEqual(len(result['samples']),4)
        self.assertTrue(all(s['producer']=='learner-export' and 'reward_evidence' in s for s in result['samples']))
        self.assertEqual(len(result['focus_ids']),2)
        self.assertEqual(result['metrics'][0]['focus']['source_rollouts'],1)
        self.assertEqual(result['metrics'][0]['difference'],7)

    def test_group_mean_direction_survives_extreme_scale_cancellation(self):
        rows=[{'x':{'value':x},'y':{'value':y},'group_status':'complete','group_id':'g'}
              for x,y in [(-1e308,0),(1e-300,1),(1e308,0)]]
        assign_patterns(rows)
        self.assertEqual([r['reward_pattern'] for r in rows],
            ['both_below','both_above','x_above_y_below'])
