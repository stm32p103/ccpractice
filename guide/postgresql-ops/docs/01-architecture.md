# 01. 構成と2重化

## 1. 全体像

分ける単位は3層あります。

| 層 | 単位 | 分け方 |
|---|---|---|
| ① Windowsのサービスアカウント | `svc-postgre-<環境>` | **環境ごと**(試行 / 本番)。PostgreSQL 以外のサービスとは共用しない |
| ② クラスタ(データフォルダ・ポート・Windowsサービス) | 環境ごと、さらに役割ごと(main / backup は別PC) | **環境ごと**に別クラスタ。アプリごとには分けない |
| ③ DBとロール(DBユーザー) | アプリごと | 同じクラスタ内で、アプリごとに DB と ロール を作る |

アプリごとにクラスタまで分けるのは、次のいずれかが必要になった場合だけにします(判断基準)。

- アプリごとに PostgreSQL のバージョンや拡張機能が違う
- アプリ単位で独立して復旧(PITR)したい ※PITR はクラスタ全体が対象
- アプリごとに再起動・メンテナンスの時間帯を分けたい
- 負荷が干渉して困る

### サーバー構成(初期)

| サーバーID | グループ | 初期の役割 | 配置 | サービスアカウント | ポート |
|---|---|---|---|---|---|
| `trial-a` | trial | main | 本機 | `svc-postgre-trial` | 5432 |
| `prod-a` | prod | main | 本番用PC(別PC可) | `svc-postgre-prod` | 5433(同一PCで試行と同居する場合。別PCなら5432でも可) |
| `prod-b` | prod | backup | **`prod-a` とは別のPC** | `svc-postgre-prod` | `prod-a` と同じ |

試行 (`trial`) は単独構成です。必要になったら `trial-b` を台帳に追加します。

**サーバーID(`-a` / `-b`)は「機器の名前」で、切り替えても変えません。** 「いまどちらが main か」は台帳の `role` 欄が表します(`inventory.ps1 -Action Show` の ★)。障害で入れ替えたら必ず台帳も更新します(`inventory.ps1 -Action Promote`)。IDに main / backup を含めないのは、切り替え後に「`prod-main` が backup」という紛らわしい状態を避けるためです。

```
        アプリ(DBごとのロールで接続)
              │  接続先は別名(hosts / DNS)で持つと、切替時に変更が1か所で済む
        ┌─────▼──────┐  WAL(ストリーミング・非同期)  ┌─────────────┐
        │   prod-a   │ ───────────────────────────▶ │    prod-b    │
        │ main       │                               │ backup       │
        │ (書き込み可) │                               │ (読み取り専用) │
        └────────────┘                               └─────────────┘
             PC-A                                       PC-B(別PC)
   ※ 役割は初期配置の例。切替後は a が backup、b が main になる
   ※ trial は別クラスタ・別アカウント・別ポート(本機)
```

### 命名規則

| 対象 | 規則 | 例 |
|---|---|---|
| サーバーID | `<グループ>-a` / `<グループ>-b`(機器の識別名。役割は `role` 欄) | `prod-a` |
| サービスアカウント | `svc-postgre-<環境>`(20文字以内) | `svc-postgre-prod` |
| Windowsサービス名 | 試行はインストーラー既定、本番は区別できる名前 | `postgresql-x64-18` / `postgresql-prod-18` |
| データフォルダ | `<ドライブ>:\...\<環境>\data` | (台帳の `data_dir`。実行時に決定) |
| バックアップ先 | データとは**別ディスク**、できれば別機器 | (台帳の `backup_dir`) |

## 2. 2重化の方式

**物理ストリーミングレプリケーション(非同期)**で、メインの変更を backup に常時送ります。backup は読み取り専用で接続できます(hot standby)。

| 項目 | 方針 | 理由・注意 |
|---|---|---|
| 同期 / 非同期 | **非同期** | メインが突然壊れると、直近の数トランザクションが backup に届いていない可能性があります。同期にすれば防げますが、backup が止まるとメインの書き込みが待たされます(小規模では非同期が現実的) |
| 切り替え | **手動** | 自動切替は誤判定でスプリットブレイン(両方が main になる)の恐れがあります。小規模では人が判断する運用にします |
| 配置 | backup は別PC | 同一PCの別ディスクでは、PCの故障・停電・誤操作に弱い |
| バックアップとの関係 | **レプリケーションはバックアップではない** | `DROP TABLE` などの誤操作もそのまま複製されます。別途 `pg_dump`(必要なら WAL アーカイブによる PITR)を取ります |
| 複製スロット | 使う(`max_slot_wal_keep_size` を併せて設定) | backup が長時間止まるとメインに WAL が溜まります。上限を設けてディスクを埋めないようにします |

## 3. 構築手順(手動で行う部分)

### 3-1. 試行 `trial-a`(単独)

1. 台帳の `trial-a` の `host` / `address` / `install_dir` / `bin_dir` / `data_dir` / `backup_dir` を記入する。
2. `.\user.ps1 -Action Create -ServerId trial-a`(ユーザー作成とデータフォルダのACL付与)。
3. PostgreSQL 18 をインストーラーで手動インストール。データディレクトリは台帳の `data_dir`、ポートは 5432。コンポーネントは PostgreSQL Server / pgAdmin 4 / Command Line Tools。
4. **サービスのログオンアカウントを変更する**: `services.msc` → 該当サービス → プロパティ → 「ログオン」タブ → 「アカウント」に `.\svc-postgre-trial` とパスワードを入力 → OK(「サービスとしてログオンする権利が付与された」と表示される)→ サービスを再起動。
5. `.\inventory.ps1 -Action Set -ServerId trial-a -Field status -Value active`、続けて `-Field pg_version -Value <入れたバージョン>`。
6. `.\service.ps1 -Action Status` で、状態 Running・受付中・起動アカウントが台帳と一致していることを確認する。
7. 初期設定(後述 §4)を行う。

