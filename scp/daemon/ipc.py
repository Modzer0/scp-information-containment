from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable


# asyncio's StreamReader buffer defaults to 64 KB. Replies to verbs like
# site_detail / list_items / vessel_detail grow past that on mature saves
# and raise ValueError("Separator is found, but chunk is longer than
# limit"). Raise the ceiling on both sides of the pipe. 16 MB covers
# realistic sizes with room to spare and matches the client.
IPC_MAX_LINE = 16 * 1024 * 1024


Handler = Callable[[dict], Awaitable[dict]]


class IpcServer:
    """JSON-lines over TCP loopback. One message = one line of JSON.

    Protocol (v0):
        {"type": "<verb>", "payload": {...}}

    Verbs: ping, schedule_event, recent_journal, list_events, subscribe.
    Replies echo as {"type": "<verb>|ack|error", "payload": {...}}.
    """

    def __init__(self, host: str, port: int, handler: Handler):
        self.host = host
        self.port = port
        self.handler = handler
        self._server: asyncio.base_events.Server | None = None
        self._subscribers: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port, limit=IPC_MAX_LINE
        )

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                    if msg.get("type") == "subscribe":
                        self._subscribers.add(writer)
                        await self._send(writer, {"type": "ack", "payload": {}})
                        continue
                    reply = await self.handler(msg)
                except Exception as exc:
                    reply = {"type": "error", "payload": {"error": str(exc)}}
                await self._send(writer, reply)
        finally:
            self._subscribers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    async def _send(writer: asyncio.StreamWriter, msg: dict) -> None:
        writer.write((json.dumps(msg) + "\n").encode())
        await writer.drain()

    async def broadcast(self, msg: dict) -> None:
        dead: list[asyncio.StreamWriter] = []
        for w in list(self._subscribers):
            try:
                await self._send(w, msg)
            except Exception:
                dead.append(w)
        for w in dead:
            self._subscribers.discard(w)
