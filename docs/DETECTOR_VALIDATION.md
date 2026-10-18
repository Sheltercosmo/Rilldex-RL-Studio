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

## Current behavior

New search workers use version 12. Findings retain exact source citations and
native scope; restriction findings also cite their prior instruction. Missing
rule candidates with observed access remain unresolved. Partial scans can
publish positives; unflagged incomplete scans remain unknown. Jev uses raw argmax,
without a confidence threshold or an extra review pass. Existing workers retain
their original versions and cached decisions.

Remaining limitations include computational reasoning, bypass false positives,
bounded evidence retrieval, and interpretation of an access without an applicable
rule when a page contains other instruction candidates. Access, instruction
conflict, answer reuse and actual evaluation distortion remain distinct measures.

The initial diagnosis used 42 changed API requests. The latest access refinement
used 12 requests (151,898 input / 6,723 output tokens). Local request/response
archives are excluded from the public package. Portable regression tests cover
capture, choice boundaries, citations, resume/replay and monitor publication;
passing those tests does not establish semantic accuracy.
