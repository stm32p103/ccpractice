# 契約: ポート(runner-agent が外に求めるもの)

**対象**: `job_runner_agent` のポート(`executor`、`source`、`artifacts`、`launcher`、`secrets`、`core_client`)、`job_core_api` の `SourceCredentialIssuer`、`job_core` の `JobLogStore`
**実装**: Fake(`job_testing.runner_fakes`、`core_fakes`、`api_fakes`)、実アダプタ(`runner-agent`・`profile-equipment-check`・`core-persistence`・005)
**検証**: `job_testing.contracts` の契約テストを、Fake と実アダプタの**両方**で実行する(憲章 原則 11)

シグネチャは Python の `typing.Protocol`。ここでは振る舞いの約束を記す。

---

## Executor(エグゼキュータ。FR-003、FR-011、FR-012、FR-022)

```text
class Executor(Protocol):
    def prepare(self, ctx: ExecutionContext) -> ExecutionPlan
    def interpret(self, ctx: ExecutionContext, outcome: ProcessOutcome) -> Verdict
```

約束:

- `prepare`: ジョブの payload(`ctx.payload`)を解釈して、**実行計画を返すだけ**。プロセスを起動しない、ネットワークを使わない、`ctx.work` の外のファイルを読まない。解釈できない payload は `ExecutorRejected(reason_code)`(固定の語彙)を送出する(エージェントが `input_rejected` で報告する)。
- 計画の `tool_id` は、設定でそのジョブ種別に許可された識別子だけ。`args` のパスは `WorkPath`(検査済み)だけで作る。
- `interpret`: ツールの終了後に、`ProcessOutcome` と、作業フォルダ内のファイル(`ctx.work` 経由)から、`Verdict` を返す。`summary` は 200 文字まで(マスクはエージェントが行う)。ログ本文を `summary` に写さない。
- エグゼキュータは、`ctx` 以外(資格・環境・コアのクライアント)に触れない。状態を持たない(ジョブごとに新しいインスタンス、または状態を持たない)。
- 例外(上記以外)は、エージェントが `executor_error` として報告し、例外の文字列は記録しない(監査には型名だけ)。

契約テスト `ExecutorContract`(用途ごとのエグゼキュータが、同じテストを通る):
- 同じ入力で同じ計画(決定的)。
- 計画の `args`・`cwd`・`artifact_patterns` が、パスの検査を通る(ただし、悪意のある payload のときは、`ExecutorRejected` か、検査で拒否される)。
- 任意の payload(Hypothesis)で、例外の型が `ExecutorRejected` に限られ、プロセス・ネットワーク・作業フォルダ外のファイルに触れない(`ctx.work` の記録で検査)。
- `interpret` が、終了コード 0・非 0・`None` のそれぞれで、`Verdict` を返す。

## SourceFetcher(ソース取得。FR-026)

```text
class SourceFetcher(Protocol):
    async def fetch(self, source: str, revision: str, credential: SourceCredential | None, dest: WorkPath) -> None
```

約束: `revision`(コミット識別子)に**固定**して `dest` へ取得する。`source` が許可リストにないものは呼ばれない(エージェントが先に拒否)。失敗は `SourceUnavailable`(例外の文字列に資格を含めない)。`dest` の外へ書かない。履歴のメタデータ(`.git` など)を残さない。
契約テスト `SourceFetcherContract`: 固定したリビジョンの内容が `dest` に入る、存在しないリビジョンで `SourceUnavailable`、`dest` の外へ書かない、例外の文字列に資格が含まれない。実アダプタ: `LocalDirectorySourceFetcher`(dev のみ)、GitHub(005)。

## ArtifactStore(成果物の保存先。FR-025、E6)

```text
class ArtifactStore(Protocol):
    async def put(self, job_id: str, name: str, source: Path) -> ArtifactReference
    async def purge_older_than(self, cutoff: datetime) -> int
    async def free_quota(self) -> int
```

約束:
- `put`: `source`(作業フォルダ内の通常のファイル。エージェントがリパースポイントでないことを確認済み)を、保存先の `<job_id>\<name>` へ書き、`size_bytes` と `sha256` を計算した `ArtifactReference` を返す。`reference` は、`unc` なら UNC パス、`url` なら HTTPS の URL。**作業フォルダ・状態フォルダのパスを含めない**。同じ `(job_id, name)` の再実行は、上書きせず `ArtifactExists`(ジョブごとに新しいフォルダ)。
- 失敗(容量・権限・通信)は `ArtifactStoreError`(エージェントが `artifact_store_failed`)。中途半端なファイルを残さない(一時名で書いてから確定)。
- `purge_older_than`: 保持期間を過ぎたジョブのフォルダを削除し、件数を返す(エージェントの起動時と 1 日ごと)。
- 書き込み先は、設定した「実行結果」フォルダ(または保存先の URL)の 1 か所だけ。アクセス権は作成・変更しない(範囲外)。
- `disabled` の設定では、`ArtifactStore` の実装は組み立てられず、成果物のパターンがあれば `artifact_store_failed` ではなく、**パターンを無視して**警告を監査に記録する(収集しない)。
契約テスト `ArtifactStoreContract`: 書いた内容と `sha256` の一致、参照の形(UNC / URL のスキーマ)、再実行の拒否、中途半端なファイルが残らない、保持期間での削除。

## ProcessLauncher(プロセスの起動と停止。FR-006、FR-015)

