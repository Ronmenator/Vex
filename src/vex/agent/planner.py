"""Task planner — decomposes complex goals into ordered tasks.

The planner prompts the LLM to break a goal into a structured task plan,
then the agent executes tasks in dependency order with error recovery.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from vex.llm.base import LlmClient, LlmResponse, Message, ToolDefinition


@dataclass
class Task:
    """A single task in a plan."""

    id: str
    description: str
    status: str = "pending"  # pending | in_progress | done | failed
    depends_on: list[str] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    delegate_to: str | None = None  # Agent ID for delegation


@dataclass
class TaskPlan:
    """A structured plan with ordered tasks."""

    goal: str
    tasks: list[Task] = field(default_factory=list)
    status: str = "pending"  # pending | in_progress | done | failed

    def next_ready_task(self) -> Task | None:
        """Find the next task whose dependencies are all done."""
        done_ids = {t.id for t in self.tasks if t.status == "done"}
        for task in self.tasks:
            if task.status != "pending":
                continue
            if all(dep in done_ids for dep in task.depends_on):
                return task
        return None

    def is_complete(self) -> bool:
        return all(t.status == "done" for t in self.tasks)

    def has_failed(self) -> bool:
        return any(t.status == "failed" and t.retry_count >= t.max_retries for t in self.tasks)

    def summary(self) -> str:
        lines = []
        for i, t in enumerate(self.tasks, 1):
            icon = {"pending": " ", "in_progress": ">", "done": "x", "failed": "!"}
            lines.append(f"  [{icon.get(t.status, '?')}] {i}. {t.description}")
        return "\n".join(lines)


PLANNING_PROMPT = """\
You are a task planner. Break down the following goal into a list of concrete, ordered tasks.

Rules:
- Each task should be a single, actionable step
- Tasks can depend on earlier tasks (reference by ID)
- Return ONLY valid JSON — no explanation, no markdown fencing
- Use this exact format:

{"tasks": [
  {"id": "1", "description": "...", "depends_on": []},
  {"id": "2", "description": "...", "depends_on": ["1"]},
  ...
]}

Goal: {goal}
"""


async def create_plan(llm: LlmClient, goal: str) -> TaskPlan:
    """Ask the LLM to decompose a goal into a task plan."""
    messages = [
        Message(role="user", content=PLANNING_PROMPT.format(goal=goal)),
    ]

    response = await llm.chat(messages)

    if not response.content:
        return TaskPlan(goal=goal, tasks=[Task(id="1", description=goal)])

    # Parse the JSON plan
    try:
        # Strip markdown code fences if present
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)
        tasks = [
            Task(
                id=t["id"],
                description=t["description"],
                depends_on=t.get("depends_on", []),
            )
            for t in data.get("tasks", [])
        ]
        if not tasks:
            tasks = [Task(id="1", description=goal)]
        return TaskPlan(goal=goal, tasks=tasks)
    except (json.JSONDecodeError, KeyError, TypeError):
        # Fallback: single task
        return TaskPlan(goal=goal, tasks=[Task(id="1", description=goal)])


REVISION_PROMPT = """\
A task in your plan failed. Here's the context:

Original goal: {goal}

Current plan:
{plan_summary}

Failed task: {task_description}
Error: {error}

Please revise the plan. You can:
1. Add new tasks to work around the failure
2. Modify remaining tasks
3. Remove tasks that are no longer needed

Return the revised plan as JSON (same format as before). Include ALL tasks (done tasks too, keeping their status).
"""


async def revise_plan(
    llm: LlmClient,
    plan: TaskPlan,
    failed_task: Task,
) -> TaskPlan:
    """Ask the LLM to revise the plan after a task failure."""
    messages = [
        Message(
            role="user",
            content=REVISION_PROMPT.format(
                goal=plan.goal,
                plan_summary=plan.summary(),
                task_description=failed_task.description,
                error=failed_task.error or "Unknown error",
            ),
        ),
    ]

    response = await llm.chat(messages)

    if not response.content:
        return plan  # Keep original plan

    try:
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)
        # Preserve done tasks from original plan
        done_tasks = {t.id: t for t in plan.tasks if t.status == "done"}

        new_tasks = []
        for t in data.get("tasks", []):
            task_id = t["id"]
            if task_id in done_tasks:
                new_tasks.append(done_tasks[task_id])
            else:
                new_tasks.append(
                    Task(
                        id=task_id,
                        description=t["description"],
                        depends_on=t.get("depends_on", []),
                    )
                )

        if new_tasks:
            return TaskPlan(goal=plan.goal, tasks=new_tasks)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    return plan  # Keep original on parse failure
