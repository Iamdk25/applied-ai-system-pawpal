from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Tuple


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

    def check_for_conflicts(self) -> List[Tuple[Task, Task]]:
        """Return pairs of tasks that share the exact same due time."""
        all_tasks = self.get_all_tasks()
        conflicts = []
        for i, t1 in enumerate(all_tasks):
            for t2 in all_tasks[i + 1:]:
                if t1.due_time == t2.due_time:
                    conflicts.append((t1, t2))
        return conflicts

    def get_tasks_by_pet(self, pet_name: str) -> List[Task]:
        """Return all tasks belonging to the pet with the given name."""
        return [t for t in self.get_all_tasks() if t in
                next((p.tasks for p in self.owner.pets if p.name == pet_name), [])]


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
