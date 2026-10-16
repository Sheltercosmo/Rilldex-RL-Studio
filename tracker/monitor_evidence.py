"""Immutable measurement drilldowns. Never substitute the latest observer output.

These receipts establish computational lineage, not independent semantic accuracy.
Unknown graph relationships are retained as unestablished, never true negatives.
"""
import json
from .schema import InputError, digest
from . import graph_store
from .rollout_metrics import DEFINITIONS, metric_aggregation

VERSION='monitor-evidence/1'


def require(condition,message):
    if not condition:raise InputError(message)


def read(store,identifier,run_id=None):
    with store.read_snapshot() as saved:
        return _read(saved,identifier,run_id)


def _read(store,identifier,run_id=None):
    with store.connect() as c:
        row=c.execute('SELECT * FROM monitor_values WHERE id=?',(identifier,)).fetchone()
        if row is None:raise KeyError(identifier)
        value=json.loads(row['document'])
        require(identifier=='value-'+digest(value),'Saved measurement content does not match its identity')
        require(value['run_id']==row['run_id'] and value['monitor_id']==row['monitor_id'],'Saved measurement references do not match its index')
        if run_id is not None:require(run_id==value['run_id'],'Measurement belongs to a different rollout')
        definition=c.execute('SELECT * FROM monitors WHERE id=?',(value['monitor_id'],)).fetchone()
        if definition is None:raise InputError('Measurement definition is unavailable')
        monitor=json.loads(definition['document'])
        require(definition['id']=='monitor-'+digest(monitor),'Saved monitor content does not match its identity')
        raw=c.execute('SELECT document FROM runs WHERE id=?',(value['run_id'],)).fetchone()
        if raw is None:raise InputError('Measurement source is unavailable')
        run=json.loads(raw['document'])
        from .monitoring import in_population
        require(in_population(monitor,run),'Measurement source is outside the saved population')
        require(value['source_hash']==digest(run),'Measurement does not match this source snapshot')
        latest=c.execute('SELECT value_id FROM monitor_latest WHERE monitor_id=? AND run_id=?',(value['monitor_id'],value['run_id'])).fetchone()
        graph=None;input_record=None;analysis_explanation=None
        if monitor['kind']=='custom' and value.get('input_id'):
            record=c.execute('SELECT document FROM custom_monitor_inputs WHERE id=?',(value['input_id'],)).fetchone()
            require(record is not None,'Custom monitor input is unavailable')
            input_record=json.loads(record[0])
            require('custom-input-'+digest(input_record)==value['input_id'],'Custom input identity changed')
            require(input_record['monitor_id']==value['monitor_id'] and input_record['run_id']==run['id'] and input_record['source_hash']==value['source_hash'],'Custom input belongs to another monitor or source')
            require(all(value.get(k)==v for k,v in input_record['result'].items()),'Saved value differs from its custom input')
            graph=graph_store.read(store,input_record['graph_id'])
            require(value.get('graph_id')==graph['id'],'Custom measurement graph differs from its input')
            require(graph['run_id']==run['id'] and graph['source_hash']==value['source_hash'] and graph['observer']==monitor['observer'],'Custom graph does not match its source or observer')
        if monitor['kind']=='graph' and value.get('graph_id'):
            graph=graph_store.read(store,value['graph_id'])
            require(graph['run_id']==run['id'] and graph['source_hash']==value['source_hash'] and graph['observer']==monitor['observer'],
                    'Measurement graph does not match its rollout, source or observer')
            require(value['input_id']==graph['id'],'Measurement input identity does not match its graph')
        elif monitor['kind']=='metric' and value.get('input_id'):
            record=c.execute('SELECT document FROM rollout_measurements WHERE id=?',(value['input_id'],)).fetchone()
            if record is None:raise InputError('Saved metric input is unavailable')
            input_record=json.loads(record['document'])
            require(digest(input_record)==value['input_id'],'Saved metric input content does not match its identity')
            require(input_record['run_id']==run['id'] and input_record['source_hash']==value['source_hash'] and input_record['observer']==monitor['observer'],
                    'Metric input does not match its rollout, source or observer')
            if value['status']=='available':
                original=input_record.get('metrics',{}).get(monitor['metric'],{})
                require(all(value.get(k)==original.get(k) for k in ('value','numerator','denominator','evidence_ids')),'Saved value differs from its metric input')
            if input_record.get('graph_id'):
                graph=graph_store.read(store,input_record['graph_id'])
                require(graph['run_id']==run['id'] and graph['source_hash']==value['source_hash'] and graph['observer']==monitor['observer'],
                        'Bound metric graph does not match its rollout, source or observer')
            elif input_record.get('annotation_hash'):
                exact=c.execute('''SELECT id FROM rollout_graphs WHERE run_id=? AND observer=? AND source_hash=? AND annotation_hash=? ORDER BY created_at LIMIT 1''',
                                (run['id'],monitor['observer'],value['source_hash'],input_record['annotation_hash'])).fetchone()
                if exact:graph=graph_store.read(store,exact[0])
        if monitor['kind']=='analysis' and value.get('analysis'):
            from .analysis_metrics import receipt as analysis_receipt
            graph,input_record,analysis_explanation=analysis_receipt(store,value,monitor)
        if graph is None:
            source=c.execute("SELECT id FROM rollout_graphs WHERE run_id=? AND observer='source' AND source_hash=? ORDER BY created_at LIMIT 1",(run['id'],value['source_hash'])).fetchone()
            if source:graph=graph_store.read(store,source[0])
        # Immutable source values remain inspectable after a producer advances.
        revisions=c.execute('''SELECT run_id FROM rollout_revisions WHERE (producer,rollout_id) IN
            (SELECT producer,rollout_id FROM rollout_revisions WHERE run_id=?) AND revision=(
                SELECT max(r.revision) FROM rollout_revisions r WHERE r.producer=rollout_revisions.producer AND r.rollout_id=rollout_revisions.rollout_id)''',(run['id'],)).fetchall()
        current_source=not revisions or any(r['run_id']==run['id'] for r in revisions)
    if monitor['kind']=='analysis' and analysis_explanation is None:
        analysis_explanation={'definition':monitor['analysis_definition']['description'],'unit':monitor['analysis_definition']['unit'],
            'value':value['value'],'numerator':value.get('numerator'),'denominator':value.get('denominator'),'status':value['status'],
            'reason':value.get('reason'),'basis':'analysis_projection','cases':[],'analysis_cases':[], 'evidence_ids':[],
            'limitations':['No completed analysis projection is available for this value.']}
    if monitor['kind']=='custom':
        analysis_explanation={'definition':monitor['custom']['description'],'unit':monitor['custom']['unit'],
            'basis':'custom_code','value':value['value'],'numerator':value.get('numerator'),'denominator':value.get('denominator'),
            'status':value['status'],'reason':value.get('reason'),'cases':[],'evidence_ids':value.get('evidence_ids',[]),
            'feedback':value.get('feedback'),'details':value.get('details'),
            'limitations':['User code result. Source binding does not validate the computation or establish causality.']}
    explanation=analysis_explanation or explain(value,monitor,graph,input_record)
    from .analysis_metrics import definition_notice
    notice=definition_notice(monitor)
    if notice:explanation['definition_notice']=notice
    # Scalar transition rewards / flags are raw source facts, not graph nodes.
    # Resolve these pointers against this receipt's immutable source revision.
    explanation['source_values']=[]
    for pointer in explanation.get('evidence_ids',[]):
        if not isinstance(pointer,str) or not pointer.startswith('/'):continue
        item=run.get('raw')
        try:
            for token in pointer.split('/')[1:]:
                token=token.replace('~1','/').replace('~0','~')
                item=item[int(token)] if isinstance(item,list) else item[token]
        except (KeyError,IndexError,TypeError,ValueError):continue
        explanation['source_values'].append({'pointer':pointer,'value':item})
    review_graph_id = (value.get('analysis') or {}).get('input_graph_id') or (graph or {}).get('id')
    review_graph = graph_store.read(store,review_graph_id) if review_graph_id else None
    from .monitoring import population,observation_inputs,observation_binding
    current_run=next((r for r in population(store) if r['id']==run['id']),None)
    indexed_monitor={'id':definition['id'],**monitor}
    input_current=bool(current_run and observation_binding(indexed_monitor,current_run,observation_inputs(store,indexed_monitor))['input_hash']==value['input_hash'])
    return {'schema':VERSION,'measurement':{'id':identifier,**value,'created_at':row['created_at']},
            'review_context': {'graph_id':review_graph_id,'observer':review_graph['observer'],
                               'run_id':run['id'],'monitor_id':definition['id']} if review_graph else None,
            'monitor':{'id':definition['id'],**monitor,'enabled':bool(definition['enabled'])},
            'run':run,'graph':graph,'input_record':input_record,'explanation':explanation,
            'freshness':{'current_source':current_source,'current_input':input_current,'current_measurement':bool(latest and latest[0]==identifier and input_current),
                         'latest_value_id':latest[0] if latest else None},
            'integrity':'Source, definition and saved input identities checked; semantic accuracy is not established.'}


