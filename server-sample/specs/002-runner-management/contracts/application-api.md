# 契約: ユースケース(core がコア API 003 に公開するもの)

**対象**: `job_core.runner.application`
**呼び出し元**: コア API(003)。人間・サービスの主体は 003 が認証して `Principal` を渡す(001 FR-024)。ランナーの主体は `AuthenticateRunner` の戻り値を使う(research R9)。
**型**: 入力・出力は Python の値オブジェクト。HTTP の形(パス・状態コード)は 003 で決める。ランナーとの通信の形(ランナープロトコル)は 004 で決める。

共通の拒否(各ユースケースの「拒否」に重ねて現れる):

- `PermissionDenied(required)`: 権限が足りない。監査ログに `DENIED`(`permission_denied`)を記録する。
- `RunnerMismatch`: ランナー用のユースケースで、`runner_id` が `principal.subject_id` と一致しない。監査ログに `DENIED`(`runner_mismatch`)を記録する。
- `RunnerNotFound`: ランナーがない、または削除済み(作成・一覧の問い合わせを除く)。
- `ConcurrencyConflict`: やり直しを使い切った(既定 3 回。001 R4)。

---

## 人間・サービス用(`runner.manage`)

### CreateRunner — 作成(US1、FR-001、FR-022)

入力: `principal`(`runner.manage`)、`name`
出力: `CreatedRunner(runner_id, token: IssuedToken)`。`IssuedToken(token_id, value)` の `value` はこのときだけ返る
拒否: `PermissionDenied`、`ValidationFailed`、`DuplicateRunnerName`
監査: `RUNNER_CREATE`、`TOKEN_ISSUE`

### SetMaintenance / ClearMaintenance(US6、FR-019)

入力: `principal`(`runner.manage`)、`runner_id`、`reason`(任意)
出力: `RunnerView`
拒否: `PermissionDenied`、`RunnerNotFound`、`AlreadyInMaintenance` / `NotInMaintenance`
監査: `RUNNER_MAINTENANCE_SET` / `RUNNER_MAINTENANCE_CLEAR`
実行中のジョブ・リースは変えない。

### ClearFault — 機材の異常の手動の解除(US5-5、FR-012)

入力: `principal`(`runner.manage`)、`runner_id`、`reason`(任意)
出力: `RunnerView`
拒否: `PermissionDenied`、`RunnerNotFound`
監査: `FAULT_CLEAR`(異常がなかった場合は記録せず、変化なしで成功)

### DeleteRunner(US6-4、US6-5、FR-020)

入力: `principal`(`runner.manage`)、`runner_id`、`reason`(任意)
出力: なし
拒否: `PermissionDenied`、`RunnerNotFound`、`RunnerHasUnfinishedJob(job_id)`
監査: `RUNNER_DELETE`、`TOKEN_REVOKE`(有効なトークンがあれば)
判定の順序: 存在 → 権限 → 未終了のジョブ(001 `find_unfinished_by_runner`)。同じ UoW で確定する。

### ReissueToken / RevokeToken(US7、FR-022、FR-023)

入力: `principal`(`runner.manage`)、`runner_id`、`reason`(任意)
出力: `ReissueToken` → `IssuedToken`(値はこのときだけ)。`RevokeToken` → なし
拒否: `PermissionDenied`、`RunnerNotFound`
監査: `TOKEN_REVOKE`(旧トークンがあれば)、`TOKEN_ISSUE`(再発行のみ)
`ReissueToken` は旧トークンの失効と新トークンの発行を同じ UoW で行う。

### ReplaceCapabilityAllowlist(FR-004、R12)

入力: `principal`(`runner.manage`)、`entries: Mapping[str, ValueKind]`、`reason`(任意)
出力: `AllowlistView`
拒否: `PermissionDenied`、`ValidationFailed`(キーの形)
監査: `ALLOWLIST_CHANGE`

---

## ランナー用(`AuthenticateRunner` が返す主体。`runner.report`)

### AuthenticateRunner — トークンの照合(FR-024、R9)

入力: `token: str`
出力: `Principal(subject_id = runner_id, permissions = {runner.report, job.execute}, kind = RUNNER)`
拒否: `RunnerAuthenticationFailed`(未知・失効・削除済みのランナー。理由は区別して返さない)
監査: 拒否のときだけ `RUNNER_AUTHENTICATE`(`authentication_failed`)。トークンの値・ハッシュは記録しない

### RegisterRunner — 起動時の登録(US1-3〜5、FR-002〜FR-004)

入力: `principal`(`runner.report`)、`runner_id`、`capabilities: Mapping[str, str | list[str]]`([contracts/capability-declaration.schema.json](capability-declaration.schema.json))
出力: `HeartbeatResult(state, lease_expires_at | None, heartbeat_interval)`
拒否: `PermissionDenied`、`RunnerMismatch`、`RunnerNotFound`、`InvalidDeclaration(violations)`(監査に `DENIED`、`invalid_declaration`。能力・最終応答時刻は変えない)
監査: `RUNNER_REGISTER`(`had_live_lease` を含む)、接続が `OFFLINE → ONLINE` に変わったら `RUNNER_ONLINE`

### Heartbeat — 生存通知(US4、FR-016)

入力: `principal`(`runner.report`)、`runner_id`
出力: `HeartbeatResult(state, lease_expires_at | None, heartbeat_interval)`
拒否: `PermissionDenied`、`RunnerMismatch`、`RunnerNotFound`、`RunnerNotRegistered`(作成後に登録していない)
監査: 接続が `OFFLINE → ONLINE` に変わったときだけ `RUNNER_ONLINE`。リースの延長は記録しない
有効なリース(期限前、ジョブが実行中で割り当て先がこのランナー)だけを延長する。期限を過ぎたリースは延長せず、`lease_expires_at` は `None` を返す。
ジョブが終了しているリースは `ENDED` にする。

