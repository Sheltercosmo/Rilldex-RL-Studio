"""Evidence-backed adjacent-purpose sequences, without ordering tool batches."""
from collections import Counter
from .capabilities import recorded_scope
from .work_order import Evidence as OrderEvidence

SEQUENCE_VERSION = "purpose-sequence/3"
DEFINITION = ("Adjacent actions in recorded order within one trajectory and recorded context. Pairs touching a multi-action "
              "model expression or explicitly unknown source order are excluded because call enumeration does not establish execution order. "
              "Unresolved purposes remain explicit states; excluded or unknown work is never bridged. "
              "An observed transition is not evidence of causation or a response to feedback.")


def observe(actions):
    # Older callers provide an already ordered list without native indices.
    # Do not manufacture a source index in that case.
    if all(type(a.get('index')) is int for a in actions):
        actions = sorted(actions, key=lambda a:a['index'])
    ordering = OrderEvidence({a['event_id']:{**a,'kind':'action'} for a in actions})
    pairs, excluded, previous, possible = [], [], {}, 0
    for action in actions:
        actor = recorded_scope(action)
        prior = previous.get(actor)
        previous[actor] = action
        if prior is None:
            continue
        possible += 1
        pair = {"from_event_id":prior["event_id"],"to_event_id":action["event_id"],
                "trajectory_id":action["trajectory_id"],"context_id":action.get("context_id"),"source":prior["mode"],"target":action["mode"]}
        if any(not ordering.is_ordered(a['event_id']) for a in (prior,action)):
            batch = any(len(ordering.groups[a['event_id']])>1 or (a.get('batch_size') or 0)>1 for a in (prior,action))
            excluded.append({**pair,"reason":"Touches a multi-action model expression; execution order is unestablished" if batch else
                "Source order is explicitly unknown; display position does not establish a transition",
                "order_basis":"parallel_expression" if batch else "unknown_source_order"})
        else:
            pairs.append(pair)
    counts = Counter(p["source"]+"."+p["target"] for p in pairs)
    summary = {"version":SEQUENCE_VERSION,"possible_pairs":possible,"observed_pairs":len(pairs),
               "excluded_order_pairs":len(excluded),
               "excluded_batch_pairs":sum(p['order_basis']=='parallel_expression' for p in excluded),
               "unresolved_pairs":sum("unresolved" in (p["source"],p["target"]) for p in pairs),
               "counts":dict(counts)}
    return {"summary":summary,"pairs":pairs,"excluded":excluded,"definition":DEFINITION}
