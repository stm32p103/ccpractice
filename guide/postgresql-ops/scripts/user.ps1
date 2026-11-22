#Requires -Version 5.1
<#
.SYNOPSIS
  PostgreSQL サービス用のローカルユーザー(サービスアカウント)の作成・削除・確認

.DESCRIPTION
  台帳 inventory.json の service_account / data_dir に従って動く。このPCが担当のサーバーのみ対象。
  Create : ローカルユーザーを作成(パスワードは対話入力。管理者グループには入れない)
           データフォルダを作成し、そのユーザーにフルコントロールを付与する。
           ※ サービスのログオンアカウントの変更は services.msc の「ログオン」タブで行う
             (「サービスとしてログオン」権利が自動で付与されるため)。
  Delete : ユーザーを削除。サービスが使用中、または台帳上ほかのサーバーが共用している場合は拒否する。
           データフォルダ上の当該ユーザーの権限(ACL)も外す。-RemoveProfile でユーザープロファイルも削除。
  Show   : ユーザーの状態・管理者グループ所属・使用中サービス・データフォルダのACLを表示する。
  -DryRun を付けると何も変更せず、実行内容だけ表示する。

.EXAMPLE
  .\user.ps1 -Action Show   -ServerId trial-a
  .\user.ps1 -Action Create -ServerId trial-a
  .\user.ps1 -Action Delete -ServerId trial-a -RemoveProfile
  .\user.ps1 -Action Create -ServerId prod-a -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Create', 'Delete', 'Show')][string]$Action,
    [Parameter(Mandatory = $true)][string]$ServerId,
    [switch]$RemoveProfile,
    [switch]$DryRun,
    [switch]$Force,
    [string]$InventoryPath
)

. (Join-Path $PSScriptRoot 'lib\PgOps.Common.ps1')

$invPath = Get-InventoryPath -Path $InventoryPath
$inv = Read-Inventory -Path $invPath
$server = Get-Server -Inventory $inv -Id $ServerId
Assert-LocalServer $server

# ---- 関数 -----------------------------------------------------------------
function Assert-AccountName {
    param([string]$Name)
    if ($Name.Length -gt 20) { throw ("ユーザー名 '{0}' が20文字を超えています(Windowsのローカルユーザー名の上限)。" -f $Name) }
    if ($Name -match '[\\/\[\]:;|=,+*?<>"@]') { throw ("ユーザー名 '{0}' に使えない文字が含まれています(ドメイン/UPN形式は未対応)。" -f $Name) }
}

