#Requires -Version 5.1
<#
.SYNOPSIS
  台帳 inventory.json の表示・検証・更新(役割の入れ替え・項目の更新)

.DESCRIPTION
  Show     : グループごとに、どのサーバーが現在の main(★)かを含めて一覧表示する。
  Validate : 台帳の整合性を検査する(グループに main がちょうど1台か、ポート/フォルダ/サービス名の重複、未設定項目など)。
             NG があれば終了コード 1。
  Promote  : -ServerId で指定した backup を main に切り替え、同じグループの現在の main を backup にする。
             ※ 台帳を書き換えるだけ。実際の昇格(pg_promote)は docs\03-failure-recovery.md の手順で別に行う。
  Set      : 台帳の1項目を更新する(-Field / -Value)。更新履歴(history)に記録し、更新前のファイルを .bak-日時 で残す。

.EXAMPLE
  .\inventory.ps1 -Action Show
  .\inventory.ps1 -Action Validate
  .\inventory.ps1 -Action Promote -ServerId prod-b
  .\inventory.ps1 -Action Set -ServerId trial-a -Field status -Value active
  .\inventory.ps1 -Action Set -ServerId trial-a -Field data_dir -Value D:\pgsql\trial\data
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Show', 'Validate', 'Promote', 'Set')][string]$Action,
    [string]$ServerId,
    [string]$Field,
    [string]$Value,
    [switch]$Force,
    [string]$InventoryPath
)

. (Join-Path $PSScriptRoot 'lib\PgOps.Common.ps1')

$invPath = Get-InventoryPath -Path $InventoryPath
$inv = Read-Inventory -Path $invPath

$requiredFields = @('id', 'group', 'role', 'status', 'host', 'address', 'port', 'pg_major', 'service_name', 'service_account', 'install_dir', 'bin_dir', 'data_dir', 'backup_dir')
$settableFields = @{
    status = 'string'; host = 'string'; address = 'string'; port = 'int'; pg_major = 'int'; pg_version = 'string'
    service_name = 'string'; service_account = 'string'; install_dir = 'string'; bin_dir = 'string'
    data_dir = 'string'; backup_dir = 'string'; note = 'string'
}

# ---- 関数 -----------------------------------------------------------------
function Show-Inventory {
    Write-Host ('台帳: {0}  (更新: {1})' -f $invPath, $inv.updated)
    $groups = @($inv.servers | ForEach-Object { $_.group } | Select-Object -Unique)
    foreach ($g in $groups) {
        Write-Host ''
        Write-Host ('■ グループ: {0}' -f $g) -ForegroundColor Cyan
        $rows = @(foreach ($s in @($inv.servers | Where-Object { $_.group -eq $g })) {
                $roleLabel = 'backup'
                if ($s.role -eq 'main') { $roleLabel = '★main' }
                [pscustomobject]@{
                    Role    = $roleLabel
                    Id      = $s.id
                    Status  = (Get-Prop $s 'status' 'active')
                    Host    = (Format-Value $s.host)
                    Address = ('{0}:{1}' -f (Format-Value $s.address), (Format-Value $s.port))
                    Service = (Format-Value $s.service_name)
                    Account = (Format-Value $s.service_account)
                    Version = (Format-Value $s.pg_version)
                    DataDir = (Format-Value $s.data_dir)
                }
            })
        $rows | Format-Table -AutoSize -Wrap
    }
    $hist = @(@(Get-Prop $inv 'history') | Where-Object { $null -ne $_ })
    if ($hist.Count -gt 0) {
        Write-Host ''
        Write-Host '■ 直近の更新履歴' -ForegroundColor Cyan
        $hist | Select-Object -Last 5 | ForEach-Object { Write-Host ('  {0}  {1}  {2}: {3}' -f $_.at, $_.by, $_.action, $_.detail) }
    }
}

