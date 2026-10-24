"""Live, scoped research functions over the workspace's relational property graph.

SQLite owns ingestion and immutable evidence. These functions open short read
snapshots; they do not export, migrate, annotate or call a model. Custom Python
runs after releasing the source snapshot, with its results in a managed sidecar.
"""
from dataclasses import dataclass
import json
from pathlib import Path

from .analytics import Analysis, VIEWS, OBSERVER_TABLES, GRAINS
from .schema import InputError


def decoded(row):
    result = {}
    for key, value in row.items():
        name = key[:-5] if key.endswith('_json') else key
        if name in result or name != key and name in row:
            raise InputError('JSON field aliases collide; give the SQL columns distinct names')
        if key.endswith('_json') and isinstance(value, str):
            try: value = json.loads(value)
            except ValueError: pass
        result[name] = value
    return result


class TableResult(dict):
    """JSON-compatible result with decoded records and optional dataframe conversion."""
    def __init__(self, result):
        super().__init__(result)
        self['rows'] = [decoded(row) for row in result['rows']]
        self['columns'] = [c[:-5] if c.endswith('_json') else c for c in result['columns']]
        if len(self['columns']) != len(set(self['columns'])):raise InputError('Decoded column names collide')

    @property
    def rows(self): return self['rows']

    def to_pandas(self):
        if self.get('truncated'):raise InputError('Result is truncated; narrow the scope or raise limit before dataframe analysis')
        import pandas as pd
        return pd.DataFrame.from_records(self.rows, columns=self['columns'])

    def to_polars(self):
        if self.get('truncated'):raise InputError('Result is truncated; narrow the scope or raise limit before dataframe analysis')
        import polars as pl
        return pl.from_dicts(self.rows, infer_schema_length=None) if self.rows else pl.DataFrame({c:[] for c in self['columns']})


@dataclass
class GraphResult:
    graph_id: str
    header: dict
    nodes: list
    edges: list
    captured_at: str

    def connections(self, node_id, *, direction='out', relation=None):
        """Return all typed edges, retaining parallel links and their evidence."""
        if direction not in ('out','in','both'):raise InputError('direction must be out, in or both')
        if not any(n['id']==node_id for n in self.nodes):raise InputError('Unknown node in this graph')
        return [e for e in self.edges if (relation is None or e['type']==relation) and
                ((direction in ('out','both') and e['source']==node_id) or
                 (direction in ('in','both') and e['target']==node_id))]

    def to_networkx(self):
        import networkx as nx
        graph=nx.MultiDiGraph(graph_id=self.graph_id, header=self.header, captured_at=self.captured_at)
        for node in self.nodes:graph.add_node(node['id'],**{k:v for k,v in node.items() if k!='id'})
        for edge in self.edges:
            graph.add_edge(edge['source'],edge['target'],key=edge['id'],**{k:v for k,v in edge.items() if k not in ('id','source','target')})
        return graph


FUNCTIONS = {
    'activity_counts': {
        'label':'Unit activities', 'question':'Which semantic activities are recorded?',
        'table':'nodes', 'grain':'Observation set × unit activity',
        'sql':'''SELECT observer,activity,COUNT(*) units,COUNT(DISTINCT run_id) rollouts
          FROM nodes WHERE kind='unit' AND activity IS NOT NULL
          GROUP BY observer,activity ORDER BY observer,units DESC,activity''',
        'boundary':'Only saved semantic units with an activity. Source events and missing annotations are not activity observations.'},
    'relation_counts': {
        'label':'Connected activities', 'question':'What links are recorded between activities and other nodes?',
        'table':'edges', 'grain':'Observation set × edge type × source/target kind and activity',
        'sql':'''SELECT e.observer,e.type,s.kind source_kind,s.activity source_activity,
          t.kind target_kind,t.activity target_activity,COUNT(*) links,COUNT(DISTINCT e.run_id) rollouts
          FROM edges e JOIN nodes s ON s.graph_id=e.graph_id AND s.node_id=e.source
          JOIN nodes t ON t.graph_id=e.graph_id AND t.node_id=e.target
          GROUP BY e.observer,e.type,s.kind,s.activity,t.kind,t.activity
          ORDER BY e.observer,links DESC,e.type,s.kind,s.activity,t.kind,t.activity''',
        'boundary':'Typed saved links, not inferred causality or a recovery rate. Nodes join by graph_id and node_id.'},
    'metric_availability': {
        'label':'Metric coverage', 'question':'Which measurements are available, and which are missing?',
        'table':'measurements', 'grain':'Observation set × metric × recorded status',
        'sql':'''SELECT observer,metric,status,COUNT(*) records,
          SUM(CASE WHEN value IS NULL THEN 1 ELSE 0 END) missing_values,
          COUNT(DISTINCT run_id) rollouts FROM measurements
          GROUP BY observer,metric,status ORDER BY observer,metric,status''',
        'boundary':'Coverage of saved measurement rows. Absent rows and null values are not zeros; status meanings are retained.'},
    'recorded_outcomes': {
        'label':'Recorded outcomes', 'question':'What verified outcomes are recorded in this population?',
        'table':'rollouts', 'grain':'Experiment × recorded verified outcome',
        'sql':'''SELECT experiment,verified_success,COUNT(*) snapshots FROM rollouts
          GROUP BY experiment,verified_success ORDER BY experiment,verified_success''',
        'boundary':'Counts source snapshots. Null means no verified outcome; reward and reported completion are different facts.'},
}


