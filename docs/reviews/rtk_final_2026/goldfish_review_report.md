# Goldfish brainstorm review: RTK final preparation

**Target:** [immutable initial brief](initial_concepts_brief.md). **Review completed:** 2026-11-16. **Mode:** BRAINSTORM.

## Reviewer status and isolation

| Lens | Status | Report and actual-read manifest |
| --- | --- | --- |
| Design / architecture and cost | Completed | [design.md](design.md) |
| Codebase / observability | Completed | [codebase.md](codebase.md) |
| Zoom out / simplicity and reuse | Completed | [zoom_out.md](zoom_out.md) |
| Comprehension / operator experience | Completed | [comprehension.md](comprehension.md) |
| Implementation readiness / migration | Completed | [migration.md](migration.md) |
| Structural / maintainability | Completed | [maintenance.md](maintenance.md) |
| Inventive catalyst / contradictions | Completed | [inventive.md](inventive.md) |

All seven returned actual reports and confirmed reading their persona, immutable target, Heilmeier standard and Zoom Out standard. Fresh reviewers were dispatched with `fork_turns: none`; parent conversation and other reviewers' findings were not supplied. Four completed reports were saved in the first session; the remaining three were dispatched independently on 16 November after the earlier coordinator was no longer active. Reviews ran in parallel within available slots, against the same snapshot. Host instruction-file exclusion was not tested; no claim of filesystem or project-instruction isolation is made.

The three later reports are explicitly marked as faithful condensed records of returned reports. All completed findings were read by the primary agent before synthesis. No reviewer failure is counted as a clean review. [Primary-agent source checks](source_checks.md) are additional evidence, not an eighth independent review.

## Overall assessment

**Post-review platform decision:** On 16 November the team selected original Jetson Nano DevKit as its onboard target. The Pi-first recommendation below records the independent review, not the currently selected platform. The updated concept includes migration/compatibility work; [decision and read-only Pi inventory](platform_decision.md) records the new evidence. The seven reviewers did not review this changed choice, and no guarantee of Nano performance is implied.

No concept blocker was reported. This supports continued design discussion; it does not establish implementation readiness, physical safety, likely score or the historical cause of QR failure. The local checkout cannot certify what ran on the robot.

The main risk is incomplete integration across perception, motion and stage evidence. Hardware replacement alone does not resolve it. Retain the Pi/laptop/lidar arrangement as the first candidate, test the complete chain, and escalate hardware changes only when a named physical or compute limit is demonstrated. The team has explicitly permitted serious changes; they remain valid options if this candidate fails.

## Deduplicated prioritized findings

| ID / priority | Finding and evidence | Required concept change | Validation proposal | Lenses |
| --- | --- | --- | --- | --- |
| R1 / Major | Search turns call mission velocity directly (`mission_sm.py:1013,1489`); Nav2 obstacle inputs do not cover that path. The inspected web guard enforces control state, not obstacles. | Assign obstacle protection across navigation, search, approach, recovery and return; define stale-input behavior and final command ownership. Preserve existing lease/stop/watchdog protections. | Cars beside the chassis during turns, route obstacles, stale depth and interrupted network; record requested/final velocity and measured stopping clearance. | Design, codebase, zoom out, maintenance |
| R2 / Major | QR can set victim evidence. Search exhaustion and timeout enter return; arrival calls completion, which unconditionally marks evacuation (`mission_sm.py:850,906,1082,1121`). | Separate candidate, confirmed victim, accepted QR, verified dwell, safe return and complete mission. One mission transition owner controls acceptance. | No victim, unreadable QR, banner alone, combined evidence, timeout return, reset; compare outcome ledger with observer record. | All seven |
| R3 / Major | QR text has no explicit captured-view identity; acceptance is based on arrival phase. Standalone/native/Python configurations differ. | Identify the deployed path before replacing it. Track image acquisition, view/attempt, decode and acceptance; retain rejected/failed evidence. | Same banner in standalone and mission modes, delayed/duplicate/frozen-frame responses, second attempt in the same session; diagnose optics versus timing from traces. | Design, codebase, zoom out, comprehension, migration, maintenance, inventive |
| R4 / Major | Camera visibility, valid depth, obstacle insertion and physical response are unproven. Floor/bridge transitions and turning blind areas matter. | Run a bounded geometry-to-motion experiment; keep lidar interfaces stable and raw depth processing local. Establish calibration and sensor-health responsibility. | Representative 4 cm cars, approach angles, turns, bridge approach/crest/exit and full workload. Route completion and safe stopping are separate tests. | Design, codebase, zoom out, migration, maintenance, inventive |
| R5 / Major | Existing native QR, recorder, protocol and telemetry can be reused, but default recordings omit relevant events/images and existing success flags can mislead. | Give each trial a baseline identity, evidence bundle, truthful stage ledger and recoverable failed-run record. Limit recording overhead. | Another teammate must explain a saved failed run without repeating the setup; check recording load. | Codebase, zoom out, comprehension |
| R6 / Major | Three people and calendar days do not establish available robot/field hours; component ownership can postpone integration. | Name an integration owner, shared field slots, capacity, major-change cutoff, protected full-run time and a restorable baseline. | Schedule the next real session with one robot; restore the candidate after restart; produce a full-run attempt before mid-window. | Design, zoom out, comprehension, migration |
| R7 / Major | City currently has sign outputs and operator-directed navigation; matching cell sizes do not provide autonomous City behavior. | Choose an explicit score-bearing City slice and capped effort; share navigation/safety, keep discipline behavior separate. | Autonomous selected City route under changed signs, followed by a documented switch and Evacuation regression without a second commander. | Zoom out, comprehension, maintenance |
| R8 / Major | New observation semantics, sensor inputs, calibration or compute placement can mix old and new behavior across hosts. | Promote one coordinated candidate between stopped missions, keep baseline plus candidate only, and record restrictions of a fallback that misses cars. | Legacy QR producer, late results after reset, depth loss and restored configuration; verify no silent authority or safety loss. | Migration, maintenance, design |

