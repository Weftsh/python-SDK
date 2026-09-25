# weftsh

The Python SDK for [Weft](https://weft.sh): a real git repository per user,
session or agent, created in under 100 ms and written entirely over HTTP.

```python
import os
from weftsh import Weft

weft = Weft(token=os.environ["WEFT_TOKEN"], org="acme")

repo = weft.create_repo()

(
    repo.create_commit(message="agent step 1")
    .put("src/app.py", "print('hello')\n")
    .put("README.md", "# session\n")
    .send()
)

print(repo.read_file("src/app.py"))
print(repo.get_remote_url())  # https://x:weft_…@api.weft.sh/acme/repo-….git
```

No checkout, no clone, no disk. Every repository is still a stock git remote
you can clone, push to and export.

- A sync client, `Weft`, and an identical `asyncio` one, `AsyncWeft`.
- One dependency: [`httpx`](https://www.python-httpx.org/).
- Fully typed (`py.typed`, checked with `mypy --strict`); results are frozen
  dataclasses.
- Python 3.10+.

## Quickstart

From nothing to a repository you have committed to over HTTP and cloned with
`git`, in about five minutes.

**1. Get a token.** [Create an account](https://weft.sh/login?mode=signup)
(free, no card) and an organization, then mint a token under
**Settings → Tokens** with `org:read` and `repo:write`. `repo:write` creates and commits;
`org:read` lets the SDK mint the short-lived clone credential in step 4. An
`org:admin` token does both.

```bash
export WEFT_TOKEN=weft_…     # the token you just minted
export WEFT_ORG=acme         # your organization's name
```

**2. Install.**

```bash
pip install weftsh
```

**3. Save this as `quickstart.py` and run it.** It needs `git` on your `PATH` for
the last step.

<!-- quickstart:start — kept identical to examples/quickstart.py by a test -->
```python
import os
import subprocess
import tempfile
from pathlib import Path

from weftsh import DEFAULT_BASE_URL, Weft

weft = Weft(
    token=os.environ["WEFT_TOKEN"],
    org=os.environ["WEFT_ORG"],
    base_url=os.environ.get("WEFT_URL", DEFAULT_BASE_URL),  # optional
)

# 1. A repository of its own: a real git remote, made in well under a second.
repo = weft.create_repo()
print("created   ", repo.name)

# 2. A commit, straight over HTTP. No clone, no checkout, no disk.
result = (
    repo.create_commit(message="first commit")
    .put("hello.txt", "hello from the Weft SDK\n")
    .send()
)
print("committed ", result.commit[:7])

# 3. Read it back, at the branch tip or at any commit.
print("read back ", repr(repo.read_file("hello.txt")))

# 4. It is still git. This URL carries a credential for this repository
#    only, and it expires in an hour.
url = repo.get_remote_url()
clone = Path(tempfile.mkdtemp(prefix="weft-")) / repo.name
subprocess.run(["git", "clone", "--quiet", url, str(clone)], check=True)
print("cloned    ", (clone / "hello.txt").read_text().strip())
```
<!-- quickstart:end -->

```bash
python quickstart.py
```

**4. See what it did.** You should get something like this (your
repository name and commit will differ):

```text
created    repo-75f21a56-2e6d-445f-bcde-09a7f20d0bfb
committed  889ba6d
read back  'hello from the Weft SDK\n'
cloned     hello from the Weft SDK
```

That repository is yours: it is in the dashboard, you can `git push` to it,
and it costs nothing while it sits there. Run the script again and you get a
second one.

**Where next:**

- [Commits](#commits): branches, concurrency with `expected_parent`, and the audit `context`
- [Reading](#reading): any file at any revision, history, diffs
- [Git remotes](#git-remotes): read-only URLs, lifetimes, and what the credential can reach
- [asyncio](#asyncio): the same client with `await`

## Contents

- [Quickstart](#quickstart)
- [Install](#install)
- [Set up the client](#set-up-the-client)
- [Repositories](#repositories)
- [Commits](#commits)
- [Reading](#reading)
- [Branches and tags](#branches-and-tags)
- [Undo](#undo)
- [Git remotes](#git-remotes)
- [Tokens](#tokens)
- [Webhooks](#webhooks)
- [Export](#export)
- [Mirrors](#mirrors)
- [Errors](#errors)
- [asyncio](#asyncio)
- [Retries, proxies and timeouts](#retries-proxies-and-timeouts)
- [API reference](#api-reference)

## Install

```bash
pip install weftsh
# or
uv add weftsh
```

## Set up the client

You need an organization and a token. [Sign up](https://weft.sh/login?mode=signup),
create an organization, and mint a token under **Settings → Tokens** (or see
[authentication](https://weft.sh/docs/authentication/)).

```python
from weftsh import Weft

weft = Weft(
    token=os.environ["WEFT_TOKEN"],  # weft_<id>_<secret>
    org="acme",  # your organization, or your personal namespace
)
```

| Argument      | Default               | What it is                                               |
| ------------- | --------------------- | -------------------------------------------------------- |
| `token`       | —                     | A Weft API token. Required.                              |
| `org`         | —                     | The namespace every call works in. Required.             |
| `base_url`    | `https://api.weft.sh` | The API origin — change it for a self-hosted deployment. |
| `http_client` | a new `httpx.Client`  | Your own client, for retries, proxies or logging.        |
| `timeout`     | `30.0`                | Seconds, for the client the SDK makes.                   |

`Weft` is a context manager (`with Weft(...) as weft:`) and has `close()`.

Keep the token on the server. To give a sandbox, a subprocess or a user
access to one repository, hand it a [remote URL](#git-remotes) or a
[repo-scoped token](#tokens) instead.

## Repositories

```python
# A generated name — the usual choice for one repository per session.
repo = weft.create_repo()

# Or choose everything.
docs = weft.create_repo(
    name="docs-site",  # letters, digits, - _ . — up to 100 characters
    default_branch="main",
    public=False,
    description="Generated documentation",
)

repo.name  # 'repo-4f7c…'
repo.info.clone_url  # 'https://api.weft.sh/acme/repo-4f7c….git'
```

Find one by name — `None` when there is none you can see:

```python
found = weft.find_one(name="docs-site")
```

Or get a handle with **no request at all**, when you already know it exists:

```python
repo = weft.repo("session-8412")
repo.create_commit(message="resume").put("state.json", "{}").send()
```

List them a page at a time, or iterate over all of them:

```python
repos, next_cursor = weft.list_repos(limit=100)

for repo in weft.iterate_repos():
    print(repo.name, repo.info.stored_bytes)
```

Fleets are one call. Up to 1,000 per request; each item reports its own
outcome, in request order:

```python
results = weft.create_repos(["agent-1", "agent-2"])
failed = [r for r in results if not r.ok]  # BatchResult(name, ok=False, error=…)

weft.delete_repos(["agent-1", "agent-2"])
```

Edit, delete, fork:

```python
repo.update(description="Session 8412", homepage="https://example.com")
repo.update(description=None)  # None clears; arguments left out are left alone

repo.delete()  # instant; storage is swept later, forks survive

fork = repo.fork(org="my-team", name="experiment")
fork.info.fork_state  # 'pending', then 'ready'
```

A dormant repository costs storage and nothing else, so creating one per
session and keeping it is the normal pattern, not a cleanup problem.

## Commits

Build a commit from changes and send it. The tree is built server-side;
nothing is checked out anywhere.

```python
from weftsh import Identity

result = (
    repo.create_commit(
        message="agent step 12",
        branch="main",  # the default; created if missing
        author=Identity(name="Build Agent", email="agent@acme.dev"),  # optional
        context={"run": "r-42", "prompt": "p-991"},  # optional audit record
    )
    .put("src/app.py", source)  # str → UTF-8 text
    .put("assets/logo.png", png)  # bytes → binary-safe
    .delete("notes.txt")
    .send()
)

result.commit  # the new commit's SHA
result.parent  # the commit it was made on — None for a branch's first
```

Commits are durable when `send()` returns. `branch` defaults to `"main"`
whatever the repository's default branch is, so pass it if yours differs.

**`context`** is any JSON you like. It is written to the organization's
immutable audit trail beside the commit and the token that made it — how you
answer "what did the agent change, and why" months later.

**Concurrency.** Pass `expected_parent` with the commit you built against.
If the branch has moved, the commit is refused with a
[`WeftConflictError`](#errors) carrying the current tip:

```python
from weftsh import WeftConflictError

try:
    repo.create_commit(message="step 13", expected_parent=last_seen).put("a.txt", "x").send()
except WeftConflictError as e:
    last_seen = e.current_tip  # rebase your change onto this and retry
```

| `expected_parent` | Meaning                                                     |
| ----------------- | ----------------------------------------------------------- |
| left out          | Commit on top of whatever the branch points at now.         |
| `"3f2a…"`         | The branch must point exactly here, or 409.                 |
| `None`            | The branch must not exist yet — create it with this commit. |

A commit holds up to 10,000 operations.

## Reading

Any file, at any revision. A revision is a full 40-character commit SHA, a
branch, a tag, a full ref name (`refs/heads/main`) or `HEAD`; git's `main~3`
and short SHAs are not understood — walk `list_commits` instead.

```python
text = repo.read_file("src/app.py")  # str, or None if absent
old = repo.read_file("src/app.py", ref="3f2a…")
```

`get_file` gives you the bytes and what the server knows about them:

```python
file = repo.get_file("assets/logo.png")
if file:
    file.content  # bytes
    file.binary  # True
    file.commit  # the commit the content came from
    file.etag  # the content hash
```

Cache with the ETag — an unchanged file costs a 304 and no bytes:

```python
again = repo.get_file("src/app.py", if_none_match=file.etag)
if again and again.not_modified:
    ...  # use what you have
```

Directories, one level at a time or all at once:

```python
tree = repo.get_tree(path="src", ref="main")
tree.entries  # [TreeEntry(name, kind='blob' | 'tree', mode, oid, size, last_commit)]

repo.get_tree(sizes=True)  # measure each blob
repo.get_tree(history=True)  # the last commit to touch each entry

repo.list_files().paths  # ['README.md', 'src/', 'src/app.py', …]
```

History, newest first — a page at a time, or iterated. Optionally only the
commits that touched one path:

```python
page = repo.list_commits(limit=50)
page.commits[0]  # CommitEntry(sha, parents, author, committer, message, tree, change)
page.next_cursor  # pass back as cursor=…

for commit in repo.iterate_commits(path="src/app.py"):
    print(commit.sha, commit.change)  # 'added' | 'modified' | 'deleted'
```

A path-filtered page examines at most 500 commits, so a long search is several
bounded requests rather than one unbounded scan; `iterate_commits` keeps
going for you.

What changed between two revisions (`from` is a keyword in Python, hence
`from_`):

```python
diff = repo.get_diff(from_="v1.0.0", to="main")
diff.changes  # [DiffChange(path, status, old_oid, new_oid, old_mode, new_mode)]
```

## Branches and tags

```python
repo.create_branch(name="feature/login", from_="main")  # returns the commit
repo.list_branches()  # [Ref(name, full, oid, default)]
repo.delete_branch("feature/login")

repo.create_tag(name="v1.0.0", target="main")
repo.list_tags()
repo.delete_tag("v1.0.0")

repo.list_refs()  # ListRefsResult(head='refs/heads/main', refs=[RefTip(name, oid), …])
```

## Undo

Undo is a primitive, not a project.

```python
# Put the branch back where it was before the agent went sideways.
repo.reset(branch="main", to=good_commit, expected_head=bad_commit)

# Or append a commit that undoes the head, keeping the history.
repo.revert(branch="main")
```

A reset never erases anything: the commits it leaves behind stay reachable by
SHA until garbage collection, so the audit trail survives the undo. Both take
`expected_head` and raise `WeftConflictError` if the branch has moved.

## Git remotes

Every repository is a real git remote. `get_remote_url()` returns one with a
**fresh credential scoped to that one repository**, so you can hand it to a
sandbox, a CI job or an agent without handing over your own token:

```python
url = repo.get_remote_url()  # can push; dies in an hour
read_only = repo.get_remote_url(access="read", ttl=600)
```

```bash
git clone "$url" && cd session-8412
git commit -am "from a sandbox" && git push
```

| Argument | Default         | What it is                                          |
| -------- | --------------- | --------------------------------------------------- |
| `access` | `"write"`       | `"write"` clones and pushes; `"read"` only clones.  |
| `ttl`    | `3600`          | Seconds until the credential dies. At most a year.  |
| `label`  | `remote:<repo>` | Shown in the token list and in the audit trail.     |

Each call mints a new token, so the client's own token must be allowed to
mint one: an `org:admin` token, or a personal token carrying `org:read` (to
mint) and `repo:write` (to grant write access; `repo:read` is enough for
`access="read"`). `repo.clone_url` is the same URL with no credential in it.

## Tokens

```python
minted = weft.create_token(
    scopes=["repo:write"],  # org:admin · org:read · repo:read · repo:write · repo:cache
    repo="session-8412",  # optional: this repository only
    label="sandbox-8412",
    ttl=3600,  # optional: seconds until it dies on its own
)
minted.token  # the secret — shown exactly once

weft.list_tokens()  # without secrets
weft.revoke_token(minted.id)  # dead on the next request
```

## Webhooks

Subscribe a URL to a repository's events:

```python
hook = repo.create_webhook(url="https://app.example.com/hooks/weft")
hook.secret  # shown once — store it
```

Verify every delivery before trusting it. `verify_webhook` checks the
`X-Weft-Signature-256` header against the raw body and returns the event, or
`None`:

```python
from weftsh import verify_webhook


# Flask; any framework that gives you the raw body works the same way.
@app.post("/hooks/weft")
def weft_hook():
    event = verify_webhook(
        payload=request.get_data(),  # the raw body — not re-serialized JSON
        signature=request.headers.get("X-Weft-Signature-256"),
        secret=os.environ["WEFT_WEBHOOK_SECRET"],
    )
    if event is None:
        return "bad signature", 401
    if event["event"] == "push":
        # Something moved. Only commits made over REST carry `branch` and
        # `commit`; a `git push` says only that something changed — fetch
        # to find out what.
        ...
    return "ok"
```

| Event            | Fires when                                                                     |
| ---------------- | ------------------------------------------------------------------------------ |
| `push`           | Anything moves a ref: `git push` over HTTPS or SSH, or a commit made over REST |
| `change.landed`  | A change lands through the land queue                                          |
| `change.ejected` | The lander refused a change                                                    |

`repo.list_webhooks()` and `repo.delete_webhook(id)` manage subscriptions.

## Export

Any repository, any time, as a standard git bundle — adopting Weft is not a
lock-in decision.

```python
job = repo.start_export()
while job.state not in ("done", "failed"):
    time.sleep(0.5)
    job = repo.get_export(job.job)

Path("repo.bundle").write_bytes(repo.download_export(job.job))
```

```bash
git clone repo.bundle my-repo
```

## Mirrors

Mirror a repository from GitHub or any git host; the first sync runs in the
background.

```python
weft.create_mirror(name="linux", origin="torvalds/linux", public=True)
weft.create_mirror(name="tool", provider="generic", origin="https://git.example.com/acme/tool.git")
```

Private GitHub origins need the Weft GitHub App — see
[the mirror quickstart](https://weft.sh/docs/quickstart-mirror/).

## Errors

Every failed request raises a `WeftError`:

```python
from weftsh import WeftError

try:
    weft.create_repo(name="taken")
except WeftError as e:
    e.status  # 409
    e.message  # the server's own sentence, written to be shown to a person
    e.body  # the parsed response body
```

| Class               | When                                                                                     |
| ------------------- | ---------------------------------------------------------------------------------------- |
| `WeftConflictError` | `409` from a concurrency check. `current_tip` is where the branch is. Subclass of `WeftError`. |
| `WeftError`         | Anything else. `status` is `0` when the request never got an answer.                     |

Lookups that commonly miss return `None` instead of raising: `find_one` for a
repository, and `get_file` and `read_file` for a path or revision that is not
there. A file read from a repository that does not exist still raises — a typo
in a repository name is not a missing file.

A `404` also covers "exists, but not for you" — Weft does not tell a caller
about repositories it cannot see.

## asyncio

`AsyncWeft` is the same client with `await`. Every method, argument and
result is identical; iterators are `async for`.

```python
from weftsh import AsyncWeft

async with AsyncWeft(token=os.environ["WEFT_TOKEN"], org="acme") as weft:
    repo = await weft.create_repo()
    await repo.create_commit(message="step 1").put("a.txt", "a").send()
    print(await repo.read_file("a.txt"))
    async for commit in repo.iterate_commits():
        print(commit.sha)
```

## Retries, proxies and timeouts

The SDK never retries on its own: a write that failed on the way back may
still have happened. Pass your own `httpx` client to decide — transport-level
retries for connection failures, for example:

```python
import httpx

http = httpx.Client(transport=httpx.HTTPTransport(retries=2), timeout=60)
weft = Weft(token=token, org="acme", http_client=http)
```

A client you pass is yours to close. A commit with `expected_parent` set is
safe to retry: if the first attempt landed, the retry answers `409` with your
own commit as `current_tip`.

## API reference

### `Weft` / `AsyncWeft`

| Method | Returns |
| --- | --- |
| `Weft(token=, org=, base_url=, http_client=, timeout=)` | |
| `create_repo(name=, public=, default_branch=, description=)` | `Repo` |
| `find_one(name=)` | `Repo \| None` |
| `repo(name, info=None)` | `Repo` — no request |
| `list_repos(limit=, cursor=)` | `(list[Repo], next_cursor)` |
| `iterate_repos(page_size=)` | iterator of `Repo` |
| `delete_repo(name)` | `None` |
| `create_repos(names, public=)` / `delete_repos(names)` | `list[BatchResult]` |
| `create_mirror(name=, origin=, provider=, installation_id=, public=)` | `Repo` |
| `create_token(scopes=, repo=, label=, ttl=)` | `CreatedToken` |
| `list_tokens()` | `list[TokenInfo]` |
| `revoke_token(id)` | `None` |
| `close()` / `aclose()` | |

### `Repo` / `AsyncRepo`

| Member | Returns |
| --- | --- |
| `name`, `org`, `id`, `default_branch`, `clone_url`, `info` | |
| `refresh()` | `RepoInfo` |
| `update(description=, homepage=, public=, default_branch=)` | `RepoInfo` |
| `delete()` | `None` |
| `fork(org=, name=)` | `Repo` |
| `get_remote_url(access=, ttl=, label=)` | `str` |
| `create_commit(message=, branch=, author=, expected_parent=, context=)` → `.put(path, content)` · `.delete(path)` · `.send()` | `CommitResult` |
| `read_file(path, ref=)` | `str \| None` |
| `get_file(path, ref=, if_none_match=)` | `FileResult \| None` |
| `get_tree(path=, ref=, sizes=, history=)` | `TreeResult` |
| `list_files(path=, ref=)` | `ListFilesResult` |
| `list_commits(ref=, path=, limit=, cursor=)` | `ListCommitsResult` |
| `iterate_commits(ref=, path=)` | iterator of `CommitEntry` |
| `get_diff(from_=, to=)` | `DiffResult` |
| `list_refs()` | `ListRefsResult` |
| `list_branches()` / `list_tags()` | `list[Ref]` |
| `create_branch(name=, from_=)` / `create_tag(name=, target=)` | `str` (the commit) |
| `delete_branch(name)` / `delete_tag(name)` | `None` |
| `reset(to=, branch=, expected_head=)` | `str` (the new tip) |
| `revert(branch=, expected_head=)` | `str` (the new commit) |
| `create_webhook(url=)` | `CreatedWebhook` |
| `list_webhooks()` / `delete_webhook(id)` | |
| `start_export()` / `get_export(job)` | `ExportJob` |
| `download_export(job)` | `bytes` |

### Functions

| Function | Returns |
| --- | --- |
| `verify_webhook(payload=, signature=, secret=)` | `dict \| None` |

Everything is typed; your editor has the rest. The full REST API is described
at [weft.sh/openapi.json](https://weft.sh/openapi.json).

## Development

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

The sync client is generated from the async one. Edit
`src/weftsh/_async_client.py`, then run `uv run python scripts/unasync.py`; a
test fails if the committed `_sync_client.py` is stale.

The unit tests check what the SDK sends. The end-to-end suite checks that a
real server agrees — run it against any Weft deployment with an `org:admin`
token:

```bash
WEFT_E2E_URL=http://127.0.0.1:8080 WEFT_E2E_ORG=acme WEFT_E2E_TOKEN=weft_… uv run pytest tests/test_e2e.py
```

It creates repositories, clones and pushes with the real `git` CLI through
`get_remote_url`, runs `git fsck --full --strict` on the clone, and deletes
everything it made.

## License

MIT
