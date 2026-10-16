"""Durable local consumption of analysis feeds, independent of the source store.

Receipts and their consumer cursor commit in one SQLite transaction. This is an
append evidence cache for downstream code, not a current-state workspace replica.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .analytics import Analysis, FEEDS, _integer
from .schema import InputError

VERSION = 'research-feed-mirror/1'


def serialized(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))


class FeedMirror:
    def __init__(self, source, destination):
        if not isinstance(source,Analysis):raise InputError('FeedMirror requires a local Analysis source')
        self.source=source;self.path=Path(destination).expanduser().resolve()
        if self.path==source.path or self.path.exists() and os.path.samefile(self.path,source.path):
            raise InputError('The result mirror must be separate from the source workspace')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        created=False
        try:
            with self.path.open('xb'):pass
            created=True
        except FileExistsError:pass
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mirror_identity'").fetchone()
            if not exists and not created:raise InputError('Destination is not a result mirror; choose a new database file')
            if created:
                c.execute('CREATE TABLE mirror_identity(schema TEXT NOT NULL,source TEXT NOT NULL)')
                c.execute('INSERT INTO mirror_identity VALUES (?,?)',(VERSION,str(source.path)))
                c.execute('''CREATE TABLE feed_cursors(feed TEXT PRIMARY KEY,cursor_json TEXT NOT NULL,updated_at TEXT NOT NULL)''')
                c.execute('''CREATE TABLE receipts(feed TEXT NOT NULL,receipt_id TEXT NOT NULL,sequence INTEGER NOT NULL,
                  recorded_at TEXT NOT NULL,document_json TEXT NOT NULL,sha256 TEXT NOT NULL,
                  PRIMARY KEY(feed,receipt_id),UNIQUE(feed,sequence))''')
            identity=c.execute('SELECT schema,source FROM mirror_identity').fetchall()
            if len(identity)!=1 or tuple(identity[0])!=(VERSION,str(source.path)):
                raise InputError('Mirror belongs to another source or schema; choose a new destination')

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=5);c.row_factory=sqlite3.Row
        try:
            yield c;c.commit()
        except Exception:
            c.rollback();raise
        finally:c.close()

    def _cursor(self, feed):
        with self.connect() as c:row=c.execute('SELECT cursor_json FROM feed_cursors WHERE feed=?',(feed,)).fetchone()
        return json.loads(row[0]) if row else None

    def _set_cursor(self,c,feed,cursor):
        c.execute('''INSERT INTO feed_cursors VALUES (?,?,?) ON CONFLICT(feed)
          DO UPDATE SET cursor_json=excluded.cursor_json,updated_at=excluded.updated_at''',
          (feed,serialized(cursor),datetime.now(timezone.utc).isoformat()))

    def _commit(self,feed,page,expected):
        inserted=0
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute('SELECT cursor_json FROM feed_cursors WHERE feed=?',(feed,)).fetchone()
            if (json.loads(current[0]) if current else None)!=expected:
                raise InputError('Another consumer advanced this mirror cursor; retry the sync')
            for row in page['rows']:
                document=serialized(row['document']);sha=hashlib.sha256(document.encode('utf-8')).hexdigest()
                prior=c.execute('SELECT receipt_id,sequence,sha256 FROM receipts WHERE feed=? AND (receipt_id=? OR sequence=?)',
                                (feed,row['id'],row['sequence'])).fetchall()
                if prior:
                    if len(prior)!=1 or tuple(prior[0])!=(row['id'],row['sequence'],sha):
                        raise InputError('Receipt identity conflicts with saved mirror evidence; nothing in this page was committed')
                    continue
                c.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?)',(feed,row['id'],row['sequence'],row['recorded_at'],document,sha))
                inserted+=1
            self._set_cursor(c,feed,page['next_cursor'])
        return inserted

    def sync(self, *, feeds=None, limit=100, pages=1):
        feeds=list(self.source.catalog()['feeds'] if feeds is None else feeds)
        if not feeds or len(feeds)!=len(set(feeds)) or any(f not in FEEDS for f in feeds):raise InputError('Select distinct supported feeds')
        _integer(limit,'limit',high=10000);_integer(pages,'pages',high=100)
        result=[]
        for feed in feeds:
            inserted=received=0
            for _ in range(pages):
                previous=self._cursor(feed)
                page=self.source.changes(feed,cursor=previous,limit=limit)
                inserted+=self._commit(feed,page,previous);received+=len(page['rows'])
                if not page['has_more']:break
            result.append({'feed':feed,'received':received,'inserted':inserted,'has_more':page['has_more'],
                           'cursor':page['next_cursor']})
        return {'schema':VERSION,'destination':str(self.path),'feeds':result,
                'has_more':any(r['has_more'] for r in result),
                'note':'Each feed commits independently. Append history, not a current-state replica; no downstream side effects are executed.'}

    def status(self):
        with self.connect() as c:
            c.execute('BEGIN')
            counts=dict(c.execute('SELECT feed,count(*) FROM receipts GROUP BY feed'))
            rows=c.execute('SELECT * FROM feed_cursors ORDER BY feed').fetchall()
        return {'schema':VERSION,'source':str(self.source.path),'destination':str(self.path),
                'feeds':[{'feed':r['feed'],'receipts':counts.get(r['feed'],0),'cursor':json.loads(r['cursor_json']),
                          'updated_at':r['updated_at']} for r in rows]}
