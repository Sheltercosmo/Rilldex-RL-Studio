"""Shared review provenance and consensus rules, independent of a tag taxonomy."""
from collections import Counter,defaultdict

from .schema import InputError


def collect(rows,cases,manifest_hash,validate):
    records=defaultdict(list);seen_ids={};independent=set()
    for row in rows:
        if not isinstance(row,dict) or row.get('case_id') not in cases:
            raise InputError('Annotation case is absent from frozen corpus')
        cid=row['case_id'];validate(row,cases[cid],manifest_hash);aid=row['annotation_id']
        if aid in seen_ids:
            if seen_ids[aid]!=row:raise InputError('Conflicting annotation IDs')
            continue
        seen_ids[aid]=row;identity=(cid,row['reviewer'])
        if row['annotation_type']=='independent':
            if identity in independent:raise InputError('One independent review per reviewer and case; preserve revisions separately')
            independent.add(identity)
        records[cid].append(row)
    return records


def resolve(case,rows):
    counts=Counter(cases=1,submitted_annotations=len(rows))
    eligible=[r for r in rows if r['reference_kind']=='human' and r['exposure']=='prediction_blind']
    independent=[r for r in eligible if r['annotation_type']=='independent']
    counts['model_proposals_excluded']+=sum(r['reference_kind']=='model_proposal' for r in rows)
    counts['prediction_exposed_excluded']+=sum(r['exposure']=='seen_predictions' for r in rows)
    for row in independent:
        for key,value in row['checks'].items():counts['review_'+key+'.'+value]+=1
    adjudications=[r for r in eligible if r['annotation_type']=='adjudication']
    if len(adjudications)>1:raise InputError('Multiple adjudications require an explicitly versioned new evaluation')
    adjudication=adjudications[0] if adjudications else None
    if adjudication:
        references=adjudication.get('reviewed_annotation_ids',[]);eligible_ids={r['annotation_id'] for r in independent}
        if (not isinstance(references,list) or any(not isinstance(x,str) for x in references)
                or len(set(references))<2 or set(references)!=eligible_ids):
            raise InputError('Adjudication must reference all of at least two independent blind human reviews')
    quality_ok=lambda r:r['checks']['attribution']=='valid' and r['checks']['segmentation']=='usable'
    resolutions=[]
    for field in case['fields']:
        votes=[r['values'][field] for r in independent];disagreement=len(set(votes))>1
        basis,reference='awaiting_two_reviews',None
        if adjudication:
            basis='adjudicated' if quality_ok(adjudication) else 'unit_excluded'
            if quality_ok(adjudication):reference=adjudication['values'][field]
        elif len(independent)>=2:
            basis='disagreement' if disagreement else 'consensus' if all(quality_ok(r) for r in independent) else 'unit_excluded'
            if basis=='consensus':reference=votes[0]
        counts['field_'+basis]+=1
        resolutions.append({'case_id':case['case_id'],'field':field,'status':basis,'reference':reference,
            'disagreement':disagreement,'votes':[{'annotation_id':r['annotation_id'],'reviewer':r['reviewer'],'value':r['values'][field]} for r in independent]})
    return {'counts':counts,'independent':independent,'adjudication':adjudication,'resolutions':resolutions}
