"""Project serialized diagnostic ranges back to readable recorded source fields.

No inference or rewriting: JSON escape decoding retains a character map to
the selected serialized character offsets. Nested JSON tool outputs are decoded
only when they are complete JSON objects/arrays, never evaluated as code.
"""
from bisect import bisect_left, bisect_right
import json

from .diagnostic_chains import _regions


def _string(text,start,end,bounds):
    pos=start+1;chars=[];edges=[bounds[pos]]
    while pos<end-1:
        stop=pos+1
        if text[pos]=='\\':
            stop=pos+(6 if text[pos+1]=='u' else 2)
            if text[pos+1]=='u' and 0xD800<=int(text[pos+2:stop],16)<=0xDBFF and text[stop:stop+2]=='\\u':
                if 0xDC00<=int(text[stop+2:stop+6],16)<=0xDFFF:stop+=6
            char=json.loads('"'+text[pos:stop]+'"')
        else:char=text[pos:stop]
        chars.append(char);edges.append(bounds[stop]);pos=stop
    return ''.join(chars),edges


def _leaves(text,bounds,path=(),depth=0,*,expand_nested=True):
    decoder=json.JSONDecoder()
    def skip(pos):
        while pos<len(text) and text[pos].isspace():pos+=1
        return pos
    def walk(pos,field):
        pos=skip(pos)
        if text[pos]=='{':
            pos=skip(pos+1)
            while text[pos]!='}':
                key,pos=decoder.raw_decode(text,pos);pos=skip(pos)
                pos=yield from walk(pos+1,(*field,key));pos=skip(pos)
                if text[pos]==',':pos=skip(pos+1)
            return pos+1
        if text[pos]=='[':
            pos=skip(pos+1);index=0
            while text[pos]!=']':
                pos=yield from walk(pos,(*field,index));index+=1;pos=skip(pos)
                if text[pos]==',':pos=skip(pos+1)
            return pos+1
        value,end=decoder.raw_decode(text,pos)
        if isinstance(value,str):
            decoded,edges=_string(text,pos,end,bounds)
            if decoded!=value:raise ValueError('JSON string offset mapping differs')
            nested=False
            if expand_nested and depth<4 and decoded.lstrip().startswith(('{','[')):
                try:nested=isinstance(json.loads(decoded),(dict,list))
                except ValueError:pass
            if nested:
                children=list(_leaves(decoded,edges,(*field,'$json'),depth+1))
                if children:yield from children
                else:yield field,value,edges
            else:yield field,value,edges
        return end
    yield from walk(0,path)


def project(source,refs,run,graph=None):
    events={e['id']:e for e in run['events']};result={};regions=None;cached={}
    for ref in refs:
        key=ref.get('id')
        if not key or key in result:continue
        text=source.get(ref.get('origin'));start=ref.get('start');end=ref.get('end')
        if not isinstance(text,str) or type(start)is not int or type(end)is not int or not 0<=start<end<=len(text):continue
        if text[start:end]!=ref.get('text'):continue
        pieces=[]
        if ref['origin']=='task':
            pieces.append(dict(field=['task'],text=text[start:end],start=start,end=end,event_id=None,node_ids=[]))
        else:
            if regions is None:regions=_regions(text)
            for a,b,meta in regions:
                if b<=start or a>=end:continue
                event=events.get(meta.get('event_id'))
                if not event:continue
                if a not in cached:
                    try:cached[a]=list(_leaves(text[a:b],list(range(a,b+1))))
                    except (ValueError,IndexError,KeyError):cached[a]=[]
                for field,value,edges in cached[a]:
                    if not field or field[0] not in {'text','arguments'}:continue
                    left=max(start,edges[0]);right=min(end,edges[-1])
                    if left>=right:continue
                    i=max(0,bisect_right(edges,left)-1);j=min(len(value),bisect_left(edges,right))
                    if not value[i:j].strip():continue
                    nodes=[]
                    if field==('text',):
                        for node in (graph or {}).get('nodes',[]):
                            span=node.get('properties',{}).get('source') or {}
                            if span.get('event_id')==event['id'] and type(span.get('start'))is int and type(span.get('end'))is int and span['start']<j and span['end']>i:nodes.append(node['id'])
                    if not nodes:nodes=['event:'+event['id']]
                    pieces.append(dict(field=list(field),text=value[i:j],start=i,end=j,event_id=event['id'],
                        actor=event['actor'],kind=event['kind'],node_ids=nodes,
                        serialized_start=edges[i],serialized_end=edges[j]))
        if pieces:result[key]=pieces
    return result
