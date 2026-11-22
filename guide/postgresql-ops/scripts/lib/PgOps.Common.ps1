# PgOps.Common.ps1
# 各スクリプトからドットソースして使う共通関数。
# 注意: UTF-8 (BOM付き) で保存すること。BOMが無いと Windows PowerShell 5.1 で日本語が文字化けする。
# 注意: 二重引用符の文字列で「$変数」の直後に日本語を続けない(変数名として解釈される)。-f 書式を使う。

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# リポジトリ(postgresql-ops)のルート = scripts\lib の2つ上
$script:OpsRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

# ---------------------------------------------------------------- 汎用

function Get-Prop {
    param($Object, [string]$Name, $Default = $null)
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p) { return $Default }
    return $p.Value
}

# 未設定(null / 空 / "<...>" のプレースホルダ)なら $true
function Test-Unresolved {
    param($Value)
    if ($null -eq $Value) { return $true }
    if ($Value -is [string]) {
        $t = $Value.Trim()
        return ($t -eq '' -or $t.StartsWith('<'))
    }
    return $false
}

function Format-Value {
    param($V)
    if (Test-Unresolved $V) { return '(未設定)' }
    return [string]$V
}

function ConvertTo-PlainText {
    param([Security.SecureString]$Secure)
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

# "MYPC\svc-x" や ".\svc-x" を "svc-x" にそろえる
function ConvertTo-LocalAccountName {
    param([string]$StartName)
    if (-not $StartName) { return '' }
    $n = $StartName -replace '^\.\\', ''
    $n = $n -replace ('^' + [regex]::Escape($env:COMPUTERNAME) + '\\'), ''
    return $n
}

function Assert-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw '管理者権限の PowerShell で実行してください。'
    }
}

# ---------------------------------------------------------------- ログ

function Write-OpsLog {
    param([string]$Message, [string]$Level = 'INFO')
    $dir = Join-Path $script:OpsRoot 'logs'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    $line = '{0} [{1}] ({2}) {3}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $env:USERNAME, $Message
    $file = Join-Path $dir ('pgops-{0}.log' -f (Get-Date -Format 'yyyyMMdd'))
    Add-Content -LiteralPath $file -Value $line -Encoding UTF8
    $color = 'Gray'
    if ($Level -eq 'WARN') { $color = 'Yellow' }
    elseif ($Level -eq 'ERROR') { $color = 'Red' }
    elseif ($Level -eq 'OK') { $color = 'Green' }
    Write-Host $line -ForegroundColor $color
}

# ---------------------------------------------------------------- 台帳

function Get-InventoryPath {
    param([string]$Path)
    if ($Path) { return $Path }
    if ($env:PGOPS_INVENTORY) { return $env:PGOPS_INVENTORY }
    return (Join-Path $script:OpsRoot 'inventory\inventory.json')
}

function Read-Inventory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw ('台帳が見つかりません: {0}' -f $Path) }
    $inv = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($null -eq (Get-Prop $inv 'servers')) { throw '台帳に servers がありません。' }
    return $inv
}

function Save-Inventory {
    param($Inventory, [string]$Path)
    $Inventory.updated = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    $bak = '{0}.bak-{1}' -f $Path, (Get-Date -Format 'yyyyMMdd-HHmmss')
    Copy-Item -LiteralPath $Path -Destination $bak
    $json = $Inventory | ConvertTo-Json -Depth 10
    # Windows PowerShell 5.1 は < > & ' を \uXXXX にエスケープするので、読みやすく戻す
    $json = $json -replace '\\u003c', '<' -replace '\\u003e', '>' -replace '\\u0026', '&' -replace '\\u0027', "'"
    [IO.File]::WriteAllText($Path, $json, (New-Object Text.UTF8Encoding $false))
    Write-Host ('台帳を更新しました (バックアップ: {0})' -f $bak) -ForegroundColor DarkGray
}

function Add-History {
    param($Inventory, [string]$Action, [string]$Detail)
    $entry = [pscustomobject]@{
        at     = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
        by     = ('{0}@{1}' -f $env:USERNAME, $env:COMPUTERNAME)
        action = $Action
        detail = $Detail
    }
    $prev = @(@(Get-Prop $Inventory 'history') | Where-Object { $null -ne $_ })
    $Inventory.history = @($prev + $entry)
}

function Get-Server {
    param($Inventory, [string]$Id)
    $s = @($Inventory.servers | Where-Object { $_.id -eq $Id })
    if ($s.Count -eq 0) { throw ("台帳にサーバー '{0}' がありません。" -f $Id) }
    if ($s.Count -gt 1) { throw ("台帳でサーバーID '{0}' が重複しています。" -f $Id) }
    return $s[0]
}

function Assert-Resolved {
    param($Server, [string[]]$Fields)
    $bad = @()
    foreach ($f in $Fields) {
        $p = $Server.PSObject.Properties[$f]
        if ($null -eq $p -or (Test-Unresolved $p.Value)) { $bad += $f }
    }
    if ($bad.Count -gt 0) {
        throw ("台帳の未設定項目があります (サーバー {0}): {1}`n  inventory.json を編集してください。" -f $Server.id, ($bad -join ', '))
    }
}

function Assert-LocalServer {
    param($Server)
    Assert-Resolved $Server @('host')
    if ($Server.host -ine $env:COMPUTERNAME) {
        throw ("サーバー {0} は PC '{1}' の担当です。このPC('{2}')では実行できません。担当のPCで実行してください。" -f $Server.id, $Server.host, $env:COMPUTERNAME)
    }
}

function Get-LocalServers {
    param($Inventory)
    @($Inventory.servers | Where-Object { (-not (Test-Unresolved $_.host)) -and ($_.host -ieq $env:COMPUTERNAME) })
}

# グループ内で現在 main の役割になっているサーバー(retired は除く)
function Get-GroupMain {
    param($Inventory, [string]$Group)
    @($Inventory.servers | Where-Object {
            $_.group -eq $Group -and $_.role -eq 'main' -and (Get-Prop $_ 'status' 'active') -ne 'retired'
        })
}

# ---------------------------------------------------------------- PostgreSQL 補助

# 接続を受け付けていれば $true / いなければ $false / pg_isready が無ければ $null
function Test-PgReady {
    param([string]$BinDir, [string]$Address, [int]$Port, [int]$TimeoutSec = 3)
    $exe = Join-Path $BinDir 'pg_isready.exe'
    if (-not (Test-Path -LiteralPath $exe)) { return $null }
    & $exe -h $Address -p $Port -t $TimeoutSec | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Wait-PgReady {
    param([string]$BinDir, [string]$Address, [int]$Port, [int]$TimeoutSec = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        $r = Test-PgReady -BinDir $BinDir -Address $Address -Port $Port
        if ($null -eq $r) { return $null }
        if ($r) { return $true }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    return $false
}

# pg_controldata から "Database cluster state" を取り出す(例: in production / in archive recovery / shut down)
function Get-ClusterState {
    param([string]$BinDir, [string]$DataDir)
    $exe = Join-Path $BinDir 'pg_controldata.exe'
    if (-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath $DataDir)) { return '-' }
    $old = $env:LC_ALL
    try {
        $env:LC_ALL = 'C'
        $out = & $exe -D $DataDir 2>$null
        foreach ($line in @($out)) {
            if ($line -match '^(Database cluster state|データベースクラスタの状態)\s*:\s*(.+)$') { return $Matches[2].Trim() }
        }
        return '-'
    }
    catch { return '-' }
    finally { $env:LC_ALL = $old }
}
