"""Category-conditioned extraction contracts, before identity or relationship inference.

These routes specify needed fields. A route is not an extraction, an empty field
is not an absent entity, and an activity tag does not establish its correctness.
"""
VERSION = 'activity-entity-contracts/7'

# role, intended analytical use, extraction mechanism
CONTRACTS = {
    'orient': [('objective','Track the stated task or subgoal','source_span'),('constraint','Preserve the stated boundary or requirement','source_span'),('situation','Separate current-state description from the objective','source_span')],
    'inspect': [('information_target','Identify what information is sought','source_span_or_tool_argument'),('query','Preserve the actual search/read request','source_span_or_tool_argument'),('source','Identify the named information source','source_span_or_tool_argument')],
    'reason': [('premise','Identify the propositions explicitly used','source_span'),('derived_claim','Identify what is inferred or computed','source_span')],
    'hypothesize': [('candidate_explanation','Keep possibilities separate from assertions','source_span'),('explained_phenomenon','Identify what the hypothesis would explain','source_span_or_prefix_candidate')],
    'plan': [('intended_operation','Capture announced work without inferring execution or plan structure','source_span'),('intended_target','Preserve the local target mention for later reference linking without asserting execution or existence','local_reference_mention'),('expressed_subgoal','Capture an explicitly named intermediate goal','source_span')],
    'construct': [('operation','Identify the attempted change or constructed content','source_span_or_tool_argument'),('target_artifact_or_state','Identify what is being changed or produced','source_span_or_tool_argument'),('proposed_change','Preserve the actual content or requested state change','source_span_or_tool_argument')],
    'verify': [('check_target','Identify the claim, artifact or state being checked','source_span_or_prefix_candidate'),('criterion','Identify the expressed acceptance rule','source_span'),('check_operation','Identify the attempted test or inspection','source_span_or_tool_argument')],
    'assess': [('feedback_referent','Identify the feedback being interpreted','source_span_or_prefix_candidate'),('assessment_claim','Preserve the interpretation as a claim','source_span')],
    'revise': [('prior_item_reference','Identify the explicitly referenced earlier item','source_span_or_prefix_candidate'),('replacement','Capture the new claim, approach or artifact proposal','source_span'),('stated_reason','Preserve an expressed reason if present','source_span')],
    'coordinate': [('requested_operation','Identify the work, answer or confirmation requested','source_span'),('addressee_mention','Identify the explicitly mentioned person asked to act','local_reference_mention'),('request_target','Identify the object or information involved','source_span_or_tool_argument')],
    'report': [('reported_content','Preserve the communicated answer, information, status or outcome','source_span'),('artifact_reference','Preserve a mentioned work artifact or transaction record','source_span_or_tool_argument'),('completion_claim','Capture an explicit completion statement without verifying it','source_span')]
}

# Local reference mentions precede reference resolution. A phrase such as
# "that result" can be extracted now; identifying the earlier result is L3.
CONTRACTS = {activity: [(role, purpose, 'local_reference_mention' if method == 'source_span_or_prefix_candidate' else method)
                       for role, purpose, method in fields] for activity, fields in CONTRACTS.items()}

