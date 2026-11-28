# Architecture and Cost Brainstorm Review

**Status: Complete.** The hypothesis identifies the right objective and preserves the proven external-laptop arrangement. It is suitable for continued brainstorming, but five consequential decisions remain before an implementation design can be accepted. No workspace files were modified.

This review treats the two standards as concept-quality guides. Message schemas, exact algorithms, parameter values, and implementation decomposition can follow later. Responsibility for safe motion, evidence of mission success, resource allocation, and hardware selection criteria cannot.

## Read manifest

Every local file actually read:

1. `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/design_critic.md` — complete.
2. `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/heilmeier-standard.md` — complete.
3. `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/zoom-out-standard.md` — complete.
4. `/home/lev/IJKbot/docs/reviews/rtk_final_2026/initial_concepts_brief.md` — complete, lines 1–110.
5. `/home/lev/IJKbot/README.md` — lines 1–130.
6. `/home/lev/IJKbot/config/ijk.yaml` — complete.
7. `/home/lev/IJKbot/src/nav2/config/nav2_params.yaml` — lines 60–190, plus keyword-search matches.
8. `/home/lev/IJKbot/src/bringup/launch/realsense_laserscan.launch.py` — complete.
9. `/home/lev/IJKbot/src/bringup/config/realsense_laserscan.yaml` — complete.
10. `/home/lev/IJKbot/src/brain/mission_sm.py` — lines 830–1135, 1420–1467, 1480–1510, plus keyword-search matches. A truncated passage in the first output was retrieved separately at lines 892–915.

No other review reports, revised concepts brief, conversation history, deployed robot, or remote system was consulted.

## 1. Major — Low-obstacle protection must cover search motions as well as navigation

**Dimension:** Architecture and onboard resource allocation.  
**Target:** Lines 43, 51–52, 95, 108.

**Evidence:** The brief proposes a depth obstacle input alongside lidar and explicitly mentions turning blind areas. However, current search rotation calls `send_cmd_vel(0.0, speed)` directly. That method cancels an active navigation goal and publishes mission-state-machine velocity commands. Nav2 obstacle avoidance is therefore not the only motion path needing evaluation. See [search rotation](/home/lev/IJKbot/src/brain/mission_sm.py:1007) and [velocity publication](/home/lev/IJKbot/src/brain/mission_sm.py:1489).

**Inference:** Adding depth to Nav2 can improve goal following while leaving search rotation vulnerable. This inspection does not prove that the deployed system lacks another protective layer; it establishes that Nav2 integration alone is insufficient evidence.

**Required concept decision:** Assign collision protection and stale-sensor behavior to a clearly identified component covering every autonomous motion source, including search and approach. Keep the stopping path local to the robot unless an alternative has a measured, acceptable failure response. Preserve the network restriction on raw point clouds.

**Strongest objection:** A common motion-protection component may expand scope.  
**Mitigation:** First inspect and test existing protection. Reuse it where sufficient. If coverage is missing, choose the smallest shared protection mechanism; do not create a second navigation stack.

**Validation proposal:** Run low-car tests during goal following, stationary search turns, approach, and return. Inject missing/stale depth and network interruption. Record sensor timestamp, obstacle representation, commanded velocity, and actual stopping distance. At the maximum permitted speed, 300 ms of delay alone means 7.5 cm of travel before braking; this is an illustrative budget calculation, not a measured latency.

## 2. Major — Reusing mission completion currently risks reporting evacuation without victim evidence

**Dimension:** Architecture and score integrity.  
**Target:** Lines 36, 39, 44–45, 55, 62.

**Evidence:** Exhausting search locations without finding QR transitions to `RETURNING_HOME` at [lines 1082–1085](/home/lev/IJKbot/src/brain/mission_sm.py:1082). Any arrival home in that state invokes completion at [lines 906–908](/home/lev/IJKbot/src/brain/mission_sm.py:906). Completion unconditionally sets `evacuated_home = True` and logs successful evacuation at [lines 1121–1130](/home/lev/IJKbot/src/brain/mission_sm.py:1121). QR reception can also set both victim and QR success flags, as already recognized in the brief.

