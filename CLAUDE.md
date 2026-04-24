# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

Python 3.12 managed via uv for packages.

Activate before any work:


## Commands

```bash
uv add                  #add a new pithon package
uv sync                   # install / re-sync dependencies
uv uv run main.py            # run the entry point
uv run pytest             # run all tests
uv run pytest tests/path/to/test_file.py::test_name  # single test
uv add <package>          # add a dependency (commits pyproject.toml + uv.lock)
uv remove <package>       # remove a dependency
```

## Git workflow

```bash
make new-branch name=feat/your-feature   # branch off latest main
make pr                                  # push + open PR interactively
```

Branch names must start with `feat/` or `fix/`. Both are enforced by `scripts/new-branch.sh`.
After a PR is open, run `/review <PR number>` in Claude Code for an AI review report.

## Project structure

Early-stage project. Entry point is `main.py`. Tests go in a `tests/` directory (not yet created). `scripts/` contains the git workflow helpers — do not modify them unless changing the branching/PR conventions.