The inventive reviewer classified additive sensing as advisory; the combined R4 is Major because other independent lenses identified unresolved physical coverage and motion-response requirements. This report does not inflate advisory pattern suggestions into separate blockers. Overlapping findings are deduplicated; no artificial finding count is used as a quality metric.

## Options, objections and choices still owned by the team

* **Retain current computing and add measured depth coverage.** Lowest migration surface, but cannot be selected on architecture alone: usable depth, bridge handling and workload must pass.
* **Reposition/add a confirmed available camera or complementary near-field sensor.** Appropriate for a demonstrated blind area; costs brackets, wiring, calibration and repeated tests. Sensor availability does not prove reliable 4 cm detection.
* **Use the Nano for a measured compute problem.** Requires compatibility, workload and deployment proof. [Official-source check](source_checks.md) identifies original Nano versus Jazzy platform risk without asserting impossibility or measured inferiority.
* **Recognize the banner as a search cue.** May simplify finding a viewing direction; whether it can confirm the victim depends on final judging criteria. Separate toy detection is not automatically required or automatically unnecessary.
* **Adopt a common final stopping boundary.** Could cover direct turns as well as navigation; costs another configured component and possible false stops. Evaluate existing Nav2 mechanisms before writing custom control infrastructure. It must preserve the current guard and driver timeout, with no alternative unguarded command path.
* **Broaden City early.** Could earn additional points, but competes for the same robot. A bounded, measurable City slice is preferable to an undefined parallel mission rewrite; the actual cap remains a team decision.

## Inventive synthesis

No false compromise was found in the initial hardware stance. Three useful refinements are separation of evidence from stage completion; a local hazard input that complements lidar navigation; and preserving observation context before changing timing or computing. Their costs are association logic, additional calibration/processing and bounded evidence storage. None removes physical visibility limits.

Ideal outcome: the operator starts one known configuration, the robot observes collision-relevant space, every autonomous motion respects current obstacle data, each observation advances only the stage it proves, and a recorded complete run supports the claimed result with few new components.

## Proposed staging, not an approved schedule

Departure is 1 December; from 16 November there are 15 calendar days. At review time actual working hours were unknown. After review the user reported 2–3 hours per day. The revised concept conservatively interprets this as 30–45 shared robot/field hours if available daily, and budgets against 30. This new fact was incorporated by the primary agent; independent reviewers did not review this updated allocation.

| Proposed dates | Evidence to obtain | Decision |
| --- | --- | --- |
| 16–18 November | Deployed baseline; actual props/QR and bridge geometry; complete recorded current attempt; depth-to-motion and QR boundary diagnosis | Select baseline plus one candidate; identify any necessary mechanical/compute change |
| 19–22 November | Candidate low-obstacle response across motions; independent stage evidence; first complete Evacuation attempt | Continue hardware changes only for a measured unresolved limit; choose bounded City behavior from rules |
| 23–25 November | Repeated complete Evacuation runs with changed placements; selected City run; cross-discipline restart/regression | Freeze major architecture/mounting changes after 25 November if evidence permits |
| 26–30 November | Repeated timed trials, failure/reset/restart rehearsal, configuration restoration and packing | Fix demonstrated faults; retain verified configuration and explicit remaining limitations |

Proposed engineering milestone: five consecutive complete Evacuation trials with varied target/obstacle positions, no contact/intervention, and the applicable mission time limit. A failure requires diagnosis and a new consecutive series after the fix. Five trials are a practical team gate, not statistical proof or a guarantee of maximum competition points. Final timing/scoring must use the applicable final rules. A safe stop is an intermediate result; a robot that remains stopped does not pass the complete-route test.

## What remains unknown

Individual attendance and confirmed daily robot/field access within the reported 2–3-hour window; deployment and current sensor/mount inventory; QR/figure samples; bridge geometry and mechanical capability; final rules beyond the accepted laptop permission; numerical City target; measured delays/stopping distance; and the historical QR failure cause. These require team answers or experiments, not further speculative architecture.

## Work performed and limits

Documents and local source paths were reviewed; official documentation was consulted for specific platform and Nav2 capabilities. No robot test, build, SSH/deployment, hardware motion, source/configuration edit or commit was performed. Initial unrelated working-copy edits remain outside this review. The concept brief incorporates these findings as recommendations pending team alignment.
