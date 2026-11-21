# データモデル: コア — ランナーとジョブの割り当ての管理(最小版)

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **調査**: [research.md](research.md)

core のドメインモデル(Python の値オブジェクト・集約)を定める。DB のテーブル設計ではない。
永続化の表現は core-persistence(003)が決め、[contracts/ports.md](contracts/ports.md) の契約テストを通すこと。

コンテキスト(憲章 原則 2):

- **runner**(本 feature): ランナー、能力、能力のキーの許可リスト、リース、ランナーのトークン、照合の規則
- **job**(001): ジョブ、待機列、監査ログの記録。runner は job の application / domain を参照してよいが、逆は禁止(research R1)
- **access**(001): 主体と権限。権限を 3 種追加する(§6)

---

## 1. 値オブジェクト

| 名前 | 型・形 | 検証 | 出典 |
|---|---|---|---|
| `RunnerId` | 不透明な文字列(001 の型。002 が `IdGenerator` で発行) | 空でない。削除後も再利用しない | FR-021 |
| `RunnerName` | 文字列 | 前後の空白を除き 1〜128 文字、制御文字なし | FR-001 |
| `CapabilityKey` | 文字列 | `^[a-z0-9][a-z0-9._-]{0,63}$` | R2 |
| `CapabilityValue` | `SingleValue(str)` または `SetValue(frozenset[str])` | 文字列は 1〜256 文字・制御文字なし。集合は 0〜64 要素 | FR-005、R2 |
| `Capabilities` | `Mapping[CapabilityKey, CapabilityValue]`(不変) | キーは最大 64 個 | FR-005 |
| `ValueKind` | `SINGLE` / `SET` | — | R12 |
| `ParsedRequirement` | `tuple[Condition, ...]` | [contracts/runner-requirement.schema.json](contracts/runner-requirement.schema.json) に適合 | FR-007、R2 |
| `Condition` | `key: CapabilityKey`、`op: Op`、`operand: str \| frozenset[str] \| Decimal \| VersionTuple` | `op` ごとに指定値の形を検査 | FR-007 |
| `Op` | `EQ`、`IN`、`NUM_GT/GE/LT/LE`、`VER_GT/GE/LT/LE`、`CONTAINS` | — | FR-007 |
| `VersionTuple` | `tuple[int, ...]`(1〜8 要素) | `^\d+(\.\d+){0,7}$` から | R2 |
| `FaultDescription` | 文字列 | 1〜200 文字、改行・制御文字なし | FR-011、R13 |
| `Reason` | 001 の `Reason`(1〜1000 文字) | — | FR-019 |
| `TokenHash` | 16 進 64 文字(SHA-256) | — | R9 |
| `RunnerTimingPolicy` | `heartbeat_interval`(既定 30 秒)、`offline_after`(既定 90 秒)、`lease_duration`(既定 180 秒) | `offline_after >= 2 × heartbeat_interval`、`lease_duration >= 2 × heartbeat_interval`、すべて正 | FR-010、FR-015、FR-016、R7 |
| `MaintenanceRecord` | `set_by`(主体の識別子)、`set_at`(日時)、`reason`(`Reason \| None`) | 理由は任意。指定するときは `Reason` の制限(1〜1000 文字)に従い、空文字は不可(指定なしは `None`) | FR-019 |
| `FaultRecord` | `reported_at`(日時)、`description`(`FaultDescription`)、`updated_at`(日時) | 説明は必須(`FaultDescription` の制限) | FR-011 |

`RunnerRequirement`(001 の不透明な値)は、002 では `parse_requirement` で `ParsedRequirement` に変換して使う(R3)。

---

## 2. 集約 `Runner`

| 項目 | 型 | 説明 |
|---|---|---|
| `runner_id` | `RunnerId` | 一意 |
| `name` | `RunnerName` | 削除されていないランナーの間で一意 |
| `created_at` | `datetime` | 作成日時 |
| `capabilities` | `Capabilities` | 最後に受け付けた登録の申告。未登録なら空 |
| `registered_at` | `datetime \| None` | 最後の登録の日時。`None` = 未登録 |
| `last_seen_at` | `datetime \| None` | 最後の登録・生存通知・割り当ての要求・異常と回復の申告の受信時刻(サーバー時刻) |
| `recorded_connectivity` | `ONLINE` / `OFFLINE` | 監査ログに最後に記録した接続の状態(R6)。初期値 `OFFLINE` |
| `maintenance` | `MaintenanceRecord \| None` | 設定者、日時、理由(任意) |
| `fault` | `FaultRecord \| None` | 申告日時、説明、最終更新日時 |
| `deleted_at` | `datetime \| None` | 削除日時。削除後も記録は残る(FR-021) |
| `version` | `int` | 楽観的排他 |

