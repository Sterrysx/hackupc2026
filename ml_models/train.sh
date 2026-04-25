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
  RED=$'\033[31m'
  RESET=$'\033[0m'
else
  BOLD=""
  DIM=""
  GREEN=""
  BLUE=""
  YELLOW=""
  RED=""
  RESET=""
fi

NOTEBOOK_TIMEOUT="${NOTEBOOK_TIMEOUT:--1}"

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

usage() {
  cat <<'EOF'
Usage:
  ./train.sh        Run all stages: 00, 01, 02, 03, then 04
  ./train.sh all    Run all stages
  ./train.sh 0      Run Stage 00 EDA notebook
  ./train.sh 1      Run Stage 01 baseline notebook
  ./train.sh 2      Run Stage 02 notebooks 00, 01, 02, 03
  ./train.sh 3      Run Stage 03 notebooks 00, 01, 02, 03, 04
  ./train.sh 4      Run Stage 04 results comparison notebook

Environment:
  NOTEBOOK_TIMEOUT=-1   Notebook cell timeout in seconds; -1 disables timeout.
  NO_COLOR=1            Disable ANSI colors.
EOF
}

line() {
  printf '%*s\n' "${COLUMNS:-88}" '' | tr ' ' "${1:-=}"
}

elapsed() {
  local seconds="$1"
  local h=$((seconds / 3600))
  local m=$(((seconds % 3600) / 60))
  local s=$((seconds % 60))
  if (( h > 0 )); then
    printf '%dh %02dm %02ds' "$h" "$m" "$s"
  elif (( m > 0 )); then
    printf '%dm %02ds' "$m" "$s"
  else
    printf '%ds' "$s"
  fi
}

stage_title() {
  case "$1" in
    0) printf 'Stage 00 - Exploratory data analysis' ;;
    1) printf 'Stage 01 - Baseline tau search' ;;
    2) printf 'Stage 02 - SSL/RUL surrogate pipeline' ;;
    3) printf 'Stage 03 - RL + SSL maintenance policy' ;;
    4) printf 'Stage 04 - Results comparison' ;;
  esac
}

run_notebook() {
  local notebook="$1"

  if [[ ! -f "$notebook" ]]; then
    printf '%sMissing notebook:%s %s\n' "$RED" "$RESET" "$notebook" >&2
    return 1
  fi

  printf '\n%s>>%s %s%s%s\n' "$BLUE" "$RESET" "$BOLD" "$notebook" "$RESET"
  printf '%s   timeout=%s, cwd=%s%s\n' "$DIM" "$NOTEBOOK_TIMEOUT" "$ROOT_DIR" "$RESET"

  local started ended
  started="$(date +%s)"
  uv run jupyter nbconvert \
    --to notebook \
    --execute \
    --inplace \
    --ExecutePreprocessor.kernel_name=python3 \
    --ExecutePreprocessor.timeout="${NOTEBOOK_TIMEOUT}" \
    "$notebook"
  ended="$(date +%s)"

  printf '%sOK%s Finished in %s\n' "$GREEN" "$RESET" "$(elapsed "$((ended - started))")"
}

run_stage() {
  local stage="$1"
  local -a notebooks=()

  case "$stage" in
    0)
      notebooks=("${STAGE_0_NOTEBOOKS[@]}")
      ;;
    1)
      notebooks=("${STAGE_1_NOTEBOOKS[@]}")
      ;;
    2)
      notebooks=("${STAGE_2_NOTEBOOKS[@]}")
      ;;
    3)
      notebooks=("${STAGE_3_NOTEBOOKS[@]}")
      ;;
    4)
      notebooks=("${STAGE_4_NOTEBOOKS[@]}")
      ;;
    *)
      printf '%sUnknown stage:%s %s\n' "$RED" "$RESET" "$stage" >&2
      return 1
      ;;
  esac

  printf '\n%s' "$BOLD"
  line '='
  printf '%s\n' "$(stage_title "$stage")"
  line '='
  printf '%s' "$RESET"
  printf '%s%d notebook(s)%s\n' "$DIM" "${#notebooks[@]}" "$RESET"

  local notebook
  for notebook in "${notebooks[@]}"; do
    run_notebook "$notebook"
  done
}

main() {
  local target="${1:-all}"
  local -a stages=()
  local started ended

  if (( $# > 1 )); then
    usage >&2
    exit 2
  fi

  case "$target" in
    -h|--help|help)
      usage
      exit 0
      ;;
    all|"")
      stages=(0 1 2 3 4)
      ;;
    0|00)
      stages=(0)
      ;;
    1|01)
      stages=(1)
      ;;
    2|02)
      stages=(2)
      ;;
    3|03)
      stages=(3)
      ;;
    4|04)
      stages=(4)
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac

  started="$(date +%s)"

  printf '%s' "$BOLD"
  line '#'
  printf 'HackUPC 2026 training runner\n'
  line '#'
  printf '%s' "$RESET"
  printf 'Target: %s%s%s\n' "$YELLOW" "$target" "$RESET"
  printf 'Stages: %s\n' "${stages[*]}"
  printf 'Notebook timeout: %s\n' "$NOTEBOOK_TIMEOUT"

  local stage
  for stage in "${stages[@]}"; do
    run_stage "$stage"
  done

  ended="$(date +%s)"
  printf '\n%s' "$BOLD"
  line '#'
  printf '%sAll requested training stages completed in %s%s\n' "$GREEN" "$(elapsed "$((ended - started))")" "$RESET"
  line '#'
  printf '%s' "$RESET"
}

main "$@"
