"""Portable authored decisions for method-comparison contract tests."""
from pathlib import Path

from tracker.semantic_extraction import read


def repeat_sample():
    control = read(Path(__file__).parent / 'fixtures/method-context-control.json')
    return control['run'], control['document']


def native_response(req, *, work='same_work_instance', procedure='same_procedure', basis='no_expressed_basis'):
    """Return explicit test choices; this is not an automatic classifier."""
    values = dict(work_instance=work, comparison=procedure, stated_basis=basis)
    return dict(model=req['model'], answers={
        key: dict(type='choice', probabilities={value: float(value == values[key]) for value in question['criteria']})
        for key, question in req['questions'].items()
    })
