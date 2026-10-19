"""Carry reviewed qualifications into local relationships without flattening.

This opt-in successor input preserves fixed work and source spans. It does not
replace stored observations or certify the semantics of model selections.
"""
from copy import deepcopy

from . import work_content_bindings as contents, work_content_targets as details
from . import work_argument_pairs as argument_pairs
from . import work_scope_interpretations as scopes, work_mentions
from .jev import DEFAULT_MODEL, SELECTION_POLICY, validate_answers
from .schema import digest, dumps

VERSION = 'qualified-work-contents/1'
require = contents.require


def review(prepared, bound, *, syntax, send, feature_ids=None, inventory_selection=None,
           scope_version=scopes.VERSION, target_version=None, argument_roles=False,
           argument_version=details.ARGUMENT_HEAD_VERSION, on_progress=None):
    """Review qualifications using syntax candidates and a caller-owned transport.

    ``send(request)`` returns a Jev response. Supply a cached, budgeted transport
    for resumable jobs; this function never retries or changes the caller's
    budget. ``on_progress`` receives a fresh snapshot after each selection.
    Syntax proposes alternatives; argmax selects scope and detail. No work is
    added, and partial reviews are useful without certifying completeness.
    """
    from . import work_syntax_evidence
    contents.checked(prepared,bound)
    work_syntax_evidence.checked(prepared,bound,syntax)
    require(callable(send),'qualification review requires a response transport')
    require(on_progress is None or callable(on_progress),'progress callback must be callable')
    require(scope_version in (scopes.LEGACY_VERSION,scopes.VERSION),'unknown scope interpretation version')
    require(target_version in (None,details.VERSION,details.SELECTOR_VERSION),'unknown detail selector version')
    require(type(argument_roles) is bool,'argument_roles must be boolean')
    require(argument_version in (*details.ARGUMENT_VERSIONS,*argument_pairs.VERSIONS),
            'unknown argument selector version')
    require(argument_roles or argument_version==details.ARGUMENT_HEAD_VERSION,
            'an argument selector requires argument_roles=True')
    known={f['id'] for f in bound['features']}
    ids=sorted(known) if feature_ids is None else feature_ids
    require(isinstance(ids,(list,tuple)) and all(isinstance(fid,str) and fid in known for fid in ids)
            and len(ids)==len(set(ids)), 'unique known feature IDs required')
    # Validate supplied inventory evidence before any paid request.
    reviews=dict(inventory_selection=inventory_selection,scope_reviews=[],target_reviews=[])
    project(prepared,bound,**reviews)
    completed=0
    def snapshot(stage,feature_id=None,content_id=None):
        result = dict(schema=VERSION+'/review',stage=stage,feature_id=feature_id,content_id=content_id,
            requested_feature_ids=sorted(ids),scope_version=scope_version,completed_requests=completed,
            reviews=deepcopy(reviews),view=project(prepared,bound,**reviews),
            publication='review_only',
            limit='Completed requests include cache reuse, not HTTP or token usage. Transport owns billing and resume.')
        if argument_roles:
            result['argument_roles']=True
            result['argument_version']=argument_version
        return result
    for fid in sorted(ids):
        req=scopes.request(prepared,bound,fid,syntax=syntax,version=scope_version)
        selected=scopes.resolve(prepared,bound,fid,send(req),syntax=syntax,version=scope_version)
        reviews['scope_reviews'].append(dict(decision=selected,syntax=deepcopy(syntax)));completed+=1
        if on_progress:on_progress(snapshot('scope',fid))
        if selected['selected'] is None or selected['selected']['application']=='joint':continue
        for cid in selected['selected']['content_ids']:
            feature=next(f for f in bound['features'] if f['id']==fid)
            is_argument=argument_roles and feature['type'] in {'subject','target'}
            targets=(details.argument_targets_from_syntax if is_argument else details.from_syntax)(prepared,bound,cid,syntax)
            version=argument_version if is_argument else target_version
            if version in argument_pairs.VERSIONS:
                req=argument_pairs.request(prepared,bound,fid,targets,syntax,version=version)
                decision=argument_pairs.resolve(prepared,bound,fid,targets,syntax,send(req),version=version)
            else:
                extra={'syntax_record':syntax} if version==details.ARGUMENT_SYNTAX_VERSION else {}
                req=details.request(prepared,bound,fid,targets,version=version,**extra)
                decision=details.resolve(prepared,bound,fid,targets,send(req),version=version,**extra)
            reviews['target_reviews'].append(dict(targets=targets,decision=decision));completed+=1
            if on_progress:on_progress(snapshot('target',fid,cid))
    return snapshot('complete')


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
        is_pairs=decision.get('schema') in argument_pairs.VERSIONS
        view = (argument_pairs.project if is_pairs else details.project)(prepared, bound, fid, review['targets'], decision)
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
            if target_decision['schema'] in argument_pairs.VERSIONS:
                row['feature']={k:deepcopy(v) for k,v in feature.items() if k not in {'scopes','type','form'}}
                row['feature'].update(type='argument',proposed_type=feature['type'],proposed_form=feature['form'])
                row.setdefault('predicate_reviews',[]).append(dict(content_id=cid,coverage=view['coverage'],
                    relations=deepcopy(view['relations']),target_review_hash=digest(target_decision)))
                for qualification in view['qualifications']:
                    row['targets'].append(dict(content_id=cid,status='selected',target=deepcopy(qualification['target']),
                        role=qualification['role'],form=view['form'],target_review_hash=digest(target_decision)))
                if view['issues']:
                    row['status']='target_review_incomplete'
                    issues.extend(dict(type=issue,feature_id=fid,content_id=cid) for issue in view['issues'])
                continue
            target = view['qualification']['target'] if view['qualification'] else None
            row['targets'].append(dict(content_id=cid, status=view['status'], target=deepcopy(target),
                target_review_hash=digest(target_decision)))
            if target_decision['schema'] in details.ARGUMENT_VERSIONS:
                row['feature']={k:deepcopy(v) for k,v in feature.items() if k not in {'scopes','type','form'}}
                row['feature'].update(type='argument',proposed_type=feature['type'],proposed_form=feature['form'])
                row['targets'][-1].update(role=target_decision['role'],form=target_decision['form'])
            if target is None:
                row['status'] = 'target_review_incomplete'
                issues.append(dict(type='target_'+view['status'], feature_id=fid, content_id=cid))
    # A competing owner or detail review of a joint scope cannot silently vanish.
    for key in sorted(set(target_index)-used):
        fid,cid = key
        issues.append(dict(type='target_scope_disagreement', feature_id=fid, content_id=cid,
            target_review_hash=digest(target_index[key][0])))
    # Do not describe a mixed old/new target set as fully role-reviewed.
    for row in rows:
        if row['feature']['type']=='argument':
            for target in row['targets']:
                if 'role' not in target:
                    issues.append(dict(type='argument_role_not_reviewed',feature_id=row['feature']['id'],
                        content_id=target.get('content_id')))
    result = dict(schema=VERSION, packet_hash=digest(prepared), bound_hash=digest(bound),
        unit=deepcopy(unit), contents=deepcopy(bound['contents']), qualifications=rows,
        inventory_assessment=inventory, inventory_review_hash=digest(inventory_selection) if inventory_selection else None,
        issues=issues, ready_for_relationships=not issues,
        coverage=dict(features=len(bound['features']), scope_reviews=len(scope_index), target_reviews=len(target_index)),
        execution_status='not_established_by_prose', publication='review_only',
        limit='Review completeness is a stage requirement, not independent semantic accuracy. No new activities or live graph edges.')
    if any(d['schema'] in details.ARGUMENT_VERSIONS for d,_ in target_index.values()):
        result['argument_role_questions']=deepcopy(details.ARGUMENT_ROLES)
    if any(d['schema'] in argument_pairs.VERSIONS for d,_ in target_index.values()):
        result['argument_role_questions']=deepcopy(argument_pairs.ROLE_QUESTIONS)
    return result


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
    if 'argument_role_questions' in view:
        request['argument_role_questions']=view['argument_role_questions']
        request['rule']+=' Argument targets carry selected predicate-specific roles and forms. proposed_type and proposed_form are historical generator labels, not selected meanings.'
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
    if 'argument_role_questions' in req:
        request['state']['argument_role_questions']=req['argument_role_questions']
    require(len(dumps(request).encode('utf-8')) <= contents.MAX_SELECTION_BYTES,
            'qualified link selection exceeds byte budget; do not truncate')
    return request


def observation(prepared, bound, links, response, **reviews):
    req = selection_request(prepared,bound,links,**reviews)
    require(isinstance(response,dict) and response.get('model') == req['model'], 'relationship selector model differs')
    answers = validate_answers(response,req)
    rows = [dict(**deepcopy(link),choice=answers[link['id']]['value']) for link in links['links']]
    result = dict(schema=VERSION,stage='shadow_observation',packet_hash=digest(prepared),bound_hash=digest(bound),
        review_hash=req['state']['review_hash'],links_hash=digest(links),request_hash=digest(req),response=deepcopy(response),
        unit=deepcopy(req['state']['unit']),contents=deepcopy(req['state']['contents']),
        qualifications=deepcopy(req['state']['qualifications']),links=rows,
        supported_links=[link['id'] for link in rows if link['choice']=='supported'],
        relationship_coverage=answers['coverage']['value'],selection_policy=SELECTION_POLICY,
        execution_status='not_established_by_prose',publication='review_only',
        limit='Selected local reading; no native execution, cross-unit identity, hierarchy or semantic accuracy guarantee.')
    if 'argument_role_questions' in req['state']:
        result['argument_role_questions']=req['state']['argument_role_questions']
    return result
