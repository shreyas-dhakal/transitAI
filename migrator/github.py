"""GitHub repository intake with commit pinning and migration branch export.

The connector downloads GitHub's source archive for an exact commit SHA and then
hands the bytes to the existing bounded ZIP inspector. Export uses GitHub's Git
Data API and never clones or runs repository code.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen

from migrator.archive import MAX_ARCHIVE_BYTES, ProjectSnapshot, inspect_project


GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class GitHubSource:
    owner: str
    repository: str
    ref: str
    sha: str
    default_branch: str

    @property
    def label(self) -> str:
        return f"{self.owner}/{self.repository}@{self.sha[:12]}"


@dataclass(frozen=True)
class GitHubPushResult:
    branch: str
    commit_sha: str
    url: str


def _valid_segment(value: str, label: str) -> str:
    value = value.strip()
    if not value or len(value) > 200 or value in {".", ".."} or any(char in value for char in "\x00\r\n"):
        raise ValueError(f"Invalid GitHub {label}.")
    return value


def _valid_branch_name(value: str) -> str:
    value = value.strip()
    if (
        not value
        or len(value) > 200
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or ".." in value
        or "@{" in value
        or any(char in value for char in "\x00\r\n~^:?*[\\")
        or value.endswith(".")
    ):
        raise ValueError("Invalid GitHub branch name.")
    return value


def parse_repository_url(value: str) -> tuple[str, str, str | None]:
    """Parse a GitHub repository URL into owner, repository, and optional ref."""
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"github.com", "www.github.com"}:
        raise ValueError("Enter a GitHub repository URL such as https://github.com/acme/legacy-site.")
    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError("GitHub URL must include both an owner and repository.")
    owner = _valid_segment(parts[0], "owner")
    repository = _valid_segment(parts[1].removesuffix(".git"), "repository")
    ref: str | None = None
    if len(parts) > 2:
        if parts[2] not in {"tree", "blob"} or len(parts) < 4:
            raise ValueError("Use a repository URL or a GitHub branch URL containing /tree/<branch>.")
        ref = _valid_segment("/".join(parts[3:]), "ref")
    return owner, repository, ref


def _github_app_token() -> str:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        return token

    app_id = os.getenv("GITHUB_APP_ID", "").strip()
    installation_id = os.getenv("GITHUB_INSTALLATION_ID", "").strip()
    private_key = os.getenv("GITHUB_PRIVATE_KEY", "").replace("\\n", "\n").strip()
    if not (app_id and installation_id and private_key):
        raise RuntimeError(
            "Configure GITHUB_TOKEN for local use, or GITHUB_APP_ID, "
            "GITHUB_INSTALLATION_ID, and GITHUB_PRIVATE_KEY for a GitHub App."
        )
    try:
        import jwt
    except ImportError as error:
        raise RuntimeError("Install the project dependencies for GitHub App support.") from error

    now = int(time.time())
    app_jwt = jwt.encode(
        {"iat": now - 30, "exp": now + 540, "iss": app_id},
        private_key,
        algorithm="RS256",
    )
    request = Request(
        f"{GITHUB_API}/app/installations/{quote(installation_id, safe='')}/access_tokens",
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {app_jwt}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": "Transit-Migration/0.1",
        },
    )
    payload = _read_json(request)
    generated = str(payload.get("token", ""))
    if not generated:
        raise RuntimeError("GitHub App did not return an installation token.")
    return generated


def _read_bytes(request: Request, maximum: int) -> bytes:
    try:
        with urlopen(request, timeout=30) as response:
            content_length = int(response.headers.get("Content-Length", "0") or "0")
            if content_length > maximum:
                raise ValueError(f"GitHub response exceeds the {maximum // (1024 * 1024)} MB limit.")
            chunks: list[bytes] = []
            total = 0
            while chunk := response.read(min(64 * 1024, maximum - total + 1)):
                total += len(chunk)
                if total > maximum:
                    raise ValueError("GitHub response exceeds the configured size limit.")
                chunks.append(chunk)
            return b"".join(chunks)
    except HTTPError as error:
        detail = error.read(500).decode("utf-8", errors="replace")
        if error.code == 403 and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            raise RuntimeError(
                "GitHub denied this write request. Grant the token or GitHub App "
                "Contents: Read and write access to this repository, then retry. "
                "GITHUB_TOKEN takes precedence over GitHub App credentials. "
                f"GitHub response: {detail}"
            ) from error
        raise RuntimeError(f"GitHub request failed ({error.code}): {detail}") from error
    except URLError as error:
        raise RuntimeError(f"GitHub request could not be completed: {error.reason}") from error


def _read_json(request: Request) -> dict[str, Any]:
    raw = _read_bytes(request, MAX_RESPONSE_BYTES)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("GitHub returned invalid JSON.") from error
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned an unexpected response.")
    return payload


class GitHubClient:
    """GitHub client for repository intake and migration branch creation."""

    def __init__(self, token: str | None = None) -> None:
        self.token = token or _github_app_token()

    def _request(self, path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Request:
        body = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": "Transit-Migration/0.1",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return Request(
            f"{GITHUB_API}{path}",
            data=body,
            method=method,
            headers=headers,
        )

    def fetch_project(self, owner: str, repository: str, ref: str | None = None) -> tuple[ProjectSnapshot, GitHubSource]:
        owner = _valid_segment(owner, "owner")
        repository = _valid_segment(repository, "repository")
        metadata = _read_json(self._request(f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}"))
        default_branch = _valid_segment(str(metadata.get("default_branch", "")), "default branch")
        selected_ref = _valid_segment(ref or default_branch, "ref")
        commit = _read_json(
            self._request(
                f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}/commits/{quote(selected_ref, safe='')}"
            )
        )
        sha = str(commit.get("sha", ""))
        if not sha or len(sha) < 12 or not all(char in "0123456789abcdefABCDEF" for char in sha):
            raise RuntimeError("GitHub did not return a valid commit SHA.")
        archive_request = self._request(
            f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}/zipball/{quote(sha, safe='')}"
        )
        archive = _read_bytes(archive_request, MAX_ARCHIVE_BYTES)
        source = GitHubSource(owner, repository, selected_ref, sha, default_branch)
        return inspect_project(archive, f"{repository}-{sha[:12]}.zip"), source

    def push_project(
        self,
        source: GitHubSource,
        files: dict[str, bytes],
        branch: str,
        commit_message: str = "Add Transit migration",
    ) -> GitHubPushResult:
        """Create one commit containing files on a new branch from the pinned source."""
        branch = _valid_branch_name(branch)
        if not files:
            raise ValueError("Cannot push an empty generated project.")
        if not commit_message.strip() or len(commit_message) > 200:
            raise ValueError("Commit message must be between 1 and 200 characters.")

        repository_path = f"/repos/{quote(source.owner, safe='')}/{quote(source.repository, safe='')}"
        blob_entries: list[dict[str, str]] = []
        for path, content in sorted(files.items()):
            blob = _read_json(
                self._request(
                    f"{repository_path}/git/blobs",
                    method="POST",
                    payload={"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
                )
            )
            blob_sha = str(blob.get("sha", ""))
            if not blob_sha:
                raise RuntimeError(f"GitHub did not return a blob SHA for {path}.")
            blob_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})

        tree = _read_json(
            self._request(
                f"{repository_path}/git/trees",
                method="POST",
                payload={"base_tree": source.sha, "tree": blob_entries},
            )
        )
        tree_sha = str(tree.get("sha", ""))
        if not tree_sha:
            raise RuntimeError("GitHub did not return a tree SHA.")

        commit = _read_json(
            self._request(
                f"{repository_path}/git/commits",
                method="POST",
                payload={"message": commit_message.strip(), "tree": tree_sha, "parents": [source.sha]},
            )
        )
        commit_sha = str(commit.get("sha", ""))
        if not commit_sha:
            raise RuntimeError("GitHub did not return a commit SHA.")

        _read_json(
            self._request(
                f"{repository_path}/git/refs",
                method="POST",
                payload={"ref": f"refs/heads/{branch}", "sha": commit_sha},
            )
        )
        return GitHubPushResult(
            branch=branch,
            commit_sha=commit_sha,
            url=f"https://github.com/{source.owner}/{source.repository}/tree/{branch}",
        )
