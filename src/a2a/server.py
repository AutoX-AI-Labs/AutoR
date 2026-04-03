"""A2A HTTP server for the Claude Code research agent."""
from __future__ import annotations

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from .agent_card import build_agent_card
from .executor import ClaudeCodeExecutor


def create_app(
    host: str = "0.0.0.0",
    port: int = 50002,
    model: str = "sonnet",
) -> A2AStarletteApplication:
    """Create an A2A Starlette application."""
    url = f"http://{host}:{port}"

    agent_card = build_agent_card(url)
    executor = ClaudeCodeExecutor(model=model)
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    return A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    )


def run_server(
    host: str = "0.0.0.0",
    port: int = 50002,
    model: str = "sonnet",
) -> None:
    """Start the A2A server with uvicorn."""
    import uvicorn

    app = create_app(host=host, port=port, model=model)
    uvicorn.run(app.build(), host=host, port=port)
