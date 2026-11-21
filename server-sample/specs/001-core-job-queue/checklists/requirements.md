# Specification Quality Checklist: コア — ジョブの受付・キュー管理

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-20
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- [NEEDS CLARIFICATION] は 2026-11-20 の回答で解消: FR-005 = 数値 1〜5(既定 3、大きいほど優先)、FR-006 = 同じ内容が待機中なら拒否(実行中・終了済みは受付)、FR-007 = 上限なし。
- 2026-11-20 FR-022 を見直し: 全ジョブを全員が閲覧可能にした(ランナーが共用で、利用者同士が相談して順番を調整するため)。権限に「順序調整」(他人の待機中ジョブの優先度変更)を追加し、管理から切り離した。これにより FR-006 の重複拒否の例外は不要になり、削除した。US2・US5・FR-011・FR-023・SC-003・SC-005・エッジケース・前提を合わせて更新。
- 2026-11-20 優先度と権限を再度見直し: 優先度・割り込みの概念を廃止(Q1 の回答は無効)。ジョブは提出・やり直しとも必ず待機列の最後に並ぶ。順番は利用者間で相談し(スコープ外)、順序調整の権限を持つ利用者が、待機中のジョブを先頭・最後・指定ジョブの直前/直後へ移す(FR-004、FR-005、FR-008〜FR-012)。SC を 10 件に再構成。
- 2026-11-20 ジョブの追加を再度見直し: 位置の指定がなければ末尾(ジョブ追加の権限)。指定したジョブの前/後への追加と、指定したジョブの前/後への移動(スケジュール変更)は、スケジュール変更の権限で行う(FR-004、FR-004a、FR-011、FR-012、FR-020、FR-023)。「順序調整」の権限名と、先頭・最後を直接指定する移動は廃止。割り込みは「先頭のジョブの前への追加」として扱う。
- 保持期間(FR-031)は上限 3 件を超えるため、マーカーにせず「clarify で確定、それまでは自動削除しない」と暫定にした。`/speckit-clarify` で確定する。
- 憲章のゲート(spec): 未確定事項の明示(原則 12)、外部への書き出しの列挙と台帳との対応(S2、「外部への書き出し」の節)、「作らないもの」を含まない(原則 4)を確認済み。
- FR-028 の「自動の検査で確認」は、入力の受け入れ基準(語彙・依存の検査)を、実装手段を書かずに表したもの。