function Test-Inventory {
    $script:ng = 0
    $script:warn = 0
    function Out-Ng { param([string]$m) $script:ng++; Write-Host ('[NG]   {0}' -f $m) -ForegroundColor Red }
    function Out-Warn { param([string]$m) $script:warn++; Write-Host ('[WARN] {0}' -f $m) -ForegroundColor Yellow }

    $servers = @($inv.servers)
    if ($servers.Count -eq 0) { Out-Ng 'servers が空です' }

    # id の重複
    foreach ($grp in @($servers | Group-Object -Property id | Where-Object { $_.Count -gt 1 })) { Out-Ng ("サーバーID '{0}' が重複しています" -f $grp.Name) }

    foreach ($s in $servers) {
        $sid = Get-Prop $s 'id' '(idなし)'
        $missing = @($requiredFields | Where-Object { $null -eq $s.PSObject.Properties[$_] })
        if ($missing.Count -gt 0) { Out-Ng ('{0}: 項目がありません: {1}' -f $sid, ($missing -join ', ')); continue }
        if (@('main', 'backup') -notcontains $s.role) { Out-Ng ("{0}: role は main か backup (現在 '{1}')" -f $sid, $s.role) }
        if (@('active', 'planned', 'retired') -notcontains $s.status) { Out-Ng ("{0}: status は active / planned / retired (現在 '{1}')" -f $sid, $s.status) }
        if ($s.status -eq 'active') {
            $unres = @($requiredFields | Where-Object { Test-Unresolved $s.PSObject.Properties[$_].Value })
            if ($unres.Count -gt 0) { Out-Ng ('{0}: active なのに未設定の項目があります: {1}' -f $sid, ($unres -join ', ')) }
        }
        elseif ($s.status -eq 'planned') {
            $unres = @($requiredFields | Where-Object { Test-Unresolved $s.PSObject.Properties[$_].Value })
            if ($unres.Count -gt 0) { Write-Host ('[INFO] {0}: planned (未設定 {1} 項目。active にする前に記入)' -f $sid, $unres.Count) -ForegroundColor DarkGray }
        }
    }

    $live = @($servers | Where-Object { (Get-Prop $_ 'status' 'active') -ne 'retired' -and $null -ne $_.PSObject.Properties['group'] -and $null -ne $_.PSObject.Properties['role'] })
    # グループごとの main は1台
    foreach ($g in @($live | ForEach-Object { $_.group } | Select-Object -Unique)) {
        $mains = @($live | Where-Object { $_.group -eq $g -and $_.role -eq 'main' })
        if ($mains.Count -eq 0) { Out-Ng ("グループ '{0}' に main がありません" -f $g) }
        elseif ($mains.Count -gt 1) { Out-Ng ("グループ '{0}' に main が {1} 台あります(スプリットブレインの恐れ): {2}" -f $g, $mains.Count, (($mains | ForEach-Object { $_.id }) -join ', ')) }
        $majors = @($live | Where-Object { $_.group -eq $g -and (-not (Test-Unresolved (Get-Prop $_ 'pg_major'))) } | ForEach-Object { [string]$_.pg_major } | Select-Object -Unique)
        if ($majors.Count -gt 1) { Out-Warn ("グループ '{0}' で pg_major が揃っていません: {1} (バージョンアップ作業中なら想定内)" -f $g, ($majors -join ', ')) }
    }

    # 同一PC内の重複(ポート / データフォルダ / サービス名)
    foreach ($h in @($live | Where-Object { -not (Test-Unresolved $_.host) } | ForEach-Object { $_.host.ToLower() } | Select-Object -Unique)) {
        $onHost = @($live | Where-Object { -not (Test-Unresolved $_.host) -and $_.host.ToLower() -eq $h })
        foreach ($f in @('port', 'data_dir', 'service_name')) {
            $vals = @($onHost | Where-Object { -not (Test-Unresolved $_.$f) })
            foreach ($d in @($vals | Group-Object -Property { ([string]$_.$f).ToLower() } | Where-Object { $_.Count -gt 1 })) {
                Out-Ng ("PC '{0}' で {1} '{2}' が重複: {3}" -f $h, $f, $d.Name, (($d.Group | ForEach-Object { $_.id }) -join ', '))
            }
        }
    }

    Write-Host ''
    Write-Host ('検証結果: NG {0} 件 / WARN {1} 件' -f $script:ng, $script:warn) -ForegroundColor Cyan
    if ($script:ng -gt 0) { exit 1 }
}

