"""Read recorded run context without inventing an effective configuration."""
import json
from datetime import datetime, timezone

from .schema import InputError

VERSION = 'experiment-details/1'
SECTIONS = ('settings', 'trainers', 'history')


def _execution_scope():
    # A shared learner/configuration record remains useful in an environment view.
    return '''FROM execution_records e WHERE e.experiment=?
      AND e.revision=(SELECT max(p.revision) FROM execution_records p
        WHERE p.producer=e.producer AND p.experiment=e.experiment AND p.record_id=e.record_id)
      AND (? IS NULL OR json_extract(e.document,'$.context.environment')=?
        OR (json_extract(e.document,'$.context.environment') IS NULL
            AND e.kind IN ('learner_update','weight_sync','configuration')))'''


def execution_context(connection, *, experiment, producer, record_id, limit=100):
    """Exact native-log references only; step/time proximity cannot establish a link."""
    scope = _execution_scope() + ''' AND EXISTS (SELECT 1 FROM json_each(e.document,'$.telemetry') ref
      WHERE json_extract(ref.value,'$.producer')=? AND json_extract(ref.value,'$.id')=?)'''
    args = [experiment, None, None, producer, record_id]
    total = connection.execute('SELECT count(*) ' + scope, args).fetchone()[0]
    rows = connection.execute('SELECT e.* ' + scope + ' ORDER BY e.received_at DESC,e.producer,e.record_id LIMIT ?', args + [limit])
    return dict(total=total, truncated=total>limit, records=[_execution(r,connection) for r in rows])


def _execution(row, connection):
    record=json.loads(row['document'])
    refs=record.get('telemetry',[])
    query='''FROM json_each(?) ref JOIN trainer_telemetry t
      ON t.producer=json_extract(ref.value,'$.producer')
      AND t.record_id=json_extract(ref.value,'$.id') AND t.experiment=?'''
    parameters=[json.dumps(refs),row['experiment']]
    matched=connection.execute('SELECT count(*) '+query,parameters).fetchone()[0] if refs else 0
    logs=[dict(r) for r in connection.execute('''SELECT t.producer,t.record_id id,t.session,t.step,
      json_extract(t.document,'$.clock') clock,json_extract(t.document,'$.split') split '''+query+
      ' ORDER BY t.producer,t.session,t.step,t.record_id LIMIT 8',parameters)] if refs else []
    return dict(producer=row['producer'], id=row['record_id'], revision=row['revision'],
                received_at=row['received_at'], record=record,trainer_logs=logs,
                matched_logs=matched,declared_logs=len(refs))


def details(store, *, experiment, environment=None, section='settings', q='', limit=20, offset=0):
    if not isinstance(experiment,str) or not experiment.strip() or len(experiment)>500:
        raise InputError('Select one experiment')
    if environment is not None and (not isinstance(environment,str) or not environment.strip()):
        raise InputError('Use an exact environment name')
    if section not in SECTIONS or not isinstance(q,str) or len(q)>200:
        raise InputError('Select settings, trainers or history and use a short search')
    if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:
        raise InputError('Use limit 1–100 and a nonnegative offset')
    args = [experiment,environment,environment]
    settings = _execution_scope()+" AND json_type(e.document,'$.configuration')='object'"
    trainers = '''FROM trainer_telemetry WHERE experiment=?
      AND (? IS NULL OR json_extract(document,'$.environment')=?)'''
    history = '''FROM experiment_history WHERE json_extract(document,'$.experiment')=?
      AND (? IS NULL OR json_extract(document,'$.environment')=? OR json_extract(document,'$.environment') IS NULL)'''
    with store.connect() as c:
        if not c.in_transaction:c.execute('BEGIN')
        # Separate producers, sessions and populations even when step numbers agree.
        streams = '''WITH streams AS (SELECT producer,session,
          json_extract(document,'$.clock') clock,json_extract(document,'$.framework') framework,
          json_extract(document,'$.framework_version') framework_version,
          json_extract(document,'$.objective') objective,json_extract(document,'$.population') population,
          json_extract(document,'$.split') split,json_extract(document,'$.environment') environment,
          count(*) logs,min(step) first_step,max(step) last_step,max(received_at) last_received '''+trainers+'''
          GROUP BY producer,session,clock,framework,framework_version,objective,population,split,environment) '''
        counts = dict(settings=c.execute('SELECT count(*) '+settings,args).fetchone()[0],
                      trainers=c.execute(streams+'SELECT count(*) FROM streams',args).fetchone()[0],
                      history=c.execute('SELECT count(*) '+history,args).fetchone()[0])
        if section=='settings':
            search=settings+" AND instr(lower(json_extract(e.document,'$.configuration')),lower(?))>0"
            total=c.execute('SELECT count(*) '+search,args+[q]).fetchone()[0]
            rows=[_execution(r,c) for r in c.execute('SELECT e.* '+search+
                ' ORDER BY e.received_at DESC,e.producer,e.record_id LIMIT ? OFFSET ?',args+[q,limit,offset])]
        elif section=='trainers':
            search='FROM streams WHERE instr(lower(producer||session||clock||framework||framework_version||objective||population||split),lower(?))>0'
            total=c.execute(streams+'SELECT count(*) '+search,args+[q]).fetchone()[0]
            rows=[dict(r) for r in c.execute(streams+'SELECT * '+search+
                ' ORDER BY last_received DESC,producer,session,clock,split,objective LIMIT ? OFFSET ?',args+[q,limit,offset])]
        else:
            search=history+" AND instr(lower(document),lower(?))>0"
            total=c.execute('SELECT count(*) '+search,args+[q]).fetchone()[0]
            rows=[dict(id=r['id'],**json.loads(r['document'])) for r in c.execute('SELECT * '+search+
                ' ORDER BY created_at DESC,id LIMIT ? OFFSET ?',args+[q,limit,offset])]
            # Supersession is resolved over the experiment, not just the current page/filter.
            for row in rows:
                row['superseded']=bool(c.execute("SELECT 1 FROM experiment_history WHERE json_extract(document,'$.experiment')=? AND json_extract(document,'$.supersedes')=? LIMIT 1",[experiment,row['id']]).fetchone())
    return dict(schema=VERSION,experiment=experiment,environment=environment,section=section,counts=counts,
                rows=rows,total=total,limit=limit,offset=offset,captured_at=datetime.now(timezone.utc).isoformat())
