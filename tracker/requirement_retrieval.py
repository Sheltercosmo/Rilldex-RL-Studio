"""Local evidence ordering. Every page remains in the eventual scan."""
from collections import defaultdict
import re
import sqlite3

from .feedback_retrieval import STOP

VERSION='requirement-page-order/1'


def tokens(text):
    # Keep both exact API names and their words: cancellationReason -> cancellation reason.
    expanded=re.sub(r'([a-z0-9])([A-Z])',r'\1 \2',text)
    return list(dict.fromkeys(w for w in re.findall(r'[^\W_]+',text.casefold()+' '+expanded.casefold())
                             if w not in STOP and len(w)>1))


def order(source_pages,requirements):
    """Diversify BM25 hits across short clauses before reading broad summaries.

    This orders work under a request budget. It does not label risk, select
    findings, discard low-score pages, or require any model/embedding service.
    """
    db=sqlite3.connect(':memory:')
    try:
        db.execute("CREATE VIRTUAL TABLE fragments USING fts5(page UNINDEXED, start UNINDEXED, content, tokenize='porter unicode61')")
        for page,fragments in enumerate(source_pages):
            for f in fragments:
                if f['origin']=='trace' and f.get('actor') not in {'user','system','developer'}:
                    db.execute('INSERT INTO fragments VALUES (?,?,?)',(page,f['start'],' '.join(tokens(f['text']))))
        scores=defaultdict(float);matches=defaultdict(list);lists=[]
        for requirement in requirements:
            text=requirement.get('display_text',requirement['text'])
            # These are retrieval queries only. Judgment retains the complete paragraph.
            clauses=[c for c in re.split(r';|[.!?](?:\s|$)|\n',text) if len(tokens(c))>=2]
            queries=list(dict.fromkeys(clauses+[text]))
            for clause in queries:
                query=tokens(clause)
                if not query:continue
                expression=' OR '.join('"'+word+'"' for word in query[:256])
                cutoff=0 if requirement['origin']=='task' else requirement['end']
                rows=db.execute('SELECT page,bm25(fragments,0,0,1) FROM fragments WHERE fragments MATCH ? AND CAST(start AS INTEGER)>=? ORDER BY 2,rowid',(expression,cutoff))
                seen=set();ranking=[]
                for page,_ in rows:
                    page=int(page)
                    if page in seen:continue
                    seen.add(page);ranking.append(page);rank=len(seen);scores[page]+=1/(60+rank)
                    matches[page].append(dict(requirement_id=requirement['id'],query=clause,rank=rank))
                lists.append(ranking)
        # First hits cover different task properties. Deeper rounds recover pages
        # with less literal vocabulary, and chronological fallback keeps every page.
        ranked=[];seen=set()
        for depth in range(max(map(len,lists),default=0)):
            for ranking in lists:
                if depth<len(ranking) and ranking[depth] not in seen:
                    seen.add(ranking[depth]);ranked.append(ranking[depth])
        ranked.extend(p for p in range(len(source_pages)) if p not in seen)
        return dict(schema=VERSION,pages=ranked,ranking=[dict(page=p,score=scores[p],matches=matches[p]) for p in ranked],
                    scope='Scheduling priority only; all source pages remain queued.')
    finally:db.close()
