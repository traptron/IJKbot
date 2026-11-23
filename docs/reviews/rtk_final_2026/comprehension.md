# UX and ergonomics brainstorm review

**Role:** UX and Ergonomics-Brainstormer / egm-comprehension.  
**Mode:** BRAINSTORM.  
**Completion status:** Complete for the delegated immutable concept scope. This is a concept review, not a readiness certificate, implementation review, or report of executed robot tests.  
**Overall assessment:** The objective and priorities are understandable to a new team member. No context-sufficiency blocker. Five consequential ergonomics findings remain to resolve or explicitly stage before detailed design.

## Faithful paraphrase

The team wants one robot ready before departure on 1 December, prioritizing the maximum Evacuation score and selecting a smaller, measurable City scope. Previous runs demonstrated interpreting destinations and reaching them, but not victim detection; QR reading failed in the competition workflow, and low cars were struck. The proposal retains the proven external-laptop arrangement, investigates camera-depth obstacle handling alongside the roof lidar, and connects victim search, QR handling, and return into a complete mission.

The brief carefully separates team experience, observations from the local checkout, proposals, and unknown measurements. The checkout suggests a mismatch between configured obstacle inputs and camera-derived scans, and coupling between QR success and victim-found status, but neither observation proves the historical failure cause or describes the deployed robot. Hardware replacement is conditional on evidence. External-laptop permission is confirmed by the team and is not an open question in this review.

## Findings

### 1. Major — P1: Define the operator's complete run, including recovery

**Dimension:** UX & Developer Ergonomics.  
**Scope:** “Mission completion and field tests”; “Evidence needed before claiming readiness”; established constraints.  
**Evidence:** The brief requires visible mission stages, bounded retries, repeated runs without intervention, and a fallback configuration. It does not yet describe the operator's preparation, start, completion, abort, and reset sequence or what constitutes an intervention.

**Inference / usability friction:** Different team members may start nominally identical tests from different conditions, or reset a failed stage without recording that the autonomous run failed. A correct component sequence would then produce ambiguous evidence of complete-mission reliability. This is a workflow gap, not evidence that the existing CLI is inadequate.

**Ergonomic requirement:** Include a short operator journey in the next concept revision: select the known configuration and discipline; verify readiness; enter the task; start; observe the active stage and remaining mission time; recognize success or a named stop/failure; stop safely when needed; reset for a new attempt. Identify which actions are preparation, autonomous execution, and disqualifying test intervention. Separate the project's safety stop from claims about a rule-compliant competition recovery.

**Options and objection:** A one-page run card using the existing CLI and event display is the smallest option. A richer dashboard could improve visibility, but should be chosen only if rehearsal demonstrates that the existing display prevents the operator from understanding or controlling a run. Do not make a new UI a prerequisite for testing the robot.

**Concrete test:** Have a teammate who did not prepare a run follow only the run card in a mock or recorded rehearsal. Include normal completion, abort, and reset after an unreadable QR. They should identify the current stage, whether the attempt still counts as uninterrupted, and the permitted next action without coaching. Follow with a supervised field rehearsal when the configuration is safe.

### 2. Major — P1: Turn diagnostic categories into decisions an operator can make

**Dimension:** UX & Developer Ergonomics.  
**Scope:** QR workstream and the diagnostic evidence list.  
**Evidence:** The brief already distinguishes missing images, missing candidates, unreadable QR, delayed results, rejected results, and successful transitions, and requests timestamped evidence images. This is a strong starting point. It does not yet state how these observations choose the next investigation or identify stale evidence.

**Inference / usability friction:** A wall of correct logs can still leave a three-person team changing camera position, mission logic, and transport settings simultaneously. A screenshot of a decoded QR may belong to another attempt or viewing position and give false confidence about the failed run.

**Ergonomic requirement:** Define a compact diagnostic outcome for each failed attempt: observed stage, last successful stage, evidence location, and the next discriminating check. Associate the captured input and acceptance/rejection event with the same run. Distinguish “not observed” from “observed and rejected.” This is an information requirement, not a demand for a logging framework or message API.

**Options and objection:** Use a shared run sheet plus existing logs and saved images first; add a consolidated status view only if retrieving the evidence is too slow. Do not prescribe “replace the camera” or “increase retries” from the symptom alone.

**Concrete test:** Give a teammate four prepared traces: no fresh image, a visible but unreadable code, a decoded code whose result arrived too late, and a decoded result rejected in the current mission phase. They should choose different next checks and point to the supporting evidence. Passing this exercise validates diagnostic clarity; it does not establish the actual cause of the historical QR failure.

### 3. Major — P1: Make scoring evidence and incomplete-mission outcomes understandable independently

**Dimension:** UX & Developer Ergonomics.  
**Scope:** “Victim search and QR”; rule applicability; maximum Evacuation score.  
**Evidence:** The brief explicitly warns against equating a QR banner with a victim, reports that existing logic can set both flags on QR success, and notes separate scoring stages in an older event task. It also requires bounded retries and return, without yet choosing the behavior after a victim is confirmed but its QR remains unreadable.

**Inference / usability friction:** The operator and judges could see one green “success” despite disagreement over what actually happened. Conversely, an unreadable code could consume the remaining run without a deliberate policy for preserving other achievable outcomes. The scoring consequences cannot be settled until the final rules are known.

