import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from tracker import findings_report as reports, failure_investigations as saved, monitoring
from tracker.schema import InputError
from rilldex import export_findings
import test_investigation_followups as fixture


class ReportTests(unittest.TestCase):
    setUp=fixture.FollowupTests.setUp
    source=fixture.FollowupTests.source
    packet=fixture.FollowupTests.packet
    add=fixture.FollowupTests.add
    setup_comparison=fixture.FollowupTests.setup_comparison
    run_fixture=fixture.FollowupTests.run_fixture
    base=fixture.FollowupTests.base
    plan=fixture.FollowupTests.plan
    finding=fixture.FollowupTests.finding

    def report_case(self,training=False):
        root=self.base(training=training);plan=self.plan(root)
        first=self.finding(plan,assessment='supports',conclusion='Initial evidence supports the recorded selection hypothesis',evidence=[{'kind':'investigation','id':root['id']}])
        last=self.finding(first,assessment='contradicts',conclusion='Counterevidence changes the interpretation',limitations='Small authored control cohort',next_action='Inspect another independent task',evidence=[{'kind':'investigation','id':root['id']}])
        return root,last

    def test_findings_counterevidence_history_and_saved_tables(self):
        root,doc=self.report_case()
        html=reports.render(self.store,doc['id'],origin='http://localhost:9999')
        for text in ('Counterevidence changes','Initial evidence supports','Previous findings (1)','Small authored control cohort',
                     'Inspect another independent task','Dispatched actions','Reported successes / known',root['id'],doc['id']):
            self.assertIn(text,html)
        self.assertNotIn('<script',html)
        self.assertIn('http://localhost:9999/investigate?saved=',html)
        self.assertIn("default-src 'none'",html)
        with patch('tracker.monitoring.sync',side_effect=AssertionError('Must not remeasure')):
            self.assertEqual(reports.render(self.store,doc['id'],origin='http://localhost:9999'),html)
        revised=self.finding(doc,conclusion='Later conclusion',evidence=[])
        self.assertNotIn('Later conclusion',reports.render(self.store,doc['id']))
        self.assertIn('Later conclusion',reports.render(self.store,revised['id']))

    def test_training_population_keeps_sample_and_rollout_grains(self):
        _,doc=self.report_case(training=True)
        html=reports.render(self.store,doc['id'])
        self.assertIn('selected training samples',html);self.assertIn('Declared samples',html)
        self.assertIn('Mean per measured rollout',html);self.assertIn('admitted',html)
        self.assertIn('No records',html)

    def test_escaping_origin_and_export(self):
        root=self.base();malicious=copy.deepcopy(root);malicious.pop('id')
        malicious['title']='</h1><script>alert("source")</script>'
        doc=saved.persist(self.store,malicious)
        html=reports.render(self.store,doc['id'])
        self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html)
        self.assertIn('No findings recorded',html)
        for origin in ('javascript:alert(1)','https://example.com/path','https://name:pass@example.com','//example.com'):
            with self.assertRaises(InputError):reports.render(self.store,doc['id'],origin=origin)
        with tempfile.TemporaryDirectory() as directory:
            dest=Path(directory)/'report.html'
            export_findings(self.store.path,doc['id'],dest)
            self.assertEqual(dest.read_text(encoding='utf-8'),html)
            with self.assertRaises(FileExistsError):export_findings(self.store.path,doc['id'],dest)

    def test_pinned_unit_quote_is_readable_offline(self):
        root=self.base();plan=self.plan(root)
        # A frozen node is already stored in a unit evidence attachment.
        from tracker.schema import digest
        doc=copy.deepcopy(plan);doc.pop('id')
        unit=dict(id='u-control',kind='unit',activity='Verify',properties={'source':{'quote':'The independent check failed.'}})
        ref=dict(kind='unit',id='control-ref',title='Verify delivery',unit=unit,graph_id='graph-frozen',run_id='run-frozen',observer='saved-observer',unit_id=unit['id'])
        finding=dict(id='finding-'+digest(ref),assessment='inconclusive',conclusion='Retained source excerpt',limitations='',next_action='',evidence=[ref])
        doc['follow_up']['checks'][0]['results'].append(finding);doc=saved.persist(self.store,doc)
        with patch('tracker.graph_store.read',side_effect=AssertionError('Unit evidence is already pinned')):
            html=reports.render(self.store,doc['id'],origin='http://localhost:9999')
        self.assertIn('<pre>The independent check failed.</pre>',html)
        self.assertIn('graph=graph-frozen',html)

    def test_case_nodes_include_direct_and_nested_explicit_ids_only(self):
        value=dict(action_id='a1',attempts=[dict(next_unit_id='u1',event_ids=['e1','e2'])],title='not-a-node',id='case-id')
        self.assertEqual(reports.referenced_ids(value),{'a1','u1','e1','e2'})
        ref=dict(kind='behavior_case',record=dict(graph_id='pinned',run_id='run',source_hash='source',case=value))
        graph=dict(id='pinned',run_id='run',source_hash='source',observer='test',nodes=[dict(id=i) for i in ['a1','u1','event:e1','event:e2','unrelated']])
        with patch('tracker.graph_store.read',return_value=graph):
            self.assertEqual(len(reports.evidence_context(self.store,ref)['nodes']),4)
        with patch('tracker.graph_store.read',side_effect=KeyError('pinned')):
            self.assertTrue(reports.evidence_context(self.store,ref)['missing'])


