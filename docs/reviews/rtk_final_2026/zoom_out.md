# Zoom-out brainstorm review — RTK final preparation

**Status: complete.** Skeptical Architect, BRAINSTORM mode, 2026-11-15. Reviewed the immutable initial brief and searched the local checkout for simpler paths and reusable components. Five consequential findings follow. None is a blocker to continuing concept discussion; these are decision and validation risks before committing scarce field time. Deliberately deferred implementation details are not deficiencies in this brainstorm.

The brief sufficiently explains the objective, existing limits, priorities and uncertainty. Its default of retaining the proven navigation arrangement is sound. External-laptop permission is accepted as team-confirmed; this review does not reopen onboard LLM requirements. Local code and historical README deployment statements do not establish what is currently running on the robot. No robot access, build, installation, test execution or source/configuration modification occurred. Only this authorized report was written.

## 1. Major — Parallel ownership must not become three separate integration projects

**Dimension:** Contrarian / YAGNI & Code Minimization.

**Target:** initial brief lines 9–13, 43–47, 55, 103–110.

**Evidence:** The brief identifies three people and sixteen calendar days, explicitly leaves engineering/field hours unknown, and proposes one owner per workstream. The existing repository already has an end-to-end mission shell: `/home/lev/IJKbot/src/brain/mission_sm.py:861–908`, with mock mission and state-transition tests in `/home/lev/IJKbot/src/brain/test_mission_sm.py:92–138`.

**Inference/risk:** Assigning three independent feature deliveries can defer the most expensive discovery—whether the actual camera, controller and mission agree—until the final days. A single robot, its field access and mechanical setup are shared resources. Headcount does not multiply those resources. This is a scheduling risk, not a claim that the team lacks time.

**Simpler option:** Keep the three ownership areas, but make their shared first deliverable one recorded, end-to-end attempt on the existing system with representative props. Use its failure boundary to select the next change. Preserve one identified fallback configuration. Choose major-change cutoff and reserved field sessions from actual availability, before starting optional migration or City expansion.

**Strongest objection:** Establishing a baseline may consume a scarce field session while component work is already possible. Mitigate by using that session to collect reusable images, depth, mission events and timing; parallelize offline analysis of those recordings afterward.

**Concrete validation proposal:** Produce a resource sheet listing named owners, available hours, robot/field slots, prop/setup needs and the next integrated trial. Each proposed major hardware change must state the measured failure it resolves, installation/calibration effort, repeated-test cost and rollback method. Reserve complete-mission trials rather than filling the calendar with component demonstrations. Exact hours and repetition thresholds remain team decisions.

## 2. Major — Reuse the existing QR paths, but first identify which behavior is actually being tested

**Dimension:** Contrarian / YAGNI & Code Minimization.

**Target:** initial brief lines 20, 31–36, 44, 53–54, 82, 109.

**Evidence:** This checkout contains both Python and C++ readers. `/home/lev/IJKbot/src/bringup/launch/laptop.launch.py:85–91` includes the QR launch; `/home/lev/IJKbot/src/vision/launch/qr_reader.launch.py:14–24` defaults to `vision_cpp`; `/home/lev/IJKbot/src/vision/config/qr_reader.yaml:3–12` consumes the preview topic, enables mission filtering and uses one confirmation frame. The separate `/home/lev/IJKbot/src/vision_cpp/launch/rpi_qr.launch.py:14–19,30–42` instead selects the full-resolution topic, three confirmations, one-shot completion and disabled state filtering. `/home/lev/IJKbot/src/vision_cpp/src/qr_reader.cpp:212–219` ends processing after the one-shot result. These are different operating contracts, not evidence that both run together.

The mission accepts results during a restricted viewing phase (`/home/lev/IJKbot/src/brain/mission_sm.py:936–938,1444–1464`) and has a one-second check interval (`:408,1059–1061`). Existing QR code already provides snapshot triggers, evidence images and processing logs (`/home/lev/IJKbot/src/vision_cpp/src/qr_reader.cpp:60–70,197–218`).

**Inference/risk:** A standalone successful QR demonstration can legitimately use different image quality, confirmation and result lifetime from the mission. A result arriving outside the mission acceptance window, or an early one-shot completion, is a plausible integration failure to test—not a diagnosed explanation of the old run. Replacing the decoder or Pi before isolating this boundary could preserve the failure and add another migration.

**Simpler option:** Pick one existing reader/capture path as the candidate mission baseline; reuse its triggers and evidence output. Record the deployed launch, image topic, mode and timing before deciding whether camera relocation, decoding changes or computing changes are needed. Keep high-resolution processing local if used; retain the repository's Wi-Fi image limits.

**Strongest objection:** The real banner may still exceed existing capture/decoder capability. That should be demonstrated on recorded representative frames before starting a new detector or compute deployment.

