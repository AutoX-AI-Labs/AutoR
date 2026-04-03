"""Claude Code executor for the A2A server.

Implements AgentExecutor to handle incoming A2A tasks.
Currently stub mode — completes immediately.
Real Anthropic SDK integration will follow in PR 6.
"""
from __future__ import annotations

import uuid

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    Artifact,
    Message,
    Part,
    Role,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
    TextPart,
)


class ClaudeCodeExecutor(AgentExecutor):
    """Executes research tasks by delegating to Claude API.

    In stub mode, immediately completes with a placeholder response.
    """

    def __init__(self, model: str = "sonnet") -> None:
        self.model = model

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        task_id = context.task_id or str(uuid.uuid4())
        context_id = context.context_id or str(uuid.uuid4())

        # Extract prompt from incoming message
        prompt = ""
        if context.message:
            for part in context.message.parts:
                inner = part.root
                if hasattr(inner, "text"):
                    prompt = inner.text
                    break

        # Signal: working
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                taskId=task_id,
                contextId=context_id,
                final=False,
                status=TaskStatus(
                    state=TaskState.working,
                    message=Message(
                        messageId=str(uuid.uuid4()),
                        role=Role.agent,
                        parts=[Part(root=TextPart(text="Processing..."))],
                    ),
                ),
            )
        )

        # Stub: produce a placeholder artifact
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                taskId=task_id,
                contextId=context_id,
                artifact=Artifact(
                    artifactId=str(uuid.uuid4()),
                    parts=[Part(root=TextPart(text=f"[stub] Received prompt ({len(prompt)} chars)"))],
                    name="response",
                ),
            )
        )

        # Signal: completed
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                taskId=task_id,
                contextId=context_id,
                final=True,
                status=TaskStatus(
                    state=TaskState.completed,
                    message=Message(
                        messageId=str(uuid.uuid4()),
                        role=Role.agent,
                        parts=[Part(root=TextPart(text="Task completed (stub mode)."))],
                    ),
                ),
            )
        )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        task_id = context.task_id or ""
        context_id = context.context_id or ""

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                taskId=task_id,
                contextId=context_id,
                final=True,
                status=TaskStatus(state=TaskState.canceled),
            )
        )
