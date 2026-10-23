# Findings reports

Open a saved investigation and select **Read report**, then **Download HTML**. The file works offline and includes recorded conclusions, counterevidence, pending checks, cohort counts, measurement coverage, versions and attached evidence. Use **Checks & findings** in the investigation to add or revise conclusions.

Reports retain the exact saved revision. Late arrivals and later findings do not change it. Source excerpts and explicitly referenced graph nodes are embedded; complete traces stay in the workspace. Workspace links require access to the original server. No model calls run when viewing or exporting.

```python
from rilldex import export_findings

export_findings("study.sqlite", "investigation-...", "findings.html")
```

The destination must be a new file. Optionally set `origin="http://localhost:8810"` to include workspace links. The HTTP route is `GET /api/investigations/{id}/report`; add `download=1` for an HTML attachment. Existing **Export JSON** retains the machine-readable investigation.
