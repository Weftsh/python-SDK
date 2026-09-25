"""The async client. ``_sync_client.py`` is generated from this file by
``scripts/unasync.py`` — edit here, then run ``python scripts/unasync.py``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any

import httpx

from . import _wire
from ._errors import WeftError
from ._types import (
    UNSET,
    BatchResult,
    CommitEntry,
    CommitResult,
    CreatedToken,
    CreatedWebhook,
    DiffResult,
    ExportJob,
    FileContent,
    FileResult,
    Identity,
    ListCommitsResult,
    ListFilesResult,
    ListRefsResult,
    Ref,
    RepoInfo,
    TokenInfo,
    TokenScope,
    TreeResult,
    Unset,
    WebhookSubscription,
    Wire,
)

__all__ = ["AsyncWeft", "AsyncRepo", "AsyncCommitBuilder"]


class AsyncWeft:
    """The Weft client. One per token and organization.

    ::

        async with AsyncWeft(token=os.environ["WEFT_TOKEN"], org="acme") as weft:
            repo = await weft.create_repo()
    """

    def __init__(
        self,
        *,
        token: str,
        org: str,
        base_url: str = _wire.DEFAULT_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        """
        Args:
            token: A Weft API token, ``weft_<id>_<secret>``.
            org: The organization (or personal namespace) every call works in.
            base_url: API origin. Defaults to ``https://api.weft.sh``.
            http_client: Your own ``httpx`` client, for retries, proxies or
                logging. The SDK never retries by itself, because a write that
                failed on the way back may still have happened. A client you
                pass is yours to close.
            timeout: Seconds, for the client the SDK makes when you pass none.
        """
        _wire.check_options(token, org)
        self.org = org
        self._base_url = base_url.rstrip("/")
        self._headers = _wire.headers(token)
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        """Closes the HTTP client, if the SDK made it."""
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncWeft:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    @property
    def base_url(self) -> str:
        return self._base_url

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        allow: tuple[int, ...] = (),
    ) -> httpx.Response:
        url = f"{self._base_url}/{path}"
        try:
            response = await self._http.request(
                method,
                url,
                params=params,
                json=json,
                headers={**self._headers, **(headers or {})},
            )
        except httpx.HTTPError as exc:
            raise _wire.transport_error(exc, method, url) from exc
        _wire.raise_for(response, allow)
        return response

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        return _wire.json_of(await self._request(method, path, **kwargs))

    def _org_path(self, suffix: str, org: str | None = None) -> str:
        return f"v1/orgs/{_wire.seg(org or self.org)}{suffix}"

    # ------------------------------------------------------------ repositories

    async def create_repo(
        self,
        *,
        name: str | None = None,
        public: bool | None = None,
        default_branch: str | None = None,
        description: str | None = None,
    ) -> AsyncRepo:
        """Creates a repository — a real git remote, typically in under 100 ms.

        With no ``name``, a unique one is generated: the usual choice for a
        repository per session. Names are letters, digits, ``-``, ``_`` and
        ``.``, up to 100 characters.
        """
        body = _wire.create_body(name or _wire.unique_name(), public, default_branch, description)
        info = RepoInfo._from_wire(await self._json("POST", self._org_path("/repos"), json=body))
        return AsyncRepo(self, info.name, info)

    async def find_one(self, *, name: str) -> AsyncRepo | None:
        """Looks a repository up by name. ``None`` if there is none you can see."""
        repo = self.repo(name)
        try:
            await repo.refresh()
        except WeftError as exc:
            if exc.status == 404:
                return None
            raise
        return repo

    def repo(self, name: str, info: RepoInfo | None = None) -> AsyncRepo:
        """A handle on a repository you know exists. Makes no request."""
        return AsyncRepo(self, name, info)

    async def list_repos(
        self, *, limit: int | None = None, cursor: str | None = None
    ) -> tuple[list[AsyncRepo], str | None]:
        """One page of repositories, and the cursor for the next (``None`` on the last)."""
        w = await self._json(
            "GET", self._org_path("/repos"), params=_wire.query(limit=limit, after=cursor)
        )
        repos = [
            AsyncRepo(self, info.name, info)
            for info in (RepoInfo._from_wire(r) for r in w["repos"])
        ]
        return repos, w.get("next_after")

    async def iterate_repos(self, *, page_size: int | None = None) -> AsyncIterator[AsyncRepo]:
        """Every repository in the organization, fetching pages as you iterate."""
        cursor: str | None = None
        while True:
            repos, cursor = await self.list_repos(limit=page_size, cursor=cursor)
            for repo in repos:
                yield repo
            if not cursor:
                return

    async def delete_repo(self, name: str) -> None:
        """Deletes a repository by name."""
        await self.repo(name).delete()

    async def create_repos(
        self, names: list[str], *, public: bool | None = None
    ) -> list[BatchResult]:
        """Creates up to 1,000 repositories in one call.

        One failing does not stop the rest: check ``ok`` on each result,
        which come back in request order.
        """
        body = {"repos": [_wire.create_body(n, public, None, None) for n in names]}
        w = await self._json("POST", self._org_path("/repos/batch/create"), json=body)
        return [BatchResult._from_wire(r) for r in w["results"]]

    async def delete_repos(self, names: list[str]) -> list[BatchResult]:
        """Deletes up to 1,000 repositories by name."""
        w = await self._json("POST", self._org_path("/repos/batch/delete"), json={"names": names})
        return [BatchResult._from_wire(r) for r in w["results"]]

    async def create_mirror(
        self,
        *,
        name: str,
        origin: str,
        provider: str | None = None,
        installation_id: str | None = None,
        public: bool | None = None,
    ) -> AsyncRepo:
        """Mirrors a repository from GitHub (``owner/name``) or any git host (a URL,
        with ``provider="generic"``). The first sync runs in the background."""
        body: Wire = {"name": name, "origin": origin}
        if provider is not None:
            body["provider"] = provider
        if installation_id is not None:
            body["installation_id"] = installation_id
        if public is not None:
            body["public"] = public
        w = await self._json("POST", self._org_path("/mirrors"), json=body)
        info = RepoInfo._from_wire({**w["repo"], "org": self.org, "clone_url": w["clone_url"]})
        return AsyncRepo(self, info.name, info)

    # ------------------------------------------------------------------ tokens

    async def create_token(
        self,
        *,
        scopes: list[TokenScope],
        repo: str | None = None,
        label: str | None = None,
        ttl: int | None = None,
    ) -> CreatedToken:
        """Mints an API token. The secret is in the result and nowhere else, ever.

        ``repo`` restricts it to one repository; ``ttl`` (seconds, at most a
        year) makes it die on its own.
        """
        return await self._mint(self.org, scopes=scopes, repo=repo, label=label, ttl=ttl)

    async def _mint(
        self,
        org: str,
        *,
        scopes: list[TokenScope],
        repo: str | None,
        label: str | None,
        ttl: int | None,
    ) -> CreatedToken:
        body: Wire = {"scopes": scopes}
        if repo is not None:
            body["repo"] = repo
        if label is not None:
            body["label"] = label
        if ttl is not None:
            body["expires_in_secs"] = int(ttl)
        return CreatedToken._from_wire(
            await self._json("POST", self._org_path("/tokens", org), json=body)
        )

    async def list_tokens(self) -> list[TokenInfo]:
        """Tokens, without their secrets: every token for an admin, your own for a member."""
        w = await self._json("GET", self._org_path("/tokens"))
        return [TokenInfo._from_wire(t) for t in w["tokens"]]

    async def revoke_token(self, id: str) -> None:
        """Revokes a token. It stops working on the next request."""
        await self._json("DELETE", self._org_path(f"/tokens/{_wire.seg(id)}"))


class AsyncRepo:
    """One repository. Get one from ``create_repo``, ``find_one`` or ``repo``."""

    def __init__(self, client: AsyncWeft, name: str, info: RepoInfo | None = None) -> None:
        self._client = client
        self.name = name
        """The repository's name."""
        self.org = info.org if info else client.org
        """The namespace it lives in."""
        self._info = info

    def __repr__(self) -> str:
        return f"{type(self).__name__}(org={self.org!r}, name={self.name!r})"

    @property
    def info(self) -> RepoInfo | None:
        """What the API last said about this repository; ``None`` until fetched."""
        return self._info

    @property
    def id(self) -> str | None:
        return self._info.id if self._info else None

    @property
    def default_branch(self) -> str | None:
        return self._info.default_branch if self._info else None

    @property
    def clone_url(self) -> str:
        """The HTTPS git remote, without credentials."""
        if self._info:
            return self._info.clone_url
        return f"{self._client.base_url}/{self.org}/{self.name}.git"

    def _path(self, suffix: str = "") -> str:
        return f"v1/orgs/{_wire.seg(self.org)}/repos/{_wire.seg(self.name)}{suffix}"

    # -------------------------------------------------------------- metadata

    async def refresh(self) -> RepoInfo:
        """Fetches the repository's metadata, stores it on ``info`` and returns it."""
        self._info = RepoInfo._from_wire(await self._client._json("GET", self._path()))
        return self._info

    async def update(
        self,
        *,
        description: str | None | Unset = UNSET,
        homepage: str | None | Unset = UNSET,
        public: bool | Unset = UNSET,
        default_branch: str | Unset = UNSET,
    ) -> RepoInfo:
        """Edits the repository. Arguments left out are left alone; ``None`` clears
        ``description`` or ``homepage``. ``public`` and ``default_branch`` need
        ``org:admin``."""
        body: Wire = {}
        if description is not UNSET:
            body["description"] = description
        if homepage is not UNSET:
            body["homepage"] = homepage
        if public is not UNSET:
            body["public"] = public
        if default_branch is not UNSET:
            body["default_branch"] = default_branch
        self._info = RepoInfo._from_wire(await self._client._json("PATCH", self._path(), json=body))
        return self._info

    async def delete(self) -> None:
        """Deletes the repository. Instant; the storage is swept later, forks survive."""
        await self._client._json("DELETE", self._path())

    async def fork(self, *, org: str | None = None, name: str | None = None) -> AsyncRepo:
        """Forks the repository. The fork is readable once ``info.fork_state`` is
        ``ready``. Needs a token that acts for a person."""
        body: Wire = {}
        if org is not None:
            body["org"] = org
        if name is not None:
            body["name"] = name
        info = RepoInfo._from_wire(
            await self._client._json("POST", self._path("/forks"), json=body)
        )
        return AsyncRepo(self._client, info.name, info)

    # ------------------------------------------------------------------ git

    async def get_remote_url(
        self, *, access: str = "write", ttl: int = 3600, label: str | None = None
    ) -> str:
        """A git remote URL with a fresh credential scoped to this repository only:
        ``https://x:weft_…@api.weft.sh/acme/session-8412.git``.

        Hand it to a sandbox or a ``git clone`` without handing over your own
        token. ``access`` is ``"write"`` (the default) or ``"read"``; the
        credential dies after ``ttl`` seconds (an hour by default).
        """
        if access not in ("read", "write"):
            raise ValueError('access must be "read" or "write"')
        minted = await self._client._mint(
            self.org,
            scopes=["repo:read" if access == "read" else "repo:write"],
            repo=self.name,
            label=label or f"remote:{self.name}",
            ttl=ttl,
        )
        return _wire.remote_url(self.clone_url, minted.token)

    # --------------------------------------------------------------- writing

    def create_commit(
        self,
        *,
        message: str,
        branch: str | None = None,
        author: Identity | None = None,
        expected_parent: str | None | Unset = UNSET,
        context: Any = None,
    ) -> AsyncCommitBuilder:
        """Starts a commit. Add changes with ``.put()`` and ``.delete()``, then ``.send()``.

        Args:
            message: The commit message.
            branch: Defaults to ``"main"`` — not the repository's default
                branch, so pass it if yours differs. Created if missing.
            author: Who ``git log`` shows. Defaults to the person or token acting.
            expected_parent: Optimistic concurrency. A SHA: the branch must
                point exactly there, or ``send()`` raises ``WeftConflictError``
                carrying the current tip. ``None``: the branch must not exist
                yet. Leave it out to commit on whatever the tip is now.
            context: Anything JSON. Recorded immutably in the audit trail
                beside the commit and the token that made it.
        """
        return AsyncCommitBuilder(
            self,
            message=message,
            branch=branch,
            author=author,
            expected_parent=expected_parent,
            context=context,
        )

    async def _send_commit(
        self,
        *,
        message: str,
        branch: str | None,
        author: Identity | None,
        expected_parent: str | None | Unset,
        context: Any,
        operations: list[Wire],
    ) -> CommitResult:
        if not operations:
            raise ValueError("a commit needs at least one operation")
        body: Wire = {"message": message, "operations": operations}
        if branch is not None:
            body["branch"] = branch
        if author is not None:
            body["author"] = {"name": author.name, "email": author.email}
        if expected_parent is not UNSET:
            body["expected_parent"] = expected_parent
        if context is not None:
            body["context"] = context
        return CommitResult._from_wire(
            await self._client._json("POST", self._path("/commits"), json=body)
        )

    # --------------------------------------------------------------- reading

    async def get_file(
        self, path: str, *, ref: str | None = None, if_none_match: str | None = None
    ) -> FileResult | None:
        """Reads a file at any revision: a full commit SHA, a branch, a tag, a full
        ref name or ``HEAD`` (the default).

        Returns ``None`` when the path or the revision does not exist. A
        repository that does not exist (or that you cannot see) raises a 404
        ``WeftError``. Pass an earlier result's ``etag`` as ``if_none_match``
        and an unchanged file answers ``not_modified=True`` with no bytes.
        """
        extra = {"Accept": "*/*"}
        if if_none_match:
            extra["If-None-Match"] = if_none_match
        try:
            response = await self._client._request(
                "GET",
                self._path(f"/files/{_wire.path_of(path)}"),
                params=_wire.query(at=ref),
                headers=extra,
                allow=(304,),
            )
        except WeftError as exc:
            if _wire.is_missing_in_repo(exc):
                return None
            raise
        return _wire.file_result(response, if_none_match)

    async def read_file(self, path: str, *, ref: str | None = None) -> str | None:
        """A file as UTF-8 text, or ``None`` when it is not there. See ``get_file``."""
        file = await self.get_file(path, ref=ref)
        return file.text if file else None

    async def get_tree(
        self,
        *,
        path: str | None = None,
        ref: str | None = None,
        sizes: bool = False,
        history: bool = False,
    ) -> TreeResult:
        """One directory: names, modes, kinds and object ids.

        ``sizes=True`` measures each blob; ``history=True`` adds the commit
        that last touched each entry (a bounded walk).
        """
        suffix = f"/tree/{_wire.path_of(path)}" if path else "/tree"
        w = await self._client._json(
            "GET", self._path(suffix), params=_wire.query(at=ref, sizes=sizes, history=history)
        )
        return TreeResult._from_wire(w)

    async def list_files(
        self, *, path: str | None = None, ref: str | None = None
    ) -> ListFilesResult:
        """Every path under a directory, flat, in one request."""
        suffix = f"/tree/{_wire.path_of(path)}" if path else "/tree"
        w = await self._client._json(
            "GET", self._path(suffix), params=_wire.query(at=ref, recursive=True)
        )
        return ListFilesResult._from_wire(w)

    async def list_commits(
        self,
        *,
        ref: str | None = None,
        path: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> ListCommitsResult:
        """First-parent history, newest first, one page at a time.

        With ``path``, only commits that changed it — each with a ``change``.
        A filtered page examines at most 500 commits, so keep paging while
        ``next_cursor`` is set, even when a page comes back empty.
        """
        w = await self._client._json(
            "GET",
            self._path("/log"),
            params=_wire.query(rev=ref, path=path, limit=limit, after=cursor),
        )
        return ListCommitsResult._from_wire(w)

    async def iterate_commits(
        self, *, ref: str | None = None, path: str | None = None
    ) -> AsyncIterator[CommitEntry]:
        """Every commit in first-parent history, fetching pages as you iterate."""
        cursor: str | None = None
        while True:
            page = await self.list_commits(ref=ref, path=path, cursor=cursor)
            for entry in page.commits:
                yield entry
            cursor = page.next_cursor
            if not cursor:
                return

    async def get_diff(self, *, from_: str, to: str) -> DiffResult:
        """Every file that differs between two revisions."""
        w = await self._client._json(
            "GET", self._path("/diff"), params=_wire.query(**{"from": from_, "to": to})
        )
        return DiffResult._from_wire(w)

    # ------------------------------------------------------------------ refs

    async def list_refs(self) -> ListRefsResult:
        """Every branch and tag at once."""
        return ListRefsResult._from_wire(await self._client._json("GET", self._path("/refs")))

    async def list_branches(self) -> list[Ref]:
        """Branches, sorted, with the default marked."""
        w = await self._client._json("GET", self._path("/branches"))
        return [Ref._from_wire(r) for r in w["branches"]]

    async def create_branch(self, *, name: str, from_: str) -> str:
        """Creates a branch at a revision. Returns the commit it points at."""
        body = {"name": name, "from": from_}
        w = await self._client._json("POST", self._path("/branches"), json=body)
        oid: str = w["oid"]
        return oid

    async def delete_branch(self, name: str) -> None:
        await self._client._json("DELETE", self._path(f"/branches/{_wire.seg(name)}"))

    async def list_tags(self) -> list[Ref]:
        """Tags, sorted."""
        w = await self._client._json("GET", self._path("/tags"))
        return [Ref._from_wire(r) for r in w["tags"]]

    async def create_tag(self, *, name: str, target: str) -> str:
        """Creates a lightweight tag at a revision. Returns the commit it points at."""
        body = {"name": name, "target": target}
        w = await self._client._json("POST", self._path("/tags"), json=body)
        oid: str = w["oid"]
        return oid

    async def delete_tag(self, name: str) -> None:
        await self._client._json("DELETE", self._path(f"/tags/{_wire.seg(name)}"))

    # ------------------------------------------------------------------ undo

    async def reset(
        self, *, to: str, branch: str | None = None, expected_head: str | None = None
    ) -> str:
        """Moves a branch to another commit — the undo primitive. Returns the new tip.

        Commits left behind stay reachable by SHA until garbage collection,
        so nothing is erased from the record. With ``expected_head``, a branch
        that has moved raises ``WeftConflictError``.
        """
        body: Wire = {"to": to}
        if branch is not None:
            body["branch"] = branch
        if expected_head is not None:
            body["expected_head"] = expected_head
        w = await self._client._json("POST", self._path("/reset"), json=body)
        oid: str = w["oid"]
        return oid

    async def revert(self, *, branch: str | None = None, expected_head: str | None = None) -> str:
        """Appends a commit that undoes the branch head, keeping history. Returns it."""
        body: Wire = {}
        if branch is not None:
            body["branch"] = branch
        if expected_head is not None:
            body["expected_head"] = expected_head
        w = await self._client._json("POST", self._path("/revert"), json=body)
        commit: str = w["commit"]
        return commit

    # -------------------------------------------------------------- webhooks

    async def create_webhook(self, *, url: str) -> CreatedWebhook:
        """Subscribes a URL to this repository's events. Check deliveries with
        ``verify_webhook`` and the returned ``secret``."""
        w = await self._client._json("POST", self._path("/webhooks"), json={"url": url})
        return CreatedWebhook(id=w["id"], url=w["url"], secret=w["secret"])

    async def list_webhooks(self) -> list[WebhookSubscription]:
        w = await self._client._json("GET", self._path("/webhooks"))
        return [
            WebhookSubscription(id=s["id"], url=s["url"], created_at=s["created_at"])
            for s in w["subscriptions"]
        ]

    async def delete_webhook(self, id: str) -> None:
        await self._client._json("DELETE", self._path(f"/webhooks/{_wire.seg(id)}"))

    # ---------------------------------------------------------------- export

    async def start_export(self) -> ExportJob:
        """Starts exporting the repository as a standard git bundle."""
        w = await self._client._json("POST", self._path("/export"))
        return ExportJob(job=w["job"], state=w["state"], error=None, download=None)

    async def get_export(self, job: str) -> ExportJob:
        return ExportJob._from_wire(
            await self._client._json("GET", self._path(f"/export/{_wire.seg(job)}"))
        )

    async def download_export(self, job: str) -> bytes:
        """A finished export's bundle. ``git clone repo.bundle`` reads it."""
        response = await self._client._request(
            "GET",
            self._path(f"/export/{_wire.seg(job)}/download"),
            headers={"Accept": "application/octet-stream"},
        )
        return response.content


class AsyncCommitBuilder:
    """Collects file changes and sends them as one commit.

    ::

        result = await (
            repo.create_commit(message="agent step 12")
            .put("src/app.py", source)
            .delete("notes.txt")
            .send()
        )
    """

    def __init__(
        self,
        repo: AsyncRepo,
        *,
        message: str,
        branch: str | None,
        author: Identity | None,
        expected_parent: str | None | Unset,
        context: Any,
    ) -> None:
        self._repo = repo
        self._message = message
        self._branch = branch
        self._author = author
        self._expected_parent = expected_parent
        self._context = context
        self._operations: list[Wire] = []

    def put(self, path: str, content: FileContent) -> AsyncCommitBuilder:
        """Writes a file, creating it or replacing what is there."""
        self._operations.append(_wire.put_operation(path, content))
        return self

    def delete(self, path: str) -> AsyncCommitBuilder:
        """Removes a file."""
        self._operations.append({"op": "delete", "path": path})
        return self

    def __len__(self) -> int:
        return len(self._operations)

    async def send(self) -> CommitResult:
        """Makes the commit. Raises ``WeftConflictError`` when ``expected_parent``
        no longer matches the branch. A commit holds up to 10,000 operations."""
        return await self._repo._send_commit(
            message=self._message,
            branch=self._branch,
            author=self._author,
            expected_parent=self._expected_parent,
            context=self._context,
            operations=list(self._operations),
        )
