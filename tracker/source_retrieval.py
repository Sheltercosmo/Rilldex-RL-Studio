"""Bounded lexical recall over a caller's already visible source prefix."""
import sqlite3

from .schema import InputError
from .feedback_retrieval import terms, chunks
from .readable_context import DATA_URI

VERSION='source-prefix-retrieval/1'
LIMIT=6


def select(records, query_text, *, retained_ids=(), limit=LIMIT):
    """Return exact source ranges; ranking never creates a semantic relation.

    The caller supplies only eligible history. Corpus statistics therefore cannot
    depend on future events, other sessions or private evaluator observations.
    Retained items get matching ranges without consuming older-history slots.
    """
    if type(limit) is not int or not 1<=limit<=12:raise InputError('Invalid source retrieval limit')
    query=terms(DATA_URI.sub(' ',query_text));ranked={};retained=set(retained_ids)
    db=sqlite3.connect(':memory:');lookup={}
    try:
        db.execute("CREATE VIRTUAL TABLE source USING fts5(text, tokenize='porter unicode61')")
        for record in records:
            for start,end,text in chunks(record['text']):
                cursor=db.execute('INSERT INTO source(text) VALUES(?)',(text,))
                lookup[cursor.lastrowid]=(record['id'],start,end)
        if query:
            expression=' OR '.join('"'+t.replace('"','""')+'"' for t in query)
            for rowid,score in db.execute('SELECT rowid,bm25(source) FROM source WHERE source MATCH ? ORDER BY 2,rowid DESC',(expression,)):
                eid,start,end=lookup[rowid]
                ranked.setdefault(eid,{'event_id':eid,'start':start,'end':end,'lexical_score':score})
    except sqlite3.OperationalError as exc:
        raise InputError('Source retrieval requires SQLite FTS5') from exc
    finally:db.close()
    older=[r for eid,r in ranked.items() if eid not in retained][:limit]
    selected=[r for eid,r in ranked.items() if eid in retained]+older
    return {'schema':VERSION,'query_terms':query,'additional_event_limit':limit,
            'matched_events':len(ranked),'selected':selected,
            'limit':'Lexical source matches are context candidates, not established identity, revision, causation or current state. Later observations can supersede earlier ones. Paraphrases without shared terms may remain unretrieved.'}
