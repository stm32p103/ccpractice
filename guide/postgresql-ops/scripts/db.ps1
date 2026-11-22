#Requires -Version 5.1
<#
.SYNOPSIS
  アプリ用のDB と DBロール(DBユーザー)の一覧・作成・削除・パスワード変更

.DESCRIPTION
  台帳 inventory.json のサーバー1台(このPC担当)に psql で接続して操作する。
  アプリごとに「DB + ロール」を1組作る方針(docs\01-architecture.md §1)。
    List        : DB とロールの一覧(参照のみ。バックアップ機でも可)
    CreateApp   : ロール <App>_user と DB <App>_db を作成する(書き込み可能な main でのみ実行できる)
                    - DB は UTF8 / template0 から作成、オーナーはそのロール
                    - PUBLIC からの接続権限を外し、そのロールにだけ接続を許可
                    - ロールのパスワードは対話入力(コマンドラインやファイルに残さない)
                    - 最後に pg_hba.conf へ追加する行の例を表示する(pg_hba.conf は自動では編集しない)
    DropApp     : DB とロールを削除する。削除前に pg_dump を取る(-NoDump で省略)。DB名の入力確認あり
    SetPassword : ロールのパスワードを変更する
  superuser(既定 postgres)のパスワードは対話入力し、プロセス内の PGPASSWORD にだけ置く(終了時に削除)。
  -DryRun を付けると何も変更せず、実行内容だけ表示する。

.EXAMPLE
  .\db.ps1 -Action List        -ServerId prod-a
  .\db.ps1 -Action CreateApp   -ServerId prod-a -App app1 -ClientCidr 192.168.1.20/32
  .\db.ps1 -Action CreateApp   -ServerId trial-a -App app1 -ConnectionLimit 20 -DryRun
  .\db.ps1 -Action SetPassword -ServerId prod-a -App app1
  .\db.ps1 -Action DropApp     -ServerId trial-a -App app1
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('List', 'CreateApp', 'DropApp', 'SetPassword')][string]$Action,
    [Parameter(Mandatory = $true)][string]$ServerId,
    [string]$App,
    [string]$DbName,
    [string]$RoleName,
    [int]$ConnectionLimit = -1,
    [string]$Collation,
    [string]$ClientCidr,
    [string]$PgUser = 'postgres',
    [switch]$NoDump,
    [switch]$KeepRole,
    [switch]$DryRun,
    [string]$InventoryPath
)

. (Join-Path $PSScriptRoot 'lib\PgOps.Common.ps1')

$invPath = Get-InventoryPath -Path $InventoryPath
$inv = Read-Inventory -Path $invPath
$server = Get-Server -Inventory $inv -Id $ServerId
Assert-LocalServer $server
$srvStatus = Get-Prop $server 'status' 'active'
if ($srvStatus -ne 'active') { throw ('サーバー {0} の status が active ではありません ({1})。' -f $ServerId, $srvStatus) }
Assert-Resolved $server @('address', 'port', 'bin_dir')

$psqlExe = Join-Path $server.bin_dir 'psql.exe'
$dumpExe = Join-Path $server.bin_dir 'pg_dump.exe'
$restoreExe = Join-Path $server.bin_dir 'pg_restore.exe'
foreach ($e in @($psqlExe)) { if (-not (Test-Path -LiteralPath $e)) { throw ('見つかりません: {0} (台帳の bin_dir を確認)' -f $e) } }

# psql へ標準入力で渡すSQL(パスワードを含む)が文字化けしないように
$OutputEncoding = New-Object Text.UTF8Encoding $false
$env:PGCLIENTENCODING = 'UTF8'

$protectedDb = @('postgres', 'template0', 'template1')
$protectedRole = @('postgres', 'repl_user')

# ---- 関数 -----------------------------------------------------------------
function Resolve-Names {
    if ($App) {
        if ($App -cnotmatch '^[a-z][a-z0-9_]{1,24}$') { throw '-App は英小文字で始まる、英小文字・数字・_ の2〜25文字で指定してください。' }
        if (-not $DbName) { $script:DbName = '{0}_db' -f $App }
        if (-not $RoleName) { $script:RoleName = '{0}_user' -f $App }
    }
    if (-not $script:DbName -or -not $script:RoleName) { throw '-App(または -DbName と -RoleName の両方)を指定してください。' }
    foreach ($n in @($script:DbName, $script:RoleName)) {
        if ($n -cnotmatch '^[a-z][a-z0-9_]{1,40}$') { throw ("名前 '{0}' は英小文字で始まる、英小文字・数字・_ の2〜41文字にしてください。" -f $n) }
        if ($n.StartsWith('pg_')) { throw ("名前 '{0}' は pg_ で始められません。" -f $n) }
    }
    if ($protectedDb -contains $script:DbName) { throw ("DB '{0}' は操作対象にできません。" -f $script:DbName) }
    if ($protectedRole -contains $script:RoleName) { throw ("ロール '{0}' は操作対象にできません。" -f $script:RoleName) }
}

