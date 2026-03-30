from datetime import datetime, timedelta
from pawpal_system import Task, Pet, Owner, Scheduler


def make_task(title="Test Task"):
    return Task(
        title=title,
        description="A test task",
        due_time=datetime.now(),
        frequency="once",
        category="feeding",
    )


def test_mark_completed():
    task = make_task()
    assert task.is_completed is False
    task.mark_completed()
    assert task.is_completed is True


def test_add_task_increases_count():
    pet = Pet(name="Buddy", species="Dog", age=2)
    assert len(pet.get_tasks()) == 0
    pet.add_task(make_task())
    assert len(pet.get_tasks()) == 1


# ---------------------------------------------------------------------------
# Helper: build a Scheduler with pets pre-populated from task lists
# ---------------------------------------------------------------------------

def make_scheduler(*tasks_per_pet):
    owner = Owner("Test Owner", "test@example.com")
    for i, tasks in enumerate(tasks_per_pet):
        pet = Pet(name=f"Pet{i}", species="Dog", age=2)
        for t in tasks:
            pet.add_task(t)
        owner.add_pet(pet)
    return Scheduler(owner)


# ---------------------------------------------------------------------------
# Sorting correctness
# ---------------------------------------------------------------------------

def test_sort_by_time_returns_chronological_order():
    now = datetime(2026, 3, 29, 10, 0)
    t1 = Task("Late",   "desc", now + timedelta(hours=2), "once", "feeding")
    t2 = Task("Middle", "desc", now + timedelta(hours=1), "once", "walk")
    t3 = Task("Early",  "desc", now,                      "once", "medication")
    # Tasks added out-of-order intentionally
    scheduler = make_scheduler([t1, t2, t3])

    sorted_tasks = scheduler.sort_by_time()

    due_times = [t.due_time for t in sorted_tasks]
    assert due_times == sorted(due_times), "Tasks must be in ascending due_time order"


# ---------------------------------------------------------------------------
# Recurrence logic
# ---------------------------------------------------------------------------

def test_mark_daily_task_complete_schedules_next_day():
    base_time = datetime(2026, 3, 29, 8, 0)
    task = Task("Morning Feed", "desc", base_time, "daily", "feeding")

    owner = Owner("Test Owner", "test@example.com")
    pet = Pet(name="Rex", species="Dog", age=3)
    pet.add_task(task)
    owner.add_pet(pet)
    scheduler = Scheduler(owner)

    next_task = scheduler.mark_task_complete(task)

    assert task.is_completed is True
    assert next_task is not None
    assert next_task.due_time == base_time + timedelta(days=1)
    assert next_task.is_completed is False
    assert len(pet.get_tasks()) == 2  # original + auto-scheduled next occurrence


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def test_conflict_detection_flags_duplicate_times():
    conflict_time = datetime(2026, 3, 29, 9, 0)
    t1 = Task("Walk",       "desc", conflict_time, "once", "walk")
    t2 = Task("Medication", "desc", conflict_time, "once", "medication")
    scheduler = make_scheduler([t1, t2])

    warnings = scheduler.get_conflict_warnings()

    assert len(warnings) >= 1, "Expected at least one conflict warning for duplicate times"
    assert any("WARNING:" in w for w in warnings)


def test_no_conflict_when_times_differ():
    now = datetime(2026, 3, 29, 9, 0)
    t1 = Task("Walk",   "desc", now,                      "once", "walk")
    t2 = Task("Dinner", "desc", now + timedelta(hours=5), "once", "feeding")
    scheduler = make_scheduler([t1, t2])

    warnings = scheduler.get_conflict_warnings()

    assert warnings == [], "Expected no warnings when tasks have different times"
