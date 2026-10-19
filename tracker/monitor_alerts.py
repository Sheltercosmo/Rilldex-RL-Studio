"""Read current, actionable monitor findings without running any detector."""
from urllib.parse import urlencode

from . import graph_store, monitoring
from .schema import digest


def snapshot(store, limit=100):
    with store.read_snapshot() as saved:
        runs = monitoring.population(saved)
        catalog = graph_store.catalog(saved)
        alerts = []
        with saved.connect() as c:
            dates = {r['id']: r['created_at'] for r in c.execute(
                'SELECT v.id,v.created_at FROM monitor_latest l JOIN monitor_values v ON v.id=l.value_id')}
        from .rollout_metrics import DIAGNOSTIC_DETECTORS
        diagnostic_metrics = {'diagnostic_' + key for key in DIAGNOSTIC_DETECTORS} | {'diagnostic_requirement_conflict'}
        for monitor in monitoring.definitions(saved):
            if not monitor['enabled']: continue
            reward = monitor.get('group') == 'Reward integrity'
            if not reward and monitor['kind'] != 'custom': continue
            selected = [r for r in runs if monitoring.in_population(monitor, r)]
            values = monitoring.current_values(saved, monitor, selected, catalog)
            for run in selected:
                value = values.get(run['id']) or {}
                if not value.get('id') or value.get('value') is None: continue
                feedback = value.get('feedback') or {}
                detector = (value.get('details') or {}).get('detector') or {}
                metric = monitor.get('metric')
                flagged = detector.get('status') == 'flagged' or (
                    metric in diagnostic_metrics and value['value'] == 1) or (
                    metric == 'reward_diagnostic_failure_observed' and value['value'] > 0)
                if not flagged and feedback.get('severity') not in {'warning', 'critical'}: continue
                params = dict(run=run['id'], observer=monitor['observer'], value=value['id'])
                meta = run['metadata']
                alerts.append(dict(id=value['id'], monitor_id=monitor['id'], run_id=run['id'],
                    title=monitor['name'], category='reward' if reward else 'monitor',
                    severity=feedback.get('severity', 'warning'),
                    summary=feedback.get('summary') or 'A saved check flagged this rollout. Open the evidence to inspect the action and context.',
                    task=meta.get('task_id') or run['id'], experiment=meta.get('experiment'),
                    environment=meta.get('environment'), created_at=dates.get(value['id']),
                    evidence_url='/semantic-map?' + urlencode(params),
                    monitor_url='/?' + urlencode(dict(monitor=monitor['id']))))
        alerts.sort(key=lambda row: (row['created_at'] or '', row['id']), reverse=True)
        return dict(workspace_id=digest(str(store.path.resolve()))[:24], alerts=alerts[:limit],
                    total=len(alerts), limit=limit, scope='Current findings from enabled monitors; flags are not confirmed reward hacking.')
