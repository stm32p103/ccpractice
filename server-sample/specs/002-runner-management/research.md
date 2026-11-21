# 調査と判断: コア — ランナーとジョブの割り当ての管理(最小版)

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-11-21

spec の `[NEEDS CLARIFICATION]` は 0 件(Clarifications 2026-11-21 で解決済み)。本書は、plan の段階で決めた技術上の判断を記す。
001 の判断([../001-core-job-queue/research.md](../001-core-job-queue/research.md) の R1〜R18)は、ことわりがない限りそのまま引き継ぐ。

---

## R1. 配置(パッケージとコンテキスト)

- **Decision**: 001 と同じパッケージ `job_core` に、コンテキスト `job_core.runner`(`domain/`、`application/`)を追加する。
  依存の向きは `runner → job`(application 同士、domain 同士)と `runner → access / shared` だけとし、`job` は `runner` を import しない(import-linter の契約を追加)。
  001 の `RunnerEligibility` ポートは、`runner.application` が実装する。
- **Rationale**: inputs/02-modules は「core(001, 002)」を 1 モジュールとし、001 plan の Structure Decision も「002 は同じ `job_core` に `runner/` を追加」と定めた。
  割り当て(待機列からの取り出し)とリースの作成を同じ Unit of Work で確定するには、同じパッケージにある方が単純。
- **Alternatives considered**: 別パッケージ `runner-core` にする — 割り当ての原子性(R4)のために UoW をパッケージ間で共有する必要が出て、契約が複雑になるため不採用。

## R2. 能力と要件の表現(FR-005、FR-007。Clarifications Q1)

- **Decision**:
  - **能力**: キー → 値。値は「1 つの値(文字列)」か「値の集合(文字列の集合)」。数値・版も文字列として持ち、比較のときに解釈する(コアは値の意味を解釈しない。FR-005)。
    - キー: `^[a-z0-9][a-z0-9._-]{0,63}$`。値の文字列: 1〜256 文字、制御文字を含まない。集合: 0〜64 要素、重複は 1 つにまとめる。
  - **要件**: JSON の `{"all": [条件, ...]}`。すべての条件を満たすとき「要件を満たす」(空の `all` はすべてのランナーが満たす)。条件は `{"key", "op", "value" | "values"}`。

    | `op` | 意味 | 指定値 | 能力の値の型 |
    |---|---|---|---|
    | `eq` | 一致 | `value`: 文字列 | 1 つの値 |
    | `in` | いずれかに一致 | `values`: 文字列の配列(1 個以上) | 1 つの値 |
    | `num_gt` / `num_ge` / `num_lt` / `num_le` | 数値の大小 | `value`: 10 進数の文字列 | 1 つの値(10 進数として解釈できること) |
    | `ver_gt` / `ver_ge` / `ver_lt` / `ver_le` | 版の大小 | `value`: 版の文字列 | 1 つの値(版として解釈できること) |
    | `contains` | 包含(すべて含む) | `values`: 文字列の配列(1 個以上) | 集合 |

  - **数値**: `^-?\d+(\.\d+)?$` を `decimal.Decimal` で比べる(浮動小数点の誤差を避ける)。
  - **版**: `^\d+(\.\d+){0,7}$` を整数の並びとして比べ、短い方の末尾を 0 で補う(`1.2` = `1.2.0`)。プレリリース表記(`-rc1` 等)は扱わない。
  - **型の不一致**: 要件の側(未知の `op`、指定値の形が `op` に合わない、`value` が数値・版として解釈できない)は**文法のエラー**(`InvalidRequirement`)。
    能力の側(キーがない、1 つの値に `contains`、集合に `eq`、数値として解釈できない値に `num_*`)は、その条件を**満たさない**(Edge Cases)。
  - 形は JSON Schema で公開する([contracts/runner-requirement.schema.json](contracts/runner-requirement.schema.json))。
