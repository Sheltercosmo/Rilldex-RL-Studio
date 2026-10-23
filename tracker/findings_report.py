"""Readable, offline handoff of an exact investigation revision. No inference."""
from collections import Counter
from html import escape
import json
import math
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from . import failure_investigations, graph_store, investigation_followups
from .schema import InputError, digest

SCHEMAS = investigation_followups.SCHEMAS
ASSESSMENTS = {'supports':'Supports this hypothesis', 'contradicts':'Contradicts this hypothesis',
               'inconclusive':'Inconclusive', 'not_run':'Not run'}


def number(value, unit=None):
    if type(value) not in (int, float) or not math.isfinite(value): return 'Unavailable'
    return f'{value * 100:.1f}%' if unit == 'fraction' else f'{value:,.6g}'


def difference(value, unit):
    return number(value,unit).replace('%',' pp') if unit=='fraction' else number(value)


def details(label, value):
    return '<details><summary>'+escape(label)+'</summary><pre>'+escape(json.dumps(value, indent=2, ensure_ascii=False))+'</pre></details>'


def table(headings, rows):
    # Rows contain text, never user-provided HTML.
    return '<div class="table-wrap" tabindex="0" role="region" aria-label="Comparison table; scroll horizontally for more columns"><table><thead><tr>'+''.join('<th>'+escape(h)+'</th>' for h in headings)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def paragraph(value, cls=''):
    return '<p class="'+cls+'">'+escape(str(value))+'</p>'


def context(value):
    return ' · '.join(str(v) for k,v in value.items() if v is not None and k in
                     ('environment','split','training_clock','training_step_basis','step_basis','reward_definition','recipe')) or 'Recorded cohort'


