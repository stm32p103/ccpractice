<#
.SYNOPSIS
    開発環境(core パッケージのテスト環境)を構築・検証・撤去する。何度実行してもよい(冪等)。

.DESCRIPTION
    1. 事前確認(PowerShell の版、設定の検証)
    2. uv の確認(版が一致する uv が無ければ、公式のリリースから取得し、SHA-256 を検証して展開)
    3. Python の確認(最低版以上が無ければ uv で導入)
    4. PowerShell のモジュール(Pester、PSScriptAnalyzer)を ops/dev/.cache に取得し、ギャラリーのハッシュで検証
    5. uv sync --locked(uv.lock のハッシュで検証)
    取得先は書き出し台帳 E15(公式の配布元・公式のパッケージ索引。取得のみ)に限る。秘密情報は扱わない。

.PARAMETER VerifyOnly
    構築はせず、quickstart.md の検証 V1〜V18 を順に実行して結果の一覧を表示する。

.PARAMETER Uninstall
    .venv と ops/dev/.cache を削除する。

.EXAMPLE
    .\ops\dev\setup-dev.ps1 -WhatIf
.EXAMPLE
    .\ops\dev\setup-dev.ps1
.EXAMPLE
    .\ops\dev\setup-dev.ps1 -VerifyOnly
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$VerifyOnly,
    [switch]$Uninstall,
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'dev.config.psd1')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-DevLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Information "[setup-dev] $Message" -InformationAction Continue
}

function Invoke-DevNativeCommand {
    # 外部コマンドを実行し、標準出力と標準エラーを文字列の配列で返す。
    # Windows PowerShell 5.1 では、$ErrorActionPreference = 'Stop' のまま標準エラーを捕捉すると停止するため、ここだけ Continue にする。
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @()
    )
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& $FilePath @ArgumentList 2>&1 | ForEach-Object { [string]$_ })
        return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $output }
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Get-DevRepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
}

function Import-DevConfig {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "設定ファイルが見つかりません: $Path"
    }
    $config = Import-PowerShellDataFile -LiteralPath $Path
    foreach ($key in @('AllowedDomains', 'CacheDir', 'Uv', 'PythonMinVersion', 'PythonVersion', 'Modules')) {
        if (-not $config.ContainsKey($key)) {
            throw "設定ファイルに $key がありません: $Path"
        }
    }
    foreach ($key in @('Version', 'ArchiveUrl', 'Sha256')) {
        if ([string]::IsNullOrWhiteSpace([string]$config.Uv[$key])) {
            throw "設定ファイルの Uv.$key が空です。公式のリリースの値を設定してください"
        }
    }
    $config.CacheFullPath = [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $Path) $config.CacheDir))
    return $config
}

function Test-DevPrerequisite {
    if ($PSVersionTable.PSVersion -lt [version]'5.1') {
        throw "Windows PowerShell 5.1 以上が必要です(現在: $($PSVersionTable.PSVersion))"
    }
    Write-DevLog "事前確認: PowerShell $($PSVersionTable.PSVersion)"
}

function Assert-DevAllowedUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string[]]$AllowedDomains
    )
    $uri = [Uri]$Url
    if ($uri.Scheme -ne 'https') {
        throw "HTTPS 以外の取得は許可していません: $Url"
    }
    if ($AllowedDomains -notcontains $uri.Host) {
        throw "許可リストにないドメインからの取得は許可していません: $($uri.Host)"
    }
}

function Save-DevDownload {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $previous = $ProgressPreference
    try {
        $ProgressPreference = 'SilentlyContinue'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination
    }
    finally {
        $ProgressPreference = $previous
    }
}

function Test-DevFileHash {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateSet('SHA256', 'SHA512')][string]$Algorithm,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    $hasher = [Security.Cryptography.HashAlgorithm]::Create($Algorithm)
    $stream = [IO.File]::OpenRead($Path)
    try {
        $bytes = $hasher.ComputeHash($stream)
    }
    finally {
        $stream.Dispose()
        $hasher.Dispose()
    }
    $hex = -join ($bytes | ForEach-Object { $_.ToString('x2') })
    $base64 = [Convert]::ToBase64String($bytes)
    return ($hex -eq $Expected.ToLowerInvariant()) -or ($base64 -eq $Expected)
}

function Get-DevUvVersion {
    param([Parameter(Mandatory = $true)][string]$UvPath)
    $output = & $UvPath --version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
    $parts = ([string]$output).Split(' ')
    if ($parts.Length -lt 2) { return $null }
    return $parts[1]
}

