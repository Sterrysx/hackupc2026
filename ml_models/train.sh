#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  BOLD=$'\033[1m'
  DIM=$'\033[2m'
  GREEN=$'\033[32m'
  BLUE=$'\033[34m'
  YELLOW=$'\033[33m'
  CYAN=$'\033[36m'
  MAGENTA=$'\033[35m'
  RED=$'\033[31m'
  RESET=$'\033[0m'
else
  BOLD=""
  DIM=""
  GREEN=""
  BLUE=""
  YELLOW=""
  CYAN=""
  MAGENTA=""
  RED=""
  RESET=""
fi

NOTEBOOK_TIMEOUT="${NOTEBOOK_TIMEOUT:--1}"
CACHE_FILE="${TRAIN_TIMINGS_CACHE:-${ROOT_DIR}/.train_timings.json}"

DRY_RUN=0
USE_CACHE=1
FAST_MODE_FLAG=0
TRAIN_PARALLEL_FLAG=""

STAGE_0_NOTEBOOKS=(
  "ml_models/00_eda/eda_fleet_baseline.ipynb"
)

STAGE_1_NOTEBOOKS=(
  "ml_models/01_baseline/search.ipynb"
)

STAGE_2_NOTEBOOKS=(
  "ml_models/02_ssl/00_generate_policy_runs.ipynb"
  "ml_models/02_ssl/01_pretrain.ipynb"
  "ml_models/02_ssl/02_finetune_rul.ipynb"
  "ml_models/02_ssl/03_surrogate_search.ipynb"
)

STAGE_3_NOTEBOOKS=(
  "ml_models/03_rl+ssl/00_setup_and_sanity.ipynb"
  "ml_models/03_rl+ssl/01_train_ppo.ipynb"
  "ml_models/03_rl+ssl/02_eval_test.ipynb"
  "ml_models/03_rl+ssl/03_compare.ipynb"
  "ml_models/03_rl+ssl/04_per_tick_recurrent_ppo.ipynb"
)

STAGE_4_NOTEBOOKS=(
  "ml_models/04/results/compare_01_02_03.ipynb"
)

# Hardcoded fallbacks used when no cache exists (calibrated for Ryzen 9 9900X
# + 2x RTX 3090, CUDA torch wheel). The fast-mode column assumes --fast and
# --n-parallel ~= half of CPU count. First successful run replaces these via
# the persisted cache.
default_eta_seconds() {
  if (( FAST_MODE_FLAG == 1 )); then
    case "$1" in
      "ml_models/00_eda/eda_fleet_baseline.ipynb")             echo 45     ;;
      "ml_models/01_baseline/search.ipynb")                    echo 1200   ;;
      "ml_models/02_ssl/00_generate_policy_runs.ipynb")        echo 600    ;;
      "ml_models/02_ssl/01_pretrain.ipynb")                    echo 900    ;;
      "ml_models/02_ssl/02_finetune_rul.ipynb")                echo 480    ;;
      "ml_models/02_ssl/03_surrogate_search.ipynb")            echo 360    ;;
      "ml_models/03_rl+ssl/00_setup_and_sanity.ipynb")         echo 600    ;;
      "ml_models/03_rl+ssl/01_train_ppo.ipynb")                echo 2400   ;;
      "ml_models/03_rl+ssl/02_eval_test.ipynb")                echo 900    ;;
      "ml_models/03_rl+ssl/03_compare.ipynb")                  echo 60     ;;
      "ml_models/03_rl+ssl/04_per_tick_recurrent_ppo.ipynb")   echo 5400   ;;
      "ml_models/04/results/compare_01_02_03.ipynb")           echo 60     ;;
      *)                                                       echo 300    ;;
    esac
  else
    case "$1" in
      "ml_models/00_eda/eda_fleet_baseline.ipynb")             echo 45     ;;
      "ml_models/01_baseline/search.ipynb")                    echo 9000   ;;
      "ml_models/02_ssl/00_generate_policy_runs.ipynb")        echo 5400   ;;
      "ml_models/02_ssl/01_pretrain.ipynb")                    echo 2100   ;;
      "ml_models/02_ssl/02_finetune_rul.ipynb")                echo 720    ;;
      "ml_models/02_ssl/03_surrogate_search.ipynb")            echo 1500   ;;
      "ml_models/03_rl+ssl/00_setup_and_sanity.ipynb")         echo 1800   ;;
      "ml_models/03_rl+ssl/01_train_ppo.ipynb")                echo 5400   ;;
      "ml_models/03_rl+ssl/02_eval_test.ipynb")                echo 1500   ;;
      "ml_models/03_rl+ssl/03_compare.ipynb")                  echo 60     ;;
      "ml_models/03_rl+ssl/04_per_tick_recurrent_ppo.ipynb")   echo 19800  ;;
      "ml_models/04/results/compare_01_02_03.ipynb")           echo 60     ;;
      *)                                                       echo 600    ;;
    esac
  fi
}

