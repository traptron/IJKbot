# Goldfish Annotated Review Report

Status: resolved

**Target:** [RTK final design](../../designs/rtk_final_2026.md) (`1–525`, Stage 7, round 1)

**Resolution:** The author approved all four proposed document fixes. All four were applied to the feature scope. Contested: 0; escalated: 0; declined: 0; remaining unaddressed findings from this round: 0. The earlier S5-01, S5-02 and C-01 remain open. This report belongs to the final-design review, not the earlier brainstorm review.

## Prioritized Findings & AI Suggestions

### design-1-1 [egm-design] — Severity: Major

* **Affected Scope:** Target lines 108, 120–150, 207–228, 279–292, 519–522 (Split-host ownership and motion protection).
* **Discrepancy Description:** The laptop owns mission coordination while onboard Nav2 executes navigation goals. The specification defines protection-process failure, stale sensing, command freshness and preserved lease behavior, but does not define what happens when the laptop mission coordinator crashes, stalls or becomes disconnected while an onboard navigation goal remains active.
* **Rationale:** Onboard Nav2 can continue generating fresh commands for an existing goal while the laptop no longer manages the mission deadline, return reserve or reset state. Collision Monitor and the driver's command timeout do not inherently detect this condition because local sensors and velocity commands can remain current.
* ***AI Suggestion:*** PROPOSE FIX
* ***Justification:*** The parent verified web_guard.py:7–46, robot_monitor.py:58–59,87–101 and mission_sm.py:1534–1563. The current web guard permits forwarding while disarmed; preserving it does not supply autonomous owner supervision. Propose a bounded owner-loss stop at the existing onboard permission boundary. This is a new policy proposal, not an implemented or tested guarantee. Its detailed transport, startup/reset semantics, file list and tests must be reconciled before implementation readiness; no numerical timeout is invented.
* ***Proposed Edit:*** Apply only the replacements below within the feature scope. No production change is proposed by this approval gate.

Replacement 1 (one occurrence) — before:

```text
Mock/replay tests first inject obstacles, sensor loss, stale data, competing commands and process failure. Controlled physical trials then measure response for navigation, search turns, approach, recovery and return. Watching the robot stop once is insufficient to accept the wiring.
```

After:

```text
Autonomous competition also requires a current mission-owner lease, enforced onboard at the permission boundary in `robot_monitor.py` independently of the existing web-control lease. Bind permission to the active coordinator session, mission and attempt. Only advancing owner updates emitted by the coordinator's mission-control loop may refresh its local monotonic deadline; fresh Nav2 commands, sensor traffic or web heartbeats cannot renew it. Measure and record the permitted owner-update age and stop-response bound in the accepted profile. Missing verified limits or a missing owner prevents autonomous readiness.

On owner expiry or invalidation, latch nonzero-motion inhibition in that common command path, record the owner-loss stop locally and request cancellation of onboard navigation work. Stopping must not depend on cancellation succeeding. Retire the expired owner context so delayed updates cannot restore permission. Reconnection or coordinator restart cannot resume the old attempt automatically: explicit stopped-state recovery must confirm cancellation/retirement of old work, establish a new attempt and owner session, and admit only newly authorized navigation work. Preserve the incomplete outcome and existing emergency/permission behavior; no new bypass publisher is introduced. The detailed contract, task list and tests must be aligned with this policy before implementation readiness is accepted.

Mock/replay tests first inject obstacles, sensor loss, stale data, competing commands and process failure. Also kill, stall or partition only the mission coordinator while onboard Nav2, sensors and protection remain healthy; verify the measured owner-loss stop bound, cancellation failure, delayed updates and restart/reconnect without stale-goal resumption. Controlled physical trials then measure response for navigation, search turns, approach, recovery and return. Watching the robot stop once is insufficient to accept the wiring.
```

### style-1-1 [egm-style] — Severity: Major

* **Affected Scope:** Target lines 300–312 (T5 detector preparation).
* **Discrepancy Description:** The sentence combines three decisions with different states. Line 20 already records laptop PyTorch and Ultralytics YOLO11n as selected; later T10/T11 sections confirm them. Library versions and measured runtime compatibility remain unresolved.
* **Rationale:** Readers could incorrectly reopen the selected model/runtime when following these preparation gates.
* ***AI Suggestion:*** PROPOSE FIX
* ***Justification:*** The parent checked the feature text and the recorded selections. CALIBRATE the obsolete sentence and the adjacent option-table wording, preserving the version, checkpoint, compatibility and concurrent-workload evidence gates.
* ***Proposed Edit:*** Apply only the replacements below within the feature scope. No production change is proposed by this approval gate.

