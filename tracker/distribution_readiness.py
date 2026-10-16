"""Source and annotation availability for behavior distributions.

One member per current observed rollout, independent of whether an annotation
exists. Availability is not semantic accuracy, applicability or job completion.
"""
from collections import Counter
from datetime import datetime
from statistics import median

from . import population_readiness

STATUSES = {
    'available': 'Current observation with opportunities',
    'no_opportunities': 'Current observation; no applicable opportunities',
    'not_observed': 'No saved observation',
    'source_mismatch': 'Observation belongs to another source version',
    'layer_unavailable': 'Saved graph has no usable input for this question',
    'source_in_progress': 'Source capture is still in progress',
    'source_failed': 'Source capture failed',
}
DELAY_BOUNDARY = ('Elapsed local time from source receipt to saving the selected observation input. '
                  'Includes import, queue and review delays; not model inference latency or training time.')


def delay(received, saved):
    try:
        a, b = (datetime.fromisoformat(v.replace('Z', '+00:00')) for v in (received, saved))
        if a.tzinfo is None or b.tzinfo is None:
            return None
        value = (b-a).total_seconds()
        return value if value >= 0 else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def members(runs, documents, graph_index, source_hashes, observer):
    docs = {d['run_id']: d for d in documents}
    result = []
    for r in runs:
        rid = r['id']; d = docs.get(rid); graph = graph_index.get((rid, observer))
        if r['state'] == 'in_progress': status = 'source_in_progress'
        elif r['state'] == 'failed': status = 'source_failed'
        elif d is not None: status = 'available' if d['records'] else 'no_opportunities'
        elif graph and graph['source_hash'] != source_hashes.get(rid): status = 'source_mismatch'
        elif graph: status = 'layer_unavailable'
        else: status = 'not_observed'
        meta = r['metadata']; step = meta.get('training_step')
        step = step if type(step) is int and step >= 0 and meta.get('experiment') else None
        saved = d.get('updated_at') if d is not None else None
        result.append(dict(run_id=rid, step=step, status=status, capture_state=r['state'],
            task_id=meta.get('task_id'), policy_version=meta.get('policy_version'),
            source_hash=source_hashes.get(rid), graph_id=d.get('graph_id') if d else None,
            saved_graph_id=graph['id'] if graph else None,
            agent_records=d.get('agent_records') if d else None,
            records_with_units=d.get('records_with_units') if d else None,
            source_received_at=r['imported_at'], observation_saved_at=saved,
            local_availability_delay_seconds=delay(r['imported_at'], saved) if saved else None))
    return sorted(result, key=lambda r: (r['step'] is None, r['step'] or 0, r['run_id']))


def summarize(rows):
    counts = Counter(r['status'] for r in rows)
    current = counts['available'] + counts['no_opportunities']
    delays = [r['local_availability_delay_seconds'] for r in rows
              if r['local_availability_delay_seconds'] is not None]
    selection = population_readiness.summarize([
        {**r, 'value': 1 if r['status'] == 'available' else None} for r in rows])['selection']
    record_rows=[r for r in rows if type(r.get('agent_records')) is int and type(r.get('records_with_units')) is int]
    records=sum(r['agent_records'] for r in record_rows)
    covered=sum(r['records_with_units'] for r in record_rows)
    return dict(population=len(rows), current=current, eligible=counts['available'],
        no_opportunities=counts['no_opportunities'], coverage=current/len(rows) if rows else None,
        statuses={k: counts[k] for k in STATUSES}, selection=selection,
        record_coverage=dict(inputs=len(record_rows), records=records, covered=covered,
            fraction=covered/records if records else None,
            definition='Agent records containing selected units, among current inputs with record counts. Not span completeness or semantic accuracy.'),
        delay=dict(available=len(delays), current=current, median_seconds=median(delays) if delays else None,
                   max_seconds=max(delays) if delays else None, definition=DELAY_BOUNDARY),
        boundary='Current imported sources only; unreported rollouts are unknown. Coverage is not semantic accuracy.')


def review(earlier, later):
    checks=[]
    for label, value in [('Earlier', earlier), ('Later', later)]:
        records=value['record_coverage']
        if records['fraction'] is not None and records['fraction']<1:
            checks.append(dict(code=label.lower()+'_partial_records',
                evidence=f"{label} window has selected units on {records['covered']}/{records['records']} agent records in {records['inputs']} current inputs.",
                next_check='Check which parts of each trace are annotated before interpreting activity shares. A current observation can still cover only part of a rollout.'))
        if value['current'] < value['population']:
            checks.append(dict(code=label.lower()+'_missing',
                evidence=f"{label} window has current observations for {value['current']}/{value['population']} imported rollouts.",
                next_check='Inspect missing inputs and revisit these same windows after annotation catch-up; do not count missing behavior as zero.'))
        for mix in value['selection']:
            if (mix['measured_mix_distance'] or 0)>0:
                checks.append(dict(code=label.lower()+'_'+mix['field']+'_selection',
                    evidence=f"{label} window uses different {mix['field'].replace('_',' ')} proportions among eligible and imported rollouts.",
                    next_check='Inspect the represented groups and compare within fixed task/policy strata. Equal annotation coverage does not establish equal selection.'))
    return checks
