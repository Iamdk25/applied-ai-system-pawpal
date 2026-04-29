# PawPal+ — Agentic Pet Care Planner

> **Applied AI System** capstone (Week 9). This project extends my Module 2
> mini-project, **PawPal+** — a Streamlit-based pet care task tracker that
> represented pets and their owners and used algorithmic logic (sorting,
> filtering, conflict detection, recurrence) to organize daily care tasks. The
> original system required users to enter every task by hand. **This version
> adds an agentic Planner** that turns a one-line care goal into a
> conflict-free, multi-day schedule using Google Gemini.

## Scenario

A busy pet owner needs help staying consistent with pet care. They want an assistant that can:

- Track pet care tasks (walks, feeding, meds, enrichment, grooming, etc.)
- Consider constraints (time available, priority, owner preferences)
- Produce a daily plan and explain why it chose that plan

Your job is to design the system first (UML), then implement the logic in Python, then connect it to the Streamlit UI.

## 📸 Demo

<a href="pawpal_app.png" target="_blank"><img src='pawpal_app.png' title='PawPal App' width='' alt='PawPal App' class='center-block' /></a>

---

## Features

### Pet & owner management
- Register multiple pets under one owner profile (name, species, age)
- Remove pets at any time; their tasks are cleaned up automatically

### Task management
- Add care tasks to any pet: **walk**, **feeding**, **medication**, or **appointment**
- Set a due time and recurrence frequency: **once**, **daily**, or **weekly**
- Priority is inferred automatically from the category — no manual input needed:
  - `medication` / `appointment` → **HIGH**
  - `feeding` → **MEDIUM**
  - `walk` → **LOW**

### Sorting
- **Sort by time** — tasks appear in ascending `due_time` order (chronological daily schedule)
- **Sort by priority** — HIGH tasks float to the top; `due_time` is used as a tie-breaker within each priority tier

### Conflict detection
- Scans every pair of incomplete tasks and flags any two scheduled within **30 minutes** of each other
- Warnings appear at the top of the schedule with the exact gap in minutes and which pet(s) are affected
- Returns an empty list (no exception) when the schedule is clean

### Overdue task warnings
- Any pending task whose `due_time` has already passed is highlighted with `st.warning` in the UI
- Overdue detection uses `datetime.now()` at render time so it stays current as the day progresses

### Recurring task automation
- Marking a task complete auto-schedules the next occurrence via Python's `timedelta`:
  - **Daily** → `due_time + 1 day`
  - **Weekly** → `due_time + 7 days`
  - **One-time** → no new task is created
- The next occurrence is a fresh `Task` object (cloned via `dataclasses.replace()`); the completed task is never mutated

### Filtering
- Filter the schedule to a single pet or view all pets at once
- Separate views for **pending** and **completed** tasks

---

## What you will build

Your final app should:

- Let a user enter basic owner + pet info
- Let a user add/edit tasks (duration + priority at minimum)
- Generate a daily schedule/plan based on constraints and priorities
- Display the plan clearly (and ideally explain the reasoning)
- Include tests for the most important scheduling behaviors

## Smarter Scheduling

The `Scheduler` class in `pawpal_system.py` goes beyond a simple task list with four algorithmic features:

### Sort by time
`sort_by_time()` uses Python's `sorted()` with a `lambda` key to order every task across all pets by `due_time` in ascending order, so the daily schedule always reads chronologically regardless of the order tasks were added.

### Filter tasks
`filter_tasks(pet_name, status, category)` applies AND logic across up to three dimensions — you can ask for "Rex's pending medication tasks" in a single call. It reuses the same sorted output as `sort_by_time()` so results are always in chronological order.

### Recurring task automation
`mark_task_complete(task)` marks a task done and immediately schedules the next occurrence using Python's `timedelta`:
- **Daily** tasks → `due_time + timedelta(days=1)`
- **Weekly** tasks → `due_time + timedelta(weeks=1)`
- **One-time** tasks → no new task is created

The next-occurrence `Task` is cloned with `dataclasses.replace()` so the original is never mutated, then added to the same pet automatically.

### Conflict detection
`get_conflict_warnings(window_minutes=30)` scans every pair of incomplete tasks and flags any two whose `due_time` falls within the configurable window (default 30 minutes). It returns plain-English strings such as `"'Walk' (08:00 AM) and 'Medication' (08:15 AM) are only 15 min apart (same pet (Rex))"`. Exact-time overlaps are called out explicitly as `"exact overlap!"`. The lower-level `check_for_conflicts(window_minutes)` returns raw `(Task, Task)` pairs for programmatic use. Neither method raises an exception — both return an empty list when the schedule is clean.

## AI Planner (Agentic Workflow)

