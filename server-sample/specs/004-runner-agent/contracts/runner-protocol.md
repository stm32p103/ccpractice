# 契約: ランナープロトコル(版 1.1 — 003 の最小版を拡張)

**形式**: HTTP(`/v1/runner/*`)。メッセージの形は [runner-protocol.schema.json](runner-protocol.schema.json)(JSON Schema、`additionalProperties: false`)。
**共有**: `runner-protocol/`(`job_runner_protocol`)が、スキーマと値の型を持つ。エージェントとコア API の両方が同じスキーマで検査する(憲章 原則 1)。
**方向**: すべて、ランナー(エージェント)からコア API への要求と、その応答。コアからランナーへの着信接続はない(憲章 原則 8)。
**互換性**: 003 のエンドポイント(登録・生存通知・異常の申告と回復・割り当ての要求・終了の報告・停止の確認)は、**加えるだけ**で、既存の項目の意味を変えない。版は `runner-protocol` の版(1.1)で管理し、破壊的な変更は 2.0 で行う。

認証: `Authorization: Bearer rt_…`(ランナーのトークン)。ランナーの識別子は URL に含めず、認証した主体から取る(003 R16)。ランナー以外の主体は、これらを呼べない。

## 1. 003 から変わらないもの(参考)

| エンドポイント | 用途 | 変更 |
|---|---|---|
| `POST /v1/runner/registration` | 起動時の登録(能力の申告) | 応答 `HeartbeatResult` に `abort_requested` を加える |
| `POST /v1/runner/heartbeat` | 生存通知(リースの延長) | 同上 |
| `POST /v1/runner/fault` / `DELETE /v1/runner/fault` | 機材の異常・回復の申告 | 同上(応答のみ) |
| `POST /v1/runner/job-requests` | 割り当ての要求 | 変更なし(応答は 003 のとおり。payload を含むのはこの応答だけ。E16) |
| `POST /v1/runner/jobs/{job_id}/stopped` | 中断の確認 | 変更なし |

`HeartbeatResult` の追加項目: `abort_requested: bool` — このランナーに割り当て中のジョブに、中断の要求がある。ジョブ・利用者の情報を含めない。

## 2. 加えるエンドポイント

| エンドポイント | 用途 | 成功 | 拒否 |
|---|---|---|---|
| `POST /v1/runner/jobs/{job_id}/logs` | ログのチャンクの送信。本文: `LogChunk`。**同じ `seq` の再送は冪等** | `200` `LogChunkResult`(`stored_up_to_seq`) | `403 runner_mismatch`(割り当て先でない)、`409 target_not_running`・`lease_expired`、`413 payload_too_large`(チャンクの上限)、`422 validation_failed`、`409 log_quota_exceeded`(総量の上限。エージェントは切り詰めて続ける)、`409 log_seq_conflict`(同じ `seq` で内容が異なる) |
| `POST /v1/runner/jobs/{job_id}/source-credential` | ジョブのソースの取得資格(短命・読み取り専用)の要求。本文: なし(`{}`) | `200` `SourceCredential` | `403 runner_mismatch`、`409 target_not_running`、`422 source_not_available`(取得資格の発行元がない構成) |
| `POST /v1/runner/jobs/{job_id}/result` | 終了の報告。本文: `FinishReport`(003 の `outcome`・`result_summary` に、`exit_code`・`failure_reason`・`artifacts`・`counters` を加える。追加は任意で、省略可) | `200` `FinishResult` | 003 のとおり(`403`・`404`・`409 invalid_state_transition`・`lease_expired` など)。`422 validation_failed` |

利用者向け(WebUI・API の利用者。権限 `job.read_output`):

| エンドポイント | 用途 | 権限 | 成功 |
|---|---|---|---|
| `GET /v1/jobs/{job_id}/logs?after_seq=&limit=` | ログの範囲の取得(`seq` の順。既定 `limit` 200、最大 1000)。本文はエージェントでマスク済み | `job.read_output` | `200` `LogPage`(`chunks`、`next_seq`、`complete`: ジョブが終了し、全チャンクを返した) |
| `GET /v1/jobs/{job_id}/artifacts` | 成果物の参照の一覧(`ArtifactReference`)。中身は返さない | `job.read_output` | `200` |

