"""Read-only research interface over saved evidence. No Store or model execution.

Use a short snapshot context for consistent joins. Each standalone call opens a
fresh snapshot so notebooks can follow a running collector without stale reads.
"""
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import zipfile

from .schema import InputError
from .run_records import VIEW_SQL as RUN_CAPTURE_SQL, EMPTY_SQL as EMPTY_RUN_CAPTURE
from .execution_records import VIEW_SQL as EXECUTION_SQL, EMPTY_SQL as EMPTY_EXECUTIONS
from .generation_cohorts import VIEW_SQL as COHORT_SQL, EMPTY_SQL as EMPTY_COHORTS
from .evaluation_receipts import VIEW_SQL as EVALUATION_SQL, EMPTY_SQL as EMPTY_EVALUATIONS
from .work_content_results import VIEW_SQL as CONTENT_SQL, EMPTY_SQL as EMPTY_CONTENTS

VERSION = 'research-data/1'
FEED_MAX_BYTES = 32*1024*1024
TRAINING_COLUMNS = ('record_schema','producer','experiment','record_id','revision','kind','sample_producer',
                    'rollout_id','sample_id','received_at','record_json','is_latest')
TRAINING_SQL = {
    'training_records': """SELECT 'training-records/1' record_schema,t.producer,t.experiment,t.record_id,t.revision,t.kind,t.sample_producer,
      t.rollout_id,NULL sample_id,t.received_at,t.document record_json,
      t.revision=(SELECT max(u.revision) FROM training_records u WHERE u.producer=t.producer
      AND u.experiment=t.experiment AND u.record_id=t.record_id) is_latest FROM training_records t""",
    'training_sample_records': """SELECT 'training-records/2' record_schema,t.producer,t.experiment,t.record_id,t.revision,t.kind,t.sample_producer,
      NULL rollout_id,t.sample_id,t.received_at,t.document record_json,
      t.revision=(SELECT max(u.revision) FROM training_sample_records u WHERE u.producer=t.producer
      AND u.experiment=t.experiment AND u.record_id=t.record_id) is_latest FROM training_sample_records t""",
}
VIEWS = {
    'run_capture': RUN_CAPTURE_SQL,
    'trainer_telemetry': '''SELECT producer,experiment,record_id,session,step,
      json_extract(document,'$.clock') clock,json_extract(document,'$.framework') framework,
      json_extract(document,'$.objective') objective,json_extract(document,'$.split') split,
      document record_json,received_at FROM trainer_telemetry''',
    'evaluations': EVALUATION_SQL,
    'generation_cohorts': COHORT_SQL,
    'executions': EXECUTION_SQL,
    'rollouts': """SELECT r.id run_id,r.imported_at,
      json_extract(r.document,'$.adapter') adapter,
      json_extract(r.document,'$.metadata.experiment') experiment,
      json_extract(r.document,'$.metadata.training_step') training_step,
      json_extract(r.document,'$.metadata.training_step_basis') training_step_basis,
      json_extract(r.document,'$.metadata.generation_step') generation_step,
      json_extract(r.document,'$.metadata.learner_step') learner_step,
      json_extract(r.document,'$.metadata.policy_version') policy_version,
      json_extract(r.document,'$.metadata') metadata_json,
      json_extract(r.document,'$.outcome.verified_success') verified_success,
      json_extract(r.document,'$.outcome') outcome_json,
      NOT EXISTS(SELECT 1 FROM rollout_revisions v WHERE v.run_id=r.id)
      OR EXISTS(SELECT 1 FROM rollout_revisions v WHERE v.run_id=r.id AND
        v.revision=(SELECT max(w.revision) FROM rollout_revisions w
        WHERE w.producer=v.producer AND w.rollout_id=v.rollout_id)) is_latest
      FROM runs r""",
    'revisions': """SELECT v.producer,v.rollout_id,v.revision,v.run_id,v.state,v.created_at,
      v.revision=(SELECT max(w.revision) FROM rollout_revisions w
        WHERE w.producer=v.producer AND w.rollout_id=v.rollout_id) is_latest
      FROM rollout_revisions v""",
    'sources': 'SELECT id run_id,document document_json FROM runs',
    'graphs': """SELECT g.id graph_id,g.run_id,g.observer,g.source_hash,g.annotation_hash,
      g.created_at,g.document header_json,
      g.rowid=(SELECT max(h.rowid) FROM rollout_graphs h WHERE h.run_id=g.run_id AND h.observer=g.observer) is_latest
      FROM rollout_graphs g""",
    'nodes': """SELECT n.graph_id,g.run_id,g.observer,g.source_hash,n.id node_id,n.kind,n.activity,
      n.trajectory_id,n.event_index,n.document node_json,g.is_latest
      FROM graph_nodes n JOIN rl_graphs g ON g.graph_id=n.graph_id""",
    'edges': """SELECT e.graph_id,g.run_id,g.observer,g.source_hash,e.id edge_id,e.source,e.target,
      e.type,e.document edge_json,g.is_latest FROM graph_edges e JOIN rl_graphs g ON g.graph_id=e.graph_id""",
    'measurements': """SELECT m.id measurement_id,m.run_id,m.observer,m.created_at,j.key metric,
      json_extract(m.document,'$.schema') measurement_schema,
      json_extract(m.document,'$.source_hash') source_hash,
      json_extract(m.document,'$.annotation_hash') annotation_hash,
      json_extract(m.document,'$.graph_id') graph_id,
      json_extract(j.value,'$.value') value,json_extract(j.value,'$.numerator') numerator,
      json_extract(j.value,'$.denominator') denominator,json_extract(j.value,'$.status') status,
      json_extract(j.value,'$.reason') reason,j.value details_json,
      m.rowid=(SELECT n.rowid FROM rollout_measurements n WHERE n.run_id=m.run_id AND n.observer=m.observer
        ORDER BY n.created_at DESC,n.rowid DESC LIMIT 1) is_latest,
      rilldex_measurement_input_current(m.id) is_current
      FROM rollout_measurements m,json_each(m.document,'$.metrics') j""",
    'monitor_values': """SELECT v.id value_id,v.monitor_id,v.run_id,v.input_hash,v.created_at,
      json_extract(d.document,'$.observer') observer,json_extract(d.document,'$.name') monitor_name,
      json_extract(v.document,'$.input_id') input_id,json_extract(v.document,'$.source_hash') source_hash,
      json_extract(v.document,'$.value') value,json_extract(v.document,'$.numerator') numerator,
      json_extract(v.document,'$.denominator') denominator,json_extract(v.document,'$.status') status,
      json_extract(v.document,'$.feedback.severity') feedback_severity,
      json_extract(v.document,'$.feedback.summary') feedback_summary,
      json_extract(v.document,'$.feedback.next_check') feedback_next_check,
      json_extract(v.document,'$.details') result_details_json,
      json_extract(v.document,'$.reason') reason,v.document details_json,
      EXISTS(SELECT 1 FROM monitor_latest l WHERE l.value_id=v.id) is_latest,
      CASE WHEN EXISTS(SELECT 1 FROM monitor_latest l WHERE l.value_id=v.id)
        THEN rilldex_monitor_input_current(v.monitor_id,v.run_id,v.input_hash) ELSE 0 END is_current
      FROM monitor_values v
      JOIN monitors d ON d.id=v.monitor_id""",
    'monitor_definitions': "SELECT id monitor_id,enabled,created_at,json_extract(document,'$.observer') observer,json_extract(document,'$.name') monitor_name,document definition_json FROM monitors",
    'training_records': ' UNION ALL '.join(TRAINING_SQL.values()),
}
VIEWS.update(CONTENT_SQL)
GRAINS = {
    'run_capture': 'One immutable console chunk, hardware sample, file version, manifest or session event per producer. File bytes are available through the file API; wall clocks across hosts may differ.',
    'trainer_telemetry': 'One immutable native trainer log. Metrics retain units and reductions; no inferred rollout or sample joins.',
    'evaluations': 'One immutable producer-reported evaluation. Repeated checks are not distinct rollouts or verified independent outcomes; select explicit receipt IDs.',
    'generation_cohorts': 'One scheduler-declared membership revision. Sealing fixes membership, not scoring or training-use completeness.',
    'executions': 'One producer execution-attempt revision. Completion is not task success or training use.',
    'rollouts': 'One immutable source snapshot; latest filters superseded producer snapshots.',
    'revisions': 'One acknowledged producer / logical rollout / revision. Lifecycle is not correctness.',
    'sources': 'One full normalized source document per snapshot; can contain sensitive trace text.',
    'graphs': 'One saved graph version per source and observer.',
    'nodes': 'One node per graph version; join by graph_id AND node_id.',
    'edges': 'One directed edge per graph version; temporal edges are not causal claims.',
    'measurements': 'One metric per saved measurement record; is_current checks source and declared map inputs. is_latest alone means publication order. Unavailable stays null, never zero.',
    'monitor_values': 'One saved monitor result per input identity. is_latest marks the published index; is_current also verifies current source, population and monitor inputs. Neither implies an available or correct measurement.',
    'monitor_definitions': 'Monitor definitions, including disabled monitors. An experiment scope retains definitions referenced by its saved results.',
    'training_records': 'One explicit trainer fact revision; no guessed joins to source snapshots.',
    'content_extractions':'Current saved progress per exact graph, unit and extraction workspace; revision changes on progress. Generated content is not a verified behavior or execution.',
    'work_contents':'One generated operation/state per extraction. Join by extraction_id AND content_id; modes are candidate interpretations, not verified outcomes.',
    'work_attachments':'One feature/content pair per extraction, including pending and unresolved decisions. Applies is model-selected attachment, not an execution or correctness claim.',
    'work_content_relations':'One directed content pair and relationship type per enabled extraction, including pending/unsupported/unresolved decisions. Join endpoints with extraction_id AND content_id. Source interpretation, not observed execution.',
}
DEFAULT_TABLES = tuple(n for n in VIEWS if n != 'sources')
OBSERVER_TABLES = ('graphs', 'nodes', 'edges', 'measurements', 'monitor_values', 'monitor_definitions', *CONTENT_SQL)
EXPORT_PROFILES = {
    'research': DEFAULT_TABLES,
    'measurements': ('rollouts', 'revisions', 'measurements', 'monitor_values', 'monitor_definitions'),
    'graphs': ('rollouts', 'revisions', 'graphs', 'nodes', 'edges'),
}
FEEDS = {'sources': ('runs', 'id', 'document', 'imported_at'),
         'generation_cohorts': ('generation_cohorts', 'json_array(producer,experiment,cohort_id,revision)', 'document', 'received_at'),
         'executions': ('execution_records', 'json_array(producer,experiment,record_id,revision)', 'document', 'received_at'),
         'revisions': ('rollout_revisions', 'json_array(producer,rollout_id,revision)',
                       "json_object('producer',producer,'rollout_id',rollout_id,'revision',revision,'run_id',run_id,'state',state)", 'created_at'),
         'graphs': ('rollout_graphs', 'id', 'document', 'created_at'),
         'measurements': ('rollout_measurements', 'id', 'document', 'created_at'),
         'monitor_values': ('monitor_values', 'id', 'document', 'created_at'),
         'training_records': ('training_records', 'json_array(producer,experiment,record_id,revision)', 'document', 'received_at'),
         'training_samples': ('training_sample_records', 'json_array(producer,experiment,record_id,revision)', 'document', 'received_at')}


