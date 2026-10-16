"""Code-first analysis over saved evidence. No server, UI or model is required.

Analyzer runs the same deterministic operations used by investigations. Research
runs caller-owned Python on explicit SQL input rows and retains independent
results, input snapshots and batch membership in an ordinary SQLite database.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

from .analytics import Analysis
from .research_results import Results, VERSION, now
from .schema import InputError, digest, dumps

class _Evidence:
    def __init__(self, path): self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        try: yield connection
        finally: connection.close()


class Analyzer:
    """Built-in projections with dependency expansion, preflight and cache reuse."""
    def __init__(self, path):
        self.data = Analysis(path)
        with self.data.snapshot() as saved:
            if saved.frozen: raise InputError('Built-in execution requires the original workspace, not a table snapshot')
        self.evidence = _Evidence(self.data.path)

    @staticmethod
    def operations():
        from .investigation_plans import catalog
        return catalog()

    def plan(self, operation, run_id, *, graph_id=None, parameters=None):
        from . import investigation_plans as plans
        from .analysis_operations import REGISTRY
        source = plans.run_source(self.evidence, run_id)
        if parameters is not None and not isinstance(parameters,dict): raise InputError('parameters must be a JSON object')
        supplied = dict(parameters or {})
        if {'run_id','source_hash','graph_id'} & supplied.keys():
            raise InputError('Pass run_id and graph_id explicitly, not inside parameters')
        supplied.update(run_id=run_id, source_hash=digest(source))
        if graph_id is not None: supplied['graph_id'] = graph_id
        # Graph-consuming operators deliberately require an explicit saved graph.
        return REGISTRY.projection_plan(operation, supplied, schema=plans.VERSION)

    def execute(self, plan, *, check=False):
        from . import investigation_plans as plans
        from .store import Store
        preflight = plans.preflight(self.evidence, plan)
        if check: return preflight
        return plans.execute(Store(self.data.path), plan)

    def run(self, operation, run_id, *, graph_id=None, parameters=None, check=False):
        return self.execute(self.plan(operation, run_id, graph_id=graph_id, parameters=parameters), check=check)

    def saved(self, plan_id):
        """Read a saved plan and every exact output without re-executing it."""
        from . import investigation_plans as plans
        plan = plans.read_plan(self.evidence, plan_id)
        outputs = {}
        with self.evidence.connect() as connection:
            for node in plan['nodes']:
                row = connection.execute('SELECT document,output_hash FROM investigation_nodes WHERE id=?', (node['id'],)).fetchone()
                if not row: raise InputError('Saved analysis output is missing')
                value = json.loads(row[0])
                if digest(value) != row[1] or row[1] != node['output_hash']:
                    raise InputError('Saved analysis output hash differs')
                outputs[node['name']] = value
        return dict(id=plan_id, manifest=plan, outputs=outputs)

    def saved_plans(self, *, limit=1000):
        return self.data.query('''SELECT id plan_id,
          json_array_length(document,'$.nodes') step_count,
          json_extract(document,'$.definition') definition_json
          FROM investigation_plans ORDER BY rowid DESC''', limit=limit)


class Research(Results):
    """Run custom row analyses over SQL evidence; keep results outside the source.

The callback receives (input_row, config) and returns a finite JSON object.
Cache identity includes name/version, query/parameters, config and exact row.
Version external code/dependencies yourself. Hidden files, model changes and
network reads inside a callback are not discovered automatically.
"""
    def __init__(self, source, destination):
        self.data = source if isinstance(source, Analysis) else Analysis(source)
        self.path = Path(destination).expanduser().resolve()
        if self.path == self.data.path or self.path.exists() and os.path.samefile(self.path, self.data.path):
            raise InputError('Custom results must use a separate database from the source')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with self._exclusive():
                if not self.path.exists(): self._initialize()
        super().__init__(self.path)
        if Path(self.source).resolve() != self.data.path:
            raise InputError('Result database belongs to a different source; use Results for source-independent access')

    def _initialize(self):
        # Publish only a fully initialized database, never an empty/partial target.
        with tempfile.TemporaryDirectory(prefix='.jev-research-',dir=self.path.parent) as temp:
            staged = Path(temp)/'results.sqlite'
            connection = sqlite3.connect(staged)
            try:
                connection.executescript('''PRAGMA journal_mode=WAL;
                  CREATE TABLE research_identity(schema TEXT NOT NULL, source TEXT NOT NULL);
                  CREATE TABLE research_definitions(id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
                    definition_json TEXT NOT NULL, created_at TEXT NOT NULL);
                  CREATE TABLE research_results(id TEXT PRIMARY KEY, definition_id TEXT NOT NULL,
                    input_hash TEXT NOT NULL, input_key_json TEXT NOT NULL, input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL, output_hash TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(definition_id,input_hash));
                  CREATE TABLE research_batches(id TEXT PRIMARY KEY, definition_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT);
                  CREATE TABLE research_batch_items(batch_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    input_key_json TEXT NOT NULL, input_hash TEXT NOT NULL, input_json TEXT NOT NULL,
                    result_id TEXT, status TEXT NOT NULL, error TEXT, PRIMARY KEY(batch_id,ordinal));
                  CREATE INDEX research_result_definition ON research_results(definition_id,input_hash);
                  CREATE INDEX research_batch_definition ON research_batches(definition_id,created_at);
                ''')
                with connection:
                    connection.execute('INSERT INTO research_identity VALUES (?,?)', (VERSION,str(self.data.path)))
            finally: connection.close()
            os.link(staged,self.path)

    def query(self, sql, parameters=(), *, limit=1000):
        """Join rl_* evidence with custom.research_* results, read only.

