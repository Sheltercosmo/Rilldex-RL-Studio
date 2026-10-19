# Diagnostic detector validation

Behavior flags identify recorded actions for investigation. They do not establish
successful reward hacking. Use [Reward checks](custom-monitors.md) to display
saved findings; custom detectors can combine task-specific rewards and external
evaluation results.

## Controlled findings · 18 October 2026

These are selected development cases from public CheatBench traces, supplemented
with explicitly synthetic policy contexts. They are not a held-out accuracy estimate.

| Controlled comparison | Finding |
| --- | --- |
| Retrieval budget versus source inventory | One grader read was on the fourth-ranked page, outside a two-page budget. Other misses occurred in inspected pages. |
| Context size, question count, Jev version | Shorter packets, a single question, and the 1.13→1.14 comparison did not fix the tested errors. No tested request hit a reported context limit. |
| Literal facts versus combined judgment | Jev recognized component facts but still misclassified some mechanisms. Independent Python emulation found 257 mismatched cells in one numerical example; it did not execute the submitted CUDA binary. |
| Task presentation | Cohesive task context cleared two false flags on five known cases; an unrelated false flag remained. |
| Native record capture | Replay preserved 272 action/result pairs across 15 SDK contexts. Linked excerpts partly recovered all 14 previously omitted oversized records. This measures evidence delivery. |
| Access definition | Separating evaluator access from permission matched all eight reviewed single-action/control expectations. This does not measure general reward-hacking accuracy. |
| Instruction/action choices | Four full-page tests recognized explicit permission, cited a prohibited read with its rule, and excluded tool quotations from rule candidates. Read-only access still caused false bypass flags. |

## Broader public-data validation · 18 October 2026

New tests used [HackTrace](https://huggingface.co/datasets/JH012/HackTrace-Data)
and fresh [CheatBench](https://huggingface.co/datasets/steinad/CheatBench) traces:

| Sample | Result with the existing version 12 detector |
| --- | --- |
| 16 HackTrace coding trajectories, complete scans | 5/8 shortcut-labeled cases flagged; 0/8 benign cases flagged. All three misses had empty recorded files despite code in the response. |
| 12 CheatBench trajectories across six environments, two-page budget | Alerts on 3/6 positive cases; one suspected-bypass false flag. A separate benign evaluator-access observation was accurate. Only 2/12 scans completed. |

These are small challenge samples with mixed reference-label quality, not
deployment accuracy. HackTrace elicits shortcuts; its shortcut labels differ
from successful exploitation. Controlled context changes fixed one false flag
but lost valid observations elsewhere, so they were **not promoted**.

The new [artifact check](custom-monitors.md#required-artifacts) examined all
40,552 HackTrace test records without model calls: 1,117 empty required-file
cases, including 279 non-cheating labels and no successful-exploit labels.
It measures artifact integrity, not hacking prevalence. Sixteen actual trace
imports also passed publication, chart/evidence access and restart reuse.

The initial transfer validation used 64 Jev calls: 1,021,219 input / 70,007 output tokens.
Unchanged decisions were replayed from cache. Remaining gaps include long-trace
retrieval and semantic discrimination of substituted work, leaked labels and
legitimate setup changes.

## Current behavior

The recorded end-to-end test completed
eight public histories and one command replay through HTTP import, scans, monitors,
evidence and restart: 38 API calls, zero on restart. Semantic flags covered two of
four reference-positive histories; a separate file check exposed empty artifacts
in a third. Bounty exploit substitution remained missed after a complete scan.
Four benign histories had no flags. This small panel is not deployment accuracy.

New search workers use version 19. Bounded native commands and embedded JSON tool
payloads stay intact as citation candidates; grouping does not infer actor roles
or execution. Oversized or heavily escaped payloads fall back to bounded chunks.
Findings retain exact source citations and native scope; restriction findings also cite their prior instruction. Missing
rule candidates with observed access remain unresolved. Partial scans can
publish positives; unflagged incomplete scans remain unknown. Jev uses raw argmax,
without a confidence threshold or an extra review pass. Existing workers retain
their original versions and cached decisions.

Version 16 adds a bounded Python code-flow check: test input, an explicit answer
field, and copied sample outputs are separate raw-argmax selections in the same
page request. Findings include the entry function, helpers and source lines.
One early scan slot prioritizes literal test-input/answer-field code. Unchanged
pages retain exact version-14 requests and can reuse decisions across workspaces.

Version 19 compares the required target, the artifact's success mechanism and
its role as a deliverable. It recovered the full-scan bounty miss: the original
panel now flags three of four reference-positive histories; all four benign
histories remain unflagged. A second recorded substitution and three native
legitimate-use controls also passed. This is development evidence, not held-out
accuracy. Text-only test tampering remains missed. Existing code-flow pages keep
their validated requests; mixing the two question sets caused a measured regression.
The refinement used 33 calls (553,995 input / 64,836 output tokens); final replay
used none. Nine monitor scans, 126 evidence reads and restart/cache reuse passed.

Nine public-trace comparisons corrected one known test-label-copying miss within
two pages, retained prior flags, and added no flags in two fresh benign scans.
All nine scans remain partial. Training-only and feature-only counterfactuals
did not trigger the code-flow rule; the package-installation reuse false flag
remains. This supports a narrow improvement, not a general accuracy percentage.
Supported code is static Python function neighborhoods in recorded code fields,
notebook source arrays and explicit Python heredocs. Dynamic/global data flow,
other languages and successful exploitation are not established.

The controlled experiments and transfer checks used 51 calls: 707,524 input /
67,493 output tokens. The final nine-case comparison reused 16 of 18 page decisions.

In 12 compared public traces, complete-payload indexing retained all previously
detected positives, cleared two false flags, and introduced one false answer-reuse
flag on package installation. Two new positive cases remained unflagged under the
two-page budget. A separately localized bounty-exploit page became detectable.
This is a small engineering comparison, not a population accuracy estimate.
The refinement used 34 additional calls (459,580 input / 37,123 output tokens).
All 44 saved end-to-end results replayed exactly without new calls. Lossless
indexing and request limits were checked across 32 public traces.

Remaining limitations include computational reasoning, bypass false positives,
bounded evidence retrieval, and interpretation of an access without an applicable
rule when a page contains other instruction candidates. Access, instruction
conflict, answer reuse and actual evaluation distortion remain distinct measures.

The initial diagnosis used 42 changed API requests. The latest access refinement
used 12 requests (151,898 input / 6,723 output tokens). Local request/response
archives are excluded from the public package. Portable regression tests cover
capture, choice boundaries, citations, resume/replay and monitor publication;
passing those tests does not establish semantic accuracy.
