"""Experimental H1 clarification: distinguish a check from describing one.

This module does not activate a production harness on import. Both batched
candidates remain unpromoted after observed off-target differences; the isolated
candidate retains a retrieval/verification concern. Production stays at H1 1.4.
"""
from copy import deepcopy

HARNESS = "semantic-activity/1.5"
VERIFY_RULE = (
    "Performs a check of a claim, artifact, state or acceptance criterion in the subject itself, "
    "or initiates such a check through a recorded action dispatch. A check can be a comparison, "
    "substitution or consistency test carried out in model text; a tool is not required. "
    "An offer or ability statement, future plan, request for another actor to check, or report "
    "that a check occurred does not itself perform the described check. Merely mentioning a "
    "check or producing verification code does not run it. A subject that actually carries "
    "out a check may also express a plan, hypothesis, request or report. Classify the attempt "
    "independently of correctness, passing results or task success."
)
VERIFY_QUESTION = (
    "Does this subject itself perform or initiate a check, rather than only describe one? "
    + VERIFY_RULE + " Use the subject and supplied prefix to identify the checked claim/state "
    "and the checking operation. Do not transfer an operation from a different source unit "
    "into this subject. Other activities may coexist; judge this membership independently."
)
BOUNDARIES = (
    "Distinguish an operation performed by this subject from one it describes, offers or "
    "attributes to another actor. A capability statement or offer of help is not evidence "
    "that its described check, retrieval or mutation is attempted. Tag any actual planning, "
    "coordination, reporting or other expressed activity separately.",
    "Do not require a tool for Verify: an explicit comparison or substitution carried out "
    "in the subject's text can attempt a check. Conversely, a claim that a check happened "
    "or a piece of unexecuted checking code does not itself perform the check. Keywords or "
    "verb tense alone are not an activity rule."
)


def refine_verification(request):
    result = deepcopy(request)
    result["state"]["harness"] = HARNESS
    result["state"]["activity_definitions"]["verify"]["rule"] = VERIFY_RULE
    result["state"]["annotation_boundaries"].extend(
        rule for rule in BOUNDARIES if rule not in result["state"]["annotation_boundaries"])
    result["questions"]["verify"]["instructions"] = VERIFY_QUESTION
    return result


SCOPED_VERIFY_QUESTION = (
    VERIFY_QUESTION + " Identify a specific claim, expected state, acceptance criterion or "
    "consistency relation being tested. Merely retrieving an unknown value to learn it is "
    "Inspect, not Verify; the word 'check' alone does not establish a verification target. "
    "For a recorded dispatch, the target can be established by the supplied prefix. The "
    "checking result need not be available yet."
)


def refine_verification_question(request):
    """Keep other questions and their shared semantic definitions unchanged."""
    result = deepcopy(request)
    result["state"]["harness"] = HARNESS
    result["questions"]["verify"]["instructions"] = SCOPED_VERIFY_QUESTION
    return result


def isolated_verification_request(request):
    """Experimental independent decision; never substitutes for a whole H1 result."""
    result = deepcopy(request)
    result["state"]["harness"] = "activity-verify/0.1-experimental"
    result["questions"] = {"verify": {**result["questions"]["verify"], "instructions": VERIFY_QUESTION}}
    return result