function Install-DevUv {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param([Parameter(Mandatory = $true)][hashtable]$Config)

    $wanted = $Config.Uv.Version
    $onPath = Get-Command uv -ErrorAction SilentlyContinue
    if ($onPath -and (Get-DevUvVersion -UvPath $onPath.Source) -eq $wanted) {
        Write-DevLog "uv ${wanted}: 変更なし(PATH 上の $($onPath.Source) を使用)"
        return $onPath.Source
    }
    $uvDir = Join-Path $Config.CacheFullPath "uv\$wanted"
    $uvExe = Join-Path $uvDir 'uv.exe'
    if ((Test-Path -LiteralPath $uvExe) -and (Get-DevUvVersion -UvPath $uvExe) -eq $wanted) {
        Write-DevLog "uv ${wanted}: 変更なし($uvExe を使用)"
        return $uvExe
    }
    if (-not $PSCmdlet.ShouldProcess($Config.Uv.ArchiveUrl, "uv $wanted を取得して $uvDir に展開")) {
        return $null
    }
    Assert-DevAllowedUrl -Url $Config.Uv.ArchiveUrl -AllowedDomains $Config.AllowedDomains
    $downloadDir = Join-Path $Config.CacheFullPath 'downloads'
    New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
    $archive = Join-Path $downloadDir "uv-$wanted.zip"
    Save-DevDownload -Url $Config.Uv.ArchiveUrl -Destination $archive
    if (-not (Test-DevFileHash -Path $archive -Algorithm 'SHA256' -Expected $Config.Uv.Sha256)) {
        Remove-Item -LiteralPath $archive -Force
        throw "uv の取得物の SHA-256 が設定の値と一致しません。導入を中止しました"
    }
    New-Item -ItemType Directory -Force -Path $uvDir | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $uvDir -Force
    Remove-Item -LiteralPath $archive -Force
    Write-DevLog "uv ${wanted}: 導入しました($uvExe)"
    return $uvExe
}

function Install-DevPython {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true)][string]$UvPath,
        [Parameter(Mandatory = $true)][hashtable]$Config
    )
    $found = & $UvPath python find ">=$($Config.PythonMinVersion)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $found) {
        Write-DevLog "Python >= $($Config.PythonMinVersion): 変更なし($found)"
        return
    }
    if ($PSCmdlet.ShouldProcess("Python $($Config.PythonVersion)", 'uv python install')) {
        $result = Invoke-DevNativeCommand -FilePath $UvPath -ArgumentList @('python', 'install', $Config.PythonVersion)
        $result.Output | ForEach-Object { Write-DevLog $_ }
        if ($result.ExitCode -ne 0) { throw "Python $($Config.PythonVersion) の導入に失敗しました" }
        Write-DevLog "Python $($Config.PythonVersion): 導入しました"
    }
}

function Install-DevPowerShellModule {
    [CmdletBinding(SupportsShouldProcess = $true)]
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $true)][hashtable]$Module,
        [Parameter(Mandatory = $true)][hashtable]$Config
    )
    $target = Join-Path $Config.CacheFullPath "modules\$($Module.Name)\$($Module.Version)"
    if (Test-Path -LiteralPath (Join-Path $target "$($Module.Name).psd1")) {
        Write-DevLog "$($Module.Name) $($Module.Version): 変更なし"
        return 'unchanged'
    }
    if (-not $PSCmdlet.ShouldProcess($Module.Url, "$($Module.Name) $($Module.Version) を取得して $target に展開")) {
        return 'skipped'
    }
    Assert-DevAllowedUrl -Url $Module.Url -AllowedDomains $Config.AllowedDomains
    $downloadDir = Join-Path $Config.CacheFullPath 'downloads'
    New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
    $package = Join-Path $downloadDir "$($Module.Name).$($Module.Version).zip"
    Save-DevDownload -Url $Module.Url -Destination $package
    if (-not (Test-DevFileHash -Path $package -Algorithm $Module.HashAlgorithm -Expected $Module.Hash)) {
        Remove-Item -LiteralPath $package -Force
        throw "$($Module.Name) の取得物のハッシュが設定の値と一致しません。導入を中止しました"
    }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Expand-Archive -LiteralPath $package -DestinationPath $target -Force
    Remove-Item -LiteralPath $package -Force
    foreach ($meta in @('_rels', 'package', '[Content_Types].xml', "$($Module.Name).nuspec")) {
        $metaPath = Join-Path $target $meta
        if (Test-Path -LiteralPath $metaPath) { Remove-Item -LiteralPath $metaPath -Recurse -Force }
    }
    Write-DevLog "$($Module.Name) $($Module.Version): 導入しました"
    return 'installed'
}

