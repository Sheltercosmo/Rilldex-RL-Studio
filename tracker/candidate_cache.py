"""Reuse exact source-bound proposals; normal stage validation still applies."""
from pathlib import Path

from .schema import InputError, digest

VERSION = 'exact-candidate-reuse/1'


def reuse(directory, request, sources, *, queue='candidates'):
    from .semantic_extraction import read, write
    if queue not in {'candidates','work_candidates'}:raise InputError('Unknown candidate cache queue')
    root = Path(directory); key = digest(request)
    destination = root / 'responses' / (key + '.json')
    if destination.exists(): return False
    matches = []
    for source in sources:
        path = Path(source) / queue
        response_path = path / 'responses' / (key + '.json')
        request_path = path / 'requests' / (key + '.json')
        if not response_path.exists() or not request_path.exists(): continue
        saved_request, response = read(request_path), read(response_path)
        if saved_request != request or response.get('request_hash') != key or not response.get('producer'):
            raise InputError('Reusable candidate source binding differs')
        matches.append((response_path, response))
    if not matches: return False
    if any(response != matches[0][1] for _, response in matches[1:]):
        raise InputError('Exact candidate cache sources contain conflicting proposals')
    path, response = matches[0]
    write(root / 'reuse' / (key + '.json'), {
        'schema': VERSION, 'request_hash': key, 'response_hash': digest(response),
        'source_path': str(path.resolve()), 'compatible_sources': len(matches),
        'new_candidate_calls': 0,
        'boundary': 'Exact request and unchanged proposal; stage validation and Jev selection remain required.'})
    write(destination, response)
    return True
