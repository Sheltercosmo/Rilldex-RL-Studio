"""Carry reviewed qualifications into local relationships without flattening.

This opt-in successor input preserves fixed work and source spans. It does not
replace stored observations or certify the semantics of model selections.
"""
from copy import deepcopy

from . import work_content_bindings as contents, work_content_targets as details
from . import work_scope_interpretations as scopes, work_mentions
from .jev import DEFAULT_MODEL, SELECTION_POLICY, validate_answers
from .schema import digest, dumps

VERSION = 'qualified-work-contents/1'
require = contents.require


def project(prepared, bound, *, inventory_selection=None, scope_reviews=(), target_reviews=()):
    """Combine exact review receipts; pending/disagreeing readings stay visible.

    Scope reviews contain ``decision`` and optionally ``syntax``. Target reviews
    contain ``targets`` and ``decision``. They must refer to this same inventory.
    Inventory selection contributes only its inventory assessment; its older
    attachment choices are not reused as individual or joint interpretations.
    """
    unit = contents.checked(prepared, bound)['unit']
    require(isinstance(scope_reviews, (list, tuple)) and len(scope_reviews) <= 32,
            'at most 32 scope reviews')
    require(isinstance(target_reviews, (list, tuple)) and len(target_reviews) <= 384,
            'at most 384 content-target reviews')
    issues = []; scope_index = {}; target_index = {}; inventory = 'not_reviewed'
    if inventory_selection is not None:
        require(isinstance(inventory_selection, dict) and inventory_selection == contents.select(
            prepared, bound, inventory_selection.get('response'),
            candidate_policy=inventory_selection.get('candidate_policy', contents.SUPPLIED_SCOPES)),
            'inventory selection receipt changed')
        inventory = inventory_selection['inventory']
    if inventory != 'adequate':
        issues.append(dict(type='inventory_'+inventory))
    for review in scope_reviews:
        require(isinstance(review, dict) and set(review) in ({'decision'}, {'decision','syntax'}) and
                isinstance(review['decision'], dict), 'scope decision and optional syntax required')
        decision = review['decision']; fid = decision.get('feature_id')
        scopes.project(prepared, bound, fid, decision, syntax=review.get('syntax'))
        require(fid not in scope_index, 'duplicate feature scope review')
        scope_index[fid] = decision
    for review in target_reviews:
        require(isinstance(review, dict) and set(review) == {'targets','decision'} and
                isinstance(review['decision'], dict), 'target candidates and decision required')
        decision = review['decision']; fid = decision.get('feature_id')
        view = details.project(prepared, bound, fid, review['targets'], decision)
        key = (fid, decision['content_id'])
        require(key not in target_index, 'duplicate content-target review')
        target_index[key] = (decision, view)

    rows = []; used = set()
    for feature in sorted(bound['features'], key=lambda f:f['id']):
        fid = feature['id']; decision = scope_index.get(fid)
        row = dict(feature={k:deepcopy(v) for k,v in feature.items() if k!='scopes'},
            status='scope_not_reviewed', application=None, targets=[], scope_review_hash=None)
        rows.append(row)
        if decision is None:
            issues.append(dict(type='scope_not_reviewed', feature_id=fid)); continue
        row['scope_review_hash'] = digest(decision)
        selected = decision['selected']
        if selected is None:
            row['status'] = decision['status']
            issues.append(dict(type='scope_'+decision['status'], feature_id=fid)); continue
        row.update(application=selected['application'], status='selected')
        if selected['application'] == 'joint':
            # Keep one combined scope. No per-member prohibition, condition,
            # assertion or completion follows from this group attachment.
            row['targets'] = [dict(kind='content_group', content_ids=deepcopy(selected['content_ids']),
                distribution='not_distributed', source_context=deepcopy(unit['source']))]
            continue
        for cid in selected['content_ids']:
            key = (fid, cid); used.add(key)
            pair = target_index.get(key)
            if pair is None:
                row['status'] = 'target_review_incomplete'
                row['targets'].append(dict(content_id=cid, status='not_reviewed', target=None))
                issues.append(dict(type='target_not_reviewed', feature_id=fid, content_id=cid)); continue
            target_decision, view = pair
            target = view['qualification']['target'] if view['qualification'] else None
            row['targets'].append(dict(content_id=cid, status=view['status'], target=deepcopy(target),
                target_review_hash=digest(target_decision)))
            if target is None:
                row['status'] = 'target_review_incomplete'
                issues.append(dict(type='target_'+view['status'], feature_id=fid, content_id=cid))
    # A competing owner or detail review of a joint scope cannot silently vanish.
    for key in sorted(set(target_index)-used):
        fid,cid = key
        issues.append(dict(type='target_scope_disagreement', feature_id=fid, content_id=cid,
            target_review_hash=digest(target_index[key][0])))
    return dict(schema=VERSION, packet_hash=digest(prepared), bound_hash=digest(bound),
        unit=deepcopy(unit), contents=deepcopy(bound['contents']), qualifications=rows,
        inventory_assessment=inventory, inventory_review_hash=digest(inventory_selection) if inventory_selection else None,
        issues=issues, ready_for_relationships=not issues,
        coverage=dict(features=len(bound['features']), scope_reviews=len(scope_index), target_reviews=len(target_index)),
        execution_status='not_established_by_prose', publication='review_only',
        limit='Review completeness is a stage requirement, not independent semantic accuracy. No new activities or live graph edges.')


