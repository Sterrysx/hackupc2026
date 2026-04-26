"""Top-level package for the 3-stage maintenance-policy ML ladder."""
from pathlib import Path

# Repository root, resolved from this file's location so notebooks in any
# subdirectory can build canonical absolute paths irrespective of the
# Jupyter / Python working directory at run time.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

__all__ = ["PROJECT_ROOT"]