- **Rationale**: spec Clarifications Q1(集合を許し、5 種類の比較)。比較の種類と値の形を JSON の構造で分けておくと、文法の検査(FR-008)を純粋な関数で網羅的にテストできる(12-plan「要件マッチングは純粋な関数で網羅的にテスト」)。
- **Alternatives considered**:
  - 文字列の式(`"os == x && fw >= 1.2"`)— 構文解析器が要り、プロファイル(用途側)が機械的に作りにくいため不採用。
  - 値を JSON の数値・真偽値でも持つ — 申告側と要件側で型の揺れ(`"1"` と `1`)が起き、照合の規則が増えるため不採用。
  - `contains` を「いずれかを含む」とする — 包含は「すべて含む」の方が要件として素直で、「いずれか」は `all` を分けても書けないが、必要になるまで加えない。

## R3. 照合の純粋関数と、判定・割り当ての同一性(FR-009、SC-001)

- **Decision**: `runner.domain.matching` に 2 つの純粋関数を置く。
  - `parse_requirement(RunnerRequirement) -> ParsedRequirement`(文法の検査。不正なら `InvalidRequirement`)
  - `satisfies(capabilities, parsed) -> bool`
  判定(`any_registered_runner_may_satisfy`、`runner_satisfies`)と割り当て(`RequestJob`)は、どちらもこの 2 つだけを使う。
  `parse_requirement` は正準化済みの JSON 文字列を鍵にメモ化する(待機中 500 件の走査で毎回解析しないため。R11)。
- **Rationale**: FR-009「判定と割り当てで同じ規則」。同じ関数を通すことが、食い違い 0 件(SC-001)の構造上の担保になる。
- **Alternatives considered**: 判定を永続化側の問い合わせ(SQL)で行う — 規則が 2 か所に分かれ、SC-001 を保証できないため不採用。

## R4. 割り当てとリースの原子性(FR-013〜FR-015)

- **Decision**: ランナー用のユースケース `RequestJob` を 002 に置き、**1 回の UoW** で次を行う。
  1. ランナーを読み込み、状態(R6)が online か確かめる。maintenance・機材の異常・offline・削除済みなら「割り当てなし」(理由付き)。
  2. 001 の割り当ての本体(待機列の走査 → 取り出し → ジョブを実行中へ → 監査 `ASSIGN`)を、そのランナーの能力で照合する述語を渡して実行する。
  3. 割り当てたら、リース(`Lease`)を作り、同じ UoW でコミットする。
  001 の `AssignNextJob` の本体を、UoW を受け取る関数 `assign_next_in(uow, deps, principal, runner_id, satisfies)` として切り出し、
  `AssignNextJob` はそれを呼ぶだけにする(001 の振る舞いと受け入れテストは変えない)。
  コア API(003)がランナーに公開するのは `RequestJob` だけとし、`AssignNextJob` は公開しない(ランナーの状態の確認を迂回させないため)。
- **同時実行**: ランナー・待機列・ジョブ・リースの `version` で楽観的排他を行い、衝突したら判定からやり直す(001 R4 と同じ)。
  - 2 台が同じジョブを求める → 待機列の `version` の衝突で一方がやり直し、別のジョブか「割り当てなし」になる(FR-014、US3-5)。
  - maintenance の設定・異常の申告と割り当てが同時 → ランナーの `version` の衝突で割り当てがやり直し、状態を見て「割り当てなし」になる(SC-006)。
- **Rationale**: 割り当てとリースを別々に確定すると、間の障害で「実行中なのにリースがない(切れることもない)」ジョブが残る。
- **Alternatives considered**:
  - 001 の `AssignNextJob` に「ランナーの可否」のポートを足す — 001 のポートが 002 の状態の概念を知ることになり、001 の UoW にリースを書けないため不採用。
  - リースを `Job` の項目にする — 001 R6・R7 が「リースは 004 / 002 で扱い、001 の遷移表を壊さない」としたため不採用。

## R5. Unit of Work の拡張

