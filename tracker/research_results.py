"""Source-independent access and recovery for researcher-owned result databases."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile

from .analytics import Snapshot
from .collector_lock import ProducerLock
from .schema import InputError, digest, dumps

VERSION = 'research-results/1'
ITEM_SQL = '''SELECT i.ordinal,i.input_key_json,i.input_hash,i.input_json,
  i.result_id,i.status,i.error,r.output_json,r.output_hash
  FROM research_batch_items i LEFT JOIN research_results r ON r.id=i.result_id
  WHERE i.batch_id=?'''


def now():
    return datetime.now(timezone.utc).isoformat()


class Results:
    """Read, export or resume saved batches without opening the source workspace.

Reads never run user code. resume() requires the original callback version and
uses only retained inputs/configuration; callbacks still run in your process.
"""
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file(): raise InputError('Research result database does not exist')
        with self._connect() as connection:
            self.source = self._identity(connection)

    @staticmethod
    def _identity(connection):
        try: identity = connection.execute('SELECT schema,source FROM research_identity').fetchall()
        except sqlite3.Error as exc: raise InputError('Destination is not a research result database') from exc
        if len(identity) != 1 or identity[0]['schema'] != VERSION:
            raise InputError('Unsupported research result schema')
        return identity[0]['source']

    @contextmanager
    def _connect(self, *, write=False):
        connection = sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            if not write:
                connection.execute('PRAGMA query_only=ON')
                connection.execute('BEGIN')
            with connection: yield connection
        finally: connection.close()

    @contextmanager
    def _exclusive(self):
        lock = ProducerLock(self, 'custom-analysis')
        if not lock.acquire(): raise InputError('Another custom analysis owns this result database; retry after it stops')
        try: yield
        finally: lock.close()

    def query(self, sql, parameters=(), *, limit=1000):
        """Bounded read-only SQL against research_* tables; no source dependency."""
        with self._connect() as connection:
            return Snapshot(connection).query(sql, parameters, limit=limit)

    @staticmethod
    def _batch(connection, batch_id):
        row = connection.execute('''SELECT b.*,d.definition_json FROM research_batches b
          JOIN research_definitions d ON d.id=b.definition_id WHERE b.id=?''', (batch_id,)).fetchone()
        if not row: raise InputError('Unknown research batch')
        batch = dict(row)
        try:
            definition = json.loads(batch.pop('definition_json'))
            valid = (definition['schema'] == VERSION and isinstance(definition['config'],dict)
                     and isinstance(definition['key_columns'],list) and bool(definition['key_columns'])
                     and batch['definition_id'] == 'research-definition-'+digest(definition))
        except (KeyError, TypeError, ValueError): valid = False
        if not valid: raise InputError('Saved research definition is invalid or its hash differs')
        batch['definition'] = definition
        counts = dict(connection.execute('''SELECT status,count(*) FROM research_batch_items
          WHERE batch_id=? GROUP BY status''', (batch_id,)).fetchall())
        batch['counts'] = {state:counts.get(state,0) for state in ('pending','computed','reused','failed')}
        batch['selected'] = sum(counts.values())
        return batch

    def batch(self, batch_id):
        """Definition, capture/completion times and current item counts."""
        with self._connect() as connection:
            return dict(self._batch(connection,batch_id), source=self.source)

    def batches(self, *, limit=1000, before=None):
        """Newest first, with a stable insertion cursor for paging older batches."""
        if before is not None and (type(before) is not int or before<1):
            raise InputError('before must be a positive batch sequence')
        with self._connect() as connection:
            page = Snapshot(connection).query('''SELECT b.rowid sequence,b.id,b.definition_id,
              d.name,d.version,b.captured_at,b.status,b.created_at,b.finished_at,
              (SELECT count(*) FROM research_batch_items i WHERE i.batch_id=b.id) selected,
              (SELECT count(*) FROM research_batch_items i WHERE i.batch_id=b.id AND i.status='pending') pending,
              (SELECT count(*) FROM research_batch_items i WHERE i.batch_id=b.id AND i.status='failed') failed
              FROM research_batches b JOIN research_definitions d ON d.id=b.definition_id
              WHERE (? IS NULL OR b.rowid<?) ORDER BY b.rowid DESC''', (before,before), limit=limit)
        page['next_before'] = page['rows'][-1]['sequence'] if page['truncated'] else None
        return page

    def results(self, batch_id, *, limit=1000, after=-1):
        """Page retained membership, including pending/failed rows and null outputs."""
        if type(after) is not int or after < -1: raise InputError('after must be an ordinal >= -1')
        with self._connect() as connection:
            batch = self._batch(connection,batch_id)
            page = Snapshot(connection).query(ITEM_SQL+' AND i.ordinal>? ORDER BY i.ordinal',
                                               (batch_id,after), limit=limit)
        page.update(batch_id=batch_id,batch_status=batch['status'],selected=batch['selected'],
                    next_after=page['rows'][-1]['ordinal'] if page['truncated'] else None)
        return page

    @staticmethod
    def _inputs(connection, batch):
        inputs = []; keys = set()
        for row in connection.execute('SELECT * FROM research_batch_items WHERE batch_id=? ORDER BY ordinal', (batch['id'],)):
            try:
                value = json.loads(row['input_json'])
                key = [value[k] for k in batch['definition']['key_columns']]
                valid = (row['ordinal']==len(inputs) and digest(value)==row['input_hash']
                         and dumps(key)==row['input_key_json'] and None not in key
                         and row['input_key_json'] not in keys
                         and row['status'] in ('pending','computed','reused','failed'))
                expected = 'research-result-'+digest([batch['definition_id'],row['input_hash']])
                valid = valid and (row['result_id']==expected if row['status'] in ('computed','reused') else row['result_id'] is None)
            except (KeyError,TypeError,ValueError): valid = False
            if not valid: raise InputError('Saved batch input identity, content or result link differs')
            keys.add(row['input_key_json']); inputs.append(dict(row))
        return inputs

    @staticmethod
    def _cached(connection, definition_id, item):
        result_id = 'research-result-'+digest([definition_id,item['input_hash']])
        cached = connection.execute('SELECT * FROM research_results WHERE id=?', (result_id,)).fetchone()
        if cached:
            try:
                output = json.loads(cached['output_json'])
                valid = (isinstance(output,dict) and digest(output)==cached['output_hash']
                         and cached['definition_id']==definition_id and cached['input_hash']==item['input_hash']
                         and cached['input_json']==item['input_json'] and cached['input_key_json']==item['input_key_json'])
            except (TypeError,ValueError): valid = False
            if not valid: raise InputError('Cached custom output hash or input identity differs')
        elif item['result_id'] is not None:
            raise InputError('Saved custom result is missing')
        return cached

    def resume(self, batch_id, function, *, version):
        """Finish exactly this batch. Never rerun its SQL or include newer data.