usage() {
  cat <<'EOF'
Usage:
  ./train.sh                  Run all stages: 00, 01, 02, 03, 04
  ./train.sh all              Run all stages
  ./train.sh 0|1|2|3|4        Run a single stage
  ./train.sh from N           Run stage N through 4 (resume after a crash)
  ./train.sh --fast           Halve hyperparameters for a fast first-pass run
                              (sets FAST_MODE=1 in the notebook env)
  ./train.sh --n-parallel N   Number of parallel workers for Optuna and the
                              per-printer simulator loops (sets TRAIN_PARALLEL=N)
  ./train.sh --dry-run        Print plan + ETAs and exit without executing
  ./train.sh --no-cache       Ignore the timings cache; use hardcoded defaults

Environment:
  NOTEBOOK_TIMEOUT=-1         Notebook cell timeout in seconds; -1 disables
  NO_COLOR=1                  Disable ANSI colors
  TRAIN_TIMINGS_CACHE=<path>  Override timings cache location
  FAST_MODE=1                 Same effect as --fast
  TRAIN_PARALLEL=N            Same effect as --n-parallel N

PowerShell users: invoke via the train.ps1 wrapper or call bash explicitly:
  bash ml_models/train.sh --dry-run
EOF
}

line() {
  printf '%*s\n' "${COLUMNS:-88}" '' | tr ' ' "${1:-=}"
}

human_duration() {
  local seconds="$1"
  if (( seconds < 0 )); then seconds=0; fi
  local h=$((seconds / 3600))
  local m=$(((seconds % 3600) / 60))
  local s=$((seconds % 60))
  if (( h > 0 )); then
    printf '%dh %02dm' "$h" "$m"
  elif (( m > 0 )); then
    printf '%dm %02ds' "$m" "$s"
  else
    printf '%ds' "$s"
  fi
}

stage_title() {
  case "$1" in
    0) printf 'Stage 00 · Exploratory data analysis' ;;
    1) printf 'Stage 01 · Baseline tau search' ;;
    2) printf 'Stage 02 · SSL/RUL surrogate pipeline' ;;
    3) printf 'Stage 03 · RL + SSL maintenance policy' ;;
    4) printf 'Stage 04 · Results comparison' ;;
  esac
}

stage_notebooks() {
  case "$1" in
    0) printf '%s\n' "${STAGE_0_NOTEBOOKS[@]}" ;;
    1) printf '%s\n' "${STAGE_1_NOTEBOOKS[@]}" ;;
    2) printf '%s\n' "${STAGE_2_NOTEBOOKS[@]}" ;;
    3) printf '%s\n' "${STAGE_3_NOTEBOOKS[@]}" ;;
    4) printf '%s\n' "${STAGE_4_NOTEBOOKS[@]}" ;;
  esac
}

# Read median of (up to) the last 3 timings from the cache.
# Prints the integer seconds, or empty string if missing/disabled.
cache_get_eta() {
  local key="$1"
  if (( USE_CACHE == 0 )) || [[ ! -f "$CACHE_FILE" ]]; then
    return 0
  fi
  uv run python - "$key" "$CACHE_FILE" <<'PY' 2>/dev/null || true
import json, statistics, sys
key, path = sys.argv[1], sys.argv[2]
try:
    with open(path) as f:
        data = json.load(f)
except (OSError, json.JSONDecodeError):
    sys.exit(0)
seq = data.get("timings", {}).get(key, [])
if seq:
    print(int(statistics.median(seq[-3:])))
PY
}

