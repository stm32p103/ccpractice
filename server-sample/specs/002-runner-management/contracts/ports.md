# 契約: ポート(002 が外に求めるもの)

**対象**: `job_core.runner.application.ports`
**実装**: Fake(`job_testing.core_fakes`)、実アダプタ(core-persistence。003 と合わせて実装)
**検証**: `job_testing.contracts` の契約テストを、Fake と実アダプタの両方で実行する(憲章 原則 11)

001 のポート([../../001-core-job-queue/contracts/ports.md](../../001-core-job-queue/contracts/ports.md))は変えずに使う。シグネチャは `typing.Protocol` で定義する。

---

## RunnerUnitOfWork(001 の UnitOfWork の拡張。research R5)

```text
class RunnerUnitOfWork(UnitOfWork, Protocol):
    runners: RunnerRepository
    leases: LeaseRepository
    tokens: RunnerTokenRepository
    allowlist: CapabilityAllowlistRepository
```

約束: 001 の UnitOfWork の約束 1〜5 を、追加の 4 つのリポジトリにも適用する(すべて確定するか何も確定しない、`version` の衝突で `ConcurrencyConflict`)。
001 のユースケースは、この UoW の上でもそのまま動く。

## RunnerRepository

```text
def get(runner_id) -> Runner | None              # 削除済みも返す
def add(runner: Runner) -> None                  # 削除されていない同名があれば DuplicateRunnerName(コミット時の検出でもよい)
def save(runner: Runner) -> None
def list_active() -> list[Runner]                # 削除されていないもの、名前の順
```

約束: 保存と復元で全項目(能力の 1 つの値と集合の区別を含む)が同一。同じ名前の同時の `add` は一方だけが確定する(不変条件 4)。

## LeaseRepository

```text
def add(lease: Lease) -> None
def save(lease: Lease) -> None
def find_active_by_runner(runner_id) -> Lease | None     # status = ACTIVE(期限は問わない)
def find_active_by_job(job_id) -> Lease | None
def list_active_expired_before(now) -> list[Lease]       # status = ACTIVE かつ expires_at < now
def list_active() -> list[Lease]
```

約束: 1 件のジョブ・1 台のランナーに `ACTIVE` のリースは高々 1 つ。2 件目の `add` は確定しない(不変条件 1)。

## RunnerTokenRepository

```text
def add(token: RunnerToken) -> None
def save(token: RunnerToken) -> None
def find_by_hash(token_hash) -> RunnerToken | None
def find_valid_by_runner(runner_id) -> RunnerToken | None
```

約束: トークンの値を受け取らない・保存しない(ハッシュだけ)。1 台のランナーに有効なトークンは高々 1 つ(不変条件 3)。

## CapabilityAllowlistRepository

```text
def get() -> CapabilityAllowlist                 # なければ空の許可リスト
def save(allowlist: CapabilityAllowlist) -> None
```

## RunnerCatalog(判定用の読み取り。`RunnerEligibilityService` が使う)

```text
def active_capabilities() -> list[tuple[RunnerId, Capabilities]]   # 削除されていないもの
def capabilities_of(runner_id) -> Capabilities | None              # 削除済み・未知は None
```

約束: 副作用を持たない。最後に確定した登録・削除を反映する。001 の `SubmitJob` の UoW の外から呼ばれてよい(提出と同時の登録・削除との前後は問わない)。

## SecretGenerator(shared に追加。research R9)

```text
class SecretGenerator(Protocol):
    def new_token(self) -> str          # "rt_" + 32 バイトの乱数の URL 安全な文字列
```

既定の実装: 標準ライブラリ `secrets.token_urlsafe(32)`。Fake: 連番から決定的に作る(テストの再現性)。

## Clock / IdGenerator

001 のものを使う。ランナーの状態とリースの判定は、`Clock.now()` だけで行う(FR-018)。

---

## 契約テストの一覧(`job_testing.contracts` に追加)

| テスト群 | 主な検査 |
|---|---|
| `RunnerUnitOfWorkContract` | 追加のリポジトリを含めた原子性、`version` の衝突でのロールバック |
| `RunnerRepositoryContract` | 保存と復元の同一性、同名の同時の追加、削除済みの扱い |
| `LeaseRepositoryContract` | ACTIVE の一意性(ジョブ・ランナー)、期限切れの抽出 |
| `RunnerTokenRepositoryContract` | ハッシュでの検索、有効なトークンの一意性、値を保持しないこと |
| `CapabilityAllowlistRepositoryContract` | 空の既定、保存と復元 |
| `RunnerCatalogContract` | 副作用がないこと、削除済みを含めないこと |
| `RunnerEligibilityContract`(001) | 002 の `RunnerEligibilityService` が 001 の契約テストを通す(`requirement_for` は `{"all": [eq ...]}` を作る) |