# 結果を返すクエリ(秘密を含まないSQL用)
function Invoke-PsqlQuery {
    param([string]$Sql, [string]$Db = 'postgres')
    $out = & $psqlExe -h $server.address -p $server.port -U $PgUser -d $Db -w -X -A -t -F '|' -c $Sql
    if ($LASTEXITCODE -ne 0) { throw ('psql が失敗しました (db={0}): {1}' -f $Db, $Sql) }
    return @($out | Where-Object { $_ -ne '' })
}

# 標準入力で渡すSQL(パスワードを含む場合用。エラー文にSQLを出さない)
function Invoke-PsqlScript {
    param([string]$Sql, [string]$Db = 'postgres')
    $null = $Sql | & $psqlExe -h $server.address -p $server.port -U $PgUser -d $Db -w -X -q -v ON_ERROR_STOP=1 -f -
    if ($LASTEXITCODE -ne 0) { throw ('psql の実行に失敗しました (db={0})。詳細は上のメッセージとサーバーログを確認してください。' -f $Db) }
}

function Read-NewPassword {
    param([string]$Label)
    $p1 = Read-Host ('{0} のパスワードを入力' -f $Label) -AsSecureString
    $p2 = Read-Host '確認のためもう一度入力' -AsSecureString
    $t1 = ConvertTo-PlainText $p1
    if ($t1.Length -eq 0) { throw 'パスワードが空です。' }
    if ($t1 -cne (ConvertTo-PlainText $p2)) { throw 'パスワードが一致しません。' }
    return $t1
}

# パスワードがログに残りにくいよう、このセッションのログ出力を抑える(superuser のみ設定可能)
$quietSql = "SET log_statement = 'none'; SET log_min_error_statement = 'panic';"

function Assert-Writable {
    $r = @(Invoke-PsqlQuery -Sql 'SELECT pg_is_in_recovery()')
    if ($r[0] -eq 't') { throw ('サーバー {0} はスタンバイ(読み取り専用)です。書き込み可能な main に対して実行してください。' -f $ServerId) }
}

function Test-RoleExists { param([string]$Name) return (@(Invoke-PsqlQuery -Sql ("SELECT 1 FROM pg_roles WHERE rolname = '{0}'" -f $Name)).Count -gt 0) }
function Test-DbExists { param([string]$Name) return (@(Invoke-PsqlQuery -Sql ("SELECT 1 FROM pg_database WHERE datname = '{0}'" -f $Name)).Count -gt 0) }

function Invoke-List {
    Write-Host ('サーバー: {0} ({1}:{2}, role={3})' -f $ServerId, $server.address, $server.port, $server.role)
    $inRec = @(Invoke-PsqlQuery -Sql 'SELECT pg_is_in_recovery()')
    if ($inRec[0] -eq 't') { Write-Host '  ※ スタンバイ(読み取り専用)に接続しています。' -ForegroundColor Yellow }

    Write-Host ''
    Write-Host '■ データベース' -ForegroundColor Cyan
    $dbs = @(Invoke-PsqlQuery -Sql 'SELECT d.datname, pg_get_userbyid(d.datdba), pg_encoding_to_char(d.encoding), pg_size_pretty(pg_database_size(d.datname)), d.datconnlimit FROM pg_database d WHERE NOT d.datistemplate ORDER BY 1')
    $dbRows = @(foreach ($l in $dbs) {
            $c = $l -split '\|'
            [pscustomobject]@{ DB = $c[0]; Owner = $c[1]; Encoding = $c[2]; Size = $c[3]; ConnLimit = $c[4] }
        })
    $dbRows | Format-Table -AutoSize

    Write-Host '■ ロール(pg_ で始まる組み込みを除く)' -ForegroundColor Cyan
    $roles = @(Invoke-PsqlQuery -Sql "SELECT rolname, rolcanlogin, rolsuper, rolreplication, rolconnlimit FROM pg_roles WHERE rolname NOT LIKE 'pg\_%' ORDER BY 1")
    $roleRows = @(foreach ($l in $roles) {
            $c = $l -split '\|'
            [pscustomobject]@{ Role = $c[0]; Login = $c[1]; Superuser = $c[2]; Replication = $c[3]; ConnLimit = $c[4] }
        })
    $roleRows | Format-Table -AutoSize
    $su = @($roleRows | Where-Object { $_.Superuser -eq 't' -and $_.Role -ne 'postgres' })
    if ($su.Count -gt 0) { Write-Host ('[警告] postgres 以外の superuser があります: {0}' -f (($su | ForEach-Object { $_.Role }) -join ', ')) -ForegroundColor Yellow }
}