### 3-2. 本番メイン `prod-a`

- **別PCに置く場合**: そのPCで 3-1 と同じ手順(アカウント名は `svc-postgre-prod`)。
- **試行と同じPCに同居させる場合**: インストーラーでは同じメジャーバージョンを2つ入れられません。2つ目は `initdb` と `pg_ctl register` で別クラスタ(別データフォルダ・別ポート・別サービス名)として作ります。データフォルダの所有者がサービスアカウントになるよう、サービスアカウントの権限で `initdb` を実行します(公式ドキュメントの「Windows での initdb / pg_ctl register」を確認してください)。

### 3-3. レプリケーション設定(`prod-a` 側)

```
# postgresql.conf
listen_addresses = 'localhost,<mainのIP>'   # backup から接続できるようにする
wal_level = replica                          # 既定
max_wal_senders = 10                         # 既定
max_slot_wal_keep_size = 10GB                # スロットの滞留でディスクを埋めない保険(値は環境に合わせる)
```

```
# pg_hba.conf に追加(backup の IP だけを許可)
host  replication  repl_user  <backupのIP>/32  scram-sha-256
```

```sql
-- 複製専用ロール(superuser は使わない)
CREATE ROLE repl_user WITH REPLICATION LOGIN PASSWORD '<パスワードは別途管理>';
```

```powershell
# ファイアウォール(backup の IP からのみ許可)
New-NetFirewallRule -DisplayName "PostgreSQL prod (from backup)" -Direction Inbound -Protocol TCP -LocalPort 5433 -RemoteAddress <backupのIP> -Action Allow
```

`listen_addresses` と `pg_hba.conf` の変更後は、サービスを再起動します(`.\service.ps1 -Action Restart -ServerId prod-a`)。

### 3-4. バックアップ機 `prod-b` の作成

1. backup 用PCで `.\user.ps1 -Action Create -ServerId prod-b`。
2. PostgreSQL をインストーラーで手動インストール(データディレクトリは台帳の `data_dir`)。`services.msc` でログオンアカウントを `.\svc-postgre-prod` に変更する(3-1 の手順4)。
3. サービスを止め、インストーラーが作った空のデータフォルダを退避する(削除は動作確認後)。
   ```powershell
   .\service.ps1 -Action Stop -ServerId prod-b
   Move-Item "<data_dir>" "<data_dir>.orig-$(Get-Date -Format yyyyMMdd)"
   ```
4. メインから基本バックアップを取得し、スタンバイとして構成する(管理者のPowerShell)。
   ```powershell
   $env:PGPASSWORD = "<repl_userのパスワード>"      # 実行後に Remove-Item Env:\PGPASSWORD
   & "<bin_dir>\pg_basebackup.exe" -h <mainのaddress> -p <mainのport> -U repl_user -D "<data_dir>" -X stream -R -C -S prod_backup_slot -P
   Remove-Item Env:\PGPASSWORD
   ```
   `-R` で `standby.signal` と接続設定(`primary_conninfo`)が作られ、`-C -S` で複製スロットが作られます。
5. データフォルダの権限をサービスアカウントに付け直す: `.\user.ps1 -Action Create -ServerId prod-b`(アカウントが既にあれば作成はスキップし、ACLだけ付与します)。
6. `.\service.ps1 -Action Start -ServerId prod-b`、台帳を `active` に更新する。
7. 確認する(下記)。

```sql
-- メイン側: backup が接続しているか(state = streaming)
SELECT client_addr, state, sync_state, replay_lag FROM pg_stat_replication;
-- バックアップ側: スタンバイか(t)、最後に反映した時刻
SELECT pg_is_in_recovery(), pg_last_xact_replay_timestamp();
```

> `primary_conninfo` にパスワードが入る場合は `postgresql.auto.conf` に平文で残ります。データフォルダの権限を「サービスアカウントと管理者のみ」に保ってください。

## 4. 各クラスタの初期設定チェックリスト

- [ ] `SHOW server_encoding;` を確認し、アプリ用DBは `CREATE DATABASE ... ENCODING 'UTF8' TEMPLATE template0;` で作る
- [ ] アプリごとに DB とロールを作成する(`.\db.ps1 -Action CreateApp -ServerId <ID> -App <名前>`。UTF8での作成と、`REVOKE CONNECT ... FROM PUBLIC` を自動で行う)
- [ ] `pg_hba.conf` は `scram-sha-256`。接続元は必要最小限
- [ ] `listen_addresses` は必要になるまで `localhost`(試行は特に)
- [ ] ログ: `logging_collector = on`、`log_rotation_age` / `log_rotation_size`、`log_min_duration_statement`
- [ ] サービスの「回復」タブで、失敗時に「サービスを再起動する」を設定
- [ ] スリープ・休止を無効化、データフォルダをウイルス対策のリアルタイムスキャン対象から除外
- [ ] データフォルダを OneDrive など同期フォルダに置かない
- [ ] `.\inventory.ps1 -Action Validate` で NG が無い
