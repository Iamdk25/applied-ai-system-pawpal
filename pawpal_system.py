from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import List, Optional, Tuple


PRIORITY_MAP = {
    "medication": "high",
    "appointment": "high",
    "feeding": "medium",
    "walk": "low",
}

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Task:
    title: str
    description: str
    due_time: datetime
    frequency: str   # "once", "daily", "weekly"
    category: str    # "feeding", "walk", "medication", "appointment"
    priority: str = field(init=False)
    is_completed: bool = False

    def __post_init__(self):
        """Infer priority from category using PRIORITY_MAP."""
        self.priority = PRIORITY_MAP.get(self.category, "medium")

    def mark_completed(self):
        """Mark this task as completed."""
        self.is_completed = True

    def next_occurrence(self) -> Optional["Task"]:
        """Return a fresh Task for the next recurrence, or None if frequency is 'once'.

        Uses timedelta to shift due_time:
          - "daily"  → due_time + timedelta(days=1)
          - "weekly" → due_time + timedelta(weeks=1)
          - "once"   → None  (no next occurrence)
        """
        if self.frequency == "daily":
            return replace(self, due_time=self.due_time + timedelta(days=1), is_completed=False)
        if self.frequency == "weekly":
            return replace(self, due_time=self.due_time + timedelta(weeks=1), is_completed=False)
        return None  # "once" — no next occurrence

    def update_time(self, new_time: datetime):
        """Update the task's scheduled due time."""
        self.due_time = new_time

    def is_overdue(self) -> bool:
        """Return True if the task is incomplete and past its due time."""
        return not self.is_completed and self.due_time < datetime.now()


@dataclass
class Pet:
    name: str
    species: str
    age: int
    tasks: List[Task] = field(default_factory=list)

    def add_task(self, task: Task):
        """Add a task to this pet's task list."""
        self.tasks.append(task)

    def remove_task(self, task: Task):
        """Remove a specific task from this pet's task list."""
        self.tasks.remove(task)

    def get_tasks(self) -> List[Task]:
        """Return all tasks belonging to this pet."""
        return self.tasks

    def get_pending_tasks(self) -> List[Task]:
        """Return only tasks that have not been completed."""
        return [t for t in self.tasks if not t.is_completed]

    def get_tasks_by_category(self, category: str) -> List[Task]:
        """Return tasks filtered by a given category (e.g. 'feeding', 'walk')."""
        return [t for t in self.tasks if t.category == category]


class Owner:
    def __init__(self, name: str, contact_info: str):
        self.name = name
        self.contact_info = contact_info
        self.pets: List[Pet] = []

    def add_pet(self, pet: Pet):
        """Register a pet under this owner."""
        self.pets.append(pet)

    def remove_pet(self, pet: Pet):
        """Remove a pet from this owner's care."""
        self.pets.remove(pet)

    def get_pets(self) -> List[Pet]:
        """Return the list of all pets owned."""
        return self.pets

    def get_all_tasks(self) -> List[Task]:
        """Return a flat list of every task across all pets."""
        return [task for pet in self.pets for task in pet.tasks]


