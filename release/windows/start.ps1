[CmdletBinding()]
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'verify-package.ps1')
. (Join-Path $PSScriptRoot 'runtime.ps1')
$projectDir = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectDir 'runtime\python.exe'
$dataPath = (Get-PlanRuntime).Data
$port = 3350
if ($env:PLAN_REVIEW_PORT -and (-not [int]::TryParse($env:PLAN_REVIEW_PORT, [ref]$port) -or $port -lt 1 -or $port -gt 65535)) {
    throw 'PLAN_REVIEW_PORT 必须是 1 到 65535 的端口号。'
}
$url = "http://127.0.0.1:$port/plan-review/"
Set-Location -LiteralPath $projectDir
Remove-Item Env:PYTHONHOME,Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '缺少内置运行时，请先完整解压 Windows 发布包。' }
$active = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() | Where-Object { $_.Port -eq $port }
if ($active) { throw "端口 $port 已被占用。如已启动本应用，请打开 $url 。更换端口见使用说明。" }
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
& (Join-Path $PSScriptRoot 'initialize-desktop.ps1') -DataPath $dataPath -PythonPath $pythonPath
Write-Host "计划审核  $url"
Write-Host "首次登录请双击 Admin.cmd。按 Ctrl+C 停止。"
$runner = Join-Path $PSScriptRoot 'portable-server.py'
if ($NoBrowser) { & $pythonPath -B $runner --data $dataPath --port $port --no-browser }
else { & $pythonPath -B $runner --data $dataPath --port $port }
exit $LASTEXITCODE
