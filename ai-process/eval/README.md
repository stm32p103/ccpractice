# 評価の仕組み（共通部）

題材に依存しない部分です。題材ごとの部分は `eval-cases/<題材>/` に置きます。

## 考え方
- **スキル無し → スキル有り**の順で、同じケースを数回ずつ動かして比べる（結果はぶれるので、1回の合否ではなく合格率で見る）
- 判定は **スクリプト → LLM採点 → 人** の順に安い。スクリプトで決まることはスクリプトで決める
- 人は生の成果物を見ない。**一覧（表）と、機械が挙げた点だけ**を見る（review.md）
- ゲートのある段階では、人が一覧を承認するまで次の段階に進まない
- 採点役と人は、スキル有りか無しかを知らずに採点する（score の時点で、使ったスキルを `runs/_hidden/` に退避する）
- 成果物には、作ったときの体制の版とモデル名を残す

## 1回分の流れ
```bash
cd ai-process
python3 eval/kit.py prepare B1 --suite equipment-loan --variant noskill --trials 3            # Claude Code
python3 eval/kit.py prepare B1 --suite equipment-loan --variant noskill --env copilot --trials 1  # Copilot（手作業）
python3 eval/kit.py next <id>        # 表示されたコマンドで生成役を動かす（新しいセッション）
python3 eval/kit.py review <id>      # ゲートの段階のあと: runs/<id>/review_<段階>.md を人が見る
python3 eval/kit.py approve <id>     # 承認 → next で次の段階
python3 eval/kit.py score <id>       # 判定（score.json）と、人が見る review.md
#   採点役: cd eval/runs/<id> && claude -p "$(cat JUDGE.md)" --allowedTools Read,Grep,Glob > judge.json
#   人    : review.md を見て human.json を付ける（judge.json を見る前に）
python3 eval/kit.py summarize        # eval/results/summary.md
```
- 評価中は、このプラグイン自体を無効にして動かします（有効のままだと、「スキル無し」の実行にも評価対象のスキルが混ざるため）。`next` が表示するコマンドには、そのための設定が入っています。設定の書き方は最新のドキュメントで確認してください。
- Copilot で試す場合は `--env copilot` で準備します。`next` が手順を表示します（workspace だけをフォルダとして開き、新しいチャットでプロンプトを貼る）。集計は環境ごとに分かれます。

## 新しい題材を足すとき
`eval-cases/<題材>/` を作り、次のものを用意します。共通部（このディレクトリ）は変えません。

| 用意するもの | 中身 |
|---|---|
| `cases.yaml` | ケース（基本／あいまい／変更）、段階とゲート、判定コマンド、合格条件。書き方は既存の題材の先頭を参照 |
| `fixtures/` | 入力の題材。正解の判定に使うもの（参照実装など）は、生成役に渡す `inputs` に入れない |
| `checks/` | 判定スクリプト。JSON を標準出力に出す。人が見る表を作るものは `--md` で review.md に追記する |
| `rubrics/` | LLM採点と人の採点の基準。`\| X-name \|` の形で観点を書くと human.json の雛形に反映される |
| `selftest/` | 判定スクリプト自体のテスト（模範解答と弱い解答で、判定が正しく分かれるか） |

最初に、**正解を機械でどこまで判定できるか（オラクルの強さ）**を見極めてください。判定できる範囲が広いほど、人が見る量が減ります。
