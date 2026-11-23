# Stage 7 — Critic Review, round 3

Date: 2026-11-16. All reviewers completed. One Major finding was escalated and settled by the author's single-pair field clarification. Round 3 is not clean; consecutive clean rounds reset from 1 to 0. The loop has not converged and Stage 8 has not started.

Target: [RTK final design](../../designs/rtk_final_2026.md), feature scope 1–529, before `## Detailed Implementation Plan` at line 530. Reviewed SHA-256: `c6de09ea7dd6ba2f0ce4dc217c9ff2720326716d7a36c48e8ba5e150b9cb007a`. [Reviewed snapshot](critic_round_3_target_snapshot.md). The target remains unchanged.

## Reviewer execution

| Reviewer | Status | Assigned standard | Raw findings | Complete result |
| --- | --- | --- | --- | --- |
| egm-design | completed | Feature Specification Standard | One Major | [Design Critic](critic_design_round_3.md) |
| egm-structural | completed | Feature Specification Standard | None | [Structure](critic_structural_round_3.md) |
| egm-style | completed | Persona only | One Nit, duplicate of a settled finding | [Style](critic_style_round_3.md) |

Three new reviewers were dispatched directly using `fork_turns: "none"`, without parent history or earlier final-design review reports. Each received the same five local context files and read its persona, active target scope, required context and assigned standard where applicable. All reported complete required reads with truncation repaired and no inaccessible file. No retry or not-run reviewer is recorded. Fresh conversation isolation does not establish host/project instruction-file exclusion.

## Flat findings and resolution

| Raw ID | Severity | Affected scope | Issue | Disposition |
| --- | --- | --- | --- | --- |
| design-3-1 | Major | 234–272, 339–349 | Valid same-view/capture observations need not describe the same physical victim/banner | PROPOSE FIX; coordinator-owned selected-target record, conservative pairing and explicit ambiguity outcome |
| style-3-1 | Nit | 361,370 | City source limitation repeated | Duplicate of settled style-2-3; retain DECLINE without reopening |

[Annotated report and exact proposed text](goldfish_review_report_round_3.md) preserve the discrepancy, rationale, resolver decision and precise replacement. [Replacement data](critic_round_3_proposed_edits.json) is bound to the reviewed hash. No proposed fix was applied.

The target already asks for separated-banner and multiple-object tests, but a test list does not define the missing acceptance invariant. The proposal binds figure, QR and hold-cell evidence to one selected-target record, requires supported pairing and revalidation across viewpoints, and preserves an incomplete outcome when correspondence is unresolved. It uses the selected T8-B image/pose/catalogue approach. It may require more views or reject readable codes where association cannot be established; qualifying this behavior is an added field-evidence obligation, not a claimed result.

The parent checked the target's feature acceptance/target evidence paragraphs and later message and hold-cell/acceptance descriptions. The finding is not a re-raised failed fix: the physical-target association text was not changed by round 1, and reverting the owner-loss or style fixes would not resolve it. No churn was established. No severity was changed.

## Convergence and remaining work

Clean status was decided from the reviewer reports before any repair. Round 1: not clean; round 2: clean; round 3: not clean. Consecutive clean rounds: 0. The ordinary five-round cap and requirement for two consecutive clean rounds remain in force. No new review round starts before the post-resolution author checkpoint.

S5-01, S5-02 and C-01 remain open. The detailed implementation must also be aligned with the approved owner-loss policy and, if approved, the target-association policy before readiness acceptance. No platform, sensor, model, schedule or competition result was physically verified in this review.

The review was local and read-only. No external URL, hardware command, build, runtime test or production edit was used. Only reports and review bookkeeping were written. Stage 7 remains active.

## Author clarification and resolution

During the interactive breakdown the author confirmed exactly one adjacent victim/QR pair. That fact was not available to the original reviewer. The resolver classified design-3-1 as ESCALATE and recorded the author's correction, rather than applying the multi-target policy. The target now explicitly scopes the scene to one pair and revises the unsupported multiple-target field cases. The initial proposal is withdrawn; freshness, independent stage evidence and negative component tests remain. See [resolved annotation](goldfish_review_report_round_3.md) and [clarification diff](critic_round_3_author_clarification.diff). The earlier proposal narrative above is historical, not an active requirement. The raw round was not clean; clean streak remains 0. No fourth round has started.
