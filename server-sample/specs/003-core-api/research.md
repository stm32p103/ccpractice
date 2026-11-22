# 調査と判断: コア API — コアを HTTP API として公開する

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-11-21

spec の `[NEEDS CLARIFICATION]` は 0 件(Clarifications 2026-11-21 で解決済み)。本書は、plan の段階で決めた技術上の判断を記す。
001・002 の判断([../001-core-job-queue/research.md](../001-core-job-queue/research.md)、[../002-runner-management/research.md](../002-runner-management/research.md))は、ことわりがない限りそのまま引き継ぐ。
ライブラリの版は、実装時に `uv.lock` で固定する(取得は公式の索引だけ。台帳 E15)。

---

## R1. パッケージの配置(憲章 原則 1、3)

- **Decision**: inputs/12-plan のリポジトリ構成に従い、次の 3 つのパッケージを `uv` のワークスペースに加える。
  - `core-api/`(`job_core_api`): HTTP の形、認証・認可、エラー、イベント配信、定期処理。`job_core` だけに依存する。
  - `core-persistence/`(`job_core_persistence`): SQLAlchemy による永続化アダプタ(001・002 のポートと、本 feature のポートの実装)。`job_core` と `job_core_api` のポートの定義に依存する。
  - `core-server/`(`job_core_server`): 起動の入口(設定の読み込み、ポート実装の選択と組み立て、ASGI サーバーの起動)。上の 2 つを import してよい唯一の場所。
- **Rationale**: 憲章 原則 1 は「拡張点はポート + 起動時の設定による実装の差し替え」だけを認める。`core-api` が `core-persistence` を import すると、
  永続化の差し替え(試験用の Fake を含む)が設定ではなく import の変更になる。組み立て専用の小さなパッケージを置けば、依存の向きを import-linter で守れる。
- **Alternatives considered**: (a) 02-modules どおり core-api に永続化を含める — 12-plan が `core-persistence/` を別に挙げており、001・002 の plan も「core-persistence で実装」と書いたため採らない。
  (b) 組み立てを `core-api` の中で文字列から import(`importlib`)する — 動的な読み込み機構を作らない規律(原則 1)に反する。
- **依存規則(import-linter に追加)**: `job_core_api` は `job_core_persistence`・`job_core_server`・`job_testing` を import しない。`job_core_persistence` は `job_core_server` を import しない。
  `job_core` は 3 つとも import しない(既存の契約を拡張)。

## R2. Web フレームワークと OpenAPI の作り方(FR-001〜003、憲章 原則 1)

- **Decision**: FastAPI + Pydantic v2(FastAPI に含まれる)+ uvicorn(Windows で動く ASGI サーバー)。エンドポイントは**同期関数(`def`)**で書く(R13)。
  OpenAPI は**コード側から生成**し、生成物を `core-api/openapi/openapi-v1.json` としてリポジトリに置く(スナップショット)。CI のテストが、生成物とスナップショットの一致を検査する。
  スナップショットを意図せず変えると失敗するので、契約の変更は必ずレビューの対象になる。
- **Rationale**: 12-plan の技術スタックに従う。コードから生成すれば、実装と定義の食い違いは構造的に小さい。スナップショットの比較で、破壊的変更の見落としを防ぐ(FR-003、SC-008)。
- **Alternatives considered**: 契約を先に YAML で書き、コードを合わせる(contract-first)— 二重管理になり、手書きの定義が実装から離れやすい。設計時の契約は [contracts/http-api.md](contracts/http-api.md) に表で示し、公式の OpenAPI は実装から生成する。
- **語彙**: OpenAPI の文書(パス、説明、スキーマ名)に、GitHub などのプラットフォームの語、用途固有の語を含めない。テストで文書全体の文字列を検査する(R15)。

## R3. バージョニングと互換性(FR-002、FR-019。Clarifications Q3)

- **Decision**: URL の先頭にメジャー版を付ける(`/v1/...`)。OpenAPI の `info.version` は `1.<マイナー>.<パッチ>` とし、メジャー版は URL と一致させる。
  - **互換を保つ変更(同じ `/v1` のまま)**: エンドポイントの追加、応答への項目の追加、任意の要求項目の追加、列挙値の追加(クライアントは未知の項目・値を無視する規約。契約に明記)。
  - **破壊的な変更(`/v2` を新設)**: 項目・エンドポイントの削除や改名、必須の要求項目の追加、項目の型・意味の変更、エラーの `code` の意味の変更、認可の強化(従来許された呼び出しが拒否される)。
  - **互換期間**: `/v2` の公開後、`/v1` を**最低 3 か月**並行して提供する(運用の合意で延長できる)。終了の予告は、`/v1` の応答ヘッダ(`Deprecation`、`Sunset`)と、リリースの記録で行う。
