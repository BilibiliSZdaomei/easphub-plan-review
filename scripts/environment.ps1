# Local Windows dependencies live outside the source and all synced folders.
$script:DependencyProject = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))

function Assert-ExternalDependencyPath([string]$Path) {
    if ($Path -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+(?:\\|$))') { throw "An absolute external path is required: $Path" }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    foreach ($root in @($script:DependencyProject, $env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial)) {
        if (-not $root) { continue }
        $boundary = [IO.Path]::GetFullPath($root).TrimEnd('\', '/')
        if ($full.Equals($boundary, [StringComparison]::OrdinalIgnoreCase) -or $full.StartsWith($boundary + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Dependencies must stay outside source/synced folders: $full"
        }
    }
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "A dependency destination must not traverse a link: $cursor" }
            if (Test-Path -LiteralPath (Join-Path $cursor '.obsidian')) { throw "Dependency destination is in an Obsidian vault: $cursor" }
        }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
    return $full
}

function Get-DependencyEnvironment {
    $config = Get-Content -LiteralPath (Join-Path $script:DependencyProject 'local-environment.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $base = $env:CODEX_ARTIFACT_ROOT
    if (-not $base) { $base = [Environment]::GetEnvironmentVariable('CODEX_ARTIFACT_ROOT', 'User') }
    if (-not $base) { $base = Join-Path $env:LOCALAPPDATA 'CodexArtifacts' }
    $base = Assert-ExternalDependencyPath $base
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $identity = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($script:DependencyProject.ToLowerInvariant())))).Replace('-', '').ToLowerInvariant().Substring(0, [int]$config.hashLength) }
    finally { $sha.Dispose() }
    $root = Assert-ExternalDependencyPath (Join-Path $base ($config.appId + '-' + $identity + '\local-environment'))
    return [pscustomobject]@{ Root = $root; Base = $base; Python = (Join-Path $root 'python\Scripts\python.exe'); Venv = (Join-Path $root 'python'); Frontend = (Join-Path $root 'frontend'); Node = (Join-Path $root 'node'); Vendor = (Join-Path $root 'vendor'); Tools = (Join-Path $root 'offline-tools'); Config = $config; Project = $script:DependencyProject }
}

function Initialize-DependencyEnvironment {
    $environment = Get-DependencyEnvironment
    foreach ($part in @('', 'temp', 'cache\npm', 'cache\ruff')) {
        New-Item -ItemType Directory -Path (Join-Path $environment.Root $part) -Force | Out-Null
    }
    $env:CODEX_ARTIFACT_ROOT = $environment.Base
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:PYTHONUTF8 = '1'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:TEMP = Join-Path $environment.Root 'temp'
    $env:TMP = $env:TEMP
    $env:npm_config_cache = Join-Path $environment.Root 'cache\npm'
    $env:RUFF_CACHE_DIR = Join-Path $environment.Root 'cache\ruff'
    if ($environment.Config.pythonSource) { $env:PYTHONPATH = Join-Path $environment.Project $environment.Config.pythonSource }
    if ($environment.Config.appId -eq 'shipping-information-platform') { $env:NODE_PATH = Join-Path $environment.Node 'node_modules' }
    return $environment
}

function Sync-FrontendSource {
    $environment = Initialize-DependencyEnvironment
    $source = Join-Path $environment.Project 'frontend'
    if (-not (Test-Path -LiteralPath (Join-Path $source 'package.json'))) { throw 'This project has no frontend package.json.' }
    New-Item -ItemType Directory -Path $environment.Frontend -Force | Out-Null
    $statePath = Join-Path $environment.Root 'frontend-source-state.json'
    $old = @{}
    if (Test-Path -LiteralPath $statePath) {
        # Assign first so Windows PowerShell 5.1 and PowerShell 7 enumerate JSON arrays identically.
        $previousRows = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($row in $previousRows) {
            if ($row.path -isnot [string] -or $row.sha256 -isnot [string]) { throw "Invalid frontend source state: $statePath" }
            $old[$row.path] = $row.sha256
        }
    }
    $files = @()
    foreach ($folder in @('src', 'public')) {
        $directory = Join-Path $source $folder
        if (Test-Path -LiteralPath $directory) {
            $files += @(Get-ChildItem -LiteralPath $directory -Recurse -File -Force)
        }
    }
    $files += @(Get-ChildItem -LiteralPath $source -File -Force | Where-Object { $_.Name -match '^(package(-lock)?\.json|pnpm-lock\.yaml|pnpm-workspace\.yaml|tsconfig.*\.json|vite\.config\.[cm]?[jt]s|index\.html)$' })
    $next = @()
    foreach ($file in $files) {
        if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Source links need explicit review: $($file.FullName)" }
        $relative = $file.FullName.Substring($source.Length + 1)
        $target = Assert-ExternalDependencyPath (Join-Path $environment.Frontend $relative)
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        if (Test-Path -LiteralPath $target) {
            $current = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
            if ($current -ne $hash -and (-not $old.ContainsKey($relative) -or $current -ne $old[$relative])) { throw "External source copy has unique edits; preserve/merge them first: $target" }
        }
        if (-not (Test-Path -LiteralPath $target) -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $hash) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        }
        $next += [pscustomobject]@{ path = $relative; sha256 = $hash }
    }
    foreach ($relative in $old.Keys) {
        if ($relative -in $next.path) { continue }
        $target = Assert-ExternalDependencyPath (Join-Path $environment.Frontend $relative)
        if (Test-Path -LiteralPath $target) {
            if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $old[$relative]) { throw "External source copy has unique edits: $target" }
            Remove-Item -LiteralPath $target -Force
        }
    }
    ConvertTo-Json -InputObject @($next) -Depth 3 | Set-Content -LiteralPath $statePath -Encoding UTF8
    return $environment
}
