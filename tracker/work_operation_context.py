"""Reuse the existing operation observer when judging a named work scope."""
from . import operation_outcomes as operations, execution_reports
from .response_material import DELIVERY
from .schema import InputError


def inspect(run, pair, decide, mechanisms):
    action=pair['dispatch'];response=pair['response']
    if action['id'] not in mechanisms:
        ma,mkey=decide(operations.mechanism_request(run,action))
        if set(ma)!={'mechanism'} or ma['mechanism']['value'] not in DELIVERY:
            raise InputError('Invalid work-context operation mechanism')
        mechanisms[action['id']]={'value':ma['mechanism']['value'],'request_hash':mkey}
    mechanism=mechanisms[action['id']]
    ra,rkey=decide(execution_reports.request(run,action,response))
    if set(ra)!={'error','warning'} or any(v['value'] not in {'reported','not_reported','unresolved'} for v in ra.values()):
        raise InputError('Invalid work-context executor report')
    req=operations.request(run,action,response,mechanism['value'],ra['error']['value'])
    oa,okey=decide(req)
    if set(oa)!={'outcome'} or oa['outcome']['value'] not in req['questions']['outcome']['criteria']:
        raise InputError('Invalid work-context operation outcome')
    value=next(k for k in operations.OUTCOMES if oa['outcome']['value']==k+'_'+mechanism['value'])
    return {'schema':operations.VERSION,'mechanism':mechanism,
            'outcome':value,'selected_option':oa['outcome']['value'],'outcome_request_hash':okey,
            'executor_report':{k:v['value'] for k,v in ra.items()},'executor_report_request_hash':rkey,
            'complete_readable_response':operations.complete_view(req['state']['response']),
            'limits':operations.LIMITS}
