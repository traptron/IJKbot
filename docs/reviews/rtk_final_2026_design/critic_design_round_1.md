Design Critic review — Stage 7, round 1

Status: Complete. One Major finding; no Blockers or Nits.

Target: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, lines 1–525, evaluated against the Feature Specification Standard. Lines 526–834 were read only to check whether later material already resolves an apparent gap.

design-1-1 — Major — Autonomous mission-owner loss has no defined onboard response

Affected target scope: lines 108 and 120–150, split-host architecture; lines 207–228, motion ownership and protection; lines 279–292, retry and return deadlines; lines 519–522, timing and recovery requirements.

Discrepancy and rationale:

The laptop owns mission coordination while onboard Nav2 executes navigation goals. The specification defines protection-process failure, stale sensing, command freshness and preserved lease behavior, but does not define what happens when the laptop mission coordinator crashes, stalls or becomes disconnected while an onboard navigation goal remains active.

These are different failures. Onboard Nav2 can continue generating fresh commands for an existing goal while the laptop no longer manages the mission deadline, return reserve or reset state. Collision Monitor and the driver's command timeout do not inherently detect this condition because local sensors and velocity commands can remain current.

Preserving the existing lease does not establish autonomous mission-owner supervision. Local evidence shows that the existing guard is specifically a web-control lease and permits forwarding while disarmed. The specification needs an explicit choice about whether and how autonomous operation depends on a live mission owner.

Concrete remedy:

Define the autonomous ownership contract at the architecture level. Specify which onboard component detects mission-owner loss, the bounded response, and how active navigation goals and permission are invalidated. For example, require a current mission/attempt-bound lease and latch motion inhibition after expiry; cancellation and reconnect must not silently revive a previous goal. Alternatively, explicitly allow a bounded onboard continuation policy and identify who enforces its deadline and terminal outcome.

Require a mock acceptance case that kills or partitions only the coordinator while onboard Nav2, sensors and protection remain healthy. Check the specified stop/continuation boundary and verify that reconnect or coordinator restart cannot resume stale mission work automatically. Numerical thresholds can remain measurement outputs.

Local evidence:

- `/home/lev/IJKbot/src/bringup/scripts/web_guard.py:7–14` initializes the guard as `disarmed`.
- `/home/lev/IJKbot/src/bringup/scripts/web_guard.py:31–46` times out only an armed web session; `tick()` blocks forwarding only in the latched state.
- `/home/lev/IJKbot/src/bringup/scripts/robot_monitor.py:58–59` receives mux commands and a separate `/ijk/web/lease`; lines 87–89 forward commands according to that web guard.
- `/home/lev/IJKbot/src/brain/mission_sm.py:1534–1548` submits a `NavigateToPose` goal. Lines 1554–1563 provide a goal-topic fallback.
- Later target lines 736–739 and 815–826 require lease-loss, protection-process and sensor/permission tests, but do not identify an autonomous coordinator lease or specify the outcome of coordinator-only failure.
- Searches of `mission_sm.py`, `competition.py`, `runner.py`, `robot.launch.py` and `system.launch.py` found no matching autonomous lease/heartbeat wiring. This supports the gap; it is not proof of deployed behavior.

Standard assessment:

The problem, goals, non-goals, component responsibilities and major alternatives are documented. Rejected alternatives include concrete technical trade-offs rather than relying solely on author approval. Nano compatibility, physical coverage, target data, catalogue ambiguity and City rules are explicitly unverified prerequisites with failure consequences; I have not treated them as demonstrated capabilities or separate missing-mitigation findings.

The remaining Major finding concerns an unspecified failure policy introduced by the split-host architecture, rather than a demand for measurements that cannot yet exist.

Actual-read manifest:

- Persona: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/design_critic.md` — complete.
- Assigned standard: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/feature-spec-standard.md` — complete.
- Target: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md` — complete lines 1–525 for audit; complete lines 526–834 for missing-context checks only.
- `/home/lev/IJKbot/concepts_brief.md` — complete, lines 1–188.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/goldfish_review_report.md` — complete, lines 1–78.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/draft_reconciliation.md` — complete, lines 1–52.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/platform_decision.md` — complete, lines 1–43.
- `/home/lev/IJKbot/docs/GOROD.md` — complete, lines 1–54.
- Additional local source: complete `web_guard.py`; `robot_monitor.py` lines 32–120; `mission_sm.py` lines 1510–1578; focused text searches across the files named in the evidence above.
- Truncation repair: initial combined output was truncated. Subsequent bounded reads recovered the affected concept, City-guide and target ranges; no required read remains missing.
- Inaccessible files: none.
- Operations: local reads only. No writes, builds, tests, hardware/network commands, external browsing or further agents.
