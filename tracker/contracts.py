"""Versioned meaning and evidence requirements for the first macro investigations."""
from copy import deepcopy

CONTRACT_VERSION = "general-measurements/1"
CONTRACTS = {
    "work_sequence": {
        "question": "How does the agent allocate and sequence its work?",
        "decision": "Select task-matched trajectories to investigate a strategy change.",
        "unit": "Non-copied action; adjacent within-agent pair with established order.",
        "measures": {
            "purpose_share": "Count of a purpose / all eligible actions, including unresolved purposes.",
            "transition_share": "Count of a purpose pair / all eligible adjacent pairs, including unresolved endpoints.",
        },
        "evidence": ["Recorded action and actor", "Authorized objective and available prefix", "Pair ordering; multi-action expressions excluded from transitions"],
        "coverage": ["Unresolved actions", "Unresolved pairs", "Excluded ambiguous-order pairs", "Task and rollout support"],
        "interpretation": "Describes observable purpose and sequence, not optimal exploration/exploitation, hidden reasoning or strategy quality.",
        "reference": "Prefix-bounded purpose labels; full action coverage required for whole-rollout purpose and transition error.",
        "validation_status": "unvalidated",
    },
    "feedback_response": {
        "question": "What observable action follows feedback?",
        "decision": "Inspect persistence or approach changes after comparable feedback opportunities.",
        "unit": "Current action with feedback recorded before it for its immediately preceding same-agent action.",
        "measures": {"response_share": "Count of response class / all eligible linked-feedback opportunities; unresolved remains in the denominator."},
        "evidence": ["Previous action", "Corresponding feedback before the current action", "Current action and available prefix"],
        "coverage": ["Eligible feedback opportunities", "Missing or ambiguous links", "Unresolved responses", "No-opportunity rollouts"],
        "interpretation": "An observed response is not proof of causal adaptation, learning, unchanged environment state or progress.",
        "reference": "Human reviews eligibility as well as response; invalid extraction is reported separately from classification.",
        "validation_status": "unvalidated",
    },
    "verification_closure": {
        "question": "What checks and later work are recorded before the trajectory ends?",
        "decision": "Inspect differences in checking and stopping practice alongside independent outcomes.",
        "unit": "Recorded check action and linked result; complete within-agent action sequence for closure.",
        "measures": {
            "check_share": "Verify-purpose actions / all eligible actions; this is the verify component of purpose share, not an independent score.",
            "closure_sequence": "No check, application after last check, or no later application; unresolved when action purposes or ordering prevent this determination.",
        },
        "evidence": ["Check purpose", "Call/result correspondence", "Complete action order", "Separate producer termination, verifier and artifact evidence for stronger conclusions"],
        "coverage": ["Unresolved purposes", "Ambiguous order", "Missing check results", "Unrecorded artifact versions", "Incomplete trajectories"],
        "interpretation": "Does not establish test validity, verified task success, fresh verification or justified stopping.",
        "reference": "Derive closure from complete purpose references; compare exact check/result links separately. A sparse sample cannot establish absence of later work.",
        "validation_status": "unvalidated",
    },
}


def catalog():
    return {"version": CONTRACT_VERSION, "contracts": deepcopy(CONTRACTS),
            "runtime_support": "Each analyzed run includes measurement-evidence/1 availability, denominators and source-link coverage. Available evidence does not mean validated accuracy. Unsupported Jev questions are withheld before inference.",
            "aggregation": "Compute rollout rates, average within task, then give matched tasks equal weight. Keep no-opportunity cases distinct from zero.",
            "comparison_requirements": ["Compatible tasks, environment, budgets and sampling", "Recorded policy identity", "Same measurement version or a reviewed bridge on frozen data", "Coverage and measurement error reported beside change"],
            "promotion_gate": "A human reference benchmark and practical investigation must support each intended use. These definitions are not validation results."}
