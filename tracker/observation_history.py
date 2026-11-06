"""Reuse exact saved readings; keep incomplete and obsolete records inspectable."""
from collections import defaultdict
from .schema import InputError


def by_subject(records):
    history = defaultdict(list)
    for record in records:
        history[record['event_id']].append(record['result'])
    return history


def select(history, run, subject, factory, *, partial=None):
    """Use the newest compatible profile, preferring its completed reading.

    The factory only constructs a client; matching never calls its transport.
    Returning an obsolete fallback preserves existing stale-state presentations.
    """
    # With one record there is no selection to make. The consuming projection
    # still validates it, including whether a partial reading is usable.
    if len(history) < 2:
        return history[0] if history else None
    pending, profile = None, None
    for saved in reversed(history):
        try:
            p = saved.get('_provenance', {})
            identity = (p.get('model'), p.get('harness'), p.get('selection_policy'))
            if not p.get('model') or profile is not None and identity != profile:
                continue
            client = factory(p['model'])
            if client.cache_matches(saved, run, subject):
                return saved
            if partial and pending is None and getattr(client, partial)(saved, run, subject):
                pending, profile = saved, identity
        except (InputError, KeyError):
            continue
    return pending if pending is not None else history[-1]
