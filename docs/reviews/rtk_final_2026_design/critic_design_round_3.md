Design Critic report — round 3

Review scope: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, lines 1–529, evaluated as a feature specification against `feature-spec-standard.md`. Lines 530–838 were read only to check for existing mitigations. No implementation audit was performed.

Result: one Major finding. No Blocker or Nit findings.

design-3-1 — Major — Same-view correlation does not establish that the QR belongs to the confirmed victim

Affected scope: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md:234–272`, especially lines 253–268, and lines 339–349.

Discrepancy: The design thoroughly associates observations with a mission, attempt, view and source capture, but does not define how the coordinator establishes that accepted figure evidence and accepted QR information refer to the same physical target. A current, correctly correlated view can contain a toy and an unrelated readable banner. Similarly, after changing viewpoints, fresh evidence can describe different objects while satisfying the same mission context. Separating victim and QR stage flags does not itself prevent their subsequent combination into a successful mission.

The design acknowledges related scenes: line 343 asks to keep figure and QR associations distinct; line 349 requires tests with multiple candidate objects and a readable banner separated from the figure. However, it supplies neither an association invariant nor an explicit ambiguous-association outcome. This differs from the nearest-cell ambiguity at lines 345–347, which has a selected resolution boundary and explicit failure handling.

Rationale: The stated goal at line 40 is to find the actual victim and obtain its QR information. The coordinator can otherwise truthfully accept two independent observations yet falsely claim that this combined goal was completed. Capture freshness and view identity prevent stale-result errors, but do not establish physical-object identity. This is an architectural acceptance risk under the standard’s requirement to identify and mitigate major failure modes.

Concrete remedy: Define a coordinator-owned selected-target association policy. State what evidence links a figure and banner to that target, how the association survives a viewpoint change, and which ambiguities prevent QR-stage credit. The policy can use surveyed target regions and image/pose evidence within T8-B; it need not introduce depth localization or a general tracking framework. Tie accepted figure, QR and hold-cell evidence to the same selected target record, and explicitly retain an incomplete outcome when association is unresolved. Add discriminating cases for an unrelated readable banner beside a toy, multiple toys/banners in one view, and a viewpoint change that exposes a different candidate.

Local evidence: The later common observation contract, lines 553–563, carries capture context, a figure bounding box and QR corners but defines no target-association acceptance rule. The later acceptance description at lines 765–769 specifies hold-cell resolution, current-context validation and stage reduction, but does not close this physical-target association gap. These later sections were consulted solely to avoid reporting an already specified mitigation.

Other assessment

The specification addresses the problem, goals, non-goals, component placement, command flow, alternatives and major deployment/resource risks. Nano compatibility, sensor geometry, detector performance, numerical stopping limits and City scoring remain explicitly unverified prerequisites with failure consequences. I did not treat author approval, proposed experiments or pending measurements as demonstrated capability. I found no additional actionable deficiency in the assigned feature-specification scope.

Actual-read manifest

Read completely:

- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/design_critic.md`, lines 1–63.
- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/feature-spec-standard.md`, lines 1–39.
- `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, active lines 1–529.
- The same target, lines 530–838, for mitigation checking only.
- `/home/lev/IJKbot/concepts_brief.md`, lines 1–188.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/goldfish_review_report.md`, lines 1–78.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/draft_reconciliation.md`, lines 1–52.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/platform_decision.md`, lines 1–43.
- `/home/lev/IJKbot/docs/GOROD.md`, lines 1–54.

An initial aggregate output was truncated. This was repaired through complete numbered reads of the concepts brief and consolidated brainstorm report, followed by separate complete numbered reads of the reconciliation, platform decision and City guide. The target was read in bounded, consecutive ranges without unresolved truncation. No required file was inaccessible.

No other review reports, source files, external URLs, chats or memory were read. No files were changed; no builds, tests, robot/network commands or subagents were used.
