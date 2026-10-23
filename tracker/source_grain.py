"""Presentation-only source grain; does not rewrite retained traces or IDs."""


def describe(run):
    if run['adapter'] == 'weave':
        return {'id':'weave_trace', 'label':'Weave trace snapshot',
                'detail':'Calls grouped by project and trace ID. Native nesting and generated outputs are preserved; input history is context. Export completeness and training consumption are not established.'}
    if run['adapter'] == 'environment-episode':
        return {'id':'environment_episode', 'label':'Environment episode',
                'detail':'Ordered recorded transitions for one environment episode. Reset and ending evidence determine completeness; model text is captured only when supplied. Termination and reward do not establish success.'}
    if run['adapter'] == 'verl-generation':
        return {'id': 'generation_record', 'label': 'Generated response',
                'detail': 'One decoded input/output pair per record. It may be one turn in a longer episode. Prompt history stays context; episode continuity and complete episode counts are not established.'}
    return {'id': 'source_trace', 'label': 'Source trace',
            'detail': 'One imported trace document. Episode completeness depends on the source; a trace count is not a verified completed-episode count.'}