function Invoke-CreateApp {
    Resolve-Names
    Assert-Writable
    if (Test-RoleExists $script:RoleName) { throw ("ロール '{0}' は既に存在します。" -f $script:RoleName) }
    if (Test-DbExists $script:DbName) { throw ("DB '{0}' は既に存在します。" -f $script:DbName) }

    $limit = ''
    if ($ConnectionLimit -ge 0) { $limit = ' CONNECTION LIMIT {0}' -f $ConnectionLimit }
    $coll = ''
    if ($Collation) {
        if ($Collation -notmatch '^[A-Za-z0-9_.@-]+$') { throw '-Collation に使えない文字が含まれています。' }
        $coll = " LC_COLLATE '{0}' LC_CTYPE '{0}'" -f $Collation
    }
    $client = '<アプリの接続元IP>/32'
    if ($ClientCidr) {
        if ($ClientCidr -notmatch '^[0-9A-Fa-f:.]+/\d{1,3}$') { throw '-ClientCidr は 192.168.1.20/32 のような形式で指定してください。' }
        $client = $ClientCidr
    }

    Write-Host ('作成内容: ロール "{0}" (LOGIN{1}) / DB "{2}" (UTF8, owner={0}){3}' -f $script:RoleName, $limit, $script:DbName, $coll)
    Write-Host '  PUBLIC の接続権限を外し、ロールにだけ接続を許可します。'
    if ($DryRun) { Write-Host '[DryRun] 何も変更していません。'; return }

    $pw = Read-NewPassword -Label $script:RoleName
    $pwSql = $pw.Replace("'", "''")
    $sql1 = @(
        $quietSql,
        ('CREATE ROLE "{0}" LOGIN PASSWORD ''{1}''{2};' -f $script:RoleName, $pwSql, $limit),
        ('CREATE DATABASE "{0}" OWNER "{1}" ENCODING ''UTF8'' TEMPLATE template0{2};' -f $script:DbName, $script:RoleName, $coll),
        ('REVOKE CONNECT ON DATABASE "{0}" FROM PUBLIC;' -f $script:DbName),
        ('GRANT CONNECT ON DATABASE "{0}" TO "{1}";' -f $script:DbName, $script:RoleName)
    ) -join "`n"
    try {
        Invoke-PsqlScript -Sql $sql1
        Invoke-PsqlScript -Db $script:DbName -Sql 'REVOKE ALL ON SCHEMA public FROM PUBLIC;'
    }
    catch {
        Write-OpsLog ('作成に失敗: {0} / {1}: {2}' -f $script:DbName, $script:RoleName, $_.Exception.Message) 'ERROR'
        # DB が作られていないのにロールだけ残った場合は片付ける
        try {
            if ((Test-RoleExists $script:RoleName) -and -not (Test-DbExists $script:DbName)) {
                Invoke-PsqlScript -Sql ('DROP ROLE "{0}";' -f $script:RoleName)
                Write-Host '  途中まで作成されたロールを削除しました。' -ForegroundColor Yellow
            }
            else { Write-Host '  一部が作成済みの可能性があります。.\db.ps1 -Action List で確認してください。' -ForegroundColor Yellow }
        }
        catch { Write-Host '  後始末にも失敗しました。.\db.ps1 -Action List で確認してください。' -ForegroundColor Yellow }
        throw
    }
    Write-OpsLog ("サーバー {0}: DB '{1}' とロール '{2}' を作成しました" -f $ServerId, $script:DbName, $script:RoleName) 'OK'

    Write-Host ''
    Write-Host '次の作業:' -ForegroundColor Cyan
    Write-Host '  1. pg_hba.conf に接続許可を追加する(main と backup の両方。docs\02-daily-operations.md §5):'
    Write-Host ('       host  {0}  {1}  {2}  scram-sha-256' -f $script:DbName, $script:RoleName, $client)
    Write-Host '     追加後に SELECT pg_reload_conf(); で反映する。'
    Write-Host ('  2. 接続確認: psql -h {0} -p {1} -U {2} -d {3}' -f $server.address, $server.port, $script:RoleName, $script:DbName)
}

