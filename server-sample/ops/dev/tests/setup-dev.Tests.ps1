# Pester 5 のテスト。ops/dev/setup-dev.ps1 の関数を読み込んで検査する(ネットワークには接続しない)。
BeforeAll {
    $script:SetupScript = Join-Path $PSScriptRoot '..\setup-dev.ps1'
    . $script:SetupScript

    function Write-TestConfigFile {
        param([string]$Directory, [string]$UvSha256 = ('0' * 64), [string]$ModuleHash = 'AAAA')
        $content = @"
@{
    AllowedDomains = @('github.com', 'www.powershellgallery.com')
    CacheDir = 'cache'
    Uv = @{ Version = '0.0.0-test'; ArchiveUrl = 'https://github.com/example/uv.zip'; Sha256 = '$UvSha256' }
    PythonMinVersion = '3.12'
    PythonVersion = '3.12'
    Modules = @(
        @{ Name = 'Dummy'; Version = '1.0.0'; Url = 'https://www.powershellgallery.com/api/v2/package/Dummy/1.0.0'; HashAlgorithm = 'SHA512'; Hash = '$ModuleHash' }
    )
}
"@
        $path = Join-Path $Directory 'test.config.psd1'
        Set-Content -LiteralPath $path -Value $content -Encoding UTF8
        return $path
    }
}

Describe 'Import-DevConfig' {
    It '必須の項目があれば読み込み、取得物の置き場所を絶対パスにする' {
        $path = Write-TestConfigFile -Directory $TestDrive
        $config = Import-DevConfig -Path $path
        $config.CacheFullPath | Should -Be ([IO.Path]::GetFullPath((Join-Path $TestDrive 'cache')))
    }

    It 'uv のハッシュが空なら停止する' {
        $path = Write-TestConfigFile -Directory $TestDrive -UvSha256 ''
        { Import-DevConfig -Path $path } | Should -Throw '*Uv.Sha256*'
    }

    It '同梱の設定ファイルを読み込める' {
        $config = Import-DevConfig -Path (Join-Path $PSScriptRoot '..\dev.config.psd1')
        $config.Uv.Sha256.Length | Should -Be 64
    }
}

Describe 'Assert-DevAllowedUrl' {
    It '許可したドメインの HTTPS は通す' {
        { Assert-DevAllowedUrl -Url 'https://github.com/x' -AllowedDomains @('github.com') } | Should -Not -Throw
    }

    It 'HTTPS 以外は拒否する' {
        { Assert-DevAllowedUrl -Url 'http://github.com/x' -AllowedDomains @('github.com') } | Should -Throw '*HTTPS*'
    }

    It '許可リストにないドメインは拒否する' {
        { Assert-DevAllowedUrl -Url 'https://example.com/x' -AllowedDomains @('github.com') } | Should -Throw '*許可リスト*'
    }
}

Describe 'Test-DevFileHash' {
    It 'SHA-256(16 進)と SHA-512(Base64)の一致・不一致を判定する' {
        $file = Join-Path $TestDrive 'data.bin'
        [IO.File]::WriteAllBytes($file, [Text.Encoding]::ASCII.GetBytes('abc'))
        $sha256 = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
        Test-DevFileHash -Path $file -Algorithm 'SHA256' -Expected $sha256 | Should -BeTrue
        Test-DevFileHash -Path $file -Algorithm 'SHA256' -Expected ('0' * 64) | Should -BeFalse
        $sha512 = [Convert]::ToBase64String([Security.Cryptography.SHA512]::Create().ComputeHash([Text.Encoding]::ASCII.GetBytes('abc')))
        Test-DevFileHash -Path $file -Algorithm 'SHA512' -Expected $sha512 | Should -BeTrue
    }
}

Describe 'Install-DevUv' {
    BeforeEach {
        Mock Get-Command { $null } -ParameterFilter { $Name -eq 'uv' }
        Mock Save-DevDownload { Set-Content -LiteralPath $Destination -Value 'not-the-official-archive' }
    }

    It 'ハッシュが一致しなければ停止し、何も導入しない' {
        $config = Import-DevConfig -Path (Write-TestConfigFile -Directory $TestDrive)
        { Install-DevUv -Config $config } | Should -Throw '*SHA-256*'
        Test-Path (Join-Path $config.CacheFullPath 'uv\0.0.0-test\uv.exe') | Should -BeFalse
        @(Get-ChildItem (Join-Path $config.CacheFullPath 'downloads')).Count | Should -Be 0
    }

    It 'ドライランでは取得しない' {
        $dir = (New-Item -ItemType Directory -Path (Join-Path $TestDrive 'whatif')).FullName
        $config = Import-DevConfig -Path (Write-TestConfigFile -Directory $dir)
        Install-DevUv -Config $config -WhatIf | Should -BeNullOrEmpty
        Should -Invoke Save-DevDownload -Times 0
        Test-Path $config.CacheFullPath | Should -BeFalse
    }
}

