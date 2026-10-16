"""Read-only SQL bindings for the same monitor inputs used by the dashboard.

The SQLite function is lazy and caches within one pinned read transaction. It
does not materialize values, run an observer, or invoke a custom callback.
"""
from . import monitoring, graph_store
from .store import ReadSnapshot


def register(connection,path):
    saved=ReadSnapshot(path,connection)
    context=None
    inputs_by_monitor={};expected={};measurement_ids=None

    def current_measurement(identifier):
        nonlocal measurement_ids
        if measurement_ids is None:
            from .measurement_lineage import resolve
            measurement_ids={r['id'] for r in resolve(saved,catalog=context['catalog'] if context else None)['records'].values()}
        return int(identifier in measurement_ids)

    def matches(monitor_id,run_id,input_hash):
        nonlocal context
        if not all(isinstance(value,str) for value in (monitor_id,run_id,input_hash)):return 0
        if context is None:
            context={'runs':{r['id']:r for r in monitoring.population(saved)},
                     'monitors':{m['id']:m for m in monitoring.definitions(saved)},
                     'catalog':graph_store.catalog(saved)}
        monitor=context['monitors'].get(monitor_id);run=context['runs'].get(run_id)
        if not monitor or not run or not monitoring.in_population(monitor,run):return 0
        if monitor_id not in inputs_by_monitor:
            inputs_by_monitor[monitor_id]=monitoring.observation_inputs(saved,monitor,context['catalog'])
        key=(monitor_id,run_id)
        if key not in expected:
            expected[key]=monitoring.observation_binding(monitor,run,inputs_by_monitor[monitor_id])['input_hash']
        return int(expected[key]==input_hash)

    connection.create_function('rilldex_monitor_input_current',3,matches)
    connection.create_function('rilldex_measurement_input_current',1,current_measurement)
