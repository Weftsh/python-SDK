"""Verifying webhook deliveries."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

SIGNATURE_HEADER = "X-Weft-Signature-256"
"""The header carrying a delivery's signature: ``sha256=<hex hmac of the body>``."""

_SIGNATURE = re.compile(r"^sha256=([0-9a-fA-F]{64})$")


def verify_webhook(
    *, payload: bytes | str, signature: str | None, secret: str
) -> dict[str, Any] | None:
    """Checks a delivery's signature and, if it is genuine, returns the event.

    Returns ``None`` for anything unsigned, mis-signed or malformed — answer
    those with a ``401`` and do not act on them. The event is
    ``{"event": ..., "repo_id": ..., "payload": {...}}``.

    Args:
        payload: The raw request body, exactly as received — not re-serialized JSON.
        signature: The ``X-Weft-Signature-256`` header.
        secret: The secret returned when the webhook was created.
    """
    if not signature or not secret:
        return None
    match = _SIGNATURE.match(signature.strip())
    if not match:
        return None
    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, match.group(1).lower()):
        return None
    try:
        event = json.loads(body)
    except ValueError:
        return None
    if not isinstance(event, dict) or not isinstance(event.get("event"), str):
        return None
    return event
