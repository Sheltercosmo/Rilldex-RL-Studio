# Workspace navigation

| Layer | Contents |
| --- | --- |
| Sidebar | One training-run switcher, analysis, research tools and pinned views. **Runs & projects** holds run management. |
| Selection | Search runs in the switcher; expand its environment filter when needed. On narrow screens, run context moves to the top bar. |
| Analysis | Overview opens the remembered run, or a recent run with trainer logs. Native signals and measured behavior lead; unavailable measures show a compact coverage link. |
| Evidence | Map inspector beside the canvas; a side sheet in narrow windows |
| Actions | Editing and setup in dialogs; exports and reports under **More** |

**Pin view** saves the current filters and evidence revision in this browser, separately for each workspace. Pins also appear in **Search workspace** (`Ctrl/Cmd K`). They are shortcuts, not new data snapshots.

Explicit URL scope overrides remembered selection. New arrivals refresh the selected run without switching it. Comparison, interval and rollout focus stay inside their analysis views; changing the training run clears those local selections. Saved investigations and explicit map links retain their evidence. Data arrival and unfinished rollouts are not claims that training is currently running.

Behavior distributions keep task, annotation and weighting under **Comparison settings**. Coverage gaps stay visible; detailed coverage is expandable. A selected category drives the trend, error follow-up and rollout evidence. Missing observations remain separate from measured zeroes. Window drafts survive refresh within the same scope.

Summary uses the same detailed training panels as Training: labeled axes, coverage, interval inspection and expandable definitions. Behavior cards retain their evidence and definition controls. Execution and map panels retain their existing canvas and inspector layouts.

**Save latest comparison** retains the applied windows, counts, coverage and source links. Reopen captures under **Comparison settings → Saved comparisons**. **Capture latest evidence** creates a follow-up for the same windows; the original stays fixed. **Open live comparison** returns to editable settings.

Saved rollout and interval comparisons group sections into **Summary**, **Rollout evidence**, **Checks & trials**, and **All sections**, where available. Metric investigations keep their analysis tabs and collapse saved selection settings. Direct evidence and check links open their containing view; **Back** retains the originating filters. `Esc` closes the active dialog before the underlying inspector.

Captured action–response links remain available in semantic maps, rollout stories and attempt comparisons. Whole-event cards show the saved link directly. Split or partial cards offer **Captured call feedback** with the full response; the interface does not assign it to an arbitrary sub-action.