### 状態の導出 `state_at(now, policy) -> RunnerState`(FR-010。保存しない)

| 優先 | 条件 | 状態 |
|---|---|---|
| — | `deleted_at` あり | `DELETED`(判定・割り当て・一覧の対象外) |
| 1 | `maintenance` あり | `MAINTENANCE` |
| 2 | `fault` あり | `FAULT` |
| 3 | `registered_at` なし、または `now - last_seen_at > offline_after` | `OFFLINE` |
| 4 | それ以外 | `ONLINE` |

割り当てを受けられるのは `ONLINE` だけ(FR-014)。

### 操作(状態の変更はこのメソッドだけで行う)

| メソッド | 事前条件 | 変更 | 例外 |
|---|---|---|---|
| `create(id, name, at)`(生成) | — | 上表の初期値 | `ValidationFailed` |
| `register(capabilities, at)` | 削除されていない | `capabilities` を置き換え、`registered_at = last_seen_at = at` | `RunnerDeleted` |
| `touch(at)`(生存通知) | 削除されていない、登録済み | `last_seen_at = at` | `RunnerDeleted`、`RunnerNotRegistered` |
| `mark_connectivity(c)` | — | `recorded_connectivity = c`(変化したかを返す) | — |
| `set_maintenance(by, at, reason)` | 削除されていない、maintenance でない | `maintenance` を設定 | `RunnerDeleted`、`AlreadyInMaintenance` |
| `clear_maintenance()` | maintenance である | `maintenance = None` | `NotInMaintenance` |
| `report_fault(description, at)` | 削除されていない | `fault` を設定(既にあれば説明と最終更新だけ) | `RunnerDeleted` |
| `report_recovered()` / `clear_fault()` | — | `fault = None`(なければ何もしない、変化の有無を返す) | — |
| `delete(at)` | 削除されていない | `deleted_at = at` | `RunnerDeleted` |

「実行中のジョブを持たない」(削除の条件 FR-020)は、ランナーの項目ではなく、001 の `JobRepository.find_unfinished_by_runner` で同じ UoW の中で判定する(001 R6 と同じ考え方)。

---

## 3. 集約 `CapabilityAllowlist`(1 個。R12)

| 項目 | 型 | 説明 |
|---|---|---|
| `entries` | `Mapping[CapabilityKey, ValueKind]` | 既定は空(すべて拒否) |
| `version` | `int` | 楽観的排他 |

`validate(declared: Mapping[str, JSON]) -> Capabilities`: すべてのキーが `entries` にあり、値の型が一致し、R2 の制限を満たせば `Capabilities` を返す。満たさなければ `InvalidDeclaration(violations)`(どのキーが・なぜ。値そのものは含めない)。
`replace(entries)`: 一覧を置き換える(既存のランナーの能力は変えない)。

---

## 4. 集約 `Lease`

| 項目 | 型 | 説明 |
|---|---|---|
| `lease_id` | `str` | 一意 |
| `job_id` | `JobId` | 001 のジョブ。1 件のジョブに `ACTIVE` のリースは同時に 1 つ |
| `runner_id` | `RunnerId` | 割り当て先 |
| `granted_at` | `datetime` | 割り当て日時 |
| `expires_at` | `datetime` | 期限 |
| `last_extended_at` | `datetime \| None` | 最後に延長した日時 |
| `status` | `ACTIVE` / `EXPIRED` / `ENDED` | 記録上の状態 |
| `version` | `int` | 楽観的排他 |

### 遷移

| 現在 | 操作 | 条件 | 次 |
|---|---|---|---|
| (なし) | `grant(job, runner, now, policy)` | 割り当てと同じ UoW | `ACTIVE`、`expires_at = now + lease_duration` |
| `ACTIVE` | `extend(now, policy)` | `now <= expires_at` | `ACTIVE`、`expires_at = now + lease_duration` |
| `ACTIVE` | `extend(now, policy)` | `now > expires_at` | 延長しない(`LeaseExpired` を送出) |
| `ACTIVE` | `expire(now)` | `now > expires_at`(`SweepRunners`) | `EXPIRED` |
| `ACTIVE` | `end()` | ジョブが終了状態 | `ENDED` |
| `EXPIRED` / `ENDED` | すべて | — | 遷移しない(`InvalidLeaseTransition`) |