- **Rationale**: 生成クライアントと URL が 1 対 1 に対応し、WebUI・提出ゲートウェイ・ランナーを段階的に移行できる。イントラネット内の少数のクライアントなので、3 か月で足りる。
- **Alternatives considered**: ヘッダでの版指定 — URL を安定させられるが、ログ・動作確認(ブラウザ、`curl`)で版が見えず、キャッシュ・ルーティングの扱いが増える。
- **検査**: スナップショットの差分を、直前の公開版と比べる破壊的変更の検査(削除・必須化・型変更を検出する小さな検査)を CI に置く。検査の道具は tasks で決める(外部のコマンドが使えない場合は、OpenAPI を JSON として比較する自前の検査でよい)。

## R4. 主体と認証情報(FR-005、FR-009〜011、FR-026)

- **Decision**: 認証情報は、`Authorization: Bearer <値>` で受け取る。人間の利用者のセッションは、同じ値を Cookie `__Host-session` でも受け取る(R5)。
  値の先頭で種類を判別する。

  | 先頭 | 主体 | 照合 | 失効 |
  |---|---|---|---|
  | `ss_` | 人間の利用者(セッション) | セッションの記録(R5) | ログアウト、期限切れ、管理者による一括の失効 |
  | `st_` | サービス | サービス用の認証情報の記録(SHA-256 のハッシュ) | `DELETE /v1/service-credentials/{id}`(即時) |
  | `rt_` | ランナー | 002 の `AuthenticateRunner`(そのまま呼ぶ) | 002 の失効(即時) |

  - 値は 32 バイトの乱数(`secrets.token_urlsafe(32)`)に先頭を付けたもの。保存するのは SHA-256 のハッシュだけで、比較は `hmac.compare_digest`。値は発行時の 1 度だけ返す(FR-026。002 R9 と同じ)。
  - 照合は**呼び出しごと**に行う(記録を引く)。キャッシュしないので、失効は次の呼び出しから効く(SC-004)。性能は SC-010 の範囲で足りる(R19)。
  - 未知・失効・期限切れ・形式の誤りは区別せず、同じ `authentication_failed`(401)を返す(認証情報の存在の推測を防ぐ)。
  - 主体の種類(`PrincipalKind`)は、監査の表示にだけ使い、可否の判定には使わない(憲章 原則 9、001 R8)。
- **サービス主体の権限**: サービス用の認証情報は、発行時に**権限の一覧**を持つ。一覧に載せられる権限は、設定の「サービスに付与できる権限の上限」(既定: `job.submit`、`job.general`、`job.submit_on_behalf`、`queue.schedule`)の部分集合に限る。
  上限にない権限(`runner.manage`、`access.manage` など)は発行できない。サービスの漏えいの影響を、ジョブの提出・参照・順序の操作の範囲に閉じ込める(S3)。
- **ランナー主体**: `AuthenticateRunner` の戻り値(`runner.report`、`job.execute` の 2 権限に固定)をそのまま使う(002 R9)。
- **Alternatives considered**: JWT(自己完結の署名つきトークン)— 失効が即時にならず(失効リストが要る)、署名鍵の管理が増える。不透明なトークン + サーバー側の記録の方が、失効の即時性(SC-004)と単純さで勝る。

## R5. 人間の利用者: 認証基盤のポートとセッション(FR-005、FR-008、FR-012。Clarifications Q1)

- **Decision**: 認証基盤を `IdentityProvider` ポートで表す([contracts/ports.md](contracts/ports.md))。
  - `begin_login(return_to) -> LoginRedirect | None`: 利用者を認証基盤へ送る遷移先を返す(遷移の要らない方式は `None`)。
  - `complete_login(params) -> VerifiedIdentity`: 認証基盤から戻ったときのパラメーター(または直接の証明)から、本人性(`subject_id`、表示名)と所属グループの一覧を返す。確認できなければ `IdentityRejected`、認証基盤が使えなければ `IdentityProviderUnavailable` を送出する。
  - API は、認証基盤の名称・概念を持たない。パラメーターは「文字列の対応表」として不透明に扱い、5 つの操作(下記)だけが API の契約になる。
- **ログインの流れ**:
  1. `GET /v1/auth/login?return_to=/path` → `begin_login` の結果へ 302(遷移の要らない方式では 404)。`return_to` は同一オリジンの相対パスだけを許す(オープンリダイレクトの防止)。
  2. `GET /v1/auth/callback?...` → すべてのクエリを `complete_login` に渡す → セッションを作り、Cookie を設定して `return_to` へ 302。
  3. `POST /v1/auth/login`(本文 `{"proof": {...}}`)→ `complete_login(proof)` → セッションを作る。Fake の認証基盤と、非ブラウザのクライアント(試験、スクリプト)が使う。`delivery=cookie|token`(既定 `cookie`)で、値の返し方を選ぶ。
  4. `GET /v1/auth/session` → 呼び出した主体の種類・識別子・権限・期限を返す(画面の表示の分岐用)。
  5. `DELETE /v1/auth/session` → ログアウト(セッションを失効)。
- **セッション**: サーバー側に不透明な値(`ss_...`)のハッシュ、`subject_id`、**ログイン時の所属グループ**、作成・最終利用・期限を保存する。権限は保存せず、**呼び出しごとに、現在の対応表(R6)で所属グループから導く**。
  対応表の変更は、再ログインなしで次の呼び出しから効く(spec の Edge Cases)。所属グループの変更は、次のログインから効く(認証基盤に毎回は問い合わせない。既定の期限の範囲で遅れうることを運用文書に明記する)。
