# Stage 3 (screen-resolved-gear-matrix) over gear-matrix chunks (memory-bounded), then concatenates the
# survivor manifests.  Expects the Stage 2 matrix pre-split into outputs\cb<level>-rust\chunks\gear-<n>.csv,
# each chunk with the header row; <n> becomes the chunk id.
# Run from the repository root (the script resolves the root from its own path and changes to it)
# after `cargo build --release` in pure_math\ has produced pure_math\target\release\pure_math.exe:
#   powershell -File pure_math\scripts\screen_chunks.ps1 -CombatLevel 40
# Outputs: chunks\survivors-<n>.csv and chunks\screen-<n>.json per chunk, the concatenated
# outputs\cb<level>-rust\resolved-survivors-cb<level>.csv, and chunks\screen-01.json copied to
# resolved-screen-cb<level>.json.
param([int]$CombatLevel = 40)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root
$exe = Join-Path $root 'pure_math\target\release\pure_math.exe'
$out = "outputs\cb$CombatLevel-rust"
$tag = "cb$CombatLevel"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$chunks = Get-ChildItem "$out\chunks\gear-*.csv" | Sort-Object Name
foreach ($chunk in $chunks) {
    $n = $chunk.BaseName.Substring(5)
    Write-Host ("[{0,7:N1}s] screen chunk {1}" -f $sw.Elapsed.TotalSeconds, $n)
    & $exe screen-resolved-gear-matrix rulesets\osrs-f2p-v1 $chunk.FullName "--manifest-output=$out\chunks\survivors-$n.csv" "--report-output=$out\chunks\screen-$n.json" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "screen chunk $n failed with exit $LASTEXITCODE" }
}
Write-Host ("[{0,7:N1}s] concatenating" -f $sw.Elapsed.TotalSeconds)
$target = "$out\resolved-survivors-$tag.csv"
$first = $true
$writer = [System.IO.StreamWriter]::new($target, $false, [System.Text.UTF8Encoding]::new($false))
foreach ($file in (Get-ChildItem "$out\chunks\survivors-*.csv" | Sort-Object Name)) {
    $reader = [System.IO.StreamReader]::new($file.FullName)
    $header = $reader.ReadLine()
    if ($first) { $writer.WriteLine($header); $first = $false }
    while (($line = $reader.ReadLine()) -ne $null) { $writer.WriteLine($line) }
    $reader.Close()
}
$writer.Close()
Copy-Item "$out\chunks\screen-01.json" "$out\resolved-screen-$tag.json" -Force
Write-Host ("[{0,7:N1}s] done" -f $sw.Elapsed.TotalSeconds)
