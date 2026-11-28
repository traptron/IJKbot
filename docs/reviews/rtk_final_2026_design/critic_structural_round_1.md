Structural review — Stage 7, round 1

Result: No structural findings. No Blocker, Major or Nit findings were identified in the active scope.

Reviewed scope: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, lines 1–525, ending immediately before `## Detailed Implementation Plan` at line 526. Lines 526–680 were read only to clarify later contract details and avoid false missing-context findings; implementation content was not audited.

Standard compliance

The assigned feature-spec standard requires substantive coverage, rather than prescribed literal heading names. The document provides:

- Problem and motivation: Overview and The Problem, lines 10–34.
- Goals and exclusions: Goals and Non-Goals, lines 36–62.
- Component responsibilities, data flows and integration: Technical Plan, lines 102–418.
- Alternative evaluation: architecture option tables and thirteen explicit alternatives, lines 420–515. These identify concrete implementation, resource, coverage and scope trade-offs and distinguish deferred options from rejected options.
- Constraints, failure modes and mitigations: distributed through sensing, motion protection, observation acceptance, prerequisites and Non-Functional Requirements. Resource limits, bounded state, freshness, malformed input, evidence-path restrictions and credential handling are addressed. The standard does not require a separate heading named “Risks & Mitigations.”

Structure map

- H1, line 1: IJKbot preparation for the RTK Cup final
  - H2, line 10: Overview
  - H2, line 22: The Problem
  - H2, line 36: Goals
  - H2, line 53: Non-Goals
  - H2, line 64: Open Questions
  - H2, line 76: Critical User Journeys (CUJs)
    - H3, line 78: CUJ 1: Complete an Evacuation attempt
    - H3, line 84: CUJ 2: Detect a low obstacle during search or navigation
    - H3, line 90: CUJ 3: Explain a failed QR attempt and restart
    - H3, line 96: CUJ 4: Switch disciplines without changing the tested motion path
  - H2, line 102: Technical Plan (Architecture)
    - H3, line 104: Scope and decision state
    - H3, line 110: Deployment prerequisite
    - H3, line 116: Logical data and command paths
    - H3, line 154: Physical coverage and low-obstacle input
      - H4, line 164: T2 — Selected: filtered 3D obstacle points with Voxel Layer
      - H4, line 181: T7 — Selected: estimate connected support surfaces from current depth
    - H3, line 207: Motion ownership and protection invariant
      - H4, line 215: T1 — Selected: Nav2 Collision Monitor on the final command path
    - H3, line 230: Observation acceptance and mission outcomes
      - H4, line 234: T3 — Selected: project-specific typed ROS observation interfaces
      - H4, line 270: T4 — Selected: bounded QR retries from different safe viewpoints
      - H4, line 294: T5 — Selected: adapt a compact detector to representative toy victims
      - H4, line 320: T8 — Selected: known safe observation poses with visual bearing
    - H3, line 349: City, operation and trial records
      - H4, line 353: T6 — Selected: bounded autonomous City action set
    - H3, line 374: Existing components affected by this plan
    - H3, line 389: Approved architectural choices
    - H3, line 405: Prerequisites to close before implementation can be finalized
  - H2, line 420: Alternatives Considered
    - H3, line 426: 1. Retain Raspberry Pi as the primary onboard target
    - H3, line 433: 2. Continue using only a narrow depth strip or simply reconnect `/depth/scan`
    - H3, line 440: 3. Lower the roof lidar or rely on added ultrasonic sensors
    - H3, line 447: 4. Put obstacle geometry checks inside the existing onboard guard
    - H3, line 454: 5. Collapse ground-filtered depth into a planar obstacle scan
    - H3, line 461: 6. Carry versioned JSON observations in standard String messages
    - H3, line 468: 7. Use QR success as the sole victim-found signal
    - H3, line 475: 8. Recognize the toy using reference images instead of adapting a detector
    - H3, line 482: 9. Retry QR only from the initial stationary pose
    - H3, line 489: 10. Use a premeasured floor/bridge surface model as the main ground classifier
    - H3, line 496: 11. Localize detections with matched depth and generate new target-relative observation poses
    - H3, line 503: 12. Develop complete City behavior or both disciplines at equal scope
    - H3, line 510: 13. Replace the navigation framework, build a general mission platform or move every workload onboard
  - H2, line 517: Non-Functional Requirements

Hierarchy and Markdown checks

Heading levels are sequential and logically nested. T-decision numbering follows subject grouping rather than numeric order; this is coherent and is not a hierarchy violation.

Lists and tables are well formed. The Mermaid block at lines 120–150 is closed. No malformed Markdown links or unclosed code fences were found.

The active scope contains fifteen Markdown links: five local links and ten external links. All five local destinations exist:

- Line 6 → `/home/lev/IJKbot/concepts_brief.md`
- Line 7 → `/home/lev/IJKbot/docs/reviews/rtk_final_2026/goldfish_review_report.md`
- Line 8 → `/home/lev/IJKbot/docs/reviews/rtk_final_2026/draft_reconciliation.md`
- Line 114 → `/home/lev/IJKbot/docs/reviews/rtk_final_2026/platform_decision.md`
- Line 357 → `/home/lev/IJKbot/docs/GOROD.md`

External links have descriptive labels and syntactically valid HTTPS destinations. External availability and source accuracy were not checked, in accordance with the local-only restriction.

Actual-read manifest

Read completely:

- Persona: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/structural.md`
- Standard: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/feature-spec-standard.md`
- Required context: `/home/lev/IJKbot/concepts_brief.md` — all 188 lines
- Required context: `/home/lev/IJKbot/docs/reviews/rtk_final_2026/goldfish_review_report.md` — all 78 lines
- Required context: `/home/lev/IJKbot/docs/reviews/rtk_final_2026/draft_reconciliation.md` — all 52 lines
- Required context: `/home/lev/IJKbot/docs/reviews/rtk_final_2026/platform_decision.md` — all 43 lines
- Required context: `/home/lev/IJKbot/docs/GOROD.md` — all 54 lines

Target reading:

- `/home/lev/IJKbot/docs/designs/rtk_final_2026.md` — active lines 1–525 read completely.
- Lines 526–680 read for context only; lines 681–834 were not read or audited.

Truncation repair: The initial combined read exceeded the tool-output limit. Every required context file and every active target line was then reread in smaller, untruncated outputs. No unresolved truncation remains in the audited scope.

Inaccessible files: None.

No other review reports were read. No files were written, no builds or tests were run, and no hardware, network or external browsing operations were performed.
