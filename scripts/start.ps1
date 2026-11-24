param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'runtime.ps1')
$paths = Get-PlanRuntime
$runtimePath = $paths.Runtime
. (Join-Path $PSScriptRoot 'environment.ps1')
$dependencyEnvironment = Initialize-DependencyEnvironment
$dataPath = $paths.Data
$venvPath = Join-Path $runtimePath 'venv'
$pythonPath = Join-Path $venvPath 'Scripts\python.exe'
$url = 'http://127.0.0.1:3350/plan-review/'
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
$existing = Get-NetTCPConnection -State Listen -LocalPort 3350 -ErrorAction SilentlyContinue
if ($existing) {
    try { $health = Invoke-RestMethod ($url + 'api/v1/health') -TimeoutSec 3 } catch { throw '3350 端口正在被其他程序使用，请先处理端口冲突。' }
    if ($health.app -ne 'plan-review') { throw '3350 端口正在被其他程序使用。' }
    if ($health.demo) {
        throw '旧版演示服务正在运行。请先停止计划审核，再启动账号工作区。'
    } else {
        Write-Host "计划审核已运行：$url"
        if (-not $NoBrowser) { Start-Process $url }
        exit 0
    }
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $uvTool = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvTool -and (Test-Path -LiteralPath $bundledPython)) { & $uvTool.Source venv --python $bundledPython $venvPath }
    else { python -m venv $venvPath }
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败，请安装 Python 3.12 及以上版本。' }
}
$lockPath = Join-Path $projectPath 'requirements-lock.txt'
$lockHash = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash
$stampPath = Join-Path $runtimePath 'dependencies.sha256'
if (-not (Test-Path -LiteralPath $stampPath) -or (Get-Content -LiteralPath $stampPath -Raw).Trim() -ne $lockHash) {
    Write-Host '正在准备本地运行环境，首次启动需要下载依赖。'
    $uvTool = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvTool) { & $uvTool.Source pip sync --python $pythonPath $lockPath }
    else { & $pythonPath -m pip install -r $lockPath }
    if ($LASTEXITCODE -ne 0) { throw '安装依赖失败。请检查网络后重新启动。' }
    Set-Content -LiteralPath $stampPath -Value $lockHash -Encoding ASCII
}
function Test-V2Frontend([string]$Directory) {
    $manifest = Join-Path $Directory 'app-build.json'
    if (-not (Test-Path -LiteralPath $manifest) -or -not (Test-Path -LiteralPath (Join-Path $Directory 'index.html'))) { return $false }
    try {
        $build = Get-Content -LiteralPath $manifest -Raw -Encoding utf8 | ConvertFrom-Json
        $expected = Get-Content -LiteralPath (Join-Path $projectPath 'frontend\package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        return $build.version -eq $expected.version -and $build.review_model -eq 'V2' -and $build.market_scope -eq 'EUROPE' -and $build.account_mode -eq 'managed' -and $build.ui_revision -eq 5
    }
    catch { return $false }
}
$externalUI = Join-Path $dependencyEnvironment.Frontend 'dist'
$bundledUI = Join-Path $projectPath 'frontend\dist'
if (Test-V2Frontend $externalUI) { $env:PLAN_REVIEW_UI_DIR = $externalUI }
elseif (Test-V2Frontend $bundledUI) { $env:PLAN_REVIEW_UI_DIR = $bundledUI }
else {
    if (-not (Test-Path -LiteralPath (Join-Path $dependencyEnvironment.Frontend 'node_modules\vite\bin\vite.js'))) {
        & (Join-Path $PSScriptRoot 'frontend.ps1') -Action Install
    }
    & (Join-Path $PSScriptRoot 'frontend.ps1') -Action Build
    $env:PLAN_REVIEW_UI_DIR = $externalUI
}
$env:PLAN_REVIEW_DATA = $dataPath
$env:PLAN_REVIEW_DEMO = '0'
$env:PLAN_REVIEW_WORKER = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
& (Join-Path $PSScriptRoot 'initialize-desktop.ps1') -DataPath $dataPath -PythonPath $pythonPath
Remove-Item Env:PLAN_REVIEW_DATABASE_URL -ErrorAction SilentlyContinue
$outPath = Join-Path $dataPath 'server.stdout.log'
$errPath = Join-Path $dataPath 'server.stderr.log'
$servePath=Join-Path $PSScriptRoot 'serve.py'
$windowless=Join-Path $venvPath 'Scripts\pythonw.exe'
$arguments='"'+$servePath+'" --desktop --data "'+$dataPath+'"'
$created=Start-Process -FilePath $windowless -ArgumentList $arguments -WorkingDirectory $projectPath -WindowStyle Hidden -PassThru
if (-not $created -or -not $created.Id) { throw '后台启动失败。' }
for ($i=0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 400
    try {
        $health = Invoke-RestMethod ($url + 'api/v1/health') -TimeoutSec 2
        if ($health.app -eq 'plan-review') {
            $listener = Get-NetTCPConnection -State Listen -LocalPort 3350 | Select-Object -First 1
            @{pid=$listener.OwningProcess;launcher=$created.Id;project=$projectPath;port=3350;url=$url} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dataPath 'server.json') -Encoding UTF8
            Write-Host "计划审核已启动：$url"
            if (-not $NoBrowser) { Start-Process $url }
            exit 0
        }
    } catch { }
}
throw "启动未完成，请查看日志：$errPath"