- **有効期限(既定。設定で変更できる)**: 絶対期限 12 時間、無操作 2 時間(呼び出しのたびに延長。SSE の接続だけでは延長しない)。サービスとランナーのトークンに期限はない(失効するまで有効。FR-012)。
- **Cookie**: `__Host-session`、`HttpOnly`、`SameSite=Strict`、`Path=/`、`Secure`(HTTP のイントラネット構成では設定で外せる。外すと `__Host-` の接頭辞は使えないため、名前を `session` に切り替える)。
  Cookie で認証された、状態を変える呼び出し(POST/PUT/PATCH/DELETE)は、`Origin` ヘッダが許可リスト(設定。既定は同一オリジン)に一致しなければ拒否する(CSRF の防止。`Authorization` ヘッダの呼び出しには適用しない)。
- **Alternatives considered**: 認証基盤の固有の流れ(OAuth など)を API の契約に含める — FR-008 に反する。ステートレスなセッション(署名つき Cookie)— 即時の失効と一括の失効ができない。

## R6. 認可: コアに任せる範囲と、API が担う範囲(FR-006、FR-007。憲章 原則 9)

- **Decision**:
  - ジョブ・ランナー・監査ログの操作の可否は、**コアのユースケースが `Principal.permissions` で判定し、拒否を監査ログに記録する**(001、002)。API は主体を作って渡すだけで、権限の判定を重複して持たない。
    API が権限の不足を `403` に写すのは、コアが送出する `PermissionDenied` を写すときだけ。
  - API 自身の操作(サービス用の認証情報、アクセスの設定、イベントの購読)は、API の層で権限を判定し、拒否を監査ログに記録する(コアと同じ `permission_denied`)。
  - 新しい権限を 1 つ加える: `access.manage`(サービス用の認証情報の発行・失効・一覧、アクセス設定の再読み込み・参照)。001 の「管理」(`audit.read_all`)とは分ける(最小権限。S3)。spec の Assumptions の「管理の権限」は、これを指す。
- **対応表(設定ファイル。FR-007)**: TOML。形式は [contracts/access-config.schema.json](contracts/access-config.schema.json)。

  ```toml
  [roles.viewer]    permissions = ["job.general"]
  [roles.member]    permissions = ["job.general", "job.submit"]
  [roles.operator]  permissions = ["job.general", "job.submit", "queue.schedule", "job.cancel_queued", "job.force_abort"]
  [roles.admin]     permissions = ["job.general", "job.submit", "queue.schedule", "job.cancel_queued", "job.force_abort",
                                   "audit.read_all", "runner.manage", "access.manage"]
  [groups]          "<所属グループの識別子>" = ["member"]        # 認証基盤が返す文字列。コアは意味を解釈しない
  default_roles = ["viewer"]                                      # どの対応にも当たらない利用者
  [service]         permission_ceiling = ["job.submit", "job.general", "job.submit_on_behalf", "queue.schedule"]
  ```

  利用者の権限 = 所属グループに対応するロールの権限の**和集合**(対応がなければ `default_roles`)。既定の設定ファイルは、上の例のとおり汎用のロール名を使う(用途固有の語を含めない)。
- **読み込みと変更の監査(FR-007)**: 起動時と `POST /v1/access/reload`(`access.manage`)で、ファイルを読み、**検証してから**差し替える(検証に失敗したら、現在の対応表を保ち、`400` の理由を返す)。
  差し替えのたびに、`ACCESS_CONFIG_CHANGE` を監査ログに記録する(操作者、変更前後の対応表の**ハッシュ**と、ロール・グループの**追加・削除・変更の差分**。権限の一覧は記録してよい。秘密情報は含まない)。
  ファイルの内容そのものの変更の統制(誰がファイルを書けるか)は、ファイルの ACL(009)に委ねる。再読み込みは、自動の監視ではなく明示の操作とする(意図しない変更の即時反映を避ける)。
- **ロールの権限に `job.execute`・`runner.report`・`retention.purge`・`runner.sweep` を載せられるか**: 載せられない。検証で拒否する(ランナーの主体と定期処理の主体に固定の権限を、人間のロールに紛れ込ませない)。
- **Alternatives considered**: 権限の判定を API の依存関係(`require_permission`)に統一する — コアが既に判定・監査しており、二重化で食い違いが生まれる。コアに任せる方が、001・002 の受け入れテストと同じ根拠を使える。

## R7. エラーの形式(FR-013、FR-014)

- **Decision**: RFC 9457(Problem Details)の `application/problem+json`。コアの例外の `code` を、そのまま `code` として返す。
  形式は [contracts/problem.schema.json](contracts/problem.schema.json)、状態コードの対応は [contracts/http-api.md](contracts/http-api.md) §3。
  - 共通の項目: `type`(`urn:job-api:error:<code>`)、`title`(固定の短い文)、`status`、`code`、`detail`(原因の説明。秘密を含まない)、`request_id`。
  - 追加の項目(コアの例外が持つもの): `required_permissions`、`existing_job_id`、`anchor_job_id`、`field`、`from_state`、`operation` など。**呼び出した主体に開示してよいものだけ**を、型で固定して写す(例外の `str()` を使わない)。
  - 要求の形式の誤り(型・必須項目)は `400`、`code = request_invalid`、`errors`(項目の場所と理由の一覧)。値の内容は含めない(payload・認証情報の漏えいの防止)。
