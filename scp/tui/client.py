from __future__ import annotations

import asyncio
import json


class DaemonClient:
    """Small async client for the daemon's JSON-lines TCP protocol."""

    def __init__(self, host: str = "127.0.0.1", port: int = 52174):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(
            self.host, self.port
        )

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def send(self, msg: dict) -> dict:
        if not self._writer or not self._reader:
            raise RuntimeError("client not connected")
        async with self._lock:
            self._writer.write((json.dumps(msg) + "\n").encode())
            await self._writer.drain()
            line = await self._reader.readline()
            if not line:
                raise ConnectionError("daemon closed connection")
            return json.loads(line.decode())