Supply the same callback implementation/version. Successful rows reuse cached
outputs; failed/pending rows retry and their latest error state is replaced.
"""
        if not callable(function): raise InputError('Supply a Python callback')
        with self._exclusive():
            with self._connect() as connection:
                batch = self._batch(connection,batch_id)
                if version != batch['definition']['version']:
                    raise InputError('Resume requires the saved callback version; use evaluate with a new version for changed logic')
                inputs = self._inputs(connection,batch)
            return self._run_batch(batch,inputs,function)

    def _run_batch(self, batch, inputs, function):
        batch_id = batch['id']; definition_id = batch['definition_id']
        if batch['status']=='complete':
            with self._connect() as connection:
                for item in inputs:
                    if item['status'] not in ('computed','reused') or not self._cached(connection,definition_id,item):
                        raise InputError('Complete batch has unfinished or missing results')
            return self._summary(batch,computed=0,reused=len(inputs),failed=0,unchanged=True)
        with self._connect(write=True) as connection:
            connection.execute("UPDATE research_batches SET status='interrupted',finished_at=? WHERE status='running' AND id<>?", (now(),batch_id))
            connection.execute("UPDATE research_batches SET status='running',finished_at=NULL WHERE id=?", (batch_id,))
        computed = reused = failed = 0
        try:
            for item in inputs:
                with self._connect() as connection: cached = self._cached(connection,definition_id,item)
                result_id = 'research-result-'+digest([definition_id,item['input_hash']])
                if cached:
                    reused += 1
                    if item['result_id']==result_id: continue
                    status = 'reused'
                else:
                    try:
                        output = function(json.loads(item['input_json']), json.loads(dumps(batch['definition']['config'])))
                        if not isinstance(output,dict): raise InputError('Custom callback must return a JSON object')
                        output_json = dumps(output)
                        if len(output_json.encode('utf-8')) > 8*1024**2: raise InputError('One custom output exceeds 8 MiB')
                    except Exception as exc:
                        failed += 1
                        with self._connect(write=True) as connection:
                            connection.execute("UPDATE research_batch_items SET status='failed',error=? WHERE batch_id=? AND ordinal=?",
                                (f'{type(exc).__name__}: {exc}'[:4000],batch_id,item['ordinal']))
                        continue
                    with self._connect(write=True) as connection:
                        connection.execute('INSERT INTO research_results VALUES (?,?,?,?,?,?,?,?)',
                            (result_id,definition_id,item['input_hash'],item['input_key_json'],item['input_json'],output_json,digest(output),now()))
                        connection.execute("UPDATE research_batch_items SET result_id=?,status='computed',error=NULL WHERE batch_id=? AND ordinal=?",
                            (result_id,batch_id,item['ordinal']))
                    computed += 1
                    continue
                with self._connect(write=True) as connection:
                    connection.execute('UPDATE research_batch_items SET result_id=?,status=?,error=NULL WHERE batch_id=? AND ordinal=?',
                        (result_id,status,batch_id,item['ordinal']))
        except BaseException:
            with self._connect(write=True) as connection:
                connection.execute("UPDATE research_batches SET status='interrupted',finished_at=? WHERE id=?", (now(),batch_id))
            raise
        with self._connect(write=True) as connection:
            connection.execute('UPDATE research_batches SET status=?,finished_at=? WHERE id=?',
                               ('partial' if failed else 'complete',now(),batch_id))
        return self._summary(self.batch(batch_id),computed=computed,reused=reused,failed=failed,unchanged=False)

    def _summary(self, batch, **counts):
        return dict(schema=VERSION,id=batch['id'],definition_id=batch['definition_id'],status=batch['status'],
                    selected=batch['selected'],captured_at=batch['captured_at'],checked_at=now(),
                    destination=str(self.path),**counts)

    def export(self, batch_id, destination, *, max_bytes=100*1024**2):
        """Atomically export one consistent batch to ZIP: manifest + results.jsonl.

