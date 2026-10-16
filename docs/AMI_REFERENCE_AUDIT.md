# Independent annotation audit: AMI dialogue acts and response links

7 October 2026. This is a native-reference retrieval audit, not validation of RL activity accuracy. Reproduction code: `research/ami_reference_audit.py`. Frozen inputs and outputs: `research/ami-source-audit-2026-10-07/`.

## What this adds

We now have source-bound published manual response links that can test whether a candidate generator supplies the annotated antecedent. The pack has 171 response targets and 175 eligible positive links. Model-facing candidate records and native references are separate files. Multiple sources for one response remain multiple references; unlinked pairs do not become negative examples.

This addresses a concrete dependency of macro inspection: an accurate local activity tag cannot identify what feedback it responds to if the relevant source is missing from its choices. Candidate coverage is measurable before paying for a Jev decision. No Jev calls were made, no live tags changed, and no independent product-schema annotations were added.

## Sources and reproducibility

- [Official AMI download page](https://groups.inf.ed.ac.uk/ami/download/), its manual-annotation archive, and [annotation availability](https://groups.inf.ed.ac.uk/ami/corpus/annotationpresent.shtml).
- [Dialogue-act guidelines](https://groups.inf.ed.ac.uk/ami/corpus/Guidelines/dialogue_acts_manual_1.0.pdf), plus the archive's actual `da-types.xml` and `ap-types.xml` ontologies.
- AMI Meeting Corpus, University of Edinburgh and AMI project. The archive's `LICENCE.txt` specifies CC BY 4.0. This project derives space-joined token text, source bindings and audit results; original XML remains intact.

The URL names `ami_public_manual_1.6.2.zip`, the internal README calls it release 1.7, and the availability page describes version 1.6. Preserve all three claims; identify the inspected bytes by SHA-256 `b56e5babb2496b8795deeeda7e71178d7fbc9963f94276cf2a3f4b56ebbc9f9d`. `sources.json` records URLs, retrieval times and hashes. The audit verifies those files and records every archive member read. Unselected meetings were not parsed.

Two development meetings, ES2002a and IS1000a, were selected from the manual availability table. They represent different meeting groups. This is neither a held-out evaluation nor a representative sample of RL or AMI behavior. Native segmentation is supplied; our own segmentation is not tested.

```powershell
python -m research.ami_reference_audit --root research/ami-source-audit-2026-10-07
python -m unittest discover -s tests -p test_ami_reference_audit.py -v
```

Seven tests pass: exact XML range binding, Unicode/non-word preservation, invalid references, absent annotations, temporal exclusion, label-free retrieval, multiple sources per target, and deterministic reconstruction of the downloaded data. These verify extraction and reference handling, not semantic accuracy.

## Reconciled source evidence

| Inspected record | ES2002a | IS1000a |
| --- | ---: | ---: |
| Dialogue acts | 475 | 658 |
| Missing act type | 1 | 0 |
| Published response links | 99 | 140 |
| Missing source endpoint | 2 | 32 |
| Source extends beyond target end | 11 | 19 |
| Complete linked source available at target end | 86 | 89 |

All referenced XML IDs resolve. The word inventory contains 15 records outside dialogue-act ranges; these are retained in the inventory. One act contains a vocal-sound interval whose end precedes its start and is marked unavailable for timed retrieval. Four acts contain gap markers. Rendered text joins original words with spaces and explicit non-word markers; it is not a verbatim transcript character span.

Of the 30 links beyond the target cutoff, 29 connect overlapping speech. One source begins after the target ends under the published timings. This audit neither repairs that link nor asserts why it occurs. A future extension could expose only an overlapping source's visible token prefix; the current benchmark excludes incomplete source acts rather than leaking their later words.

## Candidate coverage before Jev

The baseline selects the most recently completed acts from all speakers in the same meeting, excluding the target itself. It uses no native labels, source-link IDs or outcome labels. An act must finish by the target's end; equal-time ties use stable IDs for reproducibility. Time order comes from publisher word alignment, not proof of who heard what.

| Recent complete acts supplied | ES2002a retained / eligible links | IS1000a retained / eligible links | Combined |
| --- | ---: | ---: | ---: |
| 1 | 50 / 86 | 41 / 89 | 91 / 175 |
| 3 | 79 / 86 | 73 / 89 | 152 / 175 |
| 5 | 84 / 86 | 86 / 89 | 170 / 175 |
| 10 | 86 / 86 | 88 / 89 | 174 / 175 |
| 20 | 86 / 86 | 89 / 89 | 175 / 175 |

These denominators exclude missing endpoints and incomplete source acts. They measure presence of an annotated source, not sufficient context, correct selection, precision, or absence of other valid sources. Perfect retention at 20 on these meetings does not justify a universal 20-unit window.

The eligible links belong to 171 targets; four targets have two annotated sources. `target-coverage.json` also reports whether **all eligible annotated sources** are retained for a target, separately from retaining at least one. The 175 links are not independent samples. Ten eligible links are within one speaker and 165 cross speakers. Speaker identity therefore must remain separate from the scope of evidence that a responding actor can observe; this is not permission to expose private actor logs.

## What the native tags can and cannot validate

The published scheme distinguishes own-action intention (Offer), other/group action proposals (Suggest), information elicitation, and response stance. Our consent-dependent offer property is narrower. The native positive/negative response categories concern support or opposition, not environment success or failure. These definitions therefore remain native references, without automatic conversion to Plan, Execute, success, or our actor/intent properties. The actual response ontology also contains Elaboration; neither selected meeting uses it.

The inspected Offer spans include both adopted future work and consent questions. This supplies useful boundary cases for our actor/intent definitions, but does not decide their product labels. Audio, video and artifacts were not inspected. A text-only inspector may lack evidence available to the original annotator.

## Product decisions supported by this audit

1. Evaluate candidate availability separately from Jev's fixed argmax decision. Preserve explicit no-suitable-candidate/unresolved options; missing native annotations cannot label either option automatically.
2. Model a response as potentially linked to multiple sources. Use independent bounded decisions for candidate relations when the contract permits multiple links; do not force one winner across all antecedents.
3. Preserve speaker, performer, observer visibility and temporal cutoff separately. Do not derive an interaction graph from adjacent activity tags or silently admit a source's later words.
4. Keep AMI as a reusable native-reference test for extraction and retrieval. Next, specify the product response relation on existing RL cases and map only definitions that actually agree. Independent product references and RL transfer remain necessary before promoting a new relation or macro metric.

Artifacts: `derived/source-units.json`, `derived/audit.json`, `derived/retrieval-cases.json`, `derived/native-references.json`, `derived/reference-contract.json`, and `derived/target-coverage.json`. Reruns verify source hashes and refuse to overwrite different frozen outputs.
