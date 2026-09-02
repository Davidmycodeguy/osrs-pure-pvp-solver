# Runs Stages 1-5 of the Rust pipeline for one combat level into outputs\cb<level>-rust\.
# Run from the repository root (the script resolves the root from its own path and changes to it)
# after `cargo build --release` in pure_math\ has produced pure_math\target\release\pure_math.exe:
#   powershell -File pure_math\scripts\run_pipeline.ps1 -CombatLevel 40
#   powershell -File pure_math\scripts\run_pipeline.ps1 [-CombatLevel 40] [-DefenceLevels '1'] [-MaxKoOptions 4]
#                                                        [-CompletedQuests 'Dragon Slayer I'] [-KeepDefensive 'true'] [-Threads 0]
# Defaults to the classic 1-Defence pure search; pass a list such as '1,5,10,15,20,30,40' to open Defence up.
# Every level '1-40' at once produces 133,467 accounts and runs out of memory at Stage 5; see docs/pipeline.md.
# -Threads 0 lets expand-ko-kits choose its own worker count.
# Outputs, all under outputs\cb<level>-rust\ with <tag> = cb<level>:
#   Stage 1  accounts-ranking.csv, accounts-full.csv, account-frontier.json
#   Stage 2  gear-matrix-<tag>-offence.csv
#   Stage 3  resolved-survivors-<tag>.csv, resolved-screen-<tag>.json
#   Stage 4  resolved-ranked-<tag>.csv, resolved-ranking-<tag>.json
#   Stage 5  kits-<tag>.csv, kits-<tag>.json
param(
    [int]$CombatLevel = 40,
    [string]$DefenceLevels = '1',
    [int]$MaxKoOptions = 4,
    [string]$CompletedQuests = 'Dragon Slayer I',
    [string]$KeepDefensive = 'true',
    [int]$Threads = 0
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$exe = Join-Path $root 'pure_math\target\release\pure_math.exe'
$ruleset = 'rulesets\osrs-f2p-v1'
$out = "outputs\cb$CombatLevel-rust"
New-Item -ItemType Directory -Force $out | Out-Null
$tag = "cb$CombatLevel"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
function Stage($name, $arguments) {
    Write-Host ("[{0,7:N1}s] {1}" -f $sw.Elapsed.TotalSeconds, $name)
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$name failed with exit $LASTEXITCODE" }
}
Stage 'account-frontier' @('account-frontier', $ruleset, "--combat-level=$CombatLevel", "--defence-levels=$DefenceLevels",
    "--ranking-output=$out\accounts-ranking.csv", "--full-output=$out\accounts-full.csv", "--report-output=$out\account-frontier.json")
Stage 'export-account-gear-matrix' @('export-account-gear-matrix', $ruleset, "$out\accounts-ranking.csv",
    '--kit-mode=offence_pareto', "--keep-defensive=$KeepDefensive", "--completed-quests=$CompletedQuests", "--csv-output=$out\gear-matrix-$tag-offence.csv")
Stage 'screen-resolved-gear-matrix' @('screen-resolved-gear-matrix', $ruleset, "$out\gear-matrix-$tag-offence.csv",
    "--manifest-output=$out\resolved-survivors-$tag.csv", "--report-output=$out\resolved-screen-$tag.json")
Stage 'rank-resolved-survivors' @('rank-resolved-survivors', $ruleset, "$out\resolved-survivors-$tag.csv",
    "--ranked-output=$out\resolved-ranked-$tag.csv", "--report-output=$out\resolved-ranking-$tag.json")
$kitArgs = @('expand-ko-kits', $ruleset, "$out\resolved-survivors-$tag.csv",
    "--screen-report=$out\resolved-screen-$tag.json", "--kits-output=$out\kits-$tag.csv", "--report-output=$out\kits-$tag.json",
    "--max-ko-options=$MaxKoOptions")
if ($Threads -gt 0) { $kitArgs += "--threads=$Threads" }
Stage 'expand-ko-kits' $kitArgs
Write-Host ("[{0,7:N1}s] done" -f $sw.Elapsed.TotalSeconds)
