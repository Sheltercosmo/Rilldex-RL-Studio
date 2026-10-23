"""Run exported investigation trials with an explicit local Python adapter."""
from copy import deepcopy
import json
import os
from pathlib import Path

from tracker.investigation_trials import jobs, receipt, compare
from tracker.schema import InputError, digest


class TrialStudy:
    """A bounded, restartable sequence; callback owns restoration and execution.

    Callback receives a job including ``prefix`` and returns status, metrics,
    applied settings and optional experiment/name. No callback is auto-loaded.
    """

    def __init__(self, manifest):
        self.manifest = deepcopy(manifest)
        if manifest.get('schema') != 'trial-handoff/1': raise InputError('Load an exported trial handoff')
        trial = manifest['trial']
        if trial['id'] != 'trial-' + digest({k:v for k,v in trial.items() if k != 'id'}):
            raise InputError('Trial design changed; export a new design')
        if manifest['jobs'] != list(jobs(trial)): raise InputError('Trial jobs differ from the pinned design')
        if digest(manifest['prefix']) != trial['source']['prefix_hash']: raise InputError('Trial prefix changed')

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    @classmethod
    def from_investigation(cls, database, investigation_id, check_id):
        from tracker.investigation_trials import manifest
        from tracker.store import Store
        return cls(manifest(Store(database), investigation_id, check_id))

    def run(self, adapter, *, output='trial-results.json', retry_failed=False):
        """Persist after every callback. Completed jobs are never rerun here.

        Interrupted callbacks have no receipt and can run again. Use job['id']
        as an idempotency key when dispatching external trainer jobs.
        """
        path = Path(output)
        design = self.manifest['trial']
        result = dict(schema='trial-results/1', trial_id=design['id'], check_id=self.manifest['check_id'], results=[])
        check = dict(trial=design, trial_results=[])
        previous = self.manifest.get('results', [])
        if path.exists():
            saved = json.loads(path.read_text(encoding='utf-8'))
            if saved.get('trial_id') != design['id'] or saved.get('check_id') != self.manifest['check_id']:
                raise InputError('Result file belongs to another trial; use a different output path')
            previous = [*previous, *saved['results']]
        for r in previous:
            normalized = receipt(None, check, {k:v for k,v in r.items() if k != 'id'})
            if not any(x['id'] == normalized['id'] for x in check['trial_results']): check['trial_results'].append(normalized)
        result['results'] = check['trial_results']
        latest = {r['job_id']: r for r in result['results']}
        for job in self.manifest['jobs']:
            prior = latest.get(job['id'])
            if prior and (not retry_failed or prior['status'] == 'completed'): continue
            request = deepcopy(job)
            request.update(prefix=deepcopy(self.manifest['prefix']), source=deepcopy(design['source']), measure=deepcopy(design['measure']))
            try:
                returned = adapter(request)
                if not isinstance(returned, dict): raise InputError('Adapter must return a result object')
                if 'job_id' in returned: raise InputError('Adapter must not override the job identity')
                record = receipt(None, check, dict(returned, job_id=job['id']))
            except Exception as error:
                record = receipt(None, check, dict(job_id=job['id'], status='error', note=(type(error).__name__ + ': ' + str(error))[:6000]))
            result['results'].append(record)
            result['comparison'] = compare(check)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.tmp')
            with temporary.open('w', encoding='utf-8') as handle:
                json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.flush(); os.fsync(handle.fileno())
            temporary.replace(path)
        result['comparison'] = compare(check)
        return result

    def record_results(self, database, result, *, investigation_id=None):
        """Attach receipts as a new saved revision without opening the UI."""
        from tracker import failure_investigations, investigation_followups
        from tracker.store import Store
        if (result.get('schema') != 'trial-results/1' or result.get('trial_id') != self.manifest['trial']['id']
                or result.get('check_id') != self.manifest['check_id']):
            raise InputError('Results belong to another trial')
        store = Store(database)
        parent = failure_investigations.read(store, investigation_id or self.manifest['investigation_id'])
        check = next((c for c in parent.get('follow_up', {}).get('checks', []) if c['id'] == self.manifest['check_id']), None)
        if not check or check.get('trial', {}).get('id') != self.manifest['trial']['id']:
            raise InputError('Trial design does not match the target investigation')
        return investigation_followups.save(store, dict(parent_id=parent['id'], action='trial_results',
            check=dict(id=check['id'], results=[{k:v for k,v in r.items() if k != 'id'} for r in result['results']])))

    def refresh_rollouts(self, database, *, investigation_id):
        """Pin newly arrived sources/maps in a new investigation revision."""
        from tracker.investigation_followups import save
        return save(self._target(database,investigation_id),dict(parent_id=investigation_id,action='trial_evidence',check=dict(id=self.manifest['check_id'])))

    def compare_behavior(self, database, *, investigation_id, arm, selection='paired', monitor_ids=None):
        """Save behavior evidence for the returned rollouts of a trial contrast."""
        from tracker.trial_rollouts import comparison
        return comparison(self._target(database,investigation_id),dict(investigation_id=investigation_id,check_id=self.manifest['check_id'],
            arm=arm,selection=selection,**({} if monitor_ids is None else dict(monitor_ids=monitor_ids))))

    def _target(self, database, investigation_id):
        from tracker.store import Store
        from tracker.failure_investigations import read
        from tracker.trial_rollouts import check_in
        store=Store(database)
        check=check_in(read(store,investigation_id),self.manifest['check_id'])
        if check['trial']['id']!=self.manifest['trial']['id']:raise InputError('Trial design does not match the target investigation')
        return store