function Invoke-DevSync {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param([Parameter(Mandatory = $true)][string]$UvPath)
    if (-not $PSCmdlet.ShouldProcess('uv.lock', 'uv sync --locked')) { return }
    Push-Location (Get-DevRepositoryRoot)
    try {
        $result = Invoke-DevNativeCommand -FilePath $UvPath -ArgumentList @('sync', '--locked')
        if ($result.ExitCode -ne 0) {
            $result.Output | ForEach-Object { Write-DevLog $_ }
            throw 'uv sync --locked に失敗しました(uv.lock と食い違う場合は、レビューを経て uv.lock を更新してください)'
        }
        $changed = @($result.Output | Where-Object { $_ -match '^\s*(Installed|Uninstalled)\b' })
        if ($changed.Count -gt 0) {
            Write-DevLog "Python のパッケージ: 同期しました($($changed -join ', '))"
        }
        else {
            Write-DevLog 'Python のパッケージ: 変更なし'
        }
    }
    finally {
        Pop-Location
    }
}

function Get-DevModulePath {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Config,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $module = $Config.Modules | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if (-not $module) { throw "設定に $Name がありません" }
    return Join-Path $Config.CacheFullPath "modules\$Name\$($module.Version)\$Name.psd1"
}

function Invoke-DevVerification {
    # UvPath は検証の各スクリプトブロックの中で使う(解析器は検出できない)
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', 'UvPath')]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory = $true)][string]$UvPath,
        [Parameter(Mandatory = $true)][hashtable]$Config
    )
    $root = Get-DevRepositoryRoot
    $pester = Get-DevModulePath -Config $Config -Name 'Pester'
    $analyzer = Get-DevModulePath -Config $Config -Name 'PSScriptAnalyzer'
    $powershell = (Get-Process -Id $PID).Path
    $pesterCommand = "Import-Module '$pester' -Force; " +
        "`$r = Invoke-Pester -Path '$root\ops\dev\tests' -PassThru -Output Detailed; " +
        "if (`$r.FailedCount -gt 0) { exit 1 }"
    $analyzerCommand = "Import-Module '$analyzer' -Force; " +
        "`$f = @('setup-dev.ps1', 'dev.config.psd1', 'tests\setup-dev.Tests.ps1') | " +
        "ForEach-Object { Invoke-ScriptAnalyzer -Path (Join-Path '$root\ops\dev' `$_) }; " +
        "`$f | Format-Table -AutoSize | Out-String | Write-Output; " +
        "if (@(`$f).Count -gt 0) { exit 1 }"

    $checks = @(
        @{ Id = 'V1'; Name = 'ドメインの単体テスト'; Command = { & $UvPath run pytest core/tests/unit } }
        @{ Id = 'V2'; Name = '受け入れシナリオ'; Command = { & $UvPath run pytest core/tests/acceptance } }
        @{ Id = 'V3'; Name = '権限の網羅'; Command = { & $UvPath run pytest core/tests/unit/test_authorization.py } }
        @{ Id = 'V4'; Name = 'ポートの契約テスト(Fake)'; Command = { & $UvPath run pytest testing/tests } }
        @{ Id = 'V5'; Name = '同時実行のシナリオ'; Command = { & $UvPath run pytest core/tests/acceptance -k concurrency } }
        @{ Id = 'V6'; Name = '依存規則'; Command = { & $UvPath run lint-imports } }
        @{ Id = 'V7'; Name = '語彙・標準ライブラリのみ・禁止 API'; Command = { & $UvPath run pytest core/tests/architecture } }
        @{ Id = 'V8'; Name = 'イベントのスキーマと機密'; Command = { & $UvPath run pytest core/tests/contract/test_job_completed_event.py } }
        @{ Id = 'V9'; Name = '性能の目安'; Command = { & $UvPath run pytest core/tests/perf -m perf } }
        @{ Id = 'V10'; Name = '静的検査(ruff、mypy)'; Command = {
                & $UvPath run ruff check
                if ($LASTEXITCODE -eq 0) { & $UvPath run mypy --strict core/src testing/src }
            }
        }
        @{ Id = 'V11'; Name = 'スクリプトの検査(Pester、PSScriptAnalyzer)'; Command = {
                & $powershell -NoProfile -NonInteractive -Command $pesterCommand
                if ($LASTEXITCODE -eq 0) { & $powershell -NoProfile -NonInteractive -Command $analyzerCommand }
            }
        }
        @{ Id = 'V12'; Name = '照合の単体テスト'; Command = { & $UvPath run pytest core/tests/unit/runner/test_matching.py } }
        @{ Id = 'V13'; Name = 'ランナーの状態の導出・リースの遷移'; Command = { & $UvPath run pytest core/tests/unit/runner } }
        @{ Id = 'V14'; Name = 'ランナー管理の受け入れシナリオ'; Command = { & $UvPath run pytest core/tests/acceptance/runner } }
        @{ Id = 'V15'; Name = '判定と割り当ての一致'; Command = {
                & $UvPath run pytest core/tests/acceptance/runner -k eligibility_consistency
            }
        }
        @{ Id = 'V16'; Name = '権限の網羅(12 権限)'; Command = { & $UvPath run pytest core/tests/unit/test_authorization.py core/tests/unit/runner/test_authorization.py } }
        @{ Id = 'V17'; Name = 'トークンの非露出・ランナー管理の同時実行'; Command = {
                & $UvPath run pytest core/tests/acceptance/runner -k 'token or concurrency'
            }
        }
        @{ Id = 'V18'; Name = '割り当ての性能の目安'; Command = { & $UvPath run pytest core/tests/perf -m perf -k request_job } }
    )

    $results = @()
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $root
    try {
        foreach ($check in $checks) {
            Write-DevLog "$($check.Id) $($check.Name) を実行します"
            $global:LASTEXITCODE = 0
            & $check.Command | ForEach-Object { Write-Information ([string]$_) -InformationAction Continue }
            $passed = ($LASTEXITCODE -eq 0)
            $results += [pscustomobject]@{ Id = $check.Id; Name = $check.Name; Result = $(if ($passed) { '成功' } else { '失敗' }) }
        }
    }
    finally {
        Pop-Location
        $ErrorActionPreference = $previous
    }
    $results | Format-Table -AutoSize | Out-String | ForEach-Object { Write-DevLog $_ }
    return @($results | Where-Object { $_.Result -ne '成功' }).Count -eq 0
}