function Invoke-Promote {
    if (-not $ServerId) { throw '-ServerId(新しく main にするサーバー)を指定してください。' }
    $target = Get-Server -Inventory $inv -Id $ServerId
    if ($target.role -eq 'main') { throw ('{0} は既に main です。' -f $ServerId) }
    if ((Get-Prop $target 'status' 'active') -eq 'retired') { throw ('{0} は retired です。' -f $ServerId) }
    $current = @(Get-GroupMain -Inventory $inv -Group $target.group)

    Write-Host ('グループ {0} の役割を入れ替えます:' -f $target.group) -ForegroundColor Cyan
    foreach ($c in $current) { Write-Host ('  {0}: main → backup' -f $c.id) }
    Write-Host ('  {0}: backup → main' -f $target.id)
    Write-Host '  ※ 台帳を書き換えるだけです。実際の昇格(SELECT pg_promote();)は先に行ってください。' -ForegroundColor Yellow
    Write-Host '  ※ 旧メインは、再構築するまで書き込み可能な状態で起動しないでください。' -ForegroundColor Yellow
    if (-not $Force) {
        $a = Read-Host '台帳を更新しますか? (y/N)'
        if ($a -ne 'y') { Write-Host '中止しました。'; return }
    }
    foreach ($c in $current) { $c.role = 'backup' }
    $target.role = 'main'
    $detail = '{0}: backup→main' -f $target.id
    if ($current.Count -gt 0) { $detail = '{0} / {1}: main→backup' -f $detail, (($current | ForEach-Object { $_.id }) -join ', ') }
    Add-History -Inventory $inv -Action 'Promote' -Detail $detail
    Save-Inventory -Inventory $inv -Path $invPath
    Write-OpsLog ('台帳: {0}' -f $detail) 'OK'
}

function Invoke-Set {
    if (-not $ServerId -or -not $Field) { throw '-ServerId と -Field と -Value を指定してください。' }
    if (-not $settableFields.ContainsKey($Field)) { throw ("更新できる項目: {0}" -f (($settableFields.Keys | Sort-Object) -join ', ')) }
    $s = Get-Server -Inventory $inv -Id $ServerId
    $new = $Value
    if ($settableFields[$Field] -eq 'int') {
        $n = 0
        if (-not [int]::TryParse($Value, [ref]$n)) { throw ('{0} は整数で指定してください。' -f $Field) }
        $new = $n
    }
    if ($Field -eq 'status' -and (@('active', 'planned', 'retired') -notcontains $Value)) { throw 'status は active / planned / retired のいずれかです。' }
    $p = $s.PSObject.Properties[$Field]
    $old = $null
    if ($null -ne $p) { $old = $p.Value }
    Write-Host ('{0}.{1}: {2} → {3}' -f $ServerId, $Field, (Format-Value $old), $new)
    if (-not $Force) {
        $a = Read-Host '台帳を更新しますか? (y/N)'
        if ($a -ne 'y') { Write-Host '中止しました。'; return }
    }
    if ($null -eq $p) { $s | Add-Member -NotePropertyName $Field -NotePropertyValue $new } else { $p.Value = $new }
    Add-History -Inventory $inv -Action 'Set' -Detail ('{0}.{1}: {2} → {3}' -f $ServerId, $Field, $old, $new)
    Save-Inventory -Inventory $inv -Path $invPath
    Write-OpsLog ('台帳: {0}.{1} を更新' -f $ServerId, $Field) 'OK'
}

# ---- 実行 -----------------------------------------------------------------
switch ($Action) {
    'Show' { Show-Inventory }
    'Validate' { Test-Inventory }
    'Promote' { Invoke-Promote }
    'Set' { Invoke-Set }
}
