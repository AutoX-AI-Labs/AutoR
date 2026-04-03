"""Tests for the Claude Code A2A server."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from src.a2a.agent_card import build_agent_card
from src.a2a.executor import ClaudeCodeExecutor
from src.a2a.server import create_app, A2AStarletteApplication


class TestAgentCard:
    def test_agent_card_has_required_fields(self):
        card = build_agent_card("http://localhost:50002")
        assert card.name == "claude-code-research"
        assert card.url == "http://localhost:50002"
        assert card.protocol_version == "0.3"
        assert card.version == "0.1.0"

    def test_agent_card_has_8_skills(self):
        card = build_agent_card("http://localhost:50002")
        assert len(card.skills) == 8
        skill_ids = [s.id for s in card.skills]
        assert "literature_survey" in skill_ids
        assert "writing" in skill_ids
        assert "dissemination" in skill_ids

    def test_agent_card_has_streaming_capability(self):
        card = build_agent_card("http://localhost:50002")
        assert card.capabilities is not None
        assert card.capabilities.streaming is True

    def test_agent_card_has_provider(self):
        card = build_agent_card("http://localhost:50002")
        assert card.provider is not None
        assert card.provider.organization == "AutoX-AI-Labs"


class TestClaudeCodeExecutor:
    def _make_context(self, prompt: str = "Test prompt", task_id: str = "t1", context_id: str = "c1"):
        from a2a.server.agent_execution import RequestContext
        from a2a.types import Message, MessageSendParams, Part, Role, TextPart

        return RequestContext(
            request=MessageSendParams(
                message=Message(
                    messageId=str(uuid.uuid4()),
                    role=Role.user,
                    parts=[Part(root=TextPart(text=prompt))],
                ),
            ),
            task_id=task_id,
            context_id=context_id,
        )

    def _make_cancel_context(self, task_id: str = "t1", context_id: str = "c1"):
        from a2a.server.agent_execution import RequestContext
        return RequestContext(task_id=task_id, context_id=context_id)

    def test_execute_enqueues_three_events(self):
        from a2a.types import TaskState, TaskStatusUpdateEvent, TaskArtifactUpdateEvent

        executor = ClaudeCodeExecutor(model="sonnet")
        mock_queue = MagicMock()
        mock_queue.enqueue_event = AsyncMock()

        context = self._make_context("Test prompt")
        asyncio.run(executor.execute(context, mock_queue))

        assert mock_queue.enqueue_event.call_count == 3

        # Unpack the 3 events
        events = [c.args[0] for c in mock_queue.enqueue_event.call_args_list]

        # Event 1: working
        assert isinstance(events[0], TaskStatusUpdateEvent)
        assert events[0].status.state == TaskState.working
        assert events[0].final is False

        # Event 2: artifact
        assert isinstance(events[1], TaskArtifactUpdateEvent)
        assert events[1].artifact.name == "response"

        # Event 3: completed
        assert isinstance(events[2], TaskStatusUpdateEvent)
        assert events[2].status.state == TaskState.completed
        assert events[2].final is True

    def test_execute_captures_prompt_length(self):
        from a2a.types import TaskArtifactUpdateEvent

        executor = ClaudeCodeExecutor()
        mock_queue = MagicMock()
        mock_queue.enqueue_event = AsyncMock()

        context = self._make_context("x" * 500)
        asyncio.run(executor.execute(context, mock_queue))

        events = [c.args[0] for c in mock_queue.enqueue_event.call_args_list]
        artifact_events = [e for e in events if isinstance(e, TaskArtifactUpdateEvent)]
        assert len(artifact_events) == 1
        artifact_text = artifact_events[0].artifact.parts[0].root.text
        assert "500 chars" in artifact_text

    def test_execute_uses_task_and_context_ids(self):
        executor = ClaudeCodeExecutor()
        mock_queue = MagicMock()
        mock_queue.enqueue_event = AsyncMock()

        context = self._make_context(task_id="my-task", context_id="my-ctx")
        asyncio.run(executor.execute(context, mock_queue))

        events = [c.args[0] for c in mock_queue.enqueue_event.call_args_list]
        for event in events:
            assert event.task_id == "my-task"
            assert event.context_id == "my-ctx"

    def test_execute_with_empty_message(self):
        from a2a.server.agent_execution import RequestContext
        from a2a.types import TaskArtifactUpdateEvent

        executor = ClaudeCodeExecutor()
        mock_queue = MagicMock()
        mock_queue.enqueue_event = AsyncMock()

        context = RequestContext(task_id="t1", context_id="c1")
        asyncio.run(executor.execute(context, mock_queue))

        assert mock_queue.enqueue_event.call_count == 3
        events = [c.args[0] for c in mock_queue.enqueue_event.call_args_list]
        artifact_events = [e for e in events if isinstance(e, TaskArtifactUpdateEvent)]
        # prompt was empty → "0 chars"
        assert "0 chars" in artifact_events[0].artifact.parts[0].root.text

    def test_cancel_enqueues_canceled(self):
        from a2a.types import TaskState, TaskStatusUpdateEvent

        executor = ClaudeCodeExecutor()
        mock_queue = MagicMock()
        mock_queue.enqueue_event = AsyncMock()

        context = self._make_cancel_context(task_id="cancel-1", context_id="ctx-1")
        asyncio.run(executor.cancel(context, mock_queue))

        assert mock_queue.enqueue_event.call_count == 1
        event = mock_queue.enqueue_event.call_args_list[0].args[0]
        assert isinstance(event, TaskStatusUpdateEvent)
        assert event.status.state == TaskState.canceled
        assert event.final is True
        assert event.task_id == "cancel-1"


class TestCreateApp:
    def test_create_app_returns_starlette_application(self):
        app = create_app(host="127.0.0.1", port=50099, model="sonnet")
        assert isinstance(app, A2AStarletteApplication)

    def test_create_app_builds_asgi(self):
        app = create_app(host="127.0.0.1", port=50099)
        asgi = app.build()
        assert callable(asgi)