function Invoke-DropApp {
    Resolve-Names
    Assert-Writable
    $dbExists = Test-DbExists $script:DbName
    $roleExists = Test-RoleExists $script:RoleName
    if (-not $dbExists -and -not $roleExists) { Write-Host '対象の DB もロールも存在しません。'; return }
    Write-Host ('削除対象: DB "{0}" ({1}) / ロール "{2}" ({3})' -f $script:DbName, $(if ($dbExists) { '存在' } else { 'なし' }), $script:RoleName, $(if ($roleExists -and -not $KeepRole) { '削除する' } elseif ($roleExists) { '残す(-KeepRole)' } else { 'なし' }))
    if ($DryRun) {
        Write-Host ('[DryRun] 削除前ダンプ: {0}' -f $(if ($NoDump) { 'なし(-NoDump)' } else { '取得する' }))
        Write-Host '[DryRun] 何も変更していません。'
        return
    }
    $ans = Read-Host ("削除を実行するには DB名 '{0}' をそのまま入力してください" -f $script:DbName)
    if ($ans -cne $script:DbName) { Write-Host '入力が一致しないため中止しました。'; return }

    if ($dbExists -and -not $NoDump) {
        Assert-Resolved $server @('backup_dir')
        foreach ($e in @($dumpExe, $restoreExe)) { if (-not (Test-Path -LiteralPath $e)) { throw ('見つかりません: {0}' -f $e) } }
        New-Item -ItemType Directory -Path $server.backup_dir -Force | Out-Null
        $f = Join-Path $server.backup_dir ('drop_{0}_{1}_{2}.dump' -f $ServerId, $script:DbName, (Get-Date -Format 'yyyyMMdd-HHmmss'))
        & $dumpExe -h $server.address -p $server.port -U $PgUser -w -Fc -f $f -d $script:DbName
        if ($LASTEXITCODE -ne 0) { throw '削除前の pg_dump に失敗したため中止しました(何も削除していません)。' }
        & $restoreExe -l $f | Out-Null
        if ($LASTEXITCODE -ne 0) { throw '削除前ダンプを pg_restore -l で読めなかったため中止しました(何も削除していません)。' }
        Write-OpsLog ('削除前ダンプを取得: {0}' -f $f) 'OK'
    }
    if ($dbExists) {
        Invoke-PsqlScript -Sql ('DROP DATABASE "{0}" WITH (FORCE);' -f $script:DbName)
        Write-OpsLog ("サーバー {0}: DB '{1}' を削除しました" -f $ServerId, $script:DbName) 'OK'
    }
    if ($roleExists -and -not $KeepRole) {
        try {
            Invoke-PsqlScript -Sql ('DROP ROLE "{0}";' -f $script:RoleName)
            Write-OpsLog ("サーバー {0}: ロール '{1}' を削除しました" -f $ServerId, $script:RoleName) 'OK'
        }
        catch {
            Write-Host ("  ロール '{0}' は、ほかのDBのオブジェクトを持っているなどの理由で削除できませんでした(残しています)。" -f $script:RoleName) -ForegroundColor Yellow
        }
    }
    Write-Host '  pg_hba.conf に追加していた該当行も、main と backup の両方から削除してください。' -ForegroundColor Yellow
}

function Invoke-SetPassword {
    Resolve-Names
    Assert-Writable
    if (-not (Test-RoleExists $script:RoleName)) { throw ("ロール '{0}' が存在しません。" -f $script:RoleName) }
    Write-Host ('パスワードを変更するロール: "{0}"' -f $script:RoleName)
    if ($DryRun) { Write-Host '[DryRun] 何も変更していません。'; return }
    $pw = Read-NewPassword -Label $script:RoleName
    $sql = $quietSql + "`n" + ('ALTER ROLE "{0}" PASSWORD ''{1}'';' -f $script:RoleName, $pw.Replace("'", "''"))
    Invoke-PsqlScript -Sql $sql
    Write-OpsLog ("サーバー {0}: ロール '{1}' のパスワードを変更しました" -f $ServerId, $script:RoleName) 'OK'
    Write-Host '  アプリ側の接続設定のパスワードも更新してください。'
}

# ---- 実行 -----------------------------------------------------------------
$ready = Test-PgReady -BinDir $server.bin_dir -Address $server.address -Port ([int]$server.port)
if ($null -eq $ready) { throw 'pg_isready が見つかりません(台帳の bin_dir を確認)。' }
if (-not $ready) { throw ('接続を受け付けていません ({0}:{1})。サービスを起動してから再実行してください。' -f $server.address, $server.port) }

# -DryRun でも、存在確認や main かどうかの確認のために接続する(変更はしない)
$sec = Read-Host ("DBユーザー '{0}' のパスワード" -f $PgUser) -AsSecureString
$env:PGPASSWORD = ConvertTo-PlainText $sec
try {
    switch ($Action) {
        'List' { Invoke-List }
        'CreateApp' { Invoke-CreateApp }
        'DropApp' { Invoke-DropApp }
        'SetPassword' { Invoke-SetPassword }
    }
}
finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