### ReportFault / ReportRecovered(US5、FR-011)

入力: `principal`(`runner.report`)、`runner_id`、`description`(異常のみ。1〜200 文字)
出力: `HeartbeatResult`
拒否: `PermissionDenied`、`RunnerMismatch`、`RunnerNotFound`、`ValidationFailed`(説明)
監査: `FAULT`(新規、または説明の更新) / `FAULT_RECOVERED`(異常があったときだけ)
`last_seen_at` も更新する(生存通知を兼ねる)。

### RequestJob — 割り当ての要求(US3、FR-013〜FR-015、R4)

入力: `principal`(`runner.report` と `job.execute`)、`runner_id`
出力: `JobRequestResult(assignment: Assignment | None, not_assigned_reason | None, heartbeat_interval)`
- `Assignment(job_id, definition, lease_id, lease_expires_at)`
- `not_assigned_reason`: `NOT_ONLINE(state)`、`RUNNER_BUSY(job_id)`、`NO_MATCHING_JOB`
拒否: `PermissionDenied`、`RunnerMismatch`、`RunnerNotFound`
監査: 001 の `ASSIGN`(`runner_id`、`lease_id` 付き。割り当てたときだけ)
1 回の UoW で: ランナーの状態の確認 → 001 `assign_next_in`(このランナーの能力での照合) → `Lease.grant`。`last_seen_at` も更新する。
「割り当てなし」は例外ではなく結果として返す(ランナーは定期的に求め直すため)。

---

## 定期処理用(`runner.sweep`)

### SweepRunners(R8)

入力: `principal`(`runner.sweep`)
出力: `SweepResult(runners_marked_offline, leases_expired, leases_ended)`
拒否: `PermissionDenied`
監査: `RUNNER_OFFLINE`(ランナーごと)、`LEASE_EXPIRED`(リースごと)。冪等(2 回目は 0 件)

---

## 001 への契約(`RunnerEligibility` の実装)

`RunnerEligibilityService(catalog: RunnerCatalog)`:

- `any_registered_runner_may_satisfy(requirement)`: 削除されていない全ランナーのうち、`satisfies(capabilities, parse_requirement(requirement))` が真になるものがあるか。状態は見ない(FR-008)。
  要件が文法に合わなければ `InvalidRequirement(reason)` を送出する(001 の `SubmitJob` は、これを `ValidationFailed("requirement", reason)` として提出を拒否する。001 への小さな変更)。
- `runner_satisfies(runner_id, requirement)`: そのランナーの能力で満たすか。削除済み・未知は偽。

---

## 問い合わせ(`job.general`)

### ListRunners / GetRunner(FR-027)

入力: `principal`(`job.general`)、(`GetRunner` は `runner_id`)
出力: `RunnerView(runner_id, name, state, capabilities, fault_description | None, maintenance_reason | None, running_job_id | None, last_seen_at | None, registered_at | None)` の一覧(名前の順)
トークンの値・ハッシュ・`token_id` は含めない。削除済みは含めない。

### GetRunnerHistory(spec FR-029。001 FR-026 に倣う)

入力: `principal`(`job.general`)、`runner_id`
出力: `AuditRecordView` の並び(時刻順)。ランナーごとの成功した操作の記録(作成・登録・状態の変更・削除・トークン・リース切れ・割り当てなど)だけ。拒否の記録は含めない
拒否: `PermissionDenied`、`RunnerNotFound`(記録も存在も確認できないとき。削除済みのランナーでも、記録が残っていれば返す)

### GetCapabilityAllowlist

入力: `principal`(`job.general`)
出力: `AllowlistView(entries)`

拒否の記録を含む監査ログ全体は、001 の `GetAuditLog`(`audit.read_all`)に `runner_id` の条件を加えて取り出す(spec FR-029)。
`AuditRecordView` には `runner_id` を加える(001 の既存の項目は変えない)。

監査の操作の種類には、research R14 の 15 種に加え、拒否のときだけ記録する `RUNNER_HEARTBEAT`(生存通知の権限・ランナーの不一致による拒否。
状態が変わらない通知は記録しない)と `RUNNER_SWEEP`(定期処理の権限による拒否)がある。

---

## 受け入れシナリオとの対応(抜粋)

| シナリオ | ユースケース | 期待 |
|---|---|---|
| US1-1 | CreateRunner | `runner_id`、`IssuedToken`。状態 `OFFLINE`、能力は空 |
| US1-5 | RegisterRunner | `InvalidDeclaration`、能力は不変、`DENIED` が 1 件 |
| US2-1 | RunnerEligibilityService | offline のランナーでも真 |
| US2-5 | RunnerEligibilityService / SubmitJob | `InvalidRequirement` → 提出は `ValidationFailed` |
| US3-1 | RequestJob | 先頭 A を飛ばして B。A は待機列に残る |
| US3-4 | RequestJob | `NOT_ONLINE(MAINTENANCE / FAULT / OFFLINE)` |
| US3-5 | RequestJob × 2(同時) | 一方だけに割り当て |
| US4-4 | Heartbeat(期限後) | `lease_expires_at = None`。`SweepRunners` で `LEASE_EXPIRED` |
| US5-4 | Heartbeat(offline からの復帰) | 状態は `FAULT` のまま |
| US6-5 | DeleteRunner | `RunnerHasUnfinishedJob` |
| US7-4 | Heartbeat(別のランナーのトークンの主体) | `RunnerMismatch` |
