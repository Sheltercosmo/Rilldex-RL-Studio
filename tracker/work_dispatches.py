"""Count recorded action identities without merging their annotation witnesses.

Exact native bindings share a dispatch ID. If a binding is unavailable, keep
the original action identity; equal text, targets or timestamps cannot merge it.
"""


def identity(row):
    return row.get('dispatch_id') or row['action_id']


def identities(rows):
    return {identity(row) for row in rows}


def counts(rows):
    rows = tuple(rows)
    return dict(actions=len(identities(rows)),
        attempts=len(identities(r for r in rows if 'attempts_plan_step' in r['roles'])),
        preparations=len(identities(r for r in rows if 'prepares_plan_step' in r['roles'])),
        checks=len(identities(r for r in rows if 'checks_plan_step' in r['roles'])),
        with_feedback=len(identities(r for r in rows if r['responses'])),
        with_assessment=len(identities(r for r in rows if any(v['assessments'] for v in r['responses']))))


def retry_counts(cases):
    cases = tuple(cases)
    return dict(repeated_attempts=len(identities(cases)),
        after_reported_error=len(identities(c for c in cases if c['after_reported_error'])))
