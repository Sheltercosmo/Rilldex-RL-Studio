"""Audit retained real training traces and historical model decisions offline.

This deliberately cannot call a provider. It tests saved-decision replay and
publication, not fresh model accuracy or automatic streaming extraction.
"""
from collections import Counter
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tracker.schema import digest
from tracker.semantic_extraction import read, load_extraction
from tracker import semantic_collection, monitoring
from tracker.store import Store


def run(root, output):
    output.mkdir(parents=True,exist_ok=True)
    database=output/'workspace.sqlite'
    if database.exists():raise ValueError('Use a fresh output directory; retained evidence is never overwritten')
    sample=read(root/'sample.json');directory=root/'work-phases-routed'
    store=Store(database);sources=[];rows=[];activities=Counter()
    for member in sample['runs']:
        source=read(root/'sources'/f'{member["id"]}.json')
        if digest(source)!=member['source_hash']:raise ValueError('Retained source changed')
        bundle=load_extraction(source,directory)
        if not bundle['available']:raise ValueError('Missing retained extraction')
        selected=[u for u in bundle['raw_extraction']['units'] if u['status']=='selected']
        activities.update(u['activity'] for u in selected)
        sources.append(source)
        rows.append(dict(run_id=source['id'],source_hash=digest(source),training_step=member['step'],
            selected_units=len(selected),validation=bundle['validation']))
    store.add(sources)
    observer=semantic_collection.register(store,directory,[r['id'] for r in sources],'Retained real-trace development replay')
    monitor=monitoring.create(store,dict(name='Verify activity share · development',kind='metric',metric='activity_verify_share',observer=observer['observer']))
    monitoring.sync(store)
    snapshot=monitoring.snapshot(store)
    measured=next(m for m in snapshot['monitors'] if m['id']==monitor['id'])
    if measured['coverage']['available']!=len(sources):
        raise AssertionError('Retained activity observations did not reach every source measurement')
    # The real sources do not include same-work execution/result bindings. A
    # verified activity label cannot justify a passing-check/recovery metric.
    relationship=monitoring.create(store,dict(name='Feedback assessment · evidence check',kind='graph',observer=observer['observer'],
        requirement=monitoring.graph_queries.PRESETS['assessment_of_inspection_feedback']))
    monitoring.sync(store)
    unavailable=next(m for m in monitoring.snapshot(store)['monitors'] if m['id']==relationship['id'])
    if unavailable['coverage']['available']!=0:
        raise AssertionError('Missing relationship observations became measured behavior')
    control=read(root/'word-count-control.json')
    if control['sample_hash']!=digest(sample):raise ValueError('Word-count control belongs to another sample')
    result=dict(schema='retained-real-semantic-replay/1',status='replay_checks_passed',new_model_calls=0,
        source='Real recorded training outputs, 16 development cases from one task at logged steps 50 and 140',
        source_manifest_hash=digest(sample),rows=rows,selected_activities=dict(activities),
        observer=observer['observer'],metric=dict(coverage=measured['coverage'],series=measured['series']),
        relationship_metric=dict(coverage=unavailable['coverage'],series=unavailable['series']),
        known_independent_of_activity_control=control['by_training_step'],
        validation_scope=dict(saved_response_integrity='replayed raw argmax decisions, source spans and candidate identities',
            publication='normalized retained sources and historical observations published locally; no new HTTP or live inference in this audit',
            semantic_accuracy='not established; historical development labels include documented construct/report ambiguity',
            online_extraction='not exercised; no provider calls or automatic observation scheduling',
            generalization='not established; deliberately small, length-selected, previously exposed development sample',
            downstream_meaning='Verify activity is expressed checking, not verified correctness; missing result relations cannot become successful recovery'))
    (output/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(status=result['status'],rollouts=len(rows),activities=dict(activities),
        measured=measured['coverage']['available'],relation_available=unavailable['coverage']['available'],new_model_calls=0)))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path('research/training-semantic-pilot-2026-10-08'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();run(args.source,args.output)
