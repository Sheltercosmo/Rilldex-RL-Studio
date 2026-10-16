"""Full base-activity vocabulary and explicit same-level boundaries.

One function of an established task/interaction unit; status, mechanism,
assessment and revision are not additional base labels.
"""
VERSION='behavioral-unit-standard/2'
HARNESS='base-unit-content/0.2'


def definitions(previous):
    result=dict(previous)
    result['orient'] += ' An explicit choice among alternatives belongs to Decide; mere mention of the next operation without such selection remains Orient.'
    result['hypothesize'] = ('Introduce a new tentative explanation, assumption or candidate solution for an unresolved question. The contribution is creating a possibility to examine, not asserting a known situation, committing to a choice, organizing a plan or deriving a supported conclusion. A known setup gap and its immediate needed correction remain Orient. Uncertainty words alone are insufficient.')
    result['reason'] += ' Stating an existing rule without applying/deriving it belongs to State knowledge. Reasoning used to check a specific earlier claim belongs to Verify at this activity level; calculation is then the check method. A brief rationale subordinate to an explicit choice remains within Decide.'
    result['verify'] += ' The check may be a tool operation or a substantive textual re-computation/counterexample. It must target an established claim/artifact/state, not merely derive new task content.'
    result['report'] += ' Being user-facing alone does not make substantive derivation, artifact creation or refusal into Report. Reserve Report for communicating a result/status or concise final answer rather than performing those other contributions.'
    result['knowledge']=('State existing knowledge: introduce a remembered or attributed rule, fact, definition or procedure without deriving it or externally retrieving it in this unit. Restating the recorded task/current state is Orient. Applying the rule to derive task-specific content is Reason. This label describes the expressed contribution, not proof of factual truth or a hidden memory process.')
    result['decide']=('Select, commit to or abandon an option among explicit or contextually established alternatives. A short rationale can belong to this same selection unit. Generating possible options is Hypothesize; organizing how to carry out a broader approach is Plan; announcing a next step with no choice among alternatives is Orient. Do not infer a decision from every action.')
    result['decline']=('Decline or abstain: refuse a requested action, set a boundary on the requested assistance, or explicitly withhold an answer/commitment because it cannot be responsibly supplied. Merely describing a task limitation or uncertainty without withholding the requested contribution is Orient or the relevant content activity. Politeness within a refusal does not create another Social unit.')
    result['social']=('Perform a greeting, thanks, apology, empathy, encouragement or conversational acknowledgement as the contribution of the unit. It is an interaction behavior even without task facts. A substantive request, refusal, commitment or task update with a polite phrase uses its substantive activity; politeness is not a second label.')
    # Put substantive choices together; fallbacks remain explicit and last.
    return {k:result[k] for k in ('orient','knowledge','plan','hypothesize','reason','decide','inspect','construct','verify','coordinate','report','decline','social','other','unresolved')}


def unit_options(previous):
    result=dict(previous)
    result['coherent_unit']=('The passage is one meaningful contribution to task work OR the interaction. Supporting context, rationale, immediate needed adjustment, purpose and polite wording can belong to one contribution. A pure greeting or acknowledgement is also a unit. It need not be one clause or verb.')
    result['not_behavior']=('Only formatting, an empty marker, unattributable quotation or a payload already represented by its dispatch occurs here. A greeting, thanks, apology, refusal or other interaction act is a behavior; do not exclude it simply because it contains no task facts.')
    return result


def fields(previous):
    result={k:dict(v) for k,v in previous.items()}
    result['knowledge']={'subject':'The concept, object or rule the stated knowledge concerns.',
                         'content':'The stated fact, rule, definition or procedure, preserving its attribution/qualification.'}
    result['decide']={'choice':'The option explicitly selected, committed to or abandoned.',
                      'basis':'The stated reason or criterion for the selection, if expressed locally.'}
    result['decline']={'withheld_work':'The requested work, answer or commitment that is refused or withheld.',
                       'reason_or_limit':'The stated reason, inability or boundary; do not invent an implicit policy.'}
    # A pure social act need not invent a target entity or useful extra field.
    result['orient']['purpose'] += ' Do not select an infinitive complement that merely restates the needed adjustment, such as needs to be reactivated; require an outcome distinct from doing that operation.'
    return result
