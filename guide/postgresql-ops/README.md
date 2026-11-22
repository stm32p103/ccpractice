# PostgreSQL 運用ガイド(Windows / メイン+バックアップの2重化)

小規模環境で PostgreSQL 18 系を **「メイン」と「バックアップ」の2台構成**で運用するための手順書と、運用スクリプトです。
**今どのサーバー・サービス・ユーザーを保守しているか**を台帳(`inventory/inventory.json`)に残し、スクリプトはその台帳を読んで動きます。

## ドキュメント

| 文書 | 内容 |
|---|---|
| [docs/01-architecture.md](docs/01-architecture.md) | 構成(環境×役割)、命名、2重化の方式と構築手順の概要 |
| [docs/02-daily-operations.md](docs/02-daily-operations.md) | **起動・停止・バックアップ・更新の順序**、日常コマンド、監視、台帳の更新ルール |
| [docs/03-failure-recovery.md](docs/03-failure-recovery.md) | **障害時の復旧**(バックアップ機故障、メイン故障、計画切替、データ破損・誤操作) |
| [docs/04-version-up.md](docs/04-version-up.md) | マイナー/メジャーのバージョンアップ手順(`upgrade-prep.ps1` を使った準備) |

## ファイル構成

```
postgresql-ops/
├─ README.md
├─ docs/                    手順書(上表)
├─ inventory/
│   └─ inventory.json       台帳(サーバー・サービス・ユーザー・役割・パスの現状)
└─ scripts/                 PowerShell スクリプト
    ├─ inventory.ps1        台帳の表示 / 検証 / 役割入れ替え(Promote) / 項目更新(Set)
    ├─ user.ps1             サービス用ローカルユーザーの作成 / 削除 / 確認
    ├─ service.ps1          サービスの状態確認 / 起動 / 停止 / 再起動(順序チェック付き)
    ├─ db.ps1               アプリ用のDB・DBロールの一覧 / 作成 / 削除 / パスワード変更
    ├─ upgrade-prep.ps1     バージョンアップ前の点検とバックアップ取得(停止・変更はしない)
    └─ lib/PgOps.Common.ps1 共通関数
```

実行すると `logs/`(操作ログ)が作られます。Git で管理する場合は `logs/` と台帳のバックアップ(`inventory.json.bak-*`)を除外してください(同梱の `.gitignore` で除外済み)。

## 言語の選定: PowerShell

| 観点 | PowerShell(採用) | Python | バッチファイル |
|---|---|---|---|
| Windows のサービス・ローカルユーザー・ACL の操作 | 標準コマンドレットで書ける | `subprocess` で `net` / `sc` / `icacls` を呼ぶ形になる | 書けるが保守しにくい |
| 追加インストール | 不要(Windows PowerShell 5.1 は標準搭載) | 各PCにインストールが必要 | 不要 |
| JSON(台帳)の読み書き | 標準 | 標準 | 不可(実質) |
| 他OS(Linux)でも使う場合 | 不向き | 向いている | 不可 |

PostgreSQL をインストールした PC 自体を操作する用途で、追加導入なしに動くため PowerShell にしています。
**運用するPCに Linux が含まれる場合は、その部分だけ Python / シェルで別途用意**してください(台帳の形式は流用できます)。

## 使い始め

1. **台帳を埋める**(`inventory/inventory.json`)。`<...>` の項目がプレースホルダです。パスは環境ごとに決めて記入します。
   - `host` は、そのPCで `$env:COMPUTERNAME` を実行して確認した名前を書きます(スクリプトは `host` が自分のPC名と一致するサーバーだけを操作します)。
   - **パスワードは台帳に書きません**(スクリプトが対話入力で受け取り、ファイルには残しません)。
2. 管理者権限の PowerShell を開き、`scripts` フォルダへ移動します。
3. 台帳を検証し、内容を確認します。
   ```powershell
   cd <このフォルダ>\scripts
   .\inventory.ps1 -Action Validate
   .\inventory.ps1 -Action Show
   ```
4. サービスアカウントを作成し、データフォルダを用意します(`-DryRun` で先に内容確認できます)。
   ```powershell
   .\user.ps1 -Action Create -ServerId trial-a -DryRun
   .\user.ps1 -Action Create -ServerId trial-a
   ```
5. **PostgreSQL を手動でインストール**します。インストール後に `services.msc` でサービスのログオンアカウントを台帳のユーザーに変更します(手順は [docs/01-architecture.md](docs/01-architecture.md))。
6. 台帳を `active` にして状態を確認します。
   ```powershell
   .\inventory.ps1 -Action Set -ServerId trial-a -Field status -Value active
   .\service.ps1 -Action Status
   ```

### 実行ポリシー・文字コードの注意

- スクリプトが「実行できない」と言われたら、そのウィンドウだけ許可します: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`
- ZIP やダウンロードで他のPCへ持っていった場合は、`Get-ChildItem -Recurse -Filter *.ps1 | Unblock-File` を実行します。
- `.ps1` は **UTF-8 (BOM付き)** で保存されています。編集後に BOM が外れると、Windows PowerShell 5.1 で日本語が化けます(VS Code は右下のエンコーディング表示から「BOM付き UTF-8 で保存」を選びます)。
- 構文だけを確認するには(実行はしません):
  ```powershell
  Get-ChildItem -Recurse -Filter *.ps1 | ForEach-Object {
      $e = $null; [void][Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$null, [ref]$e)
      if ($e) { $e | ForEach-Object { '{0}: {1}' -f $_.Extent.File, $_.Message } } else { 'OK: ' + $_.Name }
  }
  ```

## スクリプトの範囲(やること / やらないこと)

| やる | やらない(手動・別手順) |
|---|---|
| サービス用ローカルユーザーの作成・削除・確認、データフォルダのACL付与 | PostgreSQL のインストール・アンインストール |
| サービスの起動・停止・再起動(main→backup の順序チェック付き) | サービスのログオンアカウントの変更(`services.msc` で実施) |
| バージョンアップ前の点検・ダンプ取得・設定退避・レポート作成 | バージョンアップ本体(インストーラー / `pg_upgrade`) |
| 台帳の検証、役割の入れ替え記録(Promote)、項目更新 | レプリケーションの構築、実際の昇格(`pg_promote`)→ docs 参照 |
| アプリ用のDB・DBロールの作成・削除・パスワード変更(`db.ps1`) | `pg_hba.conf` の編集(追加すべき行を表示するだけ。main と backup の両方に手で反映) |

操作できるのは**そのスクリプトを実行しているPC上のサーバーだけ**です。main と backup が別PCなら、それぞれのPCで実行します(別PCの状態は `pg_isready` で確認する範囲にとどまります)。
