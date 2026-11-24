function Get-PlanRuntime {
    $runtime = Join-Path $env:LOCALAPPDATA 'PlanReview'
    if (-not (Test-Path -LiteralPath (Join-Path $runtime 'venv\Scripts\python.exe'))) {
        $packages = Join-Path $env:LOCALAPPDATA 'Packages'
        if (Test-Path -LiteralPath $packages) {
            foreach ($package in Get-ChildItem -LiteralPath $packages -Directory -Filter 'OpenAI.Codex_*') {
                $candidate = Join-Path $package.FullName 'LocalCache\Local\PlanReview'
                if (Test-Path -LiteralPath (Join-Path $candidate 'venv\Scripts\python.exe')) { $runtime=$candidate; break }
            }
        }
    }
    $python = Join-Path $runtime 'venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $python) {
        $physical = & $python -c 'from pathlib import Path; import sys; print(Path(sys.executable).resolve().parents[2])'
        if ($LASTEXITCODE -eq 0 -and $physical) { $runtime=$physical.Trim(); $python=Join-Path $runtime 'venv\Scripts\python.exe' }
    }
    return @{Runtime=$runtime;Data=(Join-Path $runtime 'workspace');LegacyData=(Join-Path $runtime 'data');Python=$python}
}