**Ergonomic requirement:** Use plain-language, independently observable outcomes for target interpretation, victim evidence, QR information, and return/completion. Keep “search exhausted,” “QR unreadable,” and “mission complete” distinct. Once final rules are obtained, choose bounded behavior for each incomplete stage and show its consequence to the operator. Preserve the confirmed laptop permission while resolving these separate rule questions.

**Options and objection:** Candidate policies include another safe viewing attempt, continuing toward return after a defined budget, or terminating with an explicit incomplete result. No policy is claimed here to earn particular points. Requiring every stage to succeed before any progress is recognized is simple, but may conflict with the stated scoring priority; accepting banner evidence as a victim is also not justified by this brief.

**Concrete test:** Walk through a small decision table with the team: banner only; visible toy with unreadable QR; valid QR without sufficient victim evidence; confirmed victim and QR; time budget exhausted. Each member should predict the same next action and state which facts are recorded versus which points remain unverified. Validate the rule-dependent cells against the final regulation or an explicit judging clarification.

### 4. Major — P2: Assign integration responsibility and scarce field time, not only components

**Dimension:** UX & Developer Ergonomics.  
**Scope:** Three workstreams; proposed one-person-per-workstream ownership; unknown engineering and field hours.  
**Evidence:** One robot and three people must support obstacle work, vision work, and complete-mission testing within the remaining calendar window. Shared integration is proposed, but actual availability, accepted ownership, and field access are unknown.

**Inference / usability friction:** Three individual owners can each make progress while nobody owns the day's runnable robot, repeatable field setup, or final cross-stage acceptance. All three workstreams may compete for the same robot and props. ChatGPT subscriptions do not resolve that resource conflict.

**Ergonomic requirement:** Before committing dates, record available person-hours and field slots, name a daily integration owner, and give each workstream a small evidence-based handoff: configuration used, demonstrated behavior, known failure, and next shared test. Include mechanical and prop preparation as scheduled work. Explicitly protect time for complete Evacuation runs before expanding City.

**Options and objection:** Keep the proposed component ownership and rotate the integration role, or work as a pair on the current end-to-end failure with a third person preparing the next test. A permanent integration-only person may be unaffordable for a team of three; the responsibility still needs a name. This review does not assign individuals or invent their availability.

**Concrete test:** Build a schedule for the next available field session using actual attendance and one robot. Check that obstacle, QR, and mission activities fit without simultaneous claims on the hardware, and that the session ends with a complete-run attempt and a recorded decision. If it cannot fit, reduce concurrent scope before promising dates.

### 5. Major — P2: Give hardware choices and the fallback a simple decision record

**Dimension:** UX & Developer Ergonomics.  
**Scope:** Alternatives weighed; equipment inventory; freeze deadline and fallback open item.  
**Evidence:** The brief sensibly keeps the Nano, ultrasonic sensors, and mounting changes conditional on measurements. No accepted architecture, major-change cutoff, or known-working fallback is yet specified. The local checkout is explicitly not established as the deployed configuration.

**Inference / usability friction:** “Hardware remains an option” can become a recurring discussion after every unsuccessful run. Team members can also disagree over what “the working version” means if mounting, launch settings, and code revision differ. This threatens test comparability as well as time.

**Ergonomic requirement:** For each considered change, record the observed limitation it addresses, the smallest trial that could support or reject it, expected installation/integration effort, a decision owner and time, and the configuration to restore if it fails. Name the currently demonstrated baseline and its limitations; do not label it competition-ready merely because destination navigation once earned points.

**Options and objection:** A shared short decision table and photographs of the tested setup are sufficient initially. Prefer reversible mounting or isolated trials where practical; full compute migration needs evidence of a limitation that the migration would actually address. The objection to a baseline-first approach is that it can preserve a fundamental mechanical defect, so failed bridge clearance or obstacle coverage must remain legitimate reasons to change it.

**Concrete test:** Present the team with three hypothetical results: camera sees a car but no obstacle reaches navigation; suitable depth is absent in a required region; measured compute delay prevents timely reaction. They should choose different investigations rather than the same hardware upgrade. Before the change cutoff, rehearse restoring the recorded fallback and show exactly which complete or partial behaviors it still demonstrates. These are proposed tests, not reported measurements.

## Standards application and limits

The Heilmeier guide supports prioritizing measurable examinations, available effort, and the significance of each change. The Zoom Out guide supports retaining useful infrastructure, diagnosing the root failure, and avoiding speculative hardware or UI work. Both were applied at concept level. No detailed software interfaces, detector choice, sensor physics claim, or final-rule interpretation is required or asserted by this report.

All factual project observations above are attributed to the immutable brief. No supporting source code, deployed robot, external regulation, or manufacturer material was inspected. Therefore historical failure causes, hardware compatibility, sensor coverage, final scoring, and readiness remain unverified. No external technical claims required browsing. No robot access, SSH, installs, builds, source/config edits, or additional agents were used; only this authorized report was saved.

## Actual-read manifest

The following files were read completely, with no truncated output:

1. Persona: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/agents/comprehension.md`
2. Immutable target: `/home/lev/IJKbot/docs/reviews/rtk_final_2026/initial_concepts_brief.md`
3. Standard: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/heilmeier-standard.md`
4. Standard: `/home/lev/.codex/plugins/cache/egm/egm/0.1.1/resources/document_standards/zoom-out-standard.md`

Supporting reads: none. Other reviews, conversation/memory retrieval, and the mutable `concepts_brief` were not consulted.
