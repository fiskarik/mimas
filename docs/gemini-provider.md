# Gemini provider

Unified Interview Runtime uses Gemini by default for new sessions. The adapter is
`ai_core/llm/gemini.py`, with official `google-genai==2.24.0`. No client-side SDK,
image/audio input, tool use or extra report-generation request is added.

## Configuration

Backend environment variables override local `.env` values, including explicit empty
values. Copy the following to `.env` and enter the key locally:

```dotenv
MIMAS_LLM_PROVIDER=gemini
GEMINI_API_KEY=
MIMAS_GEMINI_MODEL=gemini-3.8-flash
MIMAS_GEMINI_QUESTION_THINKING=low
MIMAS_GEMINI_FOLLOW_UP_THINKING=medium
MIMAS_GEMINI_EVALUATION_THINKING=medium
MIMAS_GEMINI_VERIFICATION_THINKING=medium
MIMAS_GEMINI_CODE_REVIEW_THINKING=high
MIMAS_LLM_TIMEOUT_SECONDS=60
```

Thinking policy is checked at startup/provider construction: low/medium/high only.
Code review policy is reserved; no new code-review flow is implemented.

Install with `.venv\Scripts\python.exe -m pip install -r backend/requirements.lock.txt`.
Explicit live check: `.venv\Scripts\python.exe -m cli.main --check-llm`.
It sends one short structured-output task (with bounded transient retries), not an interview.
Use `start_demo.bat` for the web UI or `start_ai.bat` for a live CLI interview.

Manual rollback: set `MIMAS_LLM_PROVIDER=groq`, keep `GROQ_API_KEY` and `GROQ_MODEL`,
restart the server and create a new session. `--check-groq` checks Groq independently.
No automatic cross-provider fallback: it would silently change the evaluator and send
candidate data to another provider. Old sessions without provider metadata remain Groq;
new sessions pin provider+model, so changing the default does not corrupt resume.

The legacy camera demo retains its AI_MODE/Groq/STT configuration. This migration is for
the unified text runtime. `/api/health` includes `runtime_llm`; `/api/ai/health` returns
configuration readiness only (`connection_checked=false`), never an implied live success.

## API and validation

Use `client.aio.models.generate_content()` because it maps directly to the existing
stateless `generate(system,payload,schema,operation)->str` contract. Interactions is not
required for these single tasks. The pinned official SDK supports this API and its typed
GenerateContentConfig. SDK transports are closed by the async context manager.

Pass existing `EvaluationResult.model_json_schema()` and `GeneratedQuestion.model_json_schema()`
as `response_json_schema`, with `response_mime_type=application/json`. No duplicate
Gemini domain schemas. Thinking uses typed ThinkingConfig. Tools/AFC are disabled.
Provider rejects blocked/truncated/empty/non-object responses; callers still validate the
Pydantic model and exact quote grounding. The common prompts and score/decision rules
remain unchanged. A deterministic abstention is labelled provider=deterministic.

References checked during implementation:
- https://googleapis.github.io/python-genai/
- https://ai.google.dev/gemini-api/docs/generate-content/structured-output
- https://ai.google.dev/gemini-api/docs/generate-content/thinking

## Retries, persistence, telemetry

SDK implicit retries disabled. Gemini adapter attempts at most twice for transient
timeouts/network/429/5xx and invalid JSON, with one-second backoff. A domain-validation
retry has a one-attempt budget, so at most three requests per evaluator/generator call.
Authentication/model errors and blocked/truncated results are not retried blindly.
Each HTTP attempt also has an outer asyncio timeout, default 60 seconds.

After exhausted transient failures, a sanitized ProviderError leaves runtime at its
durable pending stage. API responds 503; reload/resume repeats the pending operation.
No turn/evidence/question is duplicated. Nontransient unavailable evaluations retain
existing behavior: an explicit unavailable result, never fabricated evidence.

Each SDK attempt records provider, model, operation, thinking level, latency, status,
retry count and available input/output/thinking/total token counts in runtime trace and
the `ai_core.llm` logger. Trace is checkpointed even on failures. It excludes keys, raw
provider errors and candidate payloads from request metrics. Existing domain traces
still contain answers as before. EvaluationAttempt also records provider/model and the
existing prompt version. No exact dollar cost is guessed from token counts.

## Validation status

Offline tests exercise real SDK serialization through httpx.MockTransport, structured
text parsing, thinking policy, temporary/permanent errors, capped retries, configuration,
provider pinning and API resume after transient failure. Existing runtime/Groq tests remain.
Normal pytest does not call Google. Browser scripted QA remains labelled as synthetic.

Live smoke and real web interview require GEMINI_API_KEY and access to the exact requested
gemini-3.8-flash model; offline test success does not confirm either. After adding the key,
run --check-llm, then test abstention, a correct answer, an explicit misconception, a paste
over 500 characters followed by a correct explanation, reload and the final report.