- **Decision**: `runner.application.ports` に `RunnerUnitOfWork(UnitOfWork, Protocol)` を定義し、001 の UoW の項目(jobs、queue、audit、outbox)に、
  `runners`、`leases`、`tokens`、`allowlist` を加える。約束(原子性、`version` の比較、未コミットの破棄)は 001 と同じ。
  001 のユースケースは 001 の `UnitOfWork` だけを見るので、そのまま `RunnerUnitOfWork` の上で動く。
- **Rationale**: 001 のポートを変えずに、割り当て・削除(実行中のジョブの確認)・リース切れを 1 回の UoW で扱える。
- **Alternatives considered**: 002 専用の UoW を別に持つ — R4 の原子性が成り立たないため不採用。

## R6. ランナーの状態(FR-010)

- **Decision**: 状態は**保存せず、時刻から導く**。`Runner.state_at(now, policy)` が、spec FR-010 の優先順で返す。
  1. `maintenance` が設定されている → `MAINTENANCE`
  2. 機材の異常がある → `FAULT`
  3. 一度も登録していない、または `now - last_seen_at > offline_after` → `OFFLINE`
  4. それ以外 → `ONLINE`
  割り当ての可否は、この導出の結果だけで決める(定期処理の遅れに左右されない)。
  監査ログの「自動の online / offline の変化」(FR-028)のために、ランナーは最後に記録した接続の状態(`recorded_connectivity`)を持つ。
  - 登録・生存通知で `OFFLINE → ONLINE` になったとき、その操作の UoW で記録する。
  - 定期処理 `SweepRunners`(R8)が、導出で offline になったランナーを見つけたとき記録する。
- **Rationale**: SC-004(途絶から offline と判定する時間 + 30 秒以内に offline になり、以後割り当てない)を、定期処理の間隔に依らず割り当ての側で満たせる。記録(表示と監査)は定期処理の間隔(既定 15 秒)で追い付く。
- **Alternatives considered**: 状態を保存し、定期処理だけで遷移させる — 定期処理が止まると offline のランナーに割り当ててしまうため不採用。

## R7. 生存通知とリース(FR-015〜FR-018)

- **Decision**: 設定値 `RunnerTimingPolicy(heartbeat_interval = 30 秒, offline_after = 90 秒, lease_duration = 180 秒)`。
  生成時に `offline_after >= 2 × heartbeat_interval` と `lease_duration >= 2 × heartbeat_interval` を検査し、満たさなければ設定エラー(FR-016)。
  - **生存通知** `Heartbeat`: ランナーの `last_seen_at` を更新し、そのランナーの**有効な**リース(期限前で、ジョブが実行中で、割り当て先がそのランナー)があれば、`expires_at = now + lease_duration` に延長する。
    応答は、導出した状態、リースの期限(あれば)、生存通知の間隔。
  - **期限切れ**: `now > expires_at` のリースは、記録の有無にかかわらず期限切れとして扱い、延長しない(FR-017)。`SweepRunners` が `EXPIRED` として記録し、監査 `LEASE_EXPIRED` を残す。
  - **リースの終了**: ジョブが終了状態になったリースは、次の生存通知・定期処理で `ENDED` とする(001 の終了の報告のユースケースを変えないため)。
  - リース切れのジョブは実行中のまま残る(扱いは 004)。そのランナーには、001 の「未終了のジョブを持つ」判定により新しい割り当てが行われない。
  - 時刻はすべてポート `Clock`(サーバー側)から得る(FR-018)。ランナーが送る時刻は使わない。
- **Rationale**: 既定値は spec の Assumptions。延長を受信時刻から計算するので、重複・遅延した生存通知でも結果が変わらない(Edge Cases)。
- **Alternatives considered**: リース切れで自動的に待機列へ戻す — spec FR-017 で 004 と別途定めるとしたため、本 feature では行わない。

## R8. 定期処理 `SweepRunners`

- **Decision**: ユースケース `SweepRunners(now)` を用意する。offline になったランナーの記録(R6)と、期限切れのリースの記録(R7)を行う。
  呼び出しの間隔(既定 15 秒)と仕組み(スケジューラ)は 003 / 009 の責務。実行には権限 `runner.sweep` を要する(R10)。
  何度実行しても結果は同じ(冪等)。
