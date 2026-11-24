param([Parameter(Mandatory)][string]$DataPath, [Parameter(Mandatory)][string]$PythonPath)
$ErrorActionPreference = 'Stop'
$prepare = Join-Path $PSScriptRoot 'prepare_desktop.py'
$lockFile = Join-Path $DataPath 'initialize.lock'
$setupLock = [IO.File]::Open($lockFile, 'OpenOrCreate', 'ReadWrite', 'None')
try {
    $state = & $PythonPath -B $prepare --data $DataPath
    if ($LASTEXITCODE -ne 0) { throw '工作区数据库准备失败。' }
    if ($state -eq 'READY') { return }
    if ($state -ne 'EMPTY') { throw '无法确认工作区初始化状态。' }
    $card = Join-Path $DataPath 'initial-admin.clixml'
    if (-not (Test-Path -LiteralPath $card)) {
        $bytes = New-Object byte[] 24
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $secret = ConvertTo-SecureString ([Convert]::ToBase64String($bytes)) -AsPlainText -Force
        $credential = New-Object Management.Automation.PSCredential('admin', $secret)
        $pending = Join-Path $DataPath ('admin-' + [guid]::NewGuid().ToString('N') + '.tmp')
        try {
            $credential | Export-Clixml -LiteralPath $pending -ErrorAction Stop
            [IO.File]::Move($pending, $card)
        } finally {
            if ([IO.File]::Exists($pending)) { [IO.File]::Delete($pending) }
        }
    }
    $credential = Import-Clixml -LiteralPath $card
    $OutputEncoding = New-Object System.Text.ASCIIEncoding
    $credential.GetNetworkCredential().Password | & $PythonPath -B $prepare --data $DataPath --create-admin
    if ($LASTEXITCODE -ne 0) { throw '创建初始管理员失败。' }
    Write-Host '初始管理员已创建。双击“查看初始管理员.cmd”可查看登录信息。'
} finally {
    $setupLock.Dispose()
}
