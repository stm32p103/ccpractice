# クイックスタート(試行と検証の手順): コア — ジョブの受付・キュー管理

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

001 は core パッケージ(ライブラリ)だけを作る。HTTP・DB・ランナーの実機は使わず、Fake(偽のリポジトリ・偽のランナー一覧・固定の時計)で、
spec の受け入れシナリオがすべて成り立つことを確認する。HTTP 経由の試行は 003 と合わせて行う(inputs/00-README「最初の試行 = 001 + 003」)。

---

## 1. 前提

- Windows 10/11 または Windows Server(憲章 原則 7)。Windows PowerShell 5.1 以上。
- Python 3.12 以上がインストール済み。
- ネットワーク: 構築時だけ、uv の公式の配布元と、公式のパッケージ索引(PyPI)への HTTPS(取得のみ。書き出し台帳 E15)。
  uv は設定ファイルで版と SHA-256 を固定し、Python のパッケージは `uv.lock` のハッシュで検証する。構築後は不要。
- 秘密情報: 不要。

## 2. 構築(冪等。何度実行してもよい)

```powershell
# ドライラン(何をするかだけを表示)
.\ops\dev\setup-dev.ps1 -WhatIf

# 構築: 事前確認 → uv の取得とハッシュの検証 → uv sync → 動作確認
.\ops\dev\setup-dev.ps1

# 撤去(.venv とキャッシュを削除)
.\ops\dev\setup-dev.ps1 -Uninstall
```

期待: 2 回目の実行で「変更なし」と表示される。ハッシュが一致しなければ停止し、何も導入しない。
設定値は `ops/dev/dev.config.psd1`(uv の版・SHA-256・配布元)。手順の詳細は [research.md R17](research.md#r17-環境構築の支援憲章-原則-14)。

## 3. 検証の実行

| # | 検証 | コマンド | 期待 |
|---|---|---|---|
| V1 | ドメインの単体テスト(状態遷移・待機列の不変条件) | `uv run pytest core/tests/unit` | 全件成功 |
| V2 | 受け入れシナリオ(US1〜US6、エッジケース) | `uv run pytest core/tests/acceptance` | 全件成功。テスト名に `us1_1` などのシナリオ番号を含む |
| V3 | 権限の網羅(SC-006) | `uv run pytest core/tests/unit/test_authorization.py` | 9 権限の全部分集合(512 通り)× 所有 × 状態 がすべて期待どおり |
| V4 | ポートの契約テスト(Fake) | `uv run pytest testing/tests` | 全件成功 |
| V5 | 同時実行のシナリオ | `uv run pytest core/tests/acceptance -k concurrency` | 「どちらか一方だけが成立」がすべて成り立つ |
| V6 | 依存規則(FR-028) | `uv run lint-imports` | 契約違反 0 件 |
| V7 | 語彙・標準ライブラリのみ・禁止 API(SC-009、FR-029) | `uv run pytest core/tests/architecture` | 検出 0 件 |
| V8 | イベントのスキーマと機密(SC-010) | `uv run pytest core/tests/contract/test_job_completed_event.py` | スキーマに適合し、payload・要約の値が現れない |
| V9 | 性能の目安(SC-005 の core 部分) | `uv run pytest core/tests/perf -m perf` | 待機中 500 件・ランナー 50 台で、提出の判定が 50 ms 以下 |
| V10 | 静的検査 | `uv run ruff check` / `uv run mypy --strict core/src testing/src` | エラー 0 件 |
| V11 | スクリプトの検査 | `Invoke-Pester ops/dev/tests` / `Invoke-ScriptAnalyzer` を `setup-dev.ps1`・`dev.config.psd1`・`tests/setup-dev.Tests.ps1` に実行(取得物の置き場所 `ops/dev/.cache` は対象外) | 全件成功 / 警告 0 件。Pester 5 と PSScriptAnalyzer は `setup-dev.ps1` が `ops/dev/.cache` に取得する |

全部をまとめて実行: `.\ops\dev\setup-dev.ps1 -VerifyOnly`(V1〜V11 を順に実行し、結果の一覧を表示)。

## 4. 手で確かめるシナリオ(対話型)

`uv run python` で、Fake を組み立てて操作できる(`job_testing.core_fakes.build_core()` が、Fake をつないだユースケースの集合を返す)。ランナー役の主体には `job.execute` を付与する。
次の流れで、spec の主要な振る舞いを目で確かめる。期待する結果は各シナリオの番号の spec の記述どおり。

1. **並んだ順に実行される**(US1-2、US1-3): ランナー R1(能力 `{os: x}`)を Fake に登録 → A、B を提出 → `AssignNextJob(R1)` が A を返す。
2. **要件を満たすランナーがない**(US1-1): 能力にない要件で提出 → `NoEligibleRunner`。
3. **先頭の前に追加(割り込み)**(US2-1): A、B、C を待機させ、`QUEUE_SCHEDULE` を持つ主体で X を `BEFORE A` に提出 → 一覧が X、A、B、C。
4. **移動**(US2-3、US2-4): C を `BEFORE A` → C、A、B。A を `AFTER B` → B、A、C 相当の結果。
5. **権限のない位置指定**(US2-6): `JOB_SUBMIT` だけの主体で位置指定 → `PermissionDenied`。監査ログ全体(`AUDIT_READ_ALL`)に `DENIED` が 1 件。
6. **強制中断**(US3-2): 実行中のジョブに `FORCE_ABORT` の主体で理由付きの中断 → `abort_pending = true` → `ConfirmStopped` → `CANCELLED`、アウトボックスに `JobCompleted` が 1 件。
7. **やり直し**(US4-1、US4-5): 失敗したジョブを別の主体がやり直す → 末尾に新しいジョブ、`retry_of` と `retries` で相互に辿れる、提出者はやり直した主体。
8. **操作の経緯**(US6-3、US6-4): 移されたジョブの `GetJobHistory` に、移した主体・日時・前後の位置が出て、拒否の記録は出ない。
9. **取りこぼしのない完了イベント**(US6-6): `fetch_pending` で取り出したイベントを `mark_dispatched` せずに再度取り出す → 同じ `event_id` が再び返る。
10. **割り当て先でないランナーからの報告**: R1 に割り当てたジョブについて、`job.execute` を持つ別のランナー R2 が `ReportFinished` を呼ぶ → `RunnerMismatch`、ジョブは実行中のまま、監査ログ全体に `DENIED` が 1 件。
11. **権限での判定**: `job.execute` を持たない主体が `AssignNextJob` を呼ぶ → 主体の種類が `RUNNER` でも `PermissionDenied`。

## 5. 完了の判定

- V1〜V11 がすべて成功する。
- 新しい Windows PC で、`setup-dev.ps1` だけで構築し、`-VerifyOnly` が成功する。再実行(アップグレード)でも成功する(憲章 原則 14)。
- 参照: 入出力と拒否の一覧は [contracts/application-api.md](contracts/application-api.md)、ポートの約束は [contracts/ports.md](contracts/ports.md)、モデルは [data-model.md](data-model.md)。