- **開示の制御(FR-014)**: エラーの応答を作る関数は、コアの例外の種類ごとの**写像の表**だけを通す。未知の例外は `500`、`code = internal_error`、詳細なし(内容は `request_id` つきでサーバーのログにだけ残す。ログにも秘密を出さない)。
  `permission_denied` は、必要な権限を返すが、**他人のジョブの存在・内容は示さない**(001 は全員が全ジョブを閲覧できるため、存在の秘匿は不要。ただし payload は一覧に含めない)。
- **Alternatives considered**: 独自の形式 — 標準があり、生成クライアント・利用者に馴染みがある形式を使う方がよい。

## R8. 一覧・ページ分割・キュー(FR-015、FR-016)

- **Decision**:
  - `GET /v1/jobs`: **履歴の検索**。絞り込み: `state`(複数可)、`submitter`(名義上の提出者)、`submitted_from` / `submitted_to`(提出日時の範囲。半開区間)。並びは `submitted_at` の新しい順(同時刻は `job_id` の降順)。
    ページ分割は**キーセット方式**(不透明な `cursor`、`limit` 既定 50・最大 200)。キーは変わらない値(提出日時、識別子)なので、ページの継ぎ目で、状態の変化・削除があっても**重複と欠落は起きない**。
    取得の途中で新しく提出されたジョブは、先頭側に入るため、続きのページには現れない(契約に明記)。
  - `GET /v1/queue`: **待機列そのもの**。待機中の全件を待機列の順序で返す(`position` つき)。ページ分割しない(待機中は数百件まで。001 の想定)。権限は `job.general`(全員が閲覧できる。001 FR-022)。
  - 001 の `ListJobs`(待機中の全件 + 実行中 + 終了済みの頁送り)は、検索の絞り込みに足りない。**コアに `SearchJobs` の問い合わせと、`JobRepository.search` のポートを加える**(001 への小さな追加。plan「001・002 への変更」)。
- **Rationale**: 「並びが変わる集合」(待機列)と「履歴の検索」を分けると、前者は常に全件・順序つき、後者は安定した頁送りになり、それぞれの契約が単純になる。
- **Alternatives considered**: 1 つの一覧で、待機列の順序と履歴の頁送りを両立する — 並びが操作で変わるため、継ぎ目の重複・欠落を避けられない。

## R9. イベントの配信: SSE(FR-017、FR-018。Clarifications Q2)

- **Decision**: `GET /v1/events`(`text/event-stream`)。権限は `job.general`。
  - **発行元**: API の層が、状態を変えるユースケースの**成功後**に、変更の通知を作ってプロセス内の `ChangeBroker` に載せる(コアの変更はしない)。
    定期処理(ランナーの offline 化、リースの期限切れ)の結果も、同じ経路で載せる。コアのアウトボックス(ジョブ完了イベント。007 が使う)とは別の仕組みとする(用途が違う: 画面の更新 vs 取りこぼせない外部への通知)。
  - **内容**([contracts/change-event.schema.json](contracts/change-event.schema.json)): `seq`(単調増加の番号)、`type`(`job.changed`、`runner.changed`、`queue.changed`、`resync`、`auth.expired`)、`occurred_at`、`subject`(種類と識別子)、`state`、`change`(固定の語彙: `submitted`、`rescheduled`、`assigned`、`completed`、`cancel_requested`、`cancelled`、`retried`、`online`、`offline`、`maintenance_changed`、`fault_changed`、…)。
    **自由な文字列は含めない**(payload、ログ、理由、異常の説明、能力の値を含めない。FR-018、001 FR-030、T-R6)。短い説明が要る画面は、識別子で詳細を引く。
  - **取りこぼしの補い**: 直近 1000 件を、プロセス内のリングバッファに持つ。クライアントは再接続時に `Last-Event-ID` を送る。範囲内なら、続きを送る。範囲外(古すぎる、またはサーバーの再起動で番号が戻った)なら、`resync` を送り、クライアントは一覧を再取得する。`seq` はサーバーの起動ごとに新しい世代の識別子とともに発行し、世代が違えば `resync` とする。
  - **接続の維持と認証**: 15 秒ごとに `: keepalive` を送る。そのたびに、認証情報(失効・期限)と `job.general` を再確認し、失われていれば `auth.expired` を送って閉じる。接続の上限は 200(超えたら `503`)。遅いクライアントは、送信待ちが 100 件を超えたら切る(再接続で補う)。
  - **ブラウザ**: `EventSource` は Cookie で認証できる(R5)。非ブラウザは `Authorization` ヘッダ。
