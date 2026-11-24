[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$package = Split-Path -Parent $PSScriptRoot
$manifest = Join-Path $package 'package-files.json'
if (-not [IO.File]::Exists($manifest)) { throw '安装包清单缺失，请重新完整解压 Windows 离线包。' }
$files = ([IO.File]::ReadAllText($manifest) | ConvertFrom-Json).PSObject.Properties
$missing = [Collections.Generic.List[string]]::new()
$digest = [Security.Cryptography.SHA256]::Create()
try {
    foreach ($file in $files) {
        $path = [IO.Path]::Combine($package, $file.Name)
        if (-not [IO.File]::Exists($path)) { $missing.Add($file.Name); continue }
        $stream = [IO.File]::OpenRead($path)
        try { $hash = [BitConverter]::ToString($digest.ComputeHash($stream)).Replace('-','') }
        finally { $stream.Dispose() }
        if ($hash -ne $file.Value) { $missing.Add($file.Name) }
    }
} finally { $digest.Dispose() }
if ($missing.Count) {
    $summary = ($missing | Select-Object -First 10) -join [Environment]::NewLine
    throw "有 $($missing.Count) 个程序文件缺失或损坏。请从原 ZIP 重新完整解压到新的短路径目录。$([Environment]::NewLine)$summary"
}
Write-Host '程序文件校验通过。'
