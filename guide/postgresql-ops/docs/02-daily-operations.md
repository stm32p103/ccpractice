# 02. 日常運用

## 1. 順序ルール(ここが一番大事)

2台構成では「どちらを先に動かすか」で結果が変わります。**スクリプトもこの順序でチェックします。**

| 操作 | 順序 | 理由 |
|---|---|---|
| **起動** | ① メイン → ② バックアップ | バックアップは起動後すぐメインへ接続して WAL を受け取る。メインが居ないと接続を繰り返して失敗する(`service.ps1` は、メインが応答しないとバックアップを起動しない。`-Force` で無視可) |
| **停止(計画停止)** | ① アプリ停止 → ② メイン → ③ バックアップ | メインを先に止めると、停止時の最後の WAL がバックアップに届いてから止まる。バックアップが最新の状態で止まるため、その後の切替や再開が安全 |
| **バックアップ機だけの停止** | メインは動かしたまま、バックアップだけ止めてよい | メンテナンス中にレプリケーションが切れるだけ。複製スロットを使っているので、メインに WAL が溜まる点に注意(長時間なら §4 を確認) |
| **メインの再起動**(設定変更など) | バックアップは動かしたまま、メインだけ再起動 | レプリケーションは自動的に再接続される |
| **バージョンアップ(マイナー)** | ① バックアップ → ② メイン | 先にバックアップで動作確認する。詳細は [04-version-up.md](04-version-up.md) |
| **バージョンアップ(メジャー)** | ① メイン(`pg_upgrade`) → ② バックアップは作り直し | メジャーを跨いだストリーミング更新はできない |
| **バックアップ取得** | `pg_dump` は **バックアップ機**で取ることもできる | メインの負荷を避けられる。ただしスタンバイ上の長い `pg_dump` は、レプリケーションとの競合でキャンセルされることがある(`hot_standby_feedback = on` にするか `max_standby_streaming_delay` を延ばす)。不安ならメインで取る。どちらで取る場合も、取得前にバックアップ機の遅れ(`replay_lag`)を確認する |

> main と backup が別PCの場合、スクリプトは自分のPC上のサーバーしか操作できません。上の順序どおりに、それぞれのPCで実行してください。

## 2. 日常のコマンド

管理者権限の PowerShell で `scripts` フォルダへ移動して実行します。

```powershell
# 台帳の確認(★ が現在の main)
.\inventory.ps1 -Action Show
.\inventory.ps1 -Action Validate

# サービスの状態(受付状況・起動アカウント・実体の役割 main/standby のずれも警告する)
.\service.ps1 -Action Status

# 起動・停止・再起動(-ServerId を省略すると、このPC上の active 全部を main→backup の順で処理)
.\service.ps1 -Action Start   -ServerId prod-a
.\service.ps1 -Action Stop    -Group prod
.\service.ps1 -Action Restart -ServerId prod-a -TimeoutSec 300

# サービスアカウント(ユーザー)
.\user.ps1 -Action Show   -ServerId prod-a
.\user.ps1 -Action Create -ServerId prod-a
.\user.ps1 -Action Delete -ServerId prod-a -RemoveProfile
```

### アプリ用のDB・DBロール(`db.ps1`)

アプリごとに「DB(`<App>_db`)+ ロール(`<App>_user`)」を1組作ります。作成・削除・パスワード変更は**書き込み可能な main**に対してだけ実行できます(スタンバイだと拒否します)。パスワードは対話入力で、コマンドラインにもファイルにも残しません。

```powershell
.\db.ps1 -Action List        -ServerId prod-a                        # DB とロールの一覧(superuser の警告も出す)
.\db.ps1 -Action CreateApp   -ServerId prod-a -App app1 -ClientCidr 192.168.1.20/32 -DryRun   # まず内容確認
.\db.ps1 -Action CreateApp   -ServerId prod-a -App app1 -ClientCidr 192.168.1.20/32
.\db.ps1 -Action SetPassword -ServerId prod-a -App app1
.\db.ps1 -Action DropApp     -ServerId trial-a -App app1             # 削除前に pg_dump を取り、DB名の入力確認あり
```

- 作成すると、**追加すべき `pg_hba.conf` の行**が表示されます。main と backup の両方に追加し、`SELECT pg_reload_conf();` で反映します(§5)。スクリプトは `pg_hba.conf` を編集しません。
- DBは UTF8 / `template0` から作られ、PUBLIC からの接続権限が外されます。
- 作成・削除したDBとロールは、`List` で確認します。台帳(`inventory.json`)にはアプリの情報は持たないため、台帳の更新は不要です。

操作の記録は `logs\pgops-<日付>.log` に残ります。

