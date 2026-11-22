#Requires -Version 5.1
<#
.SYNOPSIS
  PostgreSQL サーバーのバージョンアップ前の準備(点検とバックアップ取得)。サーバーの停止や設定変更は一切しない。

.DESCRIPTION
  台帳 inventory.json のサーバー1台について、次を行い、結果を backup_dir 配下のレポート(report.md)にまとめる。
    1. サービス状態 / バイナリとデータのバージョン / 台帳との整合 / 更新種別(マイナー・メジャー) / main・backup の実体確認
    2. ディスク空き容量の確認
    3. 設定ファイル(postgresql.conf, postgresql.auto.conf, pg_hba.conf, pg_ident.conf)の退避
    4. (-SkipDump 指定なし) ロール等の全体ダンプ + DBごとの pg_dump(-Fc) と pg_restore -l による読み取り確認
       拡張機能・エンコーディング・レプリケーション状況の記録
  DBのパスワードは対話入力し、プロセス内の環境変数 PGPASSWORD にだけ置く(終了時に削除。ファイルには残さない)。
  NG が1つでもあれば終了コード 1 を返す。NG が残る間は更新作業に進まないこと。

.EXAMPLE
  .\upgrade-prep.ps1 -ServerId prod-b -TargetVersion 18.5
  .\upgrade-prep.ps1 -ServerId trial-a -TargetVersion 19 -PgUser postgres
  .\upgrade-prep.ps1 -ServerId trial-a -SkipDump      # 点検だけ(ダンプなし)
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ServerId,
    [string]$TargetVersion,
    [string]$PgUser = 'postgres',
    [switch]$SkipDump,
    [string]$InventoryPath
)

. (Join-Path $PSScriptRoot 'lib\PgOps.Common.ps1')

$invPath = Get-InventoryPath -Path $InventoryPath
$inv = Read-Inventory -Path $invPath
$server = Get-Server -Inventory $inv -Id $ServerId
Assert-LocalServer $server
$srvStatus = Get-Prop $server 'status' 'active'
if ($srvStatus -ne 'active') { throw ('サーバー {0} の status が active ではありません ({1})。' -f $ServerId, $srvStatus) }
Assert-Resolved $server @('service_name', 'address', 'port', 'bin_dir', 'data_dir', 'backup_dir', 'pg_major')

$bin = $server.bin_dir
$psqlExe = Join-Path $bin 'psql.exe'
$dumpExe = Join-Path $bin 'pg_dump.exe'
$dumpAllExe = Join-Path $bin 'pg_dumpall.exe'
$restoreExe = Join-Path $bin 'pg_restore.exe'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outDir = Join-Path $server.backup_dir ('upgrade-prep_{0}_{1}' -f $ServerId, $stamp)

# レポート用に共有する値(スクリプトスコープ)
$results = New-Object System.Collections.Generic.List[object]
$script:binVer = '-'
$script:dataMajor = $null
$script:upType = $null
$script:clusterState = '-'
$script:serverVersion = '-'
$script:inRecovery = $null
$script:dbOk = $false
$script:dbList = @()
$script:extInfo = @{}
$script:encInfo = @()
$script:replInfo = @()
$script:slotInfo = @()
$script:dataBytes = 0

