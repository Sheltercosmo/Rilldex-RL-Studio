"""Source-local proposals for L2. Syntax proposes spans, never semantic truth.

Recorded dispatch metadata is a separate source fact. Candidate profiles avoid
offering code payloads as actor mentions without claiming exhaustive extraction.
"""
import re

from .schema import digest

VERSION = 'local-span-candidates/3'


def span_candidates(unit, event):
    text = unit['text']; spans = {}

    def add(a, b, kind, *, punctuation=True, trim=True):
        while trim and a < b and text[a].isspace(): a += 1
        while b > a and (trim and text[b-1].isspace() or punctuation and text[b-1] in '.?!,;'): b -= 1
        if a >= b: return
        key = (a, b)
        if key in spans:
            if kind not in spans[key]['proposal_kinds']: spans[key]['proposal_kinds'].append(kind)
            return
        spans[key] = {'id':'x'+digest([unit['id'],a,b])[:16], 'kind':'source_span', 'text':text[a:b],
                     'event_id':unit['event_id'], 'source_pointer':unit['source_pointer'],
                     'start':unit['start']+a, 'end':unit['start']+b, 'proposal_kinds':[kind],
                     'offset_basis':'normalized_event_text_unicode_codepoints'}

    dispatch = unit['kind'] == 'action_dispatch'
    add(0, len(text), 'whole_expression', punctuation=not dispatch)
    if dispatch:
        # Only this exact recorded editor syntax has a separable header/body.
        # Do not run a natural-language clause splitter over embedded programs.
        edit = re.fullmatch(r'(edit\s+(\d+):(\d+))\r?\n([\s\S]*?)\r?\nend_of_edit\s*', text)
        if edit:
            add(*edit.span(1), 'recorded_operation', punctuation=False)
            add(edit.start(2), edit.end(3), 'dispatch_range', punctuation=False)
            add(*edit.span(4), 'dispatch_payload', punctuation=False, trim=False)
        else:
            add(0, len(text), 'recorded_operation', punctuation=False)
        for m in re.finditer(r'\b[\w./-]+\.(?:py|js|ts|json|md|txt|yaml|yml)\b', text[:text.find('\n') if '\n' in text else len(text)]):
            add(*m.span(), 'dispatch_target', punctuation=False)
    else:
        protected=[]
        for m in re.finditer(r'`([^`\n]+)`|"([^"\n]+)"|“([^”\n]+)”', text):
            protected.append(m.span())
            group = next(i for i in (1,2,3) if m.group(i) is not None)
            add(*m.span(group), 'quoted_or_code')
        for m in re.finditer(r'\b(?:you|I|we|he|she|they|it|me|us|them|him|her|this|that)\b', text, re.I):
            add(*m.span(), 'pronoun')
        for m in re.finditer(r'(?=\b(?:please|will|shall|should|can|could|would|must|need to|let\u2019s|let\x27s|(?:I|we|you|they)[\x27\u2019]ll)\s+(.+))', text, re.I):
            add(*m.span(1), 'operation_phrase')
            purpose = re.search(r'\b(?:to see|to verify|to ensure|to replicate|to reproduce|because|so that|in order to)\b', m.group(1), re.I)
            if purpose: add(m.start(1), m.start(1)+purpose.start(), 'operation_phrase')
        # Purpose boundaries are proposals. Jev still distinguishes purpose from
        # a complement such as "need to edit", never promotes every 'to' to a goal.
        for m in re.finditer(r'(?=(\b(?:to|so that|in order to)\s+[^,;\n]+))', text, re.I):
            add(*m.span(1), 'purpose_phrase')
        for m in re.finditer(r'[,;\n]|\b(?:because|since|so that|in order to|which means|to see|to verify|to ensure|after that|if)\b', text, re.I):
            add(0, m.start(), 'clause_prefix')
            add(m.end(), len(text), 'clause_suffix')
            if m.group().lower() == 'which means': add(m.end(), len(text), 'conclusion_clause')
        # Preserve causal premise wording rather than removing its cue.
        causal = re.match(r'\s*(?:Since|Because)\b[^,]+', text, re.I)
        if causal:
            add(*causal.span(), 'premise_clause')
            comma=text.find(',',causal.end())
            if comma>=0:add(comma+1,len(text),'conclusion_clause')
        for m in re.finditer(r'\b(?:which means|therefore|thus|because|hence|so)\b',text,re.I):
            if any(a<=m.start()<b for a,b in protected):continue
            if not text[:m.start()].strip():continue
            if m.group().lower()=='because':
                add(0,m.start(),'conclusion_clause');add(m.start(),len(text),'premise_clause')
            elif m.group().lower()!='so' or not re.match(r'\s+that\b',text[m.end():],re.I):
                add(0,m.start(),'premise_clause');add(m.end(),len(text),'conclusion_clause')
        for m in re.finditer(r'\b(?:the|a|an|your|my|our|their|this|that|these|those)\s+', text, re.I):
            end = re.search(r'[,;.!?\n]|\b(?:to|for|from|using|with|without|in|on|is|are|was|were|will|should|can|could|would|does|do|has|have|and|or|when|if|which|that)\b', text[m.end():], re.I)
            b = m.end()+end.start() if end else len(text)
            if b > m.end(): add(m.start(),b,'noun_phrase'); add(m.end(),b,'noun_phrase')
        for m in re.finditer(r'\b(?:[A-Z][A-Za-z0-9_-]*)(?:[ \t]+[A-Z][A-Za-z0-9_-]*)*\b|\b[\w./-]+\.(?:py|js|ts|json|md|txt|yaml|yml)\b', text):
            add(*m.span(), 'literal_name')

    values = list(spans.values()); total = len(values); values = values[:64]
    argument_count = 0
    if dispatch:
        def walk(value, pointer):
            if isinstance(value, dict):
                for k,v in value.items(): yield from walk(v,pointer+'/'+str(k).replace('~','~0').replace('/','~1'))
            else: yield pointer,value
        args = list(walk(event.get('arguments',{}),'/arguments')); argument_count = len(args)
        for pointer,value in args[:32]:
            values.append({'id':'a'+digest([unit['id'],pointer,value])[:16], 'kind':'structured_argument', 'value':value,
                           'event_id':unit['event_id'], 'source_pointer':event['source_pointer'], 'normalized_event_pointer':pointer,
                           'proposal_kinds':['structured_argument'], 'text':value if isinstance(value,str) else str(value)})
    return values, {'proposed_source_spans':total, 'supplied_source_spans':min(total,64), 'omitted_source_spans':max(0,total-64),
                    'proposed_arguments':argument_count, 'omitted_arguments':max(0,argument_count-32),
                    'limitation':'Syntax and argument proposals are not exhaustive semantic extraction. One candidate per field; disjoint occurrences must select multiple_spans_needed. Natural-language boundaries are English-centric.'}


