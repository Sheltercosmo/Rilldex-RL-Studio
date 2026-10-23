"""Select and freeze producer reports without changing the original rollout."""
from collections import defaultdict
import json

from .schema import InputError


def selection(value):
    if not isinstance(value, dict) or set(value) != {'producer', 'label', 'purpose'}:
        raise InputError('Choose an evaluator producer, label and purpose')
    if any(not isinstance(v, str) or not v.strip() or len(v) > 240 for v in value.values()):
        raise InputError('Invalid evaluator selection')
    if value['purpose'] not in {'reward', 'independent_check', 'repair_check'}:
        raise InputError('Unknown evaluation purpose')
    return dict(value)


def records(store, run_ids, *, summaries=False):
    """Receipt ingestion binds the digest of each immutable run before saving."""
    result = defaultdict(list)
    ids = list(run_ids)
    with store.connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='evaluation_receipts'").fetchone():
            return result
        for offset in range(0, len(ids), 400):
            batch = ids[offset:offset+400]
            document = "json_object('producer',json_extract(e.document,'$.producer'),'label',json_extract(e.document,'$.label'),'purpose',json_extract(e.document,'$.purpose'))" if summaries else 'e.document'
            rows = c.execute('SELECT e.id,e.run_id,' + document + ' document FROM evaluation_receipts e JOIN runs r ON r.id=e.run_id '
                'WHERE e.run_id IN (' + ','.join('?' for _ in batch) + ') ORDER BY e.id', batch)
            for row in rows:
                result[row['run_id']].append(dict(id=row['id'], **json.loads(row['document'])))
    return result


def freeze(row, selected, reports):
    matched = [r for r in reports if all(r[k] == v for k, v in selected.items())]
    verdict = matched[0]['verdict'] if len(matched) == 1 and matched[0]['execution'] == 'completed' else 'unknown'
    status = 'missing' if not matched else 'multiple' if len(matched) > 1 else matched[0]['execution']
    return dict(row, comparison_outcome=dict(verified_success={'passed': True, 'failed': False}.get(verdict)),
                outcome_evaluation=dict(selection=selected, status=status, records=matched))


def outcome(row):
    return row.get('comparison_outcome', row.get('outcome', {}))