**Concrete validation proposal:** Run the same physical banner through standalone and mission modes, logging image arrival, photo request, decode completion, result publication, receipt and acceptance. Include a result before the scan phase, a late result, no-decode frames and a second mission in the same session. Compare correct acceptance and latency, not merely visible QR text. This review executed none of those experiments.

## 3. Major — Define score-stage evidence independently of the existing “mission complete” flag

**Dimension:** Contrarian / YAGNI & Code Minimization.

**Target:** initial brief lines 36, 38–39, 44–45, 55, 62–64, 83.

**Evidence:** In the checkout, accepted QR text sets both victim-found and QR-read flags (`/home/lev/IJKbot/src/brain/mission_sm.py:1452–1458`). More subtly, exhausted search sets `RETURNING_HOME` without a QR (`:1081–1085`); reaching home invokes completion (`:906–908`), whose handler unconditionally sets `evacuated_home = True` and logs successful evacuation (`:1121–1130`). This is a local control-flow finding, not a claim about deployed software or actual awarded points.

**Inference/risk:** Counting dashboard completion events can overstate end-to-end readiness. Adding a toy-person detector alone does not correct what the mission considers evidence. Conversely, a generalized human detector, 3D target tracker and continuous visual servoing are not established necessities merely because the prop depicts a person.

**Simpler option:** Reuse the existing navigation, scan, hold, return and protocol shell, while defining distinct observable outcomes for candidate seen, victim confirmed, QR decoded, required hold satisfied and return achieved. Compare a small fixed-prop recognition method with a trained detector on actual prop images. Banner localization may guide viewing; retain the brief's rule that it is not automatically victim confirmation. Whether nearest-cell viewing suffices or an additional approach is required remains a physical and judging question.

**Strongest objection:** A fixed-prop method can be brittle under different poses or props. Include those variations and decoys in evaluation; prefer a more capable detector only if that evidence warrants its cost. Do not lower the objective to “QR read” or “returned home.”

**Concrete validation proposal:** A human-reviewed event ledger should score each stage independently during trials. Include no victim/no QR, banner without figure, figure with unreadable QR, successful full run, and timeout return. A safe or unsuccessful return must not count as evacuation success. Keep candidate/confirmation evidence images so the chosen method can be assessed against final judging requirements.

## 4. Major — Make low-obstacle avoidance a bounded sensing experiment before selecting new hardware

**Dimension:** Contrarian / YAGNI & Code Minimization.

**Target:** initial brief lines 21–24, 33–35, 43, 51–52, 80–84, 95, 107–108.

**Evidence:** `/home/lev/IJKbot/src/nav2/config/nav2_params.yaml:130–144,168–181` names only `/scan` in obstacle sources. `/home/lev/IJKbot/src/bringup/launch/realsense_laserscan.launch.py:53,58–67` disables point-cloud output and publishes a separate `/depth/scan`; `/home/lev/IJKbot/src/bringup/config/realsense_laserscan.yaml:3` selects fifteen rows. These files establish an incomplete local connection, not the complete cause of past collisions.

**Verified platform reuse:** Nav2's Jazzy obstacle layer supports multiple named observation sources and accepts `LaserScan` or `PointCloud2`. This supplies an existing integration point and does not establish correct ground rejection, coverage or performance on this robot. [Official Nav2 Jazzy obstacle-layer documentation](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/costmap_2d/costmap_plugins/obstacle/) (observation sources and input types; retrieved 2026-11-15).

**Inference/risk:** Jumping from missed cars to a Nano replacement, multiple added sensors or a new navigation framework increases dependencies before demonstrating the missing physical measurement. Simply connecting the narrow slice is also insufficient if it never observes the cars. A floor-height filter that works on level ground cannot be assumed to preserve a traversable bridge.

**Simpler options:** First evaluate a measured camera mounting/coverage plus a depth observation path into the existing Nav2 layer. Keep any raw depth/cloud processing on the robot. Compare an existing layer input with the minimum needed preprocessing; do not commit to a custom fusion stack or 3D mapper. Consider ultrasonic coverage or compute changes only for a documented residual gap. The roof-lidar bridge constraint remains accepted pending mechanical measurement.

**Strongest objection:** The Pi may lack capacity, or no allowed mount may cover close obstacles and the bridge. Those are decisive open measurements, not reasons to promise the current hardware will suffice. Benchmark the candidate full workload and inspect physical coverage before selecting replacement hardware.

**Concrete validation proposal:** For representative four-centimetre objects, record valid depth, insertion into the costmap, resulting motion and actual stopping/clearance. Test frontal and turning approaches, disappearance of data, floor variations and bridge approach/crest/exit. Measure end-to-end latency and stopping distance at the intended speed, with all intended computation active. Pass requires avoiding contact and completing the route; stopping forever is only an intermediate safety result. Preserve speed and clearance constraints.

