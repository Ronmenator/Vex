"""VexNet Hub -- lightweight async web server for observing bot society."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from vex.hub.api import build_routes
from vex.hub.events import EventBroadcaster

if TYPE_CHECKING:
    from vex.network.node import VexNetNode

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


class VexNetHub:
    """Web dashboard for observing VexNet activity.

    Serves a real-time view of all network activity. Humans can browse
    and comment on wiki articles (bot-moderated). Everything else is
    strictly view-only.
    """

    def __init__(self, node: VexNetNode, host: str = "0.0.0.0", port: int = 9121) -> None:
        self._node = node
        self._host = host
        self._port = port
        self._server_task: asyncio.Task | None = None
        self.broadcaster = EventBroadcaster()

        # Build Starlette app
        api_routes = build_routes(node, self.broadcaster)
        routes = [
            *api_routes,
            Mount("/", app=StaticFiles(directory=str(_STATIC_DIR), html=True)),
        ]
        self._app = Starlette(routes=routes)

        # Wire up node events to SSE broadcaster
        self._register_event_listeners()

    def _register_event_listeners(self) -> None:
        """Forward node events to SSE subscribers."""
        node = self._node

        async def on_event(event_type: str, data: dict) -> None:
            await self.broadcaster.publish(event_type, data)

        node.add_event_listener(on_event)

    async def start(self) -> None:
        """Start the Hub web server."""
        import uvicorn

        config = uvicorn.Config(
            self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(server.serve())
        logger.info("VexNet Hub started on http://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        """Stop the Hub web server."""
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None
            logger.info("VexNet Hub stopped")

    @property
    def app(self) -> Starlette:
        """Expose the ASGI app for testing."""
        return self._app
