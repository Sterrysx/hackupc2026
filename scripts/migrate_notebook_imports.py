"""Migrate `from sdg.*` / `from ml_models.*` imports inside Jupyter notebooks.

Notebooks aren't covered by pytest CI but they're executed by ``ml/train.sh``.
This script walks every ``*.ipynb`` under the repo and rewrites code-cell
import lines that survived the Python-only bulk replace in Phases 4 + 6.

Usage
-----
    uv run python scripts/migrate_notebook_imports.py            # apply
    uv run python scripts/migrate_notebook_imports.py --dry-run  # preview
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import nbformat

REPO_ROOT = Path(__file__).resolve().parent.parent

SUBS = [
    ("from sdg.", "from backend.simulator."),
    ("import sdg.", "import backend.simulator."),
    ("from ml_models.", "from ml."),
    ("from ml_models import", "from ml import"),
    ("import ml_models.", "import ml."),
    # Bare `import ml_models` becomes `import ml as ml_models` so existing
    # notebook references to `ml_models.PROJECT_ROOT` keep working.
    ("import ml_models\n", "import ml as ml_models\n"),
]


def migrate(nb_path: Path, dry_run: bool) -> tuple[int, int]:
    nb = nbformat.read(nb_path, as_version=4)
    changed_cells = 0
    total_replaced = 0
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        source = cell.source
        new = source
        for old, replacement in SUBS:
            count = new.count(old)
            if count:
                new = new.replace(old, replacement)
                total_replaced += count
        if new != source:
            cell.source = new
            changed_cells += 1
    if changed_cells and not dry_run:
        nbformat.write(nb, nb_path)
    return changed_cells, total_replaced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing files.")
    args = parser.parse_args()

    notebooks = sorted(REPO_ROOT.rglob("*.ipynb"))
    notebooks = [p for p in notebooks if ".ipynb_checkpoints" not in p.parts]

    total_files = 0
    total_changed = 0
    grand_total = 0
    for nb_path in notebooks:
        cells_changed, replacements = migrate(nb_path, args.dry_run)
        total_files += 1
        if cells_changed:
            total_changed += 1
            grand_total += replacements
            rel = nb_path.relative_to(REPO_ROOT).as_posix()
            verb = "would update" if args.dry_run else "updated"
            print(f"  {verb} {rel}: {cells_changed} cell(s), {replacements} replacement(s)")

    print(f"\nScanned {total_files} notebooks; "
          f"{'would touch' if args.dry_run else 'touched'} {total_changed} files "
          f"({grand_total} total replacements).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
