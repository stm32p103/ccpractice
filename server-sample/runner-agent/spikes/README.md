# スパイク(T001)の実施手順

2 アカウント方式(`specs/004-runner-agent/research.md` R4)が成立するかを確かめる検証の手順。
スクリプトは [logon_spike.py](logon_spike.py)。**本体(`job_runner_agent`)から import しない**。

検査項目:

| # | 内容 |
|---|---|
| 1 | ログオン付きの生成(`CreateProcessWithLogonW`)を一時停止で行い、Job Object へ割り当てて再開できる |
| 2 | 環境ブロックを空から渡せる(親の環境が子に見えない) |
| 3 | ツールのアカウントが、作業フォルダ以外(`--secret-file`)を読めない |
| 4 | `TerminateJobObject` で子・孫まで止まる |
| 5 | エージェントの強制終了で子・孫が終了する(`--crash`) |

実施の段階:

- **A. 対話セッションで確認する**(項目 1〜5)。2026-11-24 に実施し、すべて OK(結果は research.md R4)。
- **B. サービスの文脈(非対話・セッション 0)で確認する**(項目 1〜4)。T001 を完了にするには、これも要る。

手順は、PowerShell(管理者権限)で、リポジトリのルートから実行する。パスは例なので、環境に読み替える。

## 0. アカウントとフォルダの準備(A・B 共通)

資格・パスワードは、この検証の間だけ使う値にする。終わったら 6 で削除する。

```powershell
# ツールのアカウント(検証用)。パスワードは自分の端末で入力する
$pw = Read-Host -AsSecureString "tool password"
New-LocalUser -Name svc-spike-tool -Password $pw -PasswordNeverExpires

# 作業フォルダと、ツールのアカウントが読めないはずのファイル
New-Item -ItemType Directory -Force D:\runner\work\spike | Out-Null
Set-Content D:\runner\secret-outside.txt "dummy-secret"

# 親の継承を切り、読み取りの権限を、自分と管理者だけにする(ドライブのルートの既定は
# Authenticated Users に読み取りを許すため、継承したままだと項目 3 が成立しない)
icacls D:\runner /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)(F)" "Administrators:(OI)(CI)(F)"
# 作業フォルダだけに、ツールのアカウントの変更権限を与える
icacls D:\runner\work\spike /grant "svc-spike-tool:(OI)(CI)M"
# 親フォルダを辿れるように、トラバースだけを与える(読み取りは与えない)
icacls D:\runner /grant "svc-spike-tool:(X)"
```

## A. 対話セッションでの実行

```powershell
# 資格は、組み立てを確認してから設定する($() で囲まないと、コロンが変数名に取り込まれる)
$env:SPIKE_TOOL_ACCOUNT = "$($env:COMPUTERNAME)\svc-spike-tool:<パスワード>"
$env:PARENT_DUMMY_SECRET = "x"          # 項目 2 の確認用(子に見えてはならない)

# 項目 1〜4(項目 3 以外 true で、終了コードが 0)
uv run python -I runner-agent/spikes/logon_spike.py --work D:\runner\work\spike --secret-file D:\runner\secret-outside.txt

# 項目 5。強制終了の直後に、別の端末で下を実行して、ツールのアカウントの python.exe が 0 件であることを確かめる
uv run python -I runner-agent/spikes/logon_spike.py --work D:\runner\work\spike --secret-file D:\runner\secret-outside.txt --crash
```

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  ForEach-Object {
    $o = Invoke-CimMethod -InputObject $_ -MethodName GetOwner
    [pscustomobject]@{ Pid=$_.ProcessId; Owner="$($o.Domain)\$($o.User)"; Cmd=$_.CommandLine.Substring(0,[Math]::Min(60,$_.CommandLine.Length)) }
  } | Where-Object Owner -like '*svc-spike-tool*'
```

子は 120 秒でスリープを終える。確認は、`--crash` の直後に行う。

注意: `tool_account` が `null` になるのは正常(環境が空のため、子から `USERNAME` が見えない)。

## B. サービスの文脈での実行(WinSW)

サービスの実行アカウントは、本番と同じく、ツールのアカウントとは別のアカウント(エージェント用)にする。
サービスの下では、非対話(セッション 0)で動く。結果は、サービスのログ(標準出力)に出る。

### B-1. エージェント用のアカウントとフォルダ

```powershell
$pw2 = Read-Host -AsSecureString "agent password"
New-LocalUser -Name svc-spike-agent -Password $pw2 -PasswordNeverExpires