The **Planner Agent** turns a high-level pet care goal (e.g. *"Help my senior
dog lose weight"*) into a 7-day, conflict-free schedule. It runs an agentic
**Planner → Reviewer → Revise** loop:

1. **Planner** — The agent drafts a multi-day plan using Google Gemini
   (`gemini-2.5-flash` by default) with function calling. The model returns
   structured JSON via a `submit_plan` function declaration, enforced by
   `FunctionCallingConfig(mode="ANY")`.
2. **Reviewer** — `Scheduler.validate_proposed_changes` (deterministic
   Python) checks the proposed plan against the user's existing schedule for
   30-minute conflicts. Pre-existing user collisions are ignored — only pairs
   involving at least one proposed change are flagged.
3. **Revise** — if the Reviewer finds conflicts, the human-readable warning
   strings are fed back into the next Planner call. The loop runs up to N
   iterations (default 3).
4. **Confirm & commit** — once the plan is clean, the Streamlit UI shows a
   summary of proposed adds and reschedules. Nothing is applied to the pet
   until the user clicks **Confirm & Apply**.

### Architecture

![System architecture](assets/architecture.png)

> Mermaid source in [`assets/architecture.mmd`](assets/architecture.mmd).

### Setup

Copy `.env.example` to `.env` and fill in your `GEMINI_API_KEY`:

```bash
cp .env.example .env
# then edit .env and paste your key
```

Override the default model with `PAWPAL_AGENT_MODEL` (e.g. `gemini-2.5-pro`).

### Sample interactions

| Goal | Existing tasks | Result |
|---|---|---|
| *"Help my senior dog lose weight over the next week"* | one daily walk at 08:00 | 8 tasks added across 7 days, 1 iteration |
| *"Potty train my 3-month-old puppy"* | (none) | 12 tasks added (feeding, bathroom breaks, short walks), 1 iteration |
| *"Recovery routine after surgery"* | medication at 08:00 daily | 6 tasks; iteration 1 collided at 08:00, iteration 2 spread to 10:00 / 14:00 / 18:00 |

The reasoning trace expander shows each iteration's proposed tasks, the
LLM's stated reasoning, and any reviewer warnings that triggered a revision.

### Guardrails & reliability

- **Goal validation** — empty goals, goals shorter than 5 chars, longer than
  500 chars, or containing a banned token (e.g. *"ignore previous"*) are
  rejected before any LLM call. The agent surfaces `error="invalid_goal: ..."`.
- **Schema-forced output** — `FunctionCallingConfig(mode="ANY")` makes Gemini
  always call `submit_plan`, so we never parse free text.
- **Past-time clipping** — if the LLM proposes `day_offset=0` at a time
  already past, the parser pushes it to tomorrow.
- **Bounded iterations** — max 3 revision rounds by default; failure surfaces
  the full trace and adds nothing to the schedule.
- **Structured logging** — every step (LLM request/response latency, token
  usage, conflict counts, errors) is JSON-logged to `pawpal_agent.log` for
  replay and the reliability writeup.

See [`model_card.md`](model_card.md) for the full reliability eval.

### Demo walkthrough

> 📹 *Add your Loom link here once recorded.*

## Getting started

### Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Suggested workflow

1. Read the scenario carefully and identify requirements and edge cases.
2. Draft a UML diagram (classes, attributes, methods, relationships).
3. Convert UML into Python class stubs (no logic yet).
4. Implement scheduling logic in small increments.
5. Add tests to verify key behaviors.
6. Connect your logic to the Streamlit UI in `app.py`.
7. Refine UML so it matches what you actually built.

## Testing PawPal+

### Running the test suite

```bash
python -m pytest tests/ -v
```

The suite has **16 tests** total — 6 covering the original scheduler and 10
covering the agent and the agent/scheduler boundary. The Gemini client is
mocked via dependency injection (`client=` parameter on `run_planner_agent`),
so tests run offline and deterministically.

### What the tests cover

**Original scheduler (`tests/test_pawpal.py`)** — 6 tests covering task
completion, chronological sorting, daily recurrence, and exact-time conflict
detection.

**Agent (`tests/test_agent.py`)** — 10 tests:

| Test | What it proves |
|---|---|
| `test_happy_path_first_iteration_passes` | A clean round-1 plan is staged but **not yet** added to the pet (commit is the user's job). |
| `test_commit_applies_tasks_to_pet` | `commit_agent_result` actually appends tasks to the pet. |
| `test_conflict_triggers_revision` | Round 1 conflicts with an existing task; round 2 picks a different time and the Reviewer passes. |
| `test_max_iterations_exceeded_commits_nothing` | All 3 rounds fail → `success=False`, no agent tasks added. |
| `test_malformed_response_logged_then_retried` | A tool input missing required fields is caught, the iteration is logged as failed, and the next iteration succeeds. |
| `test_empty_goal_rejected_before_api_call` | An empty goal is blocked by the guardrail with **zero** API calls made. |
| `test_abusive_input_rejected` | Prompt-injection canaries (e.g. *"ignore previous"*) are blocked. |
| `test_validate_finds_internal_proposed_conflicts` | Two new tasks 10 min apart are flagged. |
| `test_validate_finds_external_conflict_with_existing` | A new task 5 min after an existing one is flagged. |
| `test_validate_ignores_pre_existing_user_conflicts` | The agent isn't blamed for the user's own pre-existing collisions. |

### Reliability eval

Run `python eval_agent.py` to exercise 6 representative goals against the
live Gemini API. The script prints a markdown table of pass / fail /
iteration counts and an aggregate pass rate. The output is reproduced in
[`model_card.md`](model_card.md).

### Confidence Level

★★★★★ (5 / 5)

Original scheduler behaviors are fully covered, plus the new agent path is
exercised across happy-path, conflict-revision, max-iterations,
malformed-response, and guardrail scenarios. The Reviewer
(`validate_proposed_changes`) has direct unit tests independent of the LLM.
