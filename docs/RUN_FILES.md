# Files and checkpoints

Use `run.add_file("config.yaml")` for an embedded snapshot up to 2 MiB. Use references for large checkpoints and datasets:

```python
run.add_reference("./checkpoints/step-100", role="checkpoint", step=100)
run.add_reference("s3://bucket/models/policy.safetensors",
                  role="model", version="object-version-id")
```

Local files are hashed in chunks; directories retain relative names and per-file hashes. Record completed outputs. `checksum=False` skips local hashing. Remote URIs record supplied `size`, `sha256` and storage `version` without contacting the provider. Repeating a call retains another record. References do not copy or preserve external bytes.

**Run details → Files** supports search, worker/session selection and storage links. References can include `step`, `clock` and `trainer_session` to open the corresponding training interval. Local references identify the recording machine; use shared mounts or cloud storage when moving between hosts.

```python
from rilldex import Workspace

ws = Workspace("study.sqlite", experiment="reasoning/trial-1")
files = ws.run_records(kind="file", q="policy")
receipt = ws.download_file(files["rows"][0]["sequence"], "./policy.safetensors")
print(receipt["verification"])  # sha256, size_only, or unverified
```

Retrieval streams on your Python host, checks recorded identity and never overwrites an existing destination. Install `rilldex[s3]` or `rilldex[gcs]` for cloud access; credentials use the provider's normal configuration. S3 versions and GCS generations are passed to their storage drivers. Other providers use their fsspec driver and a versioned URI. `storage_options={...}` configures the client; `opener(reference)` supports custom storage or relocated files.

Offline bundles and workspace backups retain reference metadata. Keep external files available separately. Directory capture supports up to 10,000 files; it is a manifest of observed files, not an atomic filesystem snapshot.

This follows the external-file pattern in [W&B](https://docs.coreweave.com/products/wandb/artifacts/track-external-files) and the separation of tracking and artifact storage in [MLflow](https://mlflow.org/docs/latest/self-hosting/architecture/artifact-store/).