`is_live_at(now) = status is ACTIVE and now <= expires_at`。記録が `ACTIVE` のままでも、期限を過ぎたら延長しない(FR-017)。

---

## 5. 集約 `RunnerToken`

| 項目 | 型 | 説明 |
|---|---|---|
| `token_id` | `str` | 一意 |
| `runner_id` | `RunnerId` | 結び付くランナー |
| `token_hash` | `TokenHash` | SHA-256。トークンの値は保存しない(R9) |
| `issued_at` | `datetime` | 発行日時 |
| `revoked_at` | `datetime \| None` | 失効日時 |

1 台のランナーに `revoked_at = None` のトークンは高々 1 つ(不変条件 3)。
トークンの値は、発行のユースケースの戻り値 `IssuedToken.value` にだけ現れ、ほかのどこにも現れない(SC-008)。

---

## 6. 権限の追加(access。R10)

| 権限 | 識別子 |
|---|---|
| ランナー管理 | `runner.manage` |
| ランナーの自己申告 | `runner.report` |
| ランナーの定期処理 | `runner.sweep` |

ランナーのトークンで認証した主体は `{runner.report, job.execute}` だけを持つ(FR-025)。

---

## 7. 監査ログの記録の拡張(001 §4 への追加。R14)

- 項目 `runner_id: RunnerId | None`(既定 `None`)を追加する。
- `AuditOperation` に、research R14 の 15 種と、拒否のときだけ記録する 2 種(`RUNNER_HEARTBEAT`、`RUNNER_SWEEP`)を追加する。
- `Denial.code` に `authentication_failed`、`invalid_declaration` を追加する。

| 操作 | `before` | `after` | `reason` |
|---|---|---|---|
| `RUNNER_CREATE` | — | `name` | — |
| `RUNNER_REGISTER` | `capabilities`、`state` | `capabilities`、`state`、`had_live_lease`(真偽) | — |
| `RUNNER_ONLINE` / `RUNNER_OFFLINE` | `connectivity` | `connectivity`、`last_seen_at` | — |
| `RUNNER_MAINTENANCE_SET` / `_CLEAR` | `state` | `state` | 任意 |
| `FAULT` | `fault`(説明または無) | `fault`(説明) | — |
| `FAULT_RECOVERED` / `FAULT_CLEAR` | `fault` | 無 | 手動の解除は任意 |
| `RUNNER_DELETE` | `name`、`state` | `deleted_at` | 任意 |
| `TOKEN_ISSUE` / `TOKEN_REVOKE` | `token_id`(旧) | `token_id`(新) | 任意 |
| `ALLOWLIST_CHANGE` | `entries` | `entries` | 任意 |
| `LEASE_EXPIRED` | `expires_at` | `status = expired` | — |
| `RUNNER_AUTHENTICATE`(拒否のみ) | — | — | — |
| `RUNNER_HEARTBEAT` / `RUNNER_SWEEP`(拒否のみ) | — | — | — |

トークンの値・ハッシュは、どの記録にも入れない。`job_id` は `LEASE_EXPIRED` で設定する。`ASSIGN` は 001 の記録に `runner_id` と `lease_id` を加える。

---

## 8. 不変条件(テストで検査する)

1. 1 件のジョブに `ACTIVE` かつ期限前のリースは高々 1 つ。1 台のランナーにも高々 1 つ(001 の「未終了のジョブは 1 件」と一致)。
2. `ACTIVE` のリースのジョブは、001 で `RUNNING` かつ `assigned_runner_id = lease.runner_id`(終了したら次の生存通知・定期処理で `ENDED`)。
3. 1 台のランナーに有効なトークンは高々 1 つ。削除したランナーに有効なトークンはない。
4. 削除されていないランナーの名前は一意。
5. ランナーの `capabilities` のキーは、受け付けた時点の許可リストに含まれていた。
6. `ONLINE` 以外のランナーに、その状態の間に作られたリースはない(SC-002、SC-006)。
