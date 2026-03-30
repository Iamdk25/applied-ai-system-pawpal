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
- How did you decide which constraints mattered most?

**b. Tradeoffs**

- Describe one tradeoff your scheduler makes.
- Why is that tradeoff reasonable for this scenario?

---

## 3. AI Collaboration

**a. How you used AI**

- How did you use AI tools during this project (for example: design brainstorming, debugging, refactoring)?
- What kinds of prompts or questions were most helpful?

**b. Judgment and verification**

- Describe one moment where you did not accept an AI suggestion as-is.
- How did you evaluate or verify what the AI suggested?

---

## 4. Testing and Verification

**a. What you tested**

- What behaviors did you test?
- Why were these tests important?

**b. Confidence**

- How confident are you that your scheduler works correctly?
- What edge cases would you test next if you had more time?

---

## 5. Reflection

**a. What went well**

- What part of this project are you most satisfied with?

**b. What you would improve**

- If you had another iteration, what would you improve or redesign?

**c. Key takeaway**

- What is one important thing you learned about designing systems or working with AI on this project?