class IntervalReportTests(unittest.TestCase):
    def test_reward_patterns_and_saved_behavior_contrasts_are_included(self):
        import test_reward_investigations as reward_fixture
        from tracker import training_comparisons
        source=reward_fixture.RewardInvestigationTests();source.setUp();self.addCleanup(source.doCleanups)
        doc=source.prepare()
        comparison=training_comparisons.preview(source.store,dict(parent_id=doc['id'],spec=source.spec()))
        revised=training_comparisons.save(source.store,dict(parent_id=doc['id'],spec=source.spec(),preview_id=comparison['id']))
        html=reports.render(source.store,revised['id'])
        self.assertIn('Selected reward patterns',html);self.assertIn('Selected behavior comparison',html)
        self.assertIn('Response length',html);self.assertIn('paired scores',html)

    def test_late_arrivals_missing_measurements_and_clock_context(self):
        from test_investigation_workspace import InvestigationWorkspaceTests
        fixture=InvestigationWorkspaceTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.add(0);monitoring.sync(fixture.store);fixture.add(1,False)
        doc=fixture.capture();html=reports.render(fixture.store,doc['id'])
        self.assertIn('Unavailable · 0/1 rollouts measured',html)
        self.assertIn('policy',html);self.assertIn('generation',html)
        fixture.add(1,True);monitoring.sync(fixture.store)
        self.assertEqual(html,reports.render(fixture.store,doc['id']))


class ReportHTTPTests(unittest.TestCase):
    setUp=ReportTests.setUp
    source=ReportTests.source
    packet=ReportTests.packet
    add=ReportTests.add
    setup_comparison=ReportTests.setup_comparison
    run_fixture=ReportTests.run_fixture
    base=ReportTests.base
    plan=ReportTests.plan
    finding=ReportTests.finding
    report_case=ReportTests.report_case
    def test_report_http(self):
        from test_generation_cohort_transport import GenerationCohortTransportTests
        self.stop_server=GenerationCohortTransportTests.stop_server
        _,doc=self.report_case();self.db=self.store.path;endpoint=GenerationCohortTransportTests.start_server(self)
        with urlopen(endpoint+'/api/investigations/'+doc['id']+'/report?download=1') as response:
            self.assertIn('text/html',response.headers['Content-Type'])
            self.assertIn('attachment',response.headers['Content-Disposition'])
            self.assertIn('Counterevidence changes',response.read().decode())
        with urlopen(endpoint+'/api/investigations/'+doc['id']+'/bundle?download=1') as response:
            self.assertIn('rilldex-investigation.json',response.headers['Content-Disposition'])


if __name__=='__main__':unittest.main()
