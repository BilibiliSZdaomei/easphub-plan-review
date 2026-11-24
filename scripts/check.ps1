$ErrorActionPreference = 'Stop'
$url = 'http://127.0.0.1:3350/plan-review/'
. (Join-Path $PSScriptRoot 'runtime.ps1')
try {
    $health = Invoke-RestMethod ($url + 'api/v1/health') -TimeoutSec 5
    if ($health.app -ne 'plan-review' -or $health.status -ne 'ok') { throw '服务标识不匹配' }
    $page = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 5
    if ($page.StatusCode -ne 200 -or $page.Content -notmatch '/plan-review/assets/') { throw '页面文件未就绪' }
    Write-Host '检查通过：服务、数据库与页面均正常。'
    Write-Host "打开地址：$url"
    Write-Host "数据目录：$((Get-PlanRuntime).Data)"
} catch { Write-Host "检查未通过：$($_.Exception.Message)"; exit 1 }
