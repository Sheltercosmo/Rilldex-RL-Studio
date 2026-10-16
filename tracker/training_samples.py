"""Independent sample identities and producer-declared episode mappings.

Version 1 remains readable unchanged. A mapping establishes provenance, not
token/loss alignment or attribution of whole-episode behavior to one sample.
"""
from .schema import InputError

VERSION = 'training-records/2'
TABLE = 'training_sample_records'


def initialize(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS training_sample_records (
      producer TEXT NOT NULL, experiment TEXT NOT NULL, record_id TEXT NOT NULL,
      revision INTEGER NOT NULL, kind TEXT NOT NULL, sample_producer TEXT NOT NULL,
      sample_id TEXT NOT NULL, document TEXT NOT NULL, received_at TEXT NOT NULL,
      PRIMARY KEY(producer,experiment,record_id,revision));
    CREATE INDEX IF NOT EXISTS independent_sample_join
      ON training_sample_records(experiment,sample_producer,sample_id);
    CREATE INDEX IF NOT EXISTS independent_source_declaration ON training_sample_records(
      json_extract(document,'$.data.source.producer'),
      json_extract(document,'$.data.source.rollout_id'),
      json_extract(document,'$.data.source.revision'),experiment) WHERE kind='sample';
    ''')


def identity(row):
    if row.get('sample_identity_schema') == VERSION:
        return {k:row[k] for k in ('experiment','producer','sample_id','sample_identity_schema')}
    return {k:row[k] for k in ('experiment','producer','rollout_id')}


def reference(row):
    if row.get('sample_identity_schema') == VERSION:
        return {'producer':row['producer'],'id':row['sample_id']}
    return {'producer':row['producer'],'rollout_id':row['rollout_id']}


def validate_mapping(data, text, integer):
    if 'episode' in data:
        episode=data['episode']
        if not isinstance(episode,dict) or set(episode)!={'producer','id'}:raise InputError('Episode reference requires producer and id')
        for key,value in episode.items():text(value,'episode '+key)
    if 'interaction_ids' in data:
        ids=data['interaction_ids']
        if not isinstance(ids,list) or not 1<=len(ids)<=1000:
            raise InputError('interaction_ids must be a bounded list of native model-call identities')
        for identifier in ids:text(identifier,'interaction identity')
        if len(set(ids))!=len(ids):raise InputError('Duplicate model interaction identity')
    if 'source' not in data:return
    source=data['source']
    if (not isinstance(source,dict) or not {'producer','rollout_id','revision'}<=set(source)
            or set(source)-{'producer','rollout_id','revision','spans'}):
        raise InputError('Sample source needs producer, rollout_id, revision and optional exact spans')
    text(source['producer'],'source producer');text(source['rollout_id'],'source rollout_id');integer(source['revision'],'source revision')
    if 'spans' in source:
        spans=source['spans']
        if not isinstance(spans,list) or not 1<=len(spans)<=1000:
            raise InputError('Sample source spans must be a nonempty bounded list')
        occupied={}
        for s in spans:
            if not isinstance(s,dict) or set(s)!={'event_id','source_pointer','start','end','text'}:
                raise InputError('Source span requires exact event, pointer, codepoint bounds and text')
            text(s['event_id'],'event_id');text(s['source_pointer'],'source_pointer')
            if not isinstance(s['text'],str) or not s['text'].strip():raise InputError('Source span text must be nonempty')
            integer(s['start'],'span start');integer(s['end'],'span end')
            if s['start']>=s['end'] or s['end']-s['start']!=len(s['text']):raise InputError('Source span bounds differ from its text')
            for start,end in occupied.setdefault(s['event_id'],[]):
                if start<s['end'] and end>s['start']:raise InputError('Sample source spans overlap')
            occupied[s['event_id']].append((s['start'],s['end']))


def binding_status(run, mapping):
    """Delivered-source check; an invalid mapping never falls back to latest."""
    if 'spans' not in mapping:return 'episode_reference'
    events={e['id']:e for e in run['events']}
    for s in mapping['spans']:
        e=events.get(s['event_id'])
        if (not e or e['source_pointer']!=s['source_pointer'] or s['end']>len(e['text'])
                or e['text'][s['start']:s['end']]!=s['text'] or e.get('copied_context')
                or e.get('agent_visibility')=='not_established' or e['kind'].startswith('external_')):
            return 'invalid_source_spans'
    return 'exact_source_spans'
