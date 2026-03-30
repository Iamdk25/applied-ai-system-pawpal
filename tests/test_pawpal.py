from datetime import datetime
from pawpal_system import Task, Pet


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
