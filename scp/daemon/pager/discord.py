from __future__ import annotations

import json
import os
from urllib import error, request


SEVERITY_THRESHOLD = {"INFO": 0, "NOTICE": 1, "WARNING": 2, "ALERT": 3, "BREACH": 4, "ERROR": 3}


def _env_webhook() -> str | None:
    url = os.environ.get("SCP_DISCORD_WEBHOOK", "").strip()
    return url or None


def _env_min_severity() -> str:
    return os.environ.get("SCP_DISCORD_MIN_SEV", "ALERT").upper()


def post(title: str, message: str, severity: str) -> None:
    """Best-effort POST to a Discord webhook. Silent on failure."""
    url = _env_webhook()
    if not url:
        return
    min_sev = _env_min_severity()
    if SEVERITY_THRESHOLD.get(severity, 0) < SEVERITY_THRESHOLD.get(min_sev, 3):
        return

    emoji = {
        "INFO": ":information_source:",
        "NOTICE": ":grey_exclamation:",
        "WARNING": ":warning:",
        "ALERT": ":rotating_light:",
        "BREACH": ":red_circle:",
        "ERROR": ":x:",
    }.get(severity, ":grey_question:")
    content = f"{emoji} **{severity}** — {title}\n{message}"

    body = json.dumps({"content": content[:1900]}).encode()
    req = request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with request.urlopen(req, timeout=5) as resp:
            resp.read()
    except error.URLError:
        pass
    except Exception:
        pass


def post_report(report_text: str, severity: str) -> None:
    """Post a larger incident report as a code block."""
    url = _env_webhook()
    if not url:
        return
    min_sev = _env_min_severity()
    if SEVERITY_THRESHOLD.get(severity, 0) < SEVERITY_THRESHOLD.get(min_sev, 3):
        return
    # Discord message cap is 2000; reserve overhead for the code fence.
    text = report_text[:1900]
    body = json.dumps({"content": f"```\n{text}\n```"}).encode()
    req = request.Request(
        url, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception:
        pass