The databases have independent commit clocks. Use retained input_json and batch
membership for historical analysis. Results(path).query needs no source at all.
"""
        with self.data.snapshot() as saved:
            saved.c.execute('ATTACH DATABASE ? AS custom', (self.path.as_uri()+'?mode=ro',))
            return saved.query(sql, parameters, limit=limit)

    def evaluate(self, name, version, sql, function, *, parameters=(), config=None,
                 key_columns, limit=1000, skip_unchanged=False):
        """Capture current SQL inputs, release the source reader, then run Python.

Successful rows commit independently and are reused by content identity.
Use resume(batch_id, function, version=...) to finish an exact retained batch.
With skip_unchanged=True, the latest complete batch for this definition is
returned when ordered membership and all input content are unchanged.
"""
        if not all(isinstance(x,str) and 0 < len(x) <= 256 for x in (name,version)):
            raise InputError('Supply a nonempty analysis name and explicit version (max 256 characters)')
        if not callable(function): raise InputError('Supply a Python callback')
        if type(skip_unchanged) is not bool: raise InputError('skip_unchanged must be boolean')
        if not isinstance(key_columns,(list,tuple)) or not key_columns or any(not isinstance(k,str) or not k for k in key_columns) or len(set(key_columns)) != len(key_columns):
            raise InputError('Supply distinct key_columns defining the input row grain')
        config = {} if config is None else config
        if not isinstance(config,dict): raise InputError('config must be a JSON object')
        definition = dict(schema=VERSION, name=name, version=version, sql=sql,
                          parameters=parameters, config=config, key_columns=list(key_columns))
        definition_json = dumps(definition)
        if len(definition_json.encode('utf-8')) > 1024**2: raise InputError('Analysis definition exceeds 1 MiB')
        definition_id = 'research-definition-'+digest(json.loads(definition_json))
        with self._exclusive():
            selected = self.query(sql, parameters, limit=limit)
            if selected['truncated']: raise InputError('Input query was truncated; narrow its scope or raise limit before running')
            if not set(key_columns) <= set(selected['columns']): raise InputError('key_columns are missing from the SQL result')
            inputs = []; keys = set()
            for row in selected['rows']:
                key = [row[k] for k in key_columns]
                if any(v is None for v in key): raise InputError('Input identity columns cannot be null')
                key_json = dumps(key)
                if key_json in keys: raise InputError('Duplicate input identity; choose key_columns matching the actual row grain')
                keys.add(key_json); inputs.append((key_json,digest(row),dumps(row)))
            if skip_unchanged:
                with self._connect() as connection:
                    previous = connection.execute('SELECT id,status FROM research_batches WHERE definition_id=? ORDER BY rowid DESC LIMIT 1', (definition_id,)).fetchone()
                    if previous and previous['status']=='complete':
                        batch = self._batch(connection,previous['id'])
                        retained = self._inputs(connection,batch)
                        if [(r['input_key_json'],r['input_hash'],r['input_json']) for r in retained] == inputs:
                            return self._run_batch(batch,retained,function)
            batch_id = 'research-batch-'+uuid.uuid4().hex
            with self._connect(write=True) as connection:
                connection.execute('INSERT OR IGNORE INTO research_definitions VALUES (?,?,?,?,?)',
                    (definition_id,name,version,definition_json,now()))
                connection.execute('INSERT INTO research_batches VALUES (?,?,?,?,?,NULL)',
                    (batch_id,definition_id,selected['captured_at'],'running',now()))
                connection.executemany('INSERT INTO research_batch_items VALUES (?,?,?,?,?,NULL,?,NULL)',
                    ((batch_id,index,key,sha,encoded,'pending') for index,(key,sha,encoded) in enumerate(inputs)))
            with self._connect() as connection:
                batch = self._batch(connection,batch_id)
                retained = self._inputs(connection,batch)
            return self._run_batch(batch,retained,function)