- **制約**: ブローカーはプロセス内にあるため、API サーバーの**プロセスは 1 つ**(`uvicorn` のワーカー数 1)とする。008(耐障害性)の Active/Standby と矛盾しない。複数プロセスに増やす場合は、ブローカーの差し替え(DB の通知など)を 008 で扱う。
- **Alternatives considered**: ポーリング — 実装は単純だが、即時性(SC-007: 3 秒)とサーバーの負荷の両立が難しい。WebSocket — 双方向は不要で、プロキシ・認証の扱いが増える。

## R10. 監査(FR-020、FR-021。憲章 原則 6)

- **Decision**:
  - ジョブ・ランナーの状態を変える呼び出しは、コアのユースケースが記録する(001・002)。API は**呼び出した主体**(種類・識別子)を `Principal` で渡す。代理の場合の名義上の提出者は、コアが `on_behalf_of` として記録する(001 FR-024)。
  - API の層の操作を、同じ監査ログ(コアの `AuditLog`)に記録する。コアの `AuditOperation` に次を加える(002 が `RUNNER_*` を加えたのと同じ方式)。

    | 操作 | 記録する場面 | 結果 |
    |---|---|---|
    | `LOGIN` | セッションの作成(ログイン) | 成功。拒否(本人性を確認できない)は `AUTH_FAILED` |
    | `LOGOUT` | セッションの失効(本人、または管理者) | 成功 |
    | `AUTH_FAILED` | サービス・セッションの認証の失敗、ログインの失敗(ランナーの失敗は 002 の `RUNNER_AUTHENTICATE`) | 拒否(`authentication_failed`)。認証情報の値・ハッシュは記録しない |
    | `SERVICE_CREDENTIAL_ISSUE` / `SERVICE_CREDENTIAL_REVOKE` | サービス用の認証情報の発行・失効 | 成功(権限の一覧を `after` に記録。値は記録しない) |
    | `ACCESS_CONFIG_CHANGE` | 対応表の読み込みによる変更(R6) | 成功。検証の失敗は、記録しない(現在の対応表は変わらない)が、API の応答で理由を返す |

    `PrincipalKind` に `ANONYMOUS` を加える(認証に失敗した呼び出しの `actor_kind`。`actor` は `unauthenticated`)。
  - **認証失敗の洪水の抑制**(002 T-R7 と同じ考え方): 同じ接続元・同じ種類の失敗は、**1 分の窓で最初の 1 件を記録**し、窓の中の残りは数えて、窓が閉じたときに件数つきの 1 件(`after.suppressed`)を追記する。
    監査ログは追記専用で変更しないため、「後から更新」はしない。接続元の識別は、接続のアドレスだけを使う(`X-Forwarded-For` などの申告値は信用しない。R11)。
  - 照会(状態を変えない呼び出し)は記録しない。ただし、権限による拒否は記録する(001 の `READ_AUDIT_LOG` と同じ)。
  - 要求の追跡のため、`X-Request-Id`(受け取った値、なければ生成)を応答と、サーバーのログに付ける。監査ログの項目は増やさない(001 FR-025 の項目で足りる)。
- **ログ(アクセスログ)**: メソッド、パス(識別子を含む)、状態コード、所要時間、`request_id`、主体の種類・識別子だけを出す。`Authorization`、Cookie、クエリ文字列、本文は出さない(S4。テストで検査する)。

## R11. ネットワーク境界(FR-022。憲章 原則 8)

- **Decision**: 多層で守る。
  1. **待ち受けのアドレス**: 設定で指定したインターフェースだけに bind する(既定は `127.0.0.1`。運用ではイントラネット側のアドレスを指定)。
  2. **接続元の許可リスト**: 設定の `allowed_networks`(CIDR の一覧。既定はループバックと私的アドレスの範囲)に含まれない接続元からの要求は、認証より前に `403`(`code = network_not_allowed`、本文に詳細なし)で拒否する。接続のアドレスだけを見る。`X-Forwarded-For` などは信用しない(リバースプロキシを置く構成は、このとき allowed_networks にプロキシのアドレスを入れる運用とし、本 feature では対象外)。
  3. **ファイアウォール**: Windows ファイアウォールの受信規則(009 で構築)。
  - ランナーへの着信接続は使わない。割り当ては、ランナーからの要求への応答として返す(002 FR-031、台帳 E16)。
  - 応答ヘッダ: `Cache-Control: no-store`(認証・セッションに関する応答)、`X-Content-Type-Options: nosniff`。CORS は許可しない(WebUI は同一オリジンで配信する。006)。
- **Rationale**: 設定の誤り(0.0.0.0 に bind したまま)でも、アプリの層で外部の到達を拒否できる。2 の許可リストが「最後の砦」になる。

## R12. 外部への書き出し(FR-023〜025、憲章 S2・S3)

