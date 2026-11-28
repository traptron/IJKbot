# Migration and rollout brainstorm review

**Reviewer:** egm-implementation-readiness / migration_review. **Mode:** BRAINSTORM. **Status:** completed, 2026-11-16.

This is a faithful condensed record of the independent returned report, saved by the primary agent. No blocker to continued concept development was found. Findings are concept-level rollout requirements.

## Findings

1. **Major — Restore a reproducible deployed baseline.** The initial brief distinguishes checkout from deployment but does not identify a restorable version of the arrangement that earned points. Record Pi/laptop revisions, effective configurations, overrides, launch commands, calibration/TF, maps and mounting. Promote coordinated changes between stopped missions and choose a freeze date. A fallback that still misses cars retains explicit operating restrictions. Counterargument: documentation consumes field time; record only the actual runtime and physical dependencies. Validate by restoring the baseline and reproducing previously demonstrated behavior while recording unmet avoidance requirements.
2. **Major — Coordinate the changed meaning of victim and QR signals.** `mission_sm.py:1423–1464` accepts Boolean detections and raw QR text, with QR able to imply victim evidence. The launch defaults to the native reader and its existing String/Bool outputs. Adding a detector alone can leave this shortcut intact. Define the authority of each signal and update producer, consumer and displayed outcomes together; a narrow adapter is possible. Associate observations with the current mission/view and reject late results. Counterargument: schema redesign can cost more than detection; a clear semantic contract is required, new message types are optional. Validate victim-only, QR-only, combined, reset, late results and legacy producer cases. QR alone may confirm a victim only if final judging requirements expressly allow it.
3. **Major — Add depth without silently replacing lidar interfaces.** Costmaps and AMCL use `/scan`; camera depth uses `/depth/scan`; CSI is selected in the current configuration. Repointing `/scan` could affect other profiles and localization. Preserve lidar consumers and make the added depth path explicit, with mounting calibration recoverable. Support only a recorded baseline and one candidate to limit combinations. Depth loss must not silently allow known unsafe autonomous operation. Validate both configurations on the same free and obstructed routes, interrupt depth, and recheck affected TF/profiles and bridge traversal.

## Actual-read manifest

Fully read:

* `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/implementation_readiness.md`
* `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/heilmeier-standard.md`
* `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/zoom-out-standard.md`
* `/home/lev/IJKbot/docs/reviews/rtk_final_2026/initial_concepts_brief.md`
* `/home/lev/IJKbot/src/bringup/launch/realsense_laserscan.launch.py`
* `/home/lev/IJKbot/src/bringup/config/realsense_laserscan.yaml`
* `/home/lev/IJKbot/src/vision/config/qr_reader.yaml`
* `/home/lev/IJKbot/src/vision/launch/qr_reader.launch.py`
* `/home/lev/IJKbot/src/bringup/launch/laptop.launch.py`

Focused excerpts/search results: `/home/lev/IJKbot/config/ijk.yaml`, `src/nav2/config/nav2_params.yaml`, `src/brain/mission_sm.py`, `src/bringup/launch/robot.launch.py`, `src/vision/vision/qr_reader_node.py`, and `src/vision_cpp/src/*.cpp`, all relative paths rooted at `/home/lev/IJKbot`. Relevant file inventories inspected. Exploratory `src/vision/qr_detector.py` did not exist; actual reader files were located instead.

All required reads completed. No other reports, mutable brief, deployed robot, external technical sources, builds or remote sessions were accessed. No source edits occurred. Findings concern checkout evidence and conditional rollout risks.