**Inference:** A full start-to-return demonstration could appear successful in local status while lacking the evidence needed for the intended scoring stages. This is an integration risk even if the physical navigation remains reliable.

**Required concept decision:** Distinguish “returned safely,” “victim confirmed,” “QR accepted,” and “scoring mission completed.” Define the evidence required for each claimed stage using the applicable final rules. Preserve partial progress without inventing successful stages.

**Strongest objection:** A human judge determines points, so internal flags are merely presentation.  
**Mitigation:** These flags and logs are also the team's verification instruments. Define a small outcome table now; defer the detailed state-machine redesign.

**Validation proposal:** Exercise four end-to-end cases: no victim, confirmed victim with unreadable QR, QR cue without a confirmed victim, and complete success. Arrival home must not automatically turn the first three into full success. Record both robot outcome and judge-observable evidence.

## 3. Major — The QR problem may be a timing and result-association problem, not only an optical problem

**Dimension:** Latency, concurrency, and compute budget.  
**Target:** Lines 20, 36, 44, 53–54, 109.

**Evidence:** The current scan procedure describes two seconds of settling and a one-second QR check window. Results are accepted according to the state and current scan phase. The QR callback accepts a nonempty text result without an explicit capture identifier or capture timestamp in that callback. See [scan procedure](/home/lev/IJKbot/src/brain/mission_sm.py:943) and [result acceptance](/home/lev/IJKbot/src/brain/mission_sm.py:1444).

**Inference:** A valid result arriving after its observation window could be rejected or associated with a later view. The code does not establish that either occurred in competition. Faster hardware or a new decoder might conceal the issue without correcting its cause.

**Required concept decision:** Treat each observation as a bounded transaction: the system must know which view produced a result, whether that result is still relevant, and when to retry or move on. Select observation deadlines from measured capture-to-acceptance latency. Detailed message fields can wait.

**Strongest objection:** The main failure may simply be insufficient QR pixels or poor exposure.  
**Mitigation:** Diagnose optical quality and timing together from the same recorded observations; do not commit to a detector replacement before separating these failure modes.

**Validation proposal:** For representative banners, record the captured image, transmission completion, decoder completion, and mission acceptance. Replay delayed results after a turn and after mission reset. Measure under concurrent navigation, dashboard, and inference load. Budget the actual local workload; ChatGPT Plus subscriptions do not establish robot inference capacity or API quotas.

## 4. Major — Three workstreams compete for one integration resource

**Dimension:** Headcount, field access, and deadline economics.  
**Target:** Lines 9–11, 45–47, 55–56, 65–67, 103, 110.

**Evidence:** Three people and 16 calendar days are known; working hours, skill coverage, and field access are not. The proposed split assigns navigation, perception, and mission integration to separate owners. Mechanical work and field preparation are acknowledged but unallocated.

**Inference:** A one-person-per-component split can keep all three people busy while leaving the complete mission untested. One robot, shared mounts, and common field sessions limit useful parallelism. Additional City behavior competes directly with Evacuation validation time.

**Required concept decision:** Allocate an integration owner and a daily shared test slot before treating component work as scheduled. Reserve a substantial final validation window and select an explicit date after which major hardware and architecture changes stop. City should receive a bounded allocation tied to an Evacuation milestone.

**Strongest objection:** Detailed scheduling is premature before technical measurements.  
**Mitigation:** Use a provisional capacity envelope now and revise it after the first evidence session. This is a resource commitment, not a task-by-task implementation plan.

**Validation proposal:** Establish available person-hours and robot-hours, then compare them with timeboxed investigations. A candidate staging proposal is: first two days for baseline, props, geometry, and failure diagnosis; a complete trial by the middle of the remaining window; final several days reserved for repeated missions and recovery rehearsal. Dates and duration need adjustment to actual availability.

