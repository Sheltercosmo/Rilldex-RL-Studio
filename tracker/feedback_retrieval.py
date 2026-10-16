"""Prefix-only, local lexical retrieval; ranking is not a semantic judgment."""
from collections import defaultdict
from copy import deepcopy
import re
import sqlite3

from .schema import InputError
from .readable_context import DATA_URI,subtract

VERSION='feedback-lexical-retrieval/1'
HYBRID_VERSION='feedback-recent-plus-lexical/1'
CONTEXT_VERSION='feedback-context-recent-plus-lexical/1'
VERSIONS={VERSION,HYBRID_VERSION,CONTEXT_VERSION}
OLDER_LIMIT=2
CHUNK=1200
STRIDE=1000
QUERY_LIMIT=32
STOP=frozenset('a an the and or but of to in on for from with as is are was were be been being it its this that these those i we you they he she my our your their have has had do does did not no by at into about agent says said seems appears response responses result results returned'.split())


def terms(text):
    found=[]
    for term in re.findall(r'[^\W_]+',text.casefold(),flags=re.UNICODE):
        if term not in STOP and term not in found:found.append(term)
        if len(found)==QUERY_LIMIT:break
    return found


def chunks(text):
    """Offsets always refer to the original text; encoded media is never indexed."""
    available=subtract([(0,len(text))],[(m.start(),m.end()) for m in DATA_URI.finditer(text)])
    for first,last in available:
        for start in range(first,last,STRIDE):
            end=min(last,start+CHUNK)
            if text[start:end].strip():yield start,end,text[start:end]
            if end==last:break


