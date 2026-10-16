"""Source-recorded checkpoint measurements, separate from semantic observations.

Each metric is a per-episode numerator/denominator with an explicit unknown count.
Episodes are averaged within a task, then matched tasks receive equal weight.
This layer never turns source flags or model explanations into semantic labels.
"""
from collections import defaultdict
from statistics import mean
import random

from .schema import InputError, digest

VERSION = "source-checkpoint-study/1"
DRAWS = 2000


def score(records):
    eligible = [r for r in records if r["denominator"] > 0]
    if not eligible:
        return {"value": None, "lower": None, "upper": None, "eligible_episodes": 0,
                "episodes": len(records), "numerator": 0, "denominator": 0, "unknown": 0}
    lower = mean(r["numerator"] / r["denominator"] for r in eligible)
    upper = mean((r["numerator"] + r["unknown"]) / r["denominator"] for r in eligible)
    return {"value": lower if all(r["unknown"] == 0 for r in eligible) else None,
            "lower": lower, "upper": upper, "eligible_episodes": len(eligible), "episodes": len(records),
            **{k: sum(r[k] for r in eligible) for k in ("numerator", "denominator", "unknown")}}


def average_tasks(tasks):
    eligible = [t for t in tasks if t["lower"] is not None]
    return {"value": mean(t["value"] for t in eligible) if eligible and all(t["value"] is not None for t in eligible) else None,
            "lower": mean(t["lower"] for t in eligible) if eligible else None,
            "upper": mean(t["upper"] for t in eligible) if eligible else None,
            "tasks": len(eligible), "excluded_tasks": len(tasks) - len(eligible),
            **{k: sum(t[k] for t in tasks) for k in ("eligible_episodes", "episodes", "numerator", "denominator", "unknown")}}


def build(*, title, pack, checkpoints, episodes, metrics, provenance, limitations):
    """Internal import boundary; validate measurements before saving any study.

    Provenance is explicit adapter-supplied evidence, not independent authentication.
    Raw episode source is retained separately from the compact browser summaries.
    """
    if len(checkpoints) < 2 or len({c["id"] for c in checkpoints}) != len(checkpoints):
        raise InputError("A study requires at least two distinct checkpoints")
    if not metrics or any(m.get("unit") not in ("fraction", "count") for m in metrics.values()):
        raise InputError("Metric definitions need fraction or count units")
    contexts = {digest(c["recorded_context"]) for c in checkpoints}
    if len(contexts) != 1:
        raise InputError("Recorded evaluation contexts differ")
    ids, slots, grouped = set(), set(), defaultdict(lambda: defaultdict(list))
    for row in episodes:
        if row["checkpoint"] not in {c["id"] for c in checkpoints}:
            raise InputError("Unknown episode checkpoint")
        key = (row["checkpoint"], row["slot"])
        if key in slots or row["id"] in ids:
            raise InputError("Duplicate episode slot or identity")
        slots.add(key); ids.add(row["id"])
        if row.get("source_hash") != digest(row["raw"]):
            raise InputError("Episode raw source hash does not match")
        if set(row["metrics"]) != set(metrics):
            raise InputError("Episode metric definitions differ")
        for name, measure in row["metrics"].items():
            if set(measure) != {"numerator", "denominator", "unknown"} or any(type(v) is not int or v < 0 for v in measure.values()):
                raise InputError("Source metrics require nonnegative integer counts")
            n, d, u = (measure[k] for k in ("numerator", "denominator", "unknown"))
            if (not d and (n or u)) or (metrics[name]["unit"] == "fraction" and n + u > d):
                raise InputError("Metric numerator/unknown exceed their opportunity count")
            if metrics[name]["unit"] == "count" and (d != 1 or u):
                raise InputError("Count metrics require one episode denominator and no unknown count")
        grouped[row["checkpoint"]][row["task_id"]].append(row)
    if any(not grouped[c["id"]] for c in checkpoints):
        raise InputError("Every checkpoint needs episodes")
    # An evaluation slot can align only to the same recorded task and description.
    slot_context = {}
    task_context = {}
    for row in episodes:
        context = (row["task_id"], row["task"])
        if row["slot"] in slot_context and slot_context[row["slot"]] != context:
            raise InputError("Task identity differs at a recorded evaluation slot")
        if row["task_id"] in task_context and task_context[row["task_id"]] != row["task"]:
            raise InputError("Task description differs for one task identity")
        slot_context[row["slot"]] = context; task_context[row["task_id"]] = row["task"]
    cohorts = {}
    for cp in checkpoints:
        tasks = []
        for task_id, rows in sorted(grouped[cp["id"]].items()):
            tasks.append({"task_id": task_id, "task": rows[0]["task"],
                          "episodes": [{k: r[k] for k in ("id", "slot", "source", "metrics")} for r in sorted(rows, key=lambda r: r["slot"])],
                          "metrics": {key: score([r["metrics"][key] for r in rows]) for key in metrics}})
        cohorts[cp["id"]] = {"tasks": tasks, "metrics": {key: average_tasks([t["metrics"][key] for t in tasks]) for key in metrics},
                             "episode_weighted": {key: score([r["metrics"][key] for rows in grouped[cp["id"]].values() for r in rows]) for key in metrics}}
    study = {"version": VERSION, "title": title, "pack": pack, "checkpoints": checkpoints, "metrics": metrics,
             "provenance": provenance, "limitations": limitations, "cohorts": cohorts,
             "episode_hashes": {r["id"]: digest(r) for r in episodes},
             "definition": "Average episode rates within each game identity, then weight matched games equally. Source measurements only; no semantic inference.",
             "missingness_definition": "Bounds assign every unknown opportunity to absent or present. They assume known extraction labels are correct; they are not confidence intervals."}
    study["id"] = digest(study)[:24]
    return study