- **Decision**: 本 feature は、**外部への送信を一切行わない**。API が外部へ書き出すのは、台帳に載った次だけ。

  | 台帳 | 本 feature での扱い |
  |---|---|
  | E4(ランナー → コア API) | 受け取るだけ。受け取る項目は 002 の契約と同じ(能力、生存通知、異常の状態・短い説明、割り当ての要求・終了の報告)。ログ・成果物は 004 |
  | E16(コア API → ランナー) | ランナーの要求への応答だけ。割り当てたジョブの識別子とジョブ定義、リースの期限、生存通知の間隔、ランナーの状態 |
  | E9・E10 | 本 feature は送らない(005・007 が、イベントと API の契約だけを使って送る)。ジョブ完了イベントのスキーマは 001 が固定済み |
  | E11 | テレメトリ・外部資産なし。API は静的資産を配信しない(WebUI の配信は 006) |

  - **認証基盤のポートの実装(アダプタ)**は、外部へ通信する可能性がある(005 の GitHub など)。**そのアダプタの出力先は、005 で台帳に追加し、レビューを受ける**。本 feature の既定の実装(Fake)は通信しない。
  - **検査**: (1) 禁止 API の検査 — `job_core_api`・`job_core_persistence` に、HTTP クライアント(`httpx`、`requests`、`urllib.request`、`http.client`、`aiohttp`)、`socket` の直接の利用がないこと(`job_core_persistence` のデータベースの接続は、ドライバ経由に限る)。
    (2) 送信を記録する偽のサーバーを用意し、一連の操作(ログインを含む)のあいだ、外向きの通信が 0 件であることを確認する(SC-009)。
- **本 feature での台帳の追加**: 1 件(開発環境の構築のみ。R17)。

## R13. 永続化(core-persistence)

- **Decision**: SQLAlchemy 2.0(**同期**)+ psycopg 3 + PostgreSQL。マイグレーションは Alembic。
  - **同期にする理由**: コアのユースケースは同期の関数で、Unit of Work は「同期のコンテキストマネージャー」として契約されている(001)。FastAPI の `def` エンドポイントは、スレッドプールで実行される。非同期にすると、コアの契約を変える必要がある。
  - **並行性**: コアの契約に従い、`version` 列による楽観的排他(衝突は `ConcurrencyConflict`、ユースケースが再試行)。待機列の取り出しの原子性は、1 回の UoW での `version` の比較で守る(12-plan の `SELECT ... FOR UPDATE SKIP LOCKED` は、複数プロセスで同時に割り当てる場合の最適化として残し、本 feature では使わない。プロセスが 1 つで足りる: R9)。
  - **永続化するもの**: ジョブ、待機列、監査ログ、アウトボックス(001)、ランナー、リース、トークン、許可リスト(002)、サービス用の認証情報、セッション(本 feature)。表の設計は [data-model.md](data-model.md) §5。
  - **契約テスト**: 001・002 のポートの契約テスト(`job_testing.contracts`)を、**Fake と SQLAlchemy 実装の両方**で通す(憲章 原則 11)。本 feature のポート(R14 の表)の契約テストも同様。
  - **PostgreSQL の用意(開発・CI)**: コンテナ・仮想化が使えないため(憲章 原則 7)、**公式の Windows 用バイナリの zip を、版・ハッシュを固定して取得し、ユーザー領域の一時的なインスタンス**として起動する。`ops/dev/setup-dev.ps1` を拡張する(R17)。
- **Alternatives considered**: SQLite でアダプタを試験する — 排他・型の挙動が異なり、契約テストの意味が薄れる。非同期の SQLAlchemy — 上記のとおり、コアの契約を変える。

## R14. ポートの一覧(本 feature が加えるもの)

| ポート | 責務 | 実装(本 feature) |
|---|---|---|
| `IdentityProvider` | 本人性と所属グループの確認(R5) | `FakeIdentityProvider`(`testing`)。実アダプタは 005 |
| `ServiceCredentialRepository` | サービス用の認証情報の保存・照合・失効 | メモリ(Fake)、SQLAlchemy |
| `SessionRepository` | セッションの保存・照合・失効・期限切れの削除 | メモリ(Fake)、SQLAlchemy |
| `AccessConfigSource` | 対応表の読み込み(R6) | TOML ファイル、メモリ(Fake) |
| `ChangeBroker` | 変更の通知の発行・購読・再送(R9) | プロセス内の実装(本番も試験も同じ。Fake は不要) |
| `SecretSource` | データベースの接続の秘密などの取得 | 環境変数(開発専用)。本番(資格情報の保管機能)は 009 のスパイクの結果に従う |

契約は [contracts/ports.md](contracts/ports.md)。001・002 のポート(`UnitOfWork` など)は変えない(追加は R8 の `JobRepository.search` だけ)。

## R15. テストの方針(憲章 原則 11)

