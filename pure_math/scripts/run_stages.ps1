# Runs a subset of pipeline Stages 2-5 for one combat level, reading and writing outputs\cb<level>-rust\.
# Every stage reads the previous stage's files, so those must already exist (run_pipeline.ps1 makes them all).
# Run from the repository root (the script resolves the root from its own path and changes to it)
# after `cargo build --release` in pure_math\ has produced pure_math\target\release\pure_math.exe:
#   powershell -File pure_math\scripts\run_stages.ps1 -CombatLevel 40 -Stages 2,3,4
#   powershell -File pure_math\scripts\run_stages.ps1 [-CombatLevel 40] [-Stages '2,3,4,5'] [-MaxKoOptions 4] [-MaxBuilds 0] [-Magic 1]
#                                                      [-CompletedQuests 'Dragon Slayer I'] [-KeepDefensive 'true'] [-Threads 0]
#                                                      [-OutDir outputs\cb40-rust-1def]   (read and write another folder)
# Outputs (<tag> = cb<level>): Stage 2 gear-matrix-<tag>-offence.csv; Stage 3 resolved-survivors-<tag>.csv and
# resolved-screen-<tag>.json; Stage 4 resolved-ranked-<tag>.csv and resolved-ranking-<tag>.json;
# Stage 5 kits-<tag>.csv and kits-<tag>.json.
param(
    [int]$CombatLevel = 40,
    [string]$Stages = '2,3,4,5',
    [int]$MaxKoOptions = 4,
    [int]$MaxBuilds = 0,
    [int]$Magic = 1,
    [string]$CompletedQuests = 'Dragon Slayer I',
    [string]$KeepDefensive = 'true',
    [int]$Threads = 0,
    [string]$OutDir = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$exe = Join-Path $root 'pure_math\target\release\pure_math.exe'
$ruleset = 'rulesets\osrs-f2p-v1'
$out = if ($OutDir) { $OutDir } else { "outputs\cb$CombatLevel-rust" }
$tag = "cb$CombatLevel"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
function Stage($name, $arguments) {
    Write-Host ("[{0,7:N1}s] {1}" -f $sw.Elapsed.TotalSeconds, $name)
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$name failed with exit $LASTEXITCODE" }
    Write-Host ("[{0,7:N1}s] {1} done" -f $sw.Elapsed.TotalSeconds, $name)
}
$wanted = $Stages -split ',' | ForEach-Object { [int]$_ }
if ($wanted -contains 2) {
    Stage 'export-account-gear-matrix' @('export-account-gear-matrix', $ruleset, "$out\accounts-ranking.csv",
        '--kit-mode=offence_pareto', "--keep-defensive=$KeepDefensive", "--completed-quests=$CompletedQuests", "--csv-output=$out\gear-matrix-$tag-offence.csv")
}
if ($wanted -contains 3) {
    Stage 'screen-resolved-gear-matrix' @('screen-resolved-gear-matrix', $ruleset, "$out\gear-matrix-$tag-offence.csv",
        "--manifest-output=$out\resolved-survivors-$tag.csv", "--report-output=$out\resolved-screen-$tag.json")
}
if ($wanted -contains 4) {
    Stage 'rank-resolved-survivors' @('rank-resolved-survivors', $ruleset, "$out\resolved-survivors-$tag.csv",
        "--ranked-output=$out\resolved-ranked-$tag.csv", "--report-output=$out\resolved-ranking-$tag.json")
}
if ($wanted -contains 5) {
    $kitArgs = @('expand-ko-kits', $ruleset, "$out\resolved-survivors-$tag.csv",
        "--screen-report=$out\resolved-screen-$tag.json", "--kits-output=$out\kits-$tag.csv", "--report-output=$out\kits-$tag.json",
        "--max-ko-options=$MaxKoOptions", "--max-builds=$MaxBuilds", "--magic=$Magic")
    if ($Threads -gt 0) { $kitArgs += "--threads=$Threads" }
    Stage 'expand-ko-kits' $kitArgs
}
Write-Host ("[{0,7:N1}s] done" -f $sw.Elapsed.TotalSeconds)
