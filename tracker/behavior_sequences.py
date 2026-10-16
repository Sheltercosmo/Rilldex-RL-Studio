"""Occurrence-preserving activity sequences. Order is not causality or task purpose."""
from collections import Counter, defaultdict
from .schema import digest
VERSION = 'activity-sequence/4'
# A sequence must preserve the unit vocabulary. Distribution groupings merge
# distinct operations (e.g. Orient/Plan) and cannot stand in for task phases.
CATEGORIES = {key: {'label':label, 'color':color} for key,label,color in [
    ('orient','Orient','#73849a'),('knowledge','State knowledge','#88999d'),
    ('plan','Plan','#7663b6'),('hypothesize','Hypothesize','#ab7ca1'),
    ('reason','Reason / derive','#5c7da9'),('decide','Decide','#87669b'),
    ('inspect','Inspect / retrieve','#45949b'),('construct','Execute / construct','#b58a46'),
    ('execute','Execute (legacy)','#b09c6b'),('verify','Verify','#669273'),
    ('coordinate','Coordinate / request','#ac778f'),('report','Report / deliver','#a17766'),
    ('decline','Decline','#9b747e'),('social','Social','#8c879b'),
    ('other','Other activity','#9296a4'),('unresolved','Unresolved activity','#b2b5bf')]}
CATEGORIES.update(unknown={'label':'Unmapped activity','color':'#9296a4'},
                  gap={'label':'Unobserved / ambiguous','color':'#c5c8cf'},
                  end={'label':'Observation ends','color':'#dee0e5'},
                  tail={'label':'Further transitions','color':'#677080'})


def project(graph):
    events = sorted([n['properties'] for n in graph['nodes'] if n['kind']=='event'], key=lambda e:e['index'])
    units = defaultdict(list)
    for n in graph['nodes']:
        p=n['properties']
        if n['kind']=='unit' and p.get('actor')=='agent' and p.get('kind')!='feedback':
            units[p.get('source',{}).get('event_id')].append(n)
    lanes=defaultdict(list); missing=0; unit_count=0; source_records=0
    batches=Counter((e['trajectory_id'],e.get('parent_id')) for e in events if e['kind']=='action' and e.get('parent_id'))
    def append(lane, category, eid, uid=None, start=None, end=None, member=None):
        # Gaps never disappear through compression, even between matching labels.
        if not lane or lane[-1]['category']!=category:
            lane.append({'position':len(lane)+1,'category':category,'unit_ids':[],'event_ids':[],'spans':[],'members':[]})
        b=lane[-1]
        if uid:b['unit_ids'].append(uid)
        if member:b['members'].append(member)
        if eid not in b['event_ids']:b['event_ids'].append(eid)
        if start is not None:b['spans'].append({'event_id':eid,'start':start,'end':end})
    for e in events:
        if e.get('actor')!='agent' or e.get('copied_context') or not e.get('text','').strip():continue
        source_records+=1; lane=lanes[e['trajectory_id']]; text=e['text']; rows=units.get(e['id'],[])
        bounds=[n['properties'].get('source',{}) for n in rows]
        valid=bool(rows) and all(type(b.get('start')) is int and type(b.get('end')) is int and
            0<=b['start']<b['end']<=len(text) and text[b['start']:b['end']]==b.get('text') for b in bounds)
        rows=sorted(rows,key=lambda n:n['properties'].get('source',{}).get('start',0)) if valid else []
        overlapping=any(a['properties']['source']['end']>b['properties']['source']['start'] for a,b in zip(rows,rows[1:]))
        if not valid or overlapping or e.get('batch_size',0)>1 or batches[(e['trajectory_id'],e.get('parent_id'))]>1:
            append(lane,'gap',e['id']);missing+=1;continue
        cursor=0
        for n in rows:
            s=n['properties']['source']
            if text[cursor:s['start']].strip():append(lane,'gap',e['id'],start=cursor,end=s['start']);missing+=1
            activity=n.get('activity');content=n['properties'].get('content',{})
            summary=content.get('summary',{})
            summary=summary.get('text','') if isinstance(summary,dict) else ''
            member={'unit_id':n['id'],'event_id':e['id'],'event_index':e['index'],
                    'activity':activity,'summary':summary[:240],'excerpt':s['text'][:240],
                    'start':s['start'],'end':s['end']}
            append(lane,activity if activity in CATEGORIES else 'unknown',e['id'],n['id'],s['start'],s['end'],member);unit_count+=1
            cursor=s['end']
        if text[cursor:].strip():append(lane,'gap',e['id'],start=cursor,end=len(text));missing+=1
    paths=[{'trajectory_id':k,'blocks':v} for k,v in sorted(lanes.items())]
    pairs=[]
    for p in paths:
        for a,b in zip(p['blocks'],p['blocks'][1:]):
            if {a['category'],b['category']} & {'gap','unknown','unresolved'}:continue
            pairs.append({'from':a['category'],'to':b['category'],'trajectory_id':p['trajectory_id'],
                          'from_units':a['unit_ids'],'to_units':b['unit_ids']})
    value={'schema':VERSION,'run_id':graph['run_id'],'graph_id':graph['id'],'observer':graph['observer'],
           'source_hash':graph['source_hash'],'paths':paths,'pairs':pairs,'units':unit_count,
           'source_records':source_records,'gaps':missing,'flow_eligible':len(paths)==1 and unit_count>0,
           'limit':'Consecutive units of the same base activity form a block. Blocks are not task phases; adjacency is not a relationship. Observation ends is not termination. Parallel trajectories are not concatenated.'}
    return {'id':'sequence-'+digest(value),**value}


