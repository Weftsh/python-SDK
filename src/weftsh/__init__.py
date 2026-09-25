"""The Python SDK for Weft: a real git repository per user, session or agent.

::

    from weftsh import Weft

    weft = Weft(token=os.environ["WEFT_TOKEN"], org="acme")
    repo = weft.create_repo()
    repo.create_commit(message="agent step 1").put("src/app.py", "print(1)\\n").send()
    print(repo.read_file("src/app.py"))

``AsyncWeft`` is the same client for ``asyncio``.
"""

from ._async_client import AsyncCommitBuilder, AsyncRepo, AsyncWeft
from ._errors import WeftConflictError, WeftError
from ._sync_client import CommitBuilder, Repo, Weft
from ._types import (
    UNSET,
    BatchResult,
    CommitEntry,
    CommitResult,
    CreatedToken,
    CreatedWebhook,
    DiffChange,
    DiffResult,
    ExportJob,
    FileContent,
    FileResult,
    Identity,
    LastCommit,
    ListCommitsResult,
    ListFilesResult,
    ListRefsResult,
    Ref,
    RefTip,
    RepoInfo,
    TokenInfo,
    TokenScope,
    TreeEntry,
    TreeResult,
    WebhookSubscription,
)
from ._version import VERSION
from ._wire import DEFAULT_BASE_URL
from .webhooks import SIGNATURE_HEADER, verify_webhook

__version__ = VERSION

__all__ = [
    "DEFAULT_BASE_URL",
    "SIGNATURE_HEADER",
    "UNSET",
    "VERSION",
    "AsyncCommitBuilder",
    "AsyncRepo",
    "AsyncWeft",
    "BatchResult",
    "CommitBuilder",
    "CommitEntry",
    "CommitResult",
    "CreatedToken",
    "CreatedWebhook",
    "DiffChange",
    "DiffResult",
    "ExportJob",
    "FileContent",
    "FileResult",
    "Identity",
    "LastCommit",
    "ListCommitsResult",
    "ListFilesResult",
    "ListRefsResult",
    "Ref",
    "RefTip",
    "Repo",
    "RepoInfo",
    "TokenInfo",
    "TokenScope",
    "TreeEntry",
    "TreeResult",
    "Weft",
    "WeftConflictError",
    "WeftError",
    "WebhookSubscription",
    "verify_webhook",
]
