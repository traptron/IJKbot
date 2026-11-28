Review completed read-only. No files written. Five consequential findings follow; all are **Major concept requirements**, not claims that the brainstorm should already contain a detailed implementation.

### Scope and standards

Target read completely: `/home/lev/IJKbot/docs/reviews/rtk_final_2026/initial_concepts_brief.md`.

Required materials read completely:

- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/codebase_details.md`
- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/heilmeier-standard.md`
- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/zoom-out-standard.md`

The brief supplies sufficient context and correctly separates repository observations from deployment and team experience. The findings strengthen its intermediate/final exams and reuse decisions. External-laptop permission remains accepted. Nothing here establishes the software deployed during previous failures.

### 1. Collision acceptance must include search rotation and other motion sources

**Severity:** Major  
**Dimension:** Observability & Operational SRE Debuggability  
**Target:** brief lines 43, 51–52, 95, 108.

**Evidence:** `/home/lev/IJKbot/src/nav2/config/nav2_params.yaml:130–144,168–181` confirms `/scan` as the only obstacle observation source. `/home/lev/IJKbot/src/brain/mission_sm.py:1012–1013` commands search rotation directly; lines 1305–1308 and 1489–1497 route this through `/cmd_vel_sm`. `/home/lev/IJKbot/src/nav2/config/twist_mux.yaml:13–20` gives mission commands priority over navigation. `/home/lev/IJKbot/src/bringup/launch/robot.launch.py:166–171` routes the arbiter through `/cmd_vel_mux`; `/home/lev/IJKbot/src/bringup/scripts/robot_monitor.py:53–62,87–107` forwards or stops those commands according to the web-control guard. The inspected monitor is not an obstacle checker.

**Operational risk / inference:** A new depth input can improve navigation goals while leaving search rotations vulnerable to low obstacles. A stationary center does not mean the rectangular chassis cannot touch an object while turning. This is a motion-coverage risk established by the source paths, not a claim about an observed collision.

**Mitigation requirement:** Define acceptance as safe behavior for every autonomous motion source, including search rotation, approach, recovery, and return. Record sensor freshness, requested versus final velocity, active command source, and the reason for each stop. Explicitly decide the response to missing/stale obstacle observations.

**Options:** Route search motion through an obstacle-aware motion controller; or assess a shared final obstacle-checking stage for all velocity commands. Nav2’s existing Collision Monitor provides a candidate with source freshness handling and an optional state topic. Its official Jazzy tutorial requires placement at the end of the velocity processing chain; integration must preserve the existing guard and motor timeout. [Jazzy Collision Monitor tutorial](https://docs.nav2.org/jazzy/tutorials/general_tutorials/using_collision_monitor/using_collision_monitor/), [Jazzy Collision Monitor parameters](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/collision_monitor/configuring_collision_monitor_node/).

**Concrete validation:** Using mock/replay first and controlled field tests later, place representative low obstacles beside the chassis during the complete search sweep, then test approach and return. Interrupt the added sensor during each motion. Verify the physical clearance and measured stopping response, not merely the presence of costmap cells.

### 2. QR diagnosis requires capture-to-decision correlation, especially across scan phases

**Severity:** Major  
**Dimension:** Observability & Operational SRE Debuggability  
**Target:** brief lines 36, 44, 53–54, 109.

**Evidence:** `/home/lev/IJKbot/src/brain/mission_sm.py:936–938,1015–1061` accepts search results during `CHECK`, with a one-second check interval. Its callback at lines 1444–1465 receives plain text, stores receipt time, and accepts according to the state/phase at arrival. It has no acquisition timestamp, scan-step identifier, or explicit rejection event.

The default native reader’s trigger callback, `/home/lev/IJKbot/src/vision_cpp/src/qr_reader.cpp:60–70`, uses the latest retained image. Lines 181–182 apply epoch/state rejection only to non-forced results. Lines 197–203 publish text and a separately stamped evidence image. The snapshot trigger and text result do not carry a shared attempt identifier.

**Operational risk / inference:** A delayed result can be rejected after its valid view ends, or associated with a later eligible view. A trigger can process a retained old frame when capture has stopped. These are concrete failure hypotheses; neither is proven to explain the competition failure.

**Mitigation requirement:** Every attempted view should expose whether a fresh image arrived, its acquisition age, trigger/view identity, decoding duration/outcome, confirmation status, and mission acceptance or rejection reason. Failed attempts need bounded evidence retention too. The requirement belongs in the concept; message schemas and storage format can wait for design.

**Options:** Extend the current trigger/result contract with correlation metadata; alternatively retain a small correlated diagnostic event stream alongside existing public topics. Do not introduce a general distributed tracing platform merely for this mission.

**Concrete validation:** Replay the same scene with processing delays below and above the check interval, freeze camera delivery, and return results after a phase/state change. An observer must identify the exact failing boundary and verify that stale/wrong-view results cannot advance the mission.

### 3. Existing “mission complete” output is insufficient evidence of scoring-stage completion

**Severity:** Major  
**Dimension:** Observability & Operational SRE Debuggability  
**Target:** brief lines 38–39, 44–45, 55, 62.

**Evidence:** QR acceptance sets both `victim_found` and `qr_scanned` in `/home/lev/IJKbot/src/brain/mission_sm.py:1454–1458`. The independent victim callback at lines 1423–1426 merely sets `victim_detected`.

When all views fail, lines 1081–1085 return home. Reaching home invokes `_handle_mission_completion` at lines 906–908. That method unconditionally sets `evacuated_home=True` and logs successful evacuation and full completion at lines 1121–1130. Consequently, “returned after search failure” and “completed all scoring stages” can share the completion label.

The five-second state at lines 892–900 measures elapsed time while commanding zero velocity; it does not itself demonstrate the nearest-cell requirement or observed physical stillness.

**Operational risk:** The team can count unsuccessful searches as complete missions or show judges a success message unsupported by the evidence. The brief already identifies QR/victim coupling; the additional issue is that existing completion reports cannot serve as its final exam unchanged.

**Mitigation requirement:** Define a stage-based trial result: independently established victim finding, accepted QR, required location/dwell evidence, return, time, contacts, and intervention. Distinguish “run ended,” “returned safely,” and “all required stages passed.” Report measured evidence separately from provisional scoring assumptions pending final rules.

**Options:** Reuse the protocol’s existing stage flags and chronology with corrected semantics, rather than create another dashboard. Keep partial-stage outcomes useful for prioritizing fixes and fallback behavior.

**Concrete validation:** Exercise no victim, unreadable QR, successful QR, early timeout, and normal completion. Compare exported outcomes with an observer’s annotated record. A no-victim return must not count as a fully successful evacuation trial.

### 4. Hardware/QR alternatives need a named baseline: the checkout already contains distinct native and Python paths

**Severity:** Major  
**Dimension:** Observability & Operational SRE Debuggability  
**Target:** brief lines 13, 31, 35–36, 53, 82, 104.

**Evidence:** `/home/lev/IJKbot/src/vision/launch/qr_reader.launch.py:18–24` selects `vision_cpp` by default, even though configuration is under `vision`. The native implementation already has a worker retaining the latest pending frame, configurable decoding duty cycle, and periodic decode-time/replaced-frame logging: `/home/lev/IJKbot/src/vision_cpp/src/qr_reader.cpp:25–33,46–58,133–179`.

The standalone CSI launch differs materially: `/home/lev/IJKbot/src/vision_cpp/launch/rpi_qr.launch.py:11–19,30–42` defaults to 1920×1080 acquisition, a separate QR image topic, three confirmations, disabled mission-state filtering, disabled disk snapshots, and one-shot completion. `/home/lev/IJKbot/src/vision/launch/rpi_qr.launch.py:23–36` delegates to this native path by default. In contrast, `/home/lev/IJKbot/src/vision/config/qr_reader.yaml:3–12` specifies the shared compressed camera topic, one confirmation, state filtering, and saved snapshots.

**Operational risk / inference:** A successful standalone demo and a failed mission may differ in image source, filtering, lifecycle, confirmation, and capture settings—not just decoder quality or compute capacity. Reimplementing threading or migrating to Nano before identifying the active path could spend scarce time duplicating existing work.

**Mitigation requirement:** Record one reproducible baseline per experiment: machine placement, exact entry point, selected implementation, actual camera/topic, resolution/compression, trigger mode, confirmation settings, and software/configuration revision. Preserve the 640×480 compressed Wi-Fi constraint; local higher-resolution processing is an option only after confirming which stream actually crosses the network.

**Options:** Keep native decoding on the current host; compare local high-resolution decoding plus permitted preview against laptop decoding only if image evidence identifies sampling quality as the limitation. Treat Nano migration as conditional on measured resource/latency failure.

**Concrete validation:** Feed the same representative recordings and prop arrangements through the selected paths; report attempt latency distributions, decoding success, resource load, and mission acceptance separately. No current source evidence establishes a need to replace Pi with Nano.

### 5. Reuse existing recording and telemetry, but expand them into a complete trial evidence bundle

**Severity:** Major  
**Dimension:** Observability & Operational SRE Debuggability  
**Target:** brief lines 47, 49–55, 67, 104, 110.

**Evidence:** Existing recording is available in `/home/lev/IJKbot/tools/ijk/runner.py:153–167`, enabled by the competition profile at `/home/lev/IJKbot/tools/ijk/profiles/competition.py:28–29`. Its default topic list records scans, odometry, TF, command velocities, and `/victim_status`; it omits mission state, photo triggers, QR images, depth obstacle input, costmaps, and system metrics.

`/home/lev/IJKbot/tools/ijk/web/telemetry.py:10–67` already provides topic age/rate and DDS link round-trip/missing-response metrics. `/home/lev/IJKbot/src/bringup/scripts/robot_monitor.py:15–37,109–111` exposes CPU, memory, temperature, and Wi-Fi signal. `/home/lev/IJKbot/tools/ijk/profiles/doctor.py:68–78` provides clock/power checks.

The mission protocol at `/home/lev/IJKbot/src/brain/mission_sm.py:1234–1266` exports chronology and stage flags, but only a Boolean for snapshot availability. Its internal chronology is bounded to 1,000 entries at lines 500–510; the automatic save inspected occurs on completion.

**Operational risk:** The team has useful tools already, but a default recording cannot reconstruct the low-obstacle-to-stop chain or a failed QR attempt. A crash or stopped run can also leave less evidence than a completed run. Without a shared run identity, resource experiments cannot be reliably tied to software configuration and outcomes.

**Mitigation requirement:** Every acceptance trial should produce an identifiable, recoverable bundle containing its baseline, stage outcomes, synchronized relevant events, selected failed/successful image evidence, sensor freshness, and resource/link measurements. Save incomplete/failed runs too. Specify a bounded retention and recording-overhead budget.

**Options:** Extend the existing recorder/protocol/telemetry facilities rather than build a new observability service. Keep bulky depth data local to the robot when needed for diagnosis; collect derived evidence without violating the Wi-Fi restriction.

**Concrete validation:** Hand a saved failed trial to the other two team members. They should independently identify whether it failed at acquisition, perception, transport, acceptance, navigation, or actuation, without rerunning the field setup. Verify that enabling recording does not invalidate timing or sensor performance.

### Source reading completion record

In addition to the fully read target/persona/standards, complete file contents were inspected for:

- `/home/lev/IJKbot/config/ijk.yaml`
- `/home/lev/IJKbot/docs/GOROD.md`
- `/home/lev/IJKbot/src/nav2/config/nav2_params.yaml`
- `/home/lev/IJKbot/src/nav2/config/twist_mux.yaml`
- `/home/lev/IJKbot/src/bringup/launch/realsense_laserscan.launch.py`
- `/home/lev/IJKbot/src/bringup/config/realsense_laserscan.yaml`
- `/home/lev/IJKbot/src/bringup/launch/laptop.launch.py`
- `/home/lev/IJKbot/src/vision/config/qr_reader.yaml`
- `/home/lev/IJKbot/src/vision/vision/qr_reader_node.py`
- `/home/lev/IJKbot/src/vision/vision/qr_decoder.py`
- `/home/lev/IJKbot/src/vision/launch/qr_reader.launch.py`
- `/home/lev/IJKbot/src/vision/launch/rpi_qr.launch.py`
- `/home/lev/IJKbot/src/vision_cpp/launch/rpi_qr.launch.py`
- `/home/lev/IJKbot/src/vision_cpp/src/qr_reader.cpp`
- `/home/lev/IJKbot/src/bringup/scripts/robot_monitor.py`
- `/home/lev/IJKbot/tools/ijk/profiles/doctor.py`
- `/home/lev/IJKbot/tools/ijk/profiles/competition.py`

Partial, targeted inspection; no whole-file completion claimed:

- `/home/lev/IJKbot/README.md` — opening/context section and search matches.
- `/home/lev/IJKbot/src/brain/mission_sm.py` — relevant state, search, QR, protocol, and motion sections; initial full-file output was truncated.
- `/home/lev/IJKbot/src/bringup/launch/robot.launch.py` — camera default, motor/arbiter, and monitor launch sections.
- `/home/lev/IJKbot/src/bringup/launch/system.launch.py` — targeted camera/arbiter search matches.
- `/home/lev/IJKbot/src/nav2/launch/navigation.launch.py` — velocity-routing search matches.
- `/home/lev/IJKbot/tools/ijk/runner.py` — recording and stop sections.
- `/home/lev/IJKbot/tools/ijk/web/telemetry.py` — lines 1–70, complete `Telemetry` class.
- Additional repository searches were used for discovery only; unrelated search matches were not audited.

No final-regulation PDF interpretation was independently performed in this review.

**Concise summary:** Keep the proposed priorities. Strengthen the concept with five testable requirements: obstacle coverage for search motion; correlated QR attempts and rejection reasons; truthful stage-based completion evidence; one named deployed/experimental baseline; and reusable, complete trial recording. Existing native QR and telemetry infrastructure substantially reduce the justification for immediate compute migration or a new diagnostics stack.
