# 契約: ポート(core-api が外に求めるもの)

**対象**: `job_core_api.access.ports`、`job_core_api.events.ports`、`job_core_api.settings`(`SecretSource`)、`job_core.job.application.ports`(`JobRepository.search` の追加)
**実装**: Fake(`job_testing.api_fakes`)、実アダプタ(`job_core_persistence`、`job_core_server`、005 の認証アダプタ)
**検証**: `job_testing.contracts` の契約テストを、Fake と実アダプタの**両方**で実行する(憲章 原則 11)

シグネチャは Python の `typing.Protocol`。ここでは振る舞いの約束を記す。001・002 のポート(`UnitOfWork` など)は変えない。

---

## IdentityProvider(認証基盤。FR-005、FR-008)

```text
class IdentityProvider(Protocol):
    def begin_login(self, return_to: str) -> LoginRedirect | None
    def complete_login(self, params: Mapping[str, str]) -> VerifiedIdentity
```

約束:

- `begin_login`: 利用者を認証基盤へ送る遷移先(`LoginRedirect(url)`)を返す。遷移の要らない方式(直接の証明だけ)は `None`。`return_to` は呼び出し側が検証済みの同一オリジンの相対パスで、実装は認証基盤との往復のあいだ**不透明な値として保持**する(解釈しない)。
- `complete_login`: 認証基盤から戻ったときのパラメーター、または直接の証明(`POST /v1/auth/login` の `proof`)から、本人性と所属グループを返す。
  - 確認できなければ `IdentityRejected`。認証基盤が使えなければ `IdentityProviderUnavailable`(API は `503 identity_provider_unavailable`)。
  - 返す `VerifiedIdentity` の `subject_id` は空でなく、同じ本人には常に同じ値(安定した識別子)。`groups` は文字列の集合で、解釈しない。
  - **例外のメッセージ・戻り値に、認証基盤が返した生の応答、トークン、パスワードを含めない**(API は例外の文字列を応答・ログに出さないが、実装も含めない)。
- 実装は、API の語彙に認証基盤の名称・概念を持ち込まない。実装の中(アダプタ)に閉じる。**外部へ通信するアダプタは、出力先を書き出し台帳に追加し、レビューを受ける**(R12。005)。
- 偽の実装 `FakeIdentityProvider`: 試験が与える対応表(`proof` の `subject` と `groups`、または事前登録した利用者)から返す。通信しない。**本番の設定で Fake を選ぶと、`core-server` は起動を拒否する**(T-A9)。

契約テスト `IdentityProviderContract`: 確認できる証明で同じ本人が同じ `subject_id` になる、確認できない証明で `IdentityRejected`、利用できない状態で `IdentityProviderUnavailable`、例外の文字列に証明の値が含まれない。

---

## ServiceCredentialRepository(FR-005、FR-010)

```text
class ServiceCredentialRepository(Protocol):
    def add(self, credential: ServiceCredential) -> None
    def get(self, credential_id: str) -> ServiceCredential | None
    def find_by_hash(self, token_hash: TokenHash) -> ServiceCredential | None
    def save(self, credential: ServiceCredential) -> None
    def list(self) -> list[ServiceCredential]
```

約束:

- `add`: 同名の**有効な**認証情報があれば `DuplicateCredentialName`。`token_hash` の重複は拒否する(乱数の衝突は事実上起きないが、契約として検査する)。
- `find_by_hash`: 失効済みも返す(呼び出し側が `revoked_at` を見て認証失敗にする)。未知は `None`。照合は**ハッシュの完全一致**で、定数時間の比較は呼び出し側が行う。
- `save`: `version` が一致しなければ `ConcurrencyConflict`。失効(`revoked_at` の設定)は一方向で、失効済みの記録を有効に戻す保存は拒否する。
- 値(トークン)そのものは、ポートに渡らない。`ServiceCredential` の `repr` にハッシュを含めない。
- 永続化は、各呼び出しが独立した短い UoW で行う(認証情報の発行は監査ログの記録と同じ UoW。R10)。

契約テスト `ServiceCredentialContract`: 追加・取得、同名の拒否(失効後は同名を許す)、ハッシュでの検索、失効の一方向、`version` の衝突、`repr` にハッシュが現れない。

## SessionRepository(FR-005、FR-012)

```text
class SessionRepository(Protocol):
    def add(self, session: Session) -> None
    def find_by_hash(self, token_hash: TokenHash) -> Session | None
    def touch(self, session_id: str, at: datetime) -> None
    def revoke(self, session_id: str, at: datetime) -> None
    def revoke_all_of(self, subject_id: SubjectId, at: datetime) -> int
    def delete_inactive_before(self, cutoff: datetime) -> int
```

約束:

- `find_by_hash`: 失効・期限切れも返す(判定は呼び出し側。`Session` の有効の判定は純粋な関数 `is_active(now, idle_timeout)`)。
- `touch`: `last_used_at` を `at` に更新する(巻き戻さない)。呼び出しごとの更新が負荷になる場合の間引き(1 分に 1 回まで)は、実装の自由とする(無操作の期限の精度が、その分だけ粗くなることを許容する)。
- `revoke` は冪等(失効済みなら何もしない)。`revoke_all_of` は、失効させた件数を返す。
- `delete_inactive_before`: 失効または期限切れから `cutoff` より前の記録を削除する。有効なセッションは削除しない。

