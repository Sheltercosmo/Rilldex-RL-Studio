import json
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
import unittest

from tracker import monitor_alerts, monitoring
from tracker.workspace_analysis import Workspace
import test_reward_detectors as rewards
import test_monitor_current_queries as queries


class MonitorAlertsTests(unittest.TestCase):
    setUp = rewards.RewardDetectorTests.setUp
    add = rewards.RewardDetectorTests.add
    detector = rewards.RewardDetectorTests.detector
    check = staticmethod(rewards.RewardDetectorTests.check)
    start_server = rewards.RewardDetectorTests.start_server
    stop_server = staticmethod(rewards.RewardDetectorTests.stop_server)

    def test_current_custom_findings_pause_and_read_only_feed(self):
        self.add('bad'); self.add('good', passed=True); self.add('missing', complete=False)
        monitor = self.detector(); monitor.run(self.check)
        before = monitoring.fingerprint(self.store)
        data = monitor_alerts.snapshot(self.store)
        self.assertEqual(data['total'], 1)
        row = data['alerts'][0]
        self.assertEqual(row['run_id'], 'run-bad')
        self.assertEqual(row['category'], 'reward')
        self.assertEqual(row['summary'], 'Compared recorded check')
        self.assertEqual(parse_qs(urlparse(row['evidence_url']).query)['value'], [row['id']])
        self.assertEqual(monitor_alerts.snapshot(self.store), data)
        self.assertEqual(monitoring.fingerprint(self.store), before)
        monitoring.enabled(self.store, monitor.id, False)
        self.assertEqual(monitor_alerts.snapshot(self.store)['total'], 0)

    def test_critical_custom_feedback_and_bounded_feed(self):
        self.add('bad'); self.add('good', passed=True)
        monitor = Workspace(self.db, observer='source').monitor('Evaluation service', version='1', description='Worker feedback')
        monitor.run(lambda ctx: dict(value=1, feedback=dict(severity='critical', summary='Evaluator unavailable')))
        data = monitor_alerts.snapshot(self.store, limit=1)
        self.assertEqual(data['total'], 2)
        self.assertEqual(len(data['alerts']), 1)
        self.assertEqual(data['alerts'][0]['category'], 'monitor')

    def test_http_route_and_packaged_client(self):
        self.add('bad'); self.detector().run(self.check)
        base = self.start_server()
        with urlopen(base+'/api/monitoring/alerts') as response:
            self.assertEqual(json.load(response)['total'], 1)
        with urlopen(base+'/workspace-alerts.js') as response:
            self.assertIn(b'WorkspaceAlerts', response.read())


class AlertFreshnessTests(unittest.TestCase):
    setUp = queries.CurrentMonitorQueriesTests.setUp
    graph = queries.CurrentMonitorQueriesTests.graph

    def test_stale_graph_result_is_not_an_alert(self):
        monitor = self.workspace.monitor('Critical', version='1', description='Controlled feedback')
        monitor.run(lambda ctx: dict(value=1, feedback=dict(severity='critical', summary='A finding')))
        self.assertEqual(monitor_alerts.snapshot(self.store)['total'], 1)
        self.graph('new')
        self.assertEqual(monitor_alerts.snapshot(self.store)['total'], 0)
