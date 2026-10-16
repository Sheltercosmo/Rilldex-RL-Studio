"""Portable, indexed SQL datasets from one live read snapshot.

Physical rl_* tables require no Jev runtime or database extensions to query.
SQLite's dynamic value types are preserved without inferring from the first row.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from .analytics import VIEWS, GRAINS, OBSERVER_TABLES, _integer
from .schema import InputError, dumps, digest

VERSION = 'research-snapshot/1'


def materialize(source, destination, *, experiment=None, observer=None, history=False,
                include_sources=False, max_rows=1_000_000, max_bytes=1024**3):
    _integer(max_rows, 'max_rows', high=100_000_000)
    _integer(max_bytes, 'max_bytes', high=100*1024**3)
    if type(include_sources) is not bool: raise InputError('include_sources must be boolean')
    target = Path(destination).expanduser().resolve()
    if target.exists(): raise InputError('Dataset destination exists; choose a new database file')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.jev-dataset-', dir=target.parent) as temp:
        staging = Path(temp)/'data.sqlite'
        connection = sqlite3.connect(staging)
        try:
            size = 0
            with source.snapshot() as saved, connection:
                if saved.frozen and include_sources and not saved.manifest['tables']['sources']['included']:
                    raise InputError('Source documents were omitted from the parent dataset; export from the original workspace')
                manifest = dict(schema=VERSION, captured_at=saved.captured_at,
                    scope=dict(experiment=experiment, observer=observer, history=history),
                    tables={}, include_sources=include_sources,
                    note='Frozen saved data, not a live replica or restorable workspace. Empty omitted source table is not evidence of absent traces.')
                if saved.frozen: manifest['parent_dataset'] = saved.manifest
                # A bounded read transaction; never hold it during user analysis.
                deadline = time.monotonic()+120
                saved.c.set_progress_handler(lambda: int(time.monotonic()>deadline), 1000)
                for name in VIEWS:
                    sql, parameters = saved._selection(name, experiment=experiment, history=history,
                        observer=observer if name in OBSERVER_TABLES else None)
                    if name == 'sources' and not include_sources: sql += ' AND 0' if ' WHERE ' in sql else ' WHERE 0'
                    cursor = saved.c.execute(sql, parameters)
                    columns = [c[0] for c in cursor.description]
                    # No affinity: heterogeneous JSON scalar values retain their SQLite type.
                    connection.execute('CREATE TABLE rl_'+name+' ('+','.join('"'+c+'"' for c in columns)+')')
                    insert = 'INSERT INTO rl_'+name+' VALUES ('+','.join('?' for _ in columns)+')'
                    count = 0; sha = hashlib.sha256()
                    while batch := cursor.fetchmany(1000):
                        count += len(batch)
                        if count > max_rows: raise InputError(f'{name} exceeds max_rows; narrow the dataset scope')
                        for row in batch:
                            encoded = (dumps(dict(row))+'\n').encode('utf-8')
                            sha.update(encoded); size += len(encoded)
                        if size > max_bytes: raise InputError('Dataset exceeds max_bytes; narrow its scope')
                        connection.executemany(insert, (tuple(r) for r in batch))
                    for fields in [('run_id',), ('graph_id','node_id'), ('graph_id','source','type'),
                                   ('graph_id','target','type'), ('observer','metric'), ('experiment',)]:
                        if all(f in columns for f in fields):
                            connection.execute(f'CREATE INDEX idx_{name}_{"_".join(fields)} ON rl_{name} ({",".join(fields)})')
                    manifest['tables'][name] = dict(rows=count, columns=columns, grain=GRAINS[name],
                        sha256=sha.hexdigest(), included=saved.available(name) and (name != 'sources' or include_sources),
                        source_coverage=saved.source_coverage.get(name))
                manifest['id'] = 'dataset-'+digest(manifest)
                connection.execute('CREATE TABLE research_snapshot (schema TEXT NOT NULL, document_json TEXT NOT NULL)')
                connection.execute('INSERT INTO research_snapshot VALUES (?,?)', (VERSION, dumps(manifest)))
            if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok': raise InputError('Dataset integrity check failed')
        except sqlite3.Error as exc:
            raise InputError(f'Dataset export failed: {exc}') from exc
        finally: connection.close()
        os.link(staging, target)  # publish complete file without replacing another writer
    return {**manifest, 'path': str(target)}
