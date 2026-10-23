"""Saved work-content extraction progress on exact graph/unit identities.

The worker owns model calls and cached receipts. These records make its current
result accessible to the map and SQL without promoting generated work to graph
edges, executions or measured behavior rates.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode

from . import graph_store, work_mentions, work_content_bindings as scopes
from .schema import InputError, digest, dumps

VERSION='work-content-result/1'
TABLE='work_content_extractions'


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS work_content_extractions (
      id TEXT PRIMARY KEY, graph_id TEXT NOT NULL, run_id TEXT NOT NULL,
      unit_id TEXT NOT NULL, revision TEXT NOT NULL, document TEXT NOT NULL,
      workspace TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      FOREIGN KEY(graph_id,unit_id) REFERENCES graph_nodes(graph_id,id))''')
    c.execute('CREATE INDEX IF NOT EXISTS work_content_by_unit ON work_content_extractions(graph_id,unit_id,updated_at)')


def present(c):
    return c.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',('table',TABLE)).fetchone() is not None


def view(packet, result, *, syntax=None):
    """Reconstruct display data from exact bound contents and decision receipts."""
    if len(packet.get('units',[]))!=1 or result.get('unit_id')!=packet['units'][0]['unit_id']:
        raise InputError('Extraction must refer to one exact semantic unit')
    bound=result.get('bound');review=result.get('review')
    output=dict(source=deepcopy(packet['units'][0]['source']),contents=[],attachments=[],features=[],
                counts=dict(contents=0,features=0,inspected=0,pending=0),inventory_status='not_evaluated')
    if bound is None:
        if review is not None:raise InputError('A scope review requires bound contents')
        if result.get('relations') is not None:raise InputError('Local relationships require bound contents')
        return output
    scopes.checked(packet,bound)
    known={f['id']:f for f in bound['features']};receipts={}
    if review is not None:
        responses={}
        for receipt in review.get('receipts',[]):
            fid=receipt.get('feature_id')
            if fid not in known or fid in responses:raise InputError('Unknown or duplicate feature receipt')
            responses[fid]=receipt['response']
        reconstructed=scopes.scope_membership_review(packet,bound,responses,
            direct_arguments=result.get('direct_arguments',True),syntax=syntax)
        if reconstructed!=review:raise InputError('Saved extraction review differs from its decisions')
        receipts={r['feature_id']:r for r in review['receipts']}
    output['counts']=dict(contents=len(bound['contents']),features=len(known),inspected=len(receipts),pending=len(known)-len(receipts))
    for feature in bound['features']:
        receipt=receipts.get(feature['id'])
        row={k:deepcopy(v) for k,v in feature.items() if k!='scopes'}
        row['status']=receipt['status'] if receipt else 'pending'
        output['features'].append(row)
        decisions={d['content_id']:d['choice'] for d in receipt['decisions']} if receipt else {}
        for content in bound['contents']:
            output['attachments'].append(dict(content_id=content['id'],feature_id=feature['id'],
                type=feature['type'],expression=deepcopy(feature['expression']),
                status=decisions.get(content['id'],'pending')))
    for content in bound['contents']:
        output['contents'].append(dict(deepcopy(content),features=[deepcopy(f) for f in output['attachments']
            if f['content_id']==content['id'] and f['status'] in {'applies','unresolved'}]))
    if result.get('relation_policy'):
        if result['relation_policy'] not in scopes.LOCAL_RELATION_POLICIES:raise InputError('Unknown local relationship protocol')
        relation=result.get('relations')
        if relation is not None:
            responses={r['page']:r['response'] for r in relation.get('receipts',[])}
            if scopes.local_relation_review(packet,bound,responses,policy=result['relation_policy'])!=relation:raise InputError('Saved local relationships differ from their decisions')
            output['relations']={k:deepcopy(v) for k,v in relation.items() if k not in {'receipts','bound_hash'}}
        else:
            output['relations']=dict(status='awaiting_content_and_attributes',links=[])
    return output


def save(store, graph, packet, result, *, syntax=None):
    uid=result.get('unit_id')
    if packet!=work_mentions.packet(graph,[uid]):raise InputError('Extraction source differs from the saved graph')
    projection=view(packet,result,syntax=syntax)
    if result.get('status') not in {'running','complete','budget_reached','needs_review','retry_required'}:
        raise InputError('Unknown extraction state')
    workspace=str(Path(result['directory']).resolve())
    identifier='work-extraction-'+digest([graph['id'],uid,workspace])
    # Keep the private resume directory out of browser/API documents.
    document=dict(schema=VERSION,id=identifier,graph_id=graph['id'],unit_id=uid,run_id=graph['run_id'],
        result={k:deepcopy(v) for k,v in result.items() if k!='directory'},
        packet=deepcopy(packet),syntax=deepcopy(syntax),view=projection)
    revision=digest(document);now=datetime.now(timezone.utc).isoformat()
    with store.connect() as c:
        initialize(c)
        if not c.execute('SELECT 1 FROM rollout_graphs WHERE id=? AND source_hash=?',(graph['id'],packet['source_hash'])).fetchone():
            raise InputError('Save the exact source graph before its extraction results')
        previous=c.execute('SELECT revision,document FROM work_content_extractions WHERE id=?',(identifier,)).fetchone()
        if previous and result['status']=='running':
            old=json.loads(previous['document']);before=old['view']['counts'];after=projection['counts']
            # Cached resume replays earlier stages before reaching the saved
            # frontier. Never make already visible content disappear meanwhile.
            prior_links=old['view'].get('relations',{}).get('pages',{}).get('inspected',0)
            current_links=projection.get('relations',{}).get('pages',{}).get('inspected',0)
            same_relation_policy=old['result'].get('relation_policy')==result.get('relation_policy')
            if ((old['result']['status']=='complete' and same_relation_policy) or prior_links>current_links or
                    any(before[k]>after[k] for k in ('contents','features','inspected'))):
                revision=previous['revision']
                document=None
        if document is None:
            return dict(id=identifier,revision=revision,map_url='/semantic-map?'+urlencode(dict(
                run=graph['run_id'],graph=graph['id'],observer=graph['observer'],level='units',focus_unit=uid,work_extraction=identifier)))
        c.execute('''INSERT INTO work_content_extractions VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document,
              updated_at=excluded.updated_at WHERE work_content_extractions.revision!=excluded.revision''',
            (identifier,graph['id'],graph['run_id'],uid,revision,dumps(document),workspace,now,now))
    return dict(id=identifier,revision=revision,map_url='/semantic-map?'+urlencode(dict(
        run=graph['run_id'],graph=graph['id'],observer=graph['observer'],level='units',focus_unit=uid,work_extraction=identifier)))


def for_graph(store, graph, unit_id=None):
    """Current records; no filesystem reads or model calls on the display path."""
    with store.connect() as c:
        if not present(c):return []
        query='SELECT id,revision,document,created_at,updated_at FROM work_content_extractions WHERE graph_id=?'
        args=[graph['id']]
        if unit_id is not None:query+=' AND unit_id=?';args.append(unit_id)
        rows=c.execute(query+' ORDER BY updated_at DESC,id',args).fetchall()
    results=[]
    for row in rows:
        document=json.loads(row['document'])
        if digest(document)!=row['revision']:raise InputError('Saved extraction record changed')
        result=document['result']
        results.append(dict(id=row['id'],revision=row['revision'],unit_id=document['unit_id'],
            status=result['status'],stage=result['stage'],content_policy=result['content_policy'],
            created_at=row['created_at'],updated_at=row['updated_at'],
            view=document['view'],usage=result['usage'],model=result['model']))
    return results


def read(store, graph_id, unit_id):
    """Small polling query; does not reload the entire rollout graph."""
    with store.connect() as c:
        if not c.execute('SELECT 1 FROM graph_nodes WHERE graph_id=? AND id=? AND kind=?',
                         (graph_id,unit_id,'unit')).fetchone():
            raise InputError('Unknown unit in this graph')
    return for_graph(store,dict(id=graph_id),unit_id)


BASE_SQL='''SELECT e.id extraction_id,e.graph_id,e.run_id,g.observer,e.unit_id,e.revision,
  json_extract(e.document,'$.result.status') status,json_extract(e.document,'$.result.stage') stage,
  json_extract(e.document,'$.result.content_policy') content_policy,
  e.created_at,e.updated_at,e.document record_json,g.is_latest
  FROM work_content_extractions e JOIN rl_graphs g ON g.graph_id=e.graph_id'''
VIEW_SQL={
 'content_extractions':BASE_SQL,
 'work_contents':'''SELECT e.extraction_id,e.graph_id,e.run_id,e.observer,e.unit_id,e.revision,
   json_extract(j.value,'$.id') content_id,json_extract(j.value,'$.kind') kind,
   json_extract(j.value,'$.mode') mode,json_extract(j.value,'$.expression.text') text,
   json_extract(j.value,'$.expression') source_json,json_extract(j.value,'$.features') features_json,
   e.is_latest FROM rl_content_extractions e,json_each(e.record_json,'$.view.contents') j''',
 'work_attachments':'''SELECT e.extraction_id,e.graph_id,e.run_id,e.observer,e.unit_id,e.revision,
   json_extract(j.value,'$.content_id') content_id,json_extract(j.value,'$.feature_id') feature_id,
   json_extract(j.value,'$.type') type,json_extract(j.value,'$.status') status,
   json_extract(j.value,'$.expression') source_json,e.is_latest
   FROM rl_content_extractions e,json_each(e.record_json,'$.view.attachments') j''',
 'work_content_relations':'''SELECT e.extraction_id,e.graph_id,e.run_id,e.observer,e.unit_id,e.revision,
   json_extract(j.value,'$.id') relation_id,json_extract(j.value,'$.source') source_content_id,
   json_extract(j.value,'$.target') target_content_id,json_extract(j.value,'$.type') type,
   json_extract(j.value,'$.status') status,json_extract(e.record_json,'$.view.relations.source') source_json,e.is_latest
   FROM rl_content_extractions e,json_each(e.record_json,'$.view.relations.links') j''',
}
COLUMNS={
 'content_extractions':'extraction_id graph_id run_id observer unit_id revision status stage content_policy created_at updated_at record_json is_latest',
 'work_contents':'extraction_id graph_id run_id observer unit_id revision content_id kind mode text source_json features_json is_latest',
 'work_attachments':'extraction_id graph_id run_id observer unit_id revision content_id feature_id type status source_json is_latest',
 'work_content_relations':'extraction_id graph_id run_id observer unit_id revision relation_id source_content_id target_content_id type status source_json is_latest',
}
EMPTY_SQL={name:'SELECT '+','.join('NULL '+c for c in columns.split())+' WHERE 0' for name,columns in COLUMNS.items()}