def explain(value,monitor,graph,input_record):
    common={'definition':DEFINITIONS[monitor['metric']][1] if monitor['kind']=='metric' else monitor['requirement']['question'],
            'value':value['value'],'numerator':value.get('numerator'),'denominator':value.get('denominator'),
            'evidence_ids':value.get('evidence_ids') or [],'status':value['status'],'reason':value.get('reason')}
    common['unit']='fraction' if monitor['kind']=='graph' or metric_aggregation(monitor['metric'])=='incidence' or monitor['metric'].endswith(('_rate','_fraction','_share','_coverage')) else 'value'
    if monitor['kind']=='metric':
        diagnostic=(input_record or {}).get('diagnostic_result')
        return {**common,'basis':'recorded_metric','cases':[],
                'source_refs':(input_record or {}).get('metrics',{}).get(monitor['metric'],{}).get('source_refs',[]),
                'retry_observation':(input_record or {}).get('retry_observation') if monitor['metric'] in {'changed_retry_completion_fraction','unchanged_retry_fraction','changed_retry_unknown_fraction'} else None,
                'revision_observation':(input_record or {}).get('revision_observation') if monitor['metric'].startswith('enacted_revision_') else (input_record or {}).get('linked_adjustment_observation') if monitor['metric'].startswith('linked_adjustment_') else None,
                'feedback_assessment':(input_record or {}).get('feedback_assessment') if monitor['metric'].startswith('feedback_assessment_') else None,
                'diagnostic':diagnostic.get('metrics',{}).get(monitor['metric'].removeprefix('diagnostic_')) if diagnostic else None,
                'limitations':[(input_record or {}).get('scope') or 'The measurement uses the saved input only.']}
    query=value.get('query')
    if not query:return {**common,'basis':'recorded_graph_matches','cases':[],'not_established':None,'behavior_negatives':None,
                         'behavior_rate':None,'limitations':['No completed graph query is available for this measurement.']}
    require(graph is not None and query['graph_id']==graph['id'],'Query evidence does not match the saved graph')
    require(query['requirement_hash']==digest(monitor['requirement']),'Query evidence does not match the saved definition')
    nodes={n['id']:n for n in graph['nodes']};edges={e['id']:e for e in graph['edges']};cases=[]
    for case in query['cases']:
        require(case['anchor'] in nodes and all(n in nodes for n in case['inspected_window']),'Query window contains unavailable units')
        witnesses=[]
        for match in case['matches']:
            e=edges.get(match['edge_id']);require(e is not None,'Query relationship is unavailable in the saved graph')
            require(e['source']==match['source'] and e['target']==match['target'],'Query relationship endpoints differ from the saved graph')
            edge_ids=list(dict.fromkeys([match['edge_id'],*match.get('evidence_links',[])]))
            require(all(i in edges for i in edge_ids),'Query witness is unavailable in the saved graph')
            path=match.get('evidence_path')
            if path:
                require(all(n in nodes for n in path['node_ids']),'Query path contains unavailable units')
                for t in path['traversals']:
                    link=edges.get(t['edge_id']);pair=(t['from'],t['to']) if t['direction']=='outgoing' else (t['to'],t['from'])
                    require(link is not None and (link['source'],link['target'])==pair,'Query path differs from its recorded edges')
            ids=list(dict.fromkeys([case['anchor'],match['source'],match['target'],*(path['node_ids'] if path else []),
                                    *[n for i in edge_ids for n in (edges[i]['source'],edges[i]['target'])]]))
            witnesses.append({**match,'node_ids':ids,'edge_ids':edge_ids})
        cases.append({'anchor':case['anchor'],'status':'recorded_match' if witnesses else 'not_established',
                      'inspected_window':case['inspected_window'],'window_size':len(case['inspected_window']),
                      'requested_window':monitor['requirement']['within_units'],'matches':witnesses})
    n=sum(bool(c['matches']) for c in cases);d=len(cases)
    require(len({c['anchor'] for c in cases})==d,'Query denominator contains duplicate anchors')
    require((n,d)==(value['numerator'],value['denominator']) and (n,d)==(query['matched_anchors'],query['anchors']),
            'Saved numerator or denominator differs from its contributing cases')
    expected=n/d if d else None
    require(query['recorded_match_fraction']==expected,'Saved graph fraction differs from its contributing cases')
    version=value.get('graph_monitor_version')
    require(version in {None,'recorded-relation-monitor/2'},'Unsupported saved graph-monitor projection')
    if version=='recorded-relation-monitor/2' and not n:
        expected=None
        require(value['status']=='unavailable','Unmeasured no-match window cannot be available')
    require(value['value']==expected,'Saved fraction differs from its contributing cases')
    return {**common,'basis':'recorded_graph_matches','cases':cases,'not_established':d-n,'behavior_negatives':None,
            'behavior_rate':None,'engine_version':query['engine_version'],'association':query['association'],
            'limitations':query['limitations']+([value['reason']] if version and not n and value.get('reason') else [])}