def summary(doc):
    """Tables preserve the native population and denominator of each saved view."""
    snapshot=doc['snapshot'];metrics=[];cohorts=[];versions=[]
    if doc['schema']=='interval-investigation/1':
        by_id={r['id']:r for r in snapshot['source_rows']}
        for side,ids in snapshot['population'].items():
            rows=[by_id[i] for i in ids];finished=[r for r in rows if r['state'] in ('complete','imported_snapshot')]
            known=[r for r in finished if type(r.get('outcome',{}).get('verified_success')) is bool]
            cohorts.append([side.title(),len(rows),len(finished),f"{sum(r['outcome']['verified_success'] for r in known)} / {len(known)}",
                            len(finished)-len(known),len(rows)-len(finished)])
        for panel in snapshot['panels']:
            monitor=panel['monitor'];versions.append(dict(name=monitor['name'],definition=monitor,reliability=panel['reliability'],
                aggregation=panel['aggregation'],unit=panel['unit'],cohorts=[dict(id=c['id'],context=c['cohort']) for c in panel['cohorts']]))
            for index,cohort in enumerate(panel['cohorts'],1):
                a,b=cohort['baseline'],cohort['current']
                def value(v):
                    extra=f"; {v['numerator']} / {v['denominator']} opportunities" if v.get('denominator') is not None else ''
                    return f"{number(v['value'],panel['unit'])} · {v['measured']}/{v['total']} rollouts measured{extra}"
                metrics.append([monitor['name'],f"Cohort {index} · {context(cohort['cohort'])}",value(a),value(b),difference(cohort['delta'],panel['unit'])])
        scope=table(['Window','Rollouts','Completed snapshots','Reported successes / known completed','Completed with unknown outcome','Unfinished / capture failed'],cohorts)
        scope+=details('Exact window, clock and population scope',dict(scope=doc['scope'],excluded=snapshot['excluded'],boundary=snapshot['clock_boundary']))
        measures=table(['Measure','Recorded cohort','Baseline','Selected interval','Change'],metrics)
    elif doc['schema']=='case-investigation/1':
        from .case_comparisons import _groups
        from .case_outcomes import outcome
        by_id={r['id']:r for r in snapshot['source_rows']}
        for side, ids in snapshot['population'].items():
            rows=[by_id[i] for i in ids]
            finished=[r for r in rows if r['state'] in ('complete','imported_snapshot')]
            known=[r for r in finished if type(outcome(r).get('verified_success')) is bool]
            cohorts.append(['Reference' if side=='baseline' else 'Selected',doc['scope'][side].get('arm',doc['scope'][side].get('experiment','')),len(rows),
                f"{sum(outcome(r)['verified_success'] for r in known)} / {len(known)}",len(rows)-len(known)])
        scope=table(['Selection','Run','Rollouts','Reported successes / known completed','Unresolved outcomes'],cohorts)
        scope+=details('Frozen selection',dict(scope=doc['scope'],boundary=snapshot['clock_boundary']))
        if snapshot.get('trainer_selection'):
            native=snapshot['trainer_selection']
            scope+=details('Native update links and coverage',native)
        if snapshot.get('trial_selection'):
            scope+=details('Trial jobs and returned rollout selection',snapshot['trial_selection'])
        reports=[dict(run_id=r['id'], **r['outcome_evaluation']) for r in snapshot['source_rows'] if r.get('outcome_evaluation')]
        if reports: scope+=details('Selected evaluator reports',reports)
        groups=_groups(doc)
        measures=table(['Task','Reference trials','Selected trials','Reported outcome comparison','Missing context'],
            [[g['context'].get('task_id') or 'Task not recorded',len(g['baseline']),len(g['current']),g['status'].replace('_',' '),
              ', '.join(g['missing_context']) or 'None'] for g in groups])
        versions=snapshot['case_evidence']
        if snapshot.get('behavior'):
            behavior=snapshot['behavior'];rows=[]
            for p in behavior['panels']:
                for label,values in [('All selected rollouts',p),('Same tasks · equal weight',p['same_tasks'])]:
                    def measured(side):
                        if label.startswith('Same'):
                            return f"{number(values[side],p['unit'])} · {values['measured_contexts']}/{values['contexts']} shared tasks measured"
                        v=values[side]
                        text=f"{number(v['value'],p['unit'])} · {v['measured']}/{v['total']} rollouts measured"
                        if v['denominator'] is not None:text+=f"; {v['numerator']}/{v['denominator']} resolved opportunities"
                        if v['unknown_opportunities']:text+=f"; {v['unknown_opportunities']} unresolved opportunities"
                        return text
                    rows.append([p['monitor']['name'],label,measured('baseline'),measured('current'),difference(values['delta'],p['unit'])])
            measures+=table(['Measure','Population','Reference','Selected','Change'],rows)
            measures+=details('Behavior measurement coverage and receipts',behavior)
    elif doc['schema']=='failure-investigation/1':
        for side in ('focus','reference'):
            rows=[r for r in snapshot['rows'] if r.get(side)];known=[r for r in rows if type(r.get('success')) is bool]
            cohorts.append([side.title(),len(rows),sum(r['complete'] for r in rows),f"{sum(r['success'] for r in known)} / {len(known)}",len(rows)-len(known)])
        scope=table(['Cohort','Rollouts','Complete','Reported successes / known','Unknown outcomes'],cohorts)+details('Selection and population',dict(controls=snapshot['controls'],population=snapshot['population']))
        for metric in snapshot['metrics']:
            a,b=metric['reference'],metric['focus']
            def value(v):return f"{number(v['mean'],metric['unit'])} · {v['n']}/{v['total']} measured"
            metrics.append([metric['label'],metric['group'],value(a),value(b),difference(metric['difference'],metric['unit'])])
        measures=table(['Measure','Group','Reference','Focus','Change'],metrics)
        versions=snapshot['protocols']
    else:
        selected=doc['selected_samples'];bound={r['run_id'] for r in selected if r.get('run_id')}
        scope=paragraph(f"{len(selected)} selected training samples · {len(bound)} distinct joined rollouts · {sum(not r.get('run_id') for r in selected)} samples without source joins")
        scope+=details('Selected population and scope',dict(scope=doc['scope'],view=doc['view'],selected_samples=selected))
        for cohort in snapshot['cohorts']:
            for stage,count in cohort['counts'].items():
                measured=cohort.get('comparison',{}).get(stage,{})
                available=cohort.get('availability',{}).get(stage,count>0)
                cohorts.append([context(cohort['cohort']),stage.replace('_',' '),count if available else 'No records',measured.get('measured','Unavailable') if available else 'Unavailable',number(measured.get('mean_per_rollout')) if available else 'Unavailable'])
        measures=table(['Recorded cohort','Population stage','Declared samples','Measured rollouts','Mean per measured rollout'],cohorts)
        measures+=paragraph('Stage counts are recorded sample memberships. Missing records do not establish exclusion; measured rollouts are a separate count.','meta')
        versions=dict(monitor=snapshot.get('monitor'),selection=snapshot.get('selection'),schema=snapshot['schema'])
        comparison=doc.get('measure_comparison')
        if comparison:
            rows=[]
            for metric in comparison['metrics']:
                def measured(v):return f"{number(v['mean_per_rollout'],metric['unit'])} · {v['measured']}/{v['population']} measured"
                rows.append([metric['monitor']['name'],measured(metric['reference']),measured(metric['focus']),difference(metric['difference'],metric['unit'])])
            measures+='<h3>Selected behavior comparison · mean per rollout</h3>'+table(['Measure','Reference','Focus','Change'],rows)
            measures+=details('Weights, opportunities and retained measurements',comparison)
        if doc.get('reward_comparison'):
            reward=doc['reward_comparison']
            measures+='<h3>Selected reward patterns</h3>'+table(['Recorded pattern','Samples'],[[r['label'],r['samples']] for r in reward['pattern_options']])
            measures+=details('Reward definitions, paired scores and group context',reward)
    for key,label in [('learning_context','Scores, selection and training use'),('native_telemetry','Linked trainer records'),('declared_populations','Declared jobs and pending population')]:
        if snapshot.get(key):measures+=details(label,snapshot[key])
    return dict(scope=scope,measures=measures,versions=versions)