# ドライブ直下・Windows/Program Files/ユーザーフォルダ自体にはACLを付けない(事故防止)
function Assert-SafeDir {
    param([string]$Path)
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $bad = @($env:SystemRoot, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:USERPROFILE, (Split-Path $env:USERPROFILE -Parent)) | Where-Object { $_ }
    $hit = @($bad | Where-Object { $_.TrimEnd('\') -ieq $full })
    if ($full -match '^[A-Za-z]:$' -or $hit.Count -gt 0) {
        throw ("データフォルダに '{0}' は指定できません。専用のサブフォルダを台帳の data_dir に指定してください。" -f $Path)
    }
}

function Invoke-Icacls {
    param([string[]]$IcaclsArgs)
    $out = & icacls.exe @IcaclsArgs
    if ($LASTEXITCODE -ne 0) { throw ('icacls が失敗しました: {0}{1}{2}' -f ($IcaclsArgs -join ' '), "`n", ($out -join "`n")) }
}

function Get-UsingServices {
    param([string]$Name)
    @(Get-CimInstance Win32_Service | Where-Object { (ConvertTo-LocalAccountName $_.StartName) -ieq $Name })
}

function Invoke-Create {
    Assert-Admin
    Assert-Resolved $server @('service_account', 'data_dir')
    $name = $server.service_account
    Assert-AccountName $name
    Assert-SafeDir $server.data_dir

    $user = Get-LocalUser -Name $name -ErrorAction SilentlyContinue
    if ($null -ne $user) {
        Write-OpsLog ("アカウント '{0}' は既に存在します(作成をスキップ)。" -f $name) 'WARN'
    }
    elseif ($DryRun) {
        Write-Host ("[DryRun] ローカルユーザー '{0}' を作成します(パスワード無期限・変更不可・管理者グループには入れない)" -f $name)
    }
    else {
        $p1 = Read-Host ('{0} のパスワードを入力' -f $name) -AsSecureString
        $p2 = Read-Host '確認のためもう一度入力' -AsSecureString
        $t1 = ConvertTo-PlainText $p1
        if ($t1.Length -eq 0) { throw 'パスワードが空です。' }
        if ($t1 -cne (ConvertTo-PlainText $p2)) { throw 'パスワードが一致しません。' }
        New-LocalUser -Name $name -Password $p1 -PasswordNeverExpires -UserMayNotChangePassword -AccountNeverExpires -Description ('PostgreSQL service account ({0})' -f $ServerId) | Out-Null
        Write-OpsLog ("ローカルユーザー '{0}' を作成しました (サーバー {1})" -f $name, $ServerId) 'OK'
    }

    $dir = $server.data_dir
    if (-not (Test-Path -LiteralPath $dir)) {
        if ($DryRun) { Write-Host ("[DryRun] フォルダを作成: {0}" -f $dir) }
        else { New-Item -ItemType Directory -Path $dir -Force | Out-Null; Write-OpsLog ('データフォルダを作成: {0}' -f $dir) }
    }
    if ($DryRun) {
        Write-Host ("[DryRun] icacls で '{0}' に '{1}' のフルコントロール(OI)(CI)を付与" -f $dir, $name)
    }
    else {
        Invoke-Icacls @($dir, '/grant', ('{0}:(OI)(CI)F' -f $name))
        Write-OpsLog ("データフォルダ '{0}' に '{1}' のフルコントロールを付与しました" -f $dir, $name) 'OK'
    }

    Write-Host ''
    Write-Host '次の作業:' -ForegroundColor Cyan
    Write-Host ("  1. PostgreSQL を手動インストール(データディレクトリ = {0})" -f $dir)
    Write-Host ("  2. services.msc で '{0}' の「ログオン」タブを開き、アカウントを '.\{1}' に変更して再起動" -f $server.service_name, $name)
    Write-Host '  3. .\service.ps1 -Action Status で起動アカウントが台帳と一致していることを確認'
}

function Invoke-Delete {
    Assert-Admin
    Assert-Resolved $server @('service_account')
    $name = $server.service_account
    Assert-AccountName $name

    $user = Get-LocalUser -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $user) { Write-OpsLog ("アカウント '{0}' は存在しません(削除不要)。" -f $name) 'WARN'; return }

    $using = @(Get-UsingServices -Name $name)
    if ($using.Count -gt 0) {
        throw ("このアカウントを使っているサービスがあります: {0}`n  先にサービスのログオンアカウントを変更するか、PostgreSQL をアンインストールしてください。" -f (($using | ForEach-Object { $_.Name }) -join ', '))
    }
    $others = @($inv.servers | Where-Object {
            $_.id -ne $ServerId -and $_.service_account -ieq $name -and
            (-not (Test-Unresolved $_.host)) -and $_.host -ieq $env:COMPUTERNAME -and
            (Get-Prop $_ 'status' 'active') -ne 'retired'
        })
    if ($others.Count -gt 0) {
        throw ("同じPC上の別サーバー({0})が台帳でこのアカウントを使っています。削除すると影響します。" -f (($others | ForEach-Object { $_.id }) -join ', '))
    }

    if ($DryRun) {
        Write-Host ("[DryRun] '{0}' のACLを data_dir から外し、ローカルユーザーを削除します(プロファイル削除: {1})" -f $name, $RemoveProfile.IsPresent)
        return
    }
    if (-not $Force) {
        $ans = Read-Host ("削除を実行するには アカウント名 '{0}' をそのまま入力してください" -f $name)
        if ($ans -cne $name) { Write-Host '入力が一致しないため中止しました。'; return }
    }

    $sid = $user.SID.Value
    if (-not (Test-Unresolved $server.data_dir) -and (Test-Path -LiteralPath $server.data_dir)) {
        Invoke-Icacls @($server.data_dir, '/remove', $name, '/T', '/C', '/Q')
        Write-OpsLog ("'{0}' のACLを '{1}' から外しました" -f $name, $server.data_dir)
    }
    Remove-LocalUser -Name $name
    Write-OpsLog ("ローカルユーザー '{0}' を削除しました (サーバー {1})" -f $name, $ServerId) 'OK'

    if ($RemoveProfile) {
        $prof = @(Get-CimInstance Win32_UserProfile -Filter ("SID='{0}'" -f $sid) -ErrorAction SilentlyContinue)
        foreach ($p in $prof) { Remove-CimInstance -InputObject $p; Write-OpsLog ('プロファイルを削除: {0}' -f $p.LocalPath) 'OK' }
        if ($prof.Count -eq 0) { Write-Host 'ユーザープロファイルはありませんでした。' }
    }
}

function Invoke-Show {
    Assert-Resolved $server @('service_account')
    $name = $server.service_account
    Write-Host ('サーバー: {0} (group={1}, role={2}, status={3})' -f $server.id, $server.group, $server.role, (Get-Prop $server 'status' 'active'))
    Write-Host ('台帳のサービスアカウント: {0}' -f $name)
    $user = Get-LocalUser -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $user) { Write-Host '  → このPCにアカウントは存在しません。' -ForegroundColor Yellow }
    else {
        Write-Host ('  存在: はい / 有効: {0} / パスワード最終更新: {1}' -f $user.Enabled, $user.PasswordLastSet)
        $admins = @(Get-LocalGroupMember -SID 'S-1-5-32-544' -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
        $isAdmin = @($admins | Where-Object { $_ -ieq ('{0}\{1}' -f $env:COMPUTERNAME, $name) })
        if ($isAdmin.Count -gt 0) { Write-Host '  [警告] 管理者グループに所属しています。サービスアカウントには不要です。' -ForegroundColor Yellow }
        $using = @(Get-UsingServices -Name $name)
        if ($using.Count -gt 0) { Write-Host ('  使用中のサービス: {0}' -f (($using | ForEach-Object { '{0}({1})' -f $_.Name, $_.State }) -join ', ')) }
        else { Write-Host '  使用中のサービス: なし' }
    }
    if (-not (Test-Unresolved $server.data_dir)) {
        if (Test-Path -LiteralPath $server.data_dir) {
            Write-Host ('データフォルダのACL: {0}' -f $server.data_dir)
            & icacls.exe $server.data_dir | ForEach-Object { Write-Host ('  ' + $_) }
        }
        else { Write-Host ('データフォルダは未作成です: {0}' -f $server.data_dir) }
    }
}

# ---- 実行 -----------------------------------------------------------------
switch ($Action) {
    'Create' { Invoke-Create }
    'Delete' { Invoke-Delete }
    'Show' { Invoke-Show }
}
