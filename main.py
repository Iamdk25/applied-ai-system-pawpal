from datetime import datetime
from pawpal_system import Task, Pet, Owner, Scheduler

# ── Setup ──────────────────────────────────────────────────────────────────
owner = Owner("Alex Rivera", "alex@pawpal.com")
scheduler = Scheduler(owner)

rex  = Pet("Rex",  "Dog", 4)
luna = Pet("Luna", "Cat", 2)
owner.add_pet(rex)
owner.add_pet(luna)

today = datetime.now().replace(second=0, microsecond=0)

# Normal tasks (added out of order to prove sorting works)
rex.add_task(Task("Dinner",       "2 cups dry kibble",
                  today.replace(hour=18, minute=0),  "daily",  "feeding"))
rex.add_task(Task("Morning Walk", "30 min walk around the block",
                  today.replace(hour=7,  minute=30), "daily",  "walk"))
rex.add_task(Task("Breakfast",    "2 cups dry kibble",
                  today.replace(hour=8,  minute=0),  "daily",  "feeding"))

luna.add_task(Task("Lunch",          "Half can of wet food",
                   today.replace(hour=13, minute=0), "daily",  "feeding"))
luna.add_task(Task("Morning Brush",  "Brush coat",
                   today.replace(hour=8,  minute=30), "daily", "walk"))

# ── Intentional conflicts ──────────────────────────────────────────────────
# Conflict 1: same pet (Rex) — two tasks at 09:00
rex.add_task(Task("Flea Medication", "Apply topical treatment",
                  today.replace(hour=9, minute=0), "weekly", "medication"))
rex.add_task(Task("Heartworm Pill",  "Give pill with food",
                  today.replace(hour=9, minute=0), "daily",  "medication"))

# Conflict 2: different pets — Rex and Luna both at 13:00
rex.add_task(Task("Vet Checkup",  "Annual exam — bring Rex",
                  today.replace(hour=13, minute=0), "once", "appointment"))
# Luna's Lunch (already added above) is also at 13:00 → cross-pet conflict


# ── Section 1: All tasks sorted by time ───────────────────────────────────
print("=" * 58)
print("  All Tasks — sorted by time")
print("=" * 58)
for task in scheduler.sort_by_time():
    time_str = task.due_time.strftime("%I:%M %p")
    status   = "[DONE]" if task.is_completed else "[    ]"
    print(f"  {status}  {time_str}  [{task.priority.upper()}]  {task.title}")

# ── Section 2: Conflict warnings ──────────────────────────────────────────
print("\n" + "=" * 58)
print("  Conflict Detection")
print("=" * 58)
warnings = scheduler.get_conflict_warnings()
if warnings:
    for w in warnings:
        print(f"  {w}")
else:
    print("  No conflicts detected.")
print("=" * 58)
