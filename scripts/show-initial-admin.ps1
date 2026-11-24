$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'runtime.ps1')
$card = Join-Path (Get-PlanRuntime).Data 'initial-admin.clixml'
if (-not (Test-Path -LiteralPath $card)) { throw '请先启动计划审核以初始化本机工作区。' }
$credential = Import-Clixml -LiteralPath $card
Add-Type -AssemblyName System.Windows.Forms
$form = New-Object Windows.Forms.Form
$form.Text = '计划审核 · 本机初始管理员'
$form.StartPosition = 'CenterScreen'
$form.Width = 420
$form.Height = 158
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$label = New-Object Windows.Forms.Label
$label.Text = "账号  " + $credential.UserName
$label.SetBounds(18, 14, 360, 25)
$password = New-Object Windows.Forms.TextBox
$password.SetBounds(18, 48, 240, 26)
$password.ReadOnly = $true
$password.UseSystemPasswordChar = $true
$password.Text = $credential.GetNetworkCredential().Password
$copy = New-Object Windows.Forms.Button
$copy.SetBounds(266, 46, 118, 28)
$copy.Text = '复制初始密码'
$copy.Add_Click({ [Windows.Forms.Clipboard]::SetText($password.Text); $copy.Text = '已复制' })
$show = New-Object Windows.Forms.CheckBox
$show.Text = '显示初始密码'
$show.SetBounds(18, 78, 120, 24)
$show.Add_CheckedChanged({ $password.UseSystemPasswordChar = -not $show.Checked })
$form.Controls.AddRange(@($label,$password,$copy,$show))
try { [void]$form.ShowDialog() } finally { $form.Dispose() }
