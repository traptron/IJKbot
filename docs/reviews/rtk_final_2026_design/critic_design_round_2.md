# Design Critic report — round 2

**Target:** `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`  
**Mode:** REVIEW  
**Active scope:** Lines 1–529, before `## Detailed Implementation Plan`  
**Standard:** Feature Specification Standard

## Findings

**No findings.** No Blocker, Major or Nit discrepancy remains in the active feature-specification scope.

The specification explains the problem, goals, non-goals, component responsibilities and integration paths. It evaluates viable alternatives with concrete engineering trade-offs. It identifies the principal failure modes and gives explicit mitigation or prerequisite gates. Author approval is consistently distinguished from demonstrated feasibility.

This conclusion concerns specification quality. It does not establish implementation readiness, platform compatibility, physical safety or competition performance.

## Architectural assessment

The following significant risks are addressed rather than silently assumed solved:

- **Nano compatibility and workload:** Lines 110–114 require inspection and demonstrated device/ROS operation before migration. Lines 413 and 419 require explicit platform or schedule reconsideration when evidence fails. The document does not claim that availability or author preference proves Nano capacity.
- **Unprotected or orphaned motion:** Lines 207–232 assign one final protected actuator path, preserve timeout braking, require acquisition-age checks and add an onboard mission-owner lease independent of sensor traffic, Nav2 commands and web heartbeats. Expiry latches inhibition; reconnect cannot automatically resume the old attempt. Coordinator-only failure and cancellation failure are explicit test cases.
- **Low obstacles, bridge interpretation and unknown space:** Lines 154–205 distinguish observed support, obstacles and unknown regions. They prohibit treating missing returns as free space, require preservation of 4 cm objects and make inadequate coverage inhibit affected motion. Mechanical traversability and inclination requirements remain separate from surface-fitting success.
- **Stale or misattributed perception:** Lines 234–270 require acquisition provenance, current request/view identity, bounded payloads, duplicate rejection and one mission acceptance owner. Legacy text cannot gain authority through invented context. Later lines 603–628 supply the selected capture-envelope mechanism and further provenance safeguards.
- **Unsafe viewpoint generation and unsupported hold credit:** Lines 324–349 restrict motion to surveyed poses and explicitly reject inferring range from a detection box. Ambiguous nearest-cell evidence requires another verified view or an unresolved outcome. Later line 765 supplies a conservative hold-cell resolution rule.
- **False mission success:** Lines 268–296 separate victim, QR, hold, safe return and terminal outcome. Failed search or exhausted retries cannot manufacture full success. Retry limits and conservative return allowance are required measured profile values.
- **Detector generalization and resource contention:** Lines 298–320 require representative props, independent capture-session evaluation, banner-only negatives and concurrent laptop workload measurements. Training completion and confidence alone do not establish acceptance.
- **Scope and schedule pressure:** Lines 16–18, 407 and 409–422 acknowledge shared robot time, additional integration work and unresolved capacity. City actions remain explicitly deferred until applicable scoring rules exist; they are not represented as implemented or scheduled.
- **Security and bounded evidence handling:** Lines 249–266 bound observations, preserve original QR content and separate evidence references from remote filesystem instructions. Later lines 561–565 explicitly reject path traversal and clarify byte-bound validation.

The open hardware measurements, final City rules, measured thresholds and surveyed coverage are explicit prerequisites with failure consequences. They are not concealed decisions or missing proof presented as success.

## Alternatives rule

The active specification meets the alternatives requirement. Lines 164–245, 274–366 and 424–519 compare mechanisms, costs and failure conditions.

The Pi alternative is retained as a genuine option rather than rejected through an invented benchmark. Its disposition is transparently a recorded team platform choice, with migration costs, compatibility risks and reconsideration conditions preserved. The other principal selections have concrete technical trade-offs, including final-monitor reuse versus custom guard geometry, 3D versus planar obstacle representation, generated interfaces versus JSON, trained detection versus reference matching, and surveyed viewpoints versus target-depth localization.

## Actual-read manifest

All reads were local and read-only.

Read completely:

- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/design_critic.md`
- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/feature-spec-standard.md`
- `/home/lev/IJKbot/concepts_brief.md` — lines 1–188
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/goldfish_review_report.md` — lines 1–78
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/draft_reconciliation.md` — lines 1–52
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/platform_decision.md` — lines 1–43
- `/home/lev/IJKbot/docs/GOROD.md` — lines 1–54
- `/home/lev/IJKbot/docs/designs/rtk_final_2026.md` — active lines 1–529
- `/home/lev/IJKbot/docs/designs/rtk_final_2026.md` — later lines 530–838, consulted only for already specified explanations and mitigations; not audited as active implementation scope

The initial combined output was truncated. All affected mandatory context and target content was reread in smaller, complete chunks. No inaccessible files remained.

No other review reports, repository source files, external URLs or network resources were read. No files were changed, and no builds, tests, robot commands or deployments were performed.
