"""The sync client is generated; the committed copy must match the async source."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_sync_client_is_generated_from_the_async_one() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "unasync.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_sync_client_has_no_async_left_in_it() -> None:
    text = (ROOT / "src" / "weftsh" / "_sync_client.py").read_text()
    for word in (
        "async def",
        "async for",
        "async with",
        "await ",
        "AsyncClient",
        "AsyncIterator",
        "AsyncRepo",
        "AsyncWeft",
        "aclose",
    ):
        assert word not in text, word
