"""BotManagerLock — shared reentrant mutex for BotManager collaborators.

A thin wrapper around :class:`threading.RLock` injected into every
collaborator so they share one lock without referencing each other.
Reentrant so a collaborator may call another locked method on the same
thread without deadlocking (e.g. ``submit_manual_order_with_brackets``
calls ``submit_manual_order`` then ``attach_stop_loss``).
"""

from __future__ import annotations

import threading


class BotManagerLock:
    """Reentrant mutex shared across BotManager collaborators."""

    __slots__ = ("_lock",)

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def __enter__(self) -> BotManagerLock:
        self._lock.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self._lock.release()
