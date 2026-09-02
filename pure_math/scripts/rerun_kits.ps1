# Re-runs Stage 5 (expand-ko-kits with its default flags) for the given combat levels and re-exports the viewer data.
# Needs Stage 3's resolved-survivors-cb<level>.csv and resolved-screen-cb<level>.json in outputs\cb<level>-rust\.
# Run from the repository root (the script resolves the root from its own path and changes to it)
# after `cargo build --release` in pure_math\ has produced pure_math\target\release\pure_math.exe:
#   powershell -File pure_math\scripts\rerun_kits.ps1                 (combat 40 only, the default)
#   powershell -File pure_math\scripts\rerun_kits.ps1 -Levels 30,40   (include combat 30 again)
# Outputs: outputs\cb<level>-rust\kits-cb<level>.csv and kits-cb<level>.json, then whatever
# viewer\scripts\export_build_data.py <level> writes for the viewer.
param([string]$Levels = '40')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$exe = Join-Path $root 'pure_math\target\release\pure_math.exe'
$sw = [System.Diagnostics.Stopwatch]::StartNew()
foreach ($level in ($Levels -split ',' | ForEach-Object { [int]$_ })) {
    $out = "outputs\cb$level-rust"
    $tag = "cb$level"
    Write-Host ("[{0,7:N1}s] expand-ko-kits cb{1}" -f $sw.Elapsed.TotalSeconds, $level)
    & $exe expand-ko-kits rulesets\osrs-f2p-v1 "$out\resolved-survivors-$tag.csv" "--screen-report=$out\resolved-screen-$tag.json" "--kits-output=$out\kits-$tag.csv" "--report-output=$out\kits-$tag.json"
    if ($LASTEXITCODE -ne 0) { throw "expand-ko-kits cb$level failed with exit $LASTEXITCODE" }
    Write-Host ("[{0,7:N1}s] export viewer data cb{1}" -f $sw.Elapsed.TotalSeconds, $level)
    Set-Location (Join-Path $root 'viewer')
    python scripts\export_build_data.py $level
    if ($LASTEXITCODE -ne 0) { throw "export cb$level failed with exit $LASTEXITCODE" }
    Set-Location $root
}
Write-Host ("[{0,7:N1}s] done" -f $sw.Elapsed.TotalSeconds)
