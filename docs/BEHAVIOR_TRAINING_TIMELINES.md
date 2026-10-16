# Behavior across training

Open **Training health → Show → Behavior across training**, then choose an existing behavior measure. Opening Training health with a selected monitor also chooses this view in Automatic mode. No inference or new annotation is triggered.

The two charts use different coordinates:

- **At generation**: the source-declared generation position of each captured sample. Samples without a position are inspectable separately.
- **Backward passes / Optimizer updates**: the producer's recorded learner step for the selected stage and exact training-settings reference. Receipts from different stages, producers or settings revisions remain separate.

Each point counts a bound source rollout once, even if several training samples reference it or the trainer uses it repeatedly at that position. The same source can appear again at later positions. Scalar measures use the mean across measured source rollouts. Opportunity-ratio monitors pool their recorded numerator and denominator, with unresolved opportunities shown separately. The charts share a numerical scale but keep their own horizontal axes.

Select a point or open its coverage table to inspect sample identities, source measurements and receipt counts. **Measured behavior** opens the immutable monitor-value evidence. Export includes the pinned health snapshot, timeline identity, sample-to-source bindings, recorded measurements, receipt references and the selected full receipts. The timeline API itself keeps compact receipt references to avoid copying token arrays into every point.

Missing observations remain gaps. Samples outside or with unknown monitor scope are reported. A missing use receipt does not mean rejection. These measures describe whole-source context, not behavior in trained tokens, gradient attribution, improvement or causal effects. Task mix and annotation coverage can affect changes.

The same observation model supports different RL methods; it does not require scalar advantages, a group baseline or a particular policy objective. Native source/sample/use capture and valid saved behavior measurements are still required. Framework settings recognition alone cannot supply them.

See [native replay evidence and validation](../research/behavior-training-timelines-2026-10-12/README.md).
