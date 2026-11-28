Structural Goldfish report — Stage 7, round 3, Mode REVIEW

Target and scope: /home/lev/IJKbot/docs/designs/rtk_final_2026.md, feature specification at lines 1–529, immediately before the primary “## Detailed Implementation Plan” at line 530. Lines 530–838 were read for clarification only and were not audited as an implementation plan.

Result: No findings. No Blocker, Major or Nit discrepancies were identified in the assigned structural scope. No structural-3-* finding IDs are issued.

Standard compliance:

The specification explains the problem and motivation at lines 22–34, goals at lines 36–51, non-goals at lines 53–62, and component responsibilities, data flows and integration at lines 102–422.

Alternatives are substantively evaluated rather than merely listed. The architecture contains paired mechanisms, costs and failure conditions, and lines 424–519 consolidate thirteen alternatives with technical or scope trade-offs and reconsideration conditions. The platform preference is explicitly distinguished from a measured technical rejection. Recorded author selections are not presented as unsupported maintainer objections.

Failure modes, constraints and mitigations appear throughout the architecture and prerequisite tables. These include deployment compatibility, compute capacity, sensing coverage, stale observations, command ownership, loss of the mission coordinator, bounded retries, network/storage load and partial outcomes. Security-relevant handling includes malformed and oversized payload rejection, bounded evidence references rather than arbitrary remote filesystem instructions, and exclusion of credentials from evidence documents. The final non-functional requirements consolidate timing, bounded state, rollout/recovery and traceability.

The assigned standard requires these substantive areas but does not prescribe mandatory literal section titles. The document’s distributed treatment of risks does not require an additional heading named “Risks & Mitigations.”

Structure map:

- H1, line 1: IJKbot preparation for the RTK Cup final
  - H2, line 10: Overview
  - H2, line 22: The Problem
  - H2, line 36: Goals
  - H2, line 53: Non-Goals
  - H2, line 64: Open Questions
  - H2, line 76: Critical User Journeys (CUJs)
    - H3, lines 78, 84, 90 and 96: CUJs 1–4
  - H2, line 102: Technical Plan (Architecture)
    - H3, line 104: Scope and decision state
    - H3, line 110: Deployment prerequisite
    - H3, line 116: Logical data and command paths
    - H3, line 154: Physical coverage and low-obstacle input
      - H4, line 164: T2 — filtered 3D obstacle points with Voxel Layer
      - H4, line 181: T7 — connected support surfaces from current depth
    - H3, line 207: Motion ownership and protection invariant
      - H4, line 215: T1 — Collision Monitor on the final command path
    - H3, line 234: Observation acceptance and mission outcomes
      - H4, line 238: T3 — typed ROS observation interfaces
      - H4, line 274: T4 — bounded QR retries
      - H4, line 298: T5 — compact toy-victim detector
      - H4, line 324: T8 — known safe observation poses
    - H3, line 353: City, operation and trial records
      - H4, line 357: T6 — bounded autonomous City action set
    - H3, line 378: Existing components affected by this plan
    - H3, line 393: Approved architectural choices
    - H3, line 409: Prerequisites to close before implementation can be finalized
  - H2, line 424: Alternatives Considered
    - H3, lines 430–514: Thirteen numbered alternative evaluations
  - H2, line 521: Non-Functional Requirements

Formatting and local-link checks:

Heading nesting is sequential and logical, without skipped levels. Decision identifiers follow their architectural grouping; their nonnumerical presentation order does not violate the hierarchy.

All fourteen active-scope Markdown tables have consistent column counts and valid separator rows. Lists are well formed. The Mermaid block opens at line 120 and closes at line 150; no unclosed fence was found.

All five active-scope local Markdown links resolve to existing files: the concepts brief, brainstorm findings, predecessor reconciliation, platform decision and City guide. No local anchor fragments require validation. External destinations were not accessed, as required by the local-only review boundary.

Actual-read manifest:

Read completely:

- /home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/structural.md — 65 lines.
- /home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/feature-spec-standard.md — 39 lines.
- /home/lev/IJKbot/docs/designs/rtk_final_2026.md — 838 lines; active audit lines 1–529, remainder clarification only.
- /home/lev/IJKbot/concepts_brief.md — 188 lines.
- /home/lev/IJKbot/docs/reviews/rtk_final_2026/goldfish_review_report.md — 78 lines.
- /home/lev/IJKbot/docs/reviews/rtk_final_2026/draft_reconciliation.md — 52 lines.
- /home/lev/IJKbot/docs/reviews/rtk_final_2026/platform_decision.md — 43 lines.
- /home/lev/IJKbot/docs/GOROD.md — 54 lines.

Truncation repairs: Two oversized output batches were truncated. The target was subsequently reread in bounded numbered chunks covering lines 1–838. Mandatory context was reread separately; the omitted concepts-brief passage was explicitly repaired by rereading lines 120–146. No required content remains unread because of truncation.

Inaccessible files: None.

Review limits: Read-only local document inspection and static Markdown/link checks only. No files were written, builds or tests run, robot/network commands issued, external URLs accessed, or additional agents used.
