"""Evidence-backed adjacent-purpose sequences, without ordering tool batches."""
from collections import Counter

SEQUENCE_VERSION = "purpose-sequence/1"
DEFINITION = ("Adjacent actions in recorded order within one agent. Pairs touching a multi-action "
              "model expression are excluded because call enumeration does not establish execution order. "
              "Unresolved purposes remain explicit states; excluded or unknown work is never bridged. "
              "An observed transition is not evidence of causation or a response to feedback.")


def observe(actions):
    batch_sizes = Counter((a["trajectory_id"],a["parent_id"]) for a in actions if a.get("parent_id"))
    pairs, excluded, previous, possible = [], [], {}, 0
    for action in actions:
        actor = action["trajectory_id"]
        prior = previous.get(actor)
        previous[actor] = action
        if prior is None:
            continue
        possible += 1
        pair = {"from_event_id":prior["event_id"],"to_event_id":action["event_id"],
                "trajectory_id":actor,"source":prior["mode"],"target":action["mode"]}
        if any(a.get("parent_id") and batch_sizes[(actor,a["parent_id"])]>1 for a in (prior,action)):
            excluded.append({**pair,"reason":"Touches a multi-action model expression; execution order is unestablished"})
        else:
            pairs.append(pair)
    counts = Counter(p["source"]+"."+p["target"] for p in pairs)
    summary = {"version":SEQUENCE_VERSION,"possible_pairs":possible,"observed_pairs":len(pairs),
               "excluded_batch_pairs":len(excluded),"unresolved_pairs":sum("unresolved" in (p["source"],p["target"]) for p in pairs),
               "counts":dict(counts)}
    return {"summary":summary,"pairs":pairs,"excluded":excluded,"definition":DEFINITION}
