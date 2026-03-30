# PawPal+ Project Reflection

## 1. System Design

Based on the PawPal+ scenario, a user should be able to:

Register a new pet under an owner's profile.
Schedule a new care task (like a feeding, walk, or medication) for a specific pet.
View a sorted daily schedule of all pending tasks to keep the pet's routine on track.

**a. Initial design**

- Briefly describe your initial UML design.

In the UML diagram that I just made, I have added multiple objects (Owner, Pets, Task, Scheduler) and they have certain attributes such as the name, contact info and list of pets for the owner, species and age for the Pet, etc. They also have certain methods which are unique to them. Owner owns pets, pets have tasks and those tasks are managed by the scheduler.

- What classes did you include, and what responsibilities did you assign to each?

For the Owner: They can add pet, remove pet, get list of pets.
Class Pets: Can add a task, remove a task, and get tasks list.
Class Scheduler: Can schedule a task, remove task, get, sort tasks and check for conflicts.
Class Tasks: Can be changed to be mark completed and update time 

**b. Design changes**

- Did your design change during implementation?

Yes I had to make some changes to the system to ensure that there are no bottlenecks or missing relationships. AI Agent was able to find many missing links in the backend code which were not mentioned in the UML diagram.

- If yes, describe at least one change and why you made it.

The first change that AI made was to the Scheduler class which had no link to the Pet or the Owner which can lead to no way for the system to realize which pet the task belongs to in case the owner has multiple pets.

The next change was to the Task class which had no pet back-reference and would loose contect of which pet the task is for upon implementation. A pet_name: str (or a Pet reference) on Task would fix this.

Also the owner and the scheduler were not connected so there was no way for the owner to interact with the scheduler to book and view tasks for their pets. This was fixed by adding self.scheduler = scheduler in owner class.

Agent also pointed out how the sort_tasks_by_time() will be slow if due time is a str so it was changed to datetime. Also tasks on Pet and all_tasks on Scheduler were duplicated state which would result in the task in pet.add_task() not appearing in the scheduler.all_tasks and vice-versa, so we made the scheduler the single source of truth and had pet.get_tasks() to query it.



---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

- What constraints does your scheduler consider (for example: time, priority, preferences)?

The scheduler that we have designed generally considers three main constraints:
1. Time - Tasks with a due_time are used by the scheduler to chronologically sort these tasks, detect if certain tasks are overdue and flagging tasks which are certainly too close to each other.
2. Priority - Each task has been assigned a priority of high, medium or low according to which the tasks are automatically inferred. Eg: Medication and Appointment have been given higher priority while feeding is at medium and Walk is at low. sort_by_priority sorts the priority level first and then decides with the due time as a tie breaker.
3. Frequency - This is also one constraint that the scheduler considers. Each task has a frequency field option which can be once, daily or weekly and the scheduler uses this to auto-generate future instances and auto-reschedule after completion.

- How did you decide which constraints mattered most?

Time was the most critical as tasks which missed by their due time can pose very harmful to a pet. Priority ensures that health-critical tasks are taken care of in the first place so the owner never misses a dose of medication. Recurrence is important as pet care is inherently repetitive and this helps with the manual reentry and human error.

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.

The 30-min conflict window was a tradeoff I was ready to make as it is a fight between sensitivity and usability. You can easily create genuinely problematic cases such like there is a stricter window of 0 - 15 mins difference between a vet appointment and walk. A looser window of 60+ mins would give too many false positives and warnings which would be easier to ignore as they might get really annoying. 

- Why is that tradeoff reasonable for this scenario?

A 30-mins window is what I would consider to be reasonable as it takes 10 - 20 mins max for any of the low or medium priority tasks for the pet. Anything of importance within that 30 mins range can give the owner a lead time to reschedule without being overly conservative about anything.
---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
I used AI primarily for brainstorming, debugging, refactoring the code, Validating my initial UML and catching missing relationships, and restructuring the duplicate task state between Pet and Scheduler.

- What kinds of prompts or questions were most helpful?
What relationships are missing from this UML diagram? 
Why would sorting be inefficient if due_time is a string?
I asked AI to explain what is wrong and just not focused on fixing the code which gave me insights on understanding the code than just copy-pasting that code for use.

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.

When AI suggested adding that adding the full Pet object reference on the Task class, I didn't accept it as-is. A full Pet reference on Task would create a much circular reference (Pet holds Tasks, Task holds Pet), making the data model harder to reason about and serialize.

- How did you evaluate or verify what the AI suggested?

Sketching the code layout first made clear that just a pet_name: str would work fine. Since the Scheduler already stores Pet instances, checking ownership through that link stayed straightforward. To be sure, I walked step by step through how mark_task_complete() runs. The chain of steps kept working as intended, setting up the next task automatically - no need for Task to carry an entire Pet object after all.

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?

I tested six behaviors:

test_mark_completed — that task.is_completed flips from False to True
test_add_task_increases_count — that pet.get_tasks() length increments when a task is added
test_sort_by_time_returns_chronological_order — that tasks inserted out-of-order come back sorted by ascending due_time
test_mark_daily_task_complete_schedules_next_day — that completing a "daily" task auto-adds a new task exactly 1 day later with is_completed=False
test_conflict_detection_flags_duplicate_times — that get_conflict_warnings() returns at least one "WARNING:" string for two tasks at the exact same time
test_no_conflict_when_times_differ — that get_conflict_warnings() returns an empty list when tasks are 5 hours apart (no false positives)

- Why were these tests important?

Because they mainly cover the three core pillars of the scheduler — task lifecycle, sorting, and conflict detection — and the recurrence engine is the most complex single feature which if silently breaks would break the whole scheduling loop.

**b. Confidence**

- How confident are you that your scheduler works correctly?
I'm about 4 out of 5 confident that the scheduler works correctly for the behaviors I tested.

- What edge cases would you test next if you had more time?
 Weekly recurrence — does completing a "weekly" task schedule it exactly 7 days out?
 30-minute window conflicts — my test only checks exact-time overlap, not whether two tasks 20 minutes apart trigger a warning. 

 These are two edge cases I would like to work more on.

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?
The most satisfactory part was the automatic interence system working and deriving the priority from category directly. THis removed the entire input from the user and elimited the whole class of data entry mistakes. The owner doesn't have to decide priority for certain tasks as the system just beautifully does it by itself.

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?
I would try to add a manual priority override on the top of the automatic inference. We have defaulted the walk to low but the owner might want to set it to a specific high priority. I would try and give an option to do that.

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?

What stands out to be the most important thing is how data consistency ties back to structure, not just writing lines of code. Though the duplication between Pet.tasks and Scheduler.all_tasks looked like an error at first glance, it revealed a choice made without full consideration. Tools powered by artificial intelligence helped label what was happening, yet grasping the real impact - how shifting ownership reshaped the system’s shape - came only after slow reflection.
