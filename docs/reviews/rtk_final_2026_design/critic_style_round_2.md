Mode: REVIEW — Style Goldfish, Stage 7, round 2.

Active scope: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, lines 1–529 inclusive, covering the feature specification before the primary `## Detailed Implementation Plan`.

No Blocker or Major findings. Three editorial Nits remain.

1. **style-2-1 — Nit**
   **Affected scope:** Non-Goals, line 59.
   
   **Rationale:** The text excludes “committing to a particular toy-person detector before selecting sufficient evidence and testing representative inputs.” Elsewhere, the document records an approved detector approach and selects Ultralytics YOLO11n with native PyTorch (lines 106 and 316). This wording blurs the distinction between selecting an implementation candidate and validating it.
   
   **Remedy:** Preserve the banner-evidence restriction, but replace the detector clause with: “Treating the selected toy-person detector as validated before establishing sufficient victim evidence and testing representative inputs.”

2. **style-2-2 — Nit — DROP**
   **Affected scope:** T5, line 307, final sentence; T8, line 333, final sentence.
   
   **Rationale:** “No external images, weights or datasets have been downloaded during drafting” and “No alignment setting is changed during this design step” report drafting activity. Neither sentence changes an implementation or operator decision. They interrupt the architectural explanation with work-log details.
   
   **Remedy:** Remove these two sentences from the feature specification. Retain the surrounding limitations about dataset sufficiency, measured performance, calibration and valid depth. The required reconciliation document already records that drafting did not implement or deploy changes.

3. **style-2-3 — Nit — DROP**
   **Affected scope:** City, operation and trial records, line 370.
   
   **Rationale:** This paragraph repeats the missing scoring table, unsuccessful PDF retrieval and prohibition on invented City scores already explained at line 361. Line 372 then provides the current decision: defer City action selection until the rules appear and continue Evacuation/shared work. Repeating the caveat adds reading cost without adding another decision.
   
   **Remedy:** Delete line 370. Retain line 361’s source limitation, line 368’s budget qualification, line 372’s current dependency decision and line 374’s action-selection requirements.

Concrete safety requirements, motion-inhibition rules, deployment prerequisites, measurement gates and truthful partial outcomes should remain. Their caveats identify actual decisions and failure consequences.

Actual-read manifest:

- Persona: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/style.md` — read completely.
- Target: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md` — lines 1–529 read completely; later sections not read.
- `/home/lev/IJKbot/concepts_brief.md` — all 188 lines read.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/goldfish_review_report.md` — all 78 lines read.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/draft_reconciliation.md` — all 52 lines read.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/platform_decision.md` — all 43 lines read.
- `/home/lev/IJKbot/docs/GOROD.md` — all 54 lines read.

The initial combined output was truncated. All mandatory context and active target content were subsequently reread in bounded outputs, repairing the truncation completely. No inaccessible files. No additional reports, repository source files or external URLs were read. No writes, builds, tests, hardware/network actions or agent delegation were performed.
