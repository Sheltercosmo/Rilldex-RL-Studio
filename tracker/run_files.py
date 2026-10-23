"""Reference large outputs without moving their bytes through the tracking DB.

Only the calling Python client opens references. The web server returns metadata
and embedded snapshots, never arbitrary local paths or remote URLs.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import urlopen, url2pathname

from .schema import InputError

CHUNK = 1024 * 1024
SCHEMES = {'file','http','https','s3','gs','gcs','az','abfs','hf'}


def local_path(uri):
    parsed=urlsplit(uri)
    if parsed.scheme!='file' or parsed.query or parsed.fragment:raise InputError('Use an absolute file URI')
    path=url2pathname(parsed.path)
    if parsed.netloc and parsed.netloc!='localhost':path='//'+parsed.netloc+path
    return Path(path)


def validate_name(name):
    if (not isinstance(name,str) or not name or len(name)>500 or '\\' in name or ':' in name
        or any(ord(ch)<32 for ch in name) or name.startswith('/')
        or any(part in ('','.','..') for part in name.split('/'))):
        raise InputError('Use a relative artifact name without empty, dot or parent path components')


def validate_reference(payload):
    validate_name(payload.get('name'))
    ref=payload.get('reference')
    if not isinstance(ref,dict):raise InputError('reference must contain a storage URI')
    uri=ref.get('uri')
    if not isinstance(uri,str) or len(uri)>4096 or any(ord(c)<32 for c in uri):raise InputError('Invalid artifact URI')
    try:parsed=urlsplit(uri)
    except ValueError:raise InputError('Invalid artifact URI') from None
    if parsed.scheme not in SCHEMES or not parsed.path or parsed.username or parsed.password:
        raise InputError('Use a file, HTTP, S3, GCS, Azure or Hugging Face URI without embedded credentials')
    if parsed.scheme!='file' and not parsed.netloc:raise InputError('Artifact URI requires a storage host or bucket')
    if parsed.scheme=='file' and (not parsed.path.startswith('/') or parsed.query or parsed.fragment):raise InputError('Use an absolute file URI')
    for key in ('version','host'):
        if key in ref and (not isinstance(ref[key],str) or not ref[key] or len(ref[key])>500):raise InputError('Invalid artifact '+key)
    size=payload.get('size');sha=payload.get('sha256')
    if size is not None and (type(size) is not int or not 0<=size<2**63):raise InputError('Invalid artifact byte size')
    if sha is not None and (not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha)):raise InputError('Use a lowercase SHA-256 checksum')
    if payload.get('role','artifact') not in ('artifact','checkpoint','dataset','model','output'):raise InputError('Unknown artifact role')
    for key in ('collection','trainer_session','clock'):
        if key in payload and (not isinstance(payload[key],str) or not payload[key] or len(payload[key])>500):raise InputError('Invalid artifact '+key)
    if 'collection_size' in payload and (type(payload['collection_size']) is not int or not 1<=payload['collection_size']<=10000 or not payload.get('collection')):
        raise InputError('Invalid artifact collection size')
    if 'step' in payload and (type(payload['step']) is not int or not 0<=payload['step']<2**63 or not payload.get('clock')):
        raise InputError('Artifact steps need a nonnegative integer and named clock')
    if 'content_base64' in payload:raise InputError('Choose embedded file bytes or an external reference')


def local_metadata(path, *, checksum=True):
    path=Path(path).expanduser().resolve(strict=True)
    if not path.is_file():raise InputError('Artifact reference must be a file')
    # Some Windows Python runtimes expose different ctime semantics through
    # fstat and path.stat. Compare ctime only between reads of the same handle.
    def identity(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno());sha=hashlib.sha256();size=0
        if checksum:
            while block:=stream.read(CHUNK):
                size+=len(block)
                if size>before.st_size:raise InputError('Artifact changed while hashing; record a completed checkpoint')
                sha.update(block)
        after=os.fstat(stream.fileno())
        if identity(before)!=identity(after) or before.st_ctime_ns!=after.st_ctime_ns or identity(before)!=identity(path.stat()):
            raise InputError('Artifact changed while hashing; record a completed checkpoint')
    return dict(size=before.st_size,sha256=sha.hexdigest() if checksum else None,
                reference=dict(uri=path.as_uri(),host=platform.node()))


def reference_payload(source, *, name=None, checksum=True, size=None, sha256=None, version=None, role='artifact',
                      step=None, clock=None, trainer_session=None, collection=None):
    raw=os.fspath(source)
    if raw.startswith('file://'):raw=str(local_path(raw))
    # Windows drive paths must not be interpreted as URI schemes.
    remote=bool(re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://',raw))
    if remote:
        payload=dict(name=name or unquote(PurePosixPath(urlsplit(raw).path).name),size=size,sha256=sha256,reference=dict(uri=raw))
    else:
        payload=dict(name=name or Path(raw).name,**local_metadata(raw,checksum=checksum))
        if size is not None and size!=payload['size'] or sha256 is not None and sha256!=payload['sha256']:
            raise InputError('Supplied artifact identity differs from the local file')
    if version is not None:payload['reference']['version']=version
    payload['role']=role
    for key,value in dict(step=step,clock=clock,trainer_session=trainer_session,collection=collection).items():
        if value is not None:payload[key]=value
    validate_reference(payload);return payload


def file_record(store, *, experiment, sequence):
    if type(sequence) is not int or sequence<1:raise InputError('Choose a file record sequence')
    with store.connect() as c:
        row=c.execute("SELECT * FROM run_records WHERE experiment=? AND sequence=? AND kind='file'",(experiment,sequence)).fetchone()
    if row is None:raise InputError('File record not found in this run')
    return json.loads(row['document'])


def _open_reference(ref, storage_options):
    uri=ref['uri'];parsed=urlsplit(uri);version=ref.get('version')
    query=parse_qs(parsed.query)
    if parsed.scheme=='s3' and not version:version=query.get('versionId',[None])[0]
    if parsed.scheme in ('gs','gcs') and not version:
        candidate=parsed.fragment or query.get('generation',[None])[0]
        if candidate and candidate.isdigit():version=candidate
    if version and parsed.scheme not in ('s3','gs','gcs'):
        raise InputError('Use a versioned URI or a custom opener for this storage provider')
    if parsed.scheme=='file':
        return local_path(uri).open('rb')
    if parsed.scheme in ('http','https'):
        return urlopen(uri,timeout=30)
    try:
        import fsspec
    except ImportError:raise InputError('Install the storage driver in this Python environment, such as rilldex[s3] or rilldex[gcs]') from None
    options=dict(storage_options or {});open_options={}
    if version:
        if parsed.scheme=='s3':options['version_aware']=True;open_options['version_id']=version
        elif parsed.scheme in ('gs','gcs'):options['version_aware']=True;open_options['generation']=version
        else:raise InputError('Use a versioned URI or a custom opener for this storage provider')
    protocol='gcs' if parsed.scheme in ('gs','gcs') else parsed.scheme
    try:
        fs=fsspec.filesystem(protocol,**options)
        return fs.open(uri,'rb',block_size=CHUNK,cache_type='none',**open_options)
    except ImportError:raise InputError('Install the '+protocol+' storage driver in this Python environment') from None


def retrieve(store, *, experiment, sequence, destination, storage_options=None, opener=None):
    """Stream one file on the caller's host; validate recorded size/hash, publish once.

    opener(reference) may return a binary stream for custom storage/auth. No
    credentials are stored. Object versions are selected by the native driver.
    """
    record=file_record(store,experiment=experiment,sequence=sequence);payload=record['payload']
    target=Path(destination).expanduser().absolute()
    if target.exists():raise InputError('Destination exists; choose a new file path')
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.rilldex-download-',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as output:
            if 'reference' in payload:
                ref=dict(payload['reference']);source=opener(ref) if opener else _open_reference(ref,storage_options)
            else:source=io.BytesIO(base64.b64decode(payload['content_base64']))
            size=0;sha=hashlib.sha256()
            with source:
                length=getattr(source,'headers',{}).get('Content-Length')
                expected_transport=int(length) if length is not None and str(length).isdigit() else None
                while block:=source.read(CHUNK):
                    size+=len(block)
                    if payload.get('size') is not None and size>payload['size']:raise InputError('Artifact size changed; destination was not published')
                    output.write(block);sha.update(block)
            if expected_transport is not None and size!=expected_transport:raise InputError('Artifact transfer ended early; destination was not published')
            if payload.get('size') is not None and size!=payload['size']:raise InputError('Artifact size differs; destination was not published')
            if payload.get('sha256') is not None and sha.hexdigest()!=payload['sha256']:raise InputError('Artifact checksum differs; destination was not published')
        try:os.link(temporary,target)
        except FileExistsError:raise InputError('Destination exists; choose a new file path') from None
        except OSError:raise InputError('Destination filesystem must support atomic hard-link publication') from None
        return dict(path=str(target),bytes=size,sha256=sha.hexdigest(),
                    verification='sha256' if payload.get('sha256') else 'size_only' if payload.get('size') is not None else 'unverified')
    finally:Path(temporary).unlink(missing_ok=True)
