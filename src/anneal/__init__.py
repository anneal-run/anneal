"""Anneal: an agent compiler.

Records agent runs, finds reproducible structure, compiles it to guarded
deterministic steps, and hands back to the original agent on anything it
cannot reproduce.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("anneal-run")
except PackageNotFoundError:  # pragma: no cover - only when running from an uninstalled tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