# エージェント用のアカウントが、スクリプトと Python を読めること、作業フォルダへ書けること
icacls D:\runner /grant "svc-spike-agent:(OI)(CI)M"
New-Item -ItemType Directory -Force D:\runner\svc | Out-Null
```

- リポジトリ(`e:\claude\job_pf\server-sample`)と、`.venv` の Python の実体(`uv` が管理する Python の場所)を、
  エージェント用のアカウントが読み取り・実行できる必要がある。ユーザーのプロファイルの下(`C:\Users\<あなた>\...`)に
  あると、既定では読めない。その場合は、読み取りの権限を与えるか、リポジトリと Python を、読める場所へ置く。
- `--secret-file` は、ツールのアカウントには読めず、エージェント用のアカウントには読めてよい(読めなくても検査は成立する)。

### B-2. WinSW の設定(検証用)

WinSW の実行ファイル(`WinSW-x64.exe`)を `D:\runner\svc\spike-service.exe` として置き、同じ場所に
`spike-service.xml` を作る。**資格を XML に書くため、検証が済んだら、この XML とサービスを削除する**
(本番の雛形 `runner-service/winsw/agent.xml.template` には、秘密を書かない)。

```xml
<service>
  <id>JobRunnerSpike</id>
  <name>Job Runner Spike</name>
  <description>T001 のスパイク(検証用。検証が済んだら削除する)。</description>
  <executable>E:\claude\job_pf\server-sample\.venv\Scripts\python.exe</executable>
  <arguments>-I runner-agent\spikes\logon_spike.py --work D:\runner\work\spike --secret-file D:\runner\secret-outside.txt</arguments>
  <workingdirectory>E:\claude\job_pf\server-sample</workingdirectory>
  <env name="SPIKE_TOOL_ACCOUNT" value="PC名\svc-spike-tool:&lt;パスワード&gt;"/>
  <env name="PARENT_DUMMY_SECRET" value="x"/>
  <serviceaccount>
    <username>PC名\svc-spike-agent</username>
    <password>&lt;エージェント用のパスワード&gt;</password>
    <allowservicelogon>true</allowservicelogon>
  </serviceaccount>
  <startmode>Manual</startmode>
  <onfailure action="none"/>
  <log mode="roll-by-size"/>
  <logpath>D:\runner\svc\log</logpath>
</service>
```

- `PC名` は `$env:COMPUTERNAME` の値。パスワードの `&`・`<` は、XML のエスケープ(`&amp;`・`&lt;`)にする。
- `allowservicelogon` を `true` にするのは、「サービスとしてログオン」の権利を、WinSW が付与するため。

### B-3. 実行と判定

```powershell
cd D:\runner\svc
.\spike-service.exe install
.\spike-service.exe start        # スパイクは 1 回で終わり、サービスは停止する
Start-Sleep 10
.\spike-service.exe status       # Stopped になっていればよい
Get-Content D:\runner\svc\log\*.out.log
```

ログに、JSON(項目 1〜4)が出る。判定は A と同じ。

- 項目 1・2・3・4 がすべて `true` なら、サービスの文脈でも成立。
- 項目 1 が失敗(`CreateProcessWithLogonW` のエラー)する場合は、エラーコードを research.md R4 に記録し、
  **plan を改定して確認を得る**(1 アカウントへの縮退はしない)。
  - 1326: 資格の誤り(組み立て、パスワード、アカウント名)。
  - 1314: 権限の不足(サービスのアカウントが、プロセスを別のアカウントで起動する権限を持たない)。
  - 5: アクセスの拒否(実行ファイル・作業フォルダへの権限)。
- 項目 5(エージェントの終了で子が終了)は、サービスの文脈では、`--arguments` に `--crash` を付けて再実行し、
  サービスの停止後に、ツールのアカウントの `python.exe` が 0 件であることを、A の確認のコマンドで確かめる。

### B-4. 結果の記録

research.md R4 の「スパイクの結果」に、**サービスの文脈での結果**(項目ごとの可否、エラーコード)を追記し、
「未確認」の行を更新する。すべて成立したら、tasks.md の T001 を `[X]` にする。

## 6. 後片付け

```powershell
cd D:\runner\svc
.\spike-service.exe stop 2>$null
.\spike-service.exe uninstall
Remove-Item D:\runner\svc\spike-service.xml      # 資格が書いてある
Remove-Item Env:SPIKE_TOOL_ACCOUNT, Env:PARENT_DUMMY_SECRET -ErrorAction SilentlyContinue
Remove-LocalUser svc-spike-tool, svc-spike-agent
Remove-Item -Recurse -Force D:\runner
```

資格(パスワード)を XML・環境変数・ログに残さない。ログ(`D:\runner\svc\log`)に、資格が出ていないことも確かめてから削除する。
