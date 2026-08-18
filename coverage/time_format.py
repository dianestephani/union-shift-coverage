"""
Per-request "military time" preference, mirroring how django.utils.timezone
activate/deactivate work: a contextvar set by middleware at the start of
each request, read wherever a time needs to be formatted (the ShiftRequest
model and the coverage_extras template filters).
"""
from contextvars import ContextVar

_current = ContextVar("uses_24h_time", default=False)


def activate(uses_24h: bool) -> None:
    _current.set(uses_24h)


def deactivate() -> None:
    _current.set(False)


def uses_24h_time() -> bool:
    return _current.get()
