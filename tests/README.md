# Running tests

Install a checkout with `python -m pip install ".[contracts]"`, then run:

```sh
python scripts/run_tests.py
python scripts/run_tests.py --javascript
```

Node.js is required for the JavaScript suite and the Python suite's renderer integration check. Runtime collection does not require it.

The portable suite uses repository fixtures and synthetic controls. Some retained tests reference separately stored research datasets and observation receipts; those modules are listed in `scripts/run_tests.py` and excluded by default. Maintainers with those archives can use `--with-archives`. They are not shipped as user data or silently downloaded.

Installed-package lifecycle tests live in `scripts/*_smoke.py`. `telemetry_smoke.py` sends a 128-step synthetic native-log replay through a real collector; it requires an isolated collector endpoint and an output directory. It tests capture, gaps, replay and series separation, not training quality or detector accuracy.