Failed/pending rows remain present. Source access and callback execution are not
required. A live batch exports its committed state at the captured read snapshot.
"""
        if type(max_bytes) is not int or not 0<max_bytes<=100*1024**3:
            raise InputError('max_bytes must be between 1 byte and 100 GiB')
        destination = Path(destination).expanduser().resolve()
        if destination.exists(): raise InputError('Export destination already exists')
        destination.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.jev-results-',dir=destination.parent) as temp:
            target = Path(temp)/'batch.zip'
            with self._connect() as connection, zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
                batch = self._batch(connection,batch_id)
                self._inputs(connection,batch)
                checksum = hashlib.sha256(); size = count = 0
                with archive.open('results.jsonl','w') as stream:
                    for row in connection.execute(ITEM_SQL+' ORDER BY i.ordinal',(batch_id,)):
                        self._cached(connection,batch['definition_id'],row)
                        record = dict(row)
                        for key in ('input_key','input','output'):
                            value = record.pop(key+'_json')
                            record[key] = json.loads(value) if value is not None else None
                        encoded = (dumps(record)+'\n').encode('utf-8'); size += len(encoded)
                        if size>max_bytes: raise InputError('Batch export exceeds max_bytes; raise the limit explicitly')
                        stream.write(encoded); checksum.update(encoded); count += 1
                manifest = dict(schema='research-batch-export/1',exported_at=now(),source=self.source,batch=batch,
                                files={'results.jsonl':dict(rows=count,bytes=size,sha256=checksum.hexdigest())})
                archive.writestr('manifest.json',dumps(manifest))
            try: os.link(target,destination)
            except FileExistsError as exc: raise InputError('Export destination already exists') from exc
        return manifest
