"""The SDK against a real Weft server. The unit tests check what we send;
these check that the server agrees, which a mocked transport cannot.

    WEFT_E2E_URL=http://127.0.0.1:8080 WEFT_E2E_TOKEN=weft_… WEFT_E2E_ORG=acme \
        pytest tests/test_e2e.py

Skipped unless all three are set. The token needs org:admin (it mints
repo-scoped tokens and creates webhooks). Every repository it makes is
deleted at the end.
"""

from __future__ import annotations

import http.server
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

from weftsh import AsyncWeft, Identity, Repo, Weft, WeftConflictError, WeftError, verify_webhook

URL = os.environ.get("WEFT_E2E_URL")
TOKEN = os.environ.get("WEFT_E2E_TOKEN")
ORG = os.environ.get("WEFT_E2E_ORG")

pytestmark = pytest.mark.skipif(
    not (URL and TOKEN and ORG), reason="set WEFT_E2E_URL, WEFT_E2E_TOKEN and WEFT_E2E_ORG"
)

HAS_GIT = shutil.which("git") is not None
LOOPBACK = URL is not None and urlparse(URL).hostname in ("127.0.0.1", "localhost", "::1")


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


# Built inside fixtures, never at import: a skipped module must not construct
# a client from unset variables.
@pytest.fixture(scope="module")
def weft() -> Iterator[Weft]:
    assert URL and TOKEN and ORG
    client = Weft(token=TOKEN, org=ORG, base_url=URL)
    made: list[str] = []
    client.made = made  # type: ignore[attr-defined]
    yield client
    if made:
        client.delete_repos(made)
    client.close()


def track(weft: Weft, repo: Repo) -> Repo:
    weft.made.append(repo.name)  # type: ignore[attr-defined]
    return repo


@pytest.fixture(scope="module")
def state(weft: Weft) -> dict[str, Any]:
    """One repository, two commits: the shared ground every read test stands on."""
    repo = track(weft, weft.create_repo(description="python sdk e2e"))
    first = (
        repo.create_commit(
            message="first",
            expected_parent=None,
            context={"run": "e2e"},
            author=Identity(name="SDK", email="sdk@weft.test"),
        )
        .put("README.md", "# hello\n")
        .put("src/app.py", "x = 1\n")
        .put("bin/blob", b"\x00\x01\x02\xff\x00")
        .send()
    )
    second = (
        repo.create_commit(message="second", expected_parent=first.commit)
        .put("src/app.py", "x = 2\n")
        .delete("bin/blob")
        .send()
    )
    assert second.parent == first.commit
    return {"repo": repo, "first": first.commit, "second": second.commit}