```text
class ProcessLauncher(Protocol):
    async def launch(self, spec: LaunchSpec) -> RunningProcess
class RunningProcess(Protocol):
    stdout: AsyncIterator[bytes]; stderr: AsyncIterator[bytes]
    async def wait(self) -> int | None
    async def terminate_tree(self, wait: float) -> bool
```

`LaunchSpec`: `exe`(`tool_id` から解決した絶対パス)、`args`(解決済みの引数の列)、`cwd`、`env`(**完全な環境ブロック**)、`memory_limit`。
約束:
- シェルを介さず、`args` をそのまま渡す。`env` 以外の変数が子に入らない。
- 起動したプロセスと、その子孫のすべてが、`terminate_tree` で終了する。呼び出し元のプロセスが終了しても、子孫が残らない。
- 標準入力は閉じる(空)。標準出力・標準エラーは別々に読み取れる。
契約テスト `ProcessLauncherContract`(Windows 上。`-m windows`): 環境変数が継承されない(親に置いたダミーが子に見えない)、子・孫が `terminate_tree` で残らない(離脱した孫を含む)、親の終了で子孫が終了する、引数の特殊文字(空白・引用符・`&`・`%`)がそのまま渡る。`LogonLauncher` は、ツールのアカウントとして動くこと、作業フォルダ外の読み取りが拒否されること(`-m twoaccount`)も検査する。

## SecretSource(秘密の読み取り。003 と同じ考え方)

```text
class SecretSource(Protocol):
    def get(self, name: str) -> SecretValue
```

約束: 値は `SecretValue`(`repr` に値を出さない)で返す。ログ・例外に値を含めない。実装: 資格情報の保管機能(`prod`)、環境変数(`dev` のみ。警告)。
契約テスト: 未知の名前で `SecretNotFound`、`repr`・例外の文字列に値が含まれない。

## CoreClient(ランナープロトコルのクライアント)

[runner-protocol.md](runner-protocol.md) のエンドポイントを、型付きの呼び出しにしたもの。再試行・バックオフ・確定の拒否の判定(`CoreRejected(status, code)`)を持つ。
約束: 秘密(トークン、取得資格)を、例外・ログ・`repr` に出さない。送る本文は、[runner-protocol.schema.json](runner-protocol.schema.json) に適合する(送信前に検査)。
契約テスト `CoreClientContract`: `FakeRunnerCore` と、コア API(`build_api()`)に対して、同じ呼び出しの列が同じ結果になる。到達しない・`5xx` で再試行、`4xx` の確定の拒否で再試行しない。

---

## core 側のポート(004 が加える)

### JobLogStore(ログの保存。core)

```text
class JobLogStore(Protocol):
    def append(self, job_id: JobId, chunk: LogChunk) -> AppendResult
    def read(self, job_id: JobId, after_seq: int, limit: int) -> list[StoredLogChunk]
    def size(self, job_id: JobId) -> int
    def purge(self, job_id: JobId) -> int
```

約束: `(job_id, seq)` が一意。同じ内容の再送は冪等(`AppendResult.duplicate = True`)、異なる内容は `LogSeqConflict`。総量が上限を超える追加は `LogQuotaExceeded`(保存しない)。`read` は `seq` の順。`purge` はジョブの削除(001 FR-031)と同じ UoW で呼ばれる。
契約テスト `JobLogStoreContract`: 冪等・衝突・上限・順序・削除、Fake と SQLAlchemy(PostgreSQL)の両方。

### SourceCredentialIssuer(取得資格の発行元。core-api)

```text
class SourceCredentialIssuer(Protocol):
    def issue(self, job_id: JobId, source: str, revision: str) -> SourceCredential
```

約束: 資格は、指定の `source`・`revision` に限り、読み取り専用、短命(既定 10 分)。保存・ログ・監査・イベントに値を含めない。発行元がない構成は `SourceNotAvailable`(API は `422 source_not_available`)。実アダプタは 005 が実装し、出力先を台帳に追加する。Fake(`FakeSourceCredentialIssuer`)は、固定の値を返す。
契約テスト `SourceCredentialIssuerContract`: 有効期限、同じ呼び出しで資格が変わる(使い回さない)、例外の文字列に値が含まれない。

---

## 契約テストの一覧(`job_testing.contracts` に追加)

| 契約 | 対象 | Fake | 実アダプタ |
|---|---|---|---|
| `ExecutorContract` | `Executor` | `FakeExecutor`(スリープ、子の起動、秘密の読み取りなど) | `equipment-check` のエグゼキュータ |
| `SourceFetcherContract` | `SourceFetcher` | `FakeSourceFetcher` | `LocalDirectorySourceFetcher`(005 の実アダプタ) |
| `ArtifactStoreContract` | `ArtifactStore` | `FakeArtifactStore`(メモリ) | `SharedFolderArtifactStore`(`https_storage` は決定後) |
| `ProcessLauncherContract` | `ProcessLauncher` | `FakeProcessLauncher`(メモリ上のプロセス) | `DirectLauncher`、`LogonLauncher`(`-m windows`、`-m twoaccount`) |
| `SecretSourceContract` | `SecretSource` | `FakeSecretSource` | 資格情報の保管機能、環境変数(dev) |
| `CoreClientContract` | `CoreClient` | `FakeRunnerCore` | コア API(`build_api()`) |
| `JobLogStoreContract` | `JobLogStore` | メモリ | SQLAlchemy(PostgreSQL) |
| `SourceCredentialIssuerContract` | `SourceCredentialIssuer` | `FakeSourceCredentialIssuer` | 005 |
