"""What the SDK sends and how it reads the answer, against a recorded transport.

These pin the wire. ``test_e2e.py`` checks that a real server agrees.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from weftsh import (
    AsyncWeft,
    Identity,
    RepoInfo,
    Weft,
    WeftConflictError,
    WeftError,
    verify_webhook,
)

REPO_WIRE: dict[str, Any] = {
    "id": "r1",
    "org_id": "o1",
    "org": "acme",
    "name": "session-1",
    "description": None,
    "homepage": None,
    "kind": "native",
    "public": False,
    "default_branch": "main",
    "clone_url": "https://api.weft.sh/acme/session-1.git",
    "ssh_clone_url": None,
    "stored_bytes": 0,
    "created_at": 1766000000000,
    "origin_url": None,
    "last_sync_at": None,
    "last_synced_commit": None,
    "sync_error": None,
    "fork_state": None,
    "fork_parent": None,
    "fork_count": 0,
}


@dataclass
class Recorder:
    """Answers requests from a queue and remembers what was sent."""

    answers: list[httpx.Response]
    calls: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.calls.append(request)
        if not self.answers:
            raise AssertionError(f"unexpected request {request.method} {request.url}")
        return self.answers.pop(0)

    def body(self, i: int = 0) -> Any:
        return json.loads(self.calls[i].content)


def js(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


def client(
    *answers: httpx.Response, base_url: str = "https://api.weft.sh"
) -> tuple[Weft, Recorder]:
    rec = Recorder(list(answers))
    http = httpx.Client(transport=httpx.MockTransport(rec))
    return Weft(token="weft_a_b", org="acme", base_url=base_url, http_client=http), rec


def aclient(*answers: httpx.Response) -> tuple[AsyncWeft, Recorder]:
    rec = Recorder(list(answers))
    http = httpx.AsyncClient(transport=httpx.MockTransport(rec))
    return AsyncWeft(token="weft_a_b", org="acme", http_client=http), rec


# ------------------------------------------------------------------ client


def test_refuses_to_construct_without_a_token_or_an_org() -> None:
    with pytest.raises(ValueError, match="token"):
        Weft(token="", org="acme")
    with pytest.raises(ValueError, match="org"):
        Weft(token="weft_a_b", org=" ")


def test_creates_a_repo_with_the_bearer_token_and_snake_case_wire() -> None:
    weft, rec = client(js(201, REPO_WIRE))
    repo = weft.create_repo(name="session-1", default_branch="main", public=False)
    req = rec.calls[0]
    assert req.method == "POST"
    assert str(req.url) == "https://api.weft.sh/v1/orgs/acme/repos"
    assert req.headers["authorization"] == "Bearer weft_a_b"
    assert req.headers["user-agent"].startswith("weft-python-sdk/")
    assert rec.body() == {"name": "session-1", "default_branch": "main", "public": False}
    assert repo.name == "session-1"
    assert repo.info is not None and repo.info.clone_url.endswith("/acme/session-1.git")
    assert repo.default_branch == "main"


def test_generates_a_valid_name_when_none_is_given() -> None:
    weft, rec = client(js(201, REPO_WIRE))
    weft.create_repo()
    name = rec.body()["name"]
    assert name.startswith("repo-") and len(name) <= 100
    assert all(c.isalnum() or c in "-_." for c in name)


def test_find_one_is_none_on_404_and_raises_anything_else() -> None:
    weft, _ = client(httpx.Response(404, text="not found"), js(500, {"error": "boom"}))
    assert weft.find_one(name="nope") is None
    with pytest.raises(WeftError) as err:
        weft.find_one(name="x")
    assert err.value.status == 500 and err.value.message == "boom"


def test_repo_makes_no_request() -> None:
    weft, rec = client()
    repo = weft.repo("session-1")
    assert repo.clone_url == "https://api.weft.sh/acme/session-1.git"
    assert rec.calls == []


def test_honours_a_base_url_with_a_trailing_slash() -> None:
    weft, rec = client(
        js(200, {"repos": [], "next_after": None}), base_url="http://localhost:8080/"
    )
    weft.list_repos(limit=5)
    assert str(rec.calls[0].url) == "http://localhost:8080/v1/orgs/acme/repos?limit=5"


def test_iterates_every_page() -> None:
    weft, rec = client(
        js(200, {"repos": [REPO_WIRE], "next_after": "r1"}),
        js(200, {"repos": [{**REPO_WIRE, "id": "r2", "name": "session-2"}], "next_after": None}),
    )
    assert [r.name for r in weft.iterate_repos(page_size=1)] == ["session-1", "session-2"]
    assert rec.calls[1].url.params["after"] == "r1"


# ----------------------------------------------------------------- commits


def test_text_goes_as_put_bytes_as_put_base64_with_wire_names() -> None:
    weft, rec = client(js(201, {"commit": "c2", "tree": "t2", "parent": "c1", "branch": "main"}))
    result = (
        weft.repo("session-1")
        .create_commit(
            message="step",
            expected_parent="c1",
            context={"run": "r-42"},
            author=Identity(name="A", email="a@x"),
        )
        .put("a.txt", "hi\n")
        .put("b.bin", b"\x00\x01\xff")
        .put("c.bin", bytearray(b"\x00"))
        .delete("old.txt")
        .send()
    )
    assert (result.commit, result.parent, result.branch) == ("c2", "c1", "main")
    assert rec.calls[0].url.path == "/v1/orgs/acme/repos/session-1/commits"
    assert rec.body() == {
        "message": "step",
        "expected_parent": "c1",
        "context": {"run": "r-42"},
        "author": {"name": "A", "email": "a@x"},
        "operations": [
            {"op": "put", "path": "a.txt", "content": "hi\n"},
            {"op": "put_base64", "path": "b.bin", "content": "AAH/"},
            {"op": "put_base64", "path": "c.bin", "content": "AA=="},
            {"op": "delete", "path": "old.txt"},
        ],
    }


def test_expected_parent_none_is_an_explicit_null() -> None:
    weft, rec = client(js(201, {"commit": "c1", "tree": "t", "parent": None, "branch": "b"}))
    weft.repo("r").create_commit(message="m", branch="b", expected_parent=None).put("a", "b").send()
    assert "expected_parent" in rec.body() and rec.body()["expected_parent"] is None


def test_expected_parent_left_out_is_omitted() -> None:
    weft, rec = client(js(201, {"commit": "c1", "tree": "t", "parent": None, "branch": "main"}))
    weft.repo("r").create_commit(message="m").put("a", "b").send()
    assert "expected_parent" not in rec.body()
    assert "branch" not in rec.body()


def test_a_409_is_a_conflict_error_with_the_current_tip() -> None:
    weft, _ = client(
        js(
            409,
            {"error": "expected_parent does not match the current branch tip", "current_tip": "c9"},
        )
    )
    with pytest.raises(WeftConflictError) as err:
        weft.repo("r").create_commit(message="m", expected_parent="c1").put("a", "b").send()
    assert isinstance(err.value, WeftError)
    assert err.value.status == 409
    assert err.value.current_tip == "c9"
    assert "expected_parent" in str(err.value)


def test_reads_the_reset_conflict_shape_too() -> None:
    weft, _ = client(js(409, {"error": "precondition failed on refs/heads/main", "current": "c7"}))
    with pytest.raises(WeftConflictError) as err:
        weft.repo("r").reset(to="c1", expected_head="c2")
    assert err.value.current_tip == "c7"


def test_refuses_an_empty_commit_before_sending() -> None:
    weft, rec = client()
    with pytest.raises(ValueError, match="at least one"):
        weft.repo("r").create_commit(message="m").send()
    assert rec.calls == []


def test_refuses_content_it_cannot_encode() -> None:
    weft, _ = client()
    with pytest.raises(TypeError):
        weft.repo("r").create_commit(message="m").put("a", 42)  # type: ignore[arg-type]


# ------------------------------------------------------------------- reads


def test_reads_a_file_with_its_headers_and_a_304_as_not_modified() -> None:
    weft, rec = client(
        httpx.Response(
            200,
            content=b"hello\n",
            headers={
                "etag": '"abc"',
                "x-weft-commit": "c1",
                "x-weft-mode": "100644",
                "x-weft-binary": "false",
                "content-type": "text/plain; charset=utf-8",
            },
        ),
        httpx.Response(304, headers={"etag": '"abc"'}),
    )
    repo = weft.repo("r")
    file = repo.get_file("src/a b.ts", ref="main")
    assert file is not None
    assert (file.text, file.etag, file.commit, file.binary) == ("hello\n", '"abc"', "c1", False)
    assert rec.calls[0].url.raw_path.decode() == "/v1/orgs/acme/repos/r/files/src/a%20b.ts?at=main"

    again = repo.get_file("src/a b.ts", if_none_match=file.etag)
    assert again is not None and again.not_modified and again.content == b""
    assert rec.calls[1].headers["if-none-match"] == '"abc"'


def test_a_missing_path_or_revision_reads_as_none() -> None:
    weft, _ = client(
        js(404, {"error": '"nope" not in this layout at "HEAD"'}),
        js(404, {"error": 'unknown rev "gone"'}),
    )
    assert weft.repo("r").read_file("nope") is None
    assert weft.repo("r").read_file("a", ref="gone") is None


def test_a_missing_repository_raises_rather_than_reading_as_none() -> None:
    # The server answers a missing (or invisible) repository with a bare
    # `not found`, not a JSON error: a typo in the repo name must not read
    # as "this file does not exist".
    weft, _ = client(httpx.Response(404, text="not found"))
    with pytest.raises(WeftError) as err:
        weft.repo("typo").read_file("a")
    assert err.value.status == 404 and err.value.body == "not found"


def test_maps_log_entries_and_the_cursor() -> None:
    weft, rec = client(
        js(
            200,
            {
                "entries": [
                    {
                        "commit": "c2",
                        "tree": "t",
                        "parents": ["c1"],
                        "author": "A <a@x> 1 +0000",
                        "committer": "A <a@x> 1 +0000",
                        "message": "m\n",
                        "change": "modified",
                    }
                ],
                "next_after": "c2",
            },
        )
    )
    page = weft.repo("r").list_commits(path="a.txt", limit=1)
    assert (page.commits[0].sha, page.commits[0].parents, page.commits[0].change) == (
        "c2",
        ["c1"],
        "modified",
    )
    assert page.next_cursor == "c2"
    assert dict(rec.calls[0].url.params) == {"path": "a.txt", "limit": "1"}


def test_booleans_go_as_1_and_false_is_left_out() -> None:
    weft, rec = client(
        js(200, {"commit": "c", "paths": ["a", "src/"], "truncated": False}),
        js(200, {"commit": "c", "entries": []}),
    )
    assert weft.repo("r").list_files(path="src").paths == ["a", "src/"]
    assert rec.calls[0].url.path == "/v1/orgs/acme/repos/r/tree/src"
    assert dict(rec.calls[0].url.params) == {"recursive": "1"}
    weft.repo("r").get_tree(sizes=True, history=False)
    assert dict(rec.calls[1].url.params) == {"sizes": "1"}


def test_maps_a_diff_and_sends_from() -> None:
    weft, rec = client(
        js(
            200,
            {
                "from": "a",
                "to": "b",
                "changes": [
                    {
                        "status": "added",
                        "path": "x",
                        "old_oid": None,
                        "new_oid": "n",
                        "old_mode": None,
                        "new_mode": "100644",
                    }
                ],
            },
        )
    )
    diff = weft.repo("r").get_diff(from_="a", to="b")
    assert diff.from_ == "a" and diff.changes[0].new_oid == "n"
    assert dict(rec.calls[0].url.params) == {"from": "a", "to": "b"}


def test_a_branch_with_a_slash_is_one_segment() -> None:
    weft, rec = client(httpx.Response(204))
    weft.repo("r").delete_branch("feature/x")
    assert rec.calls[0].url.raw_path.decode() == "/v1/orgs/acme/repos/r/branches/feature%2Fx"


def test_update_sends_only_what_was_given_and_none_clears() -> None:
    weft, rec = client(js(200, REPO_WIRE), js(200, REPO_WIRE))
    weft.repo("r").update(description=None)
    assert rec.body(0) == {"description": None}
    weft.repo("r").update(homepage="https://example.com", public=True)
    assert rec.body(1) == {"homepage": "https://example.com", "public": True}


# ---------------------------------------------------------------- remotes


def test_get_remote_url_mints_a_short_lived_repo_bound_token() -> None:
    weft, rec = client(js(201, {"id": "tk", "token": "weft_tk_secret", "expires_at": 1}))
    info = RepoInfo._from_wire(REPO_WIRE)
    url = weft.repo("session-1", info).get_remote_url(access="read", ttl=600)
    assert url == "https://x:weft_tk_secret@api.weft.sh/acme/session-1.git"
    assert rec.calls[0].url.path == "/v1/orgs/acme/tokens"
    assert rec.body() == {
        "scopes": ["repo:read"],
        "repo": "session-1",
        "label": "remote:session-1",
        "expires_in_secs": 600,
    }


def test_a_forked_repo_mints_in_its_own_org() -> None:
    weft, rec = client(
        js(202, {**REPO_WIRE, "org": "elsewhere", "name": "fork"}),
        js(201, {"id": "tk", "token": "t", "expires_at": 1}),
    )
    fork = weft.repo("r").fork(org="elsewhere")
    fork.get_remote_url()
    assert rec.calls[1].url.path == "/v1/orgs/elsewhere/tokens"


@pytest.mark.parametrize("status", [404, 403, 400])
def test_get_remote_url_explains_a_refused_mint(status: int) -> None:
    weft, _ = client(js(status, {"error": "not found"}))
    with pytest.raises(WeftError) as err:
        weft.repo("session-1").get_remote_url()
    assert err.value.status == status
    assert "could not mint a credential for acme/session-1" in err.value.message
    assert "org:read and repo:write, or org:admin" in err.value.message
    assert isinstance(err.value.__cause__, WeftError)


def test_get_remote_url_names_repo_read_for_a_read_only_url() -> None:
    weft, _ = client(js(404, {"error": "not found"}))
    with pytest.raises(WeftError) as err:
        weft.repo("r").get_remote_url(access="read")
    assert "org:read and repo:read" in err.value.message


def test_get_remote_url_passes_anything_else_through() -> None:
    weft, _ = client(js(500, {"error": "boom"}))
    with pytest.raises(WeftError) as err:
        weft.repo("r").get_remote_url()
    assert err.value.message == "boom"


# ------------------------------------------------------------------ errors


def test_a_network_failure_is_status_0_with_the_cause() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("ECONNREFUSED", request=request)

    weft = Weft(
        token="t", org="acme", http_client=httpx.Client(transport=httpx.MockTransport(boom))
    )
    with pytest.raises(WeftError) as err:
        weft.list_repos()
    assert err.value.status == 0 and "ECONNREFUSED" in str(err.value)
    assert isinstance(err.value.__cause__, httpx.ConnectError)


def test_a_non_json_error_body_is_kept_as_text() -> None:
    weft, _ = client(httpx.Response(502, text="upstream went away"))
    with pytest.raises(WeftError) as err:
        weft.list_repos()
    assert err.value.status == 502 and err.value.body == "upstream went away"


# ------------------------------------------------------------------- async


async def test_the_async_client_speaks_the_same_wire() -> None:
    weft, rec = aclient(
        js(201, REPO_WIRE),
        js(201, {"commit": "c1", "tree": "t", "parent": None, "branch": "main"}),
        js(409, {"error": "stale", "current_tip": "c9"}),
        js(404, {"error": "unknown rev"}),
        js(200, {"repos": [REPO_WIRE], "next_after": None}),
    )
    async with weft:
        repo = await weft.create_repo(name="session-1")
        result = (
            await repo.create_commit(message="m", expected_parent=None).put("a", b"\x00").send()
        )
        assert result.commit == "c1"
        assert rec.body(1)["expected_parent"] is None
        assert rec.body(1)["operations"] == [{"op": "put_base64", "path": "a", "content": "AA=="}]
        with pytest.raises(WeftConflictError) as err:
            await repo.create_commit(message="m", expected_parent="c1").put("a", "b").send()
        assert err.value.current_tip == "c9"
        assert await repo.read_file("a", ref="gone") is None
        assert [r.name async for r in weft.iterate_repos()] == ["session-1"]


# ---------------------------------------------------------------- webhooks

SECRET = "whsec"
BODY = json.dumps(
    {"event": "push", "repo_id": "r1", "payload": {"via": "api", "commit": "c1", "branch": "main"}}
)


def sign(body: str, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def test_verify_webhook_accepts_a_genuine_delivery() -> None:
    event = verify_webhook(payload=BODY, signature=sign(BODY), secret=SECRET)
    assert event is not None and event["event"] == "push" and event["repo_id"] == "r1"
    assert verify_webhook(payload=BODY.encode(), signature=sign(BODY), secret=SECRET) is not None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda: {"payload": BODY + " ", "signature": sign(BODY), "secret": SECRET},
        lambda: {"payload": BODY, "signature": sign(BODY, "other"), "secret": SECRET},
        lambda: {"payload": BODY, "signature": None, "secret": SECRET},
        lambda: {"payload": BODY, "signature": "sha1=abc", "secret": SECRET},
        lambda: {"payload": BODY, "signature": sign(BODY), "secret": ""},
        lambda: {"payload": "not json", "signature": sign("not json"), "secret": SECRET},
    ],
    ids=["tampered", "wrong-secret", "missing", "malformed", "no-secret", "not-json"],
)
def test_verify_webhook_rejects(mutate: Callable[[], dict[str, Any]]) -> None:
    assert verify_webhook(**mutate()) is None
