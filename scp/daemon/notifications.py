from __future__ import annotations


def notify(title: str, message: str) -> None:
    """Best-effort desktop notification. Silent fallback on any failure."""
    try:
        from plyer import notification  # type: ignore[import-untyped]

        notification.notify(title=title, message=message, timeout=10)
    except Exception:
        pass
