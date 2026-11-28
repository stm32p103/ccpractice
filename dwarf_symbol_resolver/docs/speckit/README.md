# Spec Kit への引き継ぎ資料

DWARF Symbol Resolver (`dwarf_symbol_resolver`) の保守・機能追加を、Spec Kit で進めるための入力資料です。
試作の段階で決まったこと・確かめたことだけを、現在の実装に合わせて整理しています
(途中で取りやめた方式は載せていません)。

## 資料の一覧と、Spec Kit での使い方

| 資料 | 内容 | 渡す先 |
|---|---|---|
| [01-constitution-input.md](01-constitution-input.md) | 守るべき原則 (誤ったアドレスを黙って出さない、正解はコンパイラに出させる など) | `/speckit-constitution` |
| [02-spec-baseline.md](02-spec-baseline.md) | 現在の機能の仕様 (何を・なぜ)。利用者ストーリー、機能要件、受け入れ条件、範囲外 | `/speckit-specify` で新機能を書くときの前提。既存機能の仕様として参照させる |
| [03-architecture.md](03-architecture.md) | 技術的な構成 (モジュール、データモデル、拡張点、制約) | `/speckit-plan` の技術コンテキスト |
| [04-adaptation-guide.md](04-adaptation-guide.md) | 処理系 (DWARF) とコメント形式への適合のしかた (スキルの使い方と規則) | `/speckit-plan`、`/speckit-implement` |
| [05-verification.md](05-verification.md) | 動作確認の方法と、現在の基準となる結果 | `/speckit-tasks` の検証タスク、`/speckit-implement` の完了条件 |
| [06-usage-examples.md](06-usage-examples.md) | 利用者 (ツール開発者) が組み込むときのイメージとサンプル | `/speckit-specify` の利用者像、`/speckit-plan` の API 互換の確認 |
| [07-limitations-and-backlog.md](07-limitations-and-backlog.md) | 既知の制約・未検証事項と、機能追加の候補 | `/speckit-specify` の題材 |
| [08-glossary.md](08-glossary.md) | 用語集 | すべての段階 |

進め方の例:

1. `/speckit-constitution` に 01 を渡して憲法を作る
2. 機能追加のたびに `/speckit-specify` で「02 を既存仕様として前提にし、07 の ○○ を追加する」のように依頼する
3. `/speckit-plan` では 03・04 を技術コンテキストとして読ませる
4. 完了条件には 05 の検証 (処理系の検証とコメント形式の検査がすべて通ること) を必ず入れる

## 今回追加した資料 (提案)

依頼された最低限 (機能本体、適合方法、動作確認、利用イメージ) に加えて、次を追加しました。

- **01 憲法の入力**: 改修を重ねても設計がぶれないよう、試作で前提にしてきた原則を明文化しました。
  Spec Kit は憲法に照らして計画を検査するので、劣化を防ぐ効果が最も大きいと考えます
- **02 の「範囲外」**: やらないと決めたこと (map ファイルの読み込み、マクロ展開、値の上書き など) を
  理由付きで残しました。経緯ではなく「範囲の定義」として書いているので、再導入の議論を防げます
- **07 既知の制約と候補**: 未検証の事項 (Green Hills の実機での確認など) と、追加機能の候補です
- **08 用語集**: 「parsed」「衝突」「格納単位」など、この資料とコードで特別な意味で使う言葉です
- **実行できるサンプル** `src/dwarf_symbol_resolver/examples/export_monitor_csv.py`:
  左辺値の一覧から RAM モニタ用の CSV を作る、組み込みの見本です (06 で説明)
