# PawPal+ Planner Agent — Model Card

## Base project

This system extends my Module 2 mini-project, **PawPal+**, a Streamlit app
that helped a pet owner plan care tasks for their pet. The original used
algorithmic logic — sorting by time and priority, conflict detection in a
30-minute window, daily/weekly recurrence via `dataclasses.replace`,
multi-filter views — but every task had to be entered manually. The goal of
this extension is to introduce an agentic Planner that turns a one-line care
goal into a full multi-day schedule.

## Intended use

- Drafting 7-day pet care plans for a single pet from a natural-language goal
- Local, single-user Streamlit app — not a clinical or veterinary tool
- AI feature integrated into the main scheduler, not a standalone script

## Out of scope

- Replacing veterinary advice
- Dosage decisions for medication (the agent only proposes timing slots)
- Multi-tenant or production deployment

## Model & configuration

| Setting | Value |
|---|---|
| Provider | Google Gemini |
| Default model | `gemini-2.5-flash` |
| Override | `PAWPAL_AGENT_MODEL` env var |
| Structured output | `tool_config: FunctionCallingConfig(mode="ANY")` |
| Max iterations | 3 (configurable from UI slider, 1–5) |
| Conflict window | 30 minutes (matches existing `Scheduler` default) |

The Planner uses a single-turn-per-iteration prompt: each revision is a
fresh user message that re-states the pet profile, goal, existing tasks
summary, and any prior reviewer feedback. Stateless across iterations.

## Inputs

- **goal** — free text, 5–500 chars, banned-token denylist
- **pet** — name, species, age (existing `Pet` dataclass)
- **existing tasks** — pending tasks for the next 14 days, summarized into
  the prompt to bound tokens
- **max_iterations** — caller-controlled (default 3)

## Outputs

- `AgentResult` with a list of `AgentStep`s (full reasoning trace) and, on
  success, the staged `final_new_tasks` and `final_reschedules`. Tasks are
  applied to the pet **only after** `commit_agent_result` is called from the
  UI's Confirm & Apply button.

## Guardrails

| Guardrail | Where |
|---|---|
| Goal length 5–500 chars | `_validate_goal` |
| Banned-token denylist (prompt-injection canaries) | `_validate_goal` |
| Max 30 new tasks per plan, max 10 reschedules | tool schema |
| Category enum: `feeding`, `walk`, `medication`, `appointment` | tool schema |
| Frequency enum: `once`, `daily`, `weekly` | tool schema |
| `time_of_day` regex `^([01]\d|2[0-3]):[0-5]\d$` | tool schema |
| Past-time clipping (day_offset=0 in past → next day) | `_compose_due_time` |
| 3-iteration revision cap | `run_planner_agent` |
| API errors surfaced cleanly (one retry) | `_planner_call` |
| Pre-existing user conflicts ignored (no infinite revision) | `validate_proposed_changes` |

## Logging

Every event is JSON-logged to `pawpal_agent.log` (gitignored): `agent.start`,
`agent.guardrail_rejected`, `planner.request`, `planner.response`,
`planner.parse_error`, `reviewer.evaluated`, `agent.success`,
`agent.max_iterations`, `agent.api_error`, `agent.committed`. Fields include
iteration, goal, pet, model, latency_ms, token usage, and conflict counts.

## Reliability eval

`python eval_agent.py` runs 6 fixed cases against the live API. Latest run:

**Result: 5/6 (83%) passed. Mean iterations: 1.8.**

| # | Result | Iter | New | Resched | Goal | Error |
|---|--------|------|-----|---------|------|-------|
| 1 | PASS | 1 | 3 | 0 | Help my senior dog lose weight over the... |  |
| 2 | PASS | 2 | 11 | 0 | Potty train my 3-month-old puppy |  |
| 3 | PASS | 1 | 3 | 0 | Manage anxiety for my cat with a calmin... |  |
| 4 | FAIL | 3 | 0 | 0 | Recovery routine after surgery — rest, ... | max_iterations_exceeded |
| 5 | PASS | 3 | 7 | 0 | Senior cat dental care routine |  |
| 6 | PASS | 1 | 9 | 0 | New kitten introduction and socializati... |  |

Case 4 failed because Gemini kept proposing tasks that conflicted with the
pre-existing "Heartworm pill" at 08:00 daily. The Reviewer flagged each
collision, but the model didn't space tasks far enough apart within 3
revision attempts. The local fallback plan was applied for that case.

**Unit tests:** 16/16 passing offline (`pytest tests/ -v`).