- **Rationale**: 001 R13(`PurgeExpired`)と同じ形。core は定期実行の手段を持たない。

## R9. ランナーのトークン(FR-022〜FR-025)

- **Decision**:
  - 発行: ポート `SecretGenerator` が 32 バイトの乱数から URL で安全な文字列を作る(既定の実装は標準ライブラリ `secrets.token_urlsafe(32)`。Fake は決定的)。
    トークンの形は `rt_<乱数の文字列>`(接頭辞は、ログ・設定ファイルでの誤った露出を検査で見つけやすくするため)。
  - 保存: `SHA-256(トークン)` の 16 進文字列だけを保存し、値は保存しない(FR-022)。乱数が 256 ビットあるため、遅いハッシュ関数(鍵導出)は要らない。
    照合は、受け取ったトークンのハッシュで検索し、見つけた値と `hmac.compare_digest` で比べる。
  - 1 台のランナーに有効なトークンは 1 つ。再発行は、旧トークンの失効と新トークンの発行を同じ UoW で行う(FR-023)。
  - 認証: ユースケース `AuthenticateRunner(token) -> Principal` を用意する。有効なら `Principal(subject_id = runner_id, permissions = {runner.report, job.execute}, kind = RUNNER)` を返す。
    無効(未知・失効・削除済みのランナー)なら `RunnerAuthenticationFailed` とし、監査ログに `DENIED`(`denial.code = authentication_failed`)を記録する。トークンの値・ハッシュは記録しない。
  - コア API(003)は、ランナーからの要求ごとに `AuthenticateRunner` を呼び、返った主体でランナー用のユースケースを呼ぶ。
    ランナー用のユースケースは、引数の `runner_id` が `principal.subject_id` と一致しなければ `RunnerMismatch` で拒否する(別のランナーのトークンの拒否。FR-024、US7-4)。
- **Rationale**: 12-plan「ランナー(ランナーごとのトークン、ハッシュで保存)」。トークンが与える権限を 2 つに固定することで、FR-025(トークンではランナーとしての操作しかできない)を権限の判定で担保する。
- **Alternatives considered**:
  - トークンの検証を 003 に置く — spec FR-022〜FR-024 が発行・失効・受け付けの規則を 002 に置いているため、規則と保存を core に置き、003 は伝送(HTTP の認証ヘッダー)だけを担う。
  - PBKDF2 等で保存 — 人が選ぶパスワードではなく高エントロピーの乱数なので、効果がなく、要求ごとの照合が遅くなるため不採用。
  - 12-plan の「1 回限りの登録コード」— 環境構築の流れ(009)で扱う。本 feature は spec Assumptions の最小の形(作成時にトークンを 1 度だけ返す)とする。

## R10. 権限(FR-026)

- **Decision**: 001 の 9 種に、次の 3 種を加える(合計 12 種)。

  | 権限 | 識別子 | 用途 |
  |---|---|---|
  | ランナー管理 | `runner.manage` | 作成、maintenance の設定と解除、機材の異常の手動の解除、削除、トークンの発行と失効、能力のキーの許可リストの変更 |
  | ランナーの自己申告(plan で追加) | `runner.report` | 登録(能力の申告)、生存通知、機材の異常と回復の申告。ランナーのトークンにだけ付く |
  | ランナーの定期処理(plan で追加) | `runner.sweep` | `SweepRunners` の実行(定期実行の主体用) |

  - `RequestJob` は 001 の `job.execute` と `runner.report` の両方を要する(割り当ての取得 = ジョブの実行の一部、かつランナーとしての操作)。
  - ランナーの一覧の閲覧は、001 と同じく `job.general` を要する(R8 の解釈 3)。
  - `runner.manage` は `audit.read_all` を含まず、逆も同じ(spec FR-026)。
  - 権限の網羅テストは、12 種の部分集合(2^12 = 4096 通り)× 対象の状態の表駆動とする(SC-009)。
- **Rationale**: 憲章 原則 9、001 R8 の方針(主体の種類で判定しない)。

