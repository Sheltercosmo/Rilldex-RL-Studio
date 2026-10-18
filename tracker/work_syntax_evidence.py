"""Source-bound syntax evidence for attachment review, never semantic verdicts.

Accepts parser-neutral token/dependency records. No parser is installed, called
or downloaded here. Predicted sentence boundaries and dependencies remain model
outputs; they must not be promoted into behavior relationships or polarity.
"""
from copy import deepcopy

from . import work_content_bindings as scoped, work_feature_membership as membership
from .schema import digest, dumps

VERSION = 'work-syntax-evidence/1'
MAX_TOKENS = 4096
MAX_HEADS = 8
require = scoped.require


def bind(prepared, bound, parsed):
    source = scoped.checked(prepared, bound)['unit']['source']
    require(isinstance(parsed, dict) and set(parsed) == {'source','parser','tokens'}, 'source, parser and tokens required')
    require(parsed['source'] == source, 'syntax must retain the complete unchanged source unit')
    parser = parsed['parser']
    required = {'name','version','model','model_version','language','label_scheme'}
    require(isinstance(parser, dict) and required <= set(parser) <= required | {'model_hash'} and
            all(isinstance(v, str) and 0 < len(v.strip()) <= 256 for v in parser.values()),
            'named parser, model, versions, language and label scheme required')
    tokens = parsed['tokens']
    require(isinstance(tokens, list) and 0 < len(tokens) <= MAX_TOKENS, 'bounded nonempty syntax token list required')
    require(len(dumps(parsed).encode('utf-8')) <= 1_000_000, 'syntax record exceeds byte budget')
    end = source['start']; groups = {}; previous_sentence = None
    for index, token in enumerate(tokens):
        require(isinstance(token, dict) and set(token) == {'id','text','start','end','sentence','head','relation','pos'},
                'invalid syntax token fields')
        require(type(token['id']) is int and token['id'] == index and
                type(token['head']) is int and 0 <= token['head'] < len(tokens), 'ordered token IDs and valid heads required')
        require(type(token['start']) is int and type(token['end']) is int and
                end <= token['start'] < token['end'] <= source['end'], 'ordered nonoverlapping token ranges required')
        a,z = token['start']-source['start'], token['end']-source['start']
        require(token['text'] == source['text'][a:z], 'syntax token differs from its source range')
        require(not source['text'][end-source['start']:a].strip(), 'syntax omitted source text')
        require(type(token['sentence']) is int and token['sentence'] >= 0, 'nonnegative sentence ID required')
        require(all(isinstance(token[k], str) and 0 < len(token[k]) <= 80 for k in ['relation','pos']),
                'dependency and part-of-speech labels required')
        sentence = token['sentence']
        if sentence != previous_sentence:
            require(sentence not in groups, 'sentence tokens must be contiguous')
            groups[sentence] = []
        groups[sentence].append(index); previous_sentence = sentence; end = token['end']
    require(not source['text'][end-source['start']:].strip(), 'syntax omitted the source tail')
    for sentence, ids in groups.items():
        require(sum(tokens[i]['head'] == i for i in ids) == 1, 'one dependency root per sentence required')
        for index in ids:
            require(tokens[tokens[index]['head']]['sentence'] == sentence, 'dependency head crosses a sentence')
            seen = set(); current = index
            while tokens[current]['head'] != current:
                require(current not in seen, 'cyclic dependency tree')
                seen.add(current); current = tokens[current]['head']
    record = dict(schema=VERSION, unit_id=bound['unit_id'], parsed=deepcopy(parsed),
                  validation='Exact source coverage and dependency topology; parser predictions remain unvalidated.',
                  publication='review_only')
    return dict(id='syntax-'+digest(record), **record)


def checked(prepared, bound, record):
    require(isinstance(record, dict) and record == bind(prepared, bound, record.get('parsed')),
            'syntax receipt or source changed')
    return record['parsed']


def _anchor(expression, tokens):
    a,z = expression['start'],expression['end']
    overlap = [t for t in tokens if t['start'] < z and a < t['end']]
    aligned = bool(overlap) and all(a <= t['start'] and t['end'] <= z for t in overlap)
    ids = [t['id'] for t in overlap]
    heads = [t['id'] for t in overlap if t['head'] == t['id'] or t['head'] not in ids]
    return dict(expression=deepcopy(expression), token_ids=ids, head_ids=heads,
                sentence_ids=sorted({t['sentence'] for t in overlap}),
                status='aligned' if aligned else 'unaligned_token_boundary')


def _path(tokens, left, right):
    # A validated sentence is a tree, so the undirected path is unique.
    left_chain = []; current = left
    while True:
        left_chain.append(current)
        if tokens[current]['head'] == current:break
        current = tokens[current]['head']
    right_chain = []; current = right
    while current not in left_chain:
        right_chain.append(current)
        current = tokens[current]['head']
    ids = left_chain[:left_chain.index(current)+1] + list(reversed(right_chain))
    edges = []
    for a,z in zip(ids,ids[1:]):
        upward = tokens[a]['head'] == z
        edges.append(dict(source=a,target=z,relation=tokens[a if upward else z]['relation'],
                          direction='to_head' if upward else 'to_child'))
    return dict(feature_head=left,content_head=right,token_ids=ids,edges=edges)


