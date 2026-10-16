"""Pinned optional stages after base extraction; no heuristic activity relabeling."""
from pathlib import Path
from .schema import InputError, digest
from .semantic_extraction import read

LEGACY_FEEDBACK_PROFILE='feedback-references/1'
FEEDBACK_PROFILE='feedback-references/2'
REQUESTED_PROFILE='requested-conditions/1'


def requested_profile(value,include_user=True):
    if value is not None and (not isinstance(value,str) or value!=REQUESTED_PROFILE):
        raise InputError('Unknown requested conditions profile; use requested-conditions/1 or omit it')
    if value is not None and include_user is not True:
        raise InputError('Requested conditions require user contributions; omit agent-only')
    return value


def requested_provider(directory,command=None,producer=None,budget=None,citation_format=None,cache_directories=()):
    from .requested_work import FileCandidates,CommandCandidates
    root=Path(directory)/'work_candidates'
    if command:
        return CommandCandidates(root,command,producer,execution_budget=budget,
            citation_format=citation_format,cache_directories=cache_directories)
    return FileCandidates(root,cache_directories=cache_directories)


def requested_status(directory,extraction,value,policy):
    if requested_profile(value) is None:return {'profile':None,'status':'not_requested'}
    if not extraction or extraction.get('status')!='complete_local_extraction':
        return {'profile':value,'status':'waiting_for_base'}
    from .requested_work import path_for,CLAUSE_VERSION,user_units
    path=path_for(directory,extraction)
    pending={'profile':value,'status':'pending','eligible_user_contributions':len(user_units(extraction))}
    if not path.exists():return pending
    saved=read(path)
    if (saved.get('extraction_hash')!=digest(extraction) or saved.get('schema')!=CLAUSE_VERSION
            or saved.get('context_policy')!=policy or saved.get('status')!='complete'):
        raise InputError('Requested conditions differ from their base extraction or pinned profile')
    return {**pending,'status':'saved','records':len(saved['records']),
        'clauses':sum(len(r.get('clauses',[])) for r in saved['records']),
        'note':'Requested terms and checks; fulfillment is not established.'}


def execute_requested(run,extraction,engine,provider,value,policy):
    if requested_profile(value) is None:return None
    from .requested_work import execute,CLAUSE_VERSION
    result=execute(run,extraction,provider,engine,policy,CLAUSE_VERSION)
    return {'profile':value,'status':result['status'],'reviewed_contributions':len(result['steps'])}


def audit_requested(run,extraction,directory,value,policy):
    if requested_profile(value) is None:return None
    from .requested_work import path_for,audit
    if requested_status(directory,extraction,value,policy)['status']!='saved':
        raise InputError('Requested conditions layer is incomplete; resume before publishing this observer')
    return {'profile':value,**audit(run,extraction,read(path_for(directory,extraction)),directory)}


def profile(value):
    if value is not None and (not isinstance(value,str) or value not in {LEGACY_FEEDBACK_PROFILE,FEEDBACK_PROFILE}):
        raise InputError('Unknown feedback profile; use feedback-references/2 or omit it. Version 1 remains available for exact legacy replay.')
    return value


def feedback_protocol(value):
    if profile(value) is None:return None
    from . import feedback_assessments as feedback
    from .feedback_retrieval import CONTEXT_VERSION,HYBRID_VERSION
    return {'dependency_scope':feedback.DEPENDENCY_SCOPE,
        'evidence_layout':feedback.INLINE_EVIDENCE,'reference_rule':feedback.DIRECT_SET_RULE,
        'linkage_version':feedback.SOURCE_LINKAGE,'retrieval_version':HYBRID_VERSION if value==LEGACY_FEEDBACK_PROFILE else CONTEXT_VERSION,
        'scope_version':feedback.CONTRIBUTION_SCOPE}


def feedback_status(directory, extraction, value):
    protocol=feedback_protocol(value)
    if protocol is None:return {'profile':None,'status':'not_requested'}
    if not extraction or extraction.get('status')!='complete_local_extraction':
        return {'profile':value,'status':'waiting_for_base'}
    from .feedback_assessments import path_for
    path=path_for(directory,extraction,**protocol)
    if not path.exists():return {'profile':value,'status':'pending'}
    saved=read(path)
    if saved.get('extraction_hash')!=digest(extraction) or any(saved.get(k)!=v for k,v in protocol.items()):
        raise InputError('Feedback layer differs from its base extraction or pinned profile')
    return {'profile':value,'status':'saved','observed_contributions':len(saved['observations']),
        'linked_contributions':sum(r['status']=='linked' for r in saved['observations']),
        'relations':len(saved['relations']),
        'note':'Saved observations, not a semantic accuracy or complete negative-coverage claim.'}


def execute_feedback(run, extraction, engine, value):
    protocol=feedback_protocol(value)
    if protocol is None:return None
    from .feedback_assessments import execute
    # One shared engine means exact decisions resume without repeated inference;
    # the caller owns persistent accounting and the publication transaction.
    _,validation=execute(run,extraction,engine,**{k:v for k,v in protocol.items() if k!='dependency_scope'})
    return {'profile':value,'protocol':protocol,**validation}


def audit_feedback(run, extraction, directory, value):
    protocol=feedback_protocol(value)
    if protocol is None:return None
    from .feedback_assessments import path_for,audit
    path=path_for(directory,extraction,**protocol)
    if not path.exists():raise InputError('Feedback layer is incomplete; resume before publishing this observer')
    saved=read(path)
    if any(saved.get(k)!=v for k,v in protocol.items()):
        raise InputError('Feedback layer differs from its pinned profile')
    return {'profile':value,'protocol':protocol,**audit(run,extraction,saved,directory)}
