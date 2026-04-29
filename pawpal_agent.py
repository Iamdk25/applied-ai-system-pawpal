"""PawPal+ Planner Agent — turns a high-level care goal into a 7-day schedule.

Workflow: Planner (LLM, structured function calling) → Reviewer (deterministic
Scheduler.validate_proposed_changes) → Revise loop (max N iterations) → stage
result for UI confirmation → commit_agent_result applies it to the pet.

Uses the Google Gemini API (google-genai SDK) for structured plan generation.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple

from pawpal_system import Pet, Scheduler, Task
from agent_logging import log_event


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL = os.getenv("PAWPAL_AGENT_MODEL", "gemini-2.5-flash")
DEFAULT_MAX_ITERATIONS = 3
DEFAULT_DAYS_AHEAD = 7
CONFLICT_WINDOW_MINUTES = 30

_MIN_GOAL_LEN = 5
_MAX_GOAL_LEN = 500
_BANNED_TOKENS = (
    "ignore previous",
    "ignore all previous",
    "disregard previous",
    "disregard all previous",
    "forget previous",
    "forget your instructions",
    "override instructions",
    "new instructions",
    "you are now",
    "act as",
    "pretend you",
    "system prompt",
    "reveal your prompt",
    "<script",
    "drop table",
    "jailbreak",
)
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

VALID_CATEGORIES = {"feeding", "walk", "medication", "appointment"}
VALID_FREQUENCIES = {"once", "daily", "weekly"}


# ---------------------------------------------------------------------------
# Function declaration for Gemini function calling
# ---------------------------------------------------------------------------

SUBMIT_PLAN_FUNCTION_DECLARATION = {
    "name": "submit_plan",
    "description": (
        "Submit a multi-day pet care plan. May add new tasks and/or reschedule "
        "existing tasks. Always called exactly once."
    ),
    "parameters": {
        "type": "object",
        "required": ["reasoning", "new_tasks", "reschedules"],
        "properties": {
            "reasoning": {
                "type": "string",
                "description": "1-3 sentence justification of why this plan addresses the goal.",
            },
            "new_tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "title", "description", "category",
                        "frequency", "day_offset", "time_of_day",
                    ],
                    "properties": {
                        "title": {"type": "string", "description": "Task title, 1-80 chars"},
                        "description": {"type": "string", "description": "Task description, max 240 chars"},
                        "category": {
                            "type": "string",
                            "enum": list(VALID_CATEGORIES),
                            "description": "Task category",
                        },
                        "frequency": {
                            "type": "string",
                            "enum": list(VALID_FREQUENCIES),
                            "description": "How often the task recurs",
                        },
                        "day_offset": {
                            "type": "integer",
                            "description": "Days from today (0 = today, max 6).",
                        },
                        "time_of_day": {
                            "type": "string",
                            "description": "24-hour HH:MM format, e.g. '08:00' or '14:30'.",
                        },
                    },
                },
                "description": "New tasks to add (max 30).",
            },
            "reschedules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "existing_task_title", "existing_due_time",
                        "new_day_offset", "new_time_of_day",
                    ],
                    "properties": {
                        "existing_task_title": {"type": "string"},
                        "existing_due_time": {
                            "type": "string",
                            "description": "ISO datetime of the task to move (must match a current pending task).",
                        },
                        "new_day_offset": {"type": "integer", "description": "Days from today (0-6)"},
                        "new_time_of_day": {
                            "type": "string",
                            "description": "24-hour HH:MM.",
                        },
                    },
                },
                "description": "Existing tasks to reschedule (max 10).",
            },
        },
    },
}


SYSTEM_PROMPT = """\
You are a veterinary care planner. Given a pet profile and a high-level care goal,
produce a concrete 7-day plan of tasks the owner should perform.

Rules:
- Only use these categories: feeding, walk, medication, appointment.
- Frequencies are once, daily, or weekly.
- Avoid scheduling tasks within 30 minutes of the owner's existing commitments
  (you will be told what those are).