Describe 'Install-DevPowerShellModule' {
    It '導入済みなら取得せず「変更なし」を返す(冪等)' {
        Mock Save-DevDownload { throw 'ネットワークに接続してはならない' }
        $config = Import-DevConfig -Path (Write-TestConfigFile -Directory $TestDrive)
        $target = Join-Path $config.CacheFullPath 'modules\Dummy\1.0.0'
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        Set-Content -LiteralPath (Join-Path $target 'Dummy.psd1') -Value '@{}'
        Install-DevPowerShellModule -Module $config.Modules[0] -Config $config | Should -Be 'unchanged'
        Should -Invoke Save-DevDownload -Times 0
    }

    It 'ハッシュが一致しなければ停止し、展開しない' {
        Mock Save-DevDownload { Set-Content -LiteralPath $Destination -Value 'tampered' }
        $config = Import-DevConfig -Path (Write-TestConfigFile -Directory (New-Item -ItemType Directory -Path (Join-Path $TestDrive 'm2')).FullName)
        { Install-DevPowerShellModule -Module $config.Modules[0] -Config $config } | Should -Throw '*ハッシュ*'
        Test-Path (Join-Path $config.CacheFullPath 'modules\Dummy\1.0.0') | Should -BeFalse
    }
}

Describe 'Install-DevPostgreSql' {
    BeforeAll {
        function Write-PgConfig {
            param([string]$Directory, [string]$Sha256, [string]$Domain = 'github.com')
            $content = @"
@{
    AllowedDomains = @('$Domain')
    CacheDir = 'cache'
    Uv = @{ Version = '0.0.0-test'; ArchiveUrl = 'https://github.com/example/uv.zip'; Sha256 = '$('0' * 64)' }
    PostgreSql = @{ Version = '1.0'; ArchiveUrl = 'https://github.com/example/pg.zip'; Sha256 = '$Sha256'; Port = 54329 }
    PythonMinVersion = '3.12'
    PythonVersion = '3.12'
    Modules = @()
}
"@
            $path = Join-Path $Directory 'pg.config.psd1'
            Set-Content -LiteralPath $path -Value $content -Encoding UTF8
            return $path
        }
    }

    It 'ハッシュが一致しなければ、取得物を破棄して停止し、展開しない' {
        Mock Save-DevDownload { Set-Content -LiteralPath $Destination -Value 'tampered' }
        $config = Import-DevConfig -Path (Write-PgConfig -Directory (New-Item -ItemType Directory -Path (Join-Path $TestDrive 'pg1')).FullName -Sha256 ('0' * 64))
        { Install-DevPostgreSql -Config $config } | Should -Throw '*SHA-256*'
        Test-Path (Join-Path $config.CacheFullPath 'postgresql\1.0') | Should -BeFalse
        Test-Path (Join-Path $config.CacheFullPath 'downloads\postgresql-1.0.zip') | Should -BeFalse
    }

    It '許可リスト外の取得先は拒否し、取得しない' {
        Mock Save-DevDownload { }
        $config = Import-DevConfig -Path (Write-PgConfig -Directory (New-Item -ItemType Directory -Path (Join-Path $TestDrive 'pg2')).FullName -Sha256 ('0' * 64) -Domain 'example.org')
        { Install-DevPostgreSql -Config $config } | Should -Throw
        Should -Invoke Save-DevDownload -Times 0
    }

    It '導入済みなら変更しない(取得しない。冪等)' {
        Mock Save-DevDownload { }
        $config = Import-DevConfig -Path (Write-PgConfig -Directory (New-Item -ItemType Directory -Path (Join-Path $TestDrive 'pg3')).FullName -Sha256 ('0' * 64))
        $bin = Join-Path $config.CacheFullPath 'postgresql\1.0\pgsql\bin'
        New-Item -ItemType Directory -Force -Path $bin | Out-Null
        Set-Content -LiteralPath (Join-Path $bin 'initdb.exe') -Value 'x'
        Install-DevPostgreSql -Config $config | Should -Be $bin
        Should -Invoke Save-DevDownload -Times 0
    }

    It 'ドライランでは取得しない' {
        Mock Save-DevDownload { }
        $config = Import-DevConfig -Path (Write-PgConfig -Directory (New-Item -ItemType Directory -Path (Join-Path $TestDrive 'pg4')).FullName -Sha256 ('0' * 64))
        Install-DevPostgreSql -Config $config -WhatIf | Should -BeNullOrEmpty
        Should -Invoke Save-DevDownload -Times 0
    }

    It '設定の PostgreSQL の取得先は、許可リストの中にあり、既定のハッシュは未確定(0 だけ)で取得物を通さない' {
        $config = Import-DevConfig -Path (Join-Path $PSScriptRoot '..\dev.config.psd1')
        $hostName = ([uri]$config.PostgreSql.ArchiveUrl).Host
        $config.AllowedDomains | Should -Contain $hostName
        $config.PostgreSql.ArchiveUrl | Should -BeLike 'https://*'
        $config.PostgreSql.Sha256 | Should -Match '^[0-9a-fA-F]{64}$'
    }
}

