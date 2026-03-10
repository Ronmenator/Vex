"""Task router -- dispatches inbound network tasks to sandboxed agent loops."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from vex.agent.definition import AgentDefinition
from vex.network.claims import ClaimsRegistry
from vex.network.constitution import ConstitutionEngine
from vex.network.identity import KeyPair, PeerIdentity
from vex.network.permissions import PermissionEngine
from vex.network.precedent import ConstitutionalTrace, PrecedentStore
from vex.network.protocol import Envelope, MessageType
from vex.tools.base import RiskTier

logger = logging.getLogger(__name__)

# Type for the delegate function that runs an AgentLoop
AgentRunner = Callable[[AgentDefinition, str], Coroutine[Any, Any, str]]


@dataclass
class TaskContext:
    """Context for an inbound network task."""

    task_id: str
    requester_id: str
    description: str
    risk_ceiling: RiskTier
    job_id: str | None = None  # If from the job board


class TaskRouter:
    """Routes inbound tasks to sandboxed agent execution.

    Security model (two-layer constitutional check):
    1. Emergency brake check -- is this subject currently braked?
    2. Admissibility check -- does this task violate the Prime Directive?
    3. Mission alignment check -- is this task mission-positive?
    4. Permission check (peer policy, rate limit, concurrency)
    5. Constitutional trace recorded for every accepted task
    6. Sandboxed AgentLoop with constrained tools
    7. net.* tools always denied (no amplification)
    8. Workspace sandboxed to .vex/network/sandbox/
    9. Autonomy capped at peer policy level
    """

    def __init__(
        self,
        keypair: KeyPair,
        local_identity: PeerIdentity,
        permissions: PermissionEngine,
        constitution: ConstitutionEngine,
        precedents: PrecedentStore | None = None,
        claims: ClaimsRegistry | None = None,
        agent_runner: AgentRunner | None = None,
        sandbox_dir: str = ".vex/network/sandbox",
    ) -> None:
        self._keypair = keypair
        self._identity = local_identity
        self._permissions = permissions
        self._constitution = constitution
        self._precedents = precedents
        self._claims = claims
        self._agent_runner = agent_runner
        self._sandbox_dir = sandbox_dir
        self._active_tasks: dict[str, TaskContext] = {}

    async def handle_task_request(
        self,
        envelope: Envelope,
    ) -> Envelope:
        """Process an inbound TASK_REQUEST. Returns a response envelope."""
        requester_id = envelope.sender_id
        payload = envelope.payload
        task_desc = payload.get("description", "")
        risk_ceiling = RiskTier(min(payload.get("risk_ceiling", 2), 2))
        job_id = payload.get("job_id")

        task_id = uuid.uuid4().hex

        # 1. Emergency brake check
        if self._claims:
            brake = self._claims.is_braked("task", job_id or task_id)
            if not brake and job_id:
                brake = self._claims.is_braked("job", job_id)
            if brake:
                return Envelope.create(
                    MessageType.TASK_REJECTED,
                    self._identity.peer_id,
                    {
                        "task_id": task_id,
                        "reason": f"Emergency brake active: {brake.reason} (brake {brake.brake_id[:8]})",
                    },
                    self._keypair,
                    recipient_id=requester_id,
                    reply_to=envelope.message_id,
                )

        # 2. Constitutional admissibility check (Layer 1: binary gate)
        admissibility = self._constitution.check_admissibility(task_desc)
        if not admissibility.allowed:
            # Record rejected trace
            if self._precedents:
                trace = ConstitutionalTrace.create(
                    action_type="task",
                    action_id=task_id,
                    actor_id=requester_id,
                    articles_advanced=[],
                    plausible_harms=[f"Violates Prime Directive Article {admissibility.article}"],
                    alternatives_considered="N/A -- task inadmissible",
                    falsification_evidence="N/A -- constitutional violation",
                    rationale=task_desc,
                )
                trace.record_outcome("rejected", admissibility.reason)
                self._precedents.record(trace)

            return Envelope.create(
                MessageType.TASK_REJECTED,
                self._identity.peer_id,
                {
                    "task_id": task_id,
                    "reason": f"Constitutional violation: Prime Directive Article {admissibility.article}",
                },
                self._keypair,
                recipient_id=requester_id,
                reply_to=envelope.message_id,
            )

        # 3. Mission alignment check (Layer 2: scored, advisory)
        rationale = payload.get("rationale", "")
        mission = self._constitution.check_mission_alignment(task_desc, rationale)

        # 4. Permission check
        perm_error = self._permissions.check_task(requester_id, risk_ceiling)
        if perm_error:
            return Envelope.create(
                MessageType.TASK_REJECTED,
                self._identity.peer_id,
                {"task_id": task_id, "reason": perm_error},
                self._keypair,
                recipient_id=requester_id,
                reply_to=envelope.message_id,
            )

        # 5. Record constitutional trace
        if self._precedents:
            trace = ConstitutionalTrace.create(
                action_type="task",
                action_id=task_id,
                actor_id=requester_id,
                articles_advanced=list(mission.articles_relevant),
                plausible_harms=payload.get("plausible_harms", []),
                alternatives_considered=payload.get("alternatives_considered", ""),
                falsification_evidence=payload.get("falsification_evidence", ""),
                rationale=rationale or task_desc,
            )
            self._precedents.record(trace)

        # 6. Accept and execute
        ctx = TaskContext(
            task_id=task_id,
            requester_id=requester_id,
            description=task_desc,
            risk_ceiling=risk_ceiling,
            job_id=job_id,
        )
        self._active_tasks[task_id] = ctx
        self._permissions.record_task_start(requester_id)

        # Send acceptance with mission alignment info
        accepted = Envelope.create(
            MessageType.TASK_ACCEPTED,
            self._identity.peer_id,
            {
                "task_id": task_id,
                "mission_positive": mission.mission_positive,
                "mission_score": mission.score,
            },
            self._keypair,
            recipient_id=requester_id,
            reply_to=envelope.message_id,
        )

        # Start execution in background
        asyncio.create_task(self._execute_task(ctx))

        return accepted

    async def _execute_task(self, ctx: TaskContext) -> None:
        """Execute a task in a sandboxed agent loop."""
        try:
            if not self._agent_runner:
                logger.warning("No agent runner configured, cannot execute task %s", ctx.task_id)
                return

            # Check brake again before execution (may have been pulled since acceptance)
            if self._claims:
                brake = self._claims.is_braked("task", ctx.task_id)
                if not brake and ctx.job_id:
                    brake = self._claims.is_braked("job", ctx.job_id)
                if brake:
                    logger.warning(
                        "Task %s braked before execution: %s", ctx.task_id, brake.reason,
                    )
                    if self._precedents:
                        self._precedents.record_outcome(
                            ctx.task_id, "rejected", f"Emergency brake: {brake.reason}",
                        )
                    return

            # Build precedent context for the agent's system prompt
            precedent_ctx = ""
            if self._precedents:
                precedent_ctx = self._precedents.build_precedent_context("task")

            # Build sandboxed agent definition
            policy = self._permissions.get_policy(ctx.requester_id)
            tool_allow, tool_deny = self._permissions.get_filtered_tools(ctx.requester_id)

            system_parts = [
                f"You are executing a network task from peer {ctx.requester_id[:12]}.",
                f"Task: {ctx.description}",
                "",
                "Complete this task to the best of your ability. "
                "You are operating in a sandboxed environment.",
            ]
            if precedent_ctx and precedent_ctx != "No precedents recorded yet.":
                system_parts.extend([
                    "",
                    "## Constitutional Precedent Context",
                    precedent_ctx,
                ])

            agent_def = AgentDefinition(
                agent_id=f"net-task-{ctx.task_id[:8]}",
                display_name=f"Network Task ({ctx.task_id[:8]})",
                system_prompt="\n".join(system_parts),
                tool_allow=tool_allow,
                tool_deny=tool_deny,
                autonomy_level=min(policy.autonomy_level, 2),
                workspace_root=self._sandbox_dir,
                parent_agent_id="vexnet",
            )

            result = await self._agent_runner(agent_def, ctx.description)

            # Record successful outcome
            if self._precedents:
                trace = self._precedents.get_by_action(ctx.task_id)
                if trace:
                    trace.record_outcome("completed")
                    self._precedents.record(trace)

            logger.info("Task %s completed", ctx.task_id)

        except Exception as exc:
            logger.error("Task %s failed: %s", ctx.task_id, exc)
            if self._precedents:
                trace = self._precedents.get_by_action(ctx.task_id)
                if trace:
                    trace.record_outcome("rejected", str(exc))
                    self._precedents.record(trace)
        finally:
            self._active_tasks.pop(ctx.task_id, None)
            self._permissions.record_task_end(ctx.requester_id)

    def get_active_tasks(self) -> list[TaskContext]:
        return list(self._active_tasks.values())

    def active_count(self) -> int:
        return len(self._active_tasks)
