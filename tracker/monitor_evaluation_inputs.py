"""Declared, source-bound evaluator inputs for code monitors.

Reports remain outside the agent trace. Selectors return every matching report;
no newest, best, or independent evaluator is inferred from arrival order.
"""
import json
import re

from . import evaluation_receipts as receipts
from .schema import InputError

KEY = 'rilldex_evaluations'
VERSION = 'monitor-evaluations/1'


def validate(selectors):
    if not isinstance(selectors,dict) or not 1<=len(selectors)<=16:
        raise InputError('Declare 1–16 named evaluator inputs')
    for name,selector in selectors.items():
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',name):
            raise InputError('Use short identifier names for evaluator inputs')
        if not isinstance(selector,dict) or set(selector)-{'purpose','producer','label','evaluator_sha256','criterion_sha256'}:
            raise InputError('Evaluator selectors use purpose, producer, label, evaluator_sha256 and criterion_sha256')
        if not isinstance(selector.get('purpose'),str) or selector['purpose'] not in receipts.PURPOSES:
            raise InputError('Evaluator input requires reward, independent_check or repair_check purpose')
        for key,value in selector.items():
            if key.endswith('_sha256'):receipts.identity(value,key)
            else:receipts.text(value,key)
    return selectors


def matches(record,selector):
    return all(((record.get('inputs',{}).get(key.removesuffix('_sha256')) or {}).get('sha256')
                if key.endswith('_sha256') else record.get(key))==value for key,value in selector.items())


def capture(store,spec,run_id,source_hash):
    selectors=spec.get('evaluations')
    if selectors is None:return None,{}
    validate(selectors)
    with store.connect() as c:
        rows=c.execute('SELECT id,document FROM evaluation_receipts WHERE run_id=? ORDER BY id',(run_id,)).fetchall()
    selected={name:[] for name in selectors}
    for row in rows:
        record=json.loads(row['document'])
        if record.get('source_hash')!=source_hash:continue
        names=[name for name,selector in selectors.items() if matches(record,selector)]
        if not names:continue
        record=receipts.decode(row['id'],row['document'])
        for name in names:selected[name].append(record)
    dependency=dict(schema=VERSION,sets={name:[r['id'] for r in records] for name,records in selected.items()})
    return dependency,selected


def pinned(store,spec,run_id,source_hash,dependencies):
    """Read the original selection; current arrivals must not alter a receipt."""
    selectors=spec.get('evaluations');saved=dependencies.get(KEY)
    if selectors is None:
        if saved is not None:raise InputError('Evaluator dependencies require declared evaluator inputs')
        return {}
    validate(selectors)
    if not isinstance(saved,dict) or set(saved)!={'schema','sets'} or saved.get('schema')!=VERSION:
        raise InputError('Missing evaluator input snapshot')
    sets=saved['sets']
    if not isinstance(sets,dict) or set(sets)!=set(selectors):raise InputError('Evaluator snapshot differs from its selectors')
    selected={}
    for name,ids in sets.items():
        if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids) or ids!=sorted(set(ids)):
            raise InputError('Evaluator input IDs must be sorted and distinct')
        selected[name]=[]
        for identifier in ids:
            record=receipts.read(store,identifier)
            if record['run_id']!=run_id or record['source_hash']!=source_hash or not matches(record,selectors[name]):
                raise InputError('Evaluator report does not match its saved source and selector')
            selected[name].append(record)
    return selected


def validate_evidence(result,selected):
    ids=result.get('evaluation_ids',[])
    if not isinstance(ids,list) or len(ids)>32 or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):
        raise InputError('Attach at most 32 distinct evaluator report IDs')
    known={r['id'] for records in selected.values() for r in records}
    if set(ids)-known:raise InputError('Evaluator evidence is outside the pinned monitor inputs')


def evidence(result,selected):
    validate_evidence(result,selected)
    ids=set(result.get('evaluation_ids',[]));by_id={r['id']:r for records in selected.values() for r in records}
    return [dict(receipt=by_id[i],inputs=[name for name,rows in selected.items() if any(r['id']==i for r in rows)])
            for i in sorted(ids)]


def compare(selected,left,right):
    if left not in selected or right not in selected or left==right:
        raise InputError('Select two distinct declared evaluator input names')
    a,b=selected[left],selected[right]
    if len(a)!=1 or len(b)!=1:
        return dict(status='missing_reports' if not a or not b else 'ambiguous_reports',
                    counts={left:len(a),right:len(b)},
                    boundary='Comparison needs one explicitly selected report per input; no latest report is chosen.')
    if a[0]['id']==b[0]['id']:
        return dict(status='same_report',boundary='Both inputs select the same evaluation report.')
    return receipts.compare(a[0],b[0])
