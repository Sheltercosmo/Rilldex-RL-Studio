"""Compose local work adjustments with saved identity/action/outcome relations.

No semantic inference is made here. A recorded preparation link is not upgraded
to causation or a logically necessary prerequisite. Omitted links stay unknown.
"""
from copy import deepcopy
from .schema import InputError,digest
from .operation_outcomes import action_outcomes
from .local_adjustments import SUPPORTED as LOCAL_SUPPORTED, DECLARATION_VERSIONS, prospective
from .semantic_extraction import read
from pathlib import Path

VERSION='work-adjustment-graph/1'
DEFINITIONS={
 'linked_adjustment_completion_fraction':('Retry completion after linked adjustment attempts · experimental',
    'Completed retries / selected consecutive same-work retries with known terminal outcomes after visible failure and a later local adjustment with a saved action correspondence. That dispatch must be the retry itself or have a saved preparation link to work attempted by both endpoints. Preparation is not causation or a proven necessary prerequisite. No selected path is not absence of adaptation; completion is not verified task recovery.'),
 'linked_adjustment_unknown_fraction':('Unknown outcomes after linked adjustment attempts',
    'Retries without established terminal outcomes / all selected failure-adjustment-action-retry paths. Unknown outcomes are excluded from the completion fraction.')}


def build(run,document,work_document,local,history,actions,adjustments):
    source=digest(run)
    if document.get('source_hash')!=source or work_document.get('source_hash')!=source or digest(document['units'])!=digest(work_document['units']):
        raise InputError('Adjustment graph requires identical source units in both parent maps')
    if adjustments.get('schema') not in LOCAL_SUPPORTED or adjustments.get('source_hash')!=source or adjustments.get('base_map_hash')!=digest(work_document) or adjustments.get('work_items_hash')!=digest(local):
        raise InputError('Local adjustment dependencies differ')
    for value in (local,history,actions):
        if value.get('source_hash')!=source or value.get('base_map_hash')!=digest(work_document):raise InputError('Work graph source/base differs')
    if history['local_items_hash']!=digest(local) or actions['local_items_hash']!=digest(local) or actions['history_hash']!=digest(history):raise InputError('Work identity/action dependencies differ')
    units={u['id']:u for u in document['units']};events={e['id']:e for e in run['events']}
    selected_items={(r['unit_id'],i['id']):i for r in local['observations'] for i in r['items']}
    def order(uid):
        ref=units[uid]['source'];return events[ref['event_id']]['index'],ref['start']
    entries={};uninspected=[]
    for row in adjustments['observations']:
        if row['status']!='selected':
            if row['status']!='no_selected_work_items':uninspected.append(row['unit_id'])
            continue
        for item in row['items']:
            key=(row['unit_id'],item['item_id']);original=selected_items.get(key)
            if original is None or original['work']!=item['work']:raise InputError('Unknown or altered local work object')
            if adjustments['schema'] in DECLARATION_VERSIONS and original['declaration']!=item.get('declaration'):
                raise InputError('Adjustment facet changed the selected declaration')
            if key in entries:raise InputError('Duplicate local adjustment')
            entries[key]={'unit_id':key[0],**deepcopy(item),'request_hash':row['request_hash'],
                'id':'adjustment-'+digest({'unit':key[0],'item':key[1],'request':row['request_hash']})[:24]}
    attempts={};preparations={};bindings={};edges=[]
    for relation in actions['relations']:
        a,b=units[relation['from']],units[relation['to']]
        if a['kind']!='action' or a['actor']!='agent' or a['trajectory_id']!=b['trajectory_id']:raise InputError('Invalid saved work-action link')
        if order(a['id'])<=order(b['id']):raise InputError('Work-action correspondence points to a future declaration')
        if relation['type']=='attempts_declared_work':
            attempts.setdefault(a['id'],set()).add(relation['declared_work_id'])
            key=(b['id'],relation['to_item_id']);item=entries.get(key)
            if item and prospective(item):
                bindings.setdefault(key,[]).append(relation)
                edges.append({'from':a['id'],'to':b['id'],'type':'attempts_local_adjustment',
                    'work_item_id':key[1],'work_text':item['work'],'adjustment_id':item['id'],
                    'basis':'composition of saved local adjustment and exact work-item/action correspondence',
                    'harness':VERSION,'local_request_hash':item['request_hash'],'action_request_hash':relation['request'],
                    'evidence':[deepcopy(a['source']),*deepcopy(item['evidence'])],
                    'cutoff':deepcopy(a['source']),'explanation':'A dispatched attempt corresponds to this stated adjustment. Its success remains a separate observation.'})
        elif relation['type']=='prepares_declared_work':preparations.setdefault(a['id'],[]).append(relation)
    outcomes=action_outcomes(run,document['operation_outcomes']);episodes=[];excluded=[];seen=set()
    for pair in document.get('method_comparison',{}).get('observations',[]):
        aid,bid=pair['previous_unit_id'],pair['current_unit_id'];a,b=units[aid],units[bid]
        old,new=outcomes.get(a['source']['event_id'],{}),outcomes.get(b['source']['event_id'],{})
        if old.get('outcome')!='failed':continue
        if (aid,bid) in seen:raise InputError('Duplicate retry pair')
        seen.add((aid,bid))
        if pair.get('status')!='selected' or pair.get('work_instance')!='same_work_instance' or pair.get('upstream_identity_disputed'):
            excluded.append({'pair':[aid,bid],'reason':'Same-work relation unresolved/disputed'});continue
        feedback=[events[o['response_event_id']] for o in old['observations']]
        if not feedback or a['trajectory_id']!=b['trajectory_id'] or any(e['trajectory_id']!=a['trajectory_id'] for e in feedback):raise InputError('Failure feedback scope differs')
        fail_end=max((e['index'],len(e['text'])) for e in feedback)
        common=attempts.get(aid,set())&attempts.get(bid,set());matches=[]
        for key,relations in bindings.items():
            item=entries[key];statement=units[key[0]]
            if statement['trajectory_id']!=b['trajectory_id'] or not fail_end<order(key[0])<order(bid):continue
            for relation in relations:
                enactor=relation['from']
                if not fail_end<order(enactor)<=order(bid):continue
                preparation=[r for r in preparations.get(enactor,[]) if r['declared_work_id'] in common]
                if enactor!=bid and not preparation:continue
                match={'declaration_unit_id':key[0],'item_id':key[1],'adjustment_id':item['id'],'work':item['work'],
                    'execution_unit_id':enactor,'scope':'retry_dispatch' if enactor==bid else 'preparation_for_shared_work',
                    'local_request_hash':item['request_hash'],'action_relation':deepcopy(relation),
                    'preparation_relations':deepcopy(preparation),'shared_work_ids':sorted(common)}
                matches.append(match)
                edges.append({'from':key[0],'to':aid,'type':'adjustment_before_retry',
                    'work_item_id':key[1],'work_text':item['work'],'scope':match['scope'],'via_action':enactor,
                    'retry_unit_id':bid,'basis':'recorded graph composition, not a new semantic judgment',
                    'harness':VERSION,'proof':deepcopy(match),'method_request_hash':pair['request'],
                    'evidence':[deepcopy(a['source']),*deepcopy(item['evidence']),deepcopy(units[enactor]['source'])],
                    'cutoff':deepcopy(b['source']),
                    'explanation':'This adjustment was attempted after visible failure, on the next retry or in recorded preparation for the shared work. It does not establish causation or recovery.'})
        if not matches:
            excluded.append({'pair':[aid,bid],'reason':'No selected local-adjustment/action path; absence of a path is not absence of adaptation'});continue
        evidence=list(dict.fromkeys([aid,bid,*[e['id'] for e in feedback],
            *[i for m in matches for i in (m['declaration_unit_id'],m['execution_unit_id'])],
            *[o['response_event_id'] for o in new.get('observations',[])]]))
        episodes.append({'failed_unit_id':aid,'retry_unit_id':bid,'failed_event_id':a['source']['event_id'],
            'retry_event_id':b['source']['event_id'],'retry_outcome':new.get('outcome','not_established'),
            'changes':matches,'evidence_ids':evidence})
    known=[e for e in episodes if e['retry_outcome'] in {'completed','failed','partial'}]
    def ratio(n,rows):return {'numerator':n,'denominator':len(rows),'evidence':list(dict.fromkeys(i for e in rows for i in e['evidence_ids']))}
    return {'schema':VERSION,'source_hash':source,'base_map_hash':digest(document),
        'dependencies':{'work_items':digest(local),'work_history':digest(history),'work_actions':digest(actions),'local_adjustments':digest(adjustments)},
        'objects':list(entries.values()),'uninspected_units':uninspected,'relations':edges,'episodes':episodes,
        'excluded_failed_pairs':excluded,'metrics':{
            'linked_adjustment_completion_fraction':ratio(sum(e['retry_outcome']=='completed' for e in known),known),
            'linked_adjustment_unknown_fraction':ratio(len(episodes)-len(known),episodes)},
        'scope':'Saved local work adjustments composed with saved action/work identities and terminal operation outcomes. Incomplete graph paths remain unknown; preparation does not establish causation or necessity.'}


