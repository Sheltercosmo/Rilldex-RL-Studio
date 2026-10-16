"""Exact per-field review citations. These validate text binding, not label truth."""
from .schema import InputError

SPAN_BASIS='evidence_text_unicode_codepoints/1'
FIELDS={'field','target','evidence_id','start','end','text','role','basis'}


def evidence_item(case,target,evidence_id):
    if target=='subject':items=[case['subject']]
    elif target=='source':items=[case['source']] if case.get('source') else []
    elif target=='prefix':items=case['available_prefix']
    else:raise InputError('Unknown review citation target')
    matching=[item for item in items if item['id']==evidence_id]
    if len(matching)!=1:raise InputError('Review citation target is missing or ambiguous')
    return matching[0]


def validate_spans(row,case):
    """An optional additive field; old whole-record citations remain valid."""
    if 'evidence_spans' not in row:return
    spans=row['evidence_spans']
    if not isinstance(spans,list) or len(spans)>128:raise InputError('Use at most 128 exact review citations')
    seen=set()
    for span in spans:
        if (not isinstance(span,dict) or set(span)!=FIELDS
                or any(not isinstance(span[k],str) for k in ('target','role','basis'))
                or not isinstance(span['field'],str) or span['field'] not in case['fields']
                or not isinstance(span['evidence_id'],str) or span['evidence_id'] not in row['evidence_ids']
                or span['basis']!=SPAN_BASIS or span['role'] not in {'label_evidence','context'}):
            raise InputError('Review citation needs a supplied field, cited evidence and explicit scope')
        item=evidence_item(case,span['target'],span['evidence_id']);text=item['text']
        start,end=span['start'],span['end']
        if (type(start) is not int or type(end) is not int or not 0<=start<end<=len(text)
                or not isinstance(span['text'],str) or not span['text'].strip() or text[start:end]!=span['text']):
            raise InputError('Review citation does not match the exact bounded source text')
        identity=tuple(span[k] for k in sorted(FIELDS))
        if identity in seen:raise InputError('Duplicate exact review citation')
        seen.add(identity)
