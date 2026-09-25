"""What the sync and async clients share: request building, error mapping, encoding."""

from __future__ import annotations

import base64
import contextlib
import json
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from ._errors import WeftConflictError, WeftError
from ._types import FileContent, FileResult, Wire
from ._version import VERSION

DEFAULT_BASE_URL = "https://api.weft.sh"
USER_AGENT = f"weft-python-sdk/{VERSION}"


def check_options(token: str, org: str) -> None:
    if not isinstance(token, str) or not token.strip():
        raise ValueError("Weft: `token` must be a non-empty string (a weft_… API token)")
    if not isinstance(org, str) or not org.strip():
        raise ValueError("Weft: `org` must be a non-empty string (your organization or namespace)")


def headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def seg(value: str) -> str:
    """One path segment, with every reserved character escaped (a `/` included)."""
    return quote(value, safe="")


def path_of(path: str) -> str:
    """A repository path: each segment escaped, the slashes kept."""
    return "/".join(quote(s, safe="") for s in path.split("/") if s)


def query(**params: Any) -> dict[str, str]:
    """Drops ``None`` and ``False``; sends ``True`` as ``1``, which is what the API reads."""
    out: dict[str, str] = {}
    for k, v in params.items():
        if v is None or v is False:
            continue
        out[k] = "1" if v is True else str(v)
    return out


def unique_name() -> str:
    return f"repo-{uuid.uuid4()}"


def put_operation(path: str, content: FileContent) -> dict[str, str]:
    """A string goes as text; bytes go as base64, so binary content survives JSON."""
    if isinstance(content, str):
        return {"op": "put", "path": path, "content": content}
    if isinstance(content, (bytes, bytearray, memoryview)):
        encoded = base64.b64encode(bytes(content)).decode("ascii")
        return {"op": "put_base64", "path": path, "content": encoded}
    raise TypeError(f"unsupported content for {path}: pass str, bytes, bytearray or memoryview")


def raise_for(response: httpx.Response, allow: tuple[int, ...] = ()) -> None:
    """Raises a ``WeftError`` (or ``WeftConflictError`` for a 409) for a non-2xx answer."""
    if response.is_success or response.status_code in allow:
        return
    text = response.text
    body: Any = text or None
    with contextlib.suppress(ValueError):
        body = json.loads(text) if text else None
    message = None
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        message = body["error"]
    method = response.request.method
    url = str(response.request.url)
    if message is None:
        message = f"{method} {response.request.url.path} answered {response.status_code}"
    cls = WeftConflictError if response.status_code == 409 else WeftError
    raise cls(message, status=response.status_code, method=method, url=url, body=body)


def transport_error(exc: httpx.HTTPError, method: str, url: str) -> WeftError:
    err = WeftError(f"{method} {url} failed: {exc}", status=0, method=method, url=url)
    err.__cause__ = exc
    return err


def json_of(response: httpx.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def is_missing_in_repo(exc: WeftError) -> bool:
    """A 404 about something *inside* a repository — a path or a revision.

    The server tells the two apart by shape: inside, a JSON ``{"error": …}``
    naming what was missing; the repository itself, a bare ``not found`` that
    says nothing about whether it exists. A typo in a repository name must
    not read as "this file does not exist".
    """
    return (
        exc.status == 404 and isinstance(exc.body, dict) and isinstance(exc.body.get("error"), str)
    )


def file_result(response: httpx.Response, if_none_match: str | None) -> FileResult:
    h = response.headers
    not_modified = response.status_code == 304
    return FileResult(
        not_modified=not_modified,
        content=b"" if not_modified else response.content,
        etag=h.get("etag") or if_none_match or "",
        commit=h.get("x-weft-commit"),
        mode=h.get("x-weft-mode"),
        binary=h.get("x-weft-binary") == "true",
        content_type=h.get("content-type"),
    )


def create_body(
    name: str, public: bool | None, default_branch: str | None, description: str | None
) -> Wire:
    body: Wire = {"name": name}
    if public is not None:
        body["public"] = public
    if default_branch is not None:
        body["default_branch"] = default_branch
    if description is not None:
        body["description"] = description
    return body


def remote_url(clone_url: str, token: str) -> str:
    """Puts a credential into an HTTPS clone URL as ``x:<token>@``."""
    scheme, sep, rest = clone_url.partition("://")
    if not sep:
        raise ValueError(f"not a URL: {clone_url!r}")
    host_and_path = rest.split("@", 1)[-1]
    return f"{scheme}://x:{quote(token, safe='')}@{host_and_path}"