class Scheduler:
    def __init__(self, owner: Owner):
        self.owner = owner

    def get_all_tasks(self) -> List[Task]:
        """Return every task across all of the owner's pets."""
        return self.owner.get_all_tasks()

    def get_todays_tasks(self) -> List[Task]:
        """Return all tasks scheduled for today's date."""
        today = datetime.now().date()
        return [t for t in self.get_all_tasks() if t.due_time.date() == today]

    def get_overdue_tasks(self) -> List[Task]:
        """Return all incomplete tasks whose due time has already passed."""
        return [t for t in self.get_all_tasks() if t.is_overdue()]

    def get_upcoming_tasks(self, hours: int = 24) -> List[Task]:
        """Return incomplete tasks due within the next N hours (default 24)."""
        now = datetime.now()
        cutoff = now + timedelta(hours=hours)
        return [
            t for t in self.get_all_tasks()
            if not t.is_completed and now <= t.due_time <= cutoff
        ]

    def sort_by_time(self) -> List[Task]:
        """Return all tasks sorted in ascending order by due time."""
        return sorted(self.get_all_tasks(), key=lambda t: t.due_time)

    def sort_by_priority(self) -> List[Task]:
        """Return all tasks sorted high → medium → low, then by due time."""
        return sorted(
            self.get_all_tasks(),
            key=lambda t: (PRIORITY_ORDER.get(t.priority, 1), t.due_time)
        )

    def get_tasks_by_pet(self, pet_name: str) -> List[Task]:
        """Return all tasks belonging to the pet with the given name."""
        return [t for t in self.get_all_tasks() if t in
                next((p.tasks for p in self.owner.pets if p.name == pet_name), [])]

    def generate_recurring_instances(self, days_ahead: int = 7) -> List[Task]:
        """Return all tasks expanded by their recurrence frequency.

        - "daily"  → one copy per day for the next days_ahead days
        - "weekly" → one copy 7 days from each task's due_time
        - "once"   → included as-is, no copies

        Original task objects are never mutated; copies are made with
        dataclasses.replace() and a shifted due_time.
        """
        expanded: List[Task] = []
        for task in self.get_all_tasks():
            if task.frequency == "once":
                expanded.append(task)
            elif task.frequency == "daily":
                for day_offset in range(days_ahead):
                    expanded.append(
                        replace(task, due_time=task.due_time + timedelta(days=day_offset))
                    )
            elif task.frequency == "weekly":
                expanded.append(task)
                expanded.append(
                    replace(task, due_time=task.due_time + timedelta(weeks=1))
                )
        return sorted(expanded, key=lambda t: t.due_time)

    def check_for_conflicts(self, window_minutes: int = 30) -> List[Tuple[Task, Task]]:
        """Return pairs of incomplete tasks whose due times fall within a time window.

        Unlike an exact-match check, this catches near-collisions that are
        physically impossible for one owner to handle — e.g. two tasks only
        10 minutes apart.

        Args:
            window_minutes: Maximum gap (in minutes) between two tasks' due times
                            for them to be considered a conflict. Default is 30.

        Returns:
            A list of (Task, Task) tuples where each pair represents a conflict.
            Returns an empty list when no conflicts exist (never raises).
        """
        all_tasks = [t for t in self.get_all_tasks() if not t.is_completed]
        window = timedelta(minutes=window_minutes)
        conflicts = []
        for i, t1 in enumerate(all_tasks):
            for t2 in all_tasks[i + 1:]:
                if abs(t1.due_time - t2.due_time) <= window:
                    conflicts.append((t1, t2))
        return conflicts

    def get_conflict_warnings(self, window_minutes: int = 30) -> List[str]:
        """Return human-readable warning strings for tasks within a time window.

        Checks every pair of incomplete tasks across all pets. When two tasks
        are scheduled within window_minutes of each other, a warning is produced
        that names both tasks, their times, and which pet(s) they belong to.

        Args:
            window_minutes: Gap threshold in minutes (default 30). Tasks closer
                            than this are flagged as a scheduling conflict.

        Returns an empty list (never raises) when no conflicts are found.
        """
        # Build a fast task → pet-name lookup (one pass, O(n))
        task_to_pet: dict = {
            id(task): pet.name
            for pet in self.owner.pets
            for task in pet.tasks
        }

        all_tasks = [t for t in self.get_all_tasks() if not t.is_completed]
        window = timedelta(minutes=window_minutes)
        warnings: List[str] = []

        for i, t1 in enumerate(all_tasks):
            for t2 in all_tasks[i + 1:]:
                gap = abs(t1.due_time - t2.due_time)
                if gap <= window:
                    pet1 = task_to_pet.get(id(t1), "Unknown")
                    pet2 = task_to_pet.get(id(t2), "Unknown")
                    t1_str = t1.due_time.strftime("%I:%M %p")
                    t2_str = t2.due_time.strftime("%I:%M %p")
                    gap_mins = int(gap.total_seconds() // 60)
                    scope = (
                        f"same pet ({pet1})" if pet1 == pet2
                        else f"{pet1} and {pet2}"
                    )
                    if gap_mins == 0:
                        warnings.append(
                            f"'{t1.title}' and '{t2.title}' are both scheduled at "
                            f"{t1_str} ({scope}) — exact overlap!"
                        )
                    else:
                        warnings.append(
                            f"'{t1.title}' ({t1_str}) and '{t2.title}' ({t2_str}) "
                            f"are only {gap_mins} min apart ({scope})"
                        )

        return warnings

    def mark_task_complete(self, task: Task) -> Optional[Task]:
        """Mark task complete and auto-schedule the next occurrence for recurring tasks.

        For "daily" tasks  → next due_time = task.due_time + timedelta(days=1)
        For "weekly" tasks → next due_time = task.due_time + timedelta(weeks=1)
        For "once" tasks   → just marks complete, nothing is scheduled

        Returns the newly created Task if one was scheduled, otherwise None.
        """
        task.mark_completed()

        next_task = task.next_occurrence()
        if next_task is None:
            return None

        # Find the pet that owns this task and add the next occurrence to it
        for pet in self.owner.pets:
            if task in pet.tasks:
                pet.add_task(next_task)
                return next_task

        return None  # task not found under any pet (shouldn't happen in normal use)

    def filter_tasks(
        self,
        pet_name: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Task]:
        """Return tasks matching ALL supplied filters (AND logic).

        Args:
            pet_name: Only tasks belonging to this pet.
            status:   "pending" | "completed" | "overdue"
            category: e.g. "feeding", "walk", "medication", "appointment"

        Returns tasks sorted by due_time.
        """
        pet_task_sets = {
            p.name: set(id(t) for t in p.tasks) for p in self.owner.pets
        }

        tasks = self.get_all_tasks()

        if pet_name is not None:
            allowed = pet_task_sets.get(pet_name, set())
            tasks = [t for t in tasks if id(t) in allowed]

        if status == "pending":
            tasks = [t for t in tasks if not t.is_completed]
        elif status == "completed":
            tasks = [t for t in tasks if t.is_completed]
        elif status == "overdue":
            tasks = [t for t in tasks if t.is_overdue()]

        if category is not None:
            tasks = [t for t in tasks if t.category == category]

        return sorted(tasks, key=lambda t: t.due_time)


if __name__ == "__main__":
    from datetime import datetime, timedelta

    now = datetime.now()

    # --- Setup ---
    owner = Owner("Alex", "alex@email.com")
    scheduler = Scheduler(owner)

    rex = Pet("Rex", "Dog", 3)
    whiskers = Pet("Whiskers", "Cat", 5)
    owner.add_pet(rex)
    owner.add_pet(whiskers)

    # --- Tasks for Rex ---
    rex.add_task(Task("Morning Walk", "30 min walk around the block",
                      now.replace(hour=8, minute=0, second=0, microsecond=0),
                      "daily", "walk"))
    rex.add_task(Task("Heartworm Pill", "Give with food",
                      now.replace(hour=8, minute=0, second=0, microsecond=0),  # conflict with walk
                      "daily", "medication"))
    rex.add_task(Task("Dinner", "2 cups dry food",
                      now.replace(hour=18, minute=0, second=0, microsecond=0),
                      "daily", "feeding"))

    # --- Tasks for Whiskers ---
    whiskers.add_task(Task("Vet Appointment", "Annual checkup",
                           now - timedelta(hours=2),   # overdue
                           "once", "appointment"))
    whiskers.add_task(Task("Lunch", "Wet food",
                           now.replace(hour=12, minute=0, second=0, microsecond=0),
                           "daily", "feeding"))

    # --- Verify ---
    print("=== All Tasks (sorted by priority) ===")
    for t in scheduler.sort_by_priority():
        status = "DONE" if t.is_completed else ("OVERDUE" if t.is_overdue() else "pending")
        print(f"  [{t.priority.upper()}] {t.title} @ {t.due_time.strftime('%H:%M')} ({status})")

    print("\n=== Today's Tasks ===")
    for t in scheduler.get_todays_tasks():
        print(f"  {t.title} — {t.category}")

    print("\n=== Overdue Tasks ===")
    for t in scheduler.get_overdue_tasks():
        print(f"  {t.title} for {t.due_time.strftime('%Y-%m-%d %H:%M')}")

    print("\n=== Conflicts ===")
    conflicts = scheduler.check_for_conflicts()
    if conflicts:
        for t1, t2 in conflicts:
            print(f"  CONFLICT: '{t1.title}' and '{t2.title}' both at {t1.due_time.strftime('%H:%M')}")
    else:
        print("  No conflicts.")

    print("\n=== Rex's Tasks ===")
    for t in rex.get_tasks():
        print(f"  {t.title} ({t.category})")

    print("\n=== Whiskers' Pending Tasks ===")
    for t in whiskers.get_pending_tasks():
        print(f"  {t.title}")
