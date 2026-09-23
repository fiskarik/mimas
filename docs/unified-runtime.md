# Unified Interview Runtime

The existing `InterviewEngine` is the unified runtime for the AI web interview and CLI.
See `project-walkthrough.md` for a Russian walkthrough and the latest review findings.
The legacy camera demo is unchanged. No new LLM provider, billing, surveillance, or media
pipeline is introduced.

## State and processing

`InterviewState` holds the interview ID, role/level config, timestamps, persisted Limits
and a competency-plan snapshot for newly created sessions,
and IntegrityPolicy, questions/turns, per-skill evidence and misconceptions, observed
events/signals, grounded cross-answer contradictions, verification history, next decision,
pending answer and pending question specification. Existing saved JSON states load using
defaults for additive fields. Skill evidence keeps positive/negative/uncertain types in
one existing collection; no duplicate evidence store is created. Confidence is an internal
coverage indicator, never returned as a candidate score. Demonstrated levels remain
conservative/provisional; answer points retain their separately documented rubric.

`handle(RuntimeEvent)` dispatches start, answer, finish and client observations. Evaluation
uses earlier same-skill answers as context. Both quotes of a proposed contradiction must
match the actual referenced answers. Abstentions are normalized before LLM evaluation.
Misconceptions have unresolved/resolved/confirmed states with source question IDs.

Pipeline: save answer -> evaluate -> collect evidence and update skill/misconceptions ->
complete any active verification -> choose decision -> generate one question -> save.
Question generation receives the action, goal, prior evidence, misconceptions and the
source answer for a verification. The model does not select the next action.

## Decision policy

Hard session time/question and per-skill question limits take precedence, including over
verification. Remaining concerns stay visible in the final report when a limit stops work.
Within those limits: required integrity verification -> grounded contradiction verification
-> misconception follow-up -> specific evaluator uncertainty -> evidence/coverage decision.
Follow-up limits prevent loops. Minimum distinct evidence sources and coverage limits are
in `Limits`; paste threshold, event cap and verification attempts are in `IntegrityPolicy`.
Default large paste: 500 characters; default verification attempts per signal: one.
At the event cap, further observations are acknowledged as dropped, the report marks
the history incomplete, and answer/finish requests remain usable.

Actions: ASK_QUESTION, FOLLOW_UP, VERIFY_KNOWLEDGE, VERIFY_INTEGRITY, NEXT_SKILL,
COMPLETE_INTERVIEW. Old enum member names remain aliases for CLI source compatibility.
Coding/timeout event names are reserved in the event schema, but rejected by the text-mode
dispatcher until their flows exist. No implicit timeout event or coding evaluation is claimed.

## Integrity semantics

Frontend sends paste length, copy, window focus loss/return, event ID and current question ID.
Clipboard contents are not included in event telemetry. Events are client-reported, not
tamper-proof. A sessionStorage outbox is retried before answer/finish submission; IDs are
deduplicated server-side. Per-question repeated paste/focus observations share a signal.

Large paste requests an explanation after answer evaluation. Focus loss is informational
and does not independently trigger verification. Neither subtracts skill points.
Verification outcomes: VERIFIED (explicit corrected/correct explanation), CONTRADICTED
(explicit technical error), UNCERTAIN (including unavailable evaluation/refusal), PENDING
(question not answered). Only VERIFIED resolves its targeted signal. Outcomes refer to
demonstrated understanding, never proof that no external assistance was used.

## Persistence and API

Reuse `ai_sessions.state`, `trace`, `pending` in SQLAlchemy; no SQL schema migration.
Checkpoints commit the answer before evaluation, evaluated turn/evidence before decisions,
selected action before generation, pending generation spec, generated question, integrity
events and completion. Each checkpoint stores state+trace+pending atomically.
`resume()` handles EVALUATE_ANSWER, DECIDE_NEXT_ACTION, ASK_QUESTION and SELECT_SKILL.
Successful persisted evaluations are not repeated. An interrupted in-flight LLM call may
be repeated because its response was never durably received.

Existing `/start`, `/answers`, `/finish`, GET routes remain; `/start` also resumes an
interrupted stage. `/events` accepts observation events only, under the same token and
session lock. GET exposes `resume_required`, action and progress plus legacy UI fields.
During an interview, question goals/verification targets, misconceptions, negative evidence,
confidence and integrity signals are omitted. Final reports include signals, verification
outcomes/evidence references, contradictions, per-skill evidence and per-answer scores.

The lock pool supports the existing single-worker deployment only. Running multiple API
workers needs database concurrency control before production use.

## Verification

`ai_core/tests/test_runtime.py` covers scripted full interview, signal outcomes, priority,
abstention and four crash/recovery boundaries with FakeLLMProvider. Backend tests cover
authenticated/idempotent events, report privacy and generation-crash recovery.

For browser QA, explicitly start `scripts/runtime_qa_server.py` on port 8001, then run
`scripts/smoke-runtime.cjs` with the Playwright module path. It routes requests from the
real frontend to an isolated real API/SQLite database with a clearly labelled scripted
provider. It tests abstention -> answer -> paste -> verification -> reload -> explanation
-> report and mobile layout. This is not validation of live model judgment.

Live demo uses the configured provider (Gemini by default for new sessions; Groq remains selectable). Its semantic accuracy, latency and quota
remain separate from deterministic runtime validation.
