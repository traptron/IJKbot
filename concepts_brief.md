# IJKbot preparation for the RTK Cup final

* **Author:** traptron
* **Date:** 2026-11-16 (initial hypothesis: 2026-11-15)
* **Status:** All seven independent Goldfish brainstorm reviews completed. Revised concept awaiting team alignment and measurements. This is not an implementation plan or a verified readiness report.
* **Review:** [Consolidated findings and reviewer status](docs/reviews/rtk_final_2026/goldfish_review_report.md). [Immutable initial hypothesis](docs/reviews/rtk_final_2026/initial_concepts_brief.md).
* **Latest platform decision, 2026-11-16:** The team selected its available original Jetson Nano DevKit as the target onboard computer. This supersedes the Pi-first recommendation in the independent review. Compatibility and sustained performance remain unverified. See [decision and live Pi inventory](docs/reviews/rtk_final_2026/platform_decision.md).
* **Hardware access update:** Jetson is not connected now. The team expects to obtain/connect it during the week of 16–22 November; no exact day is committed. Work requiring the board must be scheduled relative to actual access.

## Overview

Prepare one robot for Evacuation and City before departure on 1 December 2026. The team's primary objective is the maximum available Evacuation score. City is secondary, with a useful points target still to be quantified against its applicable rules. As of 16 November, the remaining calendar window is 15 days. The team reports 2–3 hours per day. For planning, interpret this conservatively as the shared daily robot/field window: approximately 30–45 hours if available every day through 30 November. Individual attendance and uninterrupted access are not yet established.

The team has three people with ChatGPT Plus subscriptions. This establishes team size, but does not establish division of skills or guaranteed AI capacity. Do not multiply shared robot time by three; individual parallel work depends on attendance and can use recordings and offline preparation. The university has a complete City field with the same field and cell dimensions as Evacuation. Evacuation-specific objects and bridge tests still need to be arranged.

The updated working hypothesis is to move the onboard role to the available Jetson Nano DevKit while retaining the external laptop for LLM and heavier perception. Reuse the navigation behavior and interfaces that have earned points, add a tested camera-depth path for low obstacles, and build the missing victim-search and mission-completion behavior. The platform is selected by the team, but its software deployment and capacity are not established. The full mission remains the objective.

## Analysis

### Confirmed by the team

* Previous Evacuation runs interpreted target cells and reached them. Victim detection was not implemented.
* QR reading sometimes worked outside the field through the web interface, but did not work during competition runs. The failing stage has not been identified.
* The robot hit toy cars about 4 cm high while following a Nav2 goal.
* At that time, the D435 was on the robot's second level and supplied only a narrow depth slice as a substitute for a lidar. A physical 2D lidar was installed later.
* The lidar is on the roof. The team reports that bridge clearance/traversal constraints prevent simply lowering it; the exact mechanical constraint needs measurement.
* Available equipment includes a Jetson Nano DevKit, D435 cameras, the installed 2D lidar, and ultrasonic sensors. Additional usable quantities and sensor models are not confirmed.
* External-laptop computation is officially permitted according to the team, which has already earned competition points using it. Do not reopen the onboard-LLM question solely because an older preparatory document says otherwise.
* The victim is a small toy person. A separate QR banner is approximately 10–15 cm above the floor and is not hidden by the figure.
* The QR square may be about 5 × 5 cm. This is an estimate, not a measurement.

### Evidence from the current checkout

These observations describe local files, not the exact software that ran during the failed attempts or the current deployed robot.

