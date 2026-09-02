#!/usr/bin/env bash
# Runs Stages 1-5 of the Rust pipeline for one combat level into outputs/cb<level>-rust.
# Linux/macOS equivalent of run_pipeline.ps1. Run from anywhere; paths resolve against the repo root.
#
# Usage: pure_math/scripts/run_pipeline.sh [combat_level=40] [defence_levels=1] [max_ko_options=4] [threads=0]
#   defence_levels: "1" (the classic 1-Defence pure search, the default) or a list such as "1,5,10,15,20,30,40".
#   Every level "1-40" at once produces 133,467 accounts and runs out of memory at Stage 5; see docs/pipeline.md.
#   threads: 0 leaves two cores free (the binary's default).
set -euo pipefail

combat_level="${1:-40}"
defence_levels="${2:-1}"
max_ko_options="${3:-4}"
threads="${4:-0}"
completed_quests="${COMPLETED_QUESTS:-Dragon Slayer I}"
keep_defensive="${KEEP_DEFENSIVE:-true}"

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
exe="$root/pure_math/target/release/pure_math"
if [ ! -x "$exe" ]; then
  echo "building pure_math (release)..."
  (cd pure_math && cargo build --release)
fi

ruleset="rulesets/osrs-f2p-v1"
out="outputs/cb${combat_level}-rust"
tag="cb${combat_level}"
mkdir -p "$out"
start=$(date +%s)

stage() {
  local name="$1"; shift
  printf '[%7ss] %s\n' "$(( $(date +%s) - start ))" "$name"
  "$exe" "$@"
}

stage account-frontier account-frontier "$ruleset" "--combat-level=$combat_level" "--defence-levels=$defence_levels" \
  "--ranking-output=$out/accounts-ranking.csv" "--full-output=$out/accounts-full.csv" "--report-output=$out/account-frontier.json"
stage export-account-gear-matrix export-account-gear-matrix "$ruleset" "$out/accounts-ranking.csv" \
  "--kit-mode=offence_pareto" "--keep-defensive=$keep_defensive" "--completed-quests=$completed_quests" "--csv-output=$out/gear-matrix-$tag-offence.csv"
stage screen-resolved-gear-matrix screen-resolved-gear-matrix "$ruleset" "$out/gear-matrix-$tag-offence.csv" \
  "--manifest-output=$out/resolved-survivors-$tag.csv" "--report-output=$out/resolved-screen-$tag.json"
stage rank-resolved-survivors rank-resolved-survivors "$ruleset" "$out/resolved-survivors-$tag.csv" \
  "--ranked-output=$out/resolved-ranked-$tag.csv" "--report-output=$out/resolved-ranking-$tag.json"
kit_args=(expand-ko-kits "$ruleset" "$out/resolved-survivors-$tag.csv" "--screen-report=$out/resolved-screen-$tag.json"
  "--kits-output=$out/kits-$tag.csv" "--report-output=$out/kits-$tag.json" "--max-ko-options=$max_ko_options")
if [ "$threads" -gt 0 ]; then kit_args+=("--threads=$threads"); fi
stage expand-ko-kits "${kit_args[@]}"
printf '[%7ss] done -> %s\n' "$(( $(date +%s) - start ))" "$out"