- Spread tasks reasonably across the day; do not stack three tasks at the same minute.
- Prefer ADDING new tasks. Only reschedule an existing task if doing so is
  necessary to fit the goal — and never reschedule appointments.
- If you receive REVIEWER FEEDBACK, you MUST adjust the conflicting times in
  your next response.
- You MUST submit your plan via the submit_plan function. Do not respond with text only.
"""


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AgentStep:
    iteration: int
    proposed_new_tasks: List[Task]
    proposed_reschedules: List[Tuple[Task, datetime]]
    review_passed: bool
    review_feedback: List[str]
    llm_reasoning: str
    raw_tool_input: dict
    latency_ms: int = 0


@dataclass
class AgentResult:
    success: bool
    steps: List[AgentStep]
    final_new_tasks: List[Task] = field(default_factory=list)
    final_reschedules: List[Tuple[Task, datetime]] = field(default_factory=list)
    goal: str = ""
    pet_name: str = ""
    error: Optional[str] = None
    requires_confirmation: bool = True


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

def _validate_goal(goal: str) -> Optional[str]:
    """Return None if goal is acceptable, else a short error string."""
    if goal is None or not goal.strip():
        return "invalid_goal: empty goal"
    stripped = goal.strip()
    if len(stripped) < _MIN_GOAL_LEN:
        return f"invalid_goal: too short (min {_MIN_GOAL_LEN} chars)"
    if len(stripped) > _MAX_GOAL_LEN:
        return f"invalid_goal: too long (max {_MAX_GOAL_LEN} chars)"
    lowered = stripped.lower()
    for banned in _BANNED_TOKENS:
        if banned in lowered:
            return f"invalid_goal: contains banned token '{banned}'"
    return None


# ---------------------------------------------------------------------------
# Prompt building helpers
# ---------------------------------------------------------------------------

def _summarize_existing_tasks(pet: Pet, days: int = 14) -> str:
    """Compact summary of upcoming pending tasks for the target pet only."""
    now = datetime.now()
    cutoff = now + timedelta(days=days)
    pending = [
        t for t in pet.get_pending_tasks()
        if t.due_time <= cutoff
    ]
    if not pending:
        return "(none)"
    pending.sort(key=lambda t: t.due_time)
    lines = []
    for t in pending:
        lines.append(
            f"- '{t.title}' ({t.category}, {t.frequency}) "
            f"at {t.due_time.strftime('%a %b %d %H:%M')}"
        )
    return "\n".join(lines)


def _build_user_prompt(
    *,
    goal: str,
    pet: Pet,
    existing_summary: str,
    prior_feedback: List[str],
    iteration: int,
) -> str:
    parts = [
        f"Pet: {pet.name} ({pet.species}, age {pet.age})",
        f"Goal: {goal.strip()}",
        "",
        "Existing scheduled tasks (avoid 30-min conflicts with these):",
        existing_summary,
    ]
    if prior_feedback:
        parts.extend([
            "",
            f"REVIEWER FEEDBACK (iteration {iteration - 1}):",
            "The previous plan had these conflicts. Adjust the offending times:",
        ])
        for w in prior_feedback:
            parts.append(f"- {w}")
    parts.extend([
        "",
        "Submit your plan via the submit_plan function.",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parsing LLM output → Task / reschedule tuples
# ---------------------------------------------------------------------------

class PlanParseError(ValueError):
    pass


def _extract_first_json(text: str) -> str | None:
    """Find the first balanced JSON object in text and return it as a string."""
    if not isinstance(text, str):
        return None
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i+1]
    return None


def _extract_tool_input(response: Any) -> dict:
    """Pull the submit_plan function call args from a Gemini response.

    Works with both real Gemini responses and FakeClient SimpleNamespace
    responses (used in tests).
    """
    # --- Path A: FakeClient / Anthropic-shaped response ---
    # Check for stop_reason='tool_use' (test FakeClient format)
    if getattr(response, "stop_reason", None) == "tool_use":
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_plan":
                payload = getattr(block, "input", None)
                if not isinstance(payload, dict):
                    raise PlanParseError("tool_use block has no dict input")
                return payload
        raise PlanParseError("no submit_plan tool_use block in response")

    # --- Path B: Real Gemini response ---
    # Search all candidates and all parts for the submit_plan function call
    try:
        candidates = response.candidates or []
        for candidate in candidates:
            parts = getattr(candidate, "content", None)
            if parts is not None:
                parts = getattr(parts, "parts", None) or []
            else:
                parts = []
            for part in parts:
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    name = getattr(fc, "name", None)
                    if name == "submit_plan":
                        args = getattr(fc, "args", None)
                        if isinstance(args, dict):
                            return args
                        # Some SDK versions return a proto MapComposite
                        return dict(args)
    except (AttributeError, IndexError, TypeError):
        pass

    # --- Path C: Try to extract JSON from text response ---
    try:
        text = response.text
        if text:
            snippet = _extract_first_json(text)
            if snippet:
                parsed = json.loads(snippet)
                if isinstance(parsed, dict) and ("new_tasks" in parsed or "reasoning" in parsed):
                    return parsed
    except (AttributeError, json.JSONDecodeError):
        pass

    raise PlanParseError("no submit_plan function call found in response")


def _compose_due_time(day_offset: int, time_of_day: str, today: datetime) -> datetime:
    """Combine a day_offset + HH:MM into a concrete datetime, clipping past times."""
    if not _TIME_RE.match(time_of_day):
        raise PlanParseError(f"bad time_of_day {time_of_day!r}")
    hh, mm = time_of_day.split(":")
    base = (today + timedelta(days=day_offset)).replace(
        hour=int(hh), minute=int(mm), second=0, microsecond=0,
    )
    # If the LLM picks day_offset=0 at a time already past, push to tomorrow.
    if base < today:
        base += timedelta(days=1)
    return base


def _parse_proposed(
    payload: dict,
    pet: Pet,
    today: datetime,
) -> Tuple[List[Task], List[Tuple[Task, datetime]], str]:
    """Convert validated tool input into Task objects + reschedule tuples."""
    if not isinstance(payload, dict):
        raise PlanParseError("payload is not a dict")
    reasoning = str(payload.get("reasoning", "")).strip()

    raw_new = payload.get("new_tasks") or []
    raw_resched = payload.get("reschedules") or []
    if not isinstance(raw_new, list) or not isinstance(raw_resched, list):
        raise PlanParseError("new_tasks/reschedules must be lists")
    if not raw_new and not raw_resched:
        raise PlanParseError("plan has no new tasks and no reschedules")

    new_tasks: List[Task] = []
    for item in raw_new:
        if not isinstance(item, dict):
            raise PlanParseError("new_tasks item is not a dict")
        category = str(item.get("category", ""))
        frequency = str(item.get("frequency", ""))
        if category not in VALID_CATEGORIES:
            raise PlanParseError(f"invalid category {category!r}")
        if frequency not in VALID_FREQUENCIES:
            raise PlanParseError(f"invalid frequency {frequency!r}")
        title = str(item.get("title", "")).strip()
        if not title:
            raise PlanParseError("new task missing title")
        description = str(item.get("description", "")).strip()
        try:
            day_offset = int(item["day_offset"])
        except (KeyError, ValueError, TypeError) as exc:
            raise PlanParseError(f"bad day_offset: {exc}")
        time_of_day = str(item.get("time_of_day", ""))
        due = _compose_due_time(day_offset, time_of_day, today)
        new_tasks.append(Task(
            title=title,
            description=description,
            due_time=due,
            frequency=frequency,
            category=category,
        ))

    reschedules: List[Tuple[Task, datetime]] = []
    pending_by_key = {
        (t.title, t.due_time.replace(microsecond=0)): t
        for t in pet.get_pending_tasks()
    }
    for item in raw_resched:
        if not isinstance(item, dict):
            raise PlanParseError("reschedules item is not a dict")
        title = str(item.get("existing_task_title", "")).strip()
        existing_iso = str(item.get("existing_due_time", "")).strip()
        try:
            existing_dt = datetime.fromisoformat(existing_iso).replace(microsecond=0)
        except ValueError as exc:
            raise PlanParseError(f"bad existing_due_time {existing_iso!r}: {exc}")
        match = pending_by_key.get((title, existing_dt))
        if match is None:
            raise PlanParseError(
                f"reschedule target not found for '{title}' at {existing_iso}"
            )
        try:
            new_day_offset = int(item["new_day_offset"])
        except (KeyError, ValueError, TypeError) as exc:
            raise PlanParseError(f"bad new_day_offset: {exc}")
        new_time_of_day = str(item.get("new_time_of_day", ""))
        new_due = _compose_due_time(new_day_offset, new_time_of_day, today)
        reschedules.append((match, new_due))

    return new_tasks, reschedules, reasoning


# ---------------------------------------------------------------------------
# Planner LLM call (Google Gemini via google-genai SDK)
# ---------------------------------------------------------------------------

def _planner_call(
    *,
    client: Any,
    model: str,
    goal: str,
    pet: Pet,
    existing_summary: str,
    prior_feedback: List[str],
    iteration: int,
) -> Any:
    """One LLM call. Uses Gemini function calling for structured output.

    If `client` has a `messages` attribute (FakeClient from tests), we use
    the Anthropic-compatible path. Otherwise we use the real google-genai SDK.
    """
    user_msg = _build_user_prompt(
        goal=goal, pet=pet,
        existing_summary=existing_summary,
        prior_feedback=prior_feedback,
        iteration=iteration,
    )

    # --- FakeClient path (for tests) ---
    if hasattr(client, "messages") and hasattr(client.messages, "create"):
        # This is the test FakeClient — call the Anthropic-shaped API
        return client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[SUBMIT_PLAN_FUNCTION_DECLARATION],
            tool_choice={"type": "tool", "name": "submit_plan"},
            messages=[{"role": "user", "content": user_msg}],
        )

    # --- Real Gemini SDK path ---
    from google.genai import types

    tools = types.Tool(function_declarations=[SUBMIT_PLAN_FUNCTION_DECLARATION])
    # Force the model to always call the function (like Anthropic's tool_choice)
    tool_config = types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode="ANY",
            allowed_function_names=["submit_plan"],
        )
    )
    config = types.GenerateContentConfig(
        tools=[tools],
        tool_config=tool_config,
        system_instruction=SYSTEM_PROMPT,
        temperature=0.5,
    )

    combined_prompt = user_msg
    last_exc: Optional[Exception] = None
    for attempt in range(2):  # one retry on transient API error
        try:
            return client.models.generate_content(
                model=model,
                contents=combined_prompt,
                config=config,
            )
        except Exception as exc:
            last_exc = exc
            log_event(
                "agent.api_error",
                level="WARNING",
                attempt=attempt + 1,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"planner_call_failed: {last_exc}")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _default_client() -> Any:
    """Create a Google Gemini client using the google-genai SDK."""
    gem_key = os.getenv("GEMINI_API_KEY")
    if not gem_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Add it to .env or your shell environment."
        )
    from google import genai
    return genai.Client(api_key=gem_key)


def run_planner_agent(
    *,
    goal: str,
    pet: Pet,
    scheduler: Scheduler,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    days_ahead: int = DEFAULT_DAYS_AHEAD,
    client: Any = None,
    model: Optional[str] = None,
) -> AgentResult:
    """Run the Planner → Reviewer → Revise loop.

    Returns an AgentResult. On success, the result is STAGED — call
    commit_agent_result(result, pet) to actually apply it. On failure (guardrails,
    max iterations, or API errors), nothing is committed and the trace is
    available in result.steps.
    """
    model = model or DEFAULT_MODEL
    today = datetime.now().replace(second=0, microsecond=0)
    steps: List[AgentStep] = []

    err = _validate_goal(goal)
    if err is not None:
        log_event("agent.guardrail_rejected", level="WARNING",
                  goal=goal, pet=pet.name, error=err)
        return AgentResult(
            success=False, steps=[], goal=goal, pet_name=pet.name, error=err,
            requires_confirmation=False,
        )

    if client is None:
        try:
            client = _default_client()
        except Exception as exc:  # noqa: BLE001
            err = f"client_init_failed: {exc}"
            log_event("agent.api_error", level="ERROR", error=err)
            return AgentResult(
                success=False, steps=[], goal=goal, pet_name=pet.name,
                error=err, requires_confirmation=False,
            )

    log_event("agent.start", goal=goal, pet=pet.name, model=model,
              max_iterations=max_iterations)

    existing_summary = _summarize_existing_tasks(pet, days=days_ahead * 2)
    prior_feedback: List[str] = []

    for iteration in range(1, max_iterations + 1):
        t0 = time.monotonic()
        log_event("planner.request", iteration=iteration, model=model,
                  goal_len=len(goal))
        try:
            response = _planner_call(
                client=client, model=model, goal=goal, pet=pet,
                existing_summary=existing_summary,
                prior_feedback=prior_feedback,
                iteration=iteration,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc_str = str(exc)
            log_event("agent.api_error", level="WARNING",
                      attempt=1, error=last_exc_str)
            # If this looks like a quota / rate limit / 429 error,
            # provide a deterministic local fallback plan
            quota_indicators = ("quota", "429", "rate limit", "Quota exceeded",
                                "RESOURCE_EXHAUSTED")
            if any(ind.lower() in last_exc_str.lower() for ind in quota_indicators):
                log_event("agent.local_fallback", reason="quota_or_rate_limit",
                          detail=last_exc_str)
                fallback_tasks = _local_plan(goal, days_ahead)
                log_event("agent.fallback_applied", n_new=len(fallback_tasks))
                return AgentResult(
                    success=True, steps=steps,
                    final_new_tasks=fallback_tasks,
                    final_reschedules=[], goal=goal, pet_name=pet.name,
                    requires_confirmation=True,
                )

            err = f"api_error: {exc}"
            log_event("agent.api_error", level="ERROR",
                      iteration=iteration, error=err)
            return AgentResult(
                success=False, steps=steps, goal=goal, pet_name=pet.name,
                error=err, requires_confirmation=False,
            )
        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = getattr(response, "usage_metadata", None) or getattr(response, "usage", None)
        log_event(
            "planner.response",
            iteration=iteration,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "prompt_token_count", None) or getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "candidates_token_count", None) or getattr(usage, "output_tokens", None),
        )

        try:
            payload = _extract_tool_input(response)
            new_tasks, reschedules, reasoning = _parse_proposed(payload, pet, today)
        except PlanParseError as exc:
            log_event("planner.parse_error", level="WARNING",
                      iteration=iteration, error=str(exc))
            steps.append(AgentStep(
                iteration=iteration,
                proposed_new_tasks=[], proposed_reschedules=[],
                review_passed=False,
                review_feedback=[f"Malformed plan: {exc}"],
                llm_reasoning="",
                raw_tool_input={},
                latency_ms=latency_ms,
            ))
            prior_feedback = [f"Your previous response was malformed: {exc}. "
                              "Please retry and fill every required field."]
            continue

        feedback = scheduler.validate_proposed_changes(
            new_tasks, reschedules, window_minutes=CONFLICT_WINDOW_MINUTES,
        )
        passed = not feedback
        steps.append(AgentStep(
            iteration=iteration,
            proposed_new_tasks=new_tasks,
            proposed_reschedules=reschedules,
            review_passed=passed,
            review_feedback=feedback,
            llm_reasoning=reasoning,
            raw_tool_input=payload,
            latency_ms=latency_ms,
        ))
        log_event(
            "reviewer.evaluated",
            iteration=iteration,
            n_new=len(new_tasks),
            n_reschedules=len(reschedules),
            n_conflicts=len(feedback),
            passed=passed,
        )

        if passed:
            log_event("agent.success", iteration=iteration,
                      n_new=len(new_tasks), n_reschedules=len(reschedules))
            return AgentResult(
                success=True, steps=steps,
                final_new_tasks=new_tasks,
                final_reschedules=reschedules,
                goal=goal, pet_name=pet.name,
                requires_confirmation=True,
            )
        prior_feedback = feedback

    log_event("agent.max_iterations", iterations=max_iterations,
              goal=goal, pet=pet.name)
    # If the LLM failed to produce any structured proposals across all
    # iterations, fall back to a deterministic local planner
    all_empty = all((not s.proposed_new_tasks and not s.proposed_reschedules) for s in steps)
    if all_empty:
        log_event("agent.local_fallback", reason="no_structured_output")
        fallback_tasks = _local_plan(goal, days_ahead)
        return AgentResult(
            success=True, steps=steps,
            final_new_tasks=fallback_tasks,
            final_reschedules=[], goal=goal, pet_name=pet.name,
            requires_confirmation=True,
        )

    return AgentResult(
        success=False, steps=steps, goal=goal, pet_name=pet.name,
        error="max_iterations_exceeded",
        requires_confirmation=False,
    )


# ---------------------------------------------------------------------------
# Local fallback planner (no API needed)
# ---------------------------------------------------------------------------

def _local_plan(goal_text: str, days_ahead: int = 7) -> List[Task]:
    """Generate a deterministic goal-aware plan when the API is unavailable."""
    today = datetime.now().replace(second=0, microsecond=0)
    goal_l = goal_text.lower()
    tasks: List[Task] = []

    # Defaults
    meal_times = ["08:00", "18:00"]
    walk_times = ["07:00"]
    med_time = None

    # Goal-aware tweaks
    if any(k in goal_l for k in ("weight", "lose weight", "diet", "overweight")):
        walk_times = ["07:00", "18:00"]
        meal_times = ["07:30", "17:30"]
    if any(k in goal_l for k in ("potty", "potty training", "housebreaking", "toilet")):
        walk_times = ["07:00", "12:00", "17:00", "20:00"]
        meal_times = ["07:00", "12:00", "18:00"]
    if any(k in goal_l for k in ("medicat", "pill", "medicine", "medication")):
        med_time = "09:00"

    for d in range(days_ahead):
        for hhmm in meal_times:
            hh, mm = hhmm.split(":")
            due = (today + timedelta(days=d)).replace(hour=int(hh), minute=int(mm))
            tasks.append(Task(
                title="Feeding",
                description=f"Auto-scheduled feeding ({goal_text})",
                due_time=due,
                frequency="daily",
                category="feeding",
            ))
        for hhmm in walk_times:
            hh, mm = hhmm.split(":")
            due = (today + timedelta(days=d)).replace(hour=int(hh), minute=int(mm))
            tasks.append(Task(
                title="Walk",
                description=f"Walk for exercise ({goal_text})",
                due_time=due,
                frequency="daily",
                category="walk",
            ))
        if med_time:
            hh, mm = med_time.split(":")
            due = (today + timedelta(days=d)).replace(hour=int(hh), minute=int(mm))
            tasks.append(Task(
                title="Medication",
                description=f"Administer medication ({goal_text})",
                due_time=due,
                frequency="daily",
                category="medication",
            ))
    return tasks


# ---------------------------------------------------------------------------
# Commit (called from UI after user confirms)
# ---------------------------------------------------------------------------

def commit_agent_result(result: AgentResult, pet: Pet) -> None:
    """Apply a successful AgentResult to the pet. Idempotency is the caller's job."""
    if not result.success:
        raise ValueError("cannot commit a failed AgentResult")
    for existing_task, new_time in result.final_reschedules:
        existing_task.update_time(new_time)
    for task in result.final_new_tasks:
        pet.add_task(task)
    log_event(
        "agent.committed",
        pet=pet.name, goal=result.goal,
        n_new=len(result.final_new_tasks),
        n_reschedules=len(result.final_reschedules),
    )
