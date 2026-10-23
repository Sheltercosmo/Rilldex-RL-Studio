import copy
import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from rilldex import TrainerTelemetry, Workspace, chat_document
from tracker import trainer_case_studies as studies, telemetry_queries as queries
from tracker import training_lineage, case_comparisons, failure_investigations, findings_report
from tracker.store import Store
from tracker.schema import InputError
import test_generation_cohort_transport as transport


class TrainerCaseTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.db=self.root/'study.sqlite';self.store=Store(self.db)

    def source(self,name,*,experiment='run',revision=0,success=False,step=99):
        meta=dict(experiment=experiment,task_id='parser',task_revision='1',environment='terminal',
                  environment_version='1',split='train',reward_definition='tests/v1',training_step=step)
        return self.store.ingest(dict(producer='actor',rollout_id=name,revision=revision,state='complete',metadata=meta,
            document=chat_document([dict(role='assistant',content=f'Attempt {name} revision {revision}')],success=success)))['id']

    def use(self,name,*,experiment='run',producer='learner',source_revision=0,independent=False):
        sample=dict(producer='actor',**({'id':name} if independent else {'rollout_id':name}))
        records=[dict(id='sample-'+name,revision=0,kind='sample',sample=sample,
            evidence=dict(basis='source',**({} if independent else {'source_revision':source_revision})),
            data=dict(split='train',**({'source':dict(producer='actor',rollout_id=name,revision=source_revision)} if independent else {}))),
            dict(id='use-'+name,revision=0,kind='use',sample=sample,evidence=dict(basis='learner'),
                data=dict(stage='optimizer_step_completed',learner_step=700,batch_id='batch'))]
        training_lineage.receive(self.store,dict(schema='training-records/2' if independent else 'training-records/1',producer=producer,experiment=experiment,records=records))
        return dict(producer=producer,id='use-'+name,revision=0)

    def log(self,step,*refs,experiment='run',producer='learner',session='first',record_id=None,coverage='complete',metrics=None,**kwargs):
        logger=TrainerTelemetry(self.store,experiment=experiment,producer=producer,session=session,
            framework='trl-grpo',framework_version='authored',objective='grpo/test',**kwargs)
        logger.log(metrics or {'loss':.3},step=step,record_id=record_id,
            **({'training_uses':dict(records=list(refs),coverage=coverage,basis='declared batch')} if refs else {}))

    def selection(self,*,experiment='run',producer='learner',session='first',start=0,end=10):
        data=queries.query(self.store,experiment=experiment,producer=producer,session=session)
        series=next(s for s in data['series'] if s['native_key']=='loss')
        return dict(series_id=series['id'],as_of=data['as_of'],start=start,end=end)

    def save(self,left=None,right=None):
        return studies.save(self.store,dict(reference=left or self.selection(end=0),selected=right or self.selection(start=1)))

    def test_exact_links_and_matched_task_case_flow_ignore_equal_rollout_steps(self):
        a=self.source('a',step=900);b=self.source('b',success=True,step=800)
        unrelated=self.source('equal-step',step=1)
        self.log(0,self.use('a'));self.log(1,self.use('b'))
        doc=self.save();self.assertEqual(doc['snapshot']['population'],dict(baseline=[a],current=[b]))
        self.assertNotIn(unrelated,str(doc['snapshot']['population']))
        self.assertEqual(case_comparisons.listing(self.store,doc['id'])['counts'],{'improved':1})
        pair=case_comparisons.pair(self.store,doc['id'],a,b)
        self.assertEqual(pair['status'],'improved');self.assertEqual(pair['reference']['graph']['observer'],'source')
        self.assertIn('Native update links and coverage',findings_report.summary(doc)['scope'])

    def test_reused_rollouts_are_preserved_separately_and_count_once(self):
        a=self.source('a');b=self.source('b');shared=self.source('shared')
        ar,br,sr=(self.use(x) for x in ('a','b','shared'))
        self.log(0,ar,sr);self.log(1,br,sr);self.log(2,br,sr)
        doc=self.save();native=doc['snapshot']['trainer_selection']
        self.assertEqual(doc['snapshot']['population'],dict(baseline=[a],current=[b]))
        self.assertEqual(native['shared_run_ids'],[shared]);self.assertEqual(native['cohorts']['current']['references'],{'matched':4})
        self.assertEqual(len(doc['snapshot']['source_rows']),3)
        self.assertIn(shared,doc['snapshot']['case_evidence']['sources'])

    def test_old_source_revision_and_its_graph_are_pinned(self):
        old=self.source('a');ref=self.use('a');new=self.source('a',revision=1,success=True)
        b=self.source('b',success=True);self.log(0,ref);self.log(1,self.use('b'))
        doc=self.save();self.assertEqual(doc['snapshot']['population']['baseline'],[old])
        pair=case_comparisons.pair(self.store,doc['id'],old,b)
        self.assertNotEqual(pair['reference']['run']['id'],new);self.assertEqual(pair['status'],'improved')

    def test_late_logs_and_sources_do_not_mutate_saved_selection(self):
        self.source('a');self.log(0,self.use('a'));pending=self.use('late');self.log(1,pending)
        left,right=self.selection(end=0),self.selection(start=1)
        old=self.save(left,right);self.assertEqual(old['snapshot']['population']['current'],[])
        b=self.source('late',success=True);self.source('extra');self.log(1,self.use('extra'),record_id='late-native')
        refreshed=self.save(left,right)
        self.assertEqual(refreshed['snapshot']['population']['current'],[b])
        self.assertEqual(refreshed['snapshot']['trainer_selection']['cohorts']['current']['records'],1)
        self.assertEqual(failure_investigations.read(self.store,old['id']),old)
        current=self.save(left,self.selection(start=1))
        self.assertEqual(len(current['snapshot']['population']['current']),2)

    def test_partial_missing_and_wrong_references_stay_visible(self):
        a=self.source('a');ref=self.use('a');missing=dict(producer='absent',id='u',revision=0)
        self.log(0,ref,missing,coverage='partial');self.log(1);self.log(2,{**ref,'producer':'other'})
        doc=self.save();native=doc['snapshot']['trainer_selection']['cohorts']
        self.assertEqual(native['baseline']['reference_inventory'],{'partial':1})
        self.assertEqual(native['baseline']['references'],{'matched':1,'not_joined_to_selection':1})
        self.assertEqual(native['current']['reference_inventory'],{'not_declared':1,'complete':1})
        self.assertEqual(doc['snapshot']['population'],dict(baseline=[a],current=[]))

    def test_duplicate_coordinates_do_not_drop_the_33rd_reference(self):
        ids=[]
        for i in range(40):
            name='trial-'+str(i);ids.append(self.source(name));self.log(0,self.use(name),record_id='log-'+str(i))
        left=self.selection(end=0);doc=self.save(left,self.selection(start=1))
        self.assertEqual(set(doc['snapshot']['population']['baseline']),set(ids))
        c=doc['snapshot']['trainer_selection']['cohorts']['baseline']
        self.assertEqual(c['records'],40);self.assertEqual(c['coordinates'],{'conflicting':1})

    def test_series_definition_and_worker_session_boundaries(self):
        a=self.source('a');ref=self.use('a');self.log(0,ref)
        initial=self.selection();b=self.source('b');br=self.use('b')
        self.log(1,br,session='restart');self.log(1,br,producer='other')
        self.log(1,br,metrics={'entropy':.2})
        # A new metric definition at the same session does not enter the old series.
        definition=dict(label='Other loss',unit='score',reduction='sum',definition='different objective',group='loss')
        self.log(2,br,definitions={'loss':definition})
        cutoff=queries.query(self.store)['as_of'];left={**initial,'as_of':cutoff}
        doc=self.save(left,{**left,'start':20,'end':30});c=doc['snapshot']['trainer_selection']['cohorts']['baseline']
        self.assertEqual(c['run_ids'],[a]);self.assertEqual(c['records'],1);self.assertEqual(c['coordinates']['missing'],2)

    def test_independent_samples_and_cross_experiment_links(self):
        a=self.source('a',experiment='one');b=self.source('b',experiment='two',success=True)
        self.log(9,self.use('a',experiment='one',independent=True),experiment='one')
        self.log(9,self.use('b',experiment='two',independent=True),experiment='two')
        # Exact-looking identity from another experiment must not resolve here.
        self.log(10,dict(producer='learner',id='use-a',revision=0),experiment='two')
        doc=self.save(self.selection(experiment='one'),self.selection(experiment='two'))
        self.assertEqual(doc['snapshot']['population'],dict(baseline=[a],current=[b]))
        self.assertEqual(doc['snapshot']['trainer_selection']['cohorts']['current']['references']['not_joined_to_selection'],1)

    def test_full_sequence_not_downsampled_points_defines_membership(self):
        a=self.source('a');ar=self.use('a');b=self.source('b');br=self.use('b')
        for step in range(256):self.log(step,ar if step<128 else br,record_id='step-'+str(step))
        data=queries.query(self.store,max_points=24);self.assertLess(len(data['series'][0]['points']),256)
        doc=self.save(self.selection(end=127),self.selection(start=128,end=255))
        self.assertEqual([c['records'] for c in doc['snapshot']['trainer_selection']['cohorts'].values()],[128,128])
        self.assertEqual(doc['snapshot']['population'],dict(baseline=[a],current=[b]))

    def test_no_links_empty_intervals_and_invalid_input_are_explicit(self):
        self.log(0);doc=self.save()
        self.assertEqual(doc['snapshot']['population'],dict(baseline=[],current=[]))
        self.assertEqual(case_comparisons.listing(self.store,doc['id'])['total_contexts'],0)
        valid=dict(reference=self.selection(),selected=self.selection())
        for raw in ({**valid,'extra':1},{**valid,'return_to':'//evil.test'},
                    {**valid,'reference':{**valid['reference'],'as_of':True}},
                    {**valid,'selected':{**valid['selected'],'start':9,'end':2}}):
            with self.assertRaises(InputError):studies.save(self.store,raw)

    def test_all_reused_rollouts_do_not_create_empty_task_pairs(self):
        a=self.source('shared');ref=self.use('shared');self.log(0,ref);self.log(1,ref)
        doc=self.save();self.assertEqual(doc['snapshot']['trainer_selection']['shared_run_ids'],[a])
        self.assertEqual(case_comparisons.listing(self.store,doc['id'])['total_contexts'],0)

    def test_conflicting_sample_declarations_cannot_choose_a_source(self):
        self.source('a');ref=self.use('a');self.source('a',revision=1)
        row=dict(id='alternate-sample-a',revision=0,kind='sample',sample=dict(producer='actor',rollout_id='a'),
                 evidence=dict(basis='alternate source',source_revision=1),data=dict(split='train'))
        training_lineage.receive(self.store,dict(schema='training-records/1',producer='other',experiment='run',records=[row]))
        self.log(0,ref);doc=self.save();cohort=doc['snapshot']['trainer_selection']['cohorts']['baseline']
        self.assertEqual(cohort['references'],{'not_joined_to_selection':1});self.assertEqual(cohort['run_ids'],[])

    def test_record_limit_refuses_silent_partial_comparisons(self):
        self.log(0);self.log(1);selection=self.selection()
        with self.assertRaisesRegex(InputError,'Narrow each interval'):
            queries.selected_records(self.store,**selection,limit=1)

    def test_python_api_and_http_capture(self):
        a=self.source('a');b=self.source('b');self.log(0,self.use('a'));self.log(1,self.use('b'))
        raw=dict(reference=self.selection(end=0),selected=self.selection(start=1))
        saved=Workspace(self.db).compare_trainer_rollouts(**raw)
        self.assertEqual(saved['snapshot']['population'],dict(baseline=[a],current=[b]))
        endpoint=transport.GenerationCohortTransportTests.start_server(self)
        request=Request(endpoint+'/api/investigations/trainer-cases',data=json.dumps(raw).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request) as response:
            result=json.load(response);self.assertEqual(response.status,201)
        self.assertEqual(result['snapshot']['population'],saved['snapshot']['population'])
        bad=Request(endpoint+'/api/investigations/trainer-cases',data=b'{}',headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as e:urlopen(bad)
        self.assertEqual(e.exception.code,400)

    stop_server=staticmethod(transport.GenerationCohortTransportTests.stop_server)


if __name__=='__main__':unittest.main()
