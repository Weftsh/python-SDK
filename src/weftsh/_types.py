"""Result types. Every one is a frozen dataclass; timestamps are epoch milliseconds."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Literal

Wire = dict[str, Any]


class _Unset(enum.Enum):
    UNSET = "UNSET"

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset.UNSET
"""Marks an argument as not given, where ``None`` means something of its own.

``expected_parent=None`` says "the branch must not exist yet"; leaving it
``UNSET`` (the default) says "commit on whatever the tip is now".
"""

Unset = Literal[_Unset.UNSET]

FileContent = str | bytes | bytearray | memoryview
"""File content. ``str`` is sent as UTF-8 text; bytes are sent as-is (base64 on the wire)."""

TokenScope = Literal["org:admin", "org:read", "repo:read", "repo:write", "repo:cache"]


@dataclass(frozen=True)
class RepoInfo:
    """What a repository is, as the API reports it."""

    id: str
    org: str
    """The namespace it lives in, e.g. ``"acme"``."""
    org_id: str
    name: str
    description: str | None
    homepage: str | None
    kind: Literal["native", "mirror"]
    public: bool
    default_branch: str
    clone_url: str
    """HTTPS git remote, without credentials."""
    ssh_clone_url: str | None
    stored_bytes: int
    created_at: int
    origin_url: str | None
    last_sync_at: int | None
    last_synced_commit: str | None
    sync_error: str | None
    fork_state: str | None
    """``pending``, ``ready`` or ``failed`` for a fork; ``None`` otherwise."""
    fork_parent: str | None
    fork_count: int

    @classmethod
    def _from_wire(cls, w: Wire) -> RepoInfo:
        return cls(
            id=w["id"],
            org=w["org"],
            org_id=w["org_id"],
            name=w["name"],
            description=w.get("description"),
            homepage=w.get("homepage"),
            kind=w["kind"],
            public=w["public"],
            default_branch=w["default_branch"],
            clone_url=w["clone_url"],
            ssh_clone_url=w.get("ssh_clone_url"),
            stored_bytes=w.get("stored_bytes") or 0,
            created_at=w["created_at"],
            origin_url=w.get("origin_url"),
            last_sync_at=w.get("last_sync_at"),
            last_synced_commit=w.get("last_synced_commit"),
            sync_error=w.get("sync_error"),
            fork_state=w.get("fork_state"),
            fork_parent=w.get("fork_parent"),
            fork_count=w.get("fork_count") or 0,
        )


@dataclass(frozen=True)
class BatchResult:
    """One item of a batch create or delete, in request order."""

    name: str
    ok: bool
    id: str | None
    error: str | None

    @classmethod
    def _from_wire(cls, w: Wire) -> BatchResult:
        return cls(name=w["name"], ok=w["ok"], id=w.get("id"), error=w.get("error"))


@dataclass(frozen=True)
class Identity:
    """A commit author."""

    name: str
    email: str


@dataclass(frozen=True)
class CommitResult:
    """What a commit made. Durable once returned."""

    commit: str
    tree: str
    parent: str | None
    """The commit it was made on; ``None`` for a branch's first commit."""
    branch: str

    @classmethod
    def _from_wire(cls, w: Wire) -> CommitResult:
        return cls(commit=w["commit"], tree=w["tree"], parent=w.get("parent"), branch=w["branch"])


@dataclass(frozen=True)
class FileResult:
    """A file read at some revision."""

    not_modified: bool
    """``True`` when ``if_none_match`` matched: nothing changed, ``content`` is empty."""
    content: bytes
    etag: str
    """The content hash. Pass it back as ``if_none_match``."""
    commit: str | None
    mode: str | None
    binary: bool
    content_type: str | None

    @property
    def text(self) -> str:
        """The content decoded as UTF-8."""
        return self.content.decode("utf-8")


@dataclass(frozen=True)
class LastCommit:
    sha: str
    message: str
    author: str


@dataclass(frozen=True)
class TreeEntry:
    name: str
    mode: str
    kind: Literal["blob", "tree"]
    oid: str
    size: int | None
    """Bytes, for a blob when ``sizes=True`` was asked for; otherwise ``None``."""
    last_commit: LastCommit | None
    """With ``history=True``: the last commit that touched this entry, if the walk reached it."""

    @classmethod
    def _from_wire(cls, w: Wire) -> TreeEntry:
        lc = w.get("last_commit")
        return cls(
            name=w["name"],
            mode=w["mode"],
            kind=w["kind"],
            oid=w["oid"],
            size=w.get("size"),
            last_commit=LastCommit(lc["commit"], lc["message"], lc["author"]) if lc else None,
        )


