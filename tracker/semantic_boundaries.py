"""Bounded complete-partition choices from exact source blocks.

Paragraphs are candidate boundaries, never semantic units by themselves. All
adjacent merges are offered when the declared budget permits. Fenced payloads
stay intact. No generated descriptions, activity labels or inferred relations.
"""
from itertools import combinations
import re

from .schema import InputError, digest, dumps
from .semantic_extraction import (PARTITION_CANDIDATE_RULE, checked_span,
                                  partition, request, FileCandidates, PARTITION_CANDIDATE_STANDARD,
                                  generation_request, read, write)

VERSION = 'global-source-partitions/1'
DEFAULT_MAX_PARTITIONS = 128


class GlobalSourceCandidates(FileCandidates):
    """Experimental boundary mode; local content still uses the source queue.

    Activities use the existing finite vocabulary directly. This class does not
    fabricate activity readings or invoke a generative service automatically.
    """
    def __init__(self, directory, context_policy=None, *, activity_reading_sources=()):
        super().__init__(directory, context_policy=context_policy,partition_standard=PARTITION_CANDIDATE_STANDARD)
        self.partition_policy = VERSION
        self.activity_reading_sources={digest(ref) for ref in activity_reading_sources}
        self.has_activity_repairs=bool(self.activity_reading_sources)

    def reading_required(self, ref):
        return digest(ref) in self.activity_reading_sources

    def partitions(self, run, window, *, needed=False):
        # Large-region repair uses the existing external proposal contract,
        # without presenting these as exhaustive source-block alternatives.
        provider=FileCandidates(self.directory,context_policy=self.context_policy,
                                partition_standard=PARTITION_CANDIDATE_STANDARD)
        return provider.partitions(run,window,needed=needed)

    def content(self, run, ref, activity):
        try:
            return super().content(run,ref,activity)
        except InputError as exc:
            # An invalid generated proposal must not classify the unit, and
            # must not prevent independent later units from being processed.
            req=generation_request(run,ref,activity,self.context_policy);key=digest(req)
            response=read(self.directory/'responses'/f'{key}.json')
            rejected={'schema':'source-candidate-rejection/1','request_hash':key,
                      'response':response,'validation_error':str(exc)}
            rejection_hash=digest(rejected)
            write(self.directory/'rejections'/f'{rejection_hash}.json',rejected)
            return {'status':'needs_candidate_repair','request_hash':key,'rejection_hash':rejection_hash}


def fenced_ranges(text):
    """Protect CommonMark-style backtick/tilde fences, including unclosed ones."""
    ranges = []; active = None; pos = 0
    for line in text.splitlines(keepends=True):
        if active is None:
            match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
            if match and not (match[1][0] == '`' and '`' in match[2]):
                active = (pos, match[1][0], len(match[1]))
        else:
            start, mark, width = active
            if re.fullmatch(r' {0,3}'+re.escape(mark)+'{'+str(width)+r',}[ \t]*[\r\n]*', line):
                ranges.append((start, pos+len(line.rstrip('\r\n')))); active = None
        pos += len(line)
    if active is not None: ranges.append((active[0], len(text)))
    return ranges


def source_blocks(run, window):
    event = checked_span(run, window)
    text = event['text']; start, end = window['start'], window['end']
    if window.get('kind') == 'action_dispatch': return partition(run, window, [window])
    protected = [(a+start, b+start) for a,b in fenced_ranges(text[start:end])]
    spans = []; cursor = start
    for match in re.finditer(r'\n[ \t\r]*\n(?:[ \t\r]*\n)*', text[start:end]):
        a, b = start+match.start(), start+match.end()
        if any(left < b and a < right for left, right in protected): continue
        if text[cursor:a].strip(): spans.append({'start': cursor, 'end': a})
        cursor = b
    if text[cursor:end].strip(): spans.append({'start': cursor, 'end': end})
    for span in spans:
        while span['start'] < span['end'] and text[span['start']].isspace(): span['start'] += 1
        while span['end'] > span['start'] and text[span['end']-1].isspace(): span['end'] -= 1
    return partition(run, window, spans)


def proposals(run, window, *, max_partitions=DEFAULT_MAX_PARTITIONS):
    if type(max_partitions) is not int or not 1 <= max_partitions <= 1024:
        raise InputError('Global partition budget must be an integer from 1 to 1024')
    blocks = source_blocks(run, window); count = 2**(len(blocks)-1)
    result = {'schema': VERSION, 'window': window, 'blocks': blocks,
              'total_possible_partitions': count, 'max_partitions': max_partitions,
              'coverage': 'complete_at_proposed_block_boundaries', 'partitions': []}
    if count > max_partitions:
        # Do not truncate the option set and then treat a winner as complete.
        result['coverage'] = 'partition_budget_exceeded'; return result
    for size in range(len(blocks)):
        for cuts in combinations(range(1, len(blocks)), size):
            limits = (0, *cuts, len(blocks)); groups = [list(range(a,b)) for a,b in zip(limits,limits[1:])]
            spans = [{'start': blocks[g[0]]['start'], 'end': blocks[g[-1]]['end']} for g in groups]
            result['partitions'].append({'id': 'p'+str(len(result['partitions'])), 'groups': groups,
                                         'units': partition(run, window, spans)})
    return result


def selection_request(run, candidates, context_policy):
    if candidates['coverage'] != 'complete_at_proposed_block_boundaries':
        raise InputError('Cannot select an incomplete global option set')
    blocks = [{'id': 'b'+str(i), 'source': span} for i,span in enumerate(candidates['blocks'])]
    choices = {p['id']: dumps({'units': [['b'+str(i) for i in g] for g in p['groups']]})
               for p in candidates['partitions']}
    choices.update(no_suitable_candidate='None of these complete groupings preserves the contributions. A boundary inside a source block or a different representation is needed.',
                   unresolved='The supplied context does not establish the contribution structure.')
    return request(run, candidates['window'], 'global-source-partitions',
        'Select the complete partition of this source region into coherent work or interaction contributions. '
        'Each option groups consecutive numbered source blocks; a group is ONE unit containing every word of those blocks. '
        'Compare the whole grouping, not the number of sentences, listed facts, topics or action verbs. '
        'A report can deliver several related answers together. A substantive request for new authorization can be a separate contribution; '
        'details specifying the proposed action belong with that request. Keep setup, rationale and immediate needed correction together. '
        'Keep a plan and its intended stages together. Keep a generic courtesy or referential confirmation with what it supports. '
        'Do not split because of paragraphs or code fences. Do not merge merely because the topic stays the same. '
        'Use no_suitable_candidate if a necessary semantic boundary falls inside a supplied block. '
        'Choose before activity classification; do not infer progress, correctness or relations here.',
        choices, context_policy=context_policy, rule=PARTITION_CANDIDATE_RULE,
        boundary_harness=VERSION, candidate_hash=digest(candidates), source_blocks=blocks,
        candidate_coverage={'basis':'Every adjacent grouping of the supplied paragraph blocks; not all possible semantic boundaries.',
                            'partitions':len(candidates['partitions'])})


def materialize(candidates, winner):
    if winner in {'no_suitable_candidate', 'unresolved'}:
        return {'status': winner, 'units': [], 'candidate_hash': digest(candidates)}
    selected = next((p for p in candidates['partitions'] if p['id'] == winner), None)
    if selected is None: raise InputError('Global partition choice is not offered')
    return {'status': 'selected', 'units': selected['units'], 'candidate_hash': digest(candidates)}
