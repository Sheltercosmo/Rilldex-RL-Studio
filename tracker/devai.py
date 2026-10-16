"""Import the published DevAI trajectory shape without executing its contents.

The publisher supplies a JSON array. Wrap it as
{trajectory_format: 'devai/1', trajectory: <original array>} for import.
Pointers retain the original array index under /trajectory.
"""
from .schema import InputError, event


def append_events(document, events):
    rows = document.get('trajectory')
    if not isinstance(rows, list) or not rows:
        raise InputError('DevAI trajectory must be a nonempty array')
    seen = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or type(row.get('step')) is not int or row['step'] in seen:
            raise InputError('DevAI steps need distinct integer identities')
        seen.add(row['step'])
        agent = row.get('agent')
        if not isinstance(agent, dict):
            raise InputError('DevAI step needs an agent object')
        base = f'/trajectory/{i}'
        for name, value in [('user_message', row.get('user_message')), ('thought', agent.get('thought')),
                            ('action', agent.get('action')), ('environment', row.get('environment'))]:
            if value is not None and not isinstance(value, str):
                raise InputError(f'DevAI {name} must be text or null')
        if row.get('user_message'):
            event(events, kind='instruction', actor='user', text=row['user_message'], pointer=base+'/user_message')
        expression = None
        if agent.get('thought'):
            expression = event(events, kind='reasoning', text=agent['thought'], pointer=base+'/agent/thought')
        dispatch = None
        if agent.get('action'):
            # The source has human-readable action descriptions, not native
            # structured tool arguments. Preserve that limit explicitly.
            dispatch = event(events, kind='action', text=agent['action'], pointer=base+'/agent/action',
                             tool='devai_recorded_action', arguments={}, arguments_available=False, call_id=f'devai-step-{row["step"]}',
                             parent_id=expression['id'] if expression else None,
                             source_action_format='publisher description; native arguments unavailable')
        if row.get('environment'):
            event(events, kind='feedback', actor='environment', text=row['environment'], pointer=base+'/environment',
                  source_call_id=dispatch['call_id'] if dispatch else None,
                  source_binding='publisher_step_pair' if dispatch else 'unbound')
