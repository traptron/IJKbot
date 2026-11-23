# Inventive catalyst brainstorm review

**Reviewer:** egm-inventive-catalyst / inventive_review. **Mode:** BRAINSTORM. **Status:** completed, 2026-11-16.

Faithful condensed record of the independent returned report, saved by the primary agent. No false compromise detected in the hardware/computation stance: migration, mounting and added sensors already depend on measurements.

1. **Major — Separate victim evidence from QR readability (Segmentation).** Local `mission_sm.py:969–970,1046–1047,1457–1458` couples victim flags to decoding. Candidate location, victim confirmation and QR information should be separate observations. Banner detection can guide search; it does not automatically confirm the figure. Reuse decoder and evidence images. Secondary cost: association/acceptance logic and possibly another confirmation method. Strongest objection: a separate detector may be unnecessary if final judges accept another signal; confirm before committing to it. Validate figure/readable banner, figure/unreadable banner, banner only, neither. Ideal result: an observation advances only the stage it proves, without erasing other evidence.
2. **Nit / advisory — Add the missing hazard evidence (Extraction).** Local files demonstrate separate `/scan` and `/depth/scan` with no established depth-to-obstacle path. Retain lidar/navigation duties and evaluate a robot-local depth-to-hazard path feeding navigation or stopping. Secondary costs: compute, calibration, health handling and conflicting observations; floor/bridge rejection remains unresolved. Strongest objection: software separation cannot repair an unobserved collision region. Validate coverage, derived hazards, consumer response and actual motion for cars, turns and bridge transitions. Ideal result: supply missing collision evidence while retaining working navigation and Wi-Fi restrictions.
3. **Major — Preserve view identity under bounded QR timing (Preliminary Action / Beforehand Cushioning).** Mission acceptance uses current phase; plain text and stamped images travel separately. Retained latest-JPEG processing also exists in an inspected preview script. This does not prove which view supplied a result. Preserve capture context to distinguish fresh/delayed/repeated results, and replay representative inputs before tuning dwell or hardware. Avoid queues of stale results. Secondary costs: context/trace changes; replay cannot reproduce all optics/motion/network conditions. Strongest objection: images may simply be unreadable; timing changes should follow evidence of delay/acceptance failure. Validate delayed, duplicate and stale results across scan steps and resets, then repeat physically. Ideal result: bounded search with every accepted result tied to its relevant observation.

## Actual-read manifest

Full required reads: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/inventive_catalyst.md`; `resources/document_standards/heilmeier-standard.md` and `zoom-out-standard.md` under the same EGM root; `/home/lev/IJKbot/docs/reviews/rtk_final_2026/initial_concepts_brief.md`.

Full checkout reads, rooted at `/home/lev/IJKbot`: `src/nav2/config/nav2_params.yaml`; `src/bringup/launch/realsense_laserscan.launch.py`; `src/bringup/config/realsense_laserscan.yaml`; `src/vision/vision/qr_reader_node.py`; `src/vision/config/qr_reader.yaml`.

Partial: `src/brain/mission_sm.py` lines 1–280, 930–1135, 1438–1476 plus keyword matches; `scripts/qr_ssh_preview.py` lines 1–135. Discovery-only keyword excerpts across bringup/vision/config/scripts.

No required reads missing. No mutable brief, other reports, deployment, hardware or final rules inspected. No writes/builds/install/SSH or external technical claims. Findings describe local evidence and testable hypotheses, not a historical diagnosis.
