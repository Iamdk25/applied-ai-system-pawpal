import os

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pawpal_system import Owner, Pet, Task, Scheduler

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

st.title("🐾 PawPal+")

st.markdown(
    """
Welcome to the PawPal+ starter app.

This file is intentionally thin. It gives you a working Streamlit app so you can start quickly,
but **it does not implement the project logic**. Your job is to design the system and build it.

Use this app as your interactive demo once your backend classes/functions exist.
"""
)

with st.expander("Scenario", expanded=True):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.

You will design and implement the scheduling logic and connect it to this Streamlit UI.
"""
    )

with st.expander("What you need to build", expanded=True):
    st.markdown(
        """
At minimum, your system should:
- Represent pet care tasks (what needs to happen, how long it takes, priority)
- Represent the pet and the owner (basic info and preferences)
- Build a plan/schedule for a day that chooses and orders tasks based on constraints
- Explain the plan (why each task was chosen and when it happens)
"""
    )

st.divider()

# --- Session State Initialization ---
# The Owner object lives here for the entire browser session.
# The if-guard means it is only created once — never overwritten on rerun.
if "owner" not in st.session_state:
    st.session_state.owner = Owner("Jordan", "")

owner = st.session_state.owner  # convenient shorthand used throughout
scheduler = Scheduler(owner)    # shared across the AI Planner and Build Schedule sections

# ------------------------------------------------------------------
# SECTION 1 — Add a Pet
# ------------------------------------------------------------------
st.subheader("Add a Pet")

owner_name = st.text_input("Owner name", value=owner.name)
pet_name   = st.text_input("Pet name",   value="Mochi")
species    = st.selectbox("Species", ["dog", "cat", "other"])
pet_age    = st.number_input("Age (years)", min_value=0, max_value=30, value=1)

if st.button("Add Pet"):
    # 1. Build a Pet object from the form values
    new_pet = Pet(name=pet_name, species=species, age=pet_age)

    # 2. owner.add_pet() is the method from pawpal_system.py that appends
    #    the Pet to owner.pets — this is the single source of truth.
    owner.add_pet(new_pet)

    # 3. Also update the owner's display name if the user changed it.
    owner.name = owner_name

    # 4. Streamlit re-runs from top to bottom after the button click,
    #    so simply writing below is enough to "refresh" the pet list.
    st.success(f"Added {new_pet.name} ({new_pet.species}) to {owner.name}'s profile!")

# Always show the current pet list so the user sees the effect immediately.
current_pets = owner.get_pets()
if current_pets:
    st.write("**Registered pets:**")
    for pet in current_pets:
        col_info, col_btn = st.columns([4, 1])
        with col_info:
            st.write(f"**{pet.name}** — {pet.species}, {pet.age} yr(s)")
        with col_btn:
            if st.button("Remove", key=f"remove_pet_{pet.name}"):
                # owner.remove_pet() is the method from pawpal_system.py
                owner.remove_pet(pet)
                st.rerun()
else:
    st.info("No pets yet. Fill in the form above and click 'Add Pet'.")

st.divider()

# ------------------------------------------------------------------
# SECTION 2 — Add a Task to a Pet
# ------------------------------------------------------------------
st.subheader("Add a Task")
st.caption("Pick a pet and describe the task. This calls pet.add_task() behind the scenes.")

if not current_pets:
    st.warning("Add at least one pet before adding tasks.")
else:
    from datetime import datetime

    pet_options = {p.name: p for p in current_pets}
    selected_pet_name = st.selectbox("Assign task to", list(pet_options.keys()))

    col1, col2, col3 = st.columns(3)
    with col1:
        task_title = st.text_input("Task title", value="Morning walk")
    with col2:
        task_category = st.selectbox("Category", ["walk", "feeding", "medication", "appointment"])
    with col3:
        task_freq = st.selectbox("Frequency", ["daily", "once", "weekly"])

    task_desc     = st.text_input("Description", value="")
    task_due_time = st.time_input("Due time", value=datetime.now().replace(second=0, microsecond=0))

    if st.button("Add Task"):
        # Combine today's date with the chosen time to make a full datetime
        due_datetime = datetime.combine(datetime.today(), task_due_time)

        # Build the Task object — priority is inferred automatically by __post_init__
        new_task = Task(
            title=task_title,
            description=task_desc,
            due_time=due_datetime,
            frequency=task_freq,
            category=task_category,
        )

        # pet.add_task() appends the Task to the pet's internal task list
        target_pet = pet_options[selected_pet_name]
        target_pet.add_task(new_task)

        st.success(
            f"Added '{new_task.title}' ({new_task.priority} priority) "
            f"to {target_pet.name} at {task_due_time.strftime('%H:%M')}."
        )

    # Show this pet's current tasks so the user sees the update right away
    target_pet = pet_options[selected_pet_name]
    pet_tasks = target_pet.get_tasks()
    if pet_tasks:
        st.write(f"**{target_pet.name}'s tasks:**")
        for i, task in enumerate(pet_tasks):
            col_info, col_btn = st.columns([4, 1])
            with col_info:
                st.write(
                    f"**{task.title}** — {task.category}, "
                    f"{task.priority} priority, due {task.due_time.strftime('%H:%M')}"
                )
            with col_btn:
                if st.button("Remove", key=f"remove_task_{target_pet.name}_{i}_{task.title}"):
                    # pet.remove_task() is the method from pawpal_system.py
                    target_pet.remove_task(task)
                    st.rerun()
    else:
        st.info(f"No tasks for {target_pet.name} yet.")

st.divider()

# ------------------------------------------------------------------
# SECTION 2.5 — AI Planner (agentic workflow)
# ------------------------------------------------------------------
st.subheader("🤖 AI Planner (agentic)")
st.caption(
    "Describe a high-level care goal and the agent will draft a 7-day plan, "
    "check it against your existing schedule for conflicts, and revise until clean. "
    "You confirm before any tasks are added."
)

# Check for GEMINI_API_KEY
_api_key = os.environ.get("GEMINI_API_KEY")
if not _api_key:
    try:
        _api_key = st.secrets.get("GEMINI_API_KEY")  # type: ignore[attr-defined]
    except Exception:
        _api_key = None

if not _api_key:
    st.info(
        "Set `GEMINI_API_KEY` in `.env` (copy `.env.example`) "
        "or in Streamlit secrets to enable the AI Planner."
    )
elif not current_pets:
    st.info("Add at least one pet before using the AI Planner.")
else:
    ai_pet_name = st.selectbox(
        "Plan for which pet?",
        [p.name for p in current_pets],
        key="ai_pet_select",
    )
    ai_goal = st.text_area(
        "Care goal",
        placeholder="e.g. 'Help my senior dog lose weight over the next week'",
        max_chars=500,
        key="ai_goal",
    )
    col_run, col_iter = st.columns([1, 2])
    with col_iter:
        ai_max_iter = st.slider("Max revisions", 1, 5, 3, key="ai_max_iter")
    with col_run:
        run_clicked = st.button(
            "Generate plan", type="primary",
            disabled=not (ai_goal and ai_goal.strip()),
        )

    if run_clicked:
        from pawpal_agent import run_planner_agent
        target_pet = next(p for p in current_pets if p.name == ai_pet_name)
        with st.spinner("Planner is drafting and reviewing your plan..."):
            try:
                result = run_planner_agent(
                    goal=ai_goal,
                    pet=target_pet,
                    scheduler=scheduler,
                    max_iterations=ai_max_iter,
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Agent failed: {exc}")
                result = None
        if result is not None:
            st.session_state.last_agent_result = result
            st.session_state.last_agent_pet_name = ai_pet_name

    result = st.session_state.get("last_agent_result")
    if result is not None:
        if result.success:
            st.success(
                f"Plan ready for **{result.pet_name}** "
                f"(after {len(result.steps)} iteration(s)). "
                "Review below and click Confirm to add it to the schedule."
            )
        elif result.error == "max_iterations_exceeded":
            st.warning(
                f"Agent could not produce a conflict-free plan in "
                f"{len(result.steps)} iteration(s). See the trace below."
            )
        elif result.error and result.error.startswith("invalid_goal"):
            st.error(f"Goal rejected by guardrails: {result.error}")
        else:
            st.error(f"Agent failed: {result.error}")

        # ── Reasoning trace (default-expanded on failure) ─────────────
        with st.expander("Agent reasoning trace", expanded=not result.success):
            for step in result.steps:
                badge = "✅ PASSED" if step.review_passed else "🔁 REVISING"
                st.markdown(
                    f"**Iteration {step.iteration}** — {badge} "
                    f"({step.latency_ms} ms)"
                )
                if step.llm_reasoning:
                    st.caption(f"Reasoning: {step.llm_reasoning}")
                if step.proposed_new_tasks:
                    st.write(f"Proposed {len(step.proposed_new_tasks)} new task(s):")
                    for t in step.proposed_new_tasks:
                        st.write(
                            f"  • `{t.due_time.strftime('%a %b %d · %I:%M %p')}` "
                            f"[{t.category}] **{t.title}** ({t.frequency})"
                        )
                if step.proposed_reschedules:
                    st.write(f"Proposed {len(step.proposed_reschedules)} reschedule(s):")
                    for old_task, new_time in step.proposed_reschedules:
                        st.write(
                            f"  • Move **{old_task.title}** "
                            f"from `{old_task.due_time.strftime('%a %b %d %I:%M %p')}` "
                            f"→ `{new_time.strftime('%a %b %d %I:%M %p')}`"
                        )
                if step.review_feedback:
                    for w in step.review_feedback:
                        st.warning(w)
                st.divider()

        # ── Confirmation panel (only on success) ──────────────────────
        if result.success and result.requires_confirmation:
            st.markdown("**Confirm and apply?**")
            st.write(
                f"This will add **{len(result.final_new_tasks)}** new task(s) "
                f"and reschedule **{len(result.final_reschedules)}** existing task(s)."
            )
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("✅ Confirm & Apply", type="primary", key="ai_confirm"):
                    from pawpal_agent import commit_agent_result
                    target_pet = next(
                        p for p in current_pets
                        if p.name == st.session_state.get("last_agent_pet_name", "")
                    )
                    commit_agent_result(result, target_pet)
                    st.session_state.last_agent_result = None
                    st.session_state.completion_msg = (
                        f"AI plan applied to {target_pet.name}: "
                        f"{len(result.final_new_tasks)} added, "
                        f"{len(result.final_reschedules)} rescheduled."
                    )
                    st.rerun()
            with col_no:
                if st.button("❌ Discard", key="ai_discard"):
                    st.session_state.last_agent_result = None
                    st.rerun()

st.divider()

# ------------------------------------------------------------------
# SECTION 3 — Schedule: sort, filter, complete, conflict detection
# ------------------------------------------------------------------
st.subheader("Build Schedule")

all_tasks = owner.get_all_tasks()

# Persist the completion message across the rerun triggered by st.rerun()
if "completion_msg" not in st.session_state:
    st.session_state.completion_msg = None

if not all_tasks:
    st.info("No tasks yet. Add pets and tasks above, then come back here.")
else:
    # ── Show completion message from the previous rerun ───────────
    if st.session_state.completion_msg:
        st.success(st.session_state.completion_msg)
        st.session_state.completion_msg = None

    # ── Conflict warnings (30-minute window) ─────────────────────
    conflict_warnings = scheduler.get_conflict_warnings(window_minutes=30)
    if conflict_warnings:
        st.error(f"⚠️ {len(conflict_warnings)} scheduling conflict(s) detected (within 30 min):")
        for w in conflict_warnings:
            st.warning(w)
    else:
        st.success("No scheduling conflicts found.")

    st.divider()

    # ── Filters and sort order ────────────────────────────────────
    col_filter, col_sort = st.columns(2)
    with col_filter:
        pet_filter_options = ["All pets"] + [p.name for p in owner.get_pets()]
        pet_filter = st.selectbox("Filter by pet", pet_filter_options, key="filter_pet")
    with col_sort:
        sort_order = st.radio("Sort by", ["Time", "Priority"], horizontal=True, key="sort_order")
    pet_arg = None if pet_filter == "All pets" else pet_filter

    # Build task → pet-name lookup once (O(n)) before any loops
    task_to_pet = {
        id(t): pet.name
        for pet in owner.get_pets()
        for t in pet.tasks
    }

    def render_task_row(task, index):
        """Render one task row with date+time and a Done button if pending."""
        pet_name = task_to_pet.get(id(task), "?")
        due_str  = task.due_time.strftime("%a %b %d · %I:%M %p")   # date + time
        freq_tag = f"({task.frequency})"
        overdue  = task.is_overdue()
        label    = f"`{due_str}` [{task.priority.upper()}] **{task.title}** — {pet_name} {freq_tag}"
        col_info, col_btn = st.columns([5, 1])
        with col_info:
            if overdue:
                st.warning(f"OVERDUE · {label}")
            else:
                st.write(label)
        with col_btn:
            if st.button("Done", key=f"complete_{pet_name}_{index}_{task.title}"):
                next_task = scheduler.mark_task_complete(task)
                if next_task:
                    next_date = next_task.due_time.strftime("%a %b %d · %I:%M %p")
                    st.session_state.completion_msg = (
                        f"'{task.title}' marked done! "
                        f"Next {task.frequency} occurrence auto-scheduled → {next_date}"
                    )
                else:
                    st.session_state.completion_msg = (
                        f"'{task.title}' marked complete (one-time task, no recurrence)."
                    )
                st.rerun()

    # ── Section A: Upcoming (pending) tasks ───────────────────────
    pending = scheduler.filter_tasks(pet_name=pet_arg, status="pending")
    if sort_order == "Priority":
        from pawpal_system import PRIORITY_ORDER
        pending = sorted(pending, key=lambda t: (PRIORITY_ORDER.get(t.priority, 1), t.due_time))
    sort_label = "by priority then time" if sort_order == "Priority" else "by date & time"
    st.markdown(f"**Upcoming — {len(pending)} task(s)** *({sort_label})*")
    if pending:
        for i, task in enumerate(pending):
            render_task_row(task, i)
    else:
        st.info("No pending tasks — all done!")

    st.divider()

    # ── Section B: Completed tasks (collapsed by default) ─────────
    completed = scheduler.filter_tasks(pet_name=pet_arg, status="completed")
    with st.expander(f"Completed — {len(completed)} task(s)"):
        if completed:
            for task in completed:
                pet_name = task_to_pet.get(id(task), "?")
                due_str  = task.due_time.strftime("%a %b %d · %I:%M %p")
                st.write(
                    f"~~`{due_str}` [{task.priority.upper()}] "
                    f"{task.title} — {pet_name} ({task.frequency})~~"
                )
        else:
            st.write("Nothing completed yet.")
