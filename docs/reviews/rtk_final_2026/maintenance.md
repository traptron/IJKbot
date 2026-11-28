# Maintainability brainstorm review

**Reviewer:** egm-structural / maintenance_review. **Mode:** BRAINSTORM. **Status:** completed, 2026-11-16.

Faithful condensed record of the independent returned report, saved by the primary agent. No blockers found; three concept boundaries need agreement.

1. **Major — One owner for mission transitions.** Search handlers and the QR callback in `src/brain/mission_sm.py` both change state and scoring flags; QR detection also sets `victim_detected`. Perception should report observations, with one mission transition owner deciding acceptance, motion and stage evidence. Agree observation time/view association and separate candidate, victim and QR results. Keep rejected observations visible. Counterargument: centralization could consume the deadline; limit changes to affected transitions and a small contract. Validate delayed previous-view QR, duplicate QR, candidate without readable QR and QR without confirmed victim, checking for unintended motion or success flags.
2. **Major — Own the whole obstacle capability.** Sensor, transform/filter, consumer and motion response span camera launch, scan YAML, Nav2 and camera selection. Assign one owner and deliver one reproducible configuration with mount/calibration identity and compute placement. Keep obstacle perception independent of discipline semantics and preserve Wi-Fi limits. Counterargument: configuration unification can become a project; recording existing files and launch choices is sufficient. Validate a clean restart, obstacle input and response, then repeat after discipline switching using actual deployed parameters.
3. **Major — Share navigation, keep discipline behavior separate.** City launch provides sign recognition; Evacuation launch and state machine include different search/hold/return behavior. Avoid coupling City branches into the primary mission or building a general mission framework before departure. Reuse navigation and safety interfaces with explicit startup selection. Counterargument: separate scenarios duplicate sequencing; limited duplication is acceptable to protect tested behavior. Validate City, documented switch, and frozen Evacuation regression without manual configuration repair or simultaneous motion commanders.

## Actual-read manifest

Full required reads: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/structural.md`; `resources/document_standards/heilmeier-standard.md` and `zoom-out-standard.md` under the same EGM root; `/home/lev/IJKbot/docs/reviews/rtk_final_2026/initial_concepts_brief.md`.

Full checkout reads, rooted at `/home/lev/IJKbot`: `config/ijk.yaml`; `src/bringup/launch/realsense_laserscan.launch.py`; `src/bringup/config/realsense_laserscan.yaml`; `src/bringup/launch/city.launch.py`; `src/bringup/launch/laptop.launch.py`.

Focused excerpts: `src/brain/mission_sm.py` lines 400–486, 830–918, 1418–1466 and search/QR keyword matches; `src/brain/test_mission_sm.py` lines 1–100. Search-only: obstacle/frame parameters in `src/nav2/config/nav2_params.yaml`, launch references in `src/bringup/launch/system.launch.py`, inventories under brain/bringup/scripts/tests.

No required reads missing. No other reports, mutable brief, deployed robot, final rules or external documentation consulted. No builds, writes, installation or SSH. Checkout coupling and prospective risks do not establish the historical failure cause.
