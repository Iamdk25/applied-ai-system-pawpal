from dataclasses import dataclass, field
from typing import List


@dataclass
class Task:
    title: str
    description: str
    due_time: str
    is_completed: bool = False

    def mark_completed(self):
        pass

    def update_time(self, new_time: str):
        pass


@dataclass
class Pet:
    name: str
    species: str
    age: int
    tasks: List[Task] = field(default_factory=list)

    def add_task(self, task: Task):
        pass

    def remove_task(self, task: Task):
        pass

    def get_tasks(self) -> List[Task]:
        pass


class Owner:
    def __init__(self, name: str, contact_info: str):
        self.name = name
        self.contact_info = contact_info
        self.pets: List[Pet] = []

    def add_pet(self, pet: Pet):
        pass

    def remove_pet(self, pet: Pet):
        pass

    def get_pets(self) -> List[Pet]:
        pass


class Scheduler:
    def __init__(self):
        self.all_tasks: List[Task] = []

    def schedule_task(self, task: Task):
        pass

    def remove_task(self, task: Task):
        pass

    def get_todays_tasks(self) -> List[Task]:
        pass

    def sort_tasks_by_time(self) -> List[Task]:
        pass

    def check_for_conflicts(self, task: Task) -> bool:
        pass
