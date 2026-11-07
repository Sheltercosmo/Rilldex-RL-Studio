"""Source-complete action distributions from compatible saved reader decisions."""
from collections import Counter
from urllib.parse import urlencode

from .action_reading import _snapshot, _status
from .jev import JevClient, JEV_HARNESS
from .observe import analyze
from .schema import digest
from .store import current_macro_observations

VERSION = 'action-distribution/1'
LENSES = {
    'action_purpose': {'label':'Action purpose', 'grain':'recorded agent actions',
        'question':'How does the agent use its actions across training?',
        'limit':'Immediate purpose of each dispatched action, using one reader model and protocol plus saved reviews. Unread, outdated and unresolved actions remain unknown. Shares describe action counts, not time, tokens, successful progress or an RL exploration–exploitation policy.'},
    'task_connection': {'label':'Task connection', 'grain':'recorded agent actions',
        'question':'How does the connection between actions and requested work change?',
        'limit':'Saved action relationships to the recorded task, using one reader model and protocol plus saved reviews. Unknowns remain in the denominator. Outside or conflicting work is a reading to inspect, not a confirmed plan deviation or reward hack.'},
}
FIELDS = {'action_purpose':'mode', 'task_connection':'goal_relation'}
CATEGORIES = {
    'action_purpose': [('explore','Gather information'),('apply','Apply approach'),('verify','Check results'),
                       ('coordinate','Coordinate'),('report','Report'),('unknown','Unknown purpose')],
    'task_connection': [('direct','Direct task work'),('supporting','Supporting work'),('outside','Outside recorded task'),
                        ('conflicting','Conflicts with a requirement'),('unknown','Task connection unknown')],
}
COLORS = {'action_purpose':['#536eb9','#238f84','#648850','#9165a5','#617082','#b9bdc8'],
          'task_connection':['#238f84','#536eb9','#b88751','#b35668','#b9bdc8']}


def comparison_url(run):
    from .behavior_distributions import cohort
    metadata = run['metadata']
    return '/?'+urlencode({'view':'strategies','lens':'action_purpose',
        'experiment':metadata.get('experiment') or '__unassigned__',
        **({'environment':metadata['environment']} if metadata.get('environment') else {}),
        'cohort_id':'cohort-'+digest(cohort(metadata,run['id']))})


def inputs(store, lens, run_ids=None):
    """Keep model populations separate; never convert command heuristics to labels."""
    field = FIELDS[lens]; allowed = {k for k, _ in CATEGORIES[lens]} - {'unknown'}
    with store.connect() as connection:
        runs = [r[0] for r in connection.execute('SELECT id FROM runs') if run_ids is None or r[0] in run_ids]
        models = {r[0] for r in connection.execute('SELECT DISTINCT model FROM observations WHERE harness=?', (JEV_HARNESS,))}
        models.add(JevClient().model)
        sources = {r['run_id']: dict(r) for r in connection.execute("SELECT id,run_id,source_hash FROM rollout_graphs WHERE observer='source' ORDER BY rowid")}
    documents = []
    for run_id in runs:
        run, _, history, reviews = _snapshot(store, run_id)
        relevant_reviews = [r for r in reviews if r.get('field') == field]
        if not history and not relevant_reviews: continue
        events = {e['id']:e for e in run['events']}
        source = sources.get(run_id)
        if not source or source['source_hash'] != digest(run): continue
        run_models = {r['model'] for r in history if r['model'] in models}
        if not run_models and relevant_reviews:run_models.add(JevClient().model)
        for model in sorted(run_models):
            selected_history = [r for r in history if r['model'] == model]
            inspected_ids = {r['event_id'] for r in selected_history}
            observed = current_macro_observations(run, selected_history, reviews)
            records = []; counts = Counter(); current_fields = 0
            for action in analyze(run, observed)['actions']:
                if action.get('actor') != 'agent': continue
                eid = action['event_id']; reading = observed.get(eid, {}); semantic = action['semantic']
                value = semantic.get(field, {})
                status = _status(reading, {field:value}, eid in inspected_ids)
                # A compatible reading or a review of this field supplies an input,
                # even if its chosen answer is unresolved. Other fields cannot.
                has_input = value.get('source') == 'review' or (status == 'current' and bool(value))
                current_fields += has_input
                category = value['value'] if has_input and value.get('status')=='decided' and value.get('value') in allowed else 'unknown'
                if field == 'goal_relation' and action['macro']['goal_scope']['value']=='unresolved': category = 'unknown'
                counts[status] += 1
                counts['decided'] += category != 'unknown'
                records.append({'id':eid, 'event_id':eid, 'category':category, 'text':action['text'],
                    'label':((action.get('tool')+' · ') if action.get('tool') else '')+action['text'][:180]+('…' if len(action['text'])>180 else ''),
                    'status':status, 'reading':value, 'reader':reading.get('_provenance') if not reading.get('_outdated_observation') else None,
                    'source_pointer':events[eid]['source_pointer'],
                    'map_url':'/semantic-map?'+urlencode({'run':run_id,'observer':'source','graph':source['id'],
                        'level':'units','focus_unit':'event:'+eid,'action_reading':'1'})})
            if not current_fields: continue
            profile = {'model':model, 'harness':JEV_HARNESS, 'reviews':'latest-field-review'}
            value = {'schema':VERSION, 'run_id':run_id, 'source_hash':source['source_hash'], 'graph_id':source['id'],
                'observer':'action-reader-'+digest(profile), 'observer_label':model+' · '+JEV_HARNESS, 'reader_profile':profile,
                'records':records, 'reading_coverage':{'actions':len(records),'inspected':current_fields,
                    **{k:counts[k] for k in ('current','reviewed','outdated','uninspected','decided')}},
                'updated_at':max([r['created_at'] for r in selected_history]+[r['created_at'] for r in reviews]+[''])}
            documents.append({**value,'input_id':'action-distribution-input-'+digest(value)})
    return documents
