"""Bounded, non-executing inspection of uploaded LAMP project archives."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

from migrator.models import ProjectInventory


MAX_ARCHIVE_BYTES = 15 * 1024 * 1024
MAX_FILE_COUNT = 800
MAX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 300 * 1024
MAX_CONTEXT_CHARS = 120_000
MAX_ASSET_BYTES = 5 * 1024 * 1024

SOURCE_EXTENSIONS = {".php", ".phtml", ".html", ".htm", ".css", ".js", ".sql", ".xml", ".json", ".md", ".txt"}
ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".otf"}
SENSITIVE_NAMES = {
    ".env", ".htpasswd", "config.php", "credentials.json", "database.php",
    "id_ed25519", "id_rsa", "secrets.json", "settings.php", "wp-config.php",
}
NON_ROUTE_DIRECTORIES = {"config", "includes", "partials", "vendor", "lib", "src", "tests"}
NON_ROUTE_STEMS = {"bootstrap", "config", "database", "db", "footer", "functions", "header", "helpers"}


@dataclass(frozen=True)
class ProjectAsset:
    source_path: str
    output_path: str
    content: bytes


@dataclass(frozen=True)
class LampProject:
    inventory: ProjectInventory
    source_context: str
    assets: list[ProjectAsset]


def _safe_path(raw_path: str) -> PurePosixPath:
    normalized = raw_path.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"Unsafe archive member path: {raw_path}")
    if not normalized or any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ValueError(f"Unsafe archive member path: {raw_path}")
    return PurePosixPath(normalized)


def _strip_common_root(paths: list[PurePosixPath]) -> dict[PurePosixPath, PurePosixPath]:
    roots = {path.parts[0] for path in paths if path.parts}
    strip_root = len(roots) == 1 and all(len(path.parts) > 1 for path in paths)
    return {path: PurePosixPath(*path.parts[1:]) if strip_root else path for path in paths}


def _is_sensitive(path: PurePosixPath) -> bool:
    lowered = [part.lower() for part in path.parts]
    name = path.name.lower()
    return (
        name in SENSITIVE_NAMES
        or name.endswith((".pem", ".key", ".p12", ".pfx"))
        or any(part in {"secrets", "credentials", ".ssh"} for part in lowered)
    )


def _redact_secrets(content: str) -> str:
    assignment = re.compile(
        r"(?im)\b(password|passwd|secret|api[_-]?key|access[_-]?token|db[_-]?pass)\b"
        r"(\s*[:=]\s*)(['\"])[^'\"\r\n]{3,}\3"
    )
    content = assignment.sub(lambda match: f'{match.group(1)}{match.group(2)}"[REDACTED]"', content)
    return re.sub(r"(?i)mysql://[^\s'\"]+", "mysql://[REDACTED]", content)


def _php_route(path: PurePosixPath) -> str:
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1].lower() == "index":
        parts.pop()
    return "/" + "/".join(parts)


def _is_php_route(path: PurePosixPath) -> bool:
    return (
        path.suffix.lower() in {".php", ".phtml"}
        and path.stem.lower() not in NON_ROUTE_STEMS
        and not any(part.lower() in NON_ROUTE_DIRECTORIES for part in path.parts[:-1])
    )


def _technology_signals(paths: list[str], combined_text: str) -> list[str]:
    lowered_paths = [path.lower() for path in paths]
    checks = [
        ("PHP", any(path.endswith((".php", ".phtml")) for path in lowered_paths)),
        ("MySQL", bool(re.search(r"(?i)\b(mysql|mysqli|pdo)\b", combined_text))),
        ("Apache", any(path.endswith(".htaccess") for path in lowered_paths)),
        ("WordPress", any("wp-content" in path or "wp-config" in path for path in lowered_paths)),
        ("jQuery", bool(re.search(r"(?i)\bjquery\b|\$\s*\(", combined_text))),
        ("Bootstrap", bool(re.search(r"(?i)\bbootstrap\b", combined_text))),
    ]
    signals = [label for label, found in checks if found]
    return signals or ["HTML/CSS"]


def _behavior_signals(combined_text: str) -> list[str]:
    checks = [
        ("HTML form submission", r"(?i)<form\b"),
        ("Session-backed behavior", r"(?i)\bsession_start\s*\(|\$_SESSION"),
        ("Database reads or writes", r"(?i)\b(SELECT|INSERT|UPDATE|DELETE)\b|->query\s*\("),
        ("Email delivery", r"(?i)\bmail\s*\("),
        ("File uploads", r"(?i)multipart/form-data|\$_FILES"),
        ("Server-side includes", r"(?i)\b(include|require)(_once)?\s*[\s(]"),
        ("AJAX requests", r"(?i)\b(fetch|XMLHttpRequest|\$\.ajax)\b"),
    ]
    return [label for label, pattern in checks if re.search(pattern, combined_text)]


def inspect_lamp_zip(data: bytes, filename: str = "lamp-project.zip") -> LampProject:
    """Inspect an archive in memory without extracting or executing its contents."""
    if not data:
        raise ValueError("The uploaded archive is empty.")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive exceeds the 15 MB upload limit.")
    buffer = BytesIO(data)
    if not zipfile.is_zipfile(buffer):
        raise ValueError("Upload a valid ZIP archive.")

    with zipfile.ZipFile(buffer) as archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if len(members) > MAX_FILE_COUNT:
            raise ValueError(f"Archive contains more than {MAX_FILE_COUNT} files.")
        if any(member.flag_bits & 0x1 for member in members):
            raise ValueError("Encrypted ZIP members are not supported.")
        if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Archive exceeds the 40 MB uncompressed limit.")

        original_paths = [_safe_path(member.filename) for member in members]
        path_map = _strip_common_root(original_paths)
        normalized_paths = [path_map[path].as_posix() for path in original_paths]
        if len(normalized_paths) != len(set(normalized_paths)):
            raise ValueError("Archive contains duplicate normalized paths.")

        sources: dict[str, str] = {}
        assets: list[ProjectAsset] = []
        skipped_sensitive: list[str] = []
        truncated = False
        for member, original_path in zip(members, original_paths):
            path = path_map[original_path]
            if _is_sensitive(path):
                skipped_sensitive.append(path.as_posix())
                continue
            suffix = path.suffix.lower()
            if suffix in SOURCE_EXTENSIONS:
                if member.file_size > MAX_SOURCE_FILE_BYTES:
                    truncated = True
                    continue
                raw = archive.read(member)
                if b"\x00" in raw:
                    continue
                sources[path.as_posix()] = _redact_secrets(raw.decode("utf-8", errors="replace"))
            elif suffix in ASSET_EXTENSIONS and member.file_size <= MAX_ASSET_BYTES:
                safe_asset = "/".join(re.sub(r"[^A-Za-z0-9._-]", "-", part) for part in path.parts)
                assets.append(ProjectAsset(path.as_posix(), f"public/legacy/{safe_asset}", archive.read(member)))

    priority = {".php": 0, ".phtml": 0, ".html": 1, ".htm": 1, ".css": 2, ".js": 3, ".sql": 4}
    ordered = sorted(sources.items(), key=lambda item: (priority.get(PurePosixPath(item[0]).suffix.lower(), 5), item[0]))
    context_parts: list[str] = []
    context_size = 0
    for path, content in ordered:
        section = f"\n--- FILE: {path} ---\n{content}\n--- END FILE ---\n"
        if context_size + len(section) > MAX_CONTEXT_CHARS:
            truncated = True
            remaining = MAX_CONTEXT_CHARS - context_size
            if remaining > 500:
                context_parts.append(section[:remaining] + "\n[FILE TRUNCATED]\n")
            break
        context_parts.append(section)
        context_size += len(section)

    combined_text = "\n".join(sources.values())
    routes = sorted({_php_route(PurePosixPath(path)) for path in sources if _is_php_route(PurePosixPath(path))})
    tables = sorted(set(re.findall(r"(?i)CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?([A-Za-z0-9_]+)", combined_text)))
    asset_urls = ["/" + asset.output_path.removeprefix("public/") for asset in assets]
    project_name = re.sub(r"\.zip$", "", PurePosixPath(filename).name, flags=re.IGNORECASE) or "lamp-project"
    inventory = ProjectInventory(
        project_name=project_name,
        file_count=len(members),
        source_file_count=len(sources),
        asset_count=len(assets),
        source_files=sorted(sources),
        asset_urls=asset_urls,
        detected_technologies=_technology_signals(list(sources), combined_text),
        route_candidates=routes or ["/"],
        database_tables=tables,
        behavior_signals=_behavior_signals(combined_text),
        skipped_sensitive_files=sorted(skipped_sensitive),
        truncated=truncated,
    )
    return LampProject(inventory=inventory, source_context="".join(context_parts), assets=assets)