def test_creates_a_repository_with_a_generated_name(state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    assert repo.name.startswith("repo-")
    assert repo.info is not None
    assert (repo.info.kind, repo.info.default_branch, repo.info.description) == (
        "native",
        "main",
        "python sdk e2e",
    )
    assert repo.clone_url.endswith(f"/{ORG}/{repo.name}.git")
    assert len(state["first"]) == 40


def test_refuses_a_stale_expected_parent_with_the_current_tip(state: dict[str, Any]) -> None:
    with pytest.raises(WeftConflictError) as err:
        state["repo"].create_commit(message="stale", expected_parent=state["first"]).put(
            "a", "b"
        ).send()
    assert err.value.status == 409
    assert err.value.current_tip == state["second"]


def test_reads_files_at_any_revision_with_etags_and_binary_intact(state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    assert repo.read_file("src/app.py") == "x = 2\n"
    assert repo.read_file("src/app.py", ref=state["first"]) == "x = 1\n"
    assert repo.read_file("bin/blob") is None
    assert repo.read_file("README.md", ref="no-such-branch") is None

    blob = repo.get_file("bin/blob", ref=state["first"])
    assert blob is not None
    assert blob.content == b"\x00\x01\x02\xff\x00" and blob.binary and blob.commit == state["first"]

    readme = repo.get_file("README.md")
    assert readme is not None
    again = repo.get_file("README.md", if_none_match=readme.etag)
    assert again is not None and again.not_modified and again.content == b""


def test_a_missing_repository_raises(weft: Weft) -> None:
    with pytest.raises(WeftError) as err:
        weft.repo("no-such-repo-anywhere").read_file("README.md")
    assert err.value.status == 404
    assert weft.find_one(name="no-such-repo-anywhere") is None


def test_lists_trees_and_files(state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    root = repo.get_tree(sizes=True)
    assert root.commit == state["second"]
    by_name = {e.name: e for e in root.entries}
    assert (by_name["README.md"].kind, by_name["README.md"].size) == ("blob", 8)
    assert (by_name["src"].kind, by_name["src"].size) == ("tree", None)

    hist = repo.get_tree(history=True)
    assert hist.history_truncated is False
    src = next(e for e in hist.entries if e.name == "src")
    assert src.last_commit is not None and src.last_commit.sha == state["second"]

    assert [e.name for e in repo.get_tree(path="src").entries] == ["app.py"]
    listing = repo.list_files()
    assert {"README.md", "src/", "src/app.py"} <= set(listing.paths)
    assert listing.truncated is False


def test_pages_history_and_filters_it_by_path(state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    page1 = repo.list_commits(limit=1)
    assert [c.sha for c in page1.commits] == [state["second"]]
    assert page1.next_cursor == state["second"]
    page2 = repo.list_commits(limit=1, cursor=page1.next_cursor)
    assert [c.sha for c in page2.commits] == [state["first"]]
    assert page2.commits[0].author.startswith("SDK <sdk@weft.test>")

    assert [(c.sha, c.change) for c in repo.list_commits(path="README.md").commits] == [
        (state["first"], "added")
    ]
    assert [c.sha for c in repo.iterate_commits()][:2] == [state["second"], state["first"]]


def test_diffs_two_revisions(state: dict[str, Any]) -> None:
    diff = state["repo"].get_diff(from_=state["first"], to=state["second"])
    assert {c.path: c.status for c in diff.changes} == {
        "bin/blob": "deleted",
        "src/app.py": "modified",
    }


def test_branches_and_tags_slashes_included(state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    first, second = state["first"], state["second"]
    assert repo.create_branch(name="feature/x", from_=first) == first
    assert repo.create_tag(name="v1", target=second) == second
    assert repo.create_tag(name="at-main", target="main") == second
    assert repo.create_branch(name="from-tag", from_="v1") == second
    assert repo.get_diff(from_="feature/x", to="v1").from_ == first

    assert [(b.name, b.default) for b in repo.list_branches()] == [
        ("feature/x", False),
        ("from-tag", False),
        ("main", True),
    ]
    assert [t.name for t in repo.list_tags()] == ["at-main", "v1"]
    refs = repo.list_refs()
    assert refs.head == "refs/heads/main"
    assert "refs/heads/feature/x" in {r.name for r in refs.refs}

    for b in ("feature/x", "from-tag"):
        repo.delete_branch(b)
    for t in ("v1", "at-main"):
        repo.delete_tag(t)
    assert [b.name for b in repo.list_branches()] == ["main"]


def test_undoes_with_revert_and_reset_guarded_by_expected_head(state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    reverted = repo.revert(expected_head=state["second"])
    assert repo.read_file("src/app.py") == "x = 1\n"

    with pytest.raises(WeftConflictError) as err:
        repo.reset(to=state["first"], expected_head=state["second"])
    assert err.value.current_tip == reverted

    assert repo.reset(to=state["second"], expected_head=reverted) == state["second"]
    assert repo.read_file("src/app.py") == "x = 2\n"


def test_updates_metadata_and_finds_it_again(weft: Weft, state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    repo.update(description="renamed", homepage="https://example.com")
    found = weft.find_one(name=repo.name)
    assert found is not None and found.info is not None
    assert (found.info.description, found.info.homepage) == ("renamed", "https://example.com")
    repo.update(homepage=None)
    assert repo.refresh().homepage is None
    assert repo.refresh().description == "renamed"


@pytest.mark.skipif(not HAS_GIT, reason="needs the git CLI")
def test_hands_out_a_working_git_remote_scoped_to_one_repo(
    weft: Weft, state: dict[str, Any], tmp_path: Path
) -> None:
    repo: Repo = state["repo"]
    remote = repo.get_remote_url(ttl=300)
    assert remote.startswith(("http://x:weft_", "https://x:weft_"))
    work = tmp_path / "clone"
    git("clone", "--quiet", remote, str(work))
    git("fsck", "--full", "--strict", cwd=work)
    assert (work / "src" / "app.py").read_text() == "x = 2\n"

    ident = ["-c", "user.name=Git", "-c", "user.email=git@weft.test"]
    git(*ident, "commit", "--quiet", "--allow-empty", "-m", "from git", cwd=work)
    git("push", "--quiet", "origin", "main", cwd=work)
    assert repo.list_commits(limit=1).commits[0].sha == git("rev-parse", "HEAD", cwd=work)

    read_only = repo.get_remote_url(access="read", ttl=300)
    ro = tmp_path / "ro"
    git("clone", "--quiet", read_only, str(ro))
    git(*ident, "commit", "--quiet", "--allow-empty", "-m", "nope", cwd=ro)
    with pytest.raises(subprocess.CalledProcessError):
        git("push", "--quiet", "origin", "main", cwd=ro)

    other = track(weft, weft.create_repo())
    with pytest.raises(subprocess.CalledProcessError):
        git("ls-remote", remote.replace(f"/{repo.name}.git", f"/{other.name}.git"))


def test_mints_lists_and_revokes_tokens(weft: Weft, state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    minted = weft.create_token(scopes=["repo:read"], repo=repo.name, label="sdk-e2e", ttl=60)
    assert minted.token.startswith("weft_")
    assert minted.expires_at is not None and minted.expires_at > time.time() * 1000
    listed = next(t for t in weft.list_tokens() if t.id == minted.id)
    assert (listed.label, listed.scopes, listed.repo_id) == ("sdk-e2e", ["repo:read"], repo.id)

    assert URL and ORG
    with Weft(token=minted.token, org=ORG, base_url=URL) as scoped:
        assert scoped.repo(repo.name).read_file("README.md") == "# hello\n"
        weft.revoke_token(minted.id)
        with pytest.raises(WeftError) as err:
            scoped.repo(repo.name).read_file("README.md")
        assert err.value.status in (401, 404)


def test_manages_webhook_subscriptions(state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    hook = repo.create_webhook(url="https://hooks.example.com/weft")
    assert len(hook.secret) > 10
    assert hook.id in {h.id for h in repo.list_webhooks()}
    repo.delete_webhook(hook.id)
    assert hook.id not in {h.id for h in repo.list_webhooks()}


@pytest.mark.skipif(not LOOPBACK, reason="the server must reach a listener in this process")
def test_verifies_a_delivery_the_server_really_signed(state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    got: dict[str, Any] = {}
    arrived = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 — the stdlib's name
            body = self.rfile.read(int(self.headers["Content-Length"]))
            got.update(body=body, signature=self.headers.get("X-Weft-Signature-256"))
            self.send_response(200)
            self.end_headers()
            arrived.set()

        def log_message(self, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        hook = repo.create_webhook(url=f"http://127.0.0.1:{server.server_port}/weft")
        made = repo.create_commit(message="webhook").put("hook.txt", "x").send()
        assert arrived.wait(10), "no delivery arrived"
        event = verify_webhook(payload=got["body"], signature=got["signature"], secret=hook.secret)
        assert event is not None
        assert (event["event"], event["repo_id"]) == ("push", repo.id)
        assert event["payload"]["commit"] == made.commit
        assert (
            verify_webhook(payload=got["body"], signature=got["signature"], secret="not-it") is None
        )
        repo.delete_webhook(hook.id)
    finally:
        server.shutdown()


def test_creates_and_deletes_in_batches_and_iterates(weft: Weft) -> None:
    names = [f"sdk-py-batch-{s}-{int(time.time() * 1000)}" for s in "abc"]
    assert [(r.name, r.ok) for r in weft.create_repos(names)] == [(n, True) for n in names]
    dup = weft.create_repos(names[:1])
    assert not dup[0].ok and dup[0].error
    seen = {r.name for r in weft.iterate_repos(page_size=2)}
    assert set(names) <= seen
    assert all(r.ok for r in weft.delete_repos(names))


def test_exports_a_bundle_git_can_read(state: dict[str, Any]) -> None:
    repo: Repo = state["repo"]
    job = repo.start_export()
    for _ in range(100):
        if job.state in ("done", "failed"):
            break
        time.sleep(0.1)
        job = repo.get_export(job.job)
    assert job.state == "done"
    assert (
        repo.download_export(job.job)[:16]
        .decode()
        .startswith(("# v2 git bundle", "# v3 git bundle"))
    )


@pytest.mark.skipif(not HAS_GIT, reason="needs the git CLI")
def test_runs_the_readme_quickstart_exactly_as_written(weft: Weft) -> None:
    # A subprocess, importing `weftsh` the way somebody who copied it would.
    assert URL and TOKEN and ORG
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run(
        [sys.executable, str(root / "examples" / "quickstart.py")],
        env={**os.environ, "WEFT_TOKEN": TOKEN, "WEFT_ORG": ORG, "WEFT_URL": URL},
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    name = re.search(r"^created\s+(\S+)$", out, re.M)
    assert name and name.group(1).startswith("repo-"), out
    track(weft, weft.repo(name.group(1)))
    assert re.search(r"^committed\s+[0-9a-f]{7}$", out, re.M), out
    assert re.search(r"^read back\s+'hello from the Weft SDK\\n'$", out, re.M), out
    assert re.search(r"^cloned\s+hello from the Weft SDK$", out, re.M), out


def test_deletes_a_repository(weft: Weft) -> None:
    doomed = weft.create_repo()
    doomed.delete()
    assert weft.find_one(name=doomed.name) is None


async def test_the_async_client_against_the_same_server() -> None:
    assert URL and TOKEN and ORG
    async with AsyncWeft(token=TOKEN, org=ORG, base_url=URL) as weft:
        repo = await weft.create_repo()
        try:
            one = await repo.create_commit(message="a", expected_parent=None).put("f", "1").send()
            with pytest.raises(WeftConflictError) as err:
                await repo.create_commit(message="b", expected_parent=None).put("f", "2").send()
            assert err.value.current_tip == one.commit
            assert await repo.read_file("f") == "1"
            assert [c.sha async for c in repo.iterate_commits()] == [one.commit]
        finally:
            await repo.delete()
