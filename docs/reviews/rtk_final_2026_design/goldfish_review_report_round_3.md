# Goldfish Annotated Review Report

Status: resolved

**Target:** [RTK final design](../../designs/rtk_final_2026.md), Stage 7, round 3. Original reviewed scope: 1–529. The author's clarification is recorded in the revised target.

## Prioritized Findings & AI Suggestions

### design-3-1 [egm-design] — Severity: Major

* **Affected Scope:** Original lines 234–272 and 339–349, observation acceptance and target association.
* **Discrepancy Description:** The design did not specify how figure evidence and QR information were associated with the same physical target where several figures or banners might be present.
* **Rationale:** Same-view/capture context alone does not establish physical-object identity under such a scene.
* ***AI Suggestion:*** ESCALATE
* ***Justification:*** The decisive evidence was outside every file the original reviewer could read. In the interactive breakdown, the author clarified that there is exactly one QR and one victim figure and that they are next to each other. The previous proposed multi-target policy addresses a scene outside that confirmed field scope. This is not a contest using facts retrospectively claimed to have been available, and the original Major severity is preserved.
* ***Author Decision:*** The author rejected the multi-target premise and supplied the missing single-pair field constraint. Record this as the resolution of the escalation; no separate multi-target association policy is accepted.
* ***Applied Edit:*** Add the confirmed single-pair scope to The Problem, clarify that independently validated figure/QR evidence concerns that pair and may come from different verified views, and replace unsupported multiple-target field cases with single-pair visibility/readability cases. Keep banner-only/empty-field component-negative tests, stale-frame rejection and independent stage credit.

### style-3-1 [egm-style] — Severity: Nit

* **Affected Scope:** Original lines 361 and 370, repeated City source limitation.
* **Discrepancy Description:** The City source limitation is repeated.
* **Rationale:** Repetition adds no decision.
* ***AI Suggestion:*** DECLINE
* ***Justification:*** Duplicate of settled style-2-3; retain the existing no-fix disposition without reopening it.
* ***Proposed Edit:*** None.

## Post-resolution synchronization

The originally proposed selected-target record, same-frame pairing, cross-view identity policy and associated readiness gate were not applied. Their [initial proposal](goldfish_review_report_round_3_initial.md) is retained for history, and [replacement data](critic_round_3_proposed_edits.json) is marked withdrawn. The [applied clarification diff](critic_round_3_author_clarification.diff) records only the new factual scope and its direct consequences.

The author's response during the breakdown supplies the targeted correction; no additional approval for that factual correction is inferred from silence. This is not a verified official regulation. It is the team's stated field configuration. The detailed implementation text remains unchanged; no production code was written or tested.

The finding is settled under the confirmed one-pair scope. It must not be reopened solely for hypothetical additional figures or QR banners within that same scope. The raw round 3 review was not clean when issued, and its clean-round streak remains 0; resolution does not retrospectively relabel it clean. S5-01, S5-02 and C-01 remain open, as does detailed alignment of the earlier approved mission-owner policy. No target-association implementation alignment is required because that policy was withdrawn. Another review round has not started.