* `src/nav2/config/nav2_params.yaml` configures both obstacle layers to consume `/scan` only.
* `src/bringup/launch/realsense_laserscan.launch.py` sends the camera-derived scan to `/depth/scan`. It disables point-cloud output. `src/bringup/config/realsense_laserscan.yaml` uses a 15-row depth slice. Thus these files do not establish a working camera-depth obstacle input to Nav2.
* `config/ijk.yaml` names the lidar as `rplidar_a2m8`, but this has not been checked against its label. The same file selects a CSI camera, so the actual current camera and launch arrangement must be inventoried rather than inferred from the older description.
* `src/brain/mission_sm.py` includes a search sequence that looks for QR codes in several directions. Successful QR decoding can set both victim-found and QR-read flags. Result acceptance depends on the mission state and scan phase. These are investigation points, not a proven explanation of the previous failure.
* `docs/GOROD.md` describes sign recognition with navigation goals and stop timing still controlled by the operator. Full City mission behavior is therefore not established by that document.
* `docs/competition/Reglament.pdf` is the scanned on-site task for Izhevsk, 19–20 September 2026. It separates interpretation, victim finding, QR information, and return scoring; requires a stop of at least five seconds in the nearest cell; and does not require physical pickup. Its points total 500 before collision penalties. Applicability to the final remains to be confirmed; it is not a verified final regulation.
* That task does not specify that detecting a QR banner alone is sufficient evidence of finding the victim. Do not silently equate these events.
* Independent reviewers identified direct search turns through `/cmd_vel_sm` (`mission_sm.py:1013,1489`). The inspected web-control guard and driver watchdog do not themselves establish obstacle checking for that motion path. Improving Nav2 costmaps alone does not demonstrate protected search turns.
* Search exhaustion and the mission timeout can return home; reaching home calls a handler that unconditionally marks successful evacuation (`mission_sm.py:850,906,1082,1121`). Existing completion flags cannot be used as the acceptance test without correcting their meaning.
* The checkout has native and Python QR paths, with materially different standalone and mission launch settings. Identify the active implementation, image source, resolution, confirmation mode and lifecycle before changing the decoder or computer. Plain QR text and separately stamped images do not establish which viewing attempt produced an accepted result.

### Revised architecture hypothesis after review

The independent review initially recommended the Pi, laptop and lidar as the first candidate. The team subsequently selected the available Jetson Nano DevKit for the onboard role. Plan the candidate around Nano plus the external laptop and installed lidar. Add a robot-local camera-depth hazard input through existing navigation/stopping interfaces, preserving lidar consumers and Wi-Fi limits. Select mounting and filtering after demonstrating valid low-obstacle measurements, correct floor/bridge treatment and timely motion response. Confirm the exact board and a working software route before choosing image or ROS migration instructions.

**Compute and migration feasibility gate:** The competition profile currently places the base stack and Nav2 on the Pi, with QR/dashboard on the laptop. Target placement keeps LLM, toy/sign detection, QR decoding and UI on the laptop; Jetson handles devices, odometry/TF, command protection, navigation and bounded local depth-hazard computation. GPU availability is not evidence that every ROS node or depth operation is accelerated. A full dense, colorized point cloud with unrestricted filters is not the assumed implementation. Depth processing must preserve 4 cm objects; reducing samples is acceptable only after coverage is verified. Do not add every available camera/filter or move all inference onboard solely because the board has a GPU.

Before migrating motors or changing the working robot installation, verify the Jetson's model/RAM, installed OS/JetPack, storage, power/cooling and a documented deployment route compatible with the needed ROS nodes and device SDKs. Do not assume an Ubuntu 24.04 container on an older JetPack host automatically establishes GPU, USB or driver compatibility, or that different ROS distributions will interoperate correctly without testing. These are design decisions to resolve, not approved install instructions.

Once that route starts, run a proposed 15–20-minute incremental workload experiment: baseline devices/navigation, then RealSense capture, then the selected depth-hazard path, then preview/recording and laptop perception traffic. Measure each process and full-system per-core CPU, available memory/swap, temperature/frequency/throttling, USB/capture drops, sensor age, TF/odometry continuity, control deadline misses and observation-to-final-command delay. The configured controller is 10 Hz and local costmap 5 Hz; meeting them alone does not prove collision safety. Validate measured stopping distance against coverage with the full intended workload and stop-on-stale behavior. Use mock/replay or immobilized hardware first, then controlled motion tests.

