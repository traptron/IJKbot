# Stage 8 — Intermediate Zoom Out Review

**Date:** 2026-11-17  
**Mode:** REVIEW  
**Target:** `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, lines 1–840  
**Reviewed SHA-256:** `023772a41b6bbf1f781f9b5b87c1d17c239bee5c9434d2776eba264731b14db1`

The design provides enough context and addresses the root problem: incomplete sensing-to-motion integration, unreliable observation acceptance and misleading mission outcomes. It also preserves useful boundaries: local obstacle processing, one final protected command path, laptop perception, separate stage evidence and deferred City behavior.

Three earlier Major findings remain open. The mission-owner mitigation added during Critic review is appropriate, but its detailed implementation contract remains incomplete. No Blocker or genuinely new high-level YAGNI finding was established.

## Findings carried from earlier stages

### IZO-01 — Major — Shared validation still crosses the perception/mission dependency boundary

**Duplicate:** S5-01. Original severity preserved.

**Affected target:** “Generate and verify the common interface package,” lines 684–687; package updates, lines 798–800.

Line 686 still places Python validation and deduplication helpers “shared by perception and coordinator” in `src/brain/observation_contract.py`. This leaves the dependency direction unresolved. Payload validation is common contract logic; current-attempt eligibility and mission deduplication belong to mission acceptance.

**Simplicity and reuse rationale:** Perception should not need mission or dashboard code to produce an observation. Putting shared helpers inside the mission package introduces coupling without solving an additional problem. Generated interfaces already provide the common transport boundary.

**Local evidence:** `src/brain/package.xml:17` already declares a runtime dependency on `vision`. `src/vision/package.xml` does not currently depend on `brain`. A new reverse dependency would create a package cycle; an undeclared reverse import would make deployment unreliable. This is a proposed dependency problem, not an existing cycle established by this review.

**Actionable remedy:** State one acyclic dependency direction. Either place genuinely shared Python payload checks below both packages, with explicit installation/dependencies, or keep producer checks local and verify them using common contract fixtures. Keep mission-context checks and mission deduplication in `brain`.

**Verification criterion:** The perception producer imports and starts without the mission/dashboard package. The declared package graph is acyclic. Shared fixtures demonstrate consistent payload validation, while coordinator tests establish current-attempt acceptance separately.

### IZO-02 — Major — The evidence gate still depends on capabilities that the gate prevents building

**Duplicate:** S5-02. Original severity preserved.

**Affected target:** Ordered-work-list rule, line 634; Step 4, lines 660–668; Step 7, lines 714–730; Step 8 prerequisite, line 734; phase acceptance, lines 828–830.

Step 4 requires measurements of the selected ground/hazard processing path, full workload and settings. Step 7 may start only after Steps 1–4 and explicitly requires Step 4 to supply the compatible segmentation operation and parameter evidence. Step 8 similarly requires the measured stopping/coverage envelope before installing the final protection chain.

The document allows mock work in general, but does not name the preliminary candidate or experiment that produces this evidence before these prerequisites apply. The general permission at line 828 does not clearly resolve the stricter work-order rule at line 634.

**Simplicity and root-problem rationale:** Evidence gates should distinguish exploratory feasibility from final physical acceptance. Requiring final evidence before the measuring capability exists creates an execution loop and encourages undocumented prototype work.

**Local evidence:** Repository searches found no existing `depth_hazards` implementation or Collision Monitor configuration. The current RealSense launch disables point-cloud output and launches `depthimage_to_laserscan`. Current local/global costmaps use `/scan` through Obstacle Layers. The proposed depth capability therefore cannot simply be measured as an existing checkout component.

**Actionable remedy:** Split the sequence explicitly:

1. Build a bounded replay/mock feasibility candidate using recorded depth and provisional, clearly labelled settings.
2. Use that candidate to establish dependency compatibility, object preservation and preliminary timing.
3. Implement the integrated production path.
4. Require the measured full-workload profile and controlled stopping tests before physical autonomous readiness.

Name the experiment, its available inputs, outputs and stop conditions. Do not replace missing measurements with guessed approved values.

**Verification criterion:** Every required measurement has an available producer or a named preliminary experiment. The dependency sequence contains no cycle. Preliminary replay/mock acceptance and final physical acceptance are distinct.

### IZO-03 — Major — The inherited clearance requirement is still unnamed

**Duplicate:** C-01. Original severity preserved.

**Affected target:** Goals, line 51; motion protection, line 215; Non-Functional Requirements, line 525; Step 8, line 738; verification, line 823.

The target repeatedly requires preservation of “required clearance,” but does not state or directly link its inherited definition. Speed and command timeout are stated explicitly; clearance remains an unspecified existing constraint.

**Simplicity and root-problem rationale:** A mandatory inherited constraint should have one authoritative definition. Otherwise each later configuration task must rediscover it and may interpret it differently. This is separate from future measurements of footprint, stopping distance and protection-zone dimensions.

**Local evidence:** `/home/lev/IJKbot/AGENTS.md:87` requires `inflation_radius` not to fall below robot radius plus 50 mm. The current `nav2_params.yaml` uses a polygon footprint and `inflation_radius: 0.28` at lines 129/148 and 163/185. These configuration values do not establish a newly measured physical envelope, nor does the target identify them as its authoritative requirement.

**Actionable remedy:** State the inherited inflation-radius rule or link directly to AGENTS.md §4.1.2. Explain that the applicable robot geometry must be verified and that measured stopping/coverage settings must also satisfy this constraint. Do not present inflation alone as proof of physical contact avoidance.

**Verification criterion:** A reader can locate the exact inherited rule from the target and determine how the measured geometry and final configuration will be checked against it without guessing a numerical robot radius.

## Alignment of the Critic-stage addition

### IZO-04 — Major — The mission-owner policy is not yet represented by an executable implementation contract

**Traceability:** This carries the implementation-alignment obligation already recorded for Critic finding `design-1-1`. It is not a duplicate of S5-01, S5-02 or C-01, and it is not a genuinely new architecture requirement.

**Affected target:** Mission-owner policy, lines 230–234; contract definitions, lines 569–571 and 622–630; Step 8, lines 742–745; Step 9, lines 755–764; verification/profile, lines 820–832.

The new policy correctly distinguishes coordinator health from healthy onboard navigation. It requires onboard owner expiry, retired owner contexts, cancellation of old navigation work and explicit recovery into a new attempt. However, the detailed contracts do not define the owner-update transport or its fields. The task list does not explicitly assign the coordinator-loop update producer, onboard owner lifecycle/cancellation handling or recovery confirmation. “Lease loss” in the motion-chain test row is ambiguous because an existing web lease already exists.

**Simplicity and reuse rationale:** This safeguard solves a real failure boundary. It should extend the existing permission boundary rather than become a separate control framework. Leaving its contract implicit risks implementing another generic heartbeat that remains healthy while mission progress is stalled, or reusing the web lease despite the required independence.

**Local evidence:**

- `robot_monitor.py:43–60` creates one `WebGuard` and subscribes to `/ijk/web/lease`; lines 87–107 gate forwarded commands and publish guard state.
- `web_guard.py:6–51` already supplies monotonic expiry, sequence checks, retired tokens and restart latching. These are useful patterns, but their existing semantics cover web control.
- `tests/test_ijk_telemetry.py:42–83` already tests stale heartbeats, token retirement and restart behavior.
- `mission_sm.py:1315–1327` creates the laptop-side Nav2 client and goal publisher. Its existing cancellation method at lines 1619–1631 depends on that mission process being alive.
- Searches across `src`, `tools` and `tests` did not find a distinct mission-owner lease implementation.

**Actionable remedy:** Complete the narrow contract and map it onto the listed files: owner session/mission/attempt identity, advancing update sequence, coordinator-loop publication, onboard expiry and retirement, local cancellation request, recovery confirmation and admission of new navigation work. Explicitly assign the needed dependency declarations and tests. Reuse the existing guard’s pure-state patterns where appropriate without treating its current web behavior as sufficient.

Add owner-update age and owner-loss stop-response bounds to the measured-profile inventory. Their actual values remain measurement outputs.

**Verification criterion:** The detailed plan identifies the producer, consumer, contract, configuration and recovery path. Mock tests stall, kill or partition only the coordinator while Nav2 and sensors stay healthy; motion is inhibited within the validated bound, cancellation failure cannot defeat stopping, delayed updates cannot rearm the expired owner, and reconnect/restart cannot resume the old attempt.

## Assessment of the recent mitigations

The single-victim/single-adjacent-QR clarification at lines 30 and 345–351 removes the speculative need for multi-target pairing. Separate victim and QR evidence may reasonably come from different verified views of that one pair. No multi-target association framework is warranted by the stated scope.

The mission-owner addition addresses a distinct root cause: healthy sensors, Nav2 and velocity traffic do not prove a healthy coordinator. Its placement at the existing onboard permission boundary is appropriate. IZO-04 concerns completing its implementation contract, not rejecting the policy.

The selected native QR reader, Nav2 mechanisms, CLI, recorder and telemetry remain credible reuse surfaces. Repository searches did not reveal an existing equivalent for the proposed typed acquisition envelope, toy detector or connected-support hazard pipeline. Their absence supports the stated implementation work, but does not prove feasibility, compatibility or adequate performance.

City deferral remains bounded and explicit. No autonomous City controller should be inferred from existing sign recognition or operator navigation. The design appropriately avoids committing controller source files before the score-bearing action set is known.

Exact message fields and APIs largely stay in Detailed Implementation. They are therefore not independently flagged as an altitude problem. The main remaining simplification is to repair dependency ownership and the experiment sequence, rather than add more components.

## Actual-read manifest and limits

Read completely:

- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/zoom_out.md`
- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/zoom-out-standard.md`
- `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, all 840 lines
- `/home/lev/IJKbot/concepts_brief.md`, all 188 lines
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/goldfish_review_report.md`, all 78 lines
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/draft_reconciliation.md`, all 52 lines
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/platform_decision.md`, all 43 lines
- `/home/lev/IJKbot/docs/GOROD.md`, all 54 lines
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026_design/zoom_out_report.md`, all 46 lines
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026_design/comprehension_report.md`, all 24 lines
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026_design/critic_report.md`, all 30 lines