function Remove-DevEnvironment {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param(
        [Parameter(Mandatory = $true)][string]$CacheDir,
        [Parameter(Mandatory = $true)][string]$VenvDir
    )
    foreach ($path in @($VenvDir, $CacheDir)) {
        if (-not (Test-Path -LiteralPath $path)) {
            Write-DevLog "${path}: 変更なし(存在しません)"
            continue
        }
        if ($PSCmdlet.ShouldProcess($path, '削除')) {
            Remove-Item -LiteralPath $path -Recurse -Force
            Write-DevLog "${path}: 削除しました"
        }
    }
}

function Invoke-DevSetup {
    [CmdletBinding(SupportsShouldProcess = $true)]
    [OutputType([bool])]
    param(
        [switch]$VerifyOnly,
        [switch]$Uninstall,
        [Parameter(Mandatory = $true)][string]$ConfigPath
    )
    Test-DevPrerequisite
    $config = Import-DevConfig -Path $ConfigPath

    if ($Uninstall) {
        Remove-DevEnvironment -CacheDir $config.CacheFullPath -VenvDir (Join-Path (Get-DevRepositoryRoot) '.venv')
        return $true
    }

    $uv = Install-DevUv -Config $config
    if (-not $uv) {
        Write-DevLog 'ドライランのため、以降の手順は表示のみです'
        $uv = 'uv'
    }

    if ($VerifyOnly) {
        return Invoke-DevVerification -UvPath $uv -Config $config
    }

    Install-DevPython -UvPath $uv -Config $config
    foreach ($module in $config.Modules) {
        Install-DevPowerShellModule -Module $module -Config $config | Out-Null
    }
    Invoke-DevSync -UvPath $uv
    Write-DevLog '構築が完了しました。検証は -VerifyOnly で実行できます'
    return $true
}

if ($MyInvocation.InvocationName -ne '.') {
    $ok = Invoke-DevSetup -VerifyOnly:$VerifyOnly -Uninstall:$Uninstall -ConfigPath $ConfigPath
    if (-not $ok) { exit 1 }
}