- **契約テスト(OpenAPI)**: (1) 生成した OpenAPI がスナップショットと一致する。(2) 直前の公開版との破壊的変更の検査(R3)。(3) `schemathesis`(OpenAPI から要求を自動生成して実行し、応答が定義に適合することを検査する道具)で、Fake を配線したアプリに対し、各エンドポイントの応答が定義と一致することを確認する(FR-003、SC-008)。
- **生成クライアントだけの受け入れ試験(SC-001)**: OpenAPI から Python のクライアントを生成し(`openapi-python-client`)、**そのクライアントだけ**で、提出 → 参照 → スケジュール変更 → 取り消し → 強制中断 → やり直し → ランナーの管理 → 監査ログの参照を行う。WebUI・GitHub 連携のコードは使わない。
- **認証・認可**: 3 種類の主体 × 権限の部分集合(13 権限)× 操作の網羅(コアの権限の表の検査を、API の層でも通す)。偽の認証基盤による、複数の所属グループの利用者のログインと、対応表の変更(SC-002)。失効の即時性(SC-004)。
- **イベント**: 購読 → 状態の変更 → 受信までの時間(SC-007)、再接続での補い、`resync`、権限の喪失・失効での切断。通知にログ・payload・自由な文字列が含まれないこと(スキーマの検査 + 変更の発生元ごとの検査)。
- **アーキテクチャ**: import-linter の契約の追加(R1)、語彙の検査(`core-api` のソースと OpenAPI の文書に、プラットフォーム・用途固有の語がない)、禁止 API の検査(R12)。
- **偽の認証基盤の契約テスト**: `IdentityProvider` の契約テストを、Fake で通す(005 の実アダプタも、同じテストを通すこと)。
- **性能の目安**(`-m perf`): 50 人の同時の利用者で、提出・一覧・詳細が 2 秒以内(SC-010)。

## R16. ランナー向けのエンドポイント(最小。004 との境界)

- **Decision**: ランナーが、002 のユースケースを使うための**最小のエンドポイント**を、本 feature で提供する(失効したランナーでジョブを取得できないことの検証 = SC-004 に必要)。
  `POST /v1/runner/registration`(登録)、`POST /v1/runner/heartbeat`、`POST /v1/runner/fault`、`DELETE /v1/runner/fault`(回復)、`POST /v1/runner/job-requests`(割り当ての要求)、`POST /v1/runner/jobs/{job_id}/result`(終了の報告)、`POST /v1/runner/jobs/{job_id}/stopped`(停止の確認)。
  - **ランナーの識別子は URL に含めない**。認証した主体(`rt_` のトークン)の識別子だけを使う。これにより「自身に関する対象に限る」(FR-011)が構造的に守られる(`RunnerMismatch` は API からは起きない)。
  - 本 feature は、002 のユースケースの入出力を、そのまま HTTP の形にするだけにする。ログ・成果物の送信、長時間の待ち受け(long polling)、再送の約束、ジョブの状態遷移の詳細は **004 が定める**(004 は、このエンドポイントを拡張する。スキーマの共有は `runner-protocol/` で行う。12-plan)。
  - 割り当ての応答に含まれるジョブ定義(payload を含む)は、ランナー用の応答だけに載せる(台帳 E16)。一覧・イベント・エラーには載せない。
- **Alternatives considered**: 004 まで、ランナー向けのエンドポイントを持たない — SC-004 と受け入れ基準「失効したランナーの認証情報では、ジョブを取得できない」を、003 の範囲で検証できなくなる。

## R17. 環境構築の支援(憲章 原則 14)・台帳の追加

- **Decision**: 本 feature の完了の定義(試行に必要な構築・マイグレーションをスクリプトで再現できること)のため、次を行う。
  - **開発環境(`ops/dev`、001・002 の枠組みを拡張)**: (a) ワークスペースに 3 パッケージを加えた `uv sync`、(b) PostgreSQL(公式の Windows 用バイナリの zip)の取得・ハッシュ検証・一時インスタンスの起動と撤去、(c) `-VerifyOnly` に V19〜V28 を追加([quickstart.md](quickstart.md))。
  - **サーバー(`ops/server`、`ops/db`)**: 009 の基盤(`setup-server.ps1`、`migrate.ps1`、`common/`)が**先に**できていることを、本 feature の試行の前提とする(12-plan の「最初の試行(001 + 003)の前に基盤を完成」)。本 feature は、そこに次の項目を加える: コア API のサービス登録(WinSW)、設定ファイルの雛形(`server.toml`、`access.toml`)、Alembic のマイグレーション(`migrate.ps1` から呼ぶ)、スモークテスト(ログイン → 提出 → 参照)。
  - **台帳の追加(要レビュー)**: 開発環境の構築スクリプトの取得先(台帳 E15)に、PostgreSQL の公式の配布元のドメインを加える。実在する取得先と、ハッシュの値は、実装時に公式の公開値で確認して設定ファイルに固定する(ハッシュの不一致なら停止)。**台帳の更新とレビューを経ずに、取得を実装しない**(S2)。
- **009 が未了の場合**: 本 feature の自動テスト(Fake + 一時の PostgreSQL)は、009 に依存せず実行できる。009 の基盤は、サーバーでの試行にだけ必要。

## R18. 脅威の洗い出し(憲章 S6。`docs/security/threat-model.md` の「3B」に追記する)

実装の着手前に、次を `docs/security/threat-model.md` に追記する(tasks の最初のタスク)。

