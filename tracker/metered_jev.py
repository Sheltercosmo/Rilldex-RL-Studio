"""Durable, cumulative Jev HTTP budgets without an implicit retry loop."""
from collections import Counter
from pathlib import Path
import json
import os
import time
from .schema import InputError,digest,dumps
from .semantic_extraction import read,write


class BudgetExhausted(InputError):pass
class UnknownAttempt(InputError):pass


class BoundedTransport:
    def __init__(self,root,maximum,send=None):
        if type(maximum) is not int or maximum<0:raise InputError('HTTP-attempt budget must be a nonnegative integer')
        self.root=Path(root);self.maximum=maximum;self.send=send or self._send
        self.calls=0;self.usage=Counter()
    @staticmethod
    def _send(req):
        import urllib.request
        from .jev import ENDPOINT
        key=os.environ.get('JEV_API_KEY')
        if not key:raise InputError('Jev key required in process memory')
        request=urllib.request.Request(ENDPOINT,data=dumps(req).encode(),
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=90) as response:return json.load(response)
    def __call__(self,req):
        key=digest(req);wire=self.root/'wire'/f'{key}.json'
        if wire.exists():
            saved=read(wire)
            if saved['request']!=req:raise InputError('Wire request differs')
            return saved['response']
        prior=list((self.root/'attempts').glob('*.json'))
        if len(prior)>=self.maximum:raise BudgetExhausted('Aggregate HTTP-attempt budget exhausted; cache retained')
        if any(read(p)['status'] in {'pending','outcome_unknown'} for p in prior):
            raise UnknownAttempt('An earlier HTTP attempt has unknown outcome; inspect before resuming')
        attempt=self.root/'attempts'/f'{len(prior)+1:05d}.json';attempt.parent.mkdir(parents=True,exist_ok=True)
        record={'request_hash':key,'status':'pending','started_ns':time.time_ns()}
        with attempt.open('x',encoding='utf-8') as file:file.write(dumps(record))
        self.calls+=1
        try:
            response=self.send(req);self.usage.update(response.get('usage') or {})
            write(wire,{'request':req,'response':response})
            record.update(status='response_received',response_hash=digest(response),usage=response.get('usage'))
            return response
        except Exception as error:
            # Never persist exception bodies, headers, or credentials.
            record.update(status='outcome_unknown' if isinstance(error,(TimeoutError,ConnectionError)) else 'error',
                          error_type=type(error).__name__,usage=None)
            raise
        finally:write(attempt,record)