# Specific contracts guide the bounded selection. Profiles constrain proposals,
# not the answer: missing/candidate-gap alternatives remain available.
FIELD_RULES = {
    'orient__objective': ('proposition', 'The task, desired outcome or subgoal stated as what is to be achieved. Do not infer an objective merely from an operation name or a result.'),
    'orient__constraint': ('proposition', 'An explicit requirement, restriction, invariant or boundary on acceptable work. A description of current state, a reason for a fix, or any statement containing need is not automatically a constraint.'),
    'orient__situation': ('proposition', 'An expressed description of the current task or environment state. Keep it separate from what the speaker intends to change or achieve.'),
    'inspect__information_target': ('mention', 'The entity, property or question whose information is sought. A query can express a question, but an arbitrary argument value is not necessarily the information target. Do not invent returned information from a tool name.'),
    'inspect__query': ('operation', 'The expressed search/read query or recorded retrieval invocation. Preserve it as requested, intended or dispatched. Do not require an actual answer or a successful retrieval.'),
    'inspect__source': ('mention', 'An explicitly identified origin or repository of information: a document, page, database, record, instrument or person being consulted. The property being sought, a query string or lookup key is not itself its information source. A tool may imply a source without naming it; do not invent the source identity.'),
    'reason__premise': ('premise', 'A proposition explicitly used as input or support for an inference, comparison or computation in this expression. Distinguish the input evidence from the conclusion. When a sentence says P which means Q, P is the premise; Q is the conclusion. A conclusion alone does not also express its premise. Do not judge truth or correctness.'),
    'reason__derived_claim': ('conclusion', 'The result of the expressed inference, comparison, computation or synthesis. When a sentence says P which means Q, extract Q, keeping its negation or modality. Do not extract the premise again or the whole sentence if a complete conclusion candidate is available. A reported fact alone does not prove derivation.'),
    'hypothesize__candidate_explanation': ('proposition', 'An explicitly proposed possibility, assumption or candidate explanation. Retain hypothetical language and attribution. A stated fact, a requested action, or a bare method is not automatically a hypothesis.'),
    'hypothesize__explained_phenomenon': ('mention', 'The local description or mention of what the proposed explanation would explain. A named object inside an explanation is not necessarily the phenomenon being explained.'),
    'assess__feedback_referent': ('mention', 'The explicitly mentioned feedback, observation or progress state whose significance is being assessed. A pronoun is suitable only when it plays this feedback-reference role locally; do not select an arbitrary object pronoun.'),
    'assess__assessment_claim': ('proposition', 'The interpretation of significance, quality or progress expressed about feedback or a state. Preserve whether it is prospective, conditional or uncertain. A raw result without interpretation is not an assessment; an assessment is still a claim.'),
    'revise__prior_item_reference': ('mention', 'A local mention of the earlier claim, plan, method or proposal being changed. It must play the replaced-item role in this expression. An entity mentioned within the new explanation is not the prior item. In a sentence describing a school because it has a property, it refers to the school, not a previous answer. If change is expressed but the prior item is only implicit, there is no explicit local prior-item mention yet.'),
    'revise__replacement': ('proposition', 'The newly adopted claim, method or proposal replacing an earlier one, as expressed here. Keep qualification and attribution. Do not invent an earlier position or treat every repeated statement as a replacement.'),
    'revise__stated_reason': ('premise', 'The explicitly stated justification for changing an earlier item. An explanatory fact is not automatically a reason for revision unless that change-justification role is expressed. Do not invent a reason from neighboring events.'),
    'report__reported_content': ('proposition', 'The information, answer, status, finding or outcome communicated in this Report expression. It need not be a final result. A label/value pair such as Cabin class: Business or Available at $20 communicates content despite lacking a full sentence. Preserve qualification and attribution; communicating it does not verify truth or completion.'),
    'report__artifact_reference': ('mention', 'A local reference to a work artifact or task transaction record: for example a document, patch, file, report or booking confirmation. It counts as a mention even when proposed, quoted or explicitly not created. Extracting it does not establish existence, ownership, creation or delivery; retain the enclosing expression. An ordinary answer value, Boolean, person/place name, product being discussed or feature of that product is not a work artifact just because it is mentioned.'),
    'report__completion_claim': ('proposition', 'An explicit statement that the requested task, subtask or artifact work is finished. A result value, a proposed next step or the end of a message is not itself a completion statement. This field records the claim without verifying completion.'),
    'coordinate__addressee_mention': ('mention', 'Extract words locally referring to the person asked to perform the requested act. You in Could you inspect is a local addressee mention even if identity is unknown. The beneficiary or destination of information differs: in Let me know, me receives the information and the requested actor has no local mention. Do not infer the current conversational user or use a possessive object as the actor.'),
    'coordinate__requested_operation': ('operation', 'Extract the requested act including necessary objects. A request is not execution. Preserve conditions on the request and who would perform it; do not replace the operation with a tool name alone.'),
    'coordinate__request_target': ('mention', 'Extract the object, artifact or information acted on or requested. Do not substitute the expected successful outcome for the object. If the required span is unavailable select no_suitable_candidate.'),
    'verify__check_operation': ('operation', 'For a recorded action_dispatch with this Verify route, the command or function invocation is the attempted operation even if it has no word test or verify. Extract the supplied recorded_operation. A known test purpose or passing result is not required to extract the dispatch. If this activity route is wrong, select route_not_applicable rather than denying the visible operation.'),
    'verify__check_target': ('mention', 'Extract the explicitly named item being checked, such as a script or local claim reference. Do not infer a hidden acceptance target from a command name or earlier context.'),
    'verify__criterion': ('proposition', 'Extract an explicit pass/fail or acceptance condition, not a tool name, argument, operation or hoped-for result. A dispatched command alone does not state an acceptance criterion.'),
    'construct__operation': ('operation', 'Extract the change operation or command, not the payload to insert. For recorded editor calls, use the operation header separately from its body.'),
    'construct__target_artifact_or_state': ('mention', 'Extract a named target artifact or state reference. An edit body is new content, not the target identity. A line range alone is not an artifact. When the active file is only implicit in prior context, the local artifact mention is not_present; later reference resolution is separate.'),
    'construct__proposed_change': ('content', 'Extract the replacement or constructed content, excluding command delimiters when a separate payload exists. A file name alone is the target, not replacement content. A request to create an empty file may express only an operation with no separate payload.'),
    'plan__intended_operation': ('operation', 'Extract the intended operation without asserting it was executed. Bare next-step intention is not proof of organized or high-level planning.'),
    'plan__intended_target': ('mention', 'A local mention of the object, artifact, entity, property or state that the announced operation would inspect, check, change, create or act on. A pronoun is an extractable mention even before its identity is known. Keep the target separate from the operation, a tool used solely as an instrument, replacement payload, and a purpose or hoped-for outcome. Do not infer a target from a tool name or earlier context. Preserve the enclosing intention and its conditions: a target mention does not establish existence, execution, success or organized planning. If several distinct targets cannot be represented by one supplied span, select multiple_spans_needed; if the needed local span is missing, select no_suitable_candidate.'),
    'plan__expressed_subgoal': ('purpose', 'Extract an explicit purpose or intermediate outcome, including purpose clauses such as to replicate the issue. A concrete intended operation alone is not automatically a distinct subgoal. Do not judge plan organization.'),
}


