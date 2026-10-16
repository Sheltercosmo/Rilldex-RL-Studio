# Planning observations: intent, organization and scope

Revised following the user's correction on 7 October 2026.

The existing H1 Plan tag combines a next-step announcement with structured planning. Its rule explicitly includes intended steps. Treating that count as high-level planning could mistake more narration, smaller text units or repeated announcements for more planning. The same ambiguity would contaminate plan-following, replanning and training-shift analyses.

## Revised observation contract

| Dimension | What it records | Boundary |
| --- | --- | --- |
| Intended work | Work the speaker announces or adopts | A next-step callout belongs here. Use the intent/expression layer; it does not by itself establish planning structure. Performer and requests to others remain separate. |
| Plan organization | An expressed approach to a goal, decomposition, ordering/dependency, or condition selecting a course of action | Naming one operation, its immediate purpose, or saying “first” is insufficient. Require the organizing relationship to be expressed. |
| Organization scope | One operation's internal procedure, a local subgoal/phase, the overall task, multiple independently expressed scopes, or unresolved | Scope is relative to the recorded task. Length, step count and tool count do not determine it. A concise strategy can address the whole task. |

These observations can coexist. A local procedure can be structured planning without being a high-level plan. A goal statement alone is Orient; it does not describe how work is organized. A request to run a check is Coordinate; the request does not prove the check happened. An intended verification is distinct from an attempted verification.

The following are authored design illustrations, not independent reference labels or measured Jev results:

| Expression and context | Intended work | Organization | Scope |
| --- | --- | --- | --- |
| “I'll inspect the logs.” | Yes | No organization expressed | Not applicable |
| “First, I'll inspect the logs.” with no other relationship supplied | Yes | An ordinal alone is insufficient | Not applicable |
| Within repairing a service: “For the configuration check, compare active settings with defaults, then test the mismatches.” | Depends on speaker/performer context | A local sequence is expressed | Configuration subgoal |
| Within diagnosing a service: “Separate configuration, network and application causes; isolate each before changing the system.” | Depends on adoption/performer context | Decomposition and ordering are expressed | Overall task |
| Within proving a theorem: “Use proof by contradiction.” | Depends on adoption context | A problem-solving approach is selected | Overall task, despite being short |

## Building the upper layer

A plan needs an evidence-linked representation: goal, proposed approach/subgoals, ordering/dependencies/conditions, scope, performer, source references and the cutoff at which each part became available. It can span several expressions. Preserve announcement, proposal, adoption, revision, attempted execution and observed result as different events or relationships.

For example, an earlier next-step announcement can later become one referenced element of a larger plan. The later observation can record that relationship; it must not rewrite the earlier expression's source-time label. Repeated mentions must not automatically create new plan objects. A changed next action is not automatically a changed strategy.

Useful eventual comparisons include the share of rollouts containing explicit task-level organization, distinct plan revisions, and observed attempts linked to proposed subgoals. Their denominators and identity/link rules require validation. Span-level Plan frequency is not a substitute, and an absent expressed plan does not establish absence of private planning.

## Implemented now and validation still needed

- The live viewer labels the existing `general-activities/2` field **Intended steps / plans (broad)** in the filters, source list, timeline and detail. An adjacent explanation states its interpretation limit. The original definition, request, selected value, probability distribution and counts remain intact.
- `tracker/planning_structure.py` supplies a separate candidate harness, `planning-structure/0.1-experimental`: independent questions for `own_intended_work`, `organizes_work` and `organization_scope`. Each selects the maximum-probability supplied option. An unresolved/not-applicable option must win; no confidence or margin routing or cross-field repair is used.
- The candidate uses exact model-text evidence through the source cutoff and rejects action dispatches as expressions. It receives no old Plan predictions. It has now run on the development comparison below; it is not connected to live H1 or established as accurate.
- Contract and browser checks cover source binding, actor/cutoff preservation, independent selections, unchanged saved observations, and the qualified display on desktop/mobile. They do not validate the semantic boundary.

Next, build reference cases that deliberately contrast bare next-step announcements, local procedures, concise task-wide strategies, multi-span plans, restatements, candidate plans and revisions across reasoning, software and interactive domains. Evaluate organization and scope separately. Promote a new version only after that comparison; old broad labels cannot be mechanically split into the new observations. Any longitudinal comparison needs reprocessing under a common version.

## Development comparison: source units matter

The frozen [case inspector](../research/planning-structure-2026-10-07/inspection-v2.html) compares twelve real-source groups at two grains: a local expression and a cumulative block ending at the same character cutoff. Both receive the identical visible prefix. Sources cover reasoning, software, telecom, retail and search. Cases and review criteria were frozen before inference; native labels and previous Plan predictions were excluded. All 24 requests completed, reporting 126,407 input and 3,849 output tokens. This purposive development sample contains overlapping observations and no independent product references; it supplies no accuracy or behavior-prevalence estimate.

| Source contrast | Recorded choices | Consequence for design |
| --- | --- | --- |
| Phone-status and SIM-check announcements | Intended work present, organization absent, scope not applicable at both grains | A next-step intention can be retained without counting an organized plan. These selected examples do not establish general accuracy. |
| Chirp-mass calculation | Local value substitution: no organization. Larger passage with proposed calculation and formula: organization, single-operation scope | Organization can be distributed across expressions. Subject boundaries are part of the measurement contract. |
| Modulo-200 decomposition | Both grains: overall-task organization | A short passage can express a task-wide approach. Length is not a scope measure. |
| Reproduction block and retail-options block | Organization absent, but single-operation scope | Two explicit contract conflicts. The report flags them while retaining all raw argmax choices; the conflicts do not identify which field is wrong. |
| Repair method and conditional telecom procedure | Single-operation versus local-subgoal scope changes with the passage | Different subjects can warrant different scope, but this boundary is not validated. A larger block must not automatically mean broader scope. |
| Chemistry fallback from unavailable calculations to recalled values | Intended work present, organization absent at both grains | The boundary between a stated next operation and an expressed fallback strategy still needs reference review. |

These are implementation-assistant observations, with exact source citations in [findings.json](../research/planning-structure-2026-10-07/findings.json). The [summary](../research/planning-structure-2026-10-07/summary.json) separates the two grains; summing them would double-count overlapping text. The [blind review](../research/planning-structure-2026-10-07/review.html) excludes predictions and companion results. The inspected source spans, task context and raw Jev distributions remain available separately.

The near-term priority is to establish the organizing relationship and its goal anchor before treating scope as a useful metric. Reviewers should identify the exact goal/method, decomposition, ordering or conditional relation, then judge whether it organizes the whole recorded task or only part of it. The finer operation-versus-subgoal distinction must justify its reliability and analytical usefulness before promotion. Preserve candidate alternatives and independent argmax selection; improve evidence and candidate construction outside selection. No wording sweep, probability threshold or automatic cross-field correction was chosen from this run.

The next upper-layer representation should link these relationships into a distinct plan object with source spans and creation/revision cutoffs. Overlapping mentions, repeated announcements and a local-plus-block pair must not become separate plan counts. This study does not yet implement or validate those objects, plan following, plan quality or training progress.