## R11. 性能(SC-003)

- **Decision**: 待機中 500 件・ランナー 50 台の Fake で、`RequestJob` が core 内で 50 ms 以下(SC-003 の 2 秒のうち core 分の目安。DB を含む計測は 003)。
  要件の解析は R3 のメモ化で 1 要件につき 1 回にする。照合は 1 条件あたり定数時間(集合は `frozenset`)。
- **Rationale**: 001 の SC-005 と同じ規模・同じ考え方。

## R12. 能力のキーの許可リスト(FR-004。憲章 S3)

- **Decision**: 1 個の集約 `CapabilityAllowlist` とし、キーごとに値の型(`single` = 1 つの値、`set` = 集合)を持つ。既定は空(= すべてのキーを拒否)。
  - 登録の申告は、(a) すべてのキーが許可リストにある、(b) 値の型が一致する、(c) R2 の長さ・文字の制限を満たす、のすべてを満たすときだけ受け付ける。1 つでも満たさなければ登録ごと拒否し、能力・状態・最終応答時刻を変えない(拒否は監査ログに記録)。
  - 許可リストの変更は、既存のランナーの能力を書き換えない(次の登録から効く)。変更は監査ログに残す。
- **Rationale**: spec FR-004、書き出し台帳 E4「許可リストのキーだけ」。既定拒否(S3)。
- **Alternatives considered**: 許可リスト外のキーを黙って捨てる — 申告側の設定の誤りが見えなくなり、何が送られたかが曖昧になるため不採用。

## R13. 機材の異常の申告(FR-011、FR-012。Clarifications Q3)

- **Decision**: ランナー用のユースケース `ReportFault(runner_id, description)` と `ReportRecovered(runner_id)`、
  人間用の `ClearFault(runner_id, reason)`(`runner.manage`)を用意する。
  - 説明: 1〜200 文字、改行・制御文字を含まない(書き出し台帳 E4 の「長さに上限」)。core は中身を解釈しない。
  - 異常のときの再申告は説明だけを更新する。異常でないときの回復の申告は何も変えない(監査にも残さない。冪等)。
  - PC 内のツールからランナーへの伝え方(ローカルの経路)は 004 で定める。core はランナーからの申告だけを受ける。
- **Rationale**: spec US5、Edge Cases。

## R14. 監査ログの拡張(FR-028)

- **Decision**: 001 の `AuditRecord` に任意の項目 `runner_id: RunnerId | None` を加え、`AuditOperation` に次を加える。
  `RUNNER_CREATE`、`RUNNER_REGISTER`、`RUNNER_ONLINE`、`RUNNER_OFFLINE`、`RUNNER_MAINTENANCE_SET`、`RUNNER_MAINTENANCE_CLEAR`、`FAULT`、`FAULT_RECOVERED`、`FAULT_CLEAR`、
  `RUNNER_DELETE`、`TOKEN_ISSUE`、`TOKEN_REVOKE`、`ALLOWLIST_CHANGE`、`LEASE_EXPIRED`、`RUNNER_AUTHENTICATE`(拒否のときだけ記録)。
  加えて、拒否のときだけ記録する `RUNNER_HEARTBEAT`(生存通知の権限・ランナーの不一致の拒否)と `RUNNER_SWEEP`(定期処理の権限の拒否)を持つ
  (権限・認証による拒否も記録する FR-028 のため。実装で追加)。
  `Denial.code` に `authentication_failed`、`invalid_declaration` を加える。
  - 自動の変化(`RUNNER_OFFLINE`、`LEASE_EXPIRED`)の操作者は、`SweepRunners` を呼んだ主体(kind = `SYSTEM`)とする。
  - `before` / `after` に、トークンの値・ハッシュを入れない。能力は値を入れる(変更前後の能力。FR-028)。
  - 生存通知そのもの(状態が変わらない通知)は記録しない(30 秒ごとの記録で監査ログが埋まるため。状態の変化だけを記録する)。
  - 001 の `history_of(job_id)` は変えない。ランナーごとの記録は `query(filter)` に `runner_id` の条件を加えて取り出す(閲覧は `audit.read_all`。spec FR-029)。