## Known limitations & biases

- **No global optimizer.** The agent uses LLM-generated times verbatim;
  the Reviewer only checks for conflicts. The first conflict-free plan
  ships, even if a different layout would be more humane (e.g. earlier
  walks for weight loss).
- **30-min window is fixed.** Matches the existing scheduler default. A
  user with very tight scheduling (5-min appointments) would see false
  negatives; a very loose schedule would see false positives.
- **Match-by-(title, time) for reschedules.** If a user has two tasks
  with the same title at the same time, the parser will refuse to
  reschedule (raises `parse_error`), forcing a retry. Acceptable for
  this in-memory single-user app.
- **No persistence.** Tasks live in Streamlit session state. A restart
  loses everything, including agent-added tasks.
- **No memory across goals.** Each goal is independent. The agent does
  not learn the user's preferences over time.
- **English-only.** The system prompt and banned-token list are English.
- **Bias risks.** Veterinary "best practice" varies by breed, region, and
  individual pet. A single LLM may produce confident-but-wrong routines —
  the system explicitly disclaims medical advice and the Reviewer only
  checks conflicts, not medical soundness.

## Misuse and prevention

| Misuse vector | Mitigation |
|---|---|
| Prompt injection (*"ignore previous instructions"*) | Banned-token denylist before LLM call |
| Pet sized as a token bomb (very long goal) | 500-char cap on goal |
| Spamming the API via the Streamlit button | Button disabled while empty, max-iter slider caps cost per click |
| Treating output as veterinary advice | README + model card disclaimers, scope explicitly excludes dosage |
| Using the system to generate tasks for non-pet contexts | Category enum locked to 4 pet-care categories |

## Reflection — AI collaboration during this project

I worked with AI assistants (Claude and Gemini) throughout the implementation.
Two specific instances stand out:

**Helpful suggestion.** The AI flagged a pre-existing test bug at
`tests/test_pawpal.py:97`: the assertion `assert any("WARNING:" in w for w
in warnings)` was checking for a substring (`"WARNING:"`) that the actual
`get_conflict_warnings` code never emitted. This test had been silently
passing only because the prior assertion (`len(warnings) >= 1`) was caught
first — but `any(...)` would have returned `False` against the real strings
(`"...exact overlap!"`). The AI proposed updating the assertion to match
the actual format, which I accepted as part of this work.

**Flawed suggestion.** Early on, the AI proposed having the Reviewer be a
second LLM call (Planner → LLM-Reviewer → Revise) for a stronger "two-agent"
narrative. I pushed back: the existing `Scheduler.check_for_conflicts` is
deterministic, fully testable, free, and produces the same human-readable
strings the user already sees in the UI. Using a second LLM as Reviewer
would have added cost, latency, non-determinism in tests, and a
self-fulfilling-prophecy risk where the Planner-LLM and Reviewer-LLM agree
on a wrong answer. The deterministic Reviewer was the right call.

## What surprised me during reliability testing

- **Function calling with `mode=ANY` is highly reliable** — across 16 unit-test
  runs and 6 live eval cases, Gemini called `submit_plan` with valid
  structured input in most iterations. Without `mode=ANY`, the model
  sometimes responded with text instead of calling the function.
- **The LLM regularly proposed `day_offset=0` at a time already past
  "today"** — a subtle bug that would have created immediately-overdue
  tasks. The parser's "clip to tomorrow" rule was essential.
- **Conflict feedback works because the Reviewer's strings are the same
  ones the human user sees.** The Planner doesn't need a special "agent
  feedback" format — it understands the human-readable warnings as well as
  it understands a normal user message.
- **Switching from Anthropic to Google Gemini** required adapting the
  function-calling patterns but the overall architecture (Planner → Reviewer
  → Revise) worked the same way. The `google-genai` SDK's `ToolConfig` with
  `FunctionCallingConfig(mode="ANY")` is equivalent to Anthropic's
  `tool_choice`.

## What this project says about me as an AI engineer

I designed this as **augmentation, not replacement**. The original PawPal+
already had a working algorithmic scheduler — sorting, filtering, conflict
detection, recurrence — and I deliberately kept all of it. The agent is
additive: it generates plans the user could have entered manually, and
hands them off to the existing system to be checked by the existing
Reviewer logic. I split the agent run into Plan → Stage → Confirm so the
user always has the final say. Logging, guardrails, mocked tests, and a
reproducible eval script were not afterthoughts — they were how I knew
the system worked.
