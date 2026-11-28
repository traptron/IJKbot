Style review — round 1

Target: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md`, lines 1–525, before `## Detailed Implementation Plan`.

No additional style standard was assigned. No Blocker findings.

**style-1-1 — Major — Stale wording makes selected detector choices appear unresolved**

Affected scope: “T5 — Selected: adapt a compact detector to representative toy victims,” line 312.

Problem language: “No particular model generation, CUDA/TensorRT conversion or library version is selected in this draft.”

The sentence combines three decisions with different states. Line 20 already records laptop PyTorch and Ultralytics YOLO11n as selected; later T10/T11 sections confirm them. Library versions and measured runtime compatibility remain unresolved. Readers could incorrectly reopen the selected model/runtime when following these preparation gates.

Recommended action: **CALIBRATE**. Replace the sentence with: “Use the selected Ultralytics YOLO11n model with native PyTorch on the laptop. Pin compatible library versions and checkpoint artifacts after the laptop compatibility check; TensorRT conversion is outside the selected baseline.” Preserve the concurrent-workload measurement requirement.

**style-1-2 — Nit — Drafting defenses obscure the alternatives section’s useful decision record**

Affected scope: introduction to “Alternatives Considered,” line 424.

Problem language: “it is not an invented quotation of the author's motives or an upstream maintainer rejection. No alternative is labelled physically disproven without an experiment.”

These sentences defend the drafting process without giving the reader another engineering or operator decision. The individual entries already identify author selections, measured limitations and reconsideration conditions.

Recommended action: **DROP** these two sentences. Retain the predecessor-comparison statement and the distinction between deferred and rejected options. A concise introduction is sufficient: “These alternatives reflect the predecessor and recorded author choices T1–T8. Author selections are identified explicitly; deferred options remain distinct from rejected ones.”

**style-1-3 — Nit — Alternatives repeat the same attribution in adjacent labels**

Affected scope: “Alternatives Considered,” lines 430, 451, 458, 465, 479, 486, 493, 500 and 507.

Problem language: “**Reason not selected:** **Not selected by author:**”

The doubled label repeats “not selected” before the explanation begins. It makes an already long comparison harder to scan.

Precise remedy: Use one label, such as “**Author decision:**”, for these entries, followed by the selected option and technical trade-off. Preserve explicit attribution to the author and all reconsideration conditions.

The concrete safety requirements, deployment prerequisites, stale-input restrictions and incomplete-outcome rules are useful decisions. They should remain.

Actual-read manifest:

- Persona: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/style.md` — read completely.
- Target: `/home/lev/IJKbot/docs/designs/rtk_final_2026.md` — active lines 1–525 read completely; supplemental lines 526–650 read to check later context.
- `/home/lev/IJKbot/concepts_brief.md` — all 188 lines read.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/goldfish_review_report.md` — all 78 lines read.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/draft_reconciliation.md` — all 52 lines read.
- `/home/lev/IJKbot/docs/reviews/rtk_final_2026/platform_decision.md` — all 43 lines read.
- `/home/lev/IJKbot/docs/GOROD.md` — all 54 lines read.

The initial aggregate output was truncated; complete individual reads repaired it. A subsequent target excerpt omitted part of lines 272–277; lines 270–278 were reread completely. No inaccessible files. No other reports, source files, external resources, builds, tests or writes were used.