契約テスト `SessionContract`: 追加・検索、失効の冪等、一括の失効の件数、削除が有効なセッションに及ばない、`touch` が巻き戻らない。

## AccessConfigSource(FR-007)

```text
class AccessConfigSource(Protocol):
    def load(self) -> AccessConfig        # 検証済み。不正なら AccessConfigInvalid(violations)
```

約束:

- 読み込みは**検証してから**値を返す(data-model.md §2 の検証)。不正なら `AccessConfigInvalid(violations)`(違反の場所と理由の一覧。ファイルの内容の抜粋を含めない)。
- 呼び出しごとに、ファイルを読み直す(キャッシュしない)。差し替えのタイミングは、呼び出し側(起動時と `POST /v1/access/reload`)が決める。
- `AccessConfig.digest` は、内容の正規化(キーの並び替え、権限の並び替え)に対する SHA-256 で、同じ内容なら同じ値になる。

契約テスト `AccessConfigContract`: 正常な設定、未定義のロールの参照、ロールに載せられない権限、上限の外の権限、`digest` の安定性(並び順に依らない)。

## ChangeBroker(FR-017、FR-018)

```text
class ChangeBroker(Protocol):
    @property
    def epoch(self) -> str
    def publish(self, change: PendingChange) -> None
    def subscribe(self, last_event_id: str | None, topics: frozenset[str]) -> Subscription
```

約束:

- `publish`: 通知に `seq`(世代内で単調増加)と日時を付けて、リングバッファと購読者の列に載せる。**呼び出しをブロックしない**(購読者が遅くても、状態を変えるユースケースの応答を遅らせない)。購読者の送信待ちが上限を超えたら、その購読者を切断対象にする。
- `subscribe`: `last_event_id` が現在の世代でバッファの範囲内なら、続きから。範囲外・世代違い・`None` でない不正な値なら、最初に `resync` を返す。`None` なら、`hello` の後の新しい通知から。
- `PendingChange` は、`type`・`subject`・`state`・`change` だけを持つ(型で固定。自由な文字列の項目を持たない。T-A8)。
- 発行は**状態を変えるユースケースの成功後**だけ。失敗・拒否は発行しない。発行に失敗しても、ユースケースの結果(コアの状態)は変わらない(通知は再取得で補える)。

契約テスト `ChangeBrokerContract`: `seq` の単調増加、バッファ内からの再送、範囲外の `resync`、世代違いの `resync`、遅い購読者の切断と他の購読者への非影響、`PendingChange` に自由な文字列の項目がないこと(型の検査)。

## SecretSource(秘密情報の取得)

```text
class SecretSource(Protocol):
    def get(self, name: str) -> str
```

約束: 秘密の値を、設定ファイルの平文ではなく、実行環境の保管機能から取得する。`name` が未知なら `SecretNotFound`(値・探した場所の詳細を例外に含めない)。値を、ログ・例外・応答に出さない。
実装: 環境変数(**開発・試験専用**。`core-server` は、本番の設定でこの実装を選ぶと警告する)。本番の実装は、009 のスパイク(資格情報の保管機能)の結果に従う。

---

## JobRepository.search(001 への追加。R8)

```text
def search(self, criteria: JobSearchCriteria, cursor: str | None, limit: int) -> Page[Job]
```

`JobSearchCriteria`: `states`(任意の集合)、`owner`(任意)、`submitted_from` / `submitted_to`(任意。`submitted_from <= submitted_at < submitted_to`)。
約束:

- 並びは `(submitted_at 降順, job_id 降順)`。`cursor` は、直前のページの最後の `(submitted_at, job_id)` を表す不透明な値で、続きはそれより**後ろ**(より古い)の行。
- 取得の途中で、状態の変化・削除があっても、続きのページに**重複も欠落も起きない**(キーが不変)。途中で新しく提出されたジョブは、続きには現れない。
- `limit` は 1 以上。不正な `cursor` は `ValidationFailed("cursor", ...)`。
- 条件はすべて AND。結果は payload を含まない形で使われる(`SearchJobs` が `JobSummaryView` に変換する)。

契約テスト `JobSearchContract`(Fake と実アダプタで共通): 各条件の絞り込み、組み合わせ、頁の継ぎ目の重複・欠落なし(途中の削除・状態の変更を含む)、同時刻の複数ジョブの順序、不正な `cursor`。

---

## 契約テストの一覧(本 feature の追加分)

| テスト群 | 対象 | Fake | 実アダプタ |
|---|---|---|---|
| `IdentityProviderContract` | `IdentityProvider` | `FakeIdentityProvider` | 005 の実アダプタ(005 で追加) |
| `ServiceCredentialContract` | `ServiceCredentialRepository` | メモリ | SQLAlchemy(PostgreSQL) |
| `SessionContract` | `SessionRepository` | メモリ | SQLAlchemy(PostgreSQL) |
| `AccessConfigContract` | `AccessConfigSource` | メモリ | TOML ファイル |
| `ChangeBrokerContract` | `ChangeBroker` | (実装は 1 つ) | プロセス内の実装 |
| `JobSearchContract` | `JobRepository.search` | メモリ | SQLAlchemy(PostgreSQL) |
| 001・002 の既存の契約 | `UnitOfWork`、各リポジトリ | メモリ | **SQLAlchemy(PostgreSQL)を追加** |
