"""Read-only object storage mirror feeding the ordinary durable collectors."""
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from urllib.parse import urlsplit

from .schema import InputError, digest

BACKENDS = {'s3': ('s3', 's3fs'), 'gs': ('gcs', 'gcsfs'), 'gcs': ('gcs', 'gcsfs')}
MAX_OBJECT_BYTES = 1024 ** 3


def source(url):
    parsed = urlsplit(url)
    if parsed.scheme not in BACKENDS or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise InputError('Use s3://bucket/prefix or gs://bucket/prefix; configure credentials on the collector, not in the URL')
    if any(p in {'.', '..'} for p in parsed.path.split('/')) or '\\' in url or ':' in parsed.netloc:
        raise InputError('Cloud source must identify a bucket and an ordinary key prefix')
    return parsed.scheme, parsed.netloc + parsed.path.rstrip('/')


def filesystem(url):
    protocol, _ = source(url)
    name, package = BACKENDS[protocol]
    try:
        import fsspec
        return fsspec.filesystem(name, skip_instance_cache=True)
    except ImportError:
        raise InputError(f'Install cloud support in the collector environment: python -m pip install {package}') from None
    except Exception as error:
        # Constructor/config errors can contain credentials or signed endpoints.
        raise InputError(f'Cloud client setup failed ({type(error).__name__}). Check the storage client configuration on the collector host; accepted local data is retained.') from None


def signature(info):
    # Size alone cannot identify a replacement with the same byte length.
    identity = {k: str(info[k]) for k in ('ETag', 'etag', 'version_id', 'VersionId', 'generation', 'mtime', 'LastModified', 'updated') if info.get(k) is not None}
    return digest({**identity, 'size': info.get('size')}) if identity else None