- **Rationale**: 1 つの記録源(001 R9)を保ち、閲覧範囲・保持期間を 001 と同じにする(FR-029)。
- **001 への影響**: 項目の追加は既定値付きで、001 の既存の記録・テストに影響しない。

## R15. 自動検査の拡張(FR-030、FR-031、SC-012)

- **Decision**: 001 R15 の検査を `job_core.runner` にも適用する(標準ライブラリのみ、禁止 API、語彙)。追加分:
  1. import-linter: `runner-layers`(`job_core.runner.application → job_core.runner.domain`)、`job-independent-of-runner`(`job_core.job` は `job_core.runner` を import しない)。
  2. 標準ライブラリのうち `secrets`・`hashlib`・`hmac`・`decimal` を使う(禁止 API には当たらない)。
  3. 語彙: `forbidden_terms.txt` は 001 のものを共有する(能力のキーの例に用途固有の語を使わず、テストでは記号のキー `k1`、`set1` 等を使う)。
  4. トークンの非露出(SC-008): 発行以外のすべてのユースケースの戻り値・監査記録・例外のメッセージを直列化し、発行したトークンの値・ハッシュが現れないことを property-based テストで確認する。

## R16. テスト方式

- **Decision**: 001 R16 と同じ道具(pytest、Hypothesis、Fake の UoW の割り込みフック)。追加分:
  - 照合: 5 種の比較 × 1 つの値/集合 × キーの有無 × 型の不一致 の表駆動テストと、版・数値の比較の性質(反射・反対称・推移・末尾の 0 の補い)の property-based テスト(SC-001)。
  - 判定と割り当ての一致: ランダムな能力と要件の組で、`any_registered_runner_may_satisfy` と `RequestJob` の結果が食い違わないことを property-based で確認(SC-001)。
  - 状態の導出: 優先順(FR-010)の全組み合わせ(maintenance × 異常 × 最終応答の経過 × 未登録)。
  - 時刻: 手動で進める Fake の時計で、生存通知・offline・リース切れを決定的に再現(SC-004、SC-005)。
  - 同時実行: 2 台の同時の要求、maintenance の設定と割り当ての同時、再発行と認証の同時(SC-002、SC-006)。
  - 契約テスト: `RunnerRepository`、`LeaseRepository`、`RunnerTokenRepository`、`CapabilityAllowlistRepository`、`RunnerCatalog` の契約を `job_testing.contracts` に加え、001 の `RunnerEligibilityContract` を 002 の実装でも通す。

## R17. 環境構築の支援(憲章 原則 14)

- **Decision**: 001 の `ops/dev/setup-dev.ps1` をそのまま使う。新しい依存(実行時・開発時とも)は加えないため、`uv.lock` と書き出し台帳 E15 の変更はない。
  `-VerifyOnly` の検証の一覧に、002 のテスト(V12〜)を加える。
- **Rationale**: 002 は core パッケージの中だけで完結し、DB・サーバーを持たない。

## R18. 脅威モデルの追記(憲章 S6)

- **Decision**: `docs/security/threat-model.md`(001 T001)に、ランナー管理の節を**実装の着手前に**追記する。少なくとも:
  トークンの漏えい・再利用(失効と再発行、ハッシュでの保存、非露出の検査)、別のランナーへのなりすまし(`RunnerMismatch`)、
  能力の偽りの申告(許可リストは「送ってよい項目」を制限するが、値の正しさは保証しない = 残るリスク。ランナー PC と設定の信頼に依る)、
  機材の異常の偽りの申告(割り当ての妨害 = 手動の解除と監査ログで対処)、異常の説明を経由した PC 内の情報の持ち出し(長さ・文字の制限、台帳 E4)、
  生存通知の大量送信(監査ログを埋めない設計 R14、流量の制限は 003)。
- **Rationale**: 憲章 S6「実装前に、脅威モデルを明文化する」。001 の脅威モデルには 002 の範囲がない。
