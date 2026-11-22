# 03. 障害時の復旧

## 0. 先に守ること

1. **メインが本当に止まったと確認できるまで、バックアップを昇格しない。** メインが生きたまま昇格すると、2台とも「main」になり(スプリットブレイン)、データが分岐して取り返しがつかなくなります。
2. **旧メインを、そのまま書き込み可能な状態で起動しない。** 昇格後の旧メインは、再構築するまで起動禁止です(自動起動も止めておく)。
3. **操作の前に状況を記録する。** `.\service.ps1 -Action Status` と `.\inventory.ps1 -Action Show` の出力を控える。
4. **古いデータは最後まで消さない。** 退避(`Move-Item`)にとどめ、新しい構成の動作確認が済んでから削除する。
5. 操作したら**台帳を更新**する(特に役割の入れ替え)。

> 台帳のサーバーID(`prod-a` / `prod-b`)は**機器の名前**で、切り替えても変えません。「いまどちらが main か」は台帳の `role` 欄(`inventory.ps1 -Action Show` の ★)で見ます。以下では、初期配置で `prod-a` が main、`prod-b` が backup だった場合を例にします。

## 1. 症状から手順を探す

| 症状 | まず確認 | 手順 |
|---|---|---|
| バックアップ機が止まった・壊れた | メインは正常か | [A](#a-バックアップ機の故障) |
| メインが止まった・壊れた・つながらない | **本当に止まっているか**(PC電源・ネットワーク・サービス) | [B](#b-メインの故障バックアップを昇格する) |
| メンテナンスでメインとバックアップを入れ替えたい | – | [C](#c-計画切替スイッチオーバー) |
| 昇格後、旧メインを戻したい | – | [D](#d-旧メインの復帰新バックアップとして再構築) |
| 誤って DELETE / DROP した、データが壊れた、両方壊れた | レプリケーションで複製済みか | [E](#e-データ破損誤操作両系障害) |
| メインとバックアップの間の通信が切れた(両方生きている) | 両方動いているか | [F](#f-ネットワーク分断) |
| サービスが起動しない | ログ(`data\log`) | [G](#g-サービスが起動しない) |

```
メインにつながらない
 ├─ メインPC/サービスが生きている → 原因はネットワークかPostgreSQL内 → [F]/[G] を確認(昇格しない)
 └─ メインPCが停止・電源断・復旧に時間がかかる
      ├─ バックアップは健全(streaming だった) → [B] 昇格
      └─ バックアップも不調 → [E] ダンプから復元
```

---

## A. バックアップ機の故障

**影響**: メインは通常どおり動く。冗長性がなくなる。複製スロットのため、メインに WAL が溜まり続ける。

1. メインで WAL の滞留とディスク空きを確認する。
   ```sql
   SELECT slot_name, active,
          pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained
   FROM pg_replication_slots;
   ```
2. **短時間で戻せる**(再起動など)なら、復旧後に `.\service.ps1 -Action Start -ServerId prod-b` で自動的に追いつく。
3. **戻せない・長引く**なら、WAL が上限に達してディスクを埋める前に、スロットを削除する。
   ```sql
   SELECT pg_drop_replication_slot('prod_backup_slot');
   ```
4. バックアップ機を修理し、**作り直す**([01-architecture.md §3-4](01-architecture.md))。台帳の `status` を作り直し中は `planned`、完了後に `active` にする。
5. 作り直しが終わるまでは単一障害点なので、`pg_dump` の頻度を上げる。

## B. メインの故障(バックアップを昇格する)

### B-1. 昇格してよいか確認する

- [ ] メインが**本当に**止まっている(PCの電源・サービス・ネットワークを、別の経路や現場で確認した)
- [ ] ネットワークだけが切れていて、メインが生きている可能性を排除した(→ 生きているなら [F])
- [ ] メインが復旧しても**勝手にmainとして立ち上がらない**ようにした
  ```powershell
  # メインPCで(操作できる場合)
  .\service.ps1 -Action Stop -ServerId prod-a
  Set-Service -Name <メインのservice_name> -StartupType Disabled
  ```
- [ ] バックアップが最後に反映した時刻を確認した(**これより後の更新は失われている可能性がある**)
  ```sql
  -- バックアップ機で
  SELECT pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn(), pg_last_xact_replay_timestamp();
  ```

### B-2. 昇格する

```sql
-- バックアップ機で(superuser)
SELECT pg_promote();
-- 確認: false(=スタンバイではない)になれば昇格完了
SELECT pg_is_in_recovery();
```

1. 書き込みテストをする(テスト用テーブルへの INSERT など)。
2. **アプリが接続できる設定か確認する**: `listen_addresses`、`pg_hba.conf`(アプリの接続元)、ファイアウォール。設定ファイルはレプリケーションされないため、バックアップ機には事前に同じ許可を入れておくのが理想([02 §5](02-daily-operations.md))。
3. アプリの接続先を、新しいメイン(`prod-b`)に切り替える(別名で持っていれば、その向き先を変更)。
4. **台帳を更新する**: `.\inventory.ps1 -Action Promote -ServerId prod-b`
5. `.\service.ps1 -Action Status` で警告が出ないこと(台帳の役割と実体が一致)を確認する。
6. すぐに `pg_dump` を取る(冗長性がない状態のため)。
7. 旧メインを復旧して新バックアップにする → [D](#d-旧メインの復帰新バックアップとして再構築)。

> 新メインには複製スロット(`prod_backup_slot`)が存在しません。新バックアップを作る [D] で、`pg_basebackup -C -S` により作成されます。

## C. 計画切替(スイッチオーバー)

メンテナンスなどで、役割を入れ替えたい場合の手順です。

1. アプリを止める。
2. メインで遅れがないことを確認する(`pg_stat_replication` の `replay_lag` がほぼ 0、`state = streaming`)。
3. メインを停止する: `.\service.ps1 -Action Stop -ServerId prod-a`(停止時の最後の WAL がバックアップに届いてから止まる)。
4. バックアップ機で昇格する: `SELECT pg_promote();`
5. アプリの接続先を切り替え、アプリを再開する。
6. 台帳を更新する: `.\inventory.ps1 -Action Promote -ServerId prod-b`
7. 旧メインを新バックアップにする → [D](#d-旧メインの復帰新バックアップとして再構築)。

## D. 旧メインの復帰(新バックアップとして再構築)

旧メインのデータは、昇格したメインとは**分岐している可能性がある**ため、そのまま起動してはいけません。基本は**作り直し**(小規模ならこれが確実)です。

1. 旧メイン機で、サービスが停止していて自動起動が無効のままであることを確認する。
2. 旧データフォルダを退避する(削除は動作確認後)。
   ```powershell
   Move-Item "<prod-aのdata_dir>" "<prod-aのdata_dir>.old-$(Get-Date -Format yyyyMMdd)"
   ```
3. 新メインから基本バックアップを取得し、スタンバイとして構成する(管理者のPowerShell。新メインの接続先を指定)。
   ```powershell
   $env:PGPASSWORD = "<repl_userのパスワード>"
   & "<bin_dir>\pg_basebackup.exe" -h <新メインのaddress> -p <port> -U repl_user -D "<prod-aのdata_dir>" -X stream -R -C -S prod_backup_slot -P
   Remove-Item Env:\PGPASSWORD
   ```
4. 権限を付け直し、サービスを自動起動に戻して起動する。
   ```powershell
   .\user.ps1 -Action Create -ServerId prod-a          # アカウントが既にあれば作成をスキップし、ACLだけ付与
   Set-Service -Name <prod-aのservice_name> -StartupType Automatic
   .\service.ps1 -Action Start -ServerId prod-a        # 台帳上は backup なので、新メインの応答を確認してから起動する
   ```
5. 新メインで `pg_stat_replication` が `streaming` になっていること、`.\service.ps1 -Action Status` に警告が出ないことを確認する。
6. 台帳(`Promote` 済みのはず)と、`history` を確認する。

> 計画切替 [C] の直後で、旧メインを正常に停止していた場合は、`pg_rewind`(`wal_log_hints = on` またはデータチェックサム有効が前提)で差分だけ戻すこともできます。ただし異常終了していた場合は使えないことがあるため、**迷ったら作り直し**にしてください。

## E. データ破損・誤操作・両系障害

**レプリケーションは誤操作も複製します。バックアップ機があっても、誤操作の復旧には使えません。** バックアップ(ダンプ)から戻します。

### E-1. 誤操作・一部のDBの破損(論理バックアップから)

まず**別名のDBに復元して中身を確認**し、必要なデータだけを戻すか、DBごと置き換えます。

```powershell
# 1. 復元先を作る(別名)
& "<bin_dir>\psql.exe" -U postgres -c "CREATE DATABASE app_db_restore TEMPLATE template0 ENCODING 'UTF8';"
# 2. ダンプを復元する
& "<bin_dir>\pg_restore.exe" -U postgres -d app_db_restore "<backup_dir>\...\app_db.dump"
# 3. 中身を確認し、必要なデータを戻す(または DB名を入れ替える)
```

ダンプは、`upgrade-prep.ps1` が作る `globals.sql`(ロールなど)と DBごとの `*.dump` です。ロールが無い環境へ戻す場合は、先に `psql -U postgres -f globals.sql` を実行します。

### E-2. 両系障害・PCごと失った場合

1. 新しいPC(または復旧したPC)を用意し、台帳の `host` / `address` / パスを更新する(`inventory.ps1 -Action Set`)。
2. [01-architecture.md §3-1](01-architecture.md) の手順で、ユーザー作成 → インストール → ログオンアカウント変更 → 初期設定。
3. `globals.sql` → DBごとの `pg_restore` の順で復元する。
4. アプリの接続先を切り替える。動作確認後、バックアップ機を作り直す([01 §3-4](01-architecture.md))。
5. 台帳を更新する。

### E-3. 任意の時点へ戻したい(PITR。WALアーカイブを取っている場合のみ)

事前に、メインで WAL アーカイブを有効にしておく必要があります。

```
# postgresql.conf(メイン)
archive_mode = on
archive_command = 'copy "%p" "<アーカイブ先>\\%f"'     # Windows の例。アーカイブ先は別ディスク/別機器
```

復旧は「物理バックアップ(`pg_basebackup`)を復元 → `restore_command` と復旧目標を指定 → `recovery.signal` を作って起動」です。

```
# postgresql.conf(復旧用クラスタ)
restore_command = 'copy "<アーカイブ先>\\%f" "%p"'
recovery_target_time = '2026-11-22 10:30:00'      # 誤操作の直前
recovery_target_action = 'promote'
```

手順の詳細は PostgreSQL 公式ドキュメント「継続的アーカイブと時間ベースのリカバリ(PITR)」を参照してください。**復元テストを事前にやっておかないと、障害時には使えません。**

## F. ネットワーク分断

メインとバックアップは両方生きているが、通信できない状態です。

- **昇格しない。** アプリはメインだけに接続させる。
- 分断中、メインには WAL が溜まります。ディスクを確認し、長引く場合は [A] の手順3(スロット削除)を検討します。上限(`max_slot_wal_keep_size`)を超えるとスロットが無効になり、バックアップは**作り直し**になります。
- 回復後は、バックアップが自動で再接続して追いつきます(`pg_stat_replication` が `streaming` に戻ることを確認)。

## G. サービスが起動しない

まず `data\log` の最新ログと、`.\service.ps1 -Action Status` / `.\user.ps1 -Action Show -ServerId <ID>` の出力を確認します。

| 症状・メッセージ | 主な原因 | 対処 |
|---|---|---|
| 起動時に「ログオン失敗」(エラー1069) | サービスアカウントのパスワード不一致、「サービスとしてログオン」権利が無い | `services.msc` の「ログオン」タブでアカウント/パスワードを再入力(権利が自動で再付与される) |
| 起動してすぐ停止、ログに「アクセスが拒否されました」 | データフォルダのACL不足 | `.\user.ps1 -Action Create -ServerId <ID>` でACLを付け直す(既存アカウントはスキップされる) |
| ログに `postmaster.pid` が既にあるという内容 | 異常停止後の残骸 | `Get-Process postgres` でプロセスが無いことを確認してから、`postmaster.pid` を別の場所へ退避して再起動 |
| ポートが使用中 | 別クラスタとの重複、他のアプリ | `Get-NetTCPConnection -LocalPort <port>`、`.\inventory.ps1 -Action Validate` |
| ディスクフルで停止 | WAL・ログ・ダンプの滞留 | **`pg_wal` の中身は手で消さない**。ダンプやログを削除して空きを作る。WAL が溜まる原因が複製スロットなら、スロットを削除する |
| バックアップ機が追従しない | `primary_conninfo` の誤り、`pg_hba.conf`、ファイアウォール、スロット無効 | ログで原因を確認。直らなければ作り直し([01 §3-4](01-architecture.md)) |
| `Status` に「台帳と実体の役割が不一致」と出る | 昇格の取りこぼし、または誤昇格 | **どちらが正しいかを先に確認**する。実体がスプリットブレインの疑いなら、書き込みを止めて [B-1] から |

## 復旧後のチェックリスト

- [ ] `.\service.ps1 -Action Status` に警告が無い
- [ ] `.\inventory.ps1 -Action Validate` が NG なし(main がグループにちょうど1台)
- [ ] メインの `pg_stat_replication` が `streaming`
- [ ] アプリが新しいメインで動作している
- [ ] 復旧直後に `pg_dump` を取得した
- [ ] 台帳の `history` に操作が記録されている
- [ ] 原因・時刻・失った可能性のある範囲を記録した(再発防止)
