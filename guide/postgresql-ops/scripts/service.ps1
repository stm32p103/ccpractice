#Requires -Version 5.1
<#
.SYNOPSIS
  PostgreSQL サービスの状態確認・起動・停止・再起動(台帳 inventory.json に従う)

.DESCRIPTION
  このPC(COMPUTERNAME)が担当の status=active のサーバーを対象にする。
  順序ルール: 起動も停止も「main → backup」の順。
    - 起動: backup は main が接続を受け付けていないと起動しない(-Force で無視)
    - 停止: main を先に止めると、停止時の最後のWALが backup に届いてから止まる
  backup だけを止めて main を動かし続けるのは問題ない(単独指定で実行する)。

.EXAMPLE
  .\service.ps1 -Action Status
  .\service.ps1 -Action Start   -ServerId trial-a
  .\service.ps1 -Action Stop    -Group prod
  .\service.ps1 -Action Restart -ServerId prod-a -TimeoutSec 300
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Status', 'Start', 'Stop', 'Restart')][string]$Action,
    [string]$ServerId,
    [string]$Group,
    [int]$TimeoutSec = 120,
    [switch]$Force,
    [string]$InventoryPath
)

. (Join-Path $PSScriptRoot 'lib\PgOps.Common.ps1')

$invPath = Get-InventoryPath -Path $InventoryPath
$inv = Read-Inventory -Path $invPath

# ---- 対象サーバーの決定 --------------------------------------------------
if ($ServerId) {
    $one = Get-Server -Inventory $inv -Id $ServerId
    Assert-LocalServer $one
    $st = Get-Prop $one 'status' 'active'
    if ($st -ne 'active') { throw ('サーバー {0} の status が active ではありません ({1})。' -f $ServerId, $st) }
    $targets = @($one)
}
else {
    $all = @(Get-LocalServers -Inventory $inv)
    foreach ($s in $all) {
        $st = Get-Prop $s 'status' 'active'
        if ($st -ne 'active') { Write-Host ('  (対象外: {0} status={1})' -f $s.id, $st) -ForegroundColor DarkGray }
    }
    $targets = @($all | Where-Object { (Get-Prop $_ 'status' 'active') -eq 'active' })
    if ($Group) { $targets = @($targets | Where-Object { $_.group -eq $Group }) }
}
if ($targets.Count -eq 0) {
    Write-Host 'このPCで操作対象のサーバーがありません。(host / status / -Group を確認してください)'
    return
}

# main → backup の順
$ordered = @($targets | Sort-Object @{ Expression = { if ($_.role -eq 'main') { 0 } else { 1 } } }, id)

# ---- 関数 -----------------------------------------------------------------
function Get-SvcOrThrow {
    param($Server)
    Assert-Resolved $Server @('service_name')
    $svc = Get-Service -Name $Server.service_name -ErrorAction SilentlyContinue
    if ($null -eq $svc) {
        throw ("サービス '{0}' が見つかりません (サーバー {1})。インストール済みか、台帳の service_name を確認してください。" -f $Server.service_name, $Server.id)
    }
    return $svc
}

function Show-Status {
    param($Servers)
    $rows = @(foreach ($s in $Servers) {
            $state = '-'; $acct = '-'; $accepting = '-'; $cluster = '-'; $warn = @()
            if (-not (Test-Unresolved $s.service_name)) {
                $filter = "Name='{0}'" -f $s.service_name.Replace("'", "''")
                $cim = Get-CimInstance Win32_Service -Filter $filter -ErrorAction SilentlyContinue
                if ($null -eq $cim) { $state = '(サービス未登録)'; $warn += 'サービス未登録' }
                else {
                    $state = $cim.State
                    $acct = ConvertTo-LocalAccountName $cim.StartName
                    if ((-not (Test-Unresolved $s.service_account)) -and ($acct -ine $s.service_account)) {
                        $warn += ('起動アカウントが台帳({0})と不一致' -f $s.service_account)
                    }
                }
            }
            else { $state = '(台帳未設定)' }

            if (-not (Test-Unresolved $s.bin_dir)) {
                if ((-not (Test-Unresolved $s.address)) -and (-not (Test-Unresolved $s.port))) {
                    $r = Test-PgReady -BinDir $s.bin_dir -Address $s.address -Port ([int]$s.port)
                    if ($null -ne $r) { if ($r) { $accepting = '受付中' } else { $accepting = '応答なし' } }
                }
                if (-not (Test-Unresolved $s.data_dir)) { $cluster = Get-ClusterState -BinDir $s.bin_dir -DataDir $s.data_dir }
            }
            if ($s.role -eq 'main' -and $cluster -match 'in archive recovery') { $warn += '台帳はmainだが実体はスタンバイ(要確認)' }
            if ($s.role -eq 'backup' -and $cluster -match 'in production') { $warn += '台帳はbackupだが実体は本番稼働中(昇格済み? 台帳を確認)' }

            [pscustomobject]@{
                Id        = $s.id
                Group     = $s.group
                Role      = $s.role
                Service   = $s.service_name
                State     = $state
                Account   = $acct
                Port      = $s.port
                Accepting = $accepting
                Cluster   = $cluster
                Warn      = ($warn -join '; ')
            }
        })
    $rows | Format-Table Id, Group, Role, Service, State, Account, Port, Accepting, Cluster -AutoSize -Wrap
    foreach ($r in $rows) {
        if ($r.Warn) { Write-Host ('[警告] {0}: {1}' -f $r.Id, $r.Warn) -ForegroundColor Yellow }
    }
}