class CloudWatcher:
    def __init__(self, watcher, url):
        self.local, self.url = watcher, url
        _, self.prefix = source(url)
        self.fs = None

    def __getattr__(self, key):
        return getattr(self.local, key)

    def mirror(self, stop=None, *, limit=100, byte_budget=None):
        fs = self.fs or filesystem(self.url)
        self.fs = fs
        state_path = self.root / '.jev-mirror-state'
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            state = {}
        errors, copied, unchanged, pending = [], 0, 0, 0
        try:
            fs.invalidate_cache(self.prefix)
            files = fs.find(self.prefix, detail=True)
        except Exception as e:
            # Backend errors can contain signed URLs; do not save credential-bearing text.
            raise InputError(f'Cloud listing failed ({type(e).__name__}). Check collector credentials, bucket permissions and connectivity; accepted local data is retained.') from None
        if len(files) > self.max_files:
            raise InputError('Cloud prefix exceeds the file limit; select a narrower job prefix')
        names = [k.casefold() for k in files]
        if len(names) != len(set(names)):
            raise InputError('Cloud keys differ only by case; use portable unique filenames for Windows-compatible replay')
        ordered = sorted(files.items())
        cursor = state.get('_jev_scan_after', '')
        ordered = [r for r in ordered if r[0] > cursor] + [r for r in ordered if r[0] <= cursor]
        for key, info in ordered:
            if stop and stop.is_set():
                break
            if info.get('type') == 'directory':
                continue
            relative = key[len(self.prefix) + 1:] if key.startswith(self.prefix + '/') else ''
            parts = PurePosixPath(relative).parts
            if not relative or PurePosixPath(relative).as_posix() != relative or any(p in {'.', '..'} or p.endswith(('.', ' ')) for p in parts) or '\\' in relative or ':' in relative:
                errors.append(dict(path='cloud object', status='deferred', error='Object is outside the selected prefix or has a nonportable path'))
                continue
            if hasattr(self.local, 'source_suffixes') and not relative.endswith(self.local.source_suffixes):
                continue
            if hasattr(self.local, 'pattern') and not fnmatch.fnmatchcase(parts[-1], self.local.pattern):
                continue
            if not hasattr(self.local, 'pattern') and not hasattr(self.local, 'source_suffixes') and not relative.endswith(('.json', '.traj')):
                continue
            path = self.root.joinpath(*parts)
            if not path.resolve().is_relative_to(self.root.resolve()):
                errors.append(dict(path=relative, status='deferred', error='Cache path escapes the source directory'))
                continue
            stamp = signature(info)
            old = state.get(relative, {})
            local_stat = [path.stat().st_size, path.stat().st_mtime_ns] if path.is_file() else None
            if stamp and old.get('remote') == stamp and old.get('local') == local_stat:
                unchanged += 1
                continue
            if copied + len(errors) >= limit:
                pending += 1
                continue
            state['_jev_scan_after'] = key
            temporary = None
            try:
                if info.get('size', 0) > MAX_OBJECT_BYTES:
                    raise InputError('Object exceeds 1 GiB; export bounded shards')
                if byte_budget is not None and info.get('size', 0) > byte_budget:
                    raise InputError('Object exceeds the remaining preview download budget; connect to collect it')
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix='.jev-download-', dir=path.parent)
                sha, size = hashlib.sha256(), 0
                with os.fdopen(fd, 'wb') as target, fs.open(key, 'rb') as remote:
                    while True:
                        if stop and stop.is_set():
                            raise InputError('Download interrupted; retry on resume')
                        block = remote.read(1024 * 1024)
                        if not block:
                            break
                        size += len(block)
                        if byte_budget is not None:
                            byte_budget -= len(block)
                            if byte_budget < 0:
                                raise InputError('Preview download budget exhausted')
                        if size > MAX_OBJECT_BYTES:
                            raise InputError('Object exceeds 1 GiB; export bounded shards')
                        sha.update(block)
                        target.write(block)
                    target.flush()
                    os.fsync(target.fileno())
                fs.invalidate_cache(key)
                after = fs.info(key)
                if stamp != signature(after) or (type(after.get('size')) is int and size != after['size']):
                    raise InputError('Object changed during download; retrying without replacing accepted cache')
                if old.get('sha256') != sha.hexdigest() or old.get('local') != local_stat:
                    os.replace(temporary, path)
                state[relative] = dict(remote=signature(after), sha256=sha.hexdigest(),
                                       local=[path.stat().st_size, path.stat().st_mtime_ns])
                copied += 1
            except Exception as e:
                message = str(e) if isinstance(e, InputError) else f'Cloud download failed ({type(e).__name__}); retrying, previous source retained'
                errors.append(dict(path=relative, status='deferred', error=message))
            finally:
                if temporary and Path(temporary).exists():
                    Path(temporary).unlink()
        fd, temp_state = tempfile.mkstemp(prefix='.jev-state-', dir=self.root)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(state, stream)
            os.replace(temp_state, state_path)
        finally:
            if Path(temp_state).exists():
                Path(temp_state).unlink()
        return dict(copied=copied, unchanged=unchanged, pending=pending, errors=errors)

    def poll(self, stop=None):
        try:
            remote = self.mirror(stop)
            remote['state'] = 'partial' if remote['errors'] else 'catching_up' if remote['pending'] else 'current'
        except InputError as error:
            # Cloud availability must not gate already-downloaded historical
            # records. Keep the failed sync explicit; --once must still fail.
            remote = dict(copied=0, unchanged=0, pending=0, state='cached_only',
                          errors=[dict(path='cloud source', status='deferred', error=str(error))])
        result = self.local.poll(stop)
        result['entries'].extend(remote['errors'])
        result['deferred'] += len(remote['errors'])
        result['backlog'] = result.get('backlog', 0) + remote['pending']
        result['cloud'] = {k: v for k, v in remote.items() if k != 'errors'}
        return result

    def run(self, interval=2.0, once=False):
        from .watch import DirectoryWatcher
        return DirectoryWatcher.run(self, interval, once)
