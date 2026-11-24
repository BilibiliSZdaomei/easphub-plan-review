$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'runtime.ps1')
$paths = Get-PlanRuntime
$marker = Join-Path $paths.Data 'server.json'
if (-not (Test-Path -LiteralPath $marker)) { $marker = Join-Path $paths.LegacyData 'server.json' }
if (-not (Test-Path -LiteralPath $marker)) { Write-Host '没有由本项目启动的服务记录。'; exit 0 }
$record = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
if ($record.project -ne $projectPath -or $record.port -ne 3350) { throw '服务记录不属于当前项目，未停止任何进程。' }
$serverPid = [int]$record.pid
$running = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid"
if ($running) {
    $expectedScript=Join-Path $PSScriptRoot 'serve.py'
    $owned=$running.CommandLine.Contains($expectedScript) -and $running.CommandLine -match '(?:--desktop|--local-demo)(?:\s|$)'
    $legacy=$running.CommandLine -match 'uvicorn\s+backend\.api:app' -and $running.CommandLine -match '--port\s+3350(\s|$)'
    if (-not ($owned -or $legacy)) { throw '进程身份已变化，未停止任何进程。' }
    Stop-Process -Id $serverPid -Force
    Write-Host '计划审核已停止，已保存的数据保留。'
} else { Write-Host '计划审核已经停止。' }
Remove-Item -LiteralPath $marker