def review(prepared, bound, feature_id, decision, syntax):
    """Explain saved per-content judgments with syntax; never correct them."""
    parsed = checked(prepared,bound,syntax)
    require(isinstance(decision, dict) and decision == membership.resolve(
            prepared,bound,feature_id,decision.get('response')), 'membership receipt changed')
    tokens = parsed['tokens']
    feature = next(f for f in bound['features'] if f['id'] == feature_id)
    feature_anchor = _anchor(feature['expression'],tokens)
    choices = {m['content_id']:m['choice'] for m in decision['members']}
    pairs = []
    for content in sorted(bound['contents'],key=lambda c:c['id']):
        anchor = _anchor(content['expression'],tokens)
        status = ('unaligned_token_boundary' if feature_anchor['status'] != 'aligned' or anchor['status'] != 'aligned'
                  else 'multiple_sentence_span' if len(feature_anchor['sentence_ids']) != 1 or len(anchor['sentence_ids']) != 1
                  else 'separate_sentences' if feature_anchor['sentence_ids'] != anchor['sentence_ids']
                  else 'too_many_heads' if len(feature_anchor['head_ids']) > MAX_HEADS or len(anchor['head_ids']) > MAX_HEADS
                  else 'shared_sentence')
        paths = ([_path(tokens,f,c) for f in feature_anchor['head_ids'] for c in anchor['head_ids']]
                 if status == 'shared_sentence' else [])
        flags = ['positive_across_predicted_sentences'] if choices[content['id']] == 'attached' and status == 'separate_sentences' else []
        pairs.append(dict(content_id=content['id'],membership_choice=choices[content['id']],
            selected_scope_member=(content['id'] in decision['content_ids'] if decision['content_ids'] is not None else None),
            anchor=anchor,status=status,dependency_paths=paths,review_flags=flags))
    return dict(schema=VERSION+'/review',source=deepcopy(parsed['source']),syntax_id=syntax['id'],
        membership_result_hash=digest(decision),feature_id=feature_id,feature=feature_anchor,pairs=pairs,
        tokens=deepcopy(tokens),parser=deepcopy(parsed['parser']),publication='review_only',
        verdict='not_assessed',
        limit='Syntax paths and cross-sentence flags are review evidence, not semantic attachment, contradiction or permission to prune candidates.')


def from_spacy(prepared, bound, document, *, library_version, model, model_version):
    """Optional adapter for an already parsed spaCy Doc; imports no spaCy code."""
    source = scoped.checked(prepared,bound)['unit']['source']
    require(document.text == source['text'], 'parsed document text differs')
    require(all(document.has_annotation(name,require_complete=True) for name in ['DEP','POS','SENT_START']),
            'parsed document requires dependency, POS and sentence annotations')
    sentence_ids = {t.i:i for i,sentence in enumerate(document.sents) for t in sentence}
    tokens = [dict(id=t.i,text=t.text,start=source['start']+t.idx,end=source['start']+t.idx+len(t),
        sentence=sentence_ids[t.i],head=t.head.i,relation=t.dep_,pos=t.pos_) for t in document]
    return bind(prepared,bound,dict(source=source,tokens=tokens,parser=dict(name='spacy',version=library_version,
        model=model,model_version=model_version,language=document.lang_,label_scheme='spaCy pipeline dependency labels')))


def candidate_groups(prepared, bound, syntax):
    """Propose groups of fixed contents whose heads share a dependency subtree.

    This is candidate construction, not attachment or scope classification. It
    neither removes supplied groups nor invents missing content expressions.
    Sentence-spanning and unaligned contents remain in the original inventory.
    """
    parsed = checked(prepared, bound, syntax)
    tokens = parsed['tokens']
    anchors = {}; members = {}; depths = {}
    for content in sorted(bound['contents'], key=lambda item: item['id']):
        anchor = _anchor(content['expression'], tokens)
        status = (anchor['status'] if anchor['status'] != 'aligned' else
                  'multiple_sentence_span' if len(anchor['sentence_ids']) != 1 else 'eligible')
        anchors[content['id']] = dict(status=status, head_ids=anchor['head_ids'])
        if status != 'eligible':
            continue
        common = None
        for head in anchor['head_ids']:
            chain = []; current = head
            while True:
                chain.append(current)
                if tokens[current]['head'] == current:
                    break
                current = tokens[current]['head']
            for i, node in enumerate(chain):
                depths[node] = len(chain) - i
            common = set(chain) if common is None else common.intersection(chain)
        for node in common or ():
            members.setdefault(node, set()).add(content['id'])
    groups = {}
    for node, ids in members.items():
        if len(ids) < 2:
            continue
        key = tuple(sorted(ids))
        # The deepest witness is the smallest subtree with this same membership.
        if key not in groups or depths[node] > depths[groups[key]]:
            groups[key] = node
    return dict(schema=VERSION+'/candidate-groups/1', syntax_id=syntax['id'],
        source_hash=digest(parsed['source']), parser=deepcopy(parsed['parser']), anchors=anchors,
        groups=[dict(content_ids=list(ids), root_token_id=node,
                     root_expression={k:tokens[node][k] for k in ('text','start','end')},
                     basis='predicted_dependency_subtree') for ids,node in sorted(groups.items())],
        coverage=dict(all_multi_content_scopes=False, missing_contents_not_proposed=True),
        publication='review_only',
        limit='Candidate groups over the supplied inventory; no semantic scope, shared intent, execution or completeness guarantee.')
