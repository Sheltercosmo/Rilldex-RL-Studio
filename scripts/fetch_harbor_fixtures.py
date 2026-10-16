"""Fetch only pinned public test evidence, never execute trajectory commands."""
import concurrent.futures
import hashlib
import json
import urllib.request
from pathlib import Path

REVISION = "c803185a8b7c88c163abe48a22e9cea0bbd95e90"
PATHS = [
    "rfcs/0001-trajectory-format/mini-swe-agent-trajectory.json",
    "tests/golden/terminus_2/hello-world-context-summarization-linear-history.trajectory.json",
    "tests/golden/terminus_2/hello-world-context-summarization-linear-history.trajectory.cont-1.json",
    "tests/golden/terminus_2/hello-world-timeout.trajectory.json",
    "LICENSE",
]
DESTINATION = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "harbor"


def fetch(path):
    url = f"https://raw.githubusercontent.com/harbor-framework/harbor/{REVISION}/{path}"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(4_000_001)
    if len(data) > 4_000_000:
        raise ValueError("Fixture too large")
    local = DESTINATION / Path(path).name
    local.write_bytes(data)
    return {"source": url, "file": local.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(fetch, PATHS))
    (DESTINATION / "sources.json").write_text(json.dumps({"repository": "https://github.com/harbor-framework/harbor", "revision": REVISION, "files": results}, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
