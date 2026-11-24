# Windows x64 离线发布包

构建环境使用 Windows x64、CPython 3.12、Node.js 22.12+ 和 npm。请在普通工作目录取出当前发布标签，在仓库外创建依赖环境及产物目录。最终用户只需 ZIP 和 Windows 自带的 PowerShell 5.1。

下例在已检出的项目根目录运行。先将 `$buildDir` 改为本机库外的目录。安装和构建需要网络，成品首次启动可离线。

```powershell
$projectDir = (Get-Location).Path
$buildDir = 'C:\Build\PlanReview-v2'
New-Item -Path $buildDir -ItemType Directory -Force | Out-Null
py -3.12 -m venv "$buildDir\venv"
$buildPython = "$buildDir\venv\Scripts\python.exe"
& $buildPython -m pip install -r "$projectDir\requirements-lock.txt"
Copy-Item -LiteralPath "$projectDir\frontend" -Destination "$buildDir\frontend" -Recurse
Push-Location "$buildDir\frontend"
$env:APP_BASE_PATH = '/plan-review'
npm ci
npm run build
Pop-Location
$name = 'cpython-3.12.16+20261123-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'
$uri = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261123/' + $name
Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile "$buildDir\$name"
$zip = "$buildDir\PlanReview-v2.0.0-Windows-x64.zip"
& $buildPython -B release/windows/build.py --source $projectDir --ui "$buildDir\frontend\dist" --python-archive "$buildDir\$name" --output $zip
& $buildPython -B release/windows/smoke.py $zip "$buildDir\test-new"
```

`build.py` 验证 CPython 发布资产 SHA-256、生产依赖版本和 wheel 文件哈希。包内的 `versions.json` 记录实际运行版本及来源。首次启动自动在当前 Windows 用户目录建立数据库和加密的初始管理员密码卡。

`smoke.py` 在新目录解压发布包，将 PATH 限制为系统目录，以 Windows PowerShell 5.1 连续启动两次。检查项包括数据库迁移、管理员登录、重启后密码、十个仓库、空计划库、V2 模板和网页资源。启动端口随机选取，用户工作区保持独立。
