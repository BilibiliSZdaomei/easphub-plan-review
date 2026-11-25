[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Bundle,
    [Parameter(Mandatory)][string]$KeyFile,
    [string]$DataDirectory
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'verify-package.ps1')
. (Join-Path $PSScriptRoot 'runtime.ps1')
$bundlePath = (Get-Item -LiteralPath $Bundle -ErrorAction Stop).FullName
$keyPath = (Get-Item -LiteralPath $KeyFile -ErrorAction Stop).FullName
$dataPath = if ($DataDirectory) { [IO.Path]::GetFullPath($DataDirectory) } else { (Get-PlanRuntime).Data }
$appDir = Split-Path -Parent $PSScriptRoot
$python = Join-Path $appDir 'runtime\python.exe'
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
Remove-Item Env:PYTHONHOME,Env:PYTHONPATH -ErrorAction SilentlyContinue
Push-Location -LiteralPath $appDir
try {
    & $python -B (Join-Path $PSScriptRoot 'prepare_desktop.py') --data $dataPath
    if ($LASTEXITCODE) { throw '无法准备账号恢复的目标工作区。' }
    & $python -B (Join-Path $PSScriptRoot 'restore_accounts.py') restore --data-dir $dataPath --bundle $bundlePath --key-file $keyPath
    if ($LASTEXITCODE) { throw '账号恢复失败，请查看上面的检查结果。' }
} finally {
    Pop-Location
}