@dataclass(frozen=True)
class TreeResult:
    commit: str
    entries: list[TreeEntry]
    history_truncated: bool | None
    """With ``history=True``: whether the walk ran out of budget. ``None`` otherwise."""

    @classmethod
    def _from_wire(cls, w: Wire) -> TreeResult:
        return cls(
            commit=w["commit"],
            entries=[TreeEntry._from_wire(e) for e in w["entries"]],
            history_truncated=w.get("history_truncated"),
        )


@dataclass(frozen=True)
class ListFilesResult:
    commit: str
    paths: list[str]
    """Every path under the directory, flat. Directories end in ``/``."""
    truncated: bool

    @classmethod
    def _from_wire(cls, w: Wire) -> ListFilesResult:
        return cls(commit=w["commit"], paths=w["paths"], truncated=w["truncated"])


@dataclass(frozen=True)
class CommitEntry:
    sha: str
    tree: str
    parents: list[str]
    author: str
    """Raw git ident line: ``Name <email> <epoch> <tz>``."""
    committer: str
    message: str
    change: Literal["added", "modified", "deleted"] | None
    """With a ``path`` filter: what this commit did to that path."""

    @classmethod
    def _from_wire(cls, w: Wire) -> CommitEntry:
        return cls(
            sha=w["commit"],
            tree=w["tree"],
            parents=w["parents"],
            author=w["author"],
            committer=w["committer"],
            message=w["message"],
            change=w.get("change"),
        )


@dataclass(frozen=True)
class ListCommitsResult:
    commits: list[CommitEntry]
    next_cursor: str | None
    """Pass as ``cursor`` for the next page; ``None`` when history is exhausted."""

    @classmethod
    def _from_wire(cls, w: Wire) -> ListCommitsResult:
        return cls(
            commits=[CommitEntry._from_wire(e) for e in w["entries"]],
            next_cursor=w.get("next_after"),
        )


@dataclass(frozen=True)
class DiffChange:
    status: str
    path: str
    old_oid: str | None
    new_oid: str | None
    old_mode: str | None
    new_mode: str | None


@dataclass(frozen=True)
class DiffResult:
    from_: str
    """The resolved base commit (``from`` is a keyword in Python)."""
    to: str
    changes: list[DiffChange]

    @classmethod
    def _from_wire(cls, w: Wire) -> DiffResult:
        return cls(
            from_=w["from"],
            to=w["to"],
            changes=[
                DiffChange(
                    status=c["status"],
                    path=c["path"],
                    old_oid=c.get("old_oid"),
                    new_oid=c.get("new_oid"),
                    old_mode=c.get("old_mode"),
                    new_mode=c.get("new_mode"),
                )
                for c in w["changes"]
            ],
        )


@dataclass(frozen=True)
class Ref:
    name: str
    """Short name, e.g. ``main`` or ``v1.0.0``."""
    full: str
    """Full ref name, e.g. ``refs/heads/main``."""
    oid: str
    default: bool

    @classmethod
    def _from_wire(cls, w: Wire) -> Ref:
        return cls(name=w["name"], full=w["full"], oid=w["oid"], default=w["default"])


@dataclass(frozen=True)
class RefTip:
    name: str
    """Full ref name."""
    oid: str


@dataclass(frozen=True)
class ListRefsResult:
    head: str | None
    refs: list[RefTip]

    @classmethod
    def _from_wire(cls, w: Wire) -> ListRefsResult:
        return cls(head=w.get("head"), refs=[RefTip(r["name"], r["oid"]) for r in w["refs"]])


@dataclass(frozen=True)
class CreatedToken:
    id: str
    token: str
    """The secret. Shown exactly once — store it now."""
    expires_at: int | None

    @classmethod
    def _from_wire(cls, w: Wire) -> CreatedToken:
        return cls(id=w["id"], token=w["token"], expires_at=w.get("expires_at"))


@dataclass(frozen=True)
class TokenInfo:
    id: str
    label: str | None
    scopes: list[str]
    repo_id: str | None
    user_id: str | None
    created_at: int
    revoked_at: int | None
    expires_at: int | None

    @classmethod
    def _from_wire(cls, w: Wire) -> TokenInfo:
        return cls(
            id=w["id"],
            label=w.get("label"),
            scopes=w["scopes"],
            repo_id=w.get("repo_id"),
            user_id=w.get("user_id"),
            created_at=w["created_at"],
            revoked_at=w.get("revoked_at"),
            expires_at=w.get("expires_at"),
        )


@dataclass(frozen=True)
class CreatedWebhook:
    id: str
    url: str
    secret: str
    """The signing secret. Shown exactly once — store it now."""


@dataclass(frozen=True)
class WebhookSubscription:
    id: str
    url: str
    created_at: int


@dataclass(frozen=True)
class ExportJob:
    job: str
    state: str
    """``queued``, ``running``, ``done`` or ``failed``."""
    error: str | None
    download: str | None

    @classmethod
    def _from_wire(cls, w: Wire) -> ExportJob:
        return cls(job=w["job"], state=w["state"], error=w.get("error"), download=w.get("download"))