Describe 'Remove-DevPostgresInstance' {
    It 'インスタンスがなければ変更しない(撤去は冪等)' {
        $config = @{ CacheFullPath = (Join-Path $TestDrive 'pg-none'); PostgreSql = @{ Version = '1.0' } }
        { Remove-DevPostgresInstance -Config $config } | Should -Not -Throw
    }
}

Describe 'Remove-DevEnvironment' {
    It '取得物と仮想環境を削除し、再実行しても失敗しない' {
        $cache = Join-Path $TestDrive 'cache-rm'
        $venv = Join-Path $TestDrive 'venv-rm'
        New-Item -ItemType Directory -Force -Path $cache, $venv | Out-Null
        Remove-DevEnvironment -CacheDir $cache -VenvDir $venv
        Test-Path $cache | Should -BeFalse
        Test-Path $venv | Should -BeFalse
        { Remove-DevEnvironment -CacheDir $cache -VenvDir $venv } | Should -Not -Throw
    }

    It 'ドライランでは削除しない' {
        $cache = Join-Path $TestDrive 'cache-whatif'
        New-Item -ItemType Directory -Force -Path $cache | Out-Null
        Remove-DevEnvironment -CacheDir $cache -VenvDir (Join-Path $TestDrive 'none') -WhatIf
        Test-Path $cache | Should -BeTrue
    }
}

Describe 'Invoke-DevVerification の検証の一覧' {
    It 'V1 から V34 までを、この順に定義している' {
        $text = Get-Content -LiteralPath $script:SetupScript -Raw
        $ids = [regex]::Matches($text, "Id = 'V(\d+)'") | ForEach-Object { [int]$_.Groups[1].Value }
        $ids | Should -Be (1..34)
    }

    It 'PostgreSQL を使う V26 だけが、前提(Precondition)を持つ' {
        $text = Get-Content -LiteralPath $script:SetupScript -Raw
        $matches26 = [regex]::Matches($text, 'Precondition = ')
        $matches26.Count | Should -Be 1
        $text.IndexOf("Id = 'V26'") | Should -BeLessThan $text.IndexOf('Precondition = ')
        $text.IndexOf('Precondition = ') | Should -BeLessThan $text.IndexOf("Id = 'V27'")
    }
}

Describe 'Test-DevPostgresAvailable' {
    It '接続先の環境変数があれば使える' {
        $previous = $env:JOB_TEST_POSTGRES_DSN
        try {
            $env:JOB_TEST_POSTGRES_DSN = 'postgresql://example.invalid/db'
            Test-DevPostgresAvailable | Should -BeTrue
        }
        finally { $env:JOB_TEST_POSTGRES_DSN = $previous }
    }

    It '接続先も initdb もなければ使えない(取得はしない)' {
        $previous = $env:JOB_TEST_POSTGRES_DSN
        try {
            $env:JOB_TEST_POSTGRES_DSN = ''
            Mock Get-Command { $null } -ParameterFilter { $Name -eq 'initdb' }
            Test-DevPostgresAvailable | Should -BeFalse
            Should -Invoke Get-Command -Times 1 -ParameterFilter { $Name -eq 'initdb' }
        }
        finally { $env:JOB_TEST_POSTGRES_DSN = $previous }
    }

    It '前提を満たさない検証は、保留として報告し、失敗に数えない' {
        $text = Get-Content -LiteralPath $script:SetupScript -Raw
        $text | Should -Match "Result = '保留'"
        $text.Contains('$_.Result -eq ''失敗''') | Should -BeTrue
    }
}
