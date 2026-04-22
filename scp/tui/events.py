from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable


class SubscriptionClient:
    """Dedicated connection for receiving `event_fired` push messages.
    The main request/reply client can't share this socket — mixing a
    response stream with push events breaks the reply pairing.
    """

    def __init__(
        self,
        host: str,
        port: int,
        on_event: Callable[[dict], Awaitable[None]],
    ):
        self.host = host
        self.port = port
        self.on_event = on_event
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task | None = None
        self._stop = False

    async def start(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(
            self.host, self.port
        )
        self._writer.write(b'{"type":"subscribe"}\n')
        await self._writer.drain()
        # Drain the ack before starting the push loop
        await self._reader.readline()
        self._task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._reader is not None
        while not self._stop:
            line = await self._reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode())
            except Exception:
                continue
            try:
                await self.on_event(msg)
            except Exception:
                pass

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