# ---- 関数 -----------------------------------------------------------------
function Format-Bytes {
    param([double]$Bytes)
    if ($Bytes -ge 1GB) { return ('{0:N2} GB' -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ('{0:N1} MB' -f ($Bytes / 1MB)) }
    return ('{0:N0} KB' -f ($Bytes / 1KB))
}

function Add-Result {
    param([string]$Item, [string]$Status, [string]$Detail)
    $results.Add([pscustomobject]@{ Item = $Item; Status = $Status; Detail = $Detail })
    $color = 'Gray'
    if ($Status -eq 'OK') { $color = 'Green' } elseif ($Status -eq 'WARN') { $color = 'Yellow' } elseif ($Status -eq 'NG') { $color = 'Red' }
    Write-Host ('[{0,-4}] {1}: {2}' -f $Status, $Item, $Detail) -ForegroundColor $color
}

# Body の戻り値が文字列なら OK、@{Status=;Detail=} なら その状態。例外は NG。
function Invoke-Step {
    param([string]$Item, [scriptblock]$Body)
    try {
        $res = & $Body
        if ($res -is [hashtable]) { Add-Result $Item $res.Status $res.Detail }
        else { Add-Result $Item 'OK' ([string]$res) }
    }
    catch { Add-Result $Item 'NG' $_.Exception.Message }
}

function Invoke-Psql {
    param([string]$Sql, [string]$Db = 'postgres')
    $out = & $psqlExe -h $server.address -p $server.port -U $PgUser -d $Db -w -X -A -t -c $Sql
    if ($LASTEXITCODE -ne 0) { throw ('psql が失敗しました (db={0}): {1}' -f $Db, $Sql) }
    return @($out | Where-Object { $_ -ne '' })
}

function Get-NextSteps {
    $id = $ServerId
    $steps = New-Object System.Collections.Generic.List[string]
    if ($script:upType -eq 'minor') {
        $steps.Add('このレポートに NG が無く、ダンプが取得できていることを確認する')
        $steps.Add('更新順は「バックアップ機 → メイン機」。バックアップ機のPCで先に更新する')
        $steps.Add(('停止: `.\service.ps1 -Action Stop -ServerId {0}`(メインを止める場合は先にアプリを停止する)' -f $id))
        $steps.Add('新しいマイナーバージョンのインストーラーで更新する(インストール先・データディレクトリが変わらないことを確認)')
        $steps.Add(('起動: `.\service.ps1 -Action Start -ServerId {0}` → `Status` で接続受付と起動アカウントを確認' -f $id))
        $steps.Add('レプリケーションを確認する(メイン: pg_stat_replication / バックアップ: pg_is_in_recovery() = t)')
        $steps.Add(('台帳を更新: `.\inventory.ps1 -Action Set -ServerId {0} -Field pg_version -Value <新バージョン>`' -f $id))
        $steps.Add('もう一方のサーバー(メイン)も同じ手順で更新する')
    }
    elseif ($script:upType -eq 'major') {
        $steps.Add('このレポートに NG が無く、ダンプが取得できていることを確認する。別DBへ pg_restore して復元テストもしておく')
        $steps.Add('新しいメジャーバージョンを「別のインストール先・別のデータディレクトリ・別ポート」でインストールする(旧は残す)')
        $steps.Add('アプリを停止 → 旧メインを停止 → 新バージョンの pg_upgrade --check → pg_upgrade 本実行(--link はロールバックが難しくなる点に注意)')
        $steps.Add('新メインを起動して動作確認し、アプリの接続先を切り替える')
        $steps.Add('バックアップ機は pg_basebackup で作り直す(メジャーを跨いだストリーミング更新はできない)')
        $steps.Add('台帳を更新する(service_name / install_dir / bin_dir / data_dir / port / pg_major / pg_version)。`inventory.ps1 -Action Set` を使う')
        $steps.Add('統計情報を再作成する(`vacuumdb --all --analyze-in-stages`)')
        $steps.Add('旧環境は一定期間残してから撤去する')
    }
    else {
        $steps.Add('-TargetVersion を指定して再実行すると、マイナー/メジャーに応じた手順を表示します')
    }
    return $steps
}

# ---- 実行 -----------------------------------------------------------------
Write-Host ('=== バージョンアップ準備: {0} ({1} / {2}) ===' -f $ServerId, $server.group, $server.role) -ForegroundColor Cyan
Write-Host '    このスクリプトは停止・設定変更を行いません。' -ForegroundColor DarkGray

Invoke-Step 'ツールの存在' {
    $missing = @()
    foreach ($e in @($psqlExe, $dumpExe, $dumpAllExe, $restoreExe, (Join-Path $bin 'postgres.exe'))) {
        if (-not (Test-Path -LiteralPath $e)) { $missing += (Split-Path $e -Leaf) }
    }
    if ($missing.Count -gt 0) { throw ('bin_dir に見つかりません: {0} (台帳の bin_dir を確認)' -f ($missing -join ', ')) }
    $bin
}

Invoke-Step 'サービス状態' {
    $filter = "Name='{0}'" -f $server.service_name.Replace("'", "''")
    $cim = Get-CimInstance Win32_Service -Filter $filter
    if ($null -eq $cim) { throw ("サービス '{0}' が見つかりません" -f $server.service_name) }
    $acct = ConvertTo-LocalAccountName $cim.StartName
    $detail = '{0} / 起動アカウント {1}' -f $cim.State, $acct
    if ((-not (Test-Unresolved $server.service_account)) -and ($acct -ine $server.service_account)) {
        return @{ Status = 'WARN'; Detail = ('{0} (台帳は {1})' -f $detail, $server.service_account) }
    }
    $detail
}

Invoke-Step 'バイナリのバージョン' {
    $line = & (Join-Path $bin 'postgres.exe') --version | Select-Object -First 1
    if ($line -match 'PostgreSQL\)\s+(\S+)') { $script:binVer = $Matches[1] } else { $script:binVer = [string]$line }
    $script:binVer
}

Invoke-Step 'データのメジャーバージョン' {
    $vf = Join-Path $server.data_dir 'PG_VERSION'
    if (-not (Test-Path -LiteralPath $vf)) { throw ('PG_VERSION が読めません: {0} (data_dir と権限を確認)' -f $vf) }
    $v = (Get-Content -LiteralPath $vf -TotalCount 1).Trim()
    $script:dataMajor = [int](($v -split '\.')[0])
    $binMajor = [int](($script:binVer -split '\.')[0])
    if ($binMajor -ne $script:dataMajor) {
        return @{ Status = 'WARN'; Detail = ('データ {0} と bin_dir のバイナリ {1} のメジャーが違います' -f $script:dataMajor, $script:binVer) }
    }
    if ([int]$server.pg_major -ne $script:dataMajor) {
        return @{ Status = 'WARN'; Detail = ('データ {0}。台帳の pg_major({1}) と違います。台帳を更新してください' -f $script:dataMajor, $server.pg_major) }
    }
    ('{0} (台帳と一致)' -f $script:dataMajor)
}

if ($TargetVersion) {
    Invoke-Step '更新種別' {
        $tgt = [int](($TargetVersion -split '\.')[0])
        if ($null -eq $script:dataMajor) { throw '現在のメジャーバージョンが不明のため判定できません' }
        if ($tgt -lt $script:dataMajor) { throw ('目標 {0} は現在 {1} より古い(ダウングレードは対象外)' -f $TargetVersion, $script:dataMajor) }
        if ($tgt -eq $script:dataMajor) { $script:upType = 'minor'; return ('マイナー更新: {0} → {1}' -f $script:binVer, $TargetVersion) }
        $script:upType = 'major'
        ('メジャー更新: {0} → {1} (pg_upgrade または dump/restore が必要)' -f $script:dataMajor, $TargetVersion)
    }
}
else { Add-Result '更新種別' 'INFO' '-TargetVersion 未指定(判定しません)' }

Invoke-Step 'クラスタ状態と台帳の役割' {
    $script:clusterState = Get-ClusterState -BinDir $bin -DataDir $server.data_dir
    if ($script:clusterState -eq '-') { return @{ Status = 'WARN'; Detail = 'pg_controldata で状態を取得できませんでした(権限/ロケール)' } }
    if ($server.role -eq 'main' -and $script:clusterState -match 'in archive recovery') {
        return @{ Status = 'WARN'; Detail = ('台帳は main だが実体はスタンバイ ({0})。台帳を確認してください' -f $script:clusterState) }
    }
    if ($server.role -eq 'backup' -and $script:clusterState -match 'in production') {
        return @{ Status = 'WARN'; Detail = ('台帳は backup だが実体は本番稼働中 ({0})。昇格済みか確認してください' -f $script:clusterState) }
    }
    ('{0} (台帳の役割: {1})' -f $script:clusterState, $server.role)
}

Invoke-Step 'ディスク空き容量' {
    $m = Get-ChildItem -LiteralPath $server.data_dir -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum
    $size = 0
    if ($null -ne $m.Sum) { $size = [double]$m.Sum }
    $script:dataBytes = $size
    $free = $null
    try { $free = (New-Object IO.DriveInfo([IO.Path]::GetPathRoot($server.backup_dir))).AvailableFreeSpace } catch { $free = $null }
    if ($null -eq $free) { return @{ Status = 'WARN'; Detail = ('データ {0}。バックアップ先の空き容量を取得できません(UNCパス?)' -f (Format-Bytes $size)) } }
    $need = $size * 1.2
    if ($free -lt $need) {
        return @{ Status = 'WARN'; Detail = ('データ {0} に対しバックアップ先の空きが {1} で不足気味です(目安 {2})' -f (Format-Bytes $size), (Format-Bytes $free), (Format-Bytes $need)) }
    }
    ('データ {0} / バックアップ先の空き {1}' -f (Format-Bytes $size), (Format-Bytes $free))
}

Invoke-Step '出力フォルダの作成' {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    $outDir
}

Invoke-Step '設定ファイルの退避' {
    $dest = Join-Path $outDir 'config'
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    $copied = @()
    foreach ($f in @('postgresql.conf', 'postgresql.auto.conf', 'pg_hba.conf', 'pg_ident.conf')) {
        $src = Join-Path $server.data_dir $f
        if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $dest; $copied += $f }
    }
    if ($copied.Count -eq 0) { throw 'データディレクトリの設定ファイルを読めませんでした(権限を確認)' }
    '{0} → {1}' -f ($copied -join ', '), $dest
}

