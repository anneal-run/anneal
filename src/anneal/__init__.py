"""Anneal v3: harness a workflow, score structural challengers on a holdout.

The Milestone 1 compiler (import, analyze, replay) is still here. It is not
the challenger. `anneal challenge` is the product this tree is building.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("anneal-run")
except PackageNotFoundError:  # pragma: no cover - only when running from an uninstalled tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
