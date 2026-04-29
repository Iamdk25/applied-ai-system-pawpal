"""Reliability eval for the PawPal+ Planner Agent.

Runs a fixed battery of (goal, pet, preloaded tasks) cases against the live
Anthropic API and reports pass/fail stats. Output is intended for the
project's reliability writeup (model_card.md).

Usage:
    python eval_agent.py

Requires GEMINI_API_KEY (preferred) or ANTHROPIC_API_KEY in env (or in `.env`).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import List, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pawpal_agent import run_planner_agent
from pawpal_system import Owner, Pet, Scheduler, Task


# (goal, pet (name, species, age), preload tasks (title, hh:mm, frequency, category))
CASES: List[Tuple[str, Tuple[str, str, int], List[Tuple[str, str, str, str]]]] = [
    ("Help my senior dog lose weight over the next week",
     ("Rex", "dog", 10),
     [("Existing Walk", "08:00", "daily", "walk")]),
    ("Potty train my 3-month-old puppy",
     ("Bean", "dog", 0),
     []),
    ("Manage anxiety for my cat with a calming daily routine",
     ("Mochi", "cat", 4),
     [("Vet visit", "09:00", "once", "appointment")]),
    ("Recovery routine after surgery — rest, light walks, meds",
     ("Rex", "dog", 6),
     [("Heartworm pill", "08:00", "daily", "medication")]),
    ("Senior cat dental care routine",
     ("Whiskers", "cat", 12),
     []),
    ("New kitten introduction and socialization plan",
     ("Tiny", "cat", 0),
     []),
]


def _build_scenario(pet_info, preload):
    name, species, age = pet_info
    pet = Pet(name=name, species=species, age=age)
    tomorrow = (datetime.now() + timedelta(days=1)).replace(
        second=0, microsecond=0,
    )
    for title, hhmm, freq, cat in preload:
        h, m = hhmm.split(":")
        due = tomorrow.replace(hour=int(h), minute=int(m))
        pet.add_task(Task(title, "preload", due, freq, cat))
    owner = Owner("Eval Owner", "")
    owner.add_pet(pet)
    return pet, Scheduler(owner)


def main() -> int:
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")):
        print("GEMINI_API_KEY or ANTHROPIC_API_KEY not set. Add it to .env or your shell.",
              file=sys.stderr)
        return 2

    print("PawPal+ Planner Agent — Reliability Eval")
    print("=" * 48)

    rows = []
    n_pass = 0
    total_iters = 0
    for i, (goal, pet_info, preload) in enumerate(CASES, start=1):
        pet, scheduler = _build_scenario(pet_info, preload)
        result = run_planner_agent(
            goal=goal, pet=pet, scheduler=scheduler,
            max_iterations=3,
        )
        passed = result.success
        iters = len(result.steps)
        n_tasks = len(result.final_new_tasks)
        n_resched = len(result.final_reschedules)
        status = "PASS" if passed else "FAIL"
        if passed:
            n_pass += 1
        total_iters += iters
        short_goal = goal if len(goal) <= 42 else goal[:39] + "..."
        rows.append((i, status, iters, n_tasks, n_resched, short_goal,
                     result.error or ""))
        print(f"[{i}/{len(CASES)}] {status} — {short_goal} "
              f"({iters} iter, {n_tasks} new, {n_resched} resched)"
              + (f" — {result.error}" if result.error else ""))

    n_total = len(CASES)
    pass_rate = (n_pass / n_total) * 100 if n_total else 0.0
    mean_iters = (total_iters / n_total) if n_total else 0.0

    print()
    print(f"Result: {n_pass}/{n_total} ({pass_rate:.0f}%) passed")
    print(f"Mean iterations: {mean_iters:.1f}")
    print()

    print("| # | Result | Iter | New | Resched | Goal | Error |")
    print("|---|--------|------|-----|---------|------|-------|")
    for r in rows:
        print(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} |")

    return 0 if n_pass == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
