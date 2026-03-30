# PawPal+ (Module 2 Project)

You are building **PawPal+**, a Streamlit app that helps a pet owner plan care tasks for their pet.

## Scenario

A busy pet owner needs help staying consistent with pet care. They want an assistant that can:

- Track pet care tasks (walks, feeding, meds, enrichment, grooming, etc.)
- Consider constraints (time available, priority, owner preferences)
- Produce a daily plan and explain why it chose that plan

Your job is to design the system first (UML), then implement the logic in Python, then connect it to the Streamlit UI.

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
`get_conflict_warnings()` scans every pair of incomplete tasks for an **exact** same `due_time` and returns plain-English warning strings (e.g. `"WARNING: 'Walk' and 'Medication' are both scheduled at 09:00 AM (same pet (Rex))"`). The broader `check_for_conflicts(window_minutes=30)` catches near-collisions within a configurable time window. Neither method raises an exception — they return an empty list when the schedule is clean.

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