cache_save_timing() {
  local key="$1" secs="$2"
  if (( USE_CACHE == 0 )); then
    return 0
  fi
  uv run python - "$key" "$secs" "$CACHE_FILE" <<'PY' 2>/dev/null || true
import datetime, json, os, sys
key, secs, path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
data = {"version": 1, "timings": {}}
if os.path.exists(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
timings = data.setdefault("timings", {})
seq = list(timings.get(key, []))
seq.append(secs)
timings[key] = seq[-3:]
data["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
data["version"] = 1
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PY
}

eta_seconds_for() {
  local nb="$1" cached
  cached="$(cache_get_eta "$nb")"
  if [[ -n "$cached" ]]; then
    printf '%s' "$cached"
  else
    default_eta_seconds "$nb"
  fi
}

eta_source_label() {
  if (( USE_CACHE == 0 )); then
    printf 'default estimates (--no-cache)'
  elif [[ -f "$CACHE_FILE" ]]; then
    printf 'cache + defaults'
  else
    printf 'default estimates — first run on this machine'
  fi
}

stage_eta_seconds() {
  local stage="$1" total=0 nb eta
  while IFS= read -r nb; do
    [[ -z "$nb" ]] && continue
    eta="$(eta_seconds_for "$nb")"
    total=$((total + eta))
  done < <(stage_notebooks "$stage")
  printf '%s' "$total"
}

hardware_fingerprint() {
  local cpu_count gpu_info cuda_info smi
  cpu_count="$(nproc 2>/dev/null || echo '?')"

  smi="$(command -v nvidia-smi 2>/dev/null || true)"
  if [[ -z "$smi" && -x "/c/Windows/System32/nvidia-smi.exe" ]]; then
    smi="/c/Windows/System32/nvidia-smi.exe"
  fi
  if [[ -n "$smi" ]]; then
    gpu_info="$("$smi" --query-gpu=name --format=csv,noheader 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  fi
  if [[ -z "${gpu_info:-}" ]]; then
    gpu_info="no NVIDIA GPU detected"
  fi
  cuda_info="$(nvcc --version 2>/dev/null | grep -oE 'release [0-9]+\.[0-9]+' | head -1 || true)"
  if [[ -z "$cuda_info" ]]; then
    cuda_info="CUDA: not on PATH"
  fi
  printf '%s logical CPUs · GPUs: %s · %s' "$cpu_count" "$gpu_info" "$cuda_info"
}

run_notebook() {
  local notebook="$1"
  local stage="$2"
  local idx_in_stage="$3"
  local total_in_stage="$4"
  local idx_overall="$5"
  local total_overall="$6"
  local remaining_budget_var="$7"

  if [[ ! -f "$notebook" ]]; then
    printf '%sMissing notebook:%s %s\n' "$RED" "$RESET" "$notebook" >&2
    return 1
  fi

  local eta
  eta="$(eta_seconds_for "$notebook")"

  printf '\n%s[Stage %s · %d/%d]%s %s%s%s\n' \
    "$CYAN" "$stage" "$idx_in_stage" "$total_in_stage" "$RESET" \
    "$BOLD" "$notebook" "$RESET"
  printf '%s   est ~%s · timeout=%s%s\n' \
    "$DIM" "$(human_duration "$eta")" "$NOTEBOOK_TIMEOUT" "$RESET"

  if (( DRY_RUN == 1 )); then
    printf '%s   (dry-run — skipped)%s\n' "$DIM" "$RESET"
    return 0
  fi

  printf '%s   ▶ starting at %s%s\n' "$DIM" "$(date +%H:%M:%S)" "$RESET"

  local started ended elapsed
  started="$(date +%s)"
  # Invoke nbconvert directly via `python -m nbconvert`. On Windows the
  # `jupyter` CLI dispatches to `jupyter-nbconvert.exe`, which some WDAC /
  # AppLocker policies block (WinError 4551). Going through nbconvert's
  # own module entry point avoids that .exe shim entirely.
  uv run python -m nbconvert \
    --to notebook \
    --execute \
    --inplace \
    --ExecutePreprocessor.kernel_name=python3 \
    --ExecutePreprocessor.timeout="${NOTEBOOK_TIMEOUT}" \
    "$notebook"
  ended="$(date +%s)"
  elapsed=$((ended - started))

  cache_save_timing "$notebook" "$elapsed"

  # Decrement the caller's remaining budget by the actual elapsed (clipped 0).
  local remaining
  remaining="$(eval echo "\${$remaining_budget_var}")"
  remaining=$((remaining - elapsed))
  if (( remaining < 0 )); then remaining=0; fi
  eval "$remaining_budget_var=$remaining"

  printf '%s   ✓ done in %s · run progress %d/%d · remaining ~%s%s\n' \
    "$GREEN" "$(human_duration "$elapsed")" \
    "$idx_overall" "$total_overall" \
    "$(human_duration "$remaining")" "$RESET"
}

run_stage() {
  local stage="$1"
  local stage_idx="$2"
  local total_stages="$3"
  local idx_overall_var="$4"
  local total_overall="$5"
  local remaining_budget_var="$6"

  local -a notebooks=()
  while IFS= read -r nb; do
    [[ -z "$nb" ]] && continue
    notebooks+=("$nb")
  done < <(stage_notebooks "$stage")

  if (( ${#notebooks[@]} == 0 )); then
    printf '%sUnknown stage:%s %s\n' "$RED" "$RESET" "$stage" >&2
    return 1
  fi

  local stage_eta
  stage_eta="$(stage_eta_seconds "$stage")"

  printf '\n%s' "$BOLD"
  line '='
  printf '%sStage %d/%d%s — %s    %d notebook(s) · est ~%s\n' \
    "$MAGENTA" "$stage_idx" "$total_stages" "$RESET$BOLD" \
    "$(stage_title "$stage")" \
    "${#notebooks[@]}" "$(human_duration "$stage_eta")"
  line '='
  printf '%s' "$RESET"

  # Use a renamed local so we don't shadow the outer-scope variable that
  # idx_overall_var points to (set -u + local-without-init = unbound read).
  local i=1 cur_overall=0
  for nb in "${notebooks[@]}"; do
    cur_overall="$(eval echo "\${$idx_overall_var}")"
    cur_overall=$((cur_overall + 1))
    eval "$idx_overall_var=$cur_overall"
    run_notebook "$nb" "$stage" "$i" "${#notebooks[@]}" \
      "$cur_overall" "$total_overall" "$remaining_budget_var"
    i=$((i + 1))
  done
}

print_top_banner() {
  local stages_str="$1" total_stages="$2" total_notebooks="$3" total_eta="$4"

  printf '%s' "$BOLD"
  line '#'
  printf 'HackUPC 2026 training runner\n'
  line '#'
  printf '%s' "$RESET"
  printf 'Target          : %s%s%s\n' "$YELLOW" "${TARGET_LABEL:-all}" "$RESET"
  printf 'Stages          : %s (%d stages, %d notebooks)\n' \
    "$stages_str" "$total_stages" "$total_notebooks"
  printf 'Estimated total : ~%s   %s(%s)%s\n' \
    "$(human_duration "$total_eta")" "$DIM" "$(eta_source_label)" "$RESET"
  printf 'Hardware        : %s\n' "$(hardware_fingerprint)"
  printf 'Notebook timeout: %s\n' "$NOTEBOOK_TIMEOUT"
  if (( FAST_MODE_FLAG == 1 )); then
    printf 'Mode            : %sFAST%s (smaller hyperparameters; FAST_MODE=1)\n' "$YELLOW" "$RESET"
  else
    printf 'Mode            : FULL (production hyperparameters)\n'
  fi
  if [[ -n "${TRAIN_PARALLEL:-}" ]]; then
    printf 'Parallel workers: %s (TRAIN_PARALLEL)\n' "$TRAIN_PARALLEL"
  else
    printf 'Parallel workers: auto (notebooks pick %sml_models.lib.fast.PARALLEL%s)\n' "$DIM" "$RESET"
  fi
  if (( USE_CACHE == 1 )); then
    if [[ -f "$CACHE_FILE" ]]; then
      printf 'Timings cache   : %s%s%s\n' "$DIM" "$CACHE_FILE" "$RESET"
    else
      printf 'Timings cache   : %s%s (will be created)%s\n' "$DIM" "$CACHE_FILE" "$RESET"
    fi
  else
    printf 'Timings cache   : %s(disabled via --no-cache)%s\n' "$DIM" "$RESET"
  fi
  if (( DRY_RUN == 1 )); then
    printf '%sDRY RUN — no notebooks will execute%s\n' "$YELLOW" "$RESET"
  fi
}

main() {
  local -a positional=()
  local -a all_args=("$@")
  local i=0 arg
  while (( i < ${#all_args[@]} )); do
    arg="${all_args[$i]}"
    case "$arg" in
      --dry-run)  DRY_RUN=1 ;;
      --no-cache) USE_CACHE=0 ;;
      --fast)     FAST_MODE_FLAG=1 ;;
      --n-parallel)
        i=$((i + 1))
        if (( i >= ${#all_args[@]} )); then
          printf '%s--n-parallel requires an integer argument%s\n' "$RED" "$RESET" >&2
          exit 2
        fi
        TRAIN_PARALLEL_FLAG="${all_args[$i]}"
        ;;
      -h|--help|help) usage; exit 0 ;;
      *)          positional+=("$arg") ;;
    esac
    i=$((i + 1))
  done

  # Env vars also enable the same modes (so train.ps1 and CI can set them).
  if [[ "${FAST_MODE:-0}" == "1" ]]; then
    FAST_MODE_FLAG=1
  fi
  if [[ -n "${TRAIN_PARALLEL:-}" && -z "$TRAIN_PARALLEL_FLAG" ]]; then
    TRAIN_PARALLEL_FLAG="$TRAIN_PARALLEL"
  fi

  # Propagate to nbconvert subprocesses (read by ml_models/lib/fast.py).
  if (( FAST_MODE_FLAG == 1 )); then
    export FAST_MODE=1
    # Use a separate timings cache for fast mode so we don't pollute the
    # cache with mixed timings.
    if [[ -z "${TRAIN_TIMINGS_CACHE:-}" ]]; then
      CACHE_FILE="${ROOT_DIR}/.train_timings.fast.json"
    fi
  fi
  if [[ -n "$TRAIN_PARALLEL_FLAG" ]]; then
    export TRAIN_PARALLEL="$TRAIN_PARALLEL_FLAG"
  fi

  local target="${positional[0]:-all}"
  local from_stage=""

  if [[ "$target" == "from" ]]; then
    if (( ${#positional[@]} < 2 )); then
      printf 'from <N> requires a stage number\n' >&2
      usage >&2
      exit 2
    fi
    from_stage="${positional[1]}"
  elif (( ${#positional[@]} > 1 )); then
    usage >&2
    exit 2
  fi

  local -a stages=()
  case "$target" in
    all|"")     stages=(0 1 2 3 4) ;;
    0|00)       stages=(0) ;;
    1|01)       stages=(1) ;;
    2|02)       stages=(2) ;;
    3|03)       stages=(3) ;;
    4|04)       stages=(4) ;;
    from)
      case "$from_stage" in
        0|00) stages=(0 1 2 3 4) ;;
        1|01) stages=(1 2 3 4)   ;;
        2|02) stages=(2 3 4)     ;;
        3|03) stages=(3 4)       ;;
        4|04) stages=(4)         ;;
        *)    usage >&2; exit 2  ;;
      esac
      ;;
    *) usage >&2; exit 2 ;;
  esac

  TARGET_LABEL="$target"
  if [[ "$target" == "from" ]]; then
    TARGET_LABEL="from $from_stage"
  fi

  local total_eta=0 total_notebooks=0 stage
  for stage in "${stages[@]}"; do
    total_eta=$((total_eta + $(stage_eta_seconds "$stage")))
    while IFS= read -r nb; do
      [[ -z "$nb" ]] && continue
      total_notebooks=$((total_notebooks + 1))
    done < <(stage_notebooks "$stage")
  done

  print_top_banner "${stages[*]}" "${#stages[@]}" "$total_notebooks" "$total_eta"

  if (( DRY_RUN == 1 )); then
    local stage_idx=1 stage
    for stage in "${stages[@]}"; do
      printf '\n%s' "$BOLD"
      line '-'
      printf '%sStage %d/%d%s — %s    est ~%s\n' \
        "$MAGENTA" "$stage_idx" "${#stages[@]}" "$RESET$BOLD" \
        "$(stage_title "$stage")" \
        "$(human_duration "$(stage_eta_seconds "$stage")")"
      line '-'
      printf '%s' "$RESET"
      local -a dry_nbs=()
      while IFS= read -r nb; do
        [[ -z "$nb" ]] && continue
        dry_nbs+=("$nb")
      done < <(stage_notebooks "$stage")
      local i=1 nb
      for nb in "${dry_nbs[@]}"; do
        printf '   %s[Stage %s · %d/%d]%s %s   %s(est ~%s)%s\n' \
          "$CYAN" "$stage" "$i" "${#dry_nbs[@]}" "$RESET" "$nb" \
          "$DIM" "$(human_duration "$(eta_seconds_for "$nb")")" "$RESET"
        i=$((i + 1))
      done
      stage_idx=$((stage_idx + 1))
    done
    printf '\n%sDry run complete.%s\n' "$GREEN" "$RESET"
    exit 0
  fi

  local started ended idx_overall=0 remaining_budget="$total_eta"
  started="$(date +%s)"

  local stage_idx=1
  for stage in "${stages[@]}"; do
    run_stage "$stage" "$stage_idx" "${#stages[@]}" \
      idx_overall "$total_notebooks" remaining_budget
    stage_idx=$((stage_idx + 1))
  done

  ended="$(date +%s)"
  printf '\n%s' "$BOLD"
  line '#'
  printf '%sAll requested training stages completed in %s%s\n' \
    "$GREEN" "$(human_duration "$((ended - started))")" "$RESET"
  line '#'
  printf '%s' "$RESET"
}

main "$@"
