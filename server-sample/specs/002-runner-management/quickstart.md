# クイックスタート(試行と検証の手順): コア — ランナーとジョブの割り当ての管理

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

002 は 001 と同じ core パッケージに `runner` コンテキストを加える。HTTP・DB・ランナーの実機は使わず、Fake(偽のリポジトリ・手動で進める時計・決定的なトークン)で、
spec の受け入れシナリオがすべて成り立つことを確認する。ランナーエージェントとの通しの試行は 003・004 と合わせて行う。

---

## 1. 前提と構築

001 の [quickstart.md](../001-core-job-queue/quickstart.md) §1〜§2 と同じ(`.\ops\dev\setup-dev.ps1`)。002 で新しい依存・取得先・秘密情報は加えない(research R17)。

## 2. 検証の実行

001 の V1〜V11 に、次を加える。`.\ops\dev\setup-dev.ps1 -VerifyOnly` は V1〜V18 を順に実行する。

| # | 検証 | コマンド | 期待 |
|---|---|---|---|
| V12 | 照合の単体テスト(5 種の比較、1 つの値/集合、型の不一致、版・数値の性質) | `uv run pytest core/tests/unit/runner/test_matching.py` | 全件成功(SC-001) |
| V13 | ランナーの状態の導出・リースの遷移 | `uv run pytest core/tests/unit/runner` | 優先順(FR-010)の全組み合わせが期待どおり |
| V14 | 受け入れシナリオ(US1〜US7、エッジケース) | `uv run pytest core/tests/acceptance/runner` | 全件成功。テスト名に `us3_5` などのシナリオ番号を含む |
| V15 | 判定と割り当ての一致 | `uv run pytest core/tests/acceptance/runner -k eligibility_consistency` | ランダムな能力と要件で食い違い 0 件(SC-001) |
| V16 | 権限の網羅 | `uv run pytest core/tests/unit/test_authorization.py` | 12 権限の全部分集合(4096 通り)で期待どおり(SC-009) |
| V17 | トークンの非露出・同時実行 | `uv run pytest core/tests/acceptance/runner -k "token or concurrency"` | トークンの値・ハッシュが戻り値・監査・例外に現れない(SC-008)。同時の要求で 1 台だけに割り当て(SC-002) |
| V18 | 性能の目安 | `uv run pytest core/tests/perf -m perf -k request_job` | 待機中 500 件・ランナー 50 台で `RequestJob` が 50 ms 以下(SC-003 の core 部分) |

V4(契約テスト)、V6(依存規則。`job` が `runner` を import しない契約を含む)、V7(語彙・禁止 API)、V10(静的検査)は、002 の追加分も対象になる。

## 3. 手で確かめるシナリオ(対話型)

`uv run python` で、`job_testing.core_fakes.build_core()` が返すユースケースの集合を使う(002 のユースケースも含む)。
人間の主体には `runner.manage` と `job.general` を、定期処理の主体には `runner.sweep` を付ける。ランナーの主体は `AuthenticateRunner(token)` で得る。
キーは記号(`k1`、`set1`)を使う(用途固有の語を使わない)。

1. **作成と登録**(US1-1、US1-3): 許可リストを `{k1: single, set1: set}` にする → `CreateRunner("r-a")` でトークンを受け取る → `AuthenticateRunner` → `RegisterRunner({k1: "a", set1: ["x", "y"]})` → `ListRunners` で `ONLINE`、能力が表示される。トークンは表示されない。
2. **許可リスト外のキー**(US1-5): `RegisterRunner({k9: "z"})` → `InvalidDeclaration`。能力は変わらない。
3. **判定**(US2-1、US2-6): 時計を 2 分進めて offline にする → 要件 `{"all": [{"key": "set1", "op": "contains", "values": ["y"]}]}` で `SubmitJob` が受け付けられる(状態は見ない)。
4. **条件を満たすジョブだけ**(US3-1): 要件の合わない A、合う B を提出 → 生存通知で online に戻す → `RequestJob` が B とリースの期限を返す。A は待機列に残る。
5. **生存通知とリース**(US4-2、US4-4): 30 秒ごとに `Heartbeat` → `lease_expires_at` が延びる。通知を止めて 3 分進める → `Heartbeat` の `lease_expires_at` は `None`、`SweepRunners` で `LEASE_EXPIRED` が記録される。
6. **機材の異常**(US5-1、US5-2): `ReportFault("e1")` → `RequestJob` は `NOT_ONLINE(FAULT)`。`ReportRecovered` → 割り当てが再開される。
7. **maintenance**(US6-1、US6-2): 実行中のジョブを持つランナーを `SetMaintenance` → ジョブは実行中のまま、`Heartbeat` でリースは延びる。新しい割り当ては行われない。
8. **削除の拒否**(US6-5): 実行中のジョブを持つランナーの `DeleteRunner` → `RunnerHasUnfinishedJob`。
9. **トークンの失効と再発行**(US7-1、US7-2): `ReissueToken` → 旧トークンの `AuthenticateRunner` は `RunnerAuthenticationFailed`、新トークンは成功。
10. **別のランナーへのなりすまし**(US7-4): r-b のトークンで得た主体で、`runner_id = r-a` の `Heartbeat` → `RunnerMismatch`、監査ログに `DENIED`。

## 4. 完了の判定

- V1〜V18 がすべて成功する。
- 新しい Windows PC で、`setup-dev.ps1` だけで構築し、`-VerifyOnly` が成功する。再実行(アップグレード)でも成功する(憲章 原則 14)。
- 参照: 入出力と拒否は [contracts/application-api.md](contracts/application-api.md)、ポートは [contracts/ports.md](contracts/ports.md)、要件と申告の形は [contracts/](contracts/) の JSON Schema、モデルは [data-model.md](data-model.md)。
