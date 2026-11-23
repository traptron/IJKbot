Stage 5 Initial Zoom Out review — REVIEW mode

Target: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, lines 1–834.

Assessment: The objective and motivation are clear. The design addresses the observed integration failures, preserves truthful partial outcomes, reuses navigation and QR components, and avoids an unnecessary UI or general mission-framework rewrite. Two Major design issues need revision. No Blocker was established.

Author approval and previous reviews were treated as historical context, not evidence that this design is correct or feasible.

ZO-01 — Major — Shared validation is placed above its perception consumers

Affected target:
- Step 5, line 680: `src/brain/observation_contract.py` is to contain validation/deduplication helpers “shared by perception and coordinator.”
- Step 10, lines 775–778: the Python perception producer and backend belong to `vision`.
- Step 11, lines 792–793: package dependencies are updated without resolving this ownership problem.

Local source evidence:
- `src/brain/package.xml:17` already declares an execution dependency on `vision`.
- `src/vision/package.xml:12–20` contains vision, image and launch dependencies; it has no dependency on `brain`.
- `src/brain/setup.py` describes and installs the mission/LLM/dashboard package; `src/vision/setup.py` installs the perception nodes.
- Searches across `src`, `tools` and `tests` found no existing shared observation-contract implementation or current vision import from brain.

Finding status: Confirmed architectural inconsistency in the proposed ownership. A package dependency cycle is a conditional consequence if “shared by perception” is implemented by importing the helper from `brain` into the proposed `vision` node and declaring that dependency. Leaving the dependency undeclared instead creates an installation-dependent import failure.

Impact: A perception producer would depend on the mission package that already depends on perception. This couples producer deployment to mission internals, complicates package installation, and weakens the intended separation between observations and mission decisions. It also invites shared code to mix producer field validation with coordinator-only freshness, acceptance and deduplication rules.

Simplicity rationale: Reusing code should not invert the existing dependency direction. The design already introduces a common generated interface; it does not need a new reverse dependency to share all validation behavior.

Actionable remedy: Separate generic payload validation from mission acceptance. Place any genuinely shared Python payload checks in an existing lower-level package, such as `vision`, which `brain` already consumes. Keep current-attempt eligibility, acceptance and mission deduplication in `brain`. Alternatively, keep producer checks local and share cross-language contract fixtures rather than runtime mission helpers. State the final dependency direction explicitly without adding another package merely to solve this placement mistake.

Verification criterion: The declared package graph remains acyclic. The victim producer can import and start without installing the mission/dashboard package. Coordinator-only state checks remain in `brain`, and common fixtures demonstrate consistent producer/consumer payload semantics.

ZO-02 — Major — The evidence gate requires results from capabilities that it also prevents starting

Affected target:
- Ordered-work-list rule, line 628: Steps 1–4 are evidence preparation; later tasks may start only after their listed prerequisites.
- Step 4, lines 658–660: establish the segmentation choice and measure the workload including ground/hazard processing, end-to-end response, and values fixing filter, zone, retry and return settings.
- Step 7, lines 710 and 724: creating depth/support processing requires Steps 1–4; Step 4 must already output the segmentation operation and parameter evidence.
- Step 8, line 728: creating the final protection path requires Step 7 and a measured stopping/coverage envelope.
- Lines 822–824 distinguish mock implementation from real-motion acceptance, but do not reconcile the earlier ordering.

Local source evidence:
- Searches across `src`, `tools` and `tests` found no implemented `depth_hazard`, connected support-surface pipeline, Voxel Layer configuration, or Collision Monitor integration.
- `src/vision_cpp/CMakeLists.txt:17–33` builds existing camera/QR components, not the proposed hazard pipeline.
- `src/bringup/launch/realsense_laserscan.launch.py` currently starts the RealSense wrapper and narrow-strip depth-to-scan conversion.
- `src/bringup/config/realsense_laserscan.yaml` sets `scan_height: 15`.
- `src/nav2/config/nav2_params.yaml:130–144,164–181` configures scan-based obstacle layers.
- Existing command forwarding is in `src/bringup/scripts/robot_monitor.py:56–61,87–101`; it does not contain the proposed hazard processing or final Collision Monitor chain.

Finding status: Confirmed inconsistency in the written phase dependencies; a conditional execution risk rather than proof that the algorithms cannot work. A small experimental implementation could resolve it, but no such implementation path is identified between the evidence task and the gated production tasks.

