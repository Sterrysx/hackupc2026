"""One-shot editor that wires every Stage notebook to ml_models.lib.fast.

Run from repo root: ``uv run python scripts/apply_fast_mode_edits.py``.

Idempotent: re-running detects the import line and skips notebooks that
already have it. Validates every replacement; aborts with a non-zero exit
if any expected substring isn't found.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]


def _read(nb_path: Path) -> dict:
    with nb_path.open(encoding="utf-8") as f:
        return json.load(f)


def _write(nb_path: Path, nb: dict) -> None:
    with nb_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)
        f.write("\n")


def _set_source(cell: dict, new_source: str) -> None:
    lines = new_source.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        pass  # last line has no trailing newline — preserve as-is
    cell["source"] = lines


def _replace_in_cell(
    nb_path: Path, cell_idx: int, old: str, new: str, *, count_required: int = 1
) -> None:
    """Replace ``old`` with ``new`` in code cell at ``cell_idx``. Aborts the
    whole script if ``old`` doesn't appear ``count_required`` times."""
    nb = _read(nb_path)
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    cell = code_cells[cell_idx]
    src = "".join(cell["source"])
    occurrences = src.count(old)
    if occurrences != count_required:
        sys.stderr.write(
            f"FAIL {nb_path} cell[{cell_idx}]: expected {count_required} occurrences "
            f"of {old!r}, got {occurrences}\n"
        )
        sys.exit(1)
    new_src = src.replace(old, new)
    _set_source(cell, new_src)
    _write(nb_path, nb)
    print(f"  ✓ {nb_path.relative_to(ROOT)} cell[{cell_idx}]")


def _ensure_import_first_cell(nb_path: Path, names: list[str]) -> None:
    """Ensure the first code cell ends with an import of the listed names from
    ``ml_models.lib.fast`` and a one-shot ``banner()`` call. Idempotent."""
    nb = _read(nb_path)
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    cell = code_cells[0]
    src = "".join(cell["source"])
    marker = "from ml_models.lib.fast import"
    if marker in src:
        print(f"  · {nb_path.relative_to(ROOT)} cell[0]: import already present")
        return
    addition = (
        f"\nfrom ml_models.lib.fast import {', '.join(names)}, banner\n"
        f"banner()\n"
    )
    new_src = src.rstrip() + "\n" + addition
    _set_source(cell, new_src)
    _write(nb_path, nb)
    print(f"  ✓ {nb_path.relative_to(ROOT)} cell[0]: added fast.py import")


# -------------------------------------------------------------------- edits


def edit_stage_01(nb_path: Path) -> None:
    print(f"[01_baseline/search.ipynb]")
    _ensure_import_first_cell(nb_path, ["N_OPTUNA_TRIALS", "PARALLEL"])
    _replace_in_cell(
        nb_path,
        cell_idx=3,
        old="N_TRIALS = 200\n",
        new="N_TRIALS = N_OPTUNA_TRIALS  # was 200; toggled by FAST_MODE in ml_models.lib.fast\n",
    )
    _replace_in_cell(
        nb_path,
        cell_idx=3,
        old="study.optimize(objective, n_trials=N_TRIALS, n_jobs=1, show_progress_bar=True)",
        new="study.optimize(objective, n_trials=N_TRIALS, n_jobs=PARALLEL, show_progress_bar=True)",
    )


def edit_stage_02_00(nb_path: Path) -> None:
    print(f"[02_ssl/00_generate_policy_runs.ipynb]")
    _ensure_import_first_cell(nb_path, ["N_LHS_SCHEDULES"])
    _replace_in_cell(
        nb_path,
        cell_idx=1,
        old="K = 60\n",
        new="K = N_LHS_SCHEDULES  # was 60; toggled by FAST_MODE in ml_models.lib.fast\n",
    )


def edit_stage_02_01(nb_path: Path) -> None:
    print(f"[02_ssl/01_pretrain.ipynb]")
    _ensure_import_first_cell(nb_path, ["PRETRAIN_EPOCHS"])
    _replace_in_cell(
        nb_path,
        cell_idx=1,
        old="    epochs: int = 20\n",
        new="    epochs: int = PRETRAIN_EPOCHS  # was 20; toggled by FAST_MODE\n",
    )