**Target read ranges:** 1–210, 211–420, 300–420, 421–630, 551–700 and 701–840. Aggregated responses truncated parts of the middle target ranges; rereading 300–420 and 551–700 repaired them.

**Context truncation repairs:** The concepts brief was reread as 1–90 and 91–188. The brainstorm synthesis was reread separately in full. Reconciliation, platform decision and City guide were reread together in full. No required context remains truncated.

**Repository searches:** Used `rg --files` and `rg -n` across `src`, `tools` and `tests` for observation/capture interfaces, hazards/segmentation, detector implementations, QR workers, mission ownership, leases, cancellation, command routing, schema validation and recording. Searched AGENTS.md, README.md and Nav2 configuration for clearance definitions.

**Local source inspection:** Read all three relevant package manifests; complete `web_guard.py` and `robot_monitor.py`; README introduction and targeted clearance passages; relevant mission ROS setup/navigation/cancellation ranges; native QR reader ranges 1–165 and `qr.hpp`; recorder range 120–205; complete RealSense scan launch; Nav2 costmap range 120–190; native CMake rules; existing guard-test range 1–100; and search results from command, telemetry, sign, LLM and launch components. A truncated QR-reader middle excerpt was repaired by rereading lines 72–133. Source searches and excerpts are not represented as a complete audit of every repository file.

**Inaccessible required files:** None.

This was strictly local and read-only. No external URLs, parent conversation, memory or other chat history were retrieved. No agents were spawned. No files were changed, builds/tests executed, or robot/network commands issued. Physical values, installed dependency compatibility, performance and competition readiness remain unverified.