if ($SkipDump) {
    Add-Result 'ダンプ' 'INFO' '-SkipDump のため省略'
}
else {
    $ready = Test-PgReady -BinDir $bin -Address $server.address -Port ([int]$server.port)
    if ($null -eq $ready) { Add-Result 'DB接続' 'NG' 'pg_isready が見つかりません' }
    elseif (-not $ready) {
        Add-Result 'DB接続' 'NG' ('接続を受け付けていません ({0}:{1})。サービスを起動してから再実行してください(点検だけなら -SkipDump)' -f $server.address, $server.port)
    }
    else {
        $sec = Read-Host ("DBユーザー '{0}' のパスワード" -f $PgUser) -AsSecureString
        $env:PGPASSWORD = ConvertTo-PlainText $sec
        try {
            Invoke-Step 'DB接続' {
                $sv = @(Invoke-Psql -Sql 'SHOW server_version')
                $rec = @(Invoke-Psql -Sql 'SELECT pg_is_in_recovery()')
                $script:serverVersion = $sv[0]
                $script:inRecovery = ($rec[0] -eq 't')
                $script:dbOk = $true
                'server_version={0} / スタンバイ(リカバリ中)={1}' -f $sv[0], $rec[0]
            }

            if ($script:dbOk) {
                Invoke-Step 'ダンプ: ロール等(globals)' {
                    $f = Join-Path $outDir 'globals.sql'
                    & $dumpAllExe -h $server.address -p $server.port -U $PgUser -w --globals-only -f $f
                    if ($LASTEXITCODE -ne 0) { throw 'pg_dumpall が失敗しました' }
                    '{0} ({1})' -f $f, (Format-Bytes (Get-Item -LiteralPath $f).Length)
                }

                $script:dbList = @(Invoke-Psql -Sql 'SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY 1')
                foreach ($db in $script:dbList) {
                    Invoke-Step ('ダンプ: DB {0}' -f $db) {
                        $f = Join-Path $outDir ('{0}.dump' -f $db)
                        & $dumpExe -h $server.address -p $server.port -U $PgUser -w -Fc -f $f -d $db
                        if ($LASTEXITCODE -ne 0) { throw ('pg_dump が失敗しました (db={0})' -f $db) }
                        & $restoreExe -l $f | Out-Null
                        if ($LASTEXITCODE -ne 0) { throw ('作成したダンプを pg_restore -l で読めませんでした (db={0})' -f $db) }
                        '{0} ({1}) / 読み取り確認OK' -f $f, (Format-Bytes (Get-Item -LiteralPath $f).Length)
                    }
                    try {
                        $script:extInfo[$db] = @(Invoke-Psql -Db $db -Sql "SELECT extname || ' ' || extversion FROM pg_extension ORDER BY 1")
                    }
                    catch { $script:extInfo[$db] = @('(取得失敗)') }
                }

                Invoke-Step 'DBのエンコーディング' {
                    $script:encInfo = @(Invoke-Psql -Sql "SELECT datname || ' | ' || pg_encoding_to_char(encoding) || ' | ' || datcollate FROM pg_database WHERE datallowconn ORDER BY 1")
                    '{0} 件' -f $script:encInfo.Count
                }
                Invoke-Step 'レプリケーション状況' {
                    $script:replInfo = @(Invoke-Psql -Sql "SELECT COALESCE(client_addr::text, '-') || ' ' || state || ' ' || sync_state FROM pg_stat_replication")
                    $script:slotInfo = @(Invoke-Psql -Sql "SELECT slot_name || ' active=' || active::text FROM pg_replication_slots")
                    $detail = '送信先 {0} 件 / スロット {1} 件' -f $script:replInfo.Count, $script:slotInfo.Count
                    if ($server.role -eq 'main' -and $script:replInfo.Count -eq 0) {
                        return @{ Status = 'WARN'; Detail = ('{0}。mainなのにバックアップ機が接続していません' -f $detail) }
                    }
                    $detail
                }
            }
        }
        finally {
            Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
        }
    }
}

