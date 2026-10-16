"""Reproduce the fixed, source-grounded retrieval audit without provider calls.

Run from the repository with the installed project interpreter:
  python scripts/audit_source_evidence.py

The reference questions and source spans are read verbatim. Search uses only
the documented defaults (limit=8, max_chars=16000). The output is a compact
mechanical audit, not a judgment of answer quality or semantic correctness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tracker.source_evidence import VERSION, search  # noqa: E402


REFERENCE = Path('research/longtrace-replay-2026-10-15/retrieval-reference.json')
SOURCE_FILES = {
    '68f4f4de60c1226d7d896ae8': Path('research/base-unit-content-v2-2026-10-07/runs/68f4f4de60c1226d7d896ae8.json'),
    '23a6f4b7c76c919e74ae6d50': Path('research/work-paths-2026-10-07/runs/23a6f4b7c76c919e74ae6d50.json'),
    'd8c0e38f633a068fbc7aed74': Path('research/contribution-boundaries-2026-10-07/runs/d8c0e38f633a068fbc7aed74.json'),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root: Path = ROOT) -> dict:
    reference_path = root / REFERENCE
    reference = json.loads(reference_path.read_text(encoding='utf-8'))
    implementation_path = root / 'tracker/source_evidence.py'
    loaded_module_path = Path(sys.modules['tracker.source_evidence'].__file__).resolve()
    if loaded_module_path != implementation_path.resolve():
        raise ValueError(f'Loaded implementation is not the audited source file: {loaded_module_path}')
    runs = {}
    source_provenance = {}
    for run_id, relative_path in SOURCE_FILES.items():
        path = root / relative_path
        run = json.loads(path.read_text(encoding='utf-8'))
        if run.get('id') != run_id:
            raise ValueError(f'Run ID mismatch in {relative_path}')
        runs[run_id] = run
        source_provenance[run_id] = {
            'path': relative_path.as_posix(), 'sha256': sha256(path),
            'event_count': len(run.get('events', [])),
        }

    cases = []
    totals = {'must_find_spans': 0, 'exact_spans_retrieved': 0,
              'required_pairs': 0, 'pairs_fully_retained': 0,
              'pairs_with_native_link_reason': 0}
    for case in reference['cases']:
        run = runs[case['run_id']]
        event_by_id = {event['id']: event for event in run['events']}
        anchor = event_by_id[case['anchor_event_id']]
        if anchor['index'] != case['anchor_index']:
            raise ValueError(f"Anchor index mismatch for {case['id']}")
        # Keep the reference question exact and intentionally omit both
        # optional knobs so the implementation defaults are exercised.
        result = search(run, {
            'anchor': {'event_id': case['anchor_event_id']},
            'text': case['question'],
        })
        returned = {record['event_id']: record for record in result['records']}
        match_rank = {match['event_id']: match['rank'] for match in result['matches']}
        span_results = []
        for span in case['must_find']:
            event = event_by_id[span['event_id']]
            expected_quote = event['text'][span['start']:span['end']]
            if expected_quote != span['quote']:
                raise ValueError(f"Reference quote mismatch for {case['id']} / {span['event_id']}")
            exact = any(
                fragment['start'] <= span['start'] and fragment['end'] >= span['end']
                and fragment['text'][span['start'] - fragment['start']:
                                     span['end'] - fragment['start']] == span['quote']
                for fragment in returned.get(span['event_id'], {}).get('fragments', [])
            )
            span_results.append({
                'event_id': span['event_id'], 'role': span['role'],
                'start': span['start'], 'end': span['end'], 'quote': span['quote'],
                'exact_span_retrieved': exact,
                'event_retained': span['event_id'] in returned,
                'lexical_match_rank': match_rank.get(span['event_id']),
                'record_reasons': returned.get(span['event_id'], {}).get('reasons', []),
            })

        pair_results = []
        for pair in case.get('attempt_contexts', []):
            call_id, response_id = pair['call_event_id'], pair['result_event_id']
            retained = call_id in returned and response_id in returned
            call_native_reason = any(
                reason.get('kind') == 'recorded_dispatch'
                for reason in returned.get(call_id, {}).get('reasons', []))
            response_native_reason = any(
                reason.get('kind') == 'recorded_response'
                for reason in returned.get(response_id, {}).get('reasons', []))
            native_reason = call_native_reason and response_native_reason
            pair_results.append({
                'call_event_id': call_id, 'result_event_id': response_id,
                'result': pair.get('result'), 'pair_retained': retained,
                'native_link_context_reason_present': native_reason,
                'call_dispatch_reason_present': call_native_reason,
                'response_link_reason_present': response_native_reason,
            })
        totals['must_find_spans'] += len(span_results)
        totals['exact_spans_retrieved'] += sum(item['exact_span_retrieved'] for item in span_results)
        totals['required_pairs'] += len(pair_results)
        totals['pairs_fully_retained'] += sum(item['pair_retained'] for item in pair_results)
        totals['pairs_with_native_link_reason'] += sum(item['native_link_context_reason_present'] for item in pair_results)
        coverage = result['coverage']
        cases.append({
            'case_id': case['id'], 'run_id': case['run_id'],
            'anchor_event_id': case['anchor_event_id'], 'anchor_index': case['anchor_index'],
            'exact_query': case['question'],
            'expected_answerability': case['expected_answerability'],
            'query_defaults': {'limit': 8, 'max_chars': 16000},
            'search': {'version': result['schema'], 'source_hash': result['source_hash'],
                       'query_terms': result['query_terms'], 'matches': result['matches']},
            'coverage': coverage,
            'retrieved_event_ids': [record['event_id'] for record in result['records']],
            'must_find_spans': span_results,
            'span_recall': {'retrieved': sum(item['exact_span_retrieved'] for item in span_results),
                            'total': len(span_results)},
            'required_call_response_pairs': pair_results,
            'required_pair_retention': {
                'retained': sum(item['pair_retained'] for item in pair_results),
                'with_native_link_reason': sum(item['native_link_context_reason_present'] for item in pair_results),
                'total': len(pair_results)},
            'no_answer_or_ambiguity_limit': (
                'Lexical retrieval misses cannot establish absence. For no-answer cases, the reference boundary and the full visible source prefix still require review.'
                if case['expected_answerability'] in {'no_answer', 'ambiguous'} else None),
            'new_provider_calls': 0,
        })

    spans_total = totals['must_find_spans']
    pairs_total = totals['required_pairs']
    return {
        'schema': 'retrieval-audit/2',
        'reference_path': REFERENCE.as_posix(),
        'reference_sha256': sha256(reference_path),
        'reference_cases': len(cases),
        'implementation': {
            'module': 'tracker.source_evidence.search', 'version': VERSION,
            'path': 'tracker/source_evidence.py', 'sha256': sha256(implementation_path),
            'loaded_module_path': str(loaded_module_path),
            'query_text': 'Exact case.question; no paraphrasing or tuning',
            'limit': 8, 'max_chars': 16000, 'provider_calls': 0, 'model_calls': 0,
        },
        'source_provenance': source_provenance,
        'aggregate': {
            **totals,
            'exact_span_recall': totals['exact_spans_retrieved'] / spans_total if spans_total else None,
            'native_pair_retention': totals['pairs_fully_retained'] / pairs_total if pairs_total else None,
        },
        'interpretation_limit': (
            'This is a mechanical audit against model-authored reference spans, not a human-validated benchmark. '
            'Exact-span recall measures literal span retention only; it does not establish answer correctness, '
            'semantic recall, or completeness. No-answer and ambiguous cases cannot be decided from retrieval misses.'),
        'cases': cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=Path('research/longtrace-replay-2026-10-15/retrieval-results-balanced.json'))
    args = parser.parse_args()
    result = audit(args.root.resolve())
    output = args.output if args.output.is_absolute() else args.root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'implementation_sha256': result['implementation']['sha256'],
                      'aggregate': result['aggregate']}, indent=2))


if __name__ == '__main__':
    main()