def recorded_action(unit, event, candidates=None):
    """Available irrespective of H1/H2 decisions. Dispatch is not execution."""
    if unit['kind'] != 'action_dispatch': return None
    if candidates is None: candidates,_ = span_candidates(unit,event)
    operation = next((c for c in candidates if 'recorded_operation' in c['proposal_kinds']), None)
    return {'status':'recorded_dispatch', 'basis':'normalized_source_record', 'event_id':event['id'],
            'tool':event.get('tool'), 'tool_pointer':'/tool', 'source_pointer':event['source_pointer'],
            'operation':operation, 'arguments':[c for c in candidates if c['kind']=='structured_argument'],
            'boundary':'This records what was dispatched; purpose, successful execution, effects and acceptance criteria are not established.'}


def field_candidates(profile, candidates, unit):
    kinds = {
        'operation': {'whole_expression','operation_phrase','recorded_operation'},
        'mention': {'quoted_or_code','pronoun','noun_phrase','literal_name','dispatch_target','structured_argument'},
        'proposition': {'whole_expression','premise_clause','conclusion_clause'},
        'premise': {'whole_expression','premise_clause'},
        'conclusion': {'whole_expression','conclusion_clause'},
        'purpose': {'whole_expression','purpose_phrase'},
        'content': {'whole_expression','dispatch_payload','operation_phrase','structured_argument'},
    }.get(profile)
    if kinds is None: return candidates
    selected = [c for c in candidates if kinds.intersection(c['proposal_kinds'])]
    if unit['kind']=='action_dispatch':
        if profile=='operation':
            selected = [c for c in candidates if 'recorded_operation' in c['proposal_kinds']]
        elif profile=='mention':
            # A whole shell command/code body is not an object mention. Keep
            # named JSON arguments; resolving their roles is still Jev's job.
            selected = [c for c in selected if c.get('normalized_event_pointer') != '/arguments/command']
        elif profile=='content' and any('dispatch_payload' in c['proposal_kinds'] for c in candidates):
            selected = [c for c in candidates if 'dispatch_payload' in c['proposal_kinds']]
    return selected