def compare(study, reference, checkpoint):
    if reference == checkpoint:
        raise InputError("Choose two different checkpoints")
    if reference not in study["cohorts"] or checkpoint not in study["cohorts"]:
        raise InputError("Unknown study checkpoint")
    left = {t["task_id"]: t for t in study["cohorts"][reference]["tasks"]}
    right = {t["task_id"]: t for t in study["cohorts"][checkpoint]["tasks"]}
    matched = sorted(left.keys() & right.keys())
    if not matched:
        raise InputError("No matched game identities")
    output = {"reference": reference, "checkpoint": checkpoint, "matched_tasks": len(matched),
              "excluded_before": sorted(left.keys() - right.keys()), "excluded_after": sorted(right.keys() - left.keys()),
              "metrics": {}, "tasks": [],
              "interval_method": "Pointwise paired game-cluster percentile bootstrap, 2,000 deterministic draws; minimum five games. Describes across-game variation only, not policy-seed, extraction or inspector uncertainty. No multiple-testing adjustment."}
    for key in study["metrics"]:
        eligible = [t for t in matched if left[t]["metrics"][key]["lower"] is not None and right[t]["metrics"][key]["lower"] is not None]
        before = average_tasks([left[t]["metrics"][key] for t in eligible])
        after = average_tasks([right[t]["metrics"][key] for t in eligible])
        delta = interval = bounds = None
        if eligible:
            bounds = [after["lower"] - before["upper"], after["upper"] - before["lower"]]
        if eligible and before["value"] is not None and after["value"] is not None:
            values = [right[t]["metrics"][key]["value"] - left[t]["metrics"][key]["value"] for t in eligible]
            delta = mean(values)
            if len(values) >= 5:
                rng = random.Random(int(digest({"study": study["id"], "reference": reference, "checkpoint": checkpoint, "tasks": eligible})[:16], 16))
                draws = sorted(sum(values[rng.randrange(len(values))] for _ in values) / len(values) for _ in range(DRAWS))
                interval = [draws[int(.025 * DRAWS)], draws[int(.975 * DRAWS) - 1]]
        output["metrics"][key] = {"before": before, "after": after, "delta": delta, "interval_95": interval,
                                   "missingness_delta_bounds": bounds, "excluded_tasks": len(matched) - len(eligible)}
    for tid in matched:
        output["tasks"].append({"task_id": tid, "task": left[tid]["task"], "before": left[tid], "after": right[tid]})
    output['study_id']=study['id']
    output['version']='source-comparison/2'
    output['comparison_id']=digest(output)
    return output
