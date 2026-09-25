from __future__ import annotations

from typing import Any


class WeftError(Exception):
    """Every failed request raises a ``WeftError``.

    Weft answers errors as JSON ``{"error": "…"}`` with a matching status, and
    that sentence is the error's message — it is written to be shown to a
    person.
    """

    status: int
    """HTTP status, e.g. ``404``. ``0`` when the request never got an answer."""
    method: str
    url: str
    body: Any
    """The parsed response body (a dict for JSON, a string otherwise), or ``None``."""

    def __init__(self, message: str, *, status: int, method: str, url: str, body: Any = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.method = method
        self.url = url
        self.body = body

    def __repr__(self) -> str:
        return f"{type(self).__name__}(status={self.status}, message={self.message!r})"


class WeftConflictError(WeftError):
    """A ``409`` from an optimistic-concurrency check.

    The branch was not where you said it was (``expected_parent`` on a commit,
    ``expected_head`` on a reset or revert). ``current_tip`` is where it
    actually is — rebase onto it and retry.
    """

    current_tip: str | None

    def __init__(self, message: str, *, status: int, method: str, url: str, body: Any = None):
        super().__init__(message, status=status, method=method, url=url, body=body)
        tip = None
        if isinstance(body, dict):
            # Commits answer `current_tip`; reset and revert answer `current`.
            tip = body.get("current_tip", body.get("current"))
        self.current_tip = tip if isinstance(tip, str) else None
