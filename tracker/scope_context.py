"""Compare selected request versions at two dispatch cutoffs.

These are requested terms, not a queue of unfinished tasks or proof that the
agent is pursuing a record. Local annotation and work-history audits run before
this projection. Keep version identities so every summary can reopen its source.
"""
from .schema import InputError, digest


VERSION='requested-scope-comparison/1'


def build(run,document,before,after):
    work=document.get('requested_work')
    if not work or work.get('status')!='complete':
        return {'schema':VERSION,'available':False,
                'reason':'A complete selected requested-work history is unavailable.'}
    units={u['id']:u for u in document['units']}
    events={e['id']:e for e in run['events']}

    def position(unit):
        ref=unit['source'];return events[ref['event_id']]['index'],ref['start'],ref['end']

    def at_dispatch(unit,action):
        u,a=position(unit),position(action)
        return u[0]<a[0] or u[0]==a[0] and u[2]<=a[1]

    steps=[]
    for step in work['steps']:
        owner=units.get(step['unit_id'])
        if owner is None:raise InputError('Requested scope refers to a missing contribution')
        if owner['trajectory_id']!=after['trajectory_id']:continue
        if step['status'] not in {'selected_update','unchanged'}:raise InputError('Incomplete requested scope step')
        steps.append((owner,step))
    steps.sort(key=lambda item:position(item[0]))

    def snapshot(action):
        prior=[s for u,s in steps if at_dispatch(u,action)]
        last=prior[-1] if prior else None
        records=last['state_after'] if last else []
        if any(r['trajectory_id']!=action['trajectory_id'] for r in records):
            raise InputError('Cross-trajectory requested scope')
        return {'source_unit_id':last['unit_id'] if last else None,
                'record_versions':[{'record_id':r['id'],'version_id':r['version_id'],
                                    'kind':r['kind'],'status':r['status']} for r in records],
                'state_hash':digest(records)}

    previous,current=snapshot(before),snapshot(after)
    updates=[{'source_unit_id':s['unit_id'],
              'changes':[{'record_id':c['record_id'],'operation':c['operation'],
                          'before_version_id':c['before']['version_id'] if c['before'] else None,
                          'after_version_id':c['after']['version_id']} for c in s['changes']]}
             for u,s in steps if not at_dispatch(u,before) and at_dispatch(u,after) and s['changes']]
    return {'schema':VERSION,'available':True,'previous':previous,'current':current,
            'version_state_changed':previous['state_hash']!=current['state_hash'],
            'updates':updates,
            'limits':'Selected record-version changes only, including enrichment or clarification. '
                     'They do not independently establish a changed objective, active intention, '
                     'authorization validity, fulfillment or a cause of recurring work.'}