def referenced_ids(value):
    """Only explicit stored node references; never infer neighboring evidence."""
    result=set()
    if isinstance(value,dict):
        for key,item in value.items():
            if (key in {'unit_id','action_id','event_id'} or key.endswith(('_unit_id','_action_id','_event_id'))) and isinstance(item,str):result.add(item)
            elif (key in {'unit_ids','action_ids','event_ids'} or key.endswith(('_unit_ids','_action_ids','_event_ids'))) and isinstance(item,list):result.update(v for v in item if isinstance(v,str))
            elif isinstance(item,(dict,list)):result.update(referenced_ids(item))
    elif isinstance(value,list):
        for item in value:result.update(referenced_ids(item))
    return result


def evidence_context(store, item):
    """Read only explicitly pinned graph versions, with missing evidence visible."""
    if item['kind']=='unit':return dict(nodes=[item['unit']],graph_id=item['graph_id'],observer=item['observer'],run_id=item['run_id'],missing=False,omitted=0)
    if item['kind']!='behavior_case':return None
    record=item['record'];ids=referenced_ids(record['case'])
    try:graph=graph_store.read(store,record['graph_id'])
    except KeyError:return dict(nodes=[],missing=True,omitted=0)
    if graph['run_id']!=record['run_id'] or graph['source_hash']!=record['source_hash']:raise InputError('Pinned case graph differs from its saved source')
    nodes=[n for n in graph['nodes'] if n['id'] in ids or n['id'].removeprefix('event:') in ids]
    return dict(nodes=nodes[:64],graph_id=graph['id'],observer=graph['observer'],run_id=graph['run_id'],missing=False,omitted=max(0,len(nodes)-64))


def collect(store, identifier):
    with store.read_snapshot() as saved:
        bundle=investigation_followups.bundle(saved,identifier);doc=bundle['investigation']
        if doc['schema'] not in SCHEMAS:raise InputError('Choose a saved rollout, training or interval investigation')
        items={};contexts={}
        for check in doc.get('follow_up',{}).get('checks',[]):
            for finding in check['results']:
                for e in finding['evidence']:
                    key=digest(e);items[key]=e;contexts[key]=evidence_context(saved,e)
    return dict(bundle=bundle,evidence=items,contexts=contexts)


