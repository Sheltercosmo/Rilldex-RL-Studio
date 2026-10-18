# Attachment review (experimental)

Review which work items a qualifier, method or intention applies to. Use the fixed `packet` and `bound` records from `tracker.work_content_bindings`; review one `feature_id` at a time.

```python
from tracker import work_feature_membership as review
from tracker.metered_jev import BoundedTransport

request = review.request(packet, bound, feature_id)
transport = BoundedTransport("attachment-review", maximum=1)
result = review.resolve(packet, bound, feature_id, transport(request))
```

Transport uses `JEV_API_KEY`, respects proxy settings and reuses exact saved responses. The ceiling counts HTTP attempts, not tokens. Pass a recorded response to `resolve` for offline use.

`content_ids` is available only for a complete individual attachment selection. Joint scope, missing contents and unresolved decisions remain separate states. `positive_content_ids` contains intermediate judgments, not approved attachments. Selection uses raw argmax, without confidence thresholds.

`compare_to_choice(packet, feature_id, choice_bound, choice_result, membership_bound, membership_result)` compares validated readings without choosing a winner. Results are **review-only** and do not publish graph edges or modify metrics.

Development trials found mixed results: shared-method attachment improved, but hedge attachment and shared negation still failed. This is not a validated extractor replacement. Four authored controls retain the original API responses, including failures:

```sh
python -m unittest discover -s tests -p test_work_feature_membership.py
```

This replay makes no model calls. Passing tests establish protocol behavior, not semantic accuracy.

## Optional local syntax context

With [spaCy and its English model](https://spacy.io/models/en#en_core_web_sm) installed separately:

```python
import spacy
from tracker import work_syntax_evidence as syntax

nlp = spacy.load("en_core_web_sm")
document = nlp(request["state"]["unit"]["source"]["text"])
captured = syntax.from_spacy(packet, bound, document,
    library_version=spacy.__version__, model=nlp.meta["name"],
    model_version=nlp.meta["version"])
evidence = syntax.review(packet, bound, feature_id, result, captured)
```

Inspect `pairs` for source spans, predicted dependency paths and cross-sentence review flags. Flags do not reject attachments or establish negation scope. Partial token matches stay unaligned. Other parsers can supply `bind()` with the same source, parser metadata and token-tree fields. Saved records replay without spaCy or API calls.
