"""Open recorded check evidence using the existing cached analysis operators."""
from . import analysis_metrics, graph_store, investigation_plans
from .schema import InputError


def prepare_checks(store, request):
    if (not isinstance(request, dict) or set(request) != {'run_id', 'graph_id'}
            or any(not isinstance(v, str) or not v for v in request.values())):
        raise InputError('Select a rollout and its saved graph')
    graph = graph_store.read(store, request['graph_id'])
    if graph['run_id'] != request['run_id']:
        raise InputError('The saved graph belongs to a different rollout')
    spec = analysis_metrics.definition({'measure': 'criterion_recovery_window'})
    plan = analysis_metrics.projection_plan(spec, graph['run_id'], graph['source_hash'], graph['id'])
    result = investigation_plans.execute(store, plan)
    evidence = graph_store.read(store, result['outputs']['observation']['graph_id'])
    checks = [n for n in evidence['nodes'] if n['kind'] == 'check']
    return {'run_id': graph['run_id'], 'graph_id': evidence['id'], 'observer': evidence['observer'],
            'checks': len(checks), 'failed_checks': sum(n['properties']['result'] == 'failed' for n in checks),
            'execution': result['execution']}