class Workspace:
    """One entry point for live tables, graphs, native functions and custom Python.

Scope applies to table access and the named CTEs in sql(): rollouts, nodes, edges,
measurements, etc. Low-level rl_* views retain their existing unscoped semantics.
Each call sees fresh committed data; joins within one call share a read snapshot.
"""
    def __init__(self, path, *, experiment=None, observer=None, history=False):
        self.data=Analysis(path)
        for name,value in [('experiment',experiment),('observer',observer)]:
            if value is not None and (not isinstance(value,str) or not value.strip()):raise InputError(name+' must be nonempty text')
        if type(history) is not bool:raise InputError('history must be boolean')
        self.scope=dict(experiment=experiment,observer=observer,history=history)
        self.results_path=self.data.path.with_name(self.data.path.stem+'.analysis.sqlite')

    @staticmethod
    def functions():
        return [{'name':name,**{k:v for k,v in item.items() if k!='sql'}} for name,item in FUNCTIONS.items()]

    def catalog(self): return self.data.catalog()

    def options(self):
        """Discover experiment names and saved observation sets without a UI."""
        return self.data.options(experiment=self.scope['experiment'],history=self.scope['history'])

    def compare_rollouts(self, *, reference, selected, title='Rollout case comparison', hypothesis='',monitor_ids=None):
        """Save current source snapshots from two explicit selections for UI or code use.

        Each selection specifies its experiment; table-access scope is not applied.
        No inference is run. Open the returned ID in /investigate?saved=<id>.
        """
        from . import case_studies
        from .store import Store
        with self.data.snapshot() as source:
            if source.frozen: raise InputError('Saving a comparison requires the live workspace or a full restore')
        return case_studies.save(Store(self.data.path), dict(reference=reference, selected=selected, title=title, hypothesis=hypothesis,monitor_ids=monitor_ids))

    def compare_trainer_rollouts(self, *, reference, selected, title='Linked rollout comparison', hypothesis='',monitor_ids=None):
        """Save linked rollout evidence for two native metric intervals.

        Each side specifies series_id, as_of and optional start/end, taken from
        trainer_signals(). No rollout clock is inferred from trainer steps.
        """
        from . import trainer_case_studies
        from .store import Store
        with self.data.snapshot() as source:
            if source.frozen: raise InputError('Saving a comparison requires the live workspace or a full restore')
        return trainer_case_studies.save(Store(self.data.path),dict(reference=reference,selected=selected,title=title,hypothesis=hypothesis,monitor_ids=monitor_ids))

    def monitor(self,name,*,version,description,unit='value',aggregation='mean',config=None,group='Behavior',evaluations=None,alert=None):
        """Register a code-defined monitor whose saved results appear in the UI.

        Use .run(callback) for backfill and .follow(callback) for new rollouts.
        Callbacks run in your process and can use this workspace's SQL/graphs.
        """
        from .custom_monitors import CustomMonitor
        return CustomMonitor(self,name,version=version,description=description,unit=unit,
                             aggregation=aggregation,config=config,group=group,evaluations=evaluations,alert=alert)

    def reward_detector(self,name,*,version,description,reward_definition,inputs,
                        definition_path='/metadata/reward_definition',stage='custom',config=None,evaluations=None):
        """Register a reward-scoped rule; .run/.follow publish ordinary monitor values."""
        from .reward_detectors import RewardDetector
        return RewardDetector(self,name,version=version,description=description,reward_definition=reward_definition,
                              inputs=inputs,definition_path=definition_path,stage=stage,config=config,evaluations=evaluations)

    def cohort_readiness(self, *, environment=None, monitor=None, windows=None, include_members=False, clock=None, basis=None, limit=100, cohort_id=None, producer=None):
        """Live declared population evidence; observer scope constrains the monitor."""
        if self.scope['history']:raise InputError('Cohort readiness uses latest revisions; select history=False or query the declaration table')
        result=self.data.cohort_readiness(experiment=self.scope['experiment'],environment=environment,
            monitor=monitor,windows=windows,include_members=include_members,clock=clock,basis=basis,limit=limit,
            cohort_id=cohort_id,producer=producer)
        if monitor and self.scope['observer']:
            rows=self.table('monitor_definitions',monitor_id=monitor).rows
            if not rows:raise InputError('Monitor is outside this workspace observer scope')
        return result

    def _selection(self, saved, name):
        return saved._selection(name,**{k:v for k,v in self.scope.items() if k!='observer' or name in OBSERVER_TABLES})

    def _query(self,saved,sql,parameters=(),*,limit=1000):
        compiled,values=self._compile(saved,sql,parameters)
        return TableResult({**saved.query(compiled,values,limit=limit),'scope':self.scope})

    def _compile(self,saved,sql,parameters=()):
        if not isinstance(sql,str) or not sql.strip() or len(sql)>80000:raise InputError('Supply a bounded SELECT query')
        if not isinstance(parameters,(list,tuple)):raise InputError('Use positional SQL parameters')
        ctes=[];values=[]
        for name in VIEWS:
            selection,bound=self._selection(saved,name)
            ctes.append(name+' AS ('+selection+')');values.extend(bound)
        # A subquery also accepts a caller's WITH query, without parsing SQL text.
        return 'WITH '+','.join(ctes)+' SELECT * FROM ('+sql.strip().removesuffix(';')+')',values+list(parameters)

    def sql(self,sql,parameters=(),*,limit=1000):
        with self.data.snapshot() as saved:return self._query(saved,sql,parameters,limit=limit)

    def table(self,name,*,limit=1000,**filters):
        if name not in VIEWS:raise InputError('Unknown workspace table')
        with self.data.snapshot() as saved:
            columns={r[1] for r in saved.c.execute('PRAGMA table_info(rl_'+name+')')}
            if not set(filters)<=columns:raise InputError('Filter names must be table columns')
            conditions=[];values=[]
            for key,value in filters.items():
                if not (value is None or isinstance(value,(str,int,float))):raise InputError('Filters must be scalar equality values')
                conditions.append('"'+key+'" IS ?');values.append(value)
            result=self._query(saved,'SELECT * FROM '+name+(' WHERE '+' AND '.join(conditions) if conditions else ''),values,limit=limit)
            result.update(table=name,grain=GRAINS[name],available=saved.available(name) and
                (not saved.frozen or saved.manifest['tables'].get(name,{}).get('included',False)),
                source_coverage=saved.source_coverage.get(name))
            return result

    def rollouts(self,**filters): return self.table('rollouts',**filters)
    def units(self,**filters): return self.table('nodes',kind='unit',**filters)
    def graphs(self,**filters): return self.table('graphs',**filters)
    def metrics(self,**filters): return self.table('measurements',**filters)

    def telemetry(self,**filters): return self.table('trainer_telemetry',**filters)

    def trainer_signals(self, **selection):
        """Full native curves with optional worker/session scope; builds the scalar index."""
        from .store import Store
        from .telemetry_queries import query
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Trainer signals require a full workspace database')
        return query(Store(self.data.path),experiment=self.scope['experiment'],environment=self.scope.get('environment'),**selection)

    def trainer_sessions(self, **selection):
        """Browse all captured trainer sessions independently of chart limits."""
        from .store import Store
        from .telemetry_queries import sessions
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Trainer sessions require a full workspace database')
        return sessions(Store(self.data.path),experiment=self.scope['experiment'],environment=self.scope.get('environment'),**selection)

    def trainer_context(self, *, producer, session, as_of=None):
        """Find process capture for an exact trainer session, using recorded links."""
        from .store import Store
        from .run_records import trainer_context
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Trainer context requires a full workspace database')
        return trainer_context(Store(self.data.path),experiment=self.scope['experiment'],producer=producer,session=session,as_of=as_of)

    def execution_view(self, *, saved=None, **selection):
        """Read synchronized execution evidence without running a UI or model."""
        from .store import ReadSnapshot
        from . import execution_timeline
        if not saved and not self.scope['experiment']:raise InputError('Select one experiment')
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Execution views require the live workspace or a full restore')
            store=ReadSnapshot(self.data.path,source.c)
            if saved:return execution_timeline.load(store,saved)
            return execution_timeline.snapshot(store,experiment=self.scope['experiment'],environment=self.scope.get('environment'),**selection)

    def telemetry_evidence(self,*,producer,record_id):
        """Resolve a native log's explicit use references in one read snapshot."""
        from .store import ReadSnapshot
        from .telemetry_evidence import evidence
        if not self.scope['experiment']:raise InputError('Select one experiment for native log evidence')
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Linked trainer evidence requires a live workspace or full restore')
            return evidence(ReadSnapshot(self.data.path,source.c),producer=producer,
                experiment=self.scope['experiment'],record_id=record_id)

    def relations(self,*,source_activity=None,target_activity=None,relation=None,limit=1000):
        clauses=[];values=[]
        for name,value in [('s.activity',source_activity),('t.activity',target_activity),('e.type',relation)]:
            if value is not None:clauses.append(name+'=?');values.append(value)
        return self.sql('''SELECT e.*,s.activity source_activity,t.activity target_activity,
          s.kind source_kind,t.kind target_kind FROM edges e
          JOIN nodes s ON s.graph_id=e.graph_id AND s.node_id=e.source
          JOIN nodes t ON t.graph_id=e.graph_id AND t.node_id=e.target'''+
          (' WHERE '+' AND '.join(clauses) if clauses else ''),values,limit=limit)

    def analyze(self,name,*,limit=1000):
        if name not in FUNCTIONS:raise InputError('Unknown analysis function')
        item=FUNCTIONS[name]
        with self.data.snapshot() as saved:
            result=self._query(saved,item['sql'],limit=limit)
            coverage=self._query(saved,'''SELECT (SELECT count(*) FROM rollouts) source_snapshots,
              (SELECT count(*) FROM graphs) graph_versions,
              (SELECT count(DISTINCT run_id) FROM nodes WHERE kind='unit' AND activity IS NOT NULL) rollouts_with_tagged_units,
              (SELECT count(*) FROM nodes WHERE kind='unit' AND activity IS NOT NULL) tagged_units''').rows[0]
            result.update(function=name,grain=item['grain'],boundary=item['boundary'],coverage=coverage)
            return result

    def activity_counts(self,**options):return self.analyze('activity_counts',**options)
    def relation_counts(self,**options):return self.analyze('relation_counts',**options)
    def metric_availability(self,**options):return self.analyze('metric_availability',**options)
    def recorded_outcomes(self,**options):return self.analyze('recorded_outcomes',**options)

    def metric_series(self,metric,*,limit=1000):
        return self.sql('''SELECT m.*,r.experiment,r.training_step,r.training_step_basis,
          r.generation_step,r.learner_step,r.policy_version FROM measurements m
          JOIN rollouts r USING(run_id) WHERE m.metric=? ORDER BY m.observer,r.training_step_basis,
          r.training_step,r.generation_step,m.run_id''',[metric],limit=limit)

    def compare_monitor(self,monitor_id,*,baseline,current,environment=None,save=False):
        """Compare inclusive step windows with exact cohorts and retained receipts.

        Uses this workspace's experiment. save=True publishes an immutable result
        to the live database; the default only reads. No model calls or exports.
        """
        from . import monitor_comparisons
        from .store import ReadSnapshot, Store
        if self.scope['history']:raise InputError('Window comparisons use latest rollout revisions; select history=False')
        if type(save) is not bool:raise InputError('save must be boolean')
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Window comparisons require a live workspace or full workspace restore')
            result=monitor_comparisons.capture(ReadSnapshot(self.data.path,source.c),monitor_id,
                baseline=baseline,current=current,experiment=self.scope['experiment'],environment=environment)
        if self.scope['observer'] and result['monitor']['observer']!=self.scope['observer']:
            raise InputError('Monitor is outside this observation scope')
        if save:
            from .schema import dumps
            with Store(self.data.path).connect() as c:
                c.execute('INSERT OR IGNORE INTO monitor_comparisons VALUES (?,?,?)',
                    (result['id'],dumps(result),result['captured_at']))
        return result

    def compare_behavior(self,*,saved=None,save=False,parent_id=None,title=None,**controls):
        """Compare saved behavior observations; optionally retain or reopen a capture.

        parent_id with save=True captures new evidence for the original windows.
        Category counts, coverage and source graph links are retained together.
        """
        from .store import Store
        from . import behavior_distributions as behavior
        if self.scope['history']:raise InputError('Behavior comparisons use latest rollout revisions; select history=False')
        if type(save) is not bool:raise InputError('save must be boolean')
        if saved and (save or parent_id or controls or title):raise InputError('Reopen a saved comparison without new controls')
        if parent_id and (not save or controls):raise InputError('Use parent_id with save=True and no new controls')
        if title is not None and not save:raise InputError('A title requires save=True')
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Behavior comparisons require a full workspace database')
        store=Store(self.data.path)
        existing=behavior.read_comparison(store,saved or parent_id) if saved or parent_id else None
        for key in ('experiment','observer'):
            scoped=self.scope[key]
            if scoped is not None:
                if existing and existing['controls'].get(key)!=scoped:raise InputError('Comparison is outside this '+key+' scope')
                if key in controls and controls[key]!=scoped:raise InputError('Comparison is outside this '+key+' scope')
                controls[key]=scoped
        if saved:return existing
        if save:return behavior.save_comparison(store,dict(parent_id=parent_id,title=title) if parent_id else dict(controls=controls,title=title))
        return behavior.snapshot(store,**controls)

    def investigate_interval(self,*,baseline,current,monitor_ids=None,environment=None,title=None,hypothesis='',save=True,parent_id=None):
        """Freeze linked outcome, population, training-use and behavior evidence.

        No export or inference. Late arrivals require another explicit capture.
        """
        from .store import Store, ReadSnapshot
        from .investigation_workspace import capture
        from .failure_investigations import persist
        if self.scope['history']:raise InputError('Use latest source revisions for interval capture')
        if type(save) is not bool:raise InputError('save must be boolean')
        raw=dict(experiment=self.scope['experiment'],baseline=baseline,current=current,environment=environment,hypothesis=hypothesis)
        if monitor_ids is not None:raw['monitor_ids']=monitor_ids
        if title:raw['title']=title
        if parent_id:raw['parent_id']=parent_id
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Interval investigations require a live workspace or full restore')
            if self.scope['observer']:
                from .monitoring import definitions
                allowed={m['id'] for m in definitions(ReadSnapshot(self.data.path,source.c)) if m['observer']==self.scope['observer']}
                if monitor_ids is not None and not set(monitor_ids)<=allowed:raise InputError('Monitor outside this observation scope')
                raw['monitor_ids']=sorted(allowed) if monitor_ids is None else monitor_ids
            value=capture(ReadSnapshot(self.data.path,source.c),raw)
        return persist(Store(self.data.path),value) if save else value

    def run_records(self, **filters):
        """Read console, hardware, runtime and file metadata directly from this workspace."""
        from .run_records import records
        from .store import Store
        with self.data.snapshot() as source:
            if source.frozen: raise InputError('Run capture requires a full workspace database')
        return records(Store(self.data.path),experiment=self.scope['experiment'],**filters)

    def hardware_history(self, **filters):
        """Read complete machine-sample statistics and bounded plots by process session."""
        from .hardware_history import query
        from .store import Store
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Hardware history requires a full workspace database')
        return query(Store(self.data.path),experiment=self.scope['experiment'],**filters)

    def download_file(self, sequence, destination, *, storage_options=None, opener=None):
        """Retrieve an embedded or referenced file on this Python host, checking recorded identity."""
        from .store import Store
        from .run_files import retrieve
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('File retrieval requires a full workspace database')
        return retrieve(Store(self.data.path),experiment=self.scope['experiment'],sequence=sequence,
            destination=destination,storage_options=storage_options,opener=opener)

    def organize(self, **labels):
        """Set this experiment's title, project, tags, notes, pinned or archived state."""
        from .run_records import organize
        from .store import Store
        with self.data.snapshot() as source:
            if source.frozen: raise InputError('Organization requires a full workspace database')
        return organize(Store(self.data.path),experiment=self.scope['experiment'],**labels)

    def organize_experiments(self, experiments, **changes):
        """Move, tag, pin or archive explicit experiments atomically in this workspace."""
        from .experiment_management import organize_many
        from .store import Store
        if self.scope['experiment'] and experiments != [self.scope['experiment']]:
            raise InputError('Use an unscoped Workspace to organize multiple experiments')
        with self.data.snapshot() as source:
            if source.frozen: raise InputError('Organization requires a full workspace database')
        return organize_many(Store(self.data.path), experiments=experiments, **changes)

    def compare_settings(self, experiments, **options):
        """Compare recorded snapshots; reuse returned source IDs to keep a comparison fixed."""
        from .configuration_comparison import compare
        from .store import ReadSnapshot
        if self.scope['experiment'] and any(e!=self.scope['experiment'] for e in experiments):
            raise InputError('Use an unscoped Workspace to compare runs')
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Settings comparison requires a full workspace database')
            return compare(ReadSnapshot(self.data.path,source.c),experiments=experiments,**options)

    def experiment_details(self, *, section='settings', environment=None, q='', limit=20, offset=0):
        """Page recorded settings, trainer streams or run history for this experiment."""
        from .experiment_details import details
        from .store import ReadSnapshot
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Run details require a full workspace database')
            return details(ReadSnapshot(self.data.path,source.c),experiment=self.scope['experiment'],
                environment=environment,section=section,q=q,limit=limit,offset=offset)

    def annotate_history(self,*,kind,title,detail,step,clock,basis,environment=None,investigation_id=None):
        """Append a researcher event on its explicit native clock."""
        from .investigation_workspace import annotate
        from .store import Store
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('History annotations require a live workspace')
        raw=dict(experiment=self.scope['experiment'],kind=kind,title=title,detail=detail,step=step,clock=clock,basis=basis)
        if environment:raw['environment']=environment
        if investigation_id:raw['investigation_id']=investigation_id
        return annotate(Store(self.data.path),raw)

    def saved_monitor_comparisons(self):
        """Most recent 100 saved window comparisons in this experiment."""
        from .monitor_comparisons import listing
        from .store import ReadSnapshot
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Saved comparisons require a live workspace or full workspace restore')
            result=listing(ReadSnapshot(self.data.path,source.c),self.scope['experiment'],self.scope['observer'])
        return result

    def monitor_comparison(self,identifier):
        """Reopen a pinned comparison without refreshing its population."""
        from .monitor_comparisons import read
        from .store import ReadSnapshot
        with self.data.snapshot() as source:
            if source.frozen:raise InputError('Saved comparisons require a live workspace or full workspace restore')
            result=read(ReadSnapshot(self.data.path,source.c),identifier)
        if (self.scope['experiment'] and result['scope']['experiment']!=self.scope['experiment'] or
                self.scope['observer'] and result['monitor']['observer']!=self.scope['observer']):
            raise InputError('Saved comparison is outside this workspace scope')
        return result

    def graph(self,graph_id,*,limit=100000):
        with self.data.snapshot() as saved:
            header=self._query(saved,'SELECT * FROM graphs WHERE graph_id=?',[graph_id],limit=1)
            if not header.rows:raise InputError('Graph is outside this scope or unavailable; select an explicit saved graph version')
            nodes=self._query(saved,'SELECT node_json FROM nodes WHERE graph_id=?',[graph_id],limit=limit)
            edges=self._query(saved,'SELECT edge_json FROM edges WHERE graph_id=?',[graph_id],limit=limit)
            if nodes['truncated'] or edges['truncated']:raise InputError('Graph exceeds limit; partial graphs are not returned')
            n=[r['node'] for r in nodes.rows];e=[r['edge'] for r in edges.rows];ids={r['id'] for r in n}
            if any(r['source'] not in ids or r['target'] not in ids for r in e):raise InputError('Graph contains dangling links')
            return GraphResult(graph_id,header.rows[0],n,e,saved.captured_at)

    def extract_work_contents(self, graph_id, unit_id, directory, *, candidate_calls=0,
                              decision_calls=0, input_bytes=0, **options):
        """Inspect one saved semantic unit with resumable local/API generation.

        Saves experimental contents/qualifications after every stage and scope
        decision. The existing graph is unchanged; its unit inspector can read
        these records without another model call.
        Budgets are lifetime totals for the directory; no export is required.
        relations=True adds paged local relationship selection without another
        generative proposal call. Existing contents and attributes are reused.
        """
        from rilldex.scopes import extract
        from .work_mentions import packet
        from . import work_content_results
        from .store import Store
        with self.data.snapshot() as snapshot:
            if snapshot.frozen:
                raise InputError('Extract into the original workspace; portable snapshots are read-only')
        captured = self.graph(graph_id)
        graph = dict(captured.header['header'], nodes=captured.nodes, edges=captured.edges)
        prepared=packet(graph,[unit_id]);store=Store(self.data.path)
        observer=options.pop('on_progress',None);saved={}
        if observer is not None and not callable(observer):raise InputError('on_progress must be callable')
        def progress(result):
            saved.update(work_content_results.save(store,graph,prepared,result,syntax=options.get('syntax')))
            if observer:observer(result)
        result=extract(prepared,unit_id,directory,candidate_calls=candidate_calls,
                       decision_calls=decision_calls,input_bytes=input_bytes,on_progress=progress,**options)
        return dict(result,saved=saved)

    def work_contents(self, graph_id, unit_id=None):
        """Read saved extraction progress and attachments without calling models."""
        from .work_content_results import for_graph
        from .store import ReadSnapshot
        captured=self.graph(graph_id)
        if unit_id is not None and not any(n['id']==unit_id and n['kind']=='unit' for n in captured.nodes):
            raise InputError('Unknown unit in this graph')
        graph=dict(captured.header['header'],nodes=captured.nodes,edges=captured.edges)
        with self.data.snapshot() as snapshot:
            if snapshot.frozen:
                raise InputError('Use content_extractions, work_contents, work_attachments and work_content_relations tables in a portable snapshot')
            return for_graph(ReadSnapshot(self.data.path,snapshot.c),graph,unit_id)

    def work_structure(self, graph_id, *, cutoff_event_id=None, limit=100000):
        """Branch effort and decision windows from one exact scoped graph.

        Same projection as the map; no export, writes or model calls. Partial
        graphs are rejected. A cutoff limits evidence, not annotation hindsight.
        """
        from .work_structure_metrics import project
        captured = self.graph(graph_id, limit=limit)
        graph = dict(captured.header['header'], nodes=captured.nodes, edges=captured.edges)
        return project(graph, cutoff_event_id)

    def repeated_work(self, graph_id, *, limit=100000):
        """Compare inputs and feedback for saved same-work pairs, without model calls."""
        from .repeated_work import project
        captured = self.graph(graph_id, limit=limit)
        return project(dict(captured.header['header'], nodes=captured.nodes, edges=captured.edges))

    def map_foundation(self, graph_id, *, limit=100000):
        """Audit exact source anchors and necessary relationship boundaries.

        This is not a semantic accuracy score. Works on complete scoped graph
        snapshots, including exports with embedded source events.
        """
        from .map_foundation import inspect
        captured=self.graph(graph_id,limit=limit)
        return inspect(dict(captured.header['header'],nodes=captured.nodes,edges=captured.edges))

    def feedback_followthrough(self, graph_id, *, cutoff_event_id=None, limit=100000):
        """Saved feedback → reference → next dispatch/output, without inference.

        Returns evidence cases, not a recovery rate. Each call reads one scoped
        immutable graph; newer source revisions require their own graph ID.
        """
        from .feedback_followthrough import project
        captured = self.graph(graph_id, limit=limit)
        return project(dict(captured.header['header'], nodes=captured.nodes, edges=captured.edges), cutoff_event_id)

    def request_evidence(self, graph_id, *, cutoff_event_id=None, limit=100000):
        """Requested-check versions, attempted operations and response evidence.

        A response judged sufficient need not be a passing test. This reads
        saved judgments only; missing annotations remain explicit.
        """
        from .request_evidence import project
        captured = self.graph(graph_id, limit=limit)
        return project(dict(captured.header['header'], nodes=captured.nodes, edges=captured.edges), cutoff_event_id)

    def work_state(self, run_id):
        """Recorded checks, inputs and verification at delivery, without inference.

        Conflicting applicable outcomes retain their witnesses and remain unknown.
        Requires original source capture; the workspace experiment scope applies.
        """
        from .work_state import derive
        with self.data.snapshot() as saved:
            if saved.frozen:
                raise InputError('Work-state analysis requires original sources in a live or restored workspace')
            rows=self._query(saved,'SELECT run_id FROM rollouts WHERE run_id=?',[run_id],limit=1)
            if not rows.rows:raise InputError('Rollout is outside this workspace scope or unavailable')
            run=json.loads(saved.c.execute('SELECT document FROM runs WHERE id=?',(run_id,)).fetchone()[0])
        return derive(run)

    def _evaluation_scope(self, saved, run_id):
        if saved.frozen:
            raise InputError('Evaluation receipts require a live or restored workspace with original sources')
        if not self._query(saved, 'SELECT run_id FROM rollouts WHERE run_id=?', [run_id], limit=1).rows:
            raise InputError('Rollout is outside this workspace scope or unavailable')

    def record_evaluation(self, receipt):
        """Save a producer-reported check; never execute it or overwrite reward."""
        from .evaluation_receipts import receive, validate
        from .store import Store
        validate(receipt)
        with self.data.snapshot() as saved:
            self._evaluation_scope(saved, receipt['run_id'])
        return receive(Store(self.data.path), receipt)

    def cite_source(self, run_id, event_id, *, role, quote=None, start=None, end=None):
        """Exact source citation for an evaluation report; no semantic judgment.

        Use a unique quote, explicit Python codepoint offsets, or the whole event.
        Role labels are supplied by the caller, not inferred by this helper.
        """
        from .evaluation_receipts import cite_source
        with self.data.snapshot() as saved:
            self._evaluation_scope(saved, run_id)
            run = json.loads(saved.c.execute('SELECT document FROM runs WHERE id=?', [run_id]).fetchone()[0])
        return cite_source(run, event_id, role=role, quote=quote, start=start, end=end)

    def evaluations(self, run_id, *, limit=50, offset=0):
        """Page immutable evaluation reports for a rollout in this workspace scope."""
        from .evaluation_receipts import listing
        from .store import ReadSnapshot
        with self.data.snapshot() as saved:
            self._evaluation_scope(saved, run_id)
            return listing(ReadSnapshot(self.data.path, saved.c), run_id=run_id, limit=limit, offset=offset)

    def training_exposure(self, run_id, *, source_hash=None):
        """Exact-source selection and recorded use, ready to freeze in a finding."""
        from .training_exposure import snapshot
        from .store import ReadSnapshot
        with self.data.snapshot() as saved:
            self._evaluation_scope(saved, run_id)
            return snapshot(ReadSnapshot(self.data.path, saved.c), run_id=run_id,
                            source_hash=source_hash, experiment=self.scope['experiment'])

    def compare_evaluations(self, ids):
        """Compare declared inputs and verdicts; disagreement is not a diagnosis."""
        from .evaluation_receipts import compare_ids
        from .store import ReadSnapshot
        with self.data.snapshot() as saved:
            if saved.frozen:
                raise InputError('Evaluation receipts require a live or restored workspace with original sources')
            result = compare_ids(ReadSnapshot(self.data.path, saved.c), ids)
            for receipt in result['records']:
                self._evaluation_scope(saved, receipt['run_id'])
            return result

    def search_evidence(self, run_id, *, anchor, text=None, questions=None, strategy='source', limit=8, max_chars=16000, cursor=None):
        """Earlier source passages and native response context, without export or inference.

        The selected source revision must be present in this workspace scope.
        Search results are candidates for inspection, never new graph relations.
        Optional questions share one match/text budget and report their retained
        candidates separately. A retained candidate does not answer a question.
        Pass pagination.next_cursor with unchanged arguments for another bounded
        page. Set a page/character budget in calling code; exhaustion is not proof
        that all relevant evidence has been found.
        """
        from .source_evidence import search
        with self.data.snapshot() as saved:
            if saved.frozen:
                raise InputError('Evidence search requires original sources in a live or restored workspace')
            rows = self._query(saved, 'SELECT run_id FROM rollouts WHERE run_id=?', [run_id], limit=1)
            if not rows.rows:
                raise InputError('Rollout is outside this workspace scope or unavailable')
            run = json.loads(saved.c.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()[0])
        query = dict(anchor=anchor, limit=limit, max_chars=max_chars)
        if text is not None: query['text'] = text
        if questions is not None: query['questions'] = questions
        if strategy != 'source': query['strategy'] = strategy
        if cursor is not None: query['cursor'] = cursor
        return search(run, query)

    def review_conditions(self, run_id, graph_id, *, anchor, question_ids=None,
                          source_types=None, strategy='source', limit=8, max_chars=16000, cursor=None):
        """List saved terms at a cutoff, or retrieve candidates for selected terms.

        No model calls or export. Empty selection returns the complete question
        catalog and historical versions. Select at most eight returned question
        IDs per search. Verdicts remain not_assessed, including when text matches.
        """
        from .requested_evidence import review
        selected = self.graph(graph_id)
        graph = dict(selected.header['header'], nodes=selected.nodes, edges=selected.edges)
        with self.data.snapshot() as saved:
            if saved.frozen:
                raise InputError('Condition review requires original sources in a live or restored workspace')
            rows = self._query(saved, 'SELECT run_id FROM rollouts WHERE run_id=?', [run_id], limit=1)
            if not rows.rows:
                raise InputError('Rollout is outside this workspace scope or unavailable')
            run = json.loads(saved.c.execute('SELECT document FROM runs WHERE id=?', (run_id,)).fetchone()[0])
        query = dict(anchor=anchor, question_ids=[] if question_ids is None else question_ids,
                     strategy=strategy, limit=limit, max_chars=max_chars)
        if source_types is not None: query['source_types'] = source_types
        if cursor is not None: query['cursor'] = cursor
        return review(run, graph, query)

    def annotation_changes(self, baseline_graph_id, current_graph_id, *, requirements=(), limit=100000):
        """Inspect annotation and metric changes on one immutable rollout source.

        Both graph IDs must be in this workspace scope. Leave observer unset to
        compare an original observer with a reviewed one. No exports or inference.
        """
        from .annotation_changes import compare
        before = self.graph(baseline_graph_id, limit=limit)
        after = self.graph(current_graph_id, limit=limit)
        return compare(dict(before.header['header'], nodes=before.nodes, edges=before.edges),
                       dict(after.header['header'], nodes=after.nodes, edges=after.edges),
                       requirements=requirements)

    def evaluate(self,name,function,*,version,sql='SELECT * FROM rollouts',parameters=(),key_columns=('run_id',),config=None,limit=1000):
        """Run local Python on scoped inputs. Cache/reuse and provenance use Research."""
        from .research import Research
        if not callable(function):raise InputError('Supply a local Python function')
        with self.data.snapshot() as saved:compiled,values=self._compile(saved,sql,parameters)
        lab=Research(self.data,self.results_path)
        return lab.evaluate(name,version,compiled,lambda row,cfg:function(decoded(row),cfg),
            parameters=values,key_columns=key_columns,config=config,limit=limit,skip_unchanged=True)

    def saved_analyses(self,*,limit=100):
        if not self.results_path.is_file():return {'rows':[],'truncated':False,'note':'No custom Python analyses saved in this workspace'}
        return self.results().batches(limit=limit)

    def results(self):
        from .research import Results
        saved=Results(self.results_path)
        if Path(saved.source).resolve()!=self.data.path:raise InputError('Analysis sidecar belongs to another workspace')
        return saved