def compare(sequences, focus, reference, width=10):
    """Every flow column retains the initial eligible mass; paths retain run IDs."""
    requested_width=max(2,min(20,width));by_id={s['run_id']:s for s in sequences};groups={}
    # Stop after all observed paths end, rather than filling an arbitrary horizon
    # with repeated end markers. Keep one boundary column for an end or a tail.
    lengths=[len(s['paths'][0]['blocks']) for s in sequences
             if s['flow_eligible'] and s['run_id'] in set(focus+reference)]
    width=min(requested_width,max(lengths,default=requested_width))
    for name,ids in [('focus',focus),('reference',reference)]:
        chosen=[by_id[i] for i in ids if i in by_id]; eligible=[s for s in chosen if s['flow_eligible']]
        paths=[];columns=[defaultdict(list) for _ in range(width+1)];links=[defaultdict(list) for _ in range(width)]
        matrix=defaultdict(list); shares=defaultdict(list)
        for s in eligible:
            blocks=s['paths'][0]['blocks'];cats=[b['category'] for b in blocks]
            visible=[cats[i] if i<len(cats) else 'end' for i in range(width)]
            visible.append('tail' if len(cats)>width else 'end')
            paths.append({'run_id':s['run_id'],'graph_id':s['graph_id'],'trajectory_id':s['paths'][0]['trajectory_id'],
                          'categories':visible,'blocks':blocks,'units':s['units'],'source_records':s['source_records'],
                          'gaps':s['gaps'],'hidden_blocks':max(0,len(blocks)-width)})
            for i,cat in enumerate(visible):columns[i][cat].append(s['run_id'])
            for i,(a,b) in enumerate(zip(visible,visible[1:])):links[i][(a,b)].append(s['run_id'])
        # All single/multiple trajectory runs contribute known adjacent pairs, without joining lanes.
        for s in chosen:
            counts=Counter((p['from'],p['to']) for p in s['pairs']);total=sum(counts.values())
            for key,count in counts.items():matrix[key].append({'run_id':s['run_id'],'count':count,'total':total,'graph_id':s['graph_id']})
            if total:
                for a in CATEGORIES:
                    for b in CATEGORIES:shares[(a,b)].append(counts[(a,b)]/total)
        groups[name]={'total':len(ids),'available':len(chosen),'flow_eligible':len(eligible),
            'missing_or_multistream':len(ids)-len(eligible),'paths':paths,
            'columns':[[{'category':k,'count':len(v),'run_ids':v} for k,v in sorted(c.items())] for c in columns],
            'links':[[{'from':a,'to':b,'count':len(v),'run_ids':v} for (a,b),v in sorted(c.items())] for c in links],
            'transitions':[{'from':a,'to':b,'count':sum(v['count'] for v in rows),'rollouts':len(rows),
                'mean_pair_share':sum(shares[(a,b)])/len(shares[(a,b)]),'witnesses':rows} for (a,b),rows in sorted(matrix.items())],
            'pair_rollouts':sum(bool(s['pairs']) for s in chosen)}
    return {'schema':VERSION,'categories':CATEGORIES,'width':width,'requested_width':requested_width,'groups':groups,
            'definition':'Flow: one path per eligible single-trajectory rollout. Matrix: mean per-rollout share of eligible compressed adjacent pairs. Gaps are not bridged.'}