D435 computes stereo depth in its own D4 processor; host-side filtering, projection, message handling and navigation still consume resources. This helps justify the candidate but is not a benchmark. Official basis: [RealSense onboard depth processing](https://www.realsenseai.com/stereo-depth-cameras/). Thermal throttling is another capacity variable; [Raspberry Pi documentation](https://www.raspberrypi.com/documentation/computers/config_txt.html) describes Arm throttling at high temperature. Actual Pi RAM, cooling, power condition and deployed load remain unknown.

If compatibility or sustained-load tests fail, record the exact failed boundary and decide the next bounded remedy with the team. The selected Nano is not presumed sufficient merely because it is available. Preserve the Pi installation as a recoverable reference; it is not automatically a safe competition fallback. Moving Nav2 to the laptop is another possible arrangement requiring network-delay/loss tests, with local stopping retained.

Obstacle protection must cover navigation, search turns, approach, recovery and return. Identify one final motion-protection responsibility and test missing/stale inputs; preserve the existing control guard, emergency stop and motor timeout. A common stopping stage is a candidate, not yet a selected implementation. Do not allow another motion publisher to bypass the selected protection.

Perception reports observations. One mission transition owner decides whether each observation is current and relevant and which stage it proves. Keep candidate location, victim confirmation, accepted QR, required location/dwell evidence, safe return and complete mission distinct. Banner detection can guide viewing; the final judging criteria determine whether it also supplies sufficient victim evidence. This decision may avoid unnecessary detector work, but must not be assumed.

Each QR attempt needs enough context to relate acquisition, decoding, publication and acceptance to the same run/view. Define bounded retries and keep rejection reasons visible. Diagnose unreadable inputs and late or rejected results before tuning dwell, replacing algorithms or moving computation. Exact message formats belong to the later design.

Reuse the existing native QR workers, recorder, telemetry and protocol where suitable. Every trial needs one configuration identity, selected image/event evidence and a truthful stage ledger, including failed or interrupted runs. Measure recording overhead and keep bulky depth recordings local. A saved failed trial should let a teammate identify the failing stage without reproducing the scene.

City should share navigation and safety interfaces, with its own bounded mission behavior and explicit startup selection. Avoid a general multi-discipline framework during this window. Switching disciplines must leave only one active mission commander and preserve the tested Evacuation setup.

The desired result is a complete run with observable evidence at every scoring stage, protected motion, and a repeatable operator procedure with few added components. Additional sensing costs compute and calibration; separated observations cost association logic; traceable trials cost storage and recording time. These costs remain smaller only if the team limits itself to one baseline and one candidate.

### Candidate workstreams and their strongest objections

1. **Navigation and low obstacles.** Test a camera-depth obstacle input alongside the existing lidar. The camera's image visibility alone does not prove valid depth or successful obstacle insertion. The design must distinguish the floor and traversable bridge from cars and debris, and account for close-range and turning blind areas. Adding a sensor without verifying the full path to stopping/avoidance would repeat the previous failure.
2. **Victim search and QR.** Observe the actual toy figure/banner arrangement, locate a candidate, move to a safe viewing position, and decode and validate its QR. Detection, successful decoding, and mission acceptance must be observable separately. Finding a banner is a possible cue, not yet a substitute for victim confirmation. A detector working on unrelated human images would not establish performance on the competition prop.
3. **Mission completion and field tests.** Connect interpretation, search, approach, confirmation, QR handling, and return, with bounded retries and visible failure reasons. Reuse verified navigation in City while adding its own route/sign/stop behavior. The main objection is integration time: three independently functioning components do not prove a working mission.

Suggested ownership is one person per workstream, with shared integration tests. This is a proposal, not an assignment accepted by the team. Mechanical work and field setup must be included in available time.

Name an integration owner for each shared field session. All three workstreams deliver into one runnable candidate and one common trial record; robot/field time cannot be allocated to conflicting tasks simultaneously. The first shared deliverable is a recorded complete attempt with representative props, which also supplies inputs for parallel offline analysis.

### Evidence needed before claiming readiness

* Representative 4 cm cars are avoided or cause a safe stop when deliberately placed on a route; safe stopping alone is not full mission success.
* Tests include approach angles, turns, floor appearances, and bridge transitions relevant to the real field. Bridge traversal feasibility must also be checked mechanically.
* QR tests cover realistic banner size, camera height, viewing angle, lighting, and transmitted image quality. A successful desktop test is insufficient.
* Logs distinguish missing images, missing candidates, unreadable QR, delayed results, rejected mission results, and successful transitions. Save evidence images with timestamps.
* Complete missions run repeatedly with changed obstacle and target positions, within the applicable time limit, without intervention or contact. The required repetition count and acceptable success rate remain to be agreed.
* City has an explicit score-bearing behavior set and target. “Decent points” is not yet a measurable acceptance criterion.

Proposed acceptance cases also include no victim; unreadable QR; banner without figure; late/duplicate QR across a turn or reset; missing depth; timeout return; and a second mission in the same session. A return after search failure must retain its incomplete outcome. The required five-second hold needs location and observed stillness evidence, not just an elapsed timer while commanding zero.

Proposed practical final gate: five consecutive complete Evacuation trials with changed target/obstacle positions, no contact or intervention, within the applicable mission time. After a failed run, diagnose and fix it before starting a new series. This is an engineering milestone for team discussion, not statistical proof or a guarantee of competition points. Choose the City gate after confirming its score-bearing actions.

### Operator procedure and decision ownership

Use a one-page run card with existing controls: select the recorded configuration and discipline; verify sensor/control readiness; enter the task; start; observe stage/time; record completion or named failure; stop if required; reset into a new attempt. Distinguish preparation, autonomous execution and any intervention. A teammate should rehearse this without coaching.

For each hardware or algorithm change, record the observed limitation, smallest discriminating experiment, expected integration effort, decision owner, decision deadline and restoration target. Capture actual deployed revisions, effective parameters/overrides, calibration/TF, maps, camera modes and mounting. Promote coordinated Pi/laptop changes between stopped missions. A restored baseline that misses low obstacles carries explicit operating restrictions and is not automatically a safe competition fallback.

## Goals vs. Non-Goals

### In-Scope Goals

* Target all Evacuation scoring stages, with collision avoidance and a visible record of mission events.
* Address low obstacles and the missing victim-search behavior.
* Make QR reading work within the actual mission rather than only as an isolated demonstration.
* Select a City scope that can be tested on the university field without jeopardizing Evacuation readiness.
* Consider sensor mounting, wiring, power, computing placement, and software changes where evidence supports them.
* Reserve time for repeated field trials before departure.

### Out-of-Scope Non-Goals for This Brainstorm

* Implementing or deploying code before the concept is agreed.
* Treating a Jetson migration, a new detector, or a complete chassis rebuild as mandatory without showing the need.
* Treating a physical victim gripper as necessary under the available Izhevsk task; revisit only if the final requires it.
* Guaranteeing maximum points before full mission trials.

## Alternatives Weighed

The team selected Jetson Nano as the onboard target after review. The rest of the architecture remains a proposal pending alignment and measurements. The alternatives below preserve the reasoning at review time; the Pi-first preference was superseded by the team's decision, not disproved by a benchmark.

* **Continue using only a narrow camera depth slice:** previous operation missed 4 cm cars; does not establish coverage of the required obstacle volume.
* **Lower the installed lidar:** reported bridge constraints make this unsuitable as an assumed fix; measure before deciding whether any mounting change helps.
* **Replace the Pi with the Nano:** selected by the team after review because it is available and the team wants to plan around it. Include migration work in the baseline schedule. No measured workload or compatibility result yet establishes success; do not describe this as a guaranteed performance improvement.
* **Use QR decoding as the sole victim-search signal:** resembles the existing coupling and makes an unreadable QR block progress. Whether a separate banner detector can provide sufficient evidence must be checked against judging requirements.
* **Add ultrasonic sensors:** available, but coverage, mounting, and failure behavior are unverified. Review their value as an additional stopping input rather than assuming they solve mapping and navigation.
* **Develop both disciplines to equal scope immediately:** conflicts with the team's explicit priority of maximum Evacuation performance. City scope should share tested capabilities and have a separately chosen points target.

Review recommendations, not team rejections: prefer existing Nav2 sensor inputs and a measured common motion-protection boundary over a custom navigation rewrite; reuse a selected existing QR path before replacing it; accept a small amount of separate City sequencing over a generic mission framework. Each adds integration obligations and must pass its own tests.

The original Nano's official JetPack branch uses an Ubuntu 18.04-based filesystem, while Jazzy's Ubuntu packages target 24.04. This is a verified compatibility risk, not a claim of impossibility or measured lack of performance. See [official-source checks and links](docs/reviews/rtk_final_2026/source_checks.md). An additional board is justified only by a workload and deployment proof that fits the remaining time.

## Key Decisions & Staging for Next Steps

### Established constraints

* Departure: 1 December 2026.
* Priority: maximum Evacuation score; City secondary.
* Team: three people; complete City field available.
* Availability reported after review: 2–3 hours per day. Plan against 30 shared hours, using additional time up to 45 hours for recovery and verification rather than committing it to extra features. This assumes daily access from 16–30 November and is not a measurement of attendance or person-hours.
* External laptop: permitted according to the team's direct competition experience.
* Onboard target: original Jetson Nano DevKit, selected by the team on 16 November. Exact unit configuration, software route and performance remain to be checked. Keep the existing Pi installation recoverable during preparation.
* Repository safety constraints remain: mock hardware for development, motor command timeout protection, competition speed at most 0.25 m/s, no reduction below the required obstacle clearance, and no raw point clouds or uncompressed video over Wi-Fi.

### Completed review and proposed staging

All seven independent lenses completed against the immutable initial hypothesis. The consolidated review records statuses, required reads, isolated dispatch, evidence, disagreements and proposed tests. It reports no blocker to continued concept discussion; the major findings require measurements and design decisions before claiming readiness. No implementation or robot trial was performed.

Proposed dates below use the conservative two-hour daily window. They are not accepted commitments or a guarantee that missing functions fit. The first experiments must determine feasibility:

**Access dependency:** The subsequent update that Jetson will arrive during this week supersedes any assumption that migration can start on 16 November. The dates below remain target checkpoints, not a schedule proven feasible with late delivery. If the board becomes available only on 22 November, only 23–30 November provides eight full subsequent daily windows, approximately 16–24 hours. Preparation before delivery is therefore essential.

| Phase | Proposed team preparation and evidence |
| --- | --- |
| Before Jetson access | Person A documents real sensor/mount/bridge geometry and prepares equivalent 4 cm obstacles; person B collects representative QR/figure images and a reproducible failing QR attempt using the current system; person C records the actual launch/configuration and maps stage outcomes, motion sources and final-rule questions. These are proposed roles, not assignments to named members. Use the existing Pi only for authorized evidence collection and safe trials |
| First Jetson session | Inspect exact model/RAM, installed OS/JetPack and storage/power/cooling; choose and demonstrate the ROS/device deployment route with mock motors before migration. Preserve the Pi installation |
| Subsequent Jetson session | Demonstrate actual lidar/camera input and mock odometry/control integration; measure depth processing with the intended workload before controlled physical motion |
| Integration sessions | Apply the agreed mission changes and test the complete sequence and stopping envelope. Full-run milestones depend on demonstrated compatibility; a calendar entry is not a pass |

Proposed schedule checkpoint: if Jetson access or a viable software route is still unavailable on 20 November, explicitly reassess the remaining migration scope and City allocation. The team-selected Nano remains the target unless the team changes that decision. Do not silently count waiting time as completed migration or consume the final trial reserve.

| Dates / baseline hours | Milestone and decision |
| --- | --- |
| 16–18 November / 6 hours | Record deployed baseline; inspect and establish the selected Nano software route with mock devices first; obtain representative props/bridge measurements and capture current failure evidence. Migration shares this time budget and may require revising subsequent milestones if unresolved |
| 19–22 November / 8 hours | Demonstrate candidate protection across motion modes and first full Evacuation attempt; select necessary hardware changes from measurements |
| 23–25 November / 6 hours | Repeat full Evacuation trials; spend at most 3 of these hours on the selected City behavior and switch-back regression; proposed major-change freeze after 25 November |
| 26–30 November / 10 hours | Protect this time for timed full trials, measured fault fixes, operator reset/restart, configuration restoration and packing |

The three-hour City limit covers City-specific robot work within the baseline budget; shared navigation/safety improvements benefit both disciplines. Offline City preparation may proceed alongside other work when a teammate is available. This cap may be too small for a useful score: choose its exact behavior from the rules before implementation, and raise the conflict explicitly if it cannot fit. Do not imply that this budget guarantees the stated City objective.

Use the first 15–20 minutes of each session to restore the recorded setup and inspect readiness, the main period for one named change or discriminating experiment, and the final 20–30 minutes for an integrated attempt, saved evidence and next-session handoff. This overhead is included in the hours above. Two consecutive sessions without progress on a named failure trigger a bounded choice of another approach or a scope/schedule decision; they do not justify indefinite tuning.

If the first complete Evacuation attempt is not possible by 22 November, suspend additional City-specific work and optional migrations while diagnosing the missing stage. This protects the primary objective but makes the secondary objective uncertain. If actual attendance or access is lower, revise the milestones rather than silently consuming the final validation reserve.

Next, obtain team alignment on the revised scope, architecture boundaries and evidence gates, then prepare the detailed design through `egm-draft`. Record individual attendance and actual robot/field slots during the first session. Unresolved physical measurements should have named owners and early deadlines rather than invented values. Further review is useful after a material change in architecture or facts, not as a substitute for a field experiment.

### Open items for review and subsequent measurements

* Individual attendance and confirmation that reported 2–3 daily hours provide shared robot/field access on all planned days.
* Jetson unit/model/RAM, current JetPack/OS, compatible ROS/device SDK route, power/cooling and sustained load. Exact deployed software, camera(s), lidar mount and chassis remain to be inventoried. Pi was inspected read-only at `10.16.115.154`: Pi 4B Rev 1.2, approximately 4 GB RAM, Ubuntu 24.04.5 and installed Jazzy; this is not a workload benchmark.
* Final rules and a numerical City target; retain the confirmed external-laptop permission.
* Actual QR sample/size and figure appearance; availability of equivalent props for tests.
* Exact bridge geometry, approach slope, and the mechanical reason for the lidar height restriction.
* End-to-end obstacle response time, safe viewing distance, and minimum detectable obstacle coverage.
* Root cause of QR failure in a full mission, established from recorded inputs and events.
* Acceptance thresholds, a deadline for stopping major changes, and a known-working fallback configuration.