def render(store, identifier, *, origin=''):
    """Standalone HTML; inline styling, no scripts, external assets, or live data."""
    if origin:
        url=urlsplit(origin)
        if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
            raise InputError('Workspace origin must be an HTTP or HTTPS origin without a path')
    data=collect(store,identifier);bundle=data['bundle'];doc=bundle['investigation'];s=summary(doc)
    report_id='findings-report-'+digest(data)
    def link(label,path):return '<a href="'+escape(origin+path,quote=True)+'">'+escape(label)+'</a>' if origin else ''
    revision='/investigate?'+urlencode({'saved':doc['id']})
    report_path='/api/investigations/'+doc['id']+'/report'
    head='<header><span class="brand">Rilldex <span>/ Findings report</span></span><nav>'+link('Open investigation',revision)+link('Download HTML',report_path+'?'+urlencode({'origin':origin,'download':'1'}))+'</nav></header>'
    body='<main><div class="eyebrow">SAVED INVESTIGATION</div><h1>'+escape(doc['title'])+'</h1>'
    body+=paragraph(doc.get('hypothesis') or 'No research question recorded.','lead')
    body+=paragraph('Researcher-authored findings · exact saved evidence · no live refresh','meta')
    checks=doc.get('follow_up',{}).get('checks',[]);counts=Counter(c['results'][-1]['assessment'] if c['results'] else 'pending' for c in checks)
    body+='<nav class="sections">'+''.join('<a href="#'+k+'">'+v+'</a>' for k,v in [('findings','Findings'),('population','Population'),('measures','Measures'),('evidence','Evidence'),('limits','Limits & versions')])+'</nav>'
    body+='<section id="findings"><h2>Findings</h2>'
    if not checks:body+=paragraph('No findings recorded. Add a check and finding in the investigation to include your conclusions here.')
    else:
        body+=paragraph(' · '.join(f'{v} {k.replace("_"," ")}' for k,v in counts.items()),'meta')
        for check in checks:
            latest=check['results'][-1] if check['results'] else None
            status=latest['assessment'] if latest else 'pending'
            body+='<article class="finding '+status+'"><span class="badge">'+escape(ASSESSMENTS.get(status,'Awaiting a result'))+'</span><h3>'+escape(check['title'])+'</h3>'
            if latest:body+=paragraph('Hypothesis: '+check['hypothesis'],'meta')
            body+=paragraph(latest['conclusion'] if latest else check['hypothesis'],'conclusion')
            body+=details('Check procedure', {k:check.get(k) for k in ('hypothesis','procedure','expected_result','controls')})
            if latest:
                if latest.get('limitations'):body+=paragraph('Limitations: '+latest['limitations'])
                if latest.get('next_action'):body+=paragraph('Next action: '+latest['next_action'])
                body+='<div class="evidence-links">'+''.join('<a href="#e-'+digest(e)+'">'+escape(e['title'])+'</a>' for e in latest['evidence'])+'</div>'
                if len(check['results'])>1:
                    body+='<details><summary>Previous findings ('+str(len(check['results'])-1)+')</summary>'
                    for previous in check['results'][:-1]:
                        body+=paragraph(ASSESSMENTS[previous['assessment']]+': '+previous['conclusion'])
                        body+=''.join('<a href="#e-'+digest(e)+'">'+escape(e['title'])+'</a> ' for e in previous['evidence'])
                    body+='</details>'
            body+='</article>'
    body+='</section><section id="population"><h2>Population</h2>'+s['scope']+'</section>'
    body+='<section id="measures"><h2>Saved measures</h2>'+s['measures']+paragraph('Values and denominators are from this saved comparison. Missing measurements remain unavailable. Fraction changes are percentage points.','meta')+'</section>'
    body+='<section id="evidence"><h2>Linked evidence</h2>'
    if not data['evidence']:body+=paragraph('No evidence attached to findings. Saved population and measure tables remain available above.')
    linked={d['id']:d for d in bundle['linked_comparisons']}
    for key,item in data['evidence'].items():
        body+='<article class="evidence" id="e-'+key+'"><span class="eyebrow">'+escape(item['kind'].replace('_',' '))+'</span><h3>'+escape(item['title'])+'</h3>'
        kind=item['kind'];ctx=data['contexts'][key]
        if kind=='investigation':
            nested=linked[item['id']];info=summary(nested)
            body+=paragraph(nested.get('hypothesis') or 'No hypothesis recorded.')+info['scope']+info['measures']+link('Open exact comparison','/investigate?'+urlencode({'saved':nested['id']}))
        elif kind=='evaluation':
            receipt=item['receipt'];body+=paragraph(receipt['summary'])+paragraph('Recorded verdict: '+str(receipt['verdict']))+details('Evaluator, execution and inputs',receipt)
            for citation in receipt.get('source_citations',[]):
                body+='<div class="source"><strong>Source excerpt · '+escape(citation.get('role','context'))+'</strong><pre>'+escape(citation['text'])+'</pre></div>'
        elif kind=='behavior_case':
            record=item['record'];body+=paragraph(record['status_label']+' · '+record['location'])+details('Case and coverage',dict(record=record,coverage=item['coverage'],limits=item['limits']))
        else:body+=details('Saved evidence record',item)
        if ctx:
            if ctx['missing']:body+=paragraph('The pinned graph is unavailable. No newer graph was substituted.','missing')
            for node in ctx['nodes']:
                props=node.get('properties',{});quote=props.get('source',{}).get('quote') or props.get('text')
                body+='<div class="source"><strong>'+escape(str(node.get('activity') or node['kind']))+'</strong>'
                if quote:body+='<pre>'+escape(quote)+'</pre>'
                body+=details('Exact node',node)+'</div>'
            if ctx['omitted']:body+=paragraph(f"{ctx['omitted']} additional referenced nodes are available in the originating workspace.",'meta')
            if not ctx['missing']:
                body+=link('Open pinned map','/semantic-map?'+urlencode(dict(run=ctx['run_id'],graph=ctx['graph_id'],observer=ctx['observer'],**({'focus_unit':item['unit_id']} if kind=='unit' else {}))))
        if kind not in {'unit','evaluation'}:body+=details('Identity and saved record',item)
        body+='</article>'
    body+='</section><section id="limits"><h2>Limits & versions</h2>'
    limits=list(dict.fromkeys(doc.get('limits',[])+doc['snapshot'].get('limits',[])))
    body+=''.join(paragraph(x) for x in limits)
    body+=paragraph('Conclusions and assessments belong to the researcher. Temporal association alone does not establish a cause. This file includes attached records and explicitly referenced graph nodes; complete traces remain in the originating workspace.')
    body+=details('Measurement definitions and versions',s['versions'])
    if doc['snapshot'].get('history'):body+=details('Recorded run history',doc['snapshot']['history'])
    body+=details('Report provenance',dict(report_id=report_id,investigation_id=doc['id'],snapshot_id=doc['snapshot']['snapshot_id'],schema=doc['schema'],
        captured_at=doc['snapshot'].get('captured_at'),linked_comparisons=list(linked),inference_calls=0))
    body+=link('Download machine-readable investigation','/api/investigations/'+doc['id']+'/bundle?download=1')+'</section></main>'
    css=(Path(__file__).parent/'web'/'findings-report.css').read_text(encoding='utf-8')
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:; base-uri \'none\'; form-action \'none\'"><title>'+escape(doc['title'])+' · Rilldex</title><style>'+css+'</style></head><body>'+head+body+'</body></html>'


def export_findings(database, investigation_id, destination, *, origin=''):
    """Write an offline HTML report to a new file; optionally link to its workspace."""
    from .store import Store
    html=render(Store(database),investigation_id,origin=origin)
    path=Path(destination)
    with path.open('x',encoding='utf-8') as file:file.write(html)
    return path
