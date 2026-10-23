# Detector validation

1. In **Monitor management**, open rollout values and choose **Review all outcomes**. Review built-in diagnostic indicators, binary code monitors, or analysis rates with opportunity cases.
2. Save judgments, then choose **Save validation set**. Name the set and select a reviewer’s samples. Labels and source references are frozen; later edits create a different set.
3. Select **Development** or **Held out**, choose a monitor version, and **Compare saved results**. This reads existing measurements without running a detector.
4. Choose a previous evaluation to see improvements, regressions and coverage changes. **Inspect case** opens the frozen reference, source and exact measurement.

Splits keep recorded tasks together, falling back to rollout identity. A held-out assignment does not prove prior independence. Agreement uses jointly decidable cases; coverage and **Positive cases detected** include unavailable predictions. These results describe the selected reviewed cases, not population accuracy. Changed external inputs remain visible and are not scored against an older reference.

## Python

Copy the set-specific example from **Run custom Python**:

```python
from rilldex import ValidationSet

validation = ValidationSet("study.sqlite", "validation-set-...")

def detect(case):
    events = case["source_events"]
    return None  # Replace with your detector's True / False result.

result = validation.evaluate(detect, name="My detector", version="v2", split="development")
print(result["report"])
```

Callbacks receive frozen source and declared inputs, without reference labels or previous predictions. Opportunity cases retain their review scope. Return `True`, `False`, `None`, or `{ "value": null, "status": "unresolved", "reason": "..." }`. Callback failures are saved as errors. Execution happens only in your Python process; results appear in the UI.

`GET /api/detector-validation` lists sets and evaluations. `POST /sets` creates a set; `POST /capture` compares saved monitor results; `POST /results` accepts externally computed predictions by frozen case ID. Paths are relative to `/api/detector-validation`. Missing predictions remain missing. JSON exports retain labels, definitions, versions and case references; source links refer to the same workspace.