# backup の起動前に main が応答しているか確認する
function Assert-StartOrder {
    param($Server)
    if ($Server.role -ne 'backup') { return }
    $mains = @(Get-GroupMain -Inventory $inv -Group $Server.group)
    if ($mains.Count -eq 0) { Write-OpsLog ('グループ {0} に main がありません(台帳を確認)' -f $Server.group) 'WARN'; return }
    $m = $mains[0]
    if ((Test-Unresolved $m.address) -or (Test-Unresolved $m.port) -or (Test-Unresolved $Server.bin_dir)) {
        Write-OpsLog 'main の接続先または bin_dir が未設定のため、起動順の確認をスキップします' 'WARN'
        return
    }
    $r = Test-PgReady -BinDir $Server.bin_dir -Address $m.address -Port ([int]$m.port)
    if ($null -eq $r) { Write-OpsLog 'pg_isready が見つからず、起動順を確認できません' 'WARN'; return }
    if (-not $r) {
        if ($Force) { Write-OpsLog ('main({0} {1}:{2}) が応答しませんが -Force のため続行します' -f $m.id, $m.address, $m.port) 'WARN' }
        else {
            throw ('main({0} {1}:{2}) が応答しません。起動順は「main → backup」です。先に main を起動してください (無視する場合は -Force)。' -f $m.id, $m.address, $m.port)
        }
    }
}

function Start-One {
    param($Server)
    $svc = Get-SvcOrThrow $Server
    if ($svc.Status -eq 'Running') { Write-OpsLog ('既に起動中: {0} ({1})' -f $Server.id, $Server.service_name); return }
    Assert-StartOrder -Server $Server
    Write-OpsLog ('起動: {0} ({1})' -f $Server.id, $Server.service_name)
    try {
        if ($svc.Status -ne 'StartPending') { $svc.Start() }
        $svc.WaitForStatus('Running', [TimeSpan]::FromSeconds($TimeoutSec))
    }
    catch {
        Write-OpsLog ('起動失敗: {0}: {1}' -f $Server.id, $_.Exception.Message) 'ERROR'
        Write-Host '  確認: (1) サービスのログオンアカウント/パスワード (2)「サービスとしてログオン」権利 (3) データフォルダのACL (4) PostgreSQLのログ(data\log)' -ForegroundColor Yellow
        throw
    }
    if ((-not (Test-Unresolved $Server.bin_dir)) -and (-not (Test-Unresolved $Server.address)) -and (-not (Test-Unresolved $Server.port))) {
        $ok = Wait-PgReady -BinDir $Server.bin_dir -Address $Server.address -Port ([int]$Server.port) -TimeoutSec $TimeoutSec
        if ($ok) { Write-OpsLog ('起動完了(接続受付OK): {0}' -f $Server.id) 'OK' }
        elseif ($null -eq $ok) { Write-OpsLog ('起動完了(pg_isready が無いため接続確認は未実施): {0}' -f $Server.id) 'WARN' }
        else { Write-OpsLog ('サービスは起動したが接続を受け付けていません: {0} (ログを確認)' -f $Server.id) 'WARN' }
    }
    else { Write-OpsLog ('起動完了(接続確認は未実施・台帳の address/port/bin_dir が未設定): {0}' -f $Server.id) 'WARN' }
}

function Stop-One {
    param($Server)
    $svc = Get-SvcOrThrow $Server
    if ($svc.Status -eq 'Stopped') { Write-OpsLog ('既に停止中: {0} ({1})' -f $Server.id, $Server.service_name); return }
    Write-OpsLog ('停止: {0} ({1})' -f $Server.id, $Server.service_name)
    try {
        if ($svc.Status -ne 'StopPending') { $svc.Stop() }
        $svc.WaitForStatus('Stopped', [TimeSpan]::FromSeconds($TimeoutSec))
    }
    catch {
        Write-OpsLog ('停止失敗: {0}: {1}' -f $Server.id, $_.Exception.Message) 'ERROR'
        Write-Host '  接続中のアプリを止めてから再実行するか、-TimeoutSec を増やしてください。' -ForegroundColor Yellow
        throw
    }
    Write-OpsLog ('停止完了: {0}' -f $Server.id) 'OK'
    if ($Server.role -eq 'main') {
        $peers = @($inv.servers | Where-Object { $_.group -eq $Server.group -and $_.role -eq 'backup' -and (Get-Prop $_ 'status' 'active') -eq 'active' })
        if ($peers.Count -gt 0) {
            Write-Host ('  メインを停止しました。バックアップ機({0})は動作を続けます。計画停止なら、続けてバックアップ機も停止してください。' -f (($peers | ForEach-Object { $_.id }) -join ', ')) -ForegroundColor Yellow
        }
    }
}

# ---- 実行 -----------------------------------------------------------------
switch ($Action) {
    'Status' { Show-Status $ordered }
    'Start' {
        Assert-Admin
        foreach ($s in $ordered) { Start-One $s }
        Show-Status $ordered
    }
    'Stop' {
        Assert-Admin
        foreach ($s in $ordered) { Stop-One $s }
        Show-Status $ordered
    }
    'Restart' {
        Assert-Admin
        foreach ($s in $ordered) { Stop-One $s }
        foreach ($s in $ordered) { Start-One $s }
        Show-Status $ordered
    }
}
