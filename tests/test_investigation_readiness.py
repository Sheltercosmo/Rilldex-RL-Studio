"""Authored controls for evidence accounting; not semantic reference labels."""
import sqlite3
import unittest
from unittest.mock import patch

from tracker import investigation_readiness as readiness, monitoring, training_lineage
from tracker import training_samples, rollout_metrics
from tracker.schema import InputError
import test_training_lineage as fixtures
import test_training_samples as independent
import test_recovery_windows as recovery


class ReadinessTests(unittest.TestCase):
    setUp = fixtures.TrainingLineageTests.setUp
    source = fixtures.TrainingLineageTests.source
    add = fixtures.TrainingLineageTests.add
    packet = fixtures.TrainingLineageTests.packet

    def measure(self, **kwargs):
        return monitoring.create(self.store, {'name':'Recorded length','kind':'metric','observer':'source',
                                              'metric':'agent_text_chars', **kwargs})

    def request(self, monitor=None, **kwargs):
        return {'recipe':'selection','experiment':'exp', **({'monitor':monitor['id']} if monitor else {}), **kwargs}

    def check(self, monitor=None, **kwargs): return readiness.check(self.store, self.request(monitor, **kwargs))

    def pair(self):
        for name, decision in [('a','admitted'),('b','rejected')]:
            self.source(name, name)
            self.add(fixtures.record('sample',name),fixtures.record('selection',name,decision=decision))
        m=self.measure();monitoring.sync(self.store)
        f=training_lineage.snapshot(self.store)['selection_options'][0]['id']
        return m,f

    def captured(self, steps):
        run=recovery.captured(steps)
        # Use the native outbox path to apply experiment metadata and revision identity.
        self.store.ingest({'producer':'worker','rollout_id':'case','revision':0,'state':'complete',
                           'document':run['raw'],'format':run['adapter'],'metadata':{'experiment':'exp','split':'train'}})
        m=monitoring.create(self.store,{'name':'Recovery','kind':'analysis','observer':'source',
                                       'analysis':{'measure':'criterion_recovery_window'}})
        monitoring.sync(self.store)
        return m

    def test_named_filter_counts_and_exact_evidence_are_preserved(self):
        m,f=self.pair();self.add(fixtures.record('sample','missing'))
        got=self.check(m,selection=f)
        self.assertEqual(got['summary']['row_statuses'],{'available':2,'source_missing':1})
        self.assertEqual(got['selection']['decisions'],{'admitted':1,'rejected':1,'not_recorded':1})
        self.assertEqual(got['selection']['cohorts_with_measured_sides'],1)
        self.assertIn(f,got['continue_url']);self.assertIn(m['id'],got['continue_url'])
        self.assertIn('value=',got['rows'][0]['evidence_url'])
        self.assertEqual(got['validation']['status'],'not_certified')
        self.assertFalse(got['persisted']);self.assertEqual(got['new_model_calls'],0)

    def test_current_zero_is_a_measurement_not_missing(self):
        self.source('a','');self.add(fixtures.record('sample'))
        m=self.measure();monitoring.sync(self.store);got=self.check(m)
        self.assertEqual(got['rows'][0]['measurement']['status'],'available')
        self.assertEqual(got['rows'][0]['measurement']['value'],0)

    def test_no_implicit_monitor_or_filter(self):
        self.pair();got=self.check()
        self.assertIsNone(got['monitor']);self.assertIsNone(got['selection']['filter'])
        self.assertEqual(got['summary']['row_statuses'],{'choose_measure':2})

    def test_unmaterialized_is_distinct_from_missing_observation(self):
        self.source('a');self.add(fixtures.record('sample'));m=self.measure()
        self.assertEqual(self.check(m)['rows'][0]['measurement']['status'],'not_materialized')
        absent=self.measure(observer='missing-observer')
        self.assertEqual(self.check(absent)['rows'][0]['measurement']['status'],'observation_missing')

    def test_freshness_uses_same_input_identity_as_materialization(self):
        m,f=self.pair();before=self.check(m,selection=f)
        rid=before['rows'][0]['run_id'];run=self.store.get(rid,raw=True)['run']
        newer=rollout_metrics.source_record(run);newer['test_provenance']='authored revised measurement input'
        with self.store.connect() as c: rollout_metrics.save(c,newer,created_at='9999-01-01T00:00:00Z')
        got=self.check(m,selection=f)
        self.assertEqual(got['summary']['row_statuses'],{'stale_measurement':1,'available':1})
        self.assertEqual(got['selection']['cohorts_with_measured_sides'],0)
        self.assertNotIn('value=',got['rows'][0]['evidence_url'])
        monitoring.sync(self.store)
        self.assertEqual(self.check(m,selection=f)['summary']['row_statuses'],{'available':2})

    def test_monitor_scope_and_disabled_state_are_visible(self):
        self.source('a');self.add(fixtures.record('sample'))
        m=self.measure(population={'experiment':'other'});monitoring.sync(self.store)
        monitoring.enabled(self.store,m['id'],False);got=self.check(m)
        self.assertEqual(got['summary']['row_statuses'],{'outside_measure_population':1})
        self.assertFalse(got['monitor']['enabled'])

    def test_score_errors_remain_component_records_and_missing_is_unknown(self):
        self.source('a');self.add(fixtures.record('sample'),fixtures.record('score',status='error',value=None),
            fixtures.record('score',identifier='other-score',component='other',value=0),fixtures.record('sample','b'))
        h=self.check()['training_health']
        self.assertEqual(h['score_record_statuses'],{'error':1,'scored':1})
        self.assertEqual(h['samples_without_score_records'],1)
        self.assertEqual(h['samples_with_optimizer_membership'],0)

    def test_orphan_and_conflicting_declarations_stay_out_of_population(self):
        self.add(fixtures.record('score','orphan'),fixtures.record('sample'),
                 fixtures.record('sample',identifier='duplicate-declaration'))
        got=self.check()
        self.assertEqual(got['total_rows'],0)
        self.assertEqual(got['selection']['orphans'],1)
        self.assertEqual(got['selection']['conflicting_declarations'],1)

    def test_pagination_detects_late_records_and_retains_scope(self):
        m,f=self.pair();first=self.check(m,selection=f,limit=1)
        second=self.check(m,selection=f,offset=1,limit=1,expected_revision=first['revision'])
        self.assertEqual(first['revision'],second['revision']);self.assertEqual(second['offset'],1)
        self.add(fixtures.record('score'))
        with self.assertRaisesRegex(InputError,'changed'):self.check(m,selection=f,offset=1,expected_revision=first['revision'])

    def test_read_only_snapshot_prevents_hidden_materialization(self):
        m,_=self.pair()
        with self.store.connect() as c: before='\n'.join(c.iterdump())
        with patch('tracker.monitoring.sync',side_effect=AssertionError('must not materialize')):
            readiness.options(self.store);self.check(m)
        with self.store.connect() as c: self.assertEqual(before,'\n'.join(c.iterdump()))
        original=monitoring.definitions
        def illegal_write(view):
            with view.connect() as c:c.execute('DELETE FROM monitors')
            return original(view)
        with patch('tracker.monitoring.definitions',illegal_write), self.assertRaises(sqlite3.OperationalError): self.check(m)

    def test_independent_samples_do_not_multiply_source_coverage(self):
        self.source('episode');records=[]
        for name,decision in [('s1','admitted'),('s2','rejected')]:
            records.extend([independent.record('sample',name,source={'producer':'worker','rollout_id':'episode','revision':0}),
                            independent.record('selection',name,decision=decision)])
        training_lineage.receive(self.store,{'schema':training_samples.VERSION,'producer':'learner-export','experiment':'exp','records':records})
        m=self.measure();monitoring.sync(self.store)
        got=self.check(m)
        self.assertEqual(got['total_rows'],2);self.assertEqual(got['summary']['source_statuses'],{'available':1})
        self.assertEqual(got['summary']['row_statuses'],{'available':2})

    def test_historical_pinned_source_is_not_replaced_by_latest_revision(self):
        old=self.source('a','old');self.add(fixtures.record('sample'));m=self.measure();monitoring.sync(self.store)
        new=self.source('a','new',1);monitoring.sync(self.store)
        got=self.check(m)
        self.assertEqual(got['rows'][0]['run_id'],old['id']);self.assertNotEqual(old['id'],new['id'])
        self.assertEqual(got['rows'][0]['measurement']['status'],'available')

    def test_recovery_unresolved_followup_is_not_failed_behavior(self):
        m=self.captured([recovery.check(),recovery.change(),recovery.check()])
        got=self.check(m,recipe='recovery')
        self.assertEqual(got['summary']['row_statuses'],{'unresolved_followup':1})
        self.assertEqual(got['summary']['opportunity_totals'],{'opportunities':2,'denominator':0,'unknown':2})

    def test_recovery_passing_case_links_exact_receipt_and_does_not_certify_semantics(self):
        m=self.captured([recovery.check(),recovery.change(),recovery.check('passed')])
        got=self.check(m,recipe='recovery')
        self.assertEqual(got['summary']['row_statuses'],{'available':1})
        self.assertEqual(got['rows'][0]['measurement']['value'],1)
        self.assertEqual(got['summary']['opportunity_totals']['denominator'],1)
        self.assertIn('not established',got['validation']['detail'])

    def test_recovery_recipe_rejects_an_unrelated_measure(self):
        m,_=self.pair()
        with self.assertRaisesRegex(InputError,'does not implement'):self.check(m,recipe='recovery')
        options=readiness.options(self.store)
        self.assertEqual(options['monitors'][0]['recipes'],['selection'])

    def test_unknown_opportunity_counts_are_not_zero(self):
        self.source('a')
        got=self.check(recipe='recovery')
        self.assertEqual(got['summary']['opportunity_totals'],{'opportunities':None,'denominator':None,'unknown':None})

    def test_two_sides_in_different_splits_do_not_establish_a_comparison(self):
        for name,split,decision in [('a','train','admitted'),('b','evaluation','rejected')]:
            self.source(name);self.add(fixtures.record('sample',name,split=split),fixtures.record('selection',name,decision=decision))
        m=self.measure();monitoring.sync(self.store)
        f=training_lineage.snapshot(self.store)['selection_options'][0]['id']
        got=self.check(m,selection=f)
        self.assertEqual(got['selection']['cohorts_with_measured_sides'],0)
        self.assertEqual({c['cohort']['split'] for c in got['selection']['cohorts']},{'train','evaluation'})

    def test_incomplete_source_never_becomes_a_negative_measurement(self):
        self.source('a');self.add(fixtures.record('sample'));m=self.measure();monitoring.sync(self.store)
        with self.store.connect() as c:c.execute("UPDATE rollout_revisions SET state='in_progress'")
        got=self.check(m)
        self.assertEqual(got['summary']['row_statuses'],{'incomplete_source':1})
        self.assertIsNone(got['rows'][0]['measurement'].get('value'))

    def test_live_write_cannot_mix_two_database_snapshots(self):
        m,f=self.pair();original=training_lineage.snapshot
        def receive_after_read_snapshot(view, **kwargs):
            # The writer commits while the check's shared read transaction stays open.
            self.add(fixtures.record('score'))
            return original(view,**kwargs)
        with patch('tracker.investigation_readiness.training_lineage.snapshot', receive_after_read_snapshot):
            got=self.check(m,selection=f)
        self.assertEqual(got['training_health']['score_record_statuses'],{})
        self.assertEqual(self.check(m,selection=f)['training_health']['score_record_statuses'],{'scored':1})

    def test_explicit_scope_and_bounded_pages_are_required(self):
        self.pair()
        for update in [{'experiment':''},{'experiment':[]},{'recipe':[]},{'recipe':'unknown'},{'limit':True},
                       {'limit':101},{'offset':-1},{'selection':[]},{'recipe':'recovery','selection':'x'}]:
            with self.subTest(update=update), self.assertRaises(InputError):readiness.check(self.store,self.request(**update))

    def test_legacy_database_missing_training_schema_remains_read_only(self):
        self.source('a')
        with self.store.connect() as c:c.execute('DROP TABLE training_records')
        got=self.check(recipe='recovery')
        self.assertEqual(got['total_rows'],1)
        self.assertEqual(got['training_health']['capture_status'],'schema_unavailable')
        self.assertIsNone(got['training_health']['declared_samples'])
        with self.store.connect() as c:self.assertIsNone(c.execute("SELECT 1 FROM sqlite_master WHERE name='training_records'").fetchone())
        with self.assertRaisesRegex(InputError,'collector schema'):self.check(selection='missing-filter')


if __name__=='__main__': unittest.main()
