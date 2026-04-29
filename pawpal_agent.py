"""PawPal+ Planner Agent — turns a high-level care goal into a 7-day schedule.

Workflow: Planner (LLM, structured tool_use) → Reviewer (deterministic
Scheduler.validate_proposed_changes) → Revise loop (max N iterations) → stage
result for UI confirmation → commit_agent_result applies it to the pet.
"""

from __future__ import annotations

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

DEFAULT_MODEL = os.getenv("PAWPAL_AGENT_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_ITERATIONS = 3
DEFAULT_DAYS_AHEAD = 7
CONFLICT_WINDOW_MINUTES = 30

_MIN_GOAL_LEN = 5
_MAX_GOAL_LEN = 500
_BANNED_TOKENS = (
    "ignore previous",
    "ignore all previous",
    "system prompt",
    "<script",
    "drop table",
)
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

VALID_CATEGORIES = {"feeding", "walk", "medication", "appointment"}
VALID_FREQUENCIES = {"once", "daily", "weekly"}


# ---------------------------------------------------------------------------
# Tool schema (forces structured JSON via tool_choice)
# ---------------------------------------------------------------------------

SUBMIT_PLAN_TOOL: dict = {
    "name": "submit_plan",
    "description": (
        "Submit a multi-day pet care plan. May add new tasks and/or reschedule "
        "existing tasks. Always called exactly once."
    ),
    "input_schema": {
        "type": "object",
        "required": ["reasoning", "new_tasks", "reschedules"],
        "properties": {
            "reasoning": {
                "type": "string",
                "description": "1-3 sentence justification of why this plan addresses the goal.",
            },
            "new_tasks": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "required": [
                        "title", "description", "category",
                        "frequency", "day_offset", "time_of_day",
                    ],
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 80},
                        "description": {"type": "string", "maxLength": 240},
                        "category": {
                            "type": "string",
                            "enum": list(VALID_CATEGORIES),
                        },
                        "frequency": {
                            "type": "string",
                            "enum": list(VALID_FREQUENCIES),
                        },
                        "day_offset": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 6,
                            "description": "Days from today (0 = today).",
                        },
                        "time_of_day": {
                            "type": "string",
                            "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$",
                            "description": "24-hour HH:MM.",
                        },
                    },
                },
            },
            "reschedules": {
                "type": "array",
                "maxItems": 10,
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
                        "new_day_offset": {"type": "integer", "minimum": 0, "maximum": 6},
                        "new_time_of_day": {
                            "type": "string",
                            "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$",
                        },
                    },
                },
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
- You MUST submit your plan via the submit_plan tool. Do not respond with text only.
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
    """Compact summary of upcoming pending tasks for the target pet only.

    Capped at 14 days of pending tasks to bound prompt tokens even when the
    user has many.
    """
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
        "Submit your plan via the submit_plan tool.",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parsing LLM output → Task / reschedule tuples
# ---------------------------------------------------------------------------

class PlanParseError(ValueError):
    pass


