$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8='1'
. (Join-Path $PSScriptRoot 'runtime.ps1')
$paths=Get-PlanRuntime
$pythonPath=$paths.Python
$destination=Join-Path $paths.Runtime 'backups'
& $pythonPath (Join-Path $PSScriptRoot 'backup_restore.py') backup --data $paths.Data --destination $destination
if ($LASTEXITCODE -ne 0) { throw '备份失败，请查看上方原因。' }
Write-Host "备份已保存至：$destination"