### 計画停止と再開の手順(例: 本番を丸ごと止める)

```powershell
# 1. アプリを止める(アプリ側の手順)
# 2. メイン機で
.\service.ps1 -Action Stop -ServerId prod-a
# 3. バックアップ機で
.\service.ps1 -Action Stop -ServerId prod-b

# --- 再開 ---
# 4. メイン機で
.\service.ps1 -Action Start -ServerId prod-a
# 5. バックアップ機で(メインが応答していないと起動を拒否する)
.\service.ps1 -Action Start -ServerId prod-b
# 6. 確認: Status が「受付中」、メインの pg_stat_replication が streaming
# 7. アプリを再開する
```

## 3. 台帳の更新ルール

台帳が実態とずれると、障害時に誤った判断をします。次のときは**必ずその場で台帳を更新**します。

| できごと | 台帳の更新 |
|---|---|
| インストール完了 | `Set -Field status -Value active` / `pg_version` / `service_name` など |
| 切り替え(昇格)を実施 | `.\inventory.ps1 -Action Promote -ServerId <新しいmain>` |
| バージョンアップ完了 | `Set -Field pg_version -Value <版>`(メジャーなら `pg_major`、パス類も) |
| サーバーの撤去 | `Set -Field status -Value retired`(行は消さず履歴を残す) |
| フォルダ・ポート・アカウントの変更 | 該当項目を `Set` |

更新前のファイルは `inventory.json.bak-<日時>` として残り、変更内容は台帳の `history` に記録されます。
`Status` が「台帳は main だが実体はスタンバイ」などと警告したら、台帳と実体のどちらが正しいかを先に確認してください(昇格の取りこぼし、または誤昇格の可能性があります)。

## 4. 定期的に確認すること

| 頻度 | 項目 | 確認方法 |
|---|---|---|
| 毎日 | バックアップ(ダンプ)が取れている | `backup_dir` のファイルの日時とサイズ |
| 毎日 | サービスが動いている | `.\service.ps1 -Action Status` |
| 週次 | レプリケーションの遅延と状態 | 下記 SQL |
| 週次 | ディスク空き容量(データ・ログ・バックアップ先・WAL) | エクスプローラー / `Get-Volume` |
| 週次 | ログのエラー | `data\log` の最新ファイル |
| 月次 | **復元テスト**(取ったダンプを別DBへ復元できるか) | `pg_restore -d <テスト用DB> <dump>` |
| 随時 | マイナーバージョンの更新情報(セキュリティ修正) | PostgreSQL のリリース情報 |

```sql
-- メイン側: レプリケーション状況(遅延は replay_lag)
SELECT client_addr, state, sync_state, write_lag, flush_lag, replay_lag FROM pg_stat_replication;

-- メイン側: 複製スロットが WAL をどれだけ抱えているか(retained が大きくなり続けたら要対応)
SELECT slot_name, active,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained
FROM pg_replication_slots;

-- バックアップ側: スタンバイか / 最後に反映した時刻
SELECT pg_is_in_recovery(), pg_last_xact_replay_timestamp();
```

### バックアップの取り方(目安)

| 種類 | 方法 | 頻度の目安 | 用途 |
|---|---|---|---|
| 論理バックアップ | `pg_dump -Fc`(DBごと)+ `pg_dumpall --globals-only` | 毎日 | 誤操作・DB単位の復元・メジャーアップグレード |
| 物理バックアップ + WALアーカイブ(任意) | `pg_basebackup` + `archive_command` | 週次 + 常時 | 任意時点への復旧(PITR) |

どちらも保存先は**本機とは別のディスクまたは別の機器**にします。`upgrade-prep.ps1` は、更新前にこの論理バックアップを一式取るためにも使えます。

## 5. 設定ファイルの扱い(レプリケーションされないもの)

`postgresql.conf` / `pg_hba.conf` / `pg_ident.conf` は**レプリケーションされません**(データの複製とは別物です)。
片方だけ変更すると、切り替えた後に「アプリがつながらない」「設定が戻っている」という事故になります。

- 設定を変更したら、**main と backup の両方に反映**する(`port` や `listen_addresses` など機器固有の値は除く)。
- 特に `pg_hba.conf`(アプリの接続元の許可)と、ログ・メモリ関連の設定は、backup にも同じものを入れておく。
- 設定ファイルは `upgrade-prep.ps1` が `config\` に退避する。変更の記録として Git で版管理してもよい(**パスワードを含む行は除外**する)。
- 変更後の反映: `SELECT pg_reload_conf();`(再起動が必要な項目は `.\service.ps1 -Action Restart`)。