Impact: An implementer must either wait for measurements that require the proposed software, create unlisted experimental software, or weaken the prerequisite informally. This obscures when the first useful integrated candidate becomes runnable and makes the limited preparation budget harder to control.

Simplicity rationale: A staged design should expose a short, executable progression from existing components to a tested candidate. Requiring near-final evidence before constructing the capability that produces it creates process complexity without improving the real-motion gate.

Actionable remedy: Split Step 4 into preliminary feasibility evidence and later acceptance evidence. Explicitly allow bounded replay/mock implementations of Steps 7–8 using labelled experimental values after compatibility and recording prerequisites pass. Then require full-workload measurements and the accepted profile before real-mode readiness. Identify where filter, protection and mission timing values are first estimated and where they become validated; retain the final fail-closed gate.

Verification criterion: Following the dependency list yields an acyclic sequence in which every required measurement has an available implementation or named experiment. A teammate can identify the first executable replay/mock candidate and the later physical acceptance gate without inventing work or bypassing prerequisites.

Other conclusions

- The root problem is addressed directly: sensing, motion protection, capture correlation and mission acceptance are treated as an integrated path.
- Existing native QR work scheduling and decoding are credible reuse candidates. The inspected reader already uses bounded pending work and a background worker.
- Existing recorder reuse is appropriate, but its current topic list is limited; the design correctly requires an extension rather than assuming complete evidence already exists.
- No equivalent implementation of the proposed toy detector, connected-support processor or correlated observation interfaces was found in the searched code. Their absence does not prove that the selected approaches are feasible.
- The Nano platform decision is an explicit constraint. This review does not reopen it based on speculation. Compatibility and performance remain unverified, as the design states.
- City deferral is reasonable given the missing final action/scoring definition.
- The detailed message schema belongs in the Detailed Implementation section. I did not classify necessary wire-contract detail there as an altitude violation.

Actual-read manifest

Required files, read completely:
- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/zoom_out.md`
- `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/zoom-out-standard.md`
- `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, all 834 lines, using overlapping reads
- `/home/lev/IJKbot/concepts_brief.md`, all 188 lines
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/goldfish_review_report.md`, all 78 lines
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/draft_reconciliation.md`, all 52 lines
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/platform_decision.md`, all 43 lines
- `/home/lev/IJKbot/docs/GOROD.md`, all 54 lines

Additional source reads:
- `/home/lev/IJKbot/README.md`, lines 1–155
- `/home/lev/IJKbot/src/brain/package.xml`, complete
- `/home/lev/IJKbot/src/brain/setup.py`, complete
- `/home/lev/IJKbot/src/vision/package.xml`, complete
- `/home/lev/IJKbot/src/vision/setup.py`, complete
- `/home/lev/IJKbot/src/vision_cpp/CMakeLists.txt`, complete
- `/home/lev/IJKbot/src/vision_cpp/include/vision_cpp/qr.hpp`, complete
- `/home/lev/IJKbot/src/vision_cpp/src/qr_reader.cpp`, lines 1–210
- `/home/lev/IJKbot/src/vision_cpp/src/camera_node.cpp`, initial constructor/capture excerpts
- `/home/lev/IJKbot/src/bringup/launch/realsense_laserscan.launch.py`, complete
- `/home/lev/IJKbot/src/bringup/config/realsense_laserscan.yaml`, complete
- `/home/lev/IJKbot/src/nav2/config/nav2_params.yaml`, lines 90–238
- `/home/lev/IJKbot/src/bringup/scripts/robot_monitor.py`, lines 40–113
- `/home/lev/IJKbot/src/brain/llm_client.py`, lines 201–299
- `/home/lev/IJKbot/tools/ijk/runner.py`, recording method, lines 153–168

Code-search evidence:
- Enumerated source, script, configuration and test files with `rg --files`.
- Searched `src`, `tools` and `tests` for capture/session identities, proposed observation types, support-surface processing, depth hazards, Voxel Layer, Collision Monitor, detector, Pydantic and hold-cell helpers.
- Searched existing launch files for `cmd_vel`, arbitration, smoothing and monitor wiring.
- Searched recorder, competition profile, QR transport and LLM files for their relevant entry points and reuse surfaces.

Inaccessible files: None among required files. Some combined tool output was truncated; required document/context reads were completed through smaller subsequent reads.

Limits: Read-only and local-only review. No files written, builds or tests run, robot/network commands issued, external URLs opened, chat history retrieved, or agents spawned.