## 5. Major — City is a separate behavior scope despite shared field dimensions

**Dimension:** Contrarian / YAGNI & Code Minimization.

**Target:** initial brief lines 9–11, 37, 45, 56, 65, 85, 105.

**Evidence:** `/home/lev/IJKbot/docs/GOROD.md:51–54` explicitly describes operator navigation and stop timing. `/home/lev/IJKbot/src/bringup/launch/city.launch.py:18–34` launches recognition and preview; `/home/lev/IJKbot/src/vision/vision/city_sign_node.py:113–132` publishes candidate and confirmed signs. This establishes reusable recognition outputs, not an autonomous City mission. Final scoring rules were not independently retrieved in this review.

**Inference/risk:** Similar field dimensions do not make Evacuation search/return behavior a City route controller. “Add route/sign/stop behavior” can consume the same integration time reserved for the primary discipline. Building a general multi-discipline mission framework now would compound that scope.

**Simpler options:** Reuse tested motion, localization and current sign outputs. Once applicable rules are confirmed, choose one explicit autonomous, score-bearing City slice and a capped effort budget; defer expanding it until the agreed Evacuation gate. Alternatively defer City entirely if shared field time is insufficient. Neither operator intervention nor a sign-recognition demonstration should be presumed score-bearing.

**Strongest objection:** Deferring City can leave attainable points unused. Resolve this with the actual scoring table and a short representative autonomous route trial, not equal engineering allocation by default.

**Concrete validation proposal:** Write a small table of City behavior, rule/scoring basis, available code, missing behavior and allowed test budget. Run the selected route with signs changing between trials and inspect turns/stops without operator goals. Count awarded-behavior evidence and consumed field hours before expanding scope.

## Read manifest

Exact absolute filesystem paths consulted are below. Persona, immutable target and both supplied standards were read in full. Project files were read in relevant excerpts or searched for symbols; their presence and documentation are not treated as proof of deployment. Directory inventories were limited to the repository's source, configuration, scripts and tests, plus root README/AGENTS discovery. No other review, mutable concepts brief, history or memory was read.

### Full required reads

- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/zoom_out.md`
- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/heilmeier-standard.md`
- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/zoom-out-standard.md`
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/initial_concepts_brief.md`

### Local source/context reads and content searches

- `/home/lev/IJKbot/AGENTS.md`
- `/home/lev/IJKbot/README.md`
- `/home/lev/IJKbot/config/ijk.yaml`
- `/home/lev/IJKbot/docs/GOROD.md`
- `/home/lev/IJKbot/src/brain/mission_sm.py`
- `/home/lev/IJKbot/src/brain/test_mission_sm.py`
- `/home/lev/IJKbot/src/nav2/config/nav2_params.yaml`
- `/home/lev/IJKbot/src/bringup/config/realsense_laserscan.yaml`
- `/home/lev/IJKbot/src/bringup/launch/realsense_laserscan.launch.py`
- `/home/lev/IJKbot/src/bringup/launch/robot.launch.py`
- `/home/lev/IJKbot/src/bringup/launch/laptop.launch.py`
- `/home/lev/IJKbot/src/bringup/launch/city.launch.py`
- `/home/lev/IJKbot/src/vision/README.md`
- `/home/lev/IJKbot/src/vision/config/qr_reader.yaml`
- `/home/lev/IJKbot/src/vision/launch/qr_reader.launch.py`
- `/home/lev/IJKbot/src/vision/vision/__init__.py` (included in directory content search)
- `/home/lev/IJKbot/src/vision/vision/csi_capture.py` (included in directory content search)
- `/home/lev/IJKbot/src/vision/vision/rpi_camera_node.py`
- `/home/lev/IJKbot/src/vision/vision/city_signs.py`
- `/home/lev/IJKbot/src/vision/vision/city_sign_node.py`
- `/home/lev/IJKbot/src/vision/vision/qr_decoder.py`
- `/home/lev/IJKbot/src/vision/vision/qr_reader_node.py`
- `/home/lev/IJKbot/src/vision_cpp/README.md`
- `/home/lev/IJKbot/src/vision_cpp/launch/rpi_qr.launch.py`
- `/home/lev/IJKbot/src/vision_cpp/src/qr_reader.cpp`

### External primary sources

- [Nav2 Jazzy Costmap 2D](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/costmap_2d/), opened to locate its obstacle-layer reference.
- [Nav2 Jazzy Obstacle Layer Parameters](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/costmap_2d/costmap_plugins/obstacle/), especially source-list and input-type sections (rendered lines 518–557). Search-result snippets from other domains were not used as evidence.

No camera minimum-range, Nano compatibility/performance, bridge capability, final-rule applicability or required trial-success percentage is asserted. Each remains a measurement or decision for the next stage.