def relationship_request(prepared, bound, **reviews):
    from .work_content_stages import RELATION_RULE
    view = project(prepared, bound, **reviews)
    require(view['ready_for_relationships'], 'qualification reviews incomplete or disagree; relationships blocked')
    request = dict(schema=VERSION, stage='relationships', unit=view['unit'],
        review_hash=digest(view), contents=view['contents'], qualifications=view['qualifications'],
        rule=RELATION_RULE+' Qualifications are separate records. A content_group is qualified jointly; '
            'never copy its qualification onto members. A content_detail qualifies only its exact target span, '
            'not the entire owning operation. Do not create new work or link endpoints for details or groups.',
        link_meanings=deepcopy(work_mentions.LINKS),
        response_format=dict(links=[dict(source='content ID',target='content ID',type='one link type',
            evidence=dict(text='Exact contiguous relationship quote'))],
            content_issues=[dict(mention_ids=['content ID, or empty for missing content'],
                evidence=dict(text='Exact source quote'),issue='Content or qualification defect preventing relationships')]),
        publication='review_only')
    require(len(dumps(request).encode('utf-8')) <= contents.MAX_SELECTION_BYTES,
            'qualified relationship request exceeds byte budget; do not truncate reviews or source')
    return request


def bind_links(prepared, bound, response, producer, **reviews):
    req = relationship_request(prepared, bound, **reviews)
    require(isinstance(producer, str) and 0 < len(producer.strip()) <= 240, 'named relationship producer required')
    require(isinstance(response, dict) and set(response) == {'links','content_issues'}, 'links and content issues required')
    require(isinstance(response['content_issues'], list) and not response['content_issues'],
            'content review required before linking')
    require(isinstance(response['links'], list) and len(response['links']) <= 32, 'at most 32 links')
    require(len(dumps(response).encode('utf-8')) <= 100_000, 'link proposal exceeds byte budget')
    ids = {c['id'] for c in bound['contents']}; seen = set(); links = []
    for link in response['links']:
        require(isinstance(link, dict) and set(link) == {'source','target','type','evidence'}, 'invalid link fields')
        require(all(isinstance(link[k],str) for k in ('source','target','type')) and
            link['source'] in ids and link['target'] in ids and link['source'] != link['target'] and
            link['type'] in work_mentions.LINKS, 'invalid local relationship')
        key = (link['source'],link['target'],link['type'])
        require(key not in seen, 'duplicate relationship'); seen.add(key)
        links.append(dict(id='l'+str(len(links)),source=link['source'],target=link['target'],type=link['type'],
            evidence=work_mentions.quote(link['evidence'],req['unit'])))
    return dict(schema=VERSION,stage='links',request_hash=digest(req),producer=producer,
        raw_response=deepcopy(response),links=links,publication='review_only')


def selection_request(prepared, bound, links, **reviews):
    req = relationship_request(prepared, bound, **reviews)
    require(isinstance(links,dict) and links == bind_links(prepared,bound,links.get('raw_response'),
        links.get('producer'),**reviews), 'qualified relationship proposal changed')
    questions = {link['id']:dict(type='choice',instructions=(
        'Does the source express this exact relationship and direction? '+dumps(link)+
        ' Preserve all qualifications, including group and detail targets. Proposed order is not execution. '
        'Practical plausibility and shared wording are insufficient.'),criteria=dict(
            supported='The source expresses this typed link between these exact contents.',
            unsupported='The link, endpoint or direction is not supported.',
            unresolved='The source does not resolve this link.')) for link in links['links']}
    questions['coverage'] = dict(type='choice',instructions='Are explicit local relationships missing?',criteria=dict(
        complete='No explicit local relationships are missing.',incomplete='An explicit local relationship is missing.',
        unresolved='Cannot establish relationship coverage.'))
    request = dict(model=DEFAULT_MODEL,state=dict(harness=VERSION,unit=req['unit'],rule=req['rule'],
        review_hash=req['review_hash'],contents=req['contents'],qualifications=req['qualifications'],
        links=links['links'],link_meanings=req['link_meanings'],cutoff_event_id=req['unit']['source']['event_id'],
        missingness=dict(truncated_event_ids=[])),questions=questions)
    require(len(dumps(request).encode('utf-8')) <= contents.MAX_SELECTION_BYTES,
            'qualified link selection exceeds byte budget; do not truncate')
    return request


def observation(prepared, bound, links, response, **reviews):
    req = selection_request(prepared,bound,links,**reviews)
    require(isinstance(response,dict) and response.get('model') == req['model'], 'relationship selector model differs')
    answers = validate_answers(response,req)
    rows = [dict(**deepcopy(link),choice=answers[link['id']]['value']) for link in links['links']]
    return dict(schema=VERSION,stage='shadow_observation',packet_hash=digest(prepared),bound_hash=digest(bound),
        review_hash=req['state']['review_hash'],links_hash=digest(links),request_hash=digest(req),response=deepcopy(response),
        unit=deepcopy(req['state']['unit']),contents=deepcopy(req['state']['contents']),
        qualifications=deepcopy(req['state']['qualifications']),links=rows,
        supported_links=[link['id'] for link in rows if link['choice']=='supported'],
        relationship_coverage=answers['coverage']['value'],selection_policy=SELECTION_POLICY,
        execution_status='not_established_by_prose',publication='review_only',
        limit='Selected local reading; no native execution, cross-unit identity, hierarchy or semantic accuracy guarantee.')