- 参照の取得(`GET`)は、監査ログに記録する(`LOG_READ`、`ARTIFACT_READ`。誰が・いつ・どのジョブを。内容は記録しない)。
- 権限のない利用者は `403 permission_denied`(`required_permissions` に `job.read_output`)。ジョブの存在は、001 の閲覧の範囲(すべての利用者が見られる)のとおり。
- ログ・成果物の参照は、変更の通知(SSE)・監査・エラー・通知・書き戻しに含めない。クライアントは、ジョブの状態の通知を契機に、`after_seq` を使って取得する(通知専用のイベントは加えない)。

## 3. 振る舞いの約束

### 3.1 ログ(FR-004、R10)

- `seq`: ジョブの中で、0 から連続する整数。エージェントが付ける。コアは `(job_id, seq)` を一意として保存する。
- 順序: エージェントは `seq` の順に送るが、コアは順不同を受理して、`seq` の順に返す。
- 再送: ネットワークの失敗で応答を得られなかったチャンクは、同じ内容で再送する。同じ `seq`・同じ内容は `200`(冪等)、異なる内容は `409 log_seq_conflict`。
- 量: 1 チャンクは本文 64 KiB まで。ジョブごとの総量(既定 10 MiB)を超えると `409 log_quota_exceeded`。エージェントは、それ以降を送らず(切り詰め)、`counters.log_truncated = true` を報告する。
- 保持: ジョブの保持期間(001 FR-031)と同じ。

### 3.2 取得資格(FR-026、E7)

- コアは、ジョブの割り当て先のランナーに、**そのジョブのソース・リビジョンに限った**短命(既定 10 分)・読み取り専用の資格を、`SourceCredentialIssuer` から得て返す。保存しない。同じジョブへの再要求は、新しい資格を発行する。
- 応答は、`kind`(資格の種類を示す固定の語彙)、`secret`(不透明な文字列)、`expires_at`。`secret` は、ログ・監査・エラー・イベントに含まれない。
- エージェントは、取得の直後に `secret` を破棄する。

### 3.3 結果の報告(FR-005、FR-007、FR-024)

- `outcome`: `succeeded` \| `failed`。タイムアウトは `failed` + `failure_reason = "timeout"`。中断は、`result` ではなく `stopped`(003)で報告する。
- `exit_code`: ツールが終了した場合のみ。起動しなかった・強制終了のときは `null`。
- `failure_reason`: 固定の語彙([schema](runner-protocol.schema.json))。`outcome = failed` のときだけ。
- `result_summary`: 最大 200 文字。エグゼキュータが作る。マスク済み。
- `artifacts`: 最大 100 件の `ArtifactReference`。成果物の**中身は送らない**。`reference` は、`kind = unc` なら UNC パス、`kind = url` なら HTTPS の URL に限る。作業フォルダ外のローカルパスを含めない。
- `counters`: `path_rejections`、`masked_lines`(整数)、`log_truncated`(真偽)。内容を含まない。
- 重複・競合: 同じジョブへの 2 回目の報告は、003 の規則どおり拒否される(`409 invalid_state_transition`・`lease_expired`)。エージェントは、これを**確定の拒否**として扱い、記録して破棄する(結果を重複して作らない)。
- リース切れ(FR-024): リースが切れたジョブは、コアが `failed`(理由 `lease_expired`)に確定している。以後のこのリースによる報告・生存通知の延長は拒否される。

### 3.4 中断(FR-006)

1. 利用者が、001 の強制中断(`POST /v1/jobs/{id}/cancel`)を行う。コアは中断の要求を記録する。
2. 次のランナーの生存通知の応答で、`abort_requested = true` を返す。
3. エージェントは、ツールを停止し、`POST /v1/runner/jobs/{job_id}/stopped` を送る。コアが `CANCELLED` に確定する。
4. 停止と完了が競合した場合は、先に確定した状態が優先され、後の報告は `409` で拒否される(001 の不変条件)。

## 4. 書き出し台帳との対応

| 台帳 | 本契約の項目 |
|---|---|
| E4 | `registration`(許可リストの能力)、`heartbeat`、`fault`(≤ 200 文字、002)、`result` の `outcome`・`failure_reason`・`counters`(件数だけ) |
| E5 | `logs`(マスク済み。量の制限あり) |
| E6 | `result` の `artifacts`(参照だけ。本体は保存先へ) |
| E7・E16 | `source-credential`(台帳に反映済み。2026-11-22) |
| E16 | `job-requests` の応答(003)、`HeartbeatResult` の `abort_requested`(台帳に反映済み) |

契約テスト `RunnerProtocolContract`: `FakeRunnerCore` と、コア API(`build_api()`)の両方で、同じ呼び出しの列が同じ結果になる。スキーマ違反(未知の項目、上限超過)は `422`。
