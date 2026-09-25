"""The README's quickstart is what people copy; examples/quickstart.py is what
the e2e suite runs. If the two drift, the one people copy is untested."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_readme_quickstart_is_examples_quickstart_py() -> None:
    readme = (ROOT / "README.md").read_text()
    example = (ROOT / "examples" / "quickstart.py").read_text()
    block = re.search(
        r"<!-- quickstart:start[^>]*-->\n```python\n(.*?)```\n<!-- quickstart:end -->",
        readme,
        re.S,
    )
    assert block, "quickstart markers missing from README.md"
    assert block.group(1) == example
