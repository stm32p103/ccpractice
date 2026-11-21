# 契約: ポート(core が外に求めるもの)

**対象**: `job_core.job.application.ports`、`job_core.shared.ports`
**実装**: Fake(`job_testing.core_fakes`)、実アダプタ(core-persistence。003 と合わせて実装)、002(`RunnerEligibility`)
**検証**: `job_testing.contracts` の契約テストを、Fake と実アダプタの両方で実行する(憲章 原則 11)

シグネチャは Python の `typing.Protocol` で定義する。ここでは振る舞いの約束を記す(実装コードは tasks / 実装の段階で書く)。

---

## UnitOfWork

```text
class UnitOfWork(Protocol):
    jobs: JobRepository
    queue: QueueRepository
    audit: AuditLog
    outbox: Outbox
    def __enter__(self) -> Self
    def __exit__(...) -> None          # 例外時はロールバック
    def commit(self) -> None
```

約束:

1. `commit` は、ジョブ・待機列・監査ログ・アウトボックスへの変更を**すべて確定するか、何も確定しない**(原子性)。
2. 読み込んだ集約の `version` が、コミットの時点で永続化側の値と一致しなければ、何も確定せず `ConcurrencyConflict` を送出する。
   確定に成功したら、各集約の `version` を 1 増やす。
3. 集約に積まれたドメインイベントは、`commit` の中でアウトボックスへ `PENDING` として書かれる。
4. `commit` せずに `__exit__` した場合は、何も確定しない。
5. 別々の UoW の同時のコミットは、上記 2 によって直列化された結果と同じになる。

Fake は、テスト用に「コミットの直前に任意の操作を割り込ませる」フックを持つ(同時実行のシナリオの再現。R16)。

## JobRepository

```text
def get(job_id) -> Job | None
def add(job: Job) -> None
def save(job: Job) -> None
def find_queued_by_duplicate_key(key: DuplicateKey) -> Job | None
def find_unfinished_by_runner(runner_id) -> Job | None
def find_retries_of(job_id) -> list[JobId]
def exists(job_id) -> bool
def list_by_states(states, cursor, limit) -> Page[Job]
def delete_finished_before(cutoff: datetime) -> int
```

約束: `delete_finished_before` は終了状態で `finished_at < cutoff` のジョブだけを消す。待機中・実行中は消さない(FR-031)。
`find_queued_by_duplicate_key` は待機中のジョブだけを返す(FR-006)。

## QueueRepository

```text
def get() -> Queue                     # 1 本の待機列。なければ空の待機列
def save(queue: Queue) -> None
```

約束: `get` が返す `entries` の順序は、最後に確定した `save` の順序と一致する。

## AuditLog

```text
def append(record: AuditRecord) -> None                    # 同じ UoW の中で確定する
def append_denied(record: AuditRecord) -> None             # 呼び出し時点で独立に確定する(本体がロールバックしても残る)
def history_of(job_id) -> list[AuditRecord]                # outcome=SUCCEEDED のみ、occurred_at 順
def query(filter, cursor, limit) -> Page[AuditRecord]      # 全件(DENIED を含む)
def delete_before(cutoff: datetime) -> int
```

約束: 記録は追記のみで、変更されない。`delete_before` 以外で消えない(FR-032)。

## Outbox

```text
def add(event: JobCompleted) -> None                       # UoW の commit から呼ばれる
def fetch_pending(limit) -> list[OutboxEntry]
def mark_dispatched(event_id, at) -> None
def record_attempt(event_id, at) -> None
```

約束: `add` された同じ `event_id` は 1 件だけ。`mark_dispatched` までは `fetch_pending` に何度でも現れる(少なくとも 1 回の配信。FR-027、SC-008)。
配信処理そのもの(取り出しのループ、再送の間隔と上限)は 003 / 007 が実装する。

## RunnerEligibility(002 が実装。001 は Fake)

```text
def any_registered_runner_may_satisfy(requirement: RunnerRequirement) -> bool
def runner_satisfies(runner_id: RunnerId, requirement: RunnerRequirement) -> bool
```

約束:

- `any_registered_runner_may_satisfy` は、登録済みのランナー(空き・稼働状態を問わない)の能力だけで判定する(FR-002)。
- `runner_satisfies` は、そのランナーの能力で要件を満たすかだけを返す(使用中かどうかは 001 がジョブ側で判定する。R6)。
- どちらも副作用を持たない。

Fake: ランナーの識別子 → 能力の集合 の表と、「要件 = 能力の部分集合」とする単純な照合で実装する(002 の照合規則の代わり)。

## Clock / IdGenerator(shared)

```text
class Clock(Protocol):       def now(self) -> datetime     # タイムゾーン付き UTC
class IdGenerator(Protocol): def new_id(self) -> str
```

Fake: 固定・手動で進められる時計、連番の ID。

---

## 契約テストの一覧(`job_testing.contracts`)

| テスト群 | 主な検査 |
|---|---|
| `UnitOfWorkContract` | 原子性、`version` の衝突でのロールバック、イベントのアウトボックスへの書き込み、未コミットの破棄 |
| `JobRepositoryContract` | 保存と復元の同一性(全項目)、重複の鍵の照合、削除の対象の限定 |
| `QueueRepositoryContract` | 並び順の保存と復元、空の待機列 |
| `AuditLogContract` | 追記のみ、`append_denied` が本体のロールバックの影響を受けない、`history_of` が DENIED を含まない |
| `OutboxContract` | 未配信の再取得、配信済みの除外、`event_id` の一意性 |
| `RunnerEligibilityContract` | 副作用がないこと、登録済みのランナーだけで判定すること(002 の実装も同じテストを通す) |
| `QueueJobConsistency` | 待機列の `entries` と `QUEUED` のジョブが一致する(不変条件 2) |