Replacement 1 (one occurrence) — before:

```text
Validate on independent capture sessions and field arrangements before selecting model/version/thresholds
```

After:

```text
Validate on independent capture sessions and field arrangements before promoting weights and acceptance thresholds
```

Replacement 2 (one occurrence) — before:

```text
4. Select and pin the compact pretrained model, training/inference runtime and weights through a reproducible compatibility check on the laptop. No particular model generation, CUDA/TensorRT conversion or library version is selected in this draft. Measure memory/latency with QR, preview and the intended language-model workload; do not infer capacity from the GPU model alone.
```

After:

```text
4. Use the selected Ultralytics YOLO11n model with native PyTorch on the laptop. Pin compatible library versions and checkpoint artifacts after a reproducible laptop compatibility check; TensorRT conversion is outside the selected baseline. Measure memory/latency with QR, preview and the intended language-model workload; do not infer capacity from the GPU model alone.
```

### style-1-2 [egm-style] — Severity: Nit

* **Affected Scope:** Target lines 424 (Alternatives introduction).
* **Discrepancy Description:** These sentences defend the drafting process without giving the reader another engineering or operator decision.
* **Rationale:** The individual entries already identify author selections, measured limitations and reconsideration conditions.
* ***AI Suggestion:*** PROPOSE FIX
* ***Justification:*** DROP the drafting defenses through one short paragraph replacement. This Nit is worth fixing because the exact change is small, retains attribution and deferral distinctions, and changes no architecture or acceptance gate.
* ***Proposed Edit:*** Apply only the replacements below within the feature scope. No production change is proposed by this approval gate.

Replacement 1 (one occurrence) — before:

```text
This section was checked against the predecessor's `Alternatives Weighed` section and the subsequent author choices T1–T8. Author selections are recorded as such. The technical rationale describes the trade-offs discussed in drafting; it is not an invented quotation of the author's motives or an upstream maintainer rejection. No alternative is labelled physically disproven without an experiment. Deferred options remain distinct from rejected ones.
```

After:

```text
These alternatives reflect the predecessor's `Alternatives Weighed` section and recorded author choices T1–T8. Author selections are identified explicitly; deferred options remain distinct from rejected ones.
```

### style-1-3 [egm-style] — Severity: Nit

* **Affected Scope:** Target lines 430,451,458,465,479,486,493,500,507 (Alternative attribution labels).
* **Discrepancy Description:** The doubled label repeats “not selected” before the explanation begins.
* **Rationale:** It makes an already long comparison harder to scan.
* ***AI Suggestion:*** PROPOSE FIX
* ***Justification:*** Replace the nine doubled labels with one explicit author-decision label. This Nit is worth fixing as one bounded editorial replacement; retain every technical trade-off and reconsideration condition.
* ***Proposed Edit:*** Apply only the replacements below within the feature scope. No production change is proposed by this approval gate.

Replacement 1 (9 occurrences) — before:

```text
**Reason not selected:** **Not selected by author:**
```

After:

```text
**Author decision:**
```

## Approval boundary and remaining work

The full reviewer results are in [critic_report.md](critic_report.md). Machine-readable replacements and the reviewed hash are saved in [proposed edits](critic_round_1_proposed_edits.json). Applying the owner-loss proposal would update the architectural policy only in this active feature scope. Alignment of its detailed contract, tasks, configuration and acceptance tests remains required before implementation readiness, and no new production package or source file is authorized by approving these document edits.

The earlier S5-01, S5-02 and C-01 findings remain open and are outside this round's repair set. Proceeding to another review stage did not resolve or accept them as risks. There are no contested or escalated findings in this round, and no severity was changed.

After an author decision, the resolver records accepted fixes, explicit no-fix decisions and remaining issues. The review-loop then requires an explicit decision before another fresh round. Round 1 is not clean: two unsettled Major findings were present before any fix. No convergence or implementation readiness is claimed.

## Post-resolution synchronization

All exact replacements in this report were approved and applied. The target is now 838 lines; feature range 1–529; detailed range 530–838. SHA-256: `c6de09ea7dd6ba2f0ce4dc217c9ff2720326716d7a36c48e8ba5e150b9cb007a`. The detailed implementation text was preserved byte-for-byte after its heading. Its owner-loss contract/task/test alignment remains a readiness obligation. Old line references and quoted before-text in this report refer to the reviewed snapshot, not the revised target. No production files were changed. Another review round has not started.
