# 005(GitHub 連携)・006(WebUI)への引き継ぎ

## 005: ソース取得の実アダプタ

004 が定めたポートに、実アダプタを実装する。いずれも、出力先を書き出し台帳(`inputs/13-security-egress.md`)に追加し、レビューを受けてから有効にする(憲章 S2)。

- **`SourceCredentialIssuer`**(`core-api/src/job_core_api/runner_ports.py`。コア側): 指定の `source`・`revision` に限り、**読み取り専用で短命**(既定 10 分)の取得資格を発行する。呼び出しごとに新しい資格を返す。保存せず、ログ・監査・エラー・イベントに値を含めない。発行できなければ `SourceNotAvailable`。契約テスト: `SourceCredentialIssuerContract`(Fake: `job_testing.api_fakes.source_credentials.FakeSourceCredentialIssuer`)。
  `core-server/src/job_core_server/wiring.py` の `ApiDependencies.assemble(source_credentials=...)` に渡す(現在は未構成 = `422 source_not_available`)。
- **`SourceFetcher`**(`runner-agent/src/job_runner_agent/source.py`。ランナー側): 取得資格を使って、`revision`(コミット識別子)に固定して `dest` へ取得する。**取得のみ**(コミット・プッシュをしない。FR-019)。`.git` などの履歴のメタデータを残さない。許可リストのリポジトリは、エージェントが取得の前に検査済み。契約テスト: `SourceFetcherContract`(`runner-agent/tests/contract/test_source_fetcher_local.py` が参照実装)。
  ランナー側の組み立ては `runner-service/src/job_runner_service/wiring.py::build_fetcher`(`source.fetcher = "remote"` の実装を接続する)。
- 用途固有の語・GitHub の語を、`runner-agent`・`runner-protocol`・コアに入れない(語彙検査が検出する)。

## 006: ログ・成果物の表示

- **ログ**: `GET /v1/jobs/{job_id}/logs?after_seq=&limit=`(権限 `job.read_output`)。`after_seq` で追従する。変更の通知(SSE)は、ジョブの状態の変更を契機にし、**ログの本文を載せない**(ログ専用の通知イベントはない)。`complete = true` で、ジョブが終了し、全チャンクを返した。本文はエージェントでマスク済み(補助的な対策)。
- **成果物**: `GET /v1/jobs/{job_id}/artifacts`(権限 `job.read_output`)。**参照だけ**を返す(`kind = unc` は UNC パス、`kind = url` は HTTPS の URL)。UNC パスは、コピーして開けるように表示する(ブラウザからは直接開けない場合がある)。中身は、保存先から利用者が直接取得する(アクセス権は運用)。
- **権限による表示の切り替え**: `GET /v1/auth/session` の `permissions` に `job.read_output` があるときだけ、ログ・成果物の欄を出す。001 の「すべての利用者が状態・結果の要約・経緯を見られる」は変えない。
- ログ・成果物の閲覧は、監査ログに残る(`log_read`・`artifact_read`。誰が・いつ・どのジョブを。内容は記録しない)。