## 5. Major — Hardware selection needs an early mechanical gate and an explicit evidence-to-change rule

**Dimension:** Hardware cost, integration effort, and replacement risk.  
**Target:** Lines 21–24, 43, 66, 80–84, 104–108.

**Evidence:** The robot has hit 4 cm objects, the roof lidar reportedly cannot simply be lowered, the current camera configuration is uncertain, and bridge geometry remains unmeasured. The repository's depth launch disables point-cloud output, while its scan configuration uses 15 rows. None of those facts establishes usable obstacle coverage on the present chassis.

**Inference:** Software selection can be invalidated by camera occlusion, close-range gaps, or bridge mechanics. Conversely, replacing a computer cannot repair an unobservable obstacle or an impassable bridge.

**Required concept decision:** Separate three gates: mechanical traversal, sensor observability, and processing capacity. Approve hardware changes against the failed gate. Do not use aggregate “performance” as the migration justification.

**Strongest objection:** Waiting for exhaustive measurements could consume the preparation window.  
**Mitigation:** Use a short physical evidence session with representative cars, banner, and bridge geometry. Seek disqualifying failures first. Retain a reversible mount and one known-working configuration.

**Validation proposal:** Measure the chassis and bridge, then test representative poses through the bridge transition and a search turn. Compare image visibility with valid depth and obstacle insertion. Only after this path works should CPU load and end-to-end delay determine whether additional computing hardware is useful.

## Options and costs

These are comparative cost drivers, not procurement quotes or delivery estimates.

| Option | Expected benefit | Principal cost and risk | Decision trigger |
|---|---|---|---|
| Retain Pi, external laptop, lidar; integrate measured camera-depth coverage locally | Reuses a point-scoring arrangement and existing hardware | Mounting, depth filtering, robot compute load, shared motion protection, field validation | Preferred baseline if geometry and latency tests pass |
| Retain compute; adjust/add camera coverage from available equipment | May close a demonstrated view gap | Brackets, wiring, power/USB demand, calibration and additional test cases | A measured coverage gap that mounting or another confirmed available camera resolves |
| Add ultrasonic stopping input | Potential complementary protection in a specific blind area | Unknown sensor suitability; mounting, wiring, false stops and mission delays | Repeatable detection of the actual missed obstacle with useful coverage |
| Replace Pi or add Nano | Candidate response to a measured processing bottleneck | Software compatibility investigation, power/wiring changes, deployment and regression time | Existing compute misses the measured deadline after bounded tuning; alternative passes representative workload |
| Broaden City immediately | Earlier City-specific capability | Direct displacement of Evacuation integration and test hours | Only with a quantified City scope and an explicit Evacuation readiness milestone |

No claim about Nano compatibility, sensor range, or guaranteed detection performance is made here. Those claims require verified model-specific primary documentation and measurements.

## Recommended concept gate

Accept the next concept iteration when it contains:

- A small architecture showing where sensing, stopping, navigation, perception, and mission decisions run, including every motion source.
- Separate evidence-based success conditions for each scoring stage and safe-return outcomes.
- A bounded QR observation and retry strategy justified by measured latency.
- A capacity allocation, integration milestone, change cutoff, and tested fallback.
- A hardware decision table tied to mechanical, observability, and compute measurements.

The strongest reusable foundation is the navigation and laptop arrangement that previously earned points. The highest-value new work is proving the missing complete chain—observation, safe motion, victim evidence, QR acceptance, and legitimate mission completion—under the actual time and field constraints.

**Sources:** All factual repository claims are linked above and scoped to the local checkout. The [initial brief](/home/lev/IJKbot/docs/reviews/rtk_final_2026/initial_concepts_brief.md), [Heilmeier standard](/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/heilmeier-standard.md), and [Zoom Out standard](/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/zoom-out-standard.md) define the review context. No deployed-state or final-regulation verification is claimed.
