# IJKbot preparation for the RTK Cup final

* **Author:** traptron
* **Date:** 2026-11-15
* **Status:** Working hypothesis for user review. Goldfish reviews have not started. This is not an implementation plan or a verified readiness report.

## Overview

Prepare one robot for Evacuation and City before departure on 1 December 2026. The team's primary objective is the maximum available Evacuation score. City is secondary, with a useful points target still to be quantified against its applicable rules. The remaining calendar window is 16 days; actual engineering hours and field access hours are unknown.

The team has three people with ChatGPT Plus subscriptions. This establishes team size, but does not establish daily availability, division of skills, or guaranteed AI capacity. The university has a complete City field with the same field and cell dimensions as Evacuation. Evacuation-specific objects and bridge tests still need to be arranged.

The working hypothesis is to retain the navigation and external-laptop arrangement that has already earned points, add a tested path from camera depth to low-obstacle avoidance, and build the missing victim-search and mission-completion behavior. Hardware replacement remains an option when measurements show a specific need. It is not itself the objective.

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

### Candidate workstreams and their strongest objections

1. **Navigation and low obstacles.** Test a camera-depth obstacle input alongside the existing lidar. The camera's image visibility alone does not prove valid depth or successful obstacle insertion. The design must distinguish the floor and traversable bridge from cars and debris, and account for close-range and turning blind areas. Adding a sensor without verifying the full path to stopping/avoidance would repeat the previous failure.
2. **Victim search and QR.** Observe the actual toy figure/banner arrangement, locate a candidate, move to a safe viewing position, and decode and validate its QR. Detection, successful decoding, and mission acceptance must be observable separately. Finding a banner is a possible cue, not yet a substitute for victim confirmation. A detector working on unrelated human images would not establish performance on the competition prop.
3. **Mission completion and field tests.** Connect interpretation, search, approach, confirmation, QR handling, and return, with bounded retries and visible failure reasons. Reuse verified navigation in City while adding its own route/sign/stop behavior. The main objection is integration time: three independently functioning components do not prove a working mission.

Suggested ownership is one person per workstream, with shared integration tests. This is a proposal, not an assignment accepted by the team. Mechanical work and field setup must be included in available time.

### Evidence needed before claiming readiness

* Representative 4 cm cars are avoided or cause a safe stop when deliberately placed on a route; safe stopping alone is not full mission success.
* Tests include approach angles, turns, floor appearances, and bridge transitions relevant to the real field. Bridge traversal feasibility must also be checked mechanically.
* QR tests cover realistic banner size, camera height, viewing angle, lighting, and transmitted image quality. A successful desktop test is insufficient.
* Logs distinguish missing images, missing candidates, unreadable QR, delayed results, rejected mission results, and successful transitions. Save evidence images with timestamps.
* Complete missions run repeatedly with changed obstacle and target positions, within the applicable time limit, without intervention or contact. The required repetition count and acceptable success rate remain to be agreed.
* City has an explicit score-bearing behavior set and target. “Decent points” is not yet a measurable acceptance criterion.

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

No technical architecture has yet been accepted or formally rejected by the team.

* **Continue using only a narrow camera depth slice:** previous operation missed 4 cm cars; does not establish coverage of the required obstacle volume.
* **Lower the installed lidar:** reported bridge constraints make this unsuitable as an assumed fix; measure before deciding whether any mounting change helps.
* **Replace the Pi with the Nano:** available hardware, but no measured compute bottleneck or verified software compatibility case yet. Keep as an option for review rather than the default migration.
* **Use QR decoding as the sole victim-search signal:** resembles the existing coupling and makes an unreadable QR block progress. Whether a separate banner detector can provide sufficient evidence must be checked against judging requirements.
* **Add ultrasonic sensors:** available, but coverage, mounting, and failure behavior are unverified. Review their value as an additional stopping input rather than assuming they solve mapping and navigation.
* **Develop both disciplines to equal scope immediately:** conflicts with the team's explicit priority of maximum Evacuation performance. City scope should share tested capabilities and have a separately chosen points target.

## Key Decisions & Staging for Next Steps

### Established constraints

* Departure: 1 December 2026.
* Priority: maximum Evacuation score; City secondary.
* Team: three people; complete City field available.
* External laptop: permitted according to the team's direct competition experience.
* Repository safety constraints remain: mock hardware for development, motor command timeout protection, competition speed at most 0.25 m/s, no reduction below the required obstacle clearance, and no raw point clouds or uncompressed video over Wi-Fi.

### Next step, pending the EGM readiness gate

Run fresh-context Goldfish reviews of this hypothesis, challenge the hardware choices and time budget, and identify the smallest complete design that can satisfy the full Evacuation mission. Reviewers must distinguish team-confirmed facts, repository evidence, proposals, and missing measurements. No Goldfish reviews have been run yet.

### Open items for review and subsequent measurements

* Team availability and daily access to the robot and field.
* Actual deployed software, present camera(s), lidar model/mount, wheel/chassis condition, power capacity, and compute load.
* Final rules and a numerical City target; retain the confirmed external-laptop permission.
* Actual QR sample/size and figure appearance; availability of equivalent props for tests.
* Exact bridge geometry, approach slope, and the mechanical reason for the lidar height restriction.
* End-to-end obstacle response time, safe viewing distance, and minimum detectable obstacle coverage.
* Root cause of QR failure in a full mission, established from recorded inputs and events.
* Acceptance thresholds, a deadline for stopping major changes, and a known-working fallback configuration.
