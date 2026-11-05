"""Structured execution events for workflow observers."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now_iso():
    """Return a stable ISO timestamp for persisted run events."""
    return datetime.now(timezone.utc).isoformat()


def emit_event(workflow_config, event_type, **payload):
    """
    Emit a structured event to the optional workflow event sink.

    The core CLI path does not attach a sink, so this is a no-op unless the web
    runtime provides one in ``workflow_config["_event_sink"]``.
    """
    sink = workflow_config.get("_event_sink") if isinstance(workflow_config, dict) else None
    if not sink:
        return

    event = {"type": event_type, "timestamp": utc_now_iso()}
    event.update(payload)
    sink(event)
