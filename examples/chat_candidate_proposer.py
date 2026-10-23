"""Compatibility entry point. Prefer python -m rilldex.candidate after install."""
from rilldex.candidate import propose

if __name__ == "__main__":
    import runpy
    runpy.run_module("rilldex.candidate", run_name="__main__")
