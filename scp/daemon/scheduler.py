from __future__ import annotations

import asyncio
import heapq
from datetime import datetime
from typing import Awaitable, Callable

from .clock import from_iso, now_utc
from .journal import Journal


FireHook = Callable[[int, str, dict], Awaitable[None]]


class Scheduler:
    """Heap scheduler backed by SQLite. All events persist before they run.

    The heap holds (eta, scheduled_id, kind, payload). On daemon start,
    pending rows are rehydrated from the journal — past-ETA events fire
    immediately, which is the correct behavior for "site kept running
    while you were offline."
    """

    def __init__(self, journal: Journal, fire_hook: FireHook):
        self._journal = journal
        self._fire_hook = fire_hook
        self._heap: list[tuple[datetime, int, str, dict]] = []
        self._wake = asyncio.Event()

    def rehydrate(self) -> None:
        for row in self._journal.pending():
            heapq.heappush(
                self._heap,
                (from_iso(row["eta"]), row["id"], row["kind"], row["payload"]),
            )

    def add(self, eta: datetime, kind: str, payload: dict) -> int:
        sid = self._journal.schedule(eta, kind, payload)
        heapq.heappush(self._heap, (eta, sid, kind, payload))
        self._wake.set()
        return sid

    def clear(self) -> None:
        """Drop the in-memory heap. Caller is responsible for clearing the
        persisted scheduled table if desired (e.g., during a state reset)."""
        self._heap.clear()
        self._wake.set()

    async def run(self) -> None:
        while True:
            if not self._heap:
                self._wake.clear()
                await self._wake.wait()
                continue

            eta, sid, kind, payload = self._heap[0]
            delay = (eta - now_utc()).total_seconds()

            if delay > 0:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                    self._wake.clear()
                    continue
                except asyncio.TimeoutError:
                    pass

            heapq.heappop(self._heap)
            self._journal.mark_fired(sid)
            try:
                await self._fire_hook(sid, kind, payload)
            except Exception as exc:
                self._journal.append(
                    "fire_hook_error",
                    "ERROR",
                    {"scheduled_id": sid, "kind": kind, "error": str(exc)},
                )
