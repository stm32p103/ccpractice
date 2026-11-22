# 開発環境の構築(ops/dev/setup-dev.ps1)の設定。秘密情報は含めない。
# 取得先は書き出し台帳 E15(公式の配布元・公式のパッケージ索引。取得のみ)に限る。
# 版を上げるときは、各配布元が公式に公開しているハッシュの値に置き換え、レビューを受ける。
@{
    # 取得を許可するドメイン(HTTPS のみ)。これ以外の URL からは取得しない。
    AllowedDomains = @(
        'github.com'                                  # uv の公式のリリース
        'objects.githubusercontent.com'               # 同上(リダイレクト先)
        'release-assets.githubusercontent.com'        # 同上(リダイレクト先)
        'www.powershellgallery.com'                   # PowerShell のモジュールの公式の配布元
        'psg-prod-eastus.azureedge.net'               # 同上(リダイレクト先)
        'pypi.org'                                    # Python のパッケージの公式の索引(uv sync)
        'files.pythonhosted.org'                      # 同上
        'get.enterprisedb.com'                        # PostgreSQL の公式の Windows 用バイナリ(zip)の配布元(台帳 E15。003 T002 で承認)
    )

    # 取得物の置き場所(この設定ファイルからの相対パス)
    CacheDir = '.cache'

    # uv(公式のリリース。SHA-256 は公式の .sha256 ファイルの値)
    Uv = @{
        Version    = '0.13.5'
        ArchiveUrl = 'https://github.com/astral-sh/uv/releases/download/0.13.5/uv-x86_64-pc-windows-msvc.zip'
        Sha256     = 'a38b8d1902b7cfbc76b423ba1bb456f623f42064cdc72628b6075b89afd1019a'
    }

    # Python: この版以上が見つからなければ、uv で PythonVersion を導入する
    PythonMinVersion = '3.12'
    PythonVersion    = '3.12'

    # PostgreSQL(公式の Windows 用バイナリの zip。003 の実 DB の試験用。-WithPostgres のときだけ取得する)。
    # Sha256 は、配布元の公式の公開値、または公式の配布物から一度計算して、レビューを受けて固定する。
    # 下の 0 だけの値は未確定を示し、この値のままでは、ハッシュの不一致として取得物を破棄して停止する。
    PostgreSql = @{
        Version    = '16.4'
        ArchiveUrl = 'https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64-binaries.zip'
        Sha256     = '0000000000000000000000000000000000000000000000000000000000000000'
        Port       = 54329
    }

    # PowerShell のモジュール(PowerShell Gallery。ハッシュはギャラリーが公開する PackageHash)
    Modules = @(
        @{
            Name          = 'Pester'
            Version       = '5.7.1'
            Url           = 'https://www.powershellgallery.com/api/v2/package/Pester/5.7.1'
            HashAlgorithm = 'SHA512'
            Hash          = 'TZlqSN2UgW0mtOnmk1ro5sy8Gfg5DqOCY0XxIeHOKufM4WNptRfBkM6tBev/AxI/gmarvTVWBK3V8SnCTc8oAg=='
        }
        @{
            Name          = 'PSScriptAnalyzer'
            Version       = '1.24.0'
            Url           = 'https://www.powershellgallery.com/api/v2/package/PSScriptAnalyzer/1.24.0'
            HashAlgorithm = 'SHA512'
            Hash          = 'B8yVwiGkpN9LU8q7cBZHgBtBIAKgW+FbpVA/ZtSHD65K1FWFTT7nSVfehKL2OuoyufPf8VNcaRfHUTB3Rb3RZQ=='
        }
    )
}
