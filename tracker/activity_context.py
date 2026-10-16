"""Audit exact normalized text supplied to H1, independently of Jev selection.

This measures source coverage, not relevance, semantic sufficiency or accuracy.
No request, selected option, gate or stored observation is changed.
"""
from collections import defaultdict
from copy import deepcopy

VERSION = "activity-context-coverage/1"
SUPPORTED_HARNESSES = {"semantic-activity/1.4"}
TEXT_PACKET_SCHEMA = "activity-text-packet/1"
SECTIONS = ("authorized_instructions", "earlier_units", "prior_environment_or_harness_context")


def visible_prefix(run, subject):
    result = []
    for event in run["events"]:
        if (event["trajectory_id"] != subject["trajectory_id"] or event["index"] > subject["event_index"]
                or event["kind"].startswith("external_")):
            continue
        kept = {k: deepcopy(event[k]) for k in ("id", "index", "actor", "kind", "text", "source_pointer", "trajectory_id",
                "copied_context", "tool", "arguments", "parent_id", "source_call_id", "tool_contract", "media") if k in event}
        if event["id"] == subject["event_id"]:
            kept["text"] = event["text"][:subject["end"]]
            kept["cutoff_codepoint"] = subject["end"]
        result.append(kept)
    return result


def merge_ranges(ranges):
    result = []
    for start, end in sorted(ranges):
        if start == end:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def audit(prefix, state, subject, *, packet_schema=None):
    base = {"version": VERSION,
            "definition": "Union of exact Unicode-code-point spans supplied from the normalized visible prefix, including the subject. Overlapping excerpts count once. Copied context is excluded from the source denominator.",
            "limits": ["Text coverage does not establish relevance, context sufficiency or semantic accuracy.",
                       "This audits normalized text, not raw-source extraction, unread media or serialized tool-contract coverage.",
                       "Repeated content in different events remains separate. A source-span omission does not prove that its information is absent elsewhere.",
                       "These findings do not modify Jev's argmax choice or the scored observation."]}
    if not state or (state.get("harness") not in SUPPORTED_HARNESSES and packet_schema != TEXT_PACKET_SCHEMA):
        return {**base, "status": "unavailable", "reason": "No supported exact inspector packet is available."}
    if state.get("cutoff_event_id") != subject["event_id"] or state.get("cutoff_codepoint") != subject["end"]:
        return {**base, "status": "unavailable", "reason": "Inspector cutoff differs from the source subject."}
    by_id = {e["id"]: e for e in prefix}
    if len(by_id) != len(prefix) or any(e["index"] > subject["event_index"] or e["trajectory_id"] != subject["trajectory_id"] or e["kind"].startswith("external_") for e in prefix):
        return {**base, "status": "unavailable", "reason": "Source prefix contains ambiguous, future or out-of-scope events."}
    current = by_id.get(subject["event_id"])
    if not current or len(current["text"]) != subject["end"] or current["text"][subject["start"]:] != subject["text"]:
        return {**base, "status": "unavailable", "reason": "Subject text does not match the exact source prefix."}
    intervals, locations = defaultdict(list), defaultdict(list)
    errors = []
    supplied = [("subject", state.get("subject"))]
    for section in SECTIONS:
        items = state.get(section)
        if not isinstance(items, list):
            errors.append({"location": section, "reason": "Expected a supplied evidence list."})
            continue
        supplied.extend((f"{section}[{i}]", item) for i,item in enumerate(items))
    for location, item in supplied:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            errors.append({"location":location,"reason":"Missing textual evidence item."}); continue
        event_id = item.get("event_id", item.get("id"))
        event = by_id.get(event_id)
        if event is None:
            errors.append({"location":location,"reason":"Supplied source is outside the visible prefix."}); continue
        if ("actor" in item and item["actor"] != event["actor"] or item.get("trajectory_id") != event["trajectory_id"]
                or item.get("source_pointer") != event["source_pointer"]):
            errors.append({"location":location,"reason":"Supplied actor or source pointer differs from the source event."}); continue
        start, end = item.get("start",0), item.get("end",len(event["text"]))
        if (type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(event["text"])
                or len(item["text"]) > end-start):
            errors.append({"location":location,"reason":"Supplied source span is outside its recorded boundaries."}); continue
        actual_end = start + len(item["text"])
        if event["text"][start:actual_end] != item["text"]:
            errors.append({"location":location,"reason":"Supplied text does not match its source span."}); continue
        intervals[event_id].append([start,actual_end]); locations[event_id].append(location)
    events, excluded = [], []
    for event in prefix:
        if event.get("copied_context"):
            excluded.append(event["id"]); continue
        spans = merge_ranges(intervals[event["id"]]); length = len(event["text"])
        cursor, omitted = 0, []
        for start,end in spans:
            if start > cursor: omitted.append([cursor,start])
            cursor = end
        if cursor < length: omitted.append([cursor,length])
        sent = sum(end-start for start,end in spans)
        events.append({"event_id":event["id"],"source_kind":event["kind"],"actor":event["actor"],
                       "source_pointer":event["source_pointer"],"available_characters":length,"supplied_characters":sent,
                       "omitted_characters":length-sent,"supplied_ranges":spans,"omitted_ranges":omitted,
                       "packet_locations":locations[event["id"]],
                       "status":"empty_source" if not length else "omitted" if not sent else "complete" if sent==length else "partial"})
    def counts(rows):
        return {"available_events":len(rows),"available_characters":sum(r["available_characters"] for r in rows),
                "supplied_characters":sum(r["supplied_characters"] for r in rows),"omitted_characters":sum(r["omitted_characters"] for r in rows),
                **{status+"_events":sum(r["status"]==status for r in rows) for status in ("complete","partial","omitted","empty_source")}}
    return {**base,"status":"binding_issues" if errors else "audited","summary":counts(events),
            "by_source_kind":{kind:counts([e for e in events if e["source_kind"]==kind]) for kind in sorted({e["source_kind"] for e in events})},
            "events":events,"binding_issues":errors,"excluded_copied_context_event_ids":excluded,
            "counting_basis":"Only source-validated excerpt spans are counted. If bindings fail, supplied counts are partial, not complete packet coverage."}