def _extract_tool_input(response: Any) -> dict:
    """Pull the submit_plan tool input out of an Anthropic Message response."""
    if getattr(response, "stop_reason", None) != "tool_use":
        raise PlanParseError(f"expected stop_reason=tool_use, got {response.stop_reason!r}")
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_plan":
            payload = getattr(block, "input", None)
            if not isinstance(payload, dict):
                raise PlanParseError("tool_use block has no dict input")
            return payload
    raise PlanParseError("no submit_plan tool_use block in response")


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
    """Convert validated-by-schema tool input into Task objects + reschedule tuples.

    The Anthropic tool schema does most validation, but we still defensively
    re-check field types and contents.
    """
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
# Planner LLM call
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
    """One LLM call. Forces submit_plan via tool_choice. Caller handles parsing."""
    user_msg = _build_user_prompt(
        goal=goal, pet=pet,
        existing_summary=existing_summary,
        prior_feedback=prior_feedback,
        iteration=iteration,
    )
    last_exc: Optional[Exception] = None
    for attempt in range(2):  # one retry on transient API error
        try:
            return client.messages.create(
                model=model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=[SUBMIT_PLAN_TOOL],
                tool_choice={"type": "tool", "name": "submit_plan"},
                messages=[{"role": "user", "content": user_msg}],
            )
        except Exception as exc:  # noqa: BLE001 — surface anything to caller
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
    """Lazy import so tests don't need provider packages installed.

    Preference order:
    - If GEMINI_API_KEY is set, return a thin Gemini adapter that implements
      messages.create(...) with a compatible shape used by the rest of this
      module.
    - Otherwise fall back to the Anthropic SDK if available.
    """
    gem_key = os.getenv("GEMINI_API_KEY")
    if gem_key:
        try:
            # Prefer the newer package name if available
            try:
                import google.genai as genai  # type: ignore
            except Exception:
                import google.generativeai as genai  # type: ignore
        except Exception as exc:  # pragma: no cover - runtime environment dependent
            raise RuntimeError(f"gemini_client_import_failed: {exc}")
        # configure the library (some SDK versions use configure)
        try:
            # both SDKs may accept configure or require setting an env var
            if hasattr(genai, 'configure'):
                genai.configure(api_key=gem_key)  # type: ignore
            else:
                import os as _os
                _os.environ['GEMINI_API_KEY'] = gem_key
        except Exception:
            # ignore if not supported
            pass

        # Build a lightweight adapter that exposes .messages.create(...) and
        # returns a response object shape compatible with the Anthropic-based
        # flow used elsewhere in this file.
        class GeminiClientAdapter:
            def __init__(self, genai_lib):
                self._genai = genai_lib
                # messages is an object with a create method to match Anthropic
                class _Msgs:
                    def __init__(self, outer):
                        self._outer = outer

                    def create(self, *, model, max_tokens, system, tools, tool_choice, messages):
                        # Combine system + user into a single prompt when the SDK
                        # doesn't support the exact chat signature. Try several
                        # possible SDK entrypoints for compatibility.
                        user_text = ""
                        if messages and isinstance(messages, list):
                            user_text = messages[0].get("content", "")

                        prompt = f"{system}\n\n{user_text}" if system else user_text

                        text_content = None
                        resp = None

                        # 1) Newer google.genai / google.generativeai: GenerativeModel + chat
                        try:
                            GenModel = getattr(self._outer._genai, 'GenerativeModel', None)
                            if GenModel is not None:
                                model_obj = GenModel(model)
                                # start a chat session and send a single message
                                if hasattr(model_obj, 'start_chat'):
                                    chat = model_obj.start_chat()
                                    resp = chat.send_message(prompt)
                                    text_content = getattr(resp, 'text', None) or (resp.candidates[0].content if getattr(resp, 'candidates', None) else None) or None
                        except Exception:
                            text_content = None

                        # 2) Older helpers: genai.generate(model=..., prompt=...)
                        if text_content is None:
                            try:
                                gen = getattr(self._outer._genai, 'generate', None)
                                if gen is not None:
                                    resp = gen(model=model, prompt=prompt, max_output_tokens=max_tokens)
                                    text_content = getattr(resp, 'text', None) or getattr(resp, 'output', None) or str(resp)
                            except Exception:
                                text_content = None

                        # 3) ChatSession convenience API: ChatSession(model=...) -> send_message
                        if text_content is None:
                            try:
                                ChatSession = getattr(self._outer._genai, 'ChatSession', None)
                                if ChatSession is not None:
                                    # ChatSession requires a model object or name depending on SDK
                                    try:
                                        # prefer passing a model object
                                        model_obj = getattr(self._outer._genai, 'GenerativeModel', None)
                                        if model_obj is not None:
                                            session = self._outer._genai.ChatSession(model_obj(model))
                                        else:
                                            session = self._outer._genai.ChatSession(model)
                                        resp = session.send_message(prompt)
                                        text_content = getattr(resp, 'text', None) or (resp.candidates[0].content if getattr(resp, 'candidates', None) else None) or None
                                    except Exception:
                                        # fallback: try instantiating with string model
                                        session = self._outer._genai.ChatSession(model)
                                        resp = session.send_message(prompt)
                                        text_content = getattr(resp, 'text', None) or (resp.candidates[0].content if getattr(resp, 'candidates', None) else None) or None
                            except Exception:
                                text_content = None

                        # 4) Fallback: stringify whatever we got
                        if text_content is None and resp is not None:
                            try:
                                text_content = str(resp)
                            except Exception:
                                text_content = None

                        if not text_content:
                            try:
                                raw_repr = repr(resp)
                            except Exception:
                                raw_repr = '<unrepresentable response>'
                            raise RuntimeError(f"gemini_no_text_response: raw_response={raw_repr[:1000]!r}")

                        # Extract JSON object
                        import json, re
                        m = re.search(r"\{(?:[^{}]|(?R))*\}", text_content, re.S) or re.search(r"\{.*\}", text_content, re.S)
                        if not m:
                            raise RuntimeError(f"gemini_no_json_in_response: {text_content[:320]!r}")
                        try:
                            payload = json.loads(m.group(0))
                        except Exception as exc:
                            raise RuntimeError(f"gemini_json_parse_failed: {exc}: snippet={m.group(0)[:200]!r}")

                        from types import SimpleNamespace
                        tool_block = SimpleNamespace(type="tool_use", name="submit_plan", input=payload)
                        return SimpleNamespace(stop_reason="tool_use", content=[tool_block], usage=None)

                self.messages = _Msgs(self)

        return GeminiClientAdapter(genai)

    # Fallback to Anthropic if GEMINI_API_KEY not set
    try:
        import anthropic  # type: ignore
    except Exception as exc:  # pragma: no cover - environment may differ
        raise RuntimeError(f"anthropic_client_import_failed: {exc}")

    return anthropic.Anthropic()


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
            client_is_gemini = os.getenv("GEMINI_API_KEY") is not None
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
            # If Gemini returned an unparseable response, attempt an Anthropic
            # fallback (only when a GEMINI_API_KEY was used). This improves
            # reliability while we debug provider differences.
            last_exc_str = str(exc)
            log_event("agent.api_error", level="WARNING",
                      attempt=1, error=last_exc_str)
            if 'gemini_no_text_response' in last_exc_str and os.getenv("GEMINI_API_KEY"):
                try:
                    # Verify Anthropic API key exists before attempting fallback
                    if not os.getenv("ANTHROPIC_API_KEY"):
                        raise RuntimeError(
                            "anthropic_api_key_missing: set ANTHROPIC_API_KEY to enable fallback"
                        )
                    import anthropic as _ant  # type: ignore
                    # Some Anthropic SDKs accept an api_key param; try to use it.
                    try:
                        anth_client = _ant.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
                    except Exception:
                        anth_client = _ant.Anthropic()
                    log_event("agent.fallback", provider="anthropic",
                              reason="gemini_no_text_response")
                    response = _planner_call(
                        client=anth_client, model=model, goal=goal, pet=pet,
                        existing_summary=existing_summary,
                        prior_feedback=prior_feedback,
                        iteration=iteration,
                    )
                except Exception as exc2:  # noqa: BLE001
                    err = f"api_error: {exc2}"
                    log_event("agent.api_error", level="ERROR",
                              iteration=iteration, error=err)
                    return AgentResult(
                        success=False, steps=steps, goal=goal, pet_name=pet.name,
                        error=err, requires_confirmation=False,
                    )
            else:
                err = f"api_error: {exc}"
                log_event("agent.api_error", level="ERROR",
                          iteration=iteration, error=err)
                return AgentResult(
                    success=False, steps=steps, goal=goal, pet_name=pet.name,
                    error=err, requires_confirmation=False,
                )
        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = getattr(response, "usage", None)
        log_event(
            "planner.response",
            iteration=iteration,
            latency_ms=latency_ms,
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
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
    return AgentResult(
        success=False, steps=steps, goal=goal, pet_name=pet.name,
        error="max_iterations_exceeded",
        requires_confirmation=False,
    )


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
