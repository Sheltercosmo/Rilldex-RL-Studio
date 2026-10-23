"""Stable evidence pages; packet limits never truncate source citations."""
from .schema import dumps


def bounded_requests(candidates, make_request, *, count, max_bytes):
    def split(chunk):
        request=make_request(chunk)
        if len(dumps(request).encode('utf-8'))<=max_bytes:
            yield chunk,request
        elif len(chunk)==1:
            yield chunk,None
        else:
            middle=len(chunk)//2
            yield from split(chunk[:middle])
            yield from split(chunk[middle:])
    for offset in range(0,len(candidates),count):
        yield from split(candidates[offset:offset+count])
