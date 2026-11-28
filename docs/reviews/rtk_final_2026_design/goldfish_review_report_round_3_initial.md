# Goldfish Annotated Review Report

**Target:** [RTK final design](../../designs/rtk_final_2026.md) (`1–529`, Stage 7, round 3)

**Status:** Awaiting author resolution. One proposed architecture-text fix; none applied. One repeated editorial Nit retains its previously settled disposition.

## Prioritized Findings & AI Suggestions

### design-3-1 [egm-design] — Severity: Major

* **Affected Scope:** Lines 234–272, especially 253–268, and 339–349 (observation acceptance and T8 target evidence).
* **Discrepancy Description:** The design thoroughly associates observations with a mission, attempt, view and source capture, but does not define how the coordinator establishes that accepted figure evidence and accepted QR information refer to the same physical target. A current, correctly correlated view can contain a toy and an unrelated readable banner. Similarly, after changing viewpoints, fresh evidence can describe different objects while satisfying the same mission context. Separating victim and QR stage flags does not itself prevent their subsequent combination into a successful mission.
* **Rationale:** The coordinator can otherwise truthfully accept two independent observations yet falsely claim that this combined goal was completed. Capture freshness and view identity prevent stale-result errors, but do not establish physical-object identity.
* ***AI Suggestion:*** PROPOSE FIX
* ***Justification:*** The target explicitly calls for multiple-candidate and separated-banner tests but lacks the association invariant and unresolved-association outcome. The parent checked the cited feature paragraphs and later contract/hold-cell/acceptance text. Capture IDs, boxes and corners provide inputs; they do not define the missing pairing decision. Propose a coordinator-owned target record, conservative same-capture visual pairing, revalidation across views and incomplete outcomes on ambiguity, within T8-B. This is a policy proposal rather than proof that available views can establish the association. It adds a coverage/evaluation obligation and may reject otherwise readable QR codes, increasing retry time or incomplete attempts. No new depth localization, tracker or production source file is authorized.
* ***Proposed Edit:*** At current line 343, replace this paragraph once with the expanded text below. Existing figure-evidence requirements remain intact.

Before:

```text
Successful victim recognition requires accepted fresh figure evidence from the selected detector. A banner-only scene must not create that stage. A single confidence value does not prove enough evidence: determine temporal confirmation and negative-scene thresholds from held-out scenes and full runs, then fix them in the verification design. Keep evidence of the actual figure and QR associations distinct when they occupy different image regions.
```

After:

```text
Successful victim recognition requires accepted fresh figure evidence from the selected detector. A banner-only scene must not create that stage. A single confidence value does not prove enough evidence: determine temporal confirmation and negative-scene thresholds from held-out scenes and full runs, then fix them in the verification design. Keep evidence of the actual figure and QR associations distinct when they occupy different image regions.

The coordinator owns a selected-target record for the active attempt, distinct from mission, view and request identity. Bind accepted figure evidence, the target's QR information and its hold-cell evidence to that same record using their original observation/capture references, surveyed target region and verified robot pose. Separate stage evidence remains necessary, but stages from different target records cannot be combined into full success. A common view, a nearby QR or matching task context alone does not establish physical-target identity.

For QR-stage credit, obtain figure and QR observations from the same identified captured image and require a unique figure/banner pairing under the surveyed viewing geometry and representative prop relationship. Check the figure box, QR corners, permitted target region and pose uncertainty against that verified relationship. Selecting the nearest pair or accepting the only decoded code is not sufficient when another pairing remains plausible. If the image/pose evidence permits more than one association, reject target-specific QR credit with an unresolved-target-association reason; try another surveyed view within T4-A's budget or retain an incomplete outcome. If allowed field arrangements are visually indistinguishable under a view's evidence, that view cannot certify the association.

After a viewpoint change, reacquire fresh figure/banner evidence and establish a unique correspondence to the selected target through the surveyed region, verified pose and observed appearance before using the new view's QR or hold evidence. If multiple candidates remain indistinguishable, do not assume continuity. An explicit target change creates a new record without inheriting the old target's QR or hold credit; saved evidence remains in the run history. Validate an unrelated readable banner beside a toy, multiple figures/banners, ambiguous same-region pairings and a view change exposing a different candidate. Missing verified association coverage is a failed readiness prerequisite. This policy uses T8-B image/pose/catalogue evidence, not an implicit target-depth fallback or general tracking framework. Align its record, acceptance rules and tests in the detailed plan before implementation readiness.
```

### style-3-1 [egm-style] — Severity: Nit

* **Affected Scope:** Lines 361 and 370 (repeated City source limitation).
* **Discrepancy Description:** Both paragraphs explain that the City guide provides contextual behavior and that its linked official PDF could not be retrieved during drafting.
* **Rationale:** Repeating this source limitation adds no decision. The meaningful prerequisite is to obtain applicable scoring rules before selecting the autonomous action set.
* ***AI Suggestion:*** DECLINE
* ***Justification:*** This repeats settled style-2-3 at the same City paragraph. Keep its no-fix disposition rather than reopen it. The underlying critique is retained; no severity change or contest is asserted.
* ***Proposed Edit:*** None. The raw reviewer suggestion remains in [the style report](critic_style_round_3.md).

## Round and approval boundary

The [round report](critic_round_3_report.md) links every complete reviewer result and execution status. [Exact replacement data](critic_round_3_proposed_edits.json) is tied to the reviewed hash. The target remains unchanged. A new, unsettled Major finding makes round 3 not clean; consecutive clean rounds reset from 1 to 0. No churn or failed previous fix was established: the target-association omission is outside the text repaired in round 1, and reverting those repairs would not resolve it.

S5-01, S5-02 and C-01 remain open. Detailed implementation alignment of both the already approved mission-owner policy and this proposed target-association policy is required before readiness acceptance. Approval here concerns the feature document only. No production code, dataset, runtime or physical trial is changed.
