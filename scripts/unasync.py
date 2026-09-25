"""Generate ``_sync_client.py`` from ``_async_client.py``.

Every SDK method is one request (or a loop of them), so the sync client is
the async one with the ``async``/``await`` taken out. Generating it keeps
the two from drifting: ``tests/test_unasync.py`` fails when the committed
file is not what this script produces.

    python scripts/unasync.py          # rewrite src/weftsh/_sync_client.py
    python scripts/unasync.py --check  # exit 1 if it is stale
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "weftsh" / "_async_client.py"
TARGET = ROOT / "src" / "weftsh" / "_sync_client.py"

HEADER = '''"""The sync client. GENERATED from ``_async_client.py`` by ``scripts/unasync.py``
— do not edit by hand; edit the async client and run ``python scripts/unasync.py``."""
'''

# Order matters: the longer names first.
REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bAsyncCommitBuilder\b", "CommitBuilder"),
    (r"\bAsyncRepo\b", "Repo"),
    (r"\bAsyncWeft\b", "Weft"),
    (r"\bAsyncIterator\b", "Iterator"),
    (r"\bhttpx\.AsyncClient\b", "httpx.Client"),
    (r"\basync def __aenter__\b", "def __enter__"),
    (r"\basync def __aexit__\b", "def __exit__"),
    (r"\baclose\b", "close"),
    (r"\basync def\b", "def"),
    (r"\basync with\b", "with"),
    (r"\basync for\b", "for"),
    (r"\bawait ", ""),
]


def render() -> str:
    text = SOURCE.read_text()
    # Drop the async module docstring; the generated file gets its own.
    text = re.sub(r'\A""".*?"""\n', HEADER, text, count=1, flags=re.S)
    for pattern, repl in REPLACEMENTS:
        text = re.sub(pattern, repl, text)
    # `await (` left behind by a parenthesised builder chain in a docstring.
    return text


def main() -> int:
    rendered = render()
    if "--check" in sys.argv:
        if TARGET.read_text() != rendered:
            print(f"{TARGET.relative_to(ROOT)} is stale: run python scripts/unasync.py")
            return 1
        return 0
    TARGET.write_text(rendered)
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