def _integer(value, name, low=1, high=100000):
    if type(value) is not int or not low <= value <= high:
        raise InputError(f'{name} must be an integer from {low} to {high}')
    return value


class Analysis:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file(): raise InputError('Analysis requires an existing workspace database')

    @contextmanager
    def snapshot(self):
        """Pin a read transaction. Keep it short while training writes to WAL."""
        c = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=5)
        c.row_factory = sqlite3.Row
        try:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
            source_coverage = {}; unavailable = set(); unavailable_feeds = set()
            frozen = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_snapshot'").fetchone()
            execution_available = bool(c.execute('SELECT 1 FROM sqlite_master WHERE name=?',
                ('rl_executions' if frozen else 'execution_records',)).fetchone())
            cohort_available = ('rl_generation_cohorts' if frozen else 'generation_cohorts') in tables
            evaluation_available = ('rl_evaluations' if frozen else 'evaluation_receipts') in tables
            telemetry_available = ('rl_trainer_telemetry' if frozen else 'trainer_telemetry') in tables
            capture_available = ('rl_run_capture' if frozen else 'run_records') in tables
            if not capture_available: unavailable.add('run_capture')
            content_available = {name:('rl_'+name if frozen else 'work_content_extractions') in tables for name in CONTENT_SQL}
            unavailable.update(name for name,present in content_available.items() if not present)
            empty_telemetry = 'SELECT '+','.join('NULL '+k for k in ('producer','experiment','record_id','session','step','clock','framework','objective','split','record_json','received_at'))+' WHERE 0'
            if not telemetry_available: unavailable.add('trainer_telemetry')
            if not frozen:
                from .monitor_freshness import register as register_monitor_freshness
                register_monitor_freshness(c,self.path)
                present = [sql for name, sql in TRAINING_SQL.items() if name in tables]
                training_sql = ' UNION ALL '.join(present) if present else 'SELECT '+','.join('NULL '+n for n in TRAINING_COLUMNS)+' WHERE 0'
                if not present: unavailable.add('training_records')
                source_coverage['training_records'] = dict(
                    available_schemas=[f'training-records/{i}' for i, n in enumerate(TRAINING_SQL, 1) if n in tables],
                    unavailable_schemas=[f'training-records/{i}' for i, n in enumerate(TRAINING_SQL, 1) if n not in tables],
                    basis='Physical schema support, not evidence of captured or absent trainer facts')
                unavailable_feeds = {n for n, spec in FEEDS.items() if spec[0] not in tables}
                for name, sql in VIEWS.items():
                    if name == 'run_capture' and not capture_available: sql = EMPTY_RUN_CAPTURE
                    if name in CONTENT_SQL and not content_available[name]:sql=EMPTY_CONTENTS[name]
                    if name == 'trainer_telemetry' and not telemetry_available: sql = empty_telemetry
                    if name == 'training_records': sql = training_sql
                    if name == 'executions' and not execution_available: sql = EMPTY_EXECUTIONS
                    if name == 'generation_cohorts' and not cohort_available: sql = EMPTY_COHORTS
                    if name == 'evaluations' and not evaluation_available: sql = EMPTY_EVALUATIONS
                    c.execute(f'CREATE TEMP VIEW rl_{name} AS '+sql)
            else:
                if not capture_available:c.execute('CREATE TEMP VIEW rl_run_capture AS '+EMPTY_RUN_CAPTURE)
                for name,present in content_available.items():
                    if not present:c.execute('CREATE TEMP VIEW rl_'+name+' AS '+EMPTY_CONTENTS[name])
                if not telemetry_available:c.execute('CREATE TEMP VIEW rl_trainer_telemetry AS '+empty_telemetry)
                rows = c.execute('SELECT schema,document_json FROM research_snapshot').fetchall()
                if len(rows)!=1 or rows[0][0]!='research-snapshot/1': raise InputError('Unsupported research snapshot schema')
                if not execution_available:c.execute('CREATE TEMP VIEW rl_executions AS '+EMPTY_EXECUTIONS)
                execution_available = execution_available and json.loads(rows[0][1]).get('tables',{}).get('executions',{}).get('included',False)
                manifest = json.loads(rows[0][1])
                source_coverage.update({n: info['source_coverage'] for n, info in manifest.get('tables', {}).items() if info.get('source_coverage')})
                for name in ('monitor_values','measurements'):
                    columns={r[1] for r in c.execute('PRAGMA table_info(rl_'+name+')')}
                    if columns and 'is_current' not in columns:
                        # Old portable snapshots cannot establish applicability.
                        # Keep their receipts in history, never label them current.
                        c.execute('CREATE TEMP VIEW rl_'+name+' AS SELECT *,NULL is_current FROM main.rl_'+name)
                        source_coverage[name]={'freshness':'unavailable','notice':'Snapshot predates input-current flags. Use history=True to inspect saved receipts.'}
                if not cohort_available:c.execute('CREATE TEMP VIEW rl_generation_cohorts AS '+EMPTY_COHORTS)
                cohort_available = cohort_available and manifest.get('tables',{}).get('generation_cohorts',{}).get('included',False)
                if not evaluation_available:c.execute('CREATE TEMP VIEW rl_evaluations AS '+EMPTY_EVALUATIONS)
                evaluation_available = evaluation_available and manifest.get('tables',{}).get('evaluations',{}).get('included',False)
                unavailable.update(n for n, info in manifest.get('tables', {}).items() if not info.get('included'))
            if not execution_available: unavailable.add('executions')
            if not cohort_available: unavailable.add('generation_cohorts')
            if not evaluation_available: unavailable.add('evaluations')
            c.execute('PRAGMA query_only=ON')
            c.execute('BEGIN')
            c.execute('SELECT count(*) FROM rl_rollouts').fetchone()  # establish one WAL snapshot
            yield Snapshot(c, frozen=bool(frozen), manifest=json.loads(rows[0][1]) if frozen else None,
                           unavailable=unavailable, unavailable_feeds=unavailable_feeds, source_coverage=source_coverage)
        finally: c.close()

    def catalog(self):
        with self.snapshot() as s: return s.catalog()

    def execution_summary(self, **options):
        from .execution_records import summary
        return summary(self, **options)

    def cohort_readiness(self, **options):
        """Declared populations joined to current sources in one read snapshot."""
        from .generation_cohorts import project
        from .store import ReadSnapshot
        with self.snapshot() as saved:
            if saved.frozen:
                raise InputError('Cohort readiness needs a workspace database; research exports retain declared membership for SQL analysis')
            return project(ReadSnapshot(self.path,saved.c),**options)

    def query(self, sql, parameters=(), *, limit=1000):
        with self.snapshot() as s: return s.query(sql, parameters, limit=limit)

    def table(self, name, **options):
        with self.snapshot() as s: return s.table(name, **options)

    def options(self, *, experiment=None, history=False):
        with self.snapshot() as s: return s.options(experiment=experiment, history=history)

    def database(self, destination, **options):
        """Create a portable SQL dataset; use sqlite3, pandas or your own tools."""
        from .research_dataset import materialize
        return materialize(self, destination, **options)

    def changes(self, feed='sources', *, cursor=None, limit=100):
        """Resumable append feed. Persist next_cursor only AFTER processing rows.

        Source and analysis feeds advance separately. Ordering is receipt order,
        not a training clock. Graph feed headers point to graphs/nodes/edges.
        """
        if feed not in FEEDS: raise InputError('Unknown feed; choose ' + ', '.join(FEEDS))
        _integer(limit, 'limit', high=10000)
        table, identity, document, timestamp = FEEDS[feed]
        with self.snapshot() as s:
            if s.frozen: raise InputError('A research snapshot has no live change feeds; follow the original workspace')
            if not s.feed_available(feed):raise InputError('This feed is unavailable; upgrade the collector first')
            after = 0
            if cursor is not None:
                if not isinstance(cursor, dict) or cursor.get('schema') != VERSION or cursor.get('feed') != feed:
                    raise InputError('Cursor does not match this feed and schema')
                after = _integer(cursor.get('after'), 'cursor.after', low=0, high=2**63-1)
                anchor = s.c.execute(f'SELECT {identity} FROM {table} WHERE rowid=?', (after,)).fetchone()
                if (after and (not anchor or anchor[0] != cursor.get('anchor'))) or (not after and cursor.get('anchor') is not None):
                    raise InputError('Cursor anchor differs: wrong workspace or rewritten history; restart this feed explicitly')
            rows = s.c.execute(f'SELECT rowid seq,{identity} id,{document} document,{timestamp} recorded_at FROM {table} WHERE rowid>? ORDER BY rowid LIMIT ?', (after, limit+1))
            page=[]; size=0; has_more=False
            for row in rows:
                if len(page)==limit: has_more=True; break
                length=len(row['document'].encode('utf-8'))
                if size+length>FEED_MAX_BYTES:
                    if not page: raise InputError('One feed record exceeds the 32 MiB page budget; use a narrower table projection')
                    has_more=True; break
                page.append(row);size+=length
            next_cursor = {'schema': VERSION, 'feed': feed, 'after': page[-1]['seq'] if page else after,
                           'anchor': page[-1]['id'] if page else (cursor or {}).get('anchor')}
            return {'schema': VERSION, 'feed': feed, 'captured_at': s.captured_at,
                    'rows': [{'sequence': r['seq'], 'id': r['id'], 'recorded_at': r['recorded_at'], 'document': json.loads(r['document'])} for r in page],
                    'next_cursor': next_cursor, 'has_more': has_more,
                    'order': 'Receipt order in this workspace, not training order. Analysis feeds advance independently.'}

    def export(self, destination, *, tables=DEFAULT_TABLES, format='jsonl', experiment=None, history=False, observer=None, max_rows=100000, max_bytes=100*1024*1024):
        """Publish a new ZIP with one consistent snapshot, tables and manifest.

        Refuse truncation or replacement. JSON columns remain JSON strings in
        tabular rows. CSV preserves exact text; use JSONL for programmatic work.
        """
        if format not in {'jsonl', 'csv'}: raise InputError('Export format must be jsonl or csv')
        _integer(max_rows, 'max_rows'); _integer(max_bytes, 'max_bytes', high=1024**3)
        tables = list(tables)
        if not tables or len(tables) != len(set(tables)) or any(n not in VIEWS for n in tables):
            raise InputError('Choose distinct supported analysis tables')
        destination = Path(destination).expanduser().resolve()
        if destination.exists(): raise InputError('Export destination already exists; choose a new filename')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.jev-analysis-', dir=destination.parent) as temp:
            tmp = Path(temp)/'analysis.zip'; size = 0
            with self.snapshot() as s, zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                manifest = {'schema': VERSION, 'captured_at': s.captured_at, 'scope': {'experiment':experiment, 'history':history},
                            'format': format, 'tables': {}, 'inference': 'none; saved results only',
                            'note': 'Latest means latest saved, not recomputed or complete. Metadata clocks retain their source meanings. Missing evidence is not zero. CSV empty numeric cells are null; JSONL preserves null and exact types.'}
                if observer is not None:
                    manifest['scope']['observer'] = observer
                    manifest['observer_filtered_tables'] = [n for n in tables if n in OBSERVER_TABLES]
                    manifest['context_tables'] = [n for n in tables if n not in OBSERVER_TABLES]
                for name in tables:
                    result = s.table(name, experiment=experiment, history=history,
                                     observer=observer if name in OBSERVER_TABLES else None, limit=max_rows)
                    if result['truncated']: raise InputError(f'{name} exceeds max_rows; narrow the experiment or export by SQL in smaller batches')
                    content = encode(result, format)
                    size += len(content)
                    if size > max_bytes: raise InputError('Export exceeds byte limit; narrow the scope or selected tables')
                    filename = name+'.'+format; archive.writestr(filename, content)
                    manifest['tables'][name] = {'file':filename,'rows':len(result['rows']),'columns':result['columns'],
                        'grain':GRAINS[name], 'available':s.available(name), 'bytes':len(content), 'sha256':hashlib.sha256(content).hexdigest()}
                archive.writestr('manifest.json', json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
            # Atomic publication without replacing an existing destination.
            os.link(tmp, destination)
        return {**manifest, 'path':str(destination)}


class Snapshot:
    def __init__(self, connection, *, frozen=False, manifest=None, unavailable=(), unavailable_feeds=(), source_coverage=None):
        self.c = connection
        self.frozen = frozen
        self.manifest = manifest
        self.unavailable = set(unavailable)
        self.unavailable_feeds = set(unavailable_feeds)
        self.source_coverage = source_coverage or {}
        self.captured_at = datetime.now(timezone.utc).isoformat()

    def catalog(self):
        return {'schema': VERSION, 'captured_at': self.captured_at, 'feeds': [] if self.frozen else [n for n in FEEDS if self.feed_available(n)],
                'frozen': self.frozen,
                'dataset': self.manifest,
                'export_profiles': {k:list(v) for k,v in EXPORT_PROFILES.items()},
                'tables': [{'name':n, 'sql_view':'rl_'+n, 'grain':GRAINS[n], 'available':self.available(n),
                            'source_coverage':self.source_coverage.get(n),
                            'observer_filter':n in OBSERVER_TABLES,
                            'columns':[r[1] for r in self.c.execute(f'PRAGMA table_info(rl_{n})')]} for n in VIEWS],
                'note':'Saved results only. Table access defaults to latest source/artifact versions and input-current measurements and monitor values. Raw SQL exposes history; use is_current for measurements and monitor values, is_latest for other artifacts. Frozen flags describe the export snapshot. Reads never run monitors or observers.'}

    def available(self, name):
        return name not in self.unavailable

    def feed_available(self, name):
        return not self.frozen and name not in self.unavailable_feeds

    def options(self, *, experiment=None, history=False):
        if type(history) is not bool: raise InputError('history must be boolean')
        if experiment is not None and (not isinstance(experiment,str) or not experiment): raise InputError('experiment must be a nonempty string')
        latest = '' if history else ' WHERE is_latest=1'
        experiments = self.query('''WITH populations AS (
          SELECT experiment,1 snapshots,0 execution_attempts FROM rl_rollouts'''+latest+'''
          UNION ALL SELECT experiment,0,1 FROM rl_executions WHERE is_latest=1
          UNION ALL SELECT experiment,0,0 FROM rl_generation_cohorts WHERE is_latest=1)
          SELECT experiment,sum(snapshots) snapshots,sum(execution_attempts) execution_attempts
          FROM populations GROUP BY experiment ORDER BY experiment''',limit=1000)
        conditions = [] if history else ['r.is_latest=1']
        parameters = []
        if experiment is not None: conditions.append('r.experiment=?');parameters.append(experiment)
        where = ' WHERE '+' AND '.join(conditions) if conditions else ''
        # Count saved artifacts, not flattened metric rows or inferred coverage.
        observers = self.query('''WITH scoped AS (SELECT r.run_id FROM rl_rollouts r'''+where+'''),
          observed AS (
            SELECT g.observer,g.run_id,json_extract(g.header_json,'$.observer_label') label
              FROM rl_graphs g JOIN scoped s USING(run_id)'''+(' WHERE g.is_latest=1' if not history else '')+'''
            UNION SELECT m.observer,m.run_id,NULL label FROM rl_measurements m JOIN scoped s USING(run_id)
            UNION SELECT v.observer,v.run_id,NULL label FROM rl_monitor_values v JOIN scoped s USING(run_id))
          SELECT observer,count(DISTINCT run_id) snapshots,min(NULLIF(label,'')) label
            FROM observed GROUP BY observer ORDER BY observer''',parameters,limit=1000)
        return {'schema':VERSION,'captured_at':self.captured_at,'experiments':experiments['rows'],
                'observers':observers['rows'],'truncated':experiments['truncated'] or observers['truncated'],
                'note':'Counts describe saved source snapshots with records, not annotation completeness or independent training samples.'}

    def query(self, sql, parameters=(), *, limit=1000):
        _integer(limit, 'limit')
        if not isinstance(sql, str) or not sql.strip() or len(sql)>100000: raise InputError('Supply bounded SQL text')
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
        def authorize(action, a, b, database, trigger):
            if action == sqlite3.SQLITE_FUNCTION and (b or '').lower() in {'load_extension','writefile','readfile'}: return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
        deadline = time.monotonic()+10
        self.c.set_authorizer(authorize)
        self.c.set_progress_handler(lambda: int(time.monotonic()>deadline), 1000)
        try:
            cur = self.c.execute(sql, parameters)
            if not cur.description: raise InputError('Analysis SQL must return rows')
            columns = [d[0] for d in cur.description]
            if len(columns) != len(set(columns)): raise InputError('Use distinct column aliases; duplicate names would lose data')
            rows = []; size = 0
            for row in cur:
                try: size += len(json.dumps(dict(row),ensure_ascii=False).encode('utf-8'))
                except TypeError as exc: raise InputError('Use hex() or text casts for binary query values') from exc
                if size > 32*1024*1024: raise InputError('Query exceeds the 32 MiB result budget; narrow selected columns or rows')
                rows.append(row)
                if len(rows)>limit: break
            return {'schema': VERSION, 'captured_at': self.captured_at, 'columns':columns,
                    'rows':[dict(r) for r in rows[:limit]],'truncated':len(rows)>limit,'limit':limit}
        except sqlite3.Error as exc: raise InputError(f'Read-only analysis query failed: {exc}') from exc
        finally:
            self.c.set_authorizer(None); self.c.set_progress_handler(None, 0)

    def table(self, name, *, experiment=None, history=False, observer=None, limit=1000):
        sql, parameters = self._selection(name, experiment=experiment, history=history, observer=observer)
        result = self.query(sql, parameters, limit=limit)
        return {**result,'table':name,'available':self.available(name),'source_coverage':self.source_coverage.get(name),
                'scope':{'experiment':experiment,'history':history,'observer':observer},'grain':GRAINS[name]}

    def _selection(self, name, *, experiment=None, history=False, observer=None):
        if name not in VIEWS: raise InputError('Unknown analysis table')
        if type(history) is not bool: raise InputError('history must be boolean')
        if experiment is not None and (not isinstance(experiment,str) or not experiment): raise InputError('experiment must be a nonempty string')
        columns = [r[1] for r in self.c.execute(f'PRAGMA table_info(rl_{name})')]
        conditions=[]; parameters=[]
        # A late older graph publication must not replace the newest matching
        # metric input. Monitor values also require their published index.
        if not history and 'is_latest' in columns and name!='measurements': conditions.append('t.is_latest=1')
        if not history and name in {'monitor_values','measurements'} and 'is_current' in columns:conditions.append('t.is_current=1')
        if 'run_id' in columns:
            parts=['r.run_id=t.run_id']
            if not history: parts.append('r.is_latest=1')
            if experiment is not None: parts.append('r.experiment=?'); parameters.append(experiment)
            conditions.append('EXISTS(SELECT 1 FROM rl_rollouts r WHERE '+' AND '.join(parts)+')')
        elif name in {'training_records','executions','generation_cohorts','trainer_telemetry','run_capture'} and experiment is not None:
            conditions.append('t.experiment=?'); parameters.append(experiment)
        elif name == 'monitor_definitions' and experiment is not None:
            conditions.append('''EXISTS(SELECT 1 FROM rl_monitor_values v JOIN rl_rollouts r ON r.run_id=v.run_id
              WHERE v.monitor_id=t.monitor_id AND r.experiment=?'''+(' AND r.is_latest=1 AND v.is_latest=1' if not history else '')+')')
            parameters.append(experiment)
        if observer is not None:
            if 'observer' not in columns: raise InputError('This table does not have an observer column')
            conditions.append('t.observer=?'); parameters.append(observer)
        sql = 'SELECT t.* FROM rl_'+name+' t'+(' WHERE '+' AND '.join(conditions) if conditions else '')
        return sql, parameters


def encode(result, format):
    if format == 'json': return (json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    if format == 'jsonl': return ''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in result['rows']).encode('utf-8')
    if format == 'csv':
        stream=io.StringIO(newline=''); writer=csv.DictWriter(stream,fieldnames=result['columns']); writer.writeheader(); writer.writerows(result['rows'])
        return stream.getvalue().encode('utf-8')
    raise InputError('Choose json, jsonl or csv')