def edit_stage_02_02(nb_path: Path) -> None:
    print(f"[02_ssl/02_finetune_rul.ipynb]")
    _ensure_import_first_cell(nb_path, ["FINETUNE_EPOCHS"])
    _replace_in_cell(
        nb_path,
        cell_idx=4,
        old="    epochs: int = 3\n",
        new="    epochs: int = FINETUNE_EPOCHS  # was 3; toggled by FAST_MODE\n",
    )


def edit_stage_02_03(nb_path: Path) -> None:
    print(f"[02_ssl/03_surrogate_search.ipynb]")
    _ensure_import_first_cell(nb_path, ["SURROGATE_OPTUNA_TRIALS", "PARALLEL"])
    _replace_in_cell(
        nb_path,
        cell_idx=5,
        old="study.optimize(surrogate_objective, n_trials=500, show_progress_bar=True)",
        new="study.optimize(surrogate_objective, n_trials=SURROGATE_OPTUNA_TRIALS, n_jobs=PARALLEL, show_progress_bar=True)  # was n_trials=500, n_jobs=1",
    )


def edit_stage_03_00(nb_path: Path) -> None:
    print(f"[03_rl+ssl/00_setup_and_sanity.ipynb]")
    _ensure_import_first_cell(nb_path, ["SANITY_TRIALS"])
    _replace_in_cell(
        nb_path,
        cell_idx=3,
        old="N_TRIALS = 100\n",
        new="N_TRIALS = SANITY_TRIALS  # was 100; toggled by FAST_MODE\n",
    )


def edit_stage_03_01(nb_path: Path) -> None:
    print(f"[03_rl+ssl/01_train_ppo.ipynb]")
    _ensure_import_first_cell(nb_path, ["BANDIT_PPO_TIMESTEPS"])
    _replace_in_cell(
        nb_path,
        cell_idx=2,
        old="    total_timesteps=2_000,\n",
        new="    total_timesteps=BANDIT_PPO_TIMESTEPS,  # was 2_000; toggled by FAST_MODE\n",
    )


def edit_stage_03_04(nb_path: Path) -> None:
    print(f"[03_rl+ssl/04_per_tick_recurrent_ppo.ipynb]")
    _ensure_import_first_cell(nb_path, ["PERTICK_TIMESTEPS", "PERTICK_SEEDS"])
    _replace_in_cell(
        nb_path,
        cell_idx=1,
        old="    total_timesteps=20_000,    # ≈ 28 days of simulator time per env at n_steps=180\n",
        new="    total_timesteps=PERTICK_TIMESTEPS,    # was 20_000; toggled by FAST_MODE\n",
    )
    _replace_in_cell(
        nb_path,
        cell_idx=3,
        old="    seeds=(0, 1, 2),\n",
        new="    seeds=PERTICK_SEEDS,  # was (0, 1, 2); toggled by FAST_MODE\n",
    )


# -------------------------------------------------------------------- main

def main() -> int:
    edits: list[tuple[str, Callable[[Path], None]]] = [
        ("ml_models/01_baseline/search.ipynb", edit_stage_01),
        ("ml_models/02_ssl/00_generate_policy_runs.ipynb", edit_stage_02_00),
        ("ml_models/02_ssl/01_pretrain.ipynb", edit_stage_02_01),
        ("ml_models/02_ssl/02_finetune_rul.ipynb", edit_stage_02_02),
        ("ml_models/02_ssl/03_surrogate_search.ipynb", edit_stage_02_03),
        ("ml_models/03_rl+ssl/00_setup_and_sanity.ipynb", edit_stage_03_00),
        ("ml_models/03_rl+ssl/01_train_ppo.ipynb", edit_stage_03_01),
        ("ml_models/03_rl+ssl/04_per_tick_recurrent_ppo.ipynb", edit_stage_03_04),
    ]
    for rel, fn in edits:
        nb_path = ROOT / rel
        if not nb_path.exists():
            sys.stderr.write(f"FAIL: {nb_path} not found\n")
            return 1
        fn(nb_path)
    print("\nAll notebooks edited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
