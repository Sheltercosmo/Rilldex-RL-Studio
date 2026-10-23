"""Experiment entry points from captured records, without inferred run status."""
import json
from .schema import InputError

_FACTS = """WITH current_rollouts AS (
 SELECT json_extract(r.document,'$.metadata.experiment') experiment,
        json_extract(r.document,'$.metadata.environment') environment,r.imported_at received_at
 FROM runs r WHERE NOT EXISTS(SELECT 1 FROM rollout_revisions rr WHERE rr.run_id=r.id)
 OR EXISTS(SELECT 1 FROM rollout_revisions rr WHERE rr.run_id=r.id AND rr.revision=(
   SELECT max(revision) FROM rollout_revisions WHERE producer=rr.producer AND rollout_id=rr.rollout_id))
), facts AS (
 SELECT experiment,environment,received_at,'rollouts' kind FROM current_rollouts
 UNION ALL SELECT experiment,json_extract(document,'$.environment'),received_at,'logs' FROM trainer_telemetry
 UNION ALL SELECT e.experiment,json_extract(e.document,'$.context.environment'),e.received_at,'executions'
 FROM execution_records e WHERE e.revision=(SELECT max(revision) FROM execution_records
   WHERE producer=e.producer AND experiment=e.experiment AND record_id=e.record_id)
 UNION ALL SELECT experiment,json_extract(document,'$.context.environment'),received_at,'training_records' FROM training_records
 UNION ALL SELECT experiment,json_extract(document,'$.context.environment'),received_at,'training_records' FROM training_sample_records
 UNION ALL SELECT json_extract(document,'$.experiment'),json_extract(document,'$.environment'),created_at,'history_events' FROM experiment_history
 UNION ALL SELECT experiment,NULL,received_at,'capture_records' FROM run_records
), scoped AS (SELECT * FROM facts WHERE (? IS NULL OR environment=?)), grouped AS (
 SELECT experiment,sum(kind='rollouts') rollouts,sum(kind='logs') logs,
 sum(kind='executions') executions,sum(kind='training_records') training_records,sum(kind='history_events') history_events,
 sum(kind='capture_records') capture_records,max(received_at) last_received FROM scoped
 WHERE typeof(experiment)='text' AND trim(experiment)<>'' GROUP BY experiment
) """


def catalog(store, *, q='', environment=None, limit=30, offset=0, project=None, state='active', search_in='labels'):
    if not isinstance(q,str) or len(q)>200 or environment is not None and not isinstance(environment,str):
        raise InputError('Use a short experiment search and an exact environment name')
    if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:
        raise InputError('Use limit 1–100 and a nonnegative offset')
    if state not in ('active','archived','pinned','all') or project is not None and not isinstance(project,str):
        raise InputError('Invalid project or run filter')
    args=[environment,environment]
    if search_in not in ('labels','settings'):raise InputError('Search names and tags or recorded settings')
    join=' FROM grouped g LEFT JOIN experiment_labels l ON l.experiment=g.experiment '
    where=" WHERE instr(lower(g.experiment||' '||coalesce(l.title,'')||' '||coalesce(l.tags,'')),lower(?))>0 AND (? IS NULL OR coalesce(l.project,'')=?)"
    if state=='active': where+=' AND coalesce(l.archived,0)=0'
    if state=='archived': where+=' AND l.archived=1'
    if state=='pinned': where+=' AND l.pinned=1 AND l.archived=0'
    filters=[q,project,project]
    if search_in=='settings':
        where=where.replace("instr(lower(g.experiment||' '||coalesce(l.title,'')||' '||coalesce(l.tags,'')),lower(?))>0",'''EXISTS (
            SELECT 1 FROM run_records r WHERE r.experiment=g.experiment AND r.kind='manifest'
              AND instr(lower(json_extract(r.document,'$.payload.config')),lower(?))>0
            UNION ALL SELECT 1 FROM execution_records e WHERE e.experiment=g.experiment
              AND e.revision=(SELECT max(revision) FROM execution_records WHERE producer=e.producer AND experiment=e.experiment AND record_id=e.record_id)
              AND (? IS NULL OR json_extract(e.document,'$.context.environment')=? OR
                (json_extract(e.document,'$.context.environment') IS NULL AND e.kind IN ('learner_update','weight_sync','configuration')))
              AND instr(lower(json_extract(e.document,'$.configuration')),lower(?))>0)''')
        filters=[q,environment,environment,q,project,project]
    with store.connect() as c:
        # One read snapshot keeps the page and its counts consistent with arriving data.
        c.execute('BEGIN')
        total=c.execute(_FACTS+'SELECT count(*)'+join+where,args+filters).fetchone()[0]
        rows=[dict(r) for r in c.execute(_FACTS+'''SELECT g.*,coalesce(l.title,g.experiment) title,
            coalesce(l.project,'') project,coalesce(l.tags,'[]') tags,coalesce(l.notes,'') notes,
            coalesce(l.pinned,0) pinned,coalesce(l.archived,0) archived'''+join+where+'''
            ORDER BY coalesce(l.pinned,0) DESC,last_received DESC,g.experiment LIMIT ? OFFSET ?''',args+filters+[limit,offset])]
        projects=[r[0] for r in c.execute("SELECT DISTINCT project FROM experiment_labels WHERE project<>'' ORDER BY project")]
        selections=[json.loads(r[0]) for r in c.execute('SELECT document FROM experiment_selections ORDER BY name')]
        unassigned=c.execute(_FACTS+'''SELECT count(*) FROM scoped WHERE kind='rollouts'
            AND (experiment IS NULL OR trim(experiment)='')''',args).fetchone()[0]
        for row in rows:
            row['tags']=json.loads(row['tags'])
            row['trainer_contexts']=[dict(r) for r in c.execute('''SELECT DISTINCT
                json_extract(document,'$.framework') framework,json_extract(document,'$.framework_version') framework_version,
                json_extract(document,'$.objective') objective
                FROM trainer_telemetry WHERE experiment=? AND (? IS NULL OR json_extract(document,'$.environment')=?)
                ORDER BY framework,framework_version,objective''',[row['experiment'],environment,environment])]
    return dict(schema='experiment-catalog/1',rows=rows,total=total,limit=limit,offset=offset,unassigned_rollouts=unassigned,projects=projects,selections=selections)