def field_rule(activity, role):
    key = activity+'__'+role
    return FIELD_RULES[key]


def route(unit):
    """Expose the actual next stage; never imply fields were extracted."""
    if not unit.get('eligible'):
        return {'version':VERSION,'next_stage':'supporting_source','routes':[],'extraction_status':'not_applicable'}
    if unit.get('annotation_status') in {'unobserved','stale',None}:
        return {'version':VERSION,'next_stage':'base_annotation','routes':[],'extraction_status':'not_started'}
    labels=unit.get('activities',[])
    routes=[{'activity':a,'fields':[{'role':role,'purpose':purpose,'method':method,
              'candidate_profile':field_rule(a,role)[0], 'definition':field_rule(a,role)[1],
              'status':'not_extracted','absence_policy':'Use no_local_expression only after inspecting this field locally. It does not establish an absent entity or role beyond this unit.'}
             for role,purpose,method in CONTRACTS[a]]} for a in labels if a in CONTRACTS]
    if routes:
        return {'version':VERSION,'next_stage':'category_entity_extraction','routes':routes,'extraction_status':'not_started',
                'boundary':'Multiple activities route independently. Every extracted field needs exact evidence and an explicit present/not_present/unresolved decision. Resolve cross-unit identity only after local fields exist.'}
    social=(unit.get('expression') or {}).get('value')=='non_propositional'
    return {'version':VERSION,'next_stage':'no_extraction_needed' if social else 'base_annotation_review','routes':[],
            'extraction_status':'not_applicable' if social else 'not_started'}
