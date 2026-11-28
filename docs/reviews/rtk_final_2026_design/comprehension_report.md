**What this proposes**

Prepare IJKbot primarily for a complete autonomous Evacuation attempt, while deferring the concrete autonomous City subset until its scoring rules are available. The design selects an original Jetson Nano for onboard navigation and protection, with laptop-based language interpretation, toy recognition and QR decoding. It combines depth-based low-obstacle detection, a final protected motion-command path, correlated perception observations and independently recorded mission stages. Implementation proceeds through evidence gates; hardware compatibility, numerical limits, surveyed viewing poses and trained detector performance remain unproven.

**How the existing system works, per this document**

Previous Evacuation attempts interpreted target cells and navigated to them, but lacked victim detection and experienced QR failures whose exact boundary is unknown. The inspected checkout uses the lidar for navigation, has separate search-motion commands, and can mistake QR detection or an unsuccessful return home for stronger mission success. Existing command launches can expose different actuator-publishing paths, so the proposed protection cannot simply be added beside them. City currently provides sign recognition and operator-directed navigation rather than a demonstrated autonomous mission.

**C-01 — Major — The inherited minimum obstacle clearance is unspecified**

**Affected scope:** Goals, line 49; Motion ownership and protection invariant, line 213; Non-Functional Requirements, line 519; implementation step 8, line 732; Verification plan, line 817.

The document repeatedly requires preservation of the repository’s “required obstacle clearance,” but never states that minimum or links to the requirement that defines it. Line 49 supplies explicit values for the inherited speed ceiling and command timeout, while leaving clearance unnamed numerically. Consequently, a reader cannot determine the minimum clearance that the later measured zones and navigation configuration must preserve.

This differs from the explicitly pending measurements: stopping distance, sensor coverage and protection-zone dimensions are deliberately future evidence outputs. The clearance is presented as an existing constraint that already applies, rather than a value those experiments may freely select. State the inherited minimum or provide a direct link to its defining requirement.

**Actual-read manifest**

- Persona read in full: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/comprehension.md`.
- Target read in full: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, lines 1–834.
- Read chunks: 1–210, 211–420, 420–580, 580–710 and 708–834.
- The 211–420 tool response truncated part of the T5/T8 discussion. Lines 294–323 were reread separately, repairing the missing content.
- Feature scope 1–525 and detailed scope 526–834 were both checked, including later definitions before reporting the finding.
- No inaccessible or unresolved truncated content remains. No linked documents, source files, other reports or URLs were opened.