def project(run,bundle,result):
    if result['schema']!=VERSION or result['source_hash']!=digest(run) or result['base_map_hash']!=digest(bundle['document']):raise InputError('Adjustment graph projection differs')
    out=deepcopy(bundle);d=out['document'];d['adjustment_graph']=deepcopy(result)
    d['relations'].extend(deepcopy(result['relations']))
    for unit in d['units']:unit['work_adjustments']=[deepcopy(o) for o in result['objects'] if o['unit_id']==unit['id']]
    return out


def load(run,bundle,adjustment_directory,work_directory,*,include_work_graph=False,reference_directory=None):
    from . import work_item_pass,declared_work_history,declared_work_actions,local_adjustments
    _,work_run,work_document=work_item_pass.load(work_directory)
    if digest(work_run)!=digest(run):raise InputError('Local adjustment workspace belongs to another source')
    root=Path(work_directory);local=read(root/'complete.json');history=read(root/'history.json');actions=read(root/'action-correspondence.json')
    observed=read(Path(adjustment_directory)/'local-adjustments.json')
    validation={'work_items':work_item_pass.audit(run,work_document,local,root),
        'history':declared_work_history.audit(run,work_document,local,history,root),
        'actions':declared_work_actions.audit(run,work_document,local,history,actions,root),
        'local_adjustments':local_adjustments.audit(run,work_document,local,observed,adjustment_directory)}
    result=build(run,bundle['document'],work_document,local,history,actions,observed)
    out=project(run,bundle,result);out['validation']['adjustment_graph']=validation
    if reference_directory:
        from . import adjustment_references
        references=read(Path(reference_directory)/'adjustment-references.json')
        validation['references']=adjustment_references.audit(run,work_document,local,history,actions,observed,references,reference_directory)
        out['document']['adjustment_references']=references
        out['document']['relations'].extend(deepcopy(references['relations']))
    for note in out['document'].get('review_notes',[]):
        note.setdefault('review_scope','Inherited review · before this local-adjustment extension')
    if include_work_graph:
        document=out['document']
        document['declared_work_items']=deepcopy(local)
        document['declared_work_history']=deepcopy(history)
        document['declared_work_actions']=deepcopy(actions)
        seen={digest(r) for r in document['relations']}
        for relation in [*history['relations'],*actions['relations']]:
            key=digest(relation)
            if key not in seen:document['relations'].append(deepcopy(relation));seen.add(key)
        history_review=root/'history-review.json'
        if history_review.exists():
            reviewed=read(history_review)
            validation['history_reviews']=declared_work_history.validate_reviews(run,work_document,history,reviewed)
            document.setdefault('review_notes',[]).extend({**deepcopy(note),'review_scope':'Work identity review'} for note in reviewed['notes'])
    for path,hash_key,expected in [(root/'action-review.json','observation_hash',digest(actions)),
            (Path(adjustment_directory)/'source-review.json','observation_hash',digest(observed))]:
        if path.exists():
            notes=read(path)
            if notes.get(hash_key)!=expected:raise InputError('Adjustment review dependencies differ')
            scope='Work/action correspondence review' if expected==digest(actions) else 'Current local-adjustment review'
            out['document'].setdefault('review_notes',[]).extend({**deepcopy(note),'review_scope':scope} for note in notes['notes'])
    return out


