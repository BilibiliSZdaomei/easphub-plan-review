[CmdletBinding()]
param([ValidateSet('Build', 'Typecheck', 'Install', 'Dev', 'Path')][string]$Action = 'Build', [switch]$Offline)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'environment.ps1')
if ($Action -eq 'Path') { (Get-DependencyEnvironment).Frontend; exit 0 }
$environment = Sync-FrontendSource
$bundledNode = Join-Path $environment.Tools 'node\node.exe'
if (Test-Path -LiteralPath $bundledNode) { $node = $bundledNode }
else { $node = (Get-Command node.exe -ErrorAction Stop).Source }
# Use the selected runtime for package-manager lifecycle subprocesses as well.
$env:PATH = (Split-Path -Parent $node) + ';' + $env:PATH
Push-Location -LiteralPath $environment.Frontend
try {
    if ($Action -eq 'Install') {
        if (Test-Path -LiteralPath 'pnpm-lock.yaml') {
            $pnpm = Join-Path $environment.Tools 'node\pnpm\bin\pnpm.cjs'
            $arguments = @('install', '--frozen-lockfile', '--store-dir', (Join-Path $environment.Tools 'pnpm-store'))
            if ($Offline) { $arguments += '--offline' }
            if (Test-Path -LiteralPath $pnpm) { & $node $pnpm @arguments }
            else { & pnpm.cmd @arguments }
        } else {
            $arguments = @('ci', '--no-audit', '--no-fund')
            if ($Offline) { $arguments += '--offline' }
            & npm.cmd @arguments
        }
        if ($LASTEXITCODE -ne 0) { throw 'Locked frontend dependency installation failed.' }
    } else {
        $tsc = Join-Path $environment.Frontend 'node_modules\typescript\bin\tsc'
        $vite = Join-Path $environment.Frontend 'node_modules\vite\bin\vite.js'
        if (-not (Test-Path -LiteralPath $vite)) { throw 'External dependencies are missing. Run frontend.ps1 -Action Install first.' }
        if ($Action -ne 'Dev') {
            if ($environment.Config.appId -eq 'dcs-data-workbench') { & $node $tsc --noEmit }
            else { & $node $tsc -b }
            if ($LASTEXITCODE -ne 0) { throw 'Frontend type check failed.' }
        }
        if ($Action -eq 'Build') {
            & $node $vite build --outDir (Join-Path $environment.Frontend 'dist')
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
        } elseif ($Action -eq 'Dev') {
            & $node $vite --host 127.0.0.1
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dev server failed.' }
        }
    }
} finally { Pop-Location }
Write-Output "External frontend: $($environment.Frontend)"