| # | 脅威 | 対策 | 検査 |
|---|---|---|---|
| T-A1 | **認証情報の漏えい**(ログ・監査・エラー・応答・DB に値が残る) | ハッシュだけを保存、値は発行時の 1 度だけ、アクセスログに `Authorization`・Cookie・クエリを出さない、`repr` の秘匿(R4、R10) | 値・ハッシュが応答・監査・例外・ログに現れないこと(property-based) |
| T-A2 | **失効の遅れ**(失効した認証情報が使い続けられる) | 呼び出しごとの照合、キャッシュなし、SSE は 15 秒ごとに再確認(R4、R9) | 失効の直後の呼び出しが 100% 失敗(SC-004) |
| T-A3 | **権限の昇格**: サービスの認証情報に過大な権限を付ける、人間のロールに実行用の権限を載せる、一般の利用者が代理提出する | サービス用の権限の上限、ロールに載せられない権限の検証(R4、R6)、代理提出は `job.submit_on_behalf` のみ(コアが判定) | 権限の網羅、設定の検証のテスト、SC-003 |
| T-A4 | **ランナーによる越権**(他のランナーの操作、利用者向けの操作) | ランナー識別子を URL に含めず、主体から取る(R16)、権限は 2 つに固定(002 T-R3) | SC-004、他のランナー・利用者向けの操作の拒否 |
| T-A5 | **CSRF / オープンリダイレクト / セッションの固定** | `SameSite=Strict`、`Origin` の検査、`return_to` は相対パスのみ、ログインのたびに新しいセッションの値を発行(R5) | 各項目のテスト |
| T-A6 | **イントラネット外からの到達** | bind、`allowed_networks`、ファイアウォール(R11) | 許可外のアドレスからの要求が拒否されること |
| T-A7 | **認証失敗の洪水**(総当たり、監査ログの水増し) | 値が 256 ビットの乱数で総当たりが成立しない(R4)、失敗の記録の窓による抑制(R10) | 洪水のテスト(記録が窓ごとに 2 件以内) |
| T-A8 | **エラー・イベント経由の情報の持ち出し・漏えい**(payload、ログ、異常の説明、他人の情報) | 写像の表だけを通す、イベントに自由な文字列を含めない、スキーマで項目を固定(R7、R9) | 契約テスト、各ユースケースの出力に対する検査(T-5 の API 版) |
| T-A9 | **偽の認証基盤の混入**(試験用の実装が本番で有効になる) | 本番の設定では、Fake の選択を拒否する(`core-server` の起動時の検査)。Fake は `testing` に置き、本番のパッケージに含めない | 起動時の検査のテスト |
| T-A10 | **対応表の改ざん・誤設定** | 変更は明示の再読み込みだけ、検証してから差し替え、差分を監査、ファイルの ACL(009)(R6) | 検証の失敗で現在の対応表が保たれること |
| T-A11 | **SSE の資源の枯渇**(接続の大量の保持) | 接続の上限、送信待ちの上限、認証の再確認(R9) | 上限のテスト |
| T-A12 | **外部への書き出しの混入**(テレメトリ、認証基盤アダプタの無断の送信) | 禁止 API の検査、偽のサーバーでの検証、アダプタの出力先は台帳に追加(R12) | SC-009 |

残るリスク: (1) 所属グループの変更が、次のログインまで反映されない(R5。期限の範囲の遅れ)。(2) 接続元の許可リストは、接続のアドレスだけを見る。プロキシ構成では、プロキシのアドレスを許可する運用になり、実質の接続元の絞り込みが弱まる。(3) API サーバーのプロセスが 1 つであることに依存する(R9)。

## R19. 上限と性能の目安

| 項目 | 既定(設定で変更できる) | 根拠 |
|---|---|---|
| 要求本文の最大 | 1 MiB | payload の上限(001)に対して十分。超えたら `413` |
| 一覧の `limit` | 既定 50、最大 200 | R8 |
| SSE の接続数 | 200 | 利用者 50 人 × 複数のタブ。超えたら `503` |
| SSE の再送の範囲 | 直近 1000 件 | 数分〜数十分の切断を補う |
| セッション | 絶対 12 時間、無操作 2 時間 | R5 |
| 認証失敗の記録の窓 | 1 分 | R10 |
| ランナーの定期処理 | 30 秒ごと(`SweepRunners`)。保持期間の削除は 1 日 1 回(`PurgeExpired`) | 002 R8、001 FR-031 |

性能の目安: 単件の操作・一覧は 2 秒以内(SC-010)。認証の照合(記録の参照)と権限の導出は、1 呼び出しあたり数ミリ秒の範囲に収める(測定は perf テストで行う)。

## R20. 定期処理(`SweepRunners`、`PurgeExpired`)

- **Decision**: API のプロセスの中で、起動時に作る背景のスレッドが、**固定の主体**(`kind = SYSTEM`、権限は `runner.sweep` と `retention.purge` だけ)で、002 の `SweepRunners` と 001 の `PurgeExpired` を呼ぶ。HTTP からは呼べない。結果は、R9 の経路で通知にも載せる。
  プロセスが 1 つであることを前提とする(R9)。Standby 側は、起動しない設定にする(008 で扱う)。
- **Rationale**: 外部のスケジューラー(Windows のタスクスケジューラー)に依存せず、サービスの起動だけで動く。権限を持つ「HTTP から呼べる主体」を増やさない。

## 未解決の項目

なし。spec の 3 件は Clarifications で確定済み。既定値(R5、R19)は、運用で変えられる設定値として扱う。