def register(store,work_directory,adjustment_directory,label,*,reference_directory=None):
    """Publish one audited snapshot through the existing observer registry."""
    from . import work_item_pass,semantic_catalog
    from .schema import dumps
    if not isinstance(label,str) or not label.strip() or len(label)>160:raise InputError('Use an observer label of 1–160 characters')
    with work_item_pass.exclusive(work_directory) as work:
        with work_item_pass.exclusive(adjustment_directory) as adjustment:
            config,run,document=work_item_pass.load(work)
            parent=semantic_catalog.load(run,config['parent_observer'],store)
            if not parent.get('available') or digest(parent['document'])!=digest(document):raise InputError('The frozen parent observation changed')
            if not document.get('operation_outcomes'):raise InputError('Graph composition requires selected operation outcomes')
            selected=load(run,parent,adjustment,work,include_work_graph=True,reference_directory=reference_directory)
            definition={k:str(v) if isinstance(v,Path) else v for k,v in semantic_catalog.profile(config['parent_observer'],store).items()}
            definition.update(label=label.strip(),run_id=run['id'],source_hash=digest(run),
                local_adjustment_directory=str(adjustment.resolve()),adjustment_work_directory=str(work.resolve()),
                adjustment_work_links=True,
                local_adjustment_map_hash=digest(selected['document']))
            if reference_directory:definition['adjustment_reference_directory']=str(Path(reference_directory).resolve())
            key='saved-'+digest(definition)[:24]
            with store.connect() as c:c.execute('INSERT OR IGNORE INTO semantic_observers VALUES (?,?)',(key,dumps(definition)))
    return {'observer':key,'run_id':run['id'],'validation':selected['validation']['adjustment_graph'],
        'url':'/semantic-map?run='+run['id']+'&observer='+key}
