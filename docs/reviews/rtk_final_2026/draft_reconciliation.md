# Predecessor reconciliation for the RTK final design

**Date:** 2026-11-16. **Author:** traptron (comparison recorded by drafting assistant).

**Predecessor:** [concepts_brief.md](../../concepts_brief.md). **Target:** [design_draft.md](../../design_draft.md).

This is the drafting agent's required comparison with the predecessor, not an independent Goldfish review, implementation test or grading against the Zoom Out standard.

## Contradictions requiring an author decision

None detected after applying the predecessor's latest explicit decisions and the subsequent recorded author choices. No question remains where the draft silently reverses an established predecessor decision.

The predecessor retains older generic caution against making migration or a new detector mandatory without evidence, but its later explicit platform decision states that the team selected original Jetson Nano. The draft preserves that selected target and the unverified compatibility/capacity gates. It does not treat the older Pi-first recommendation as the active platform decision or claim the Pi was benchmarked insufficient.

## Architectural/interface/dependency refinements

These questions were raised or explicitly left to later design in the predecessor. The drafting conversation resolved them through author selections; they are not unapproved additions.

| Predecessor anchor | Draft refinement and author choice | Reconciliation |
| --- | --- | --- |
| "Identify one final motion-protection responsibility" | T1-A: Collision Monitor after arbitration/permission and before motor driver | Specifies the requested boundary; preserves lease, emergency and driver timeout |
| "camera-depth hazard input" and "preserving lidar consumers" | T2-A: filtered local 3D points to Voxel Layer and monitor | Does not replace roof lidar or authorize raw-cloud Wi-Fi traffic |
| "design must distinguish the floor and traversable bridge from cars" | T7-A: connected local support from current depth | Refines an explicitly open filter choice; keeps actual coverage/tilt/mechanical tests |
| "Exact message formats belong to the later design" | T3-B/T9-B: generated common typed observation with kind and validated payload | Implements explicitly deferred correlation/schema work; new interface package is a recorded author choice |
| "enough context to relate acquisition, decoding, publication and acceptance" | T12-A: one JPEG/capture-identity envelope | Refines capture association through an author-selected interface; retains source-provenance proof and bounded JPEG traffic |
| "bounded retries" and "safe viewing position" | T4-A: finite attempts at different safe poses; T8-B: surveyed pose catalogue with bearing | Preserves bounded timing and avoids an unapproved target-depth fallback; nearest-cell proof remains required |
| "build the missing victim-search" and compare actual toy evidence | T5-A/T10-A/T11-A: adapt YOLO11n, native PyTorch on laptop | Author-selected model/runtime detail; training/data/resource requirements remain unmet evidence outputs |
| "City is secondary" and "separately chosen points target" | T6-B: bounded autonomous action subset, exact actions deferred because rules are unavailable | Does not invent scores, promise full City or replace the primary Evacuation objective |

The new package, model dependencies and capture message are material implementation refinements. Their mechanisms and costs were presented and selected in the author gates. Exact physical values and actual compatible library versions were not selected by pretending to have measurements.

## Preserved constraints and practical limits

| Predecessor constraint | Draft treatment |
| --- | --- |
| Departure 1 December, three people, reported 2–3 hours/day | Same calendar/capacity assumptions; no multiplication of one robot's hours by three |
| Nano expected during 16–22 November with no fixed access day | Compatibility/device work waits for actual access; Pi installation preserved as a reference |
| External laptop officially permitted according to team | Accepted without reopening onboard-LLM permission; heavy perception/LLM remain on laptop |
| Full Evacuation result, distinct scoring stages | Separate victim/QR/hold/return evidence and truthful incomplete terminal outcomes |
| Cars about 4 cm, QR estimated 5 cm, banner 10–15 cm high | Representative measurements required; size estimates are not promoted to confirmed camera specifications |
| Safety and network constraints | Mock motors, timeout/braking, speed/clearance, local raw data and bounded JPEG/evidence retained |
| Proposed five consecutive full-run engineering milestone | Same milestone and explicit limits; not a statistical or competition-score guarantee |
| Proposed large-change cutoff/final validation reserve | Kept conditional on actual access/progress, without claiming feasibility of the full scope in 30 hours |
| Native QR, recorder and telemetry reuse | Selected reader and existing facilities extended rather than a generic navigation/UI rewrite |

The three-field Pydantic LLM response follows the supplied repository instruction. The predecessor did not authorize the checkout's fourth wire field; the draft identifies and tests the compliance change rather than presenting that field as a new approved interface. Internal diagnostic metadata remains separate.

## Approval and handoff state

The author approved the opening, Technical Plan, Alternatives Considered and phased Detailed Implementation sections in sequence. All twelve recorded decision gates are present. No independent design review has run; the seven earlier Goldfish reviews targeted the initial concept snapshot and must not be represented as reviews of this expanded design.

The author selected the standard destination in chat ("стандартно"). The design is saved at [docs/designs/rtk_final_2026.md](../../designs/rtk_final_2026.md). The authoring copy remains at `design_draft.md`; saved-document relative links were rebased and checked. No design sitemap existed, so no sitemap entry was required. No source/config changes, builds, hardware motion, installation or deployment were performed by drafting/finalization. Independent design review is the next recommended step.
