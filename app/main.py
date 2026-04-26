"""Dual entry point: CLI (default) + FastAPI (--api flag).

Usage:
    python -m app.main          # CLI interactive mode
    python -m app.main --api    # FastAPI server mode

DI STRATEGY:
- API mode: Agent is stored on app.state.agent via lifespan context manager.
  Routes access it through request.app.state — NO module-level globals.
- CLI mode: Agent is created and used within cli_main() scope — no globals needed.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from contextlib import asynccontextmanager

from app.config import Settings


# ── CLI Mode ─────────────────────────────────────────────────────


async def cli_main(settings: Settings) -> None:
    """Interactive CLI loop."""
    from app.factory import build_agent
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel

    console = Console()
    agent = await build_agent(settings)
    conv_id = str(uuid.uuid4())

    tools = [sp.name for sp in agent._tools.specs()]
    
    # Welcome banner
    welcome_text = (
        f"**Provider**: `{settings.llm_provider}` | **Model**: `{settings.resolved_model()}`\n"
        f"**Tools**: `{', '.join(tools)}`\n"
        f"**Conversation ID**: `{conv_id[:8]}...`"
    )
    console.print(Panel(Markdown(welcome_text), title="[bold cyan]MIA Personal AI Agent[/bold cyan]", border_style="cyan"))
    console.print("[dim]Type 'quit' or 'exit' to stop.[/dim]\n")

    while True:
        try:
            user_input = console.input("[bold green]You[/bold green] ❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[bold yellow]Goodbye![/bold yellow]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            console.print("[bold yellow]Goodbye![/bold yellow]")
            break

        with console.status("[bold cyan]Agent is thinking...[/bold cyan]", spinner="dots"):
            result = await agent.run(
                user_message=user_input,
                conversation_id=conv_id,
            )
            
        console.print("\n[bold purple]MIA[/bold purple] ❯")
        console.print(Markdown(result.content))
        console.print()


# ── API Mode ─────────────────────────────────────────────────────


def api_main(settings: Settings) -> None:
    """Start FastAPI server with uvicorn.

    Agent is injected via app.state.agent using lifespan context manager —
    NOT module-level globals. Routes access via request.app.state.
    """
    import uvicorn
    from fastapi import FastAPI

    from app.api.routes import router

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifespan handler: build agent on startup, cleanup on shutdown."""
        from app.factory import build_agent

        agent = await build_agent(settings)
        app.state.agent = agent
        logger = logging.getLogger(__name__)
        logger.info("Agent initialized and stored on app.state")
        yield
        # Cleanup (if needed in future)
        logger.info("Shutting down agent")

    app = FastAPI(
        title="Personal AI Agent",
        description="AI Agent with Tool Use, Memory & Self-Verification",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for local development
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Serve frontend — register root route BEFORE API router
    from pathlib import Path
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        from fastapi.responses import FileResponse

        @app.get("/", include_in_schema=False)
        async def root():
            """Serve chat frontend."""
            return FileResponse(static_dir / "index.html")

    app.include_router(router)

    uvicorn.run(app, host=settings.api_host, port=settings.api_port, log_level=settings.log_level.lower())


# ── Entrypoint ───────────────────────────────────────────────────


def main() -> None:
    """Main entrypoint — detect --api flag."""
    settings = Settings()

    # Configure logging
    if "--api" in sys.argv:
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper(), logging.INFO),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
    else:
        from rich.logging import RichHandler
        logging.basicConfig(
            level=getattr(logging, settings.log_level.upper(), logging.INFO),
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True, markup=True)]
        )

    if "--api" in sys.argv:
        api_main(settings)
    else:
        asyncio.run(cli_main(settings))


if __name__ == "__main__":
    main()
