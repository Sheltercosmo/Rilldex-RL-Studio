"""One navigation policy for saved maps; never an annotation quality ranking."""


def semantic(graph):
    coverage=graph.get('coverage',{})
    return (graph.get('observer')!='source'
            and coverage.get('semantic_relations') not in (None,'unavailable')
            and coverage.get('observation_kind')!='feedback-assessment')


def default(graphs):
    """Catalog order is saved registration order, not trajectory or training time."""
    latest=list(reversed(graphs))
    return (next((g for g in latest if semantic(g)),None)
            or next((g for g in latest if g.get('observer')=='source'),None)
            or next(iter(latest),None))


def reference(graph):
    return {k:graph[k] for k in ('id','observer','observer_label')} if graph else None