class FeedbackIndex:
    """An incremental FTS index per actor/trajectory, containing only its prefix.

    Out-of-order queries reset that scope rather than letting future documents
    influence BM25's corpus statistics. No persistent database is modified.
    """
    def __init__(self,records,events=()):
        self.groups=defaultdict(list);self.context_groups=defaultdict(list);self.states={}
        self.events={e['id']:e for e in events};self.excluded=[]
        for record in records:
            key=(record['action']['actor'],record['event']['trajectory_id'])
            self.groups[key].append(record)
            action=self.events.get(record['action']['source'].get('event_id'));response=record['event']
            if (action and action.get('context_id')==response.get('context_id')
                    and action['actor']==record['action']['actor'] and action['trajectory_id']==response['trajectory_id']
                    and action['index']<response['index']
                    and all(e.get('order_known') is not False and not e.get('copied_context') and e.get('agent_visibility')!='not_established' for e in (action,response))):
                self.context_groups[(*key,response.get('context_id'))].append(record)
            else:self.excluded.append(record)
        for rows in self.groups.values():rows.sort(key=lambda r:(r['event']['index'],r['unit_id']))
        for rows in self.context_groups.values():rows.sort(key=lambda r:(r['event']['index'],r['unit_id']))

    def __enter__(self):return self
    def __exit__(self,*_):
        for state in self.states.values():state['db'].close()

    def _state(self,key,cutoff):
        old=self.states.get(key)
        if old is not None and cutoff>=old['cutoff']:return old
        if old is not None:old['db'].close()
        db=sqlite3.connect(':memory:')
        try:db.execute("CREATE VIRTUAL TABLE evidence USING fts5(action, response, tokenize='porter unicode61')")
        except sqlite3.OperationalError as error:
            db.close();raise InputError('Local feedback retrieval requires SQLite FTS5 support') from error
        state={'db':db,'position':0,'cutoff':-1,'chunks':{},'records':[]}
        self.states[key]=state;return state

    def select(self,unit,cutoff,limit=3,*,version=VERSION,query_text=None):
        if version not in VERSIONS:raise InputError('Unknown feedback retrieval version')
        if type(limit) is not int or not 1<=limit<=3:raise InputError('Feedback retrieval retains one to three recent slots')
        hybrid=version in {HYBRID_VERSION,CONTEXT_VERSION}
        key=(unit['actor'],unit['trajectory_id']);records=self.groups[key]
        if version==CONTEXT_VERSION:
            event=self.events.get(unit['source']['event_id'])
            if not event or (event['actor'],event['trajectory_id'])!=key:
                raise InputError('Context-bound feedback retrieval requires the current unit source event')
            if event.get('order_known') is False or event.get('copied_context') or event.get('agent_visibility')=='not_established':
                raise InputError('Current contribution has unavailable visibility or source order')
            if type(cutoff) is not int or not 0<=cutoff<=event['index']:
                raise InputError('Feedback cutoff must not extend beyond the current contribution')
            key=(*key,event.get('context_id'));records=self.context_groups[key]
        state=self._state(key,cutoff);db=state['db']
        while state['position']<len(records) and records[state['position']]['event']['index']<cutoff:
            record=records[state['position']];state['position']+=1;state['records'].append(record)
            action=record['action']['content']['summary']['text']+'\n'+record['action']['source']['text']
            action=DATA_URI.sub(' ',action)
            for start,end,text in chunks(record['event']['text']):
                cursor=db.execute('INSERT INTO evidence(action,response) VALUES(?,?)',(action,text))
                state['chunks'][cursor.lastrowid]=(record,start,end)
        state['cutoff']=cutoff
        query=terms(DATA_URI.sub(' ',query_text) if query_text is not None else unit['content']['situation']['text']);ranked={}
        if query:
            expression=' OR '.join('"'+term.replace('"','""')+'"' for term in query)
            # Parameterized FTS expressions use only quoted lexical tokens.
            for rowid,score in db.execute('SELECT rowid,bm25(evidence,2.0,1.0) FROM evidence WHERE evidence MATCH ? ORDER BY 2,rowid DESC',(expression,)):
                record,start,end=state['chunks'][rowid]
                ranked.setdefault(record['unit_id'],(record,start,end,score))
        recent_ids=set()
        if hybrid:
            recent=state['records'][-limit:];recent_ids={r['unit_id'] for r in recent}
            chosen=[ranked.get(r['unit_id'],(r,None,None,None)) for r in recent]
            chosen.extend([r for uid,r in ranked.items() if uid not in recent_ids][:OLDER_LIMIT])
        else:chosen=list(ranked.values())[:limit]
        chosen_ids={r[0]['unit_id'] for r in chosen}
        fallback=[]
        for record in reversed(state['records']):
            if len(chosen)>=limit:break
            if record['unit_id'] not in chosen_ids:
                chosen.append((record,None,None,None));chosen_ids.add(record['unit_id']);fallback.append(record['event']['id'])
        selected=[];details=[]
        for record,start,end,score in sorted(chosen,key=lambda r:r[0]['event']['index'],reverse=True):
            candidate=deepcopy(record)
            if start is not None:candidate['retrieval_ranges']=[{'event_id':record['event']['id'],'start':start,'end':end}]
            selected.append(candidate)
            details.append({'feedback_event_id':record['event']['id'],'feedback_unit_id':record['unit_id'],
                            'method':'retained_recent' if record['unit_id'] in recent_ids else 'lexical_match' if score is not None else 'recent_fallback',
                            'lexical_score':score,'ranges':candidate.get('retrieval_ranges',[])})
        report={'schema':version,'engine':'SQLite FTS5 porter/unicode61 BM25; action weight 2, response weight 1',
                'sqlite_version':sqlite3.sqlite_version,
                'query_terms':query,'query_term_limit':QUERY_LIMIT,'candidate_limit':limit+(OLDER_LIMIT if hybrid else 0),
                'eligible_prior_responses':len(state['records']),'lexically_matched_responses':len(ranked),
                'omitted_responses':max(0,len(state['records'])-len(selected)),
                'selected':details,'fallback_event_ids':fallback,'cutoff_event_id':unit['source']['event_id'],
                'limit':'Lexical retrieval is incomplete for paraphrases and unresolved temporal references. A ranked hit is not an assessment link; omitted responses are not negative evidence.'}
        if hybrid:report.update(retained_recent_limit=limit,additional_older_limit=OLDER_LIMIT)
        if version==CONTEXT_VERSION:
            report.update(context_id=event.get('context_id'),scope='same actor, trajectory and source context',
                          excluded_source_event_ids=sorted({r['event']['id'] for r in self.excluded
                              if r['event']['index']<cutoff and r['event']['trajectory_id']==unit['trajectory_id']
                              and r['action']['actor']==unit['actor'] and r['event'].get('context_id')==event.get('context_id')}))
        return selected,report