# ---- レポート -------------------------------------------------------------
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add(('# バージョンアップ準備レポート: {0}' -f $ServerId))
$lines.Add('')
$lines.Add(('- 作成日時: {0}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')))
$lines.Add(('- 実行者: {0}@{1}' -f $env:USERNAME, $env:COMPUTERNAME))
$lines.Add(('- 台帳: {0}' -f $invPath))
$lines.Add(('- グループ/役割: {0} / {1}' -f $server.group, $server.role))
$lines.Add(('- 接続先: {0}:{1}' -f $server.address, $server.port))
$lines.Add(('- サービス: {0} (台帳のアカウント {1})' -f $server.service_name, $server.service_account))
$lines.Add(('- bin_dir: `{0}`' -f $server.bin_dir))
$lines.Add(('- data_dir: `{0}`' -f $server.data_dir))
$lines.Add(('- バイナリ {0} / データのメジャー {1} / SHOW server_version {2}' -f $script:binVer, $script:dataMajor, $script:serverVersion))
$lines.Add(('- 目標バージョン: {0}' -f $(if ($TargetVersion) { $TargetVersion } else { '(未指定)' })))
$lines.Add('')
$lines.Add('## 点検結果')
$lines.Add('')
$lines.Add('| 状態 | 項目 | 内容 |')
$lines.Add('|---|---|---|')
foreach ($r in $results) { $lines.Add(('| {0} | {1} | {2} |' -f $r.Status, $r.Item, ($r.Detail -replace '\|', '/'))) }
$lines.Add('')
if ($script:dbList.Count -gt 0) {
    $lines.Add('## DBと拡張機能')
    $lines.Add('')
    foreach ($db in $script:dbList) {
        $lines.Add(('- **{0}**: {1}' -f $db, ((@($script:extInfo[$db])) -join ', ')))
    }
    $lines.Add('')
    $lines.Add('## エンコーディング / 照合順序')
    $lines.Add('')
    foreach ($e in $script:encInfo) { $lines.Add(('- {0}' -f $e)) }
    $lines.Add('')
    $lines.Add('## レプリケーション')
    $lines.Add('')
    $lines.Add(('- 送信先(pg_stat_replication): {0}' -f $(if ($script:replInfo.Count -gt 0) { $script:replInfo -join ' / ' } else { 'なし' })))
    $lines.Add(('- スロット: {0}' -f $(if ($script:slotInfo.Count -gt 0) { $script:slotInfo -join ' / ' } else { 'なし' })))
    $lines.Add('')
}
$lines.Add('## 次の手順')
$lines.Add('')
$n = 1
foreach ($s in (Get-NextSteps)) { $lines.Add(('{0}. {1}' -f $n, $s)); $n++ }
$lines.Add('')
$lines.Add('## 取り扱い注意')
$lines.Add('')
$lines.Add('- 設定ファイルの退避(config フォルダ)には、postgresql.auto.conf の primary_conninfo などパスワードに関わる情報が含まれる場合があります。バックアップ先のアクセス権に注意してください。')
$lines.Add('- ダンプ(.dump / globals.sql)はDBの内容そのものです。バックアップ先は本機とは別のディスクまたは別の機器にしてください。')

$reportPath = Join-Path $outDir 'report.md'
if (Test-Path -LiteralPath $outDir) {
    [IO.File]::WriteAllText($reportPath, ($lines -join "`r`n"), (New-Object Text.UTF8Encoding $true))
}

# ---- 結果 -----------------------------------------------------------------
$ngCount = @($results | Where-Object { $_.Status -eq 'NG' }).Count
$warnCount = @($results | Where-Object { $_.Status -eq 'WARN' }).Count
Write-Host ''
Write-Host ('結果: NG {0} 件 / WARN {1} 件' -f $ngCount, $warnCount) -ForegroundColor Cyan
if (Test-Path -LiteralPath $reportPath) { Write-Host ('レポート: {0}' -f $reportPath) }
Write-OpsLog ('upgrade-prep {0}: NG={1} WARN={2} target={3}' -f $ServerId, $ngCount, $warnCount, $(if ($TargetVersion) { $TargetVersion } else { '-' }))
if ($ngCount -gt 0) {
    Write-Host 'NG が残っています。解消するまで更新作業に進まないでください。' -ForegroundColor Red
    exit 1
}
