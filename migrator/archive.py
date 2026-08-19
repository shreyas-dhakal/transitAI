"""Bounded, non-executing inspection of uploaded project archives."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath

from migrator.adapters import (
    AdapterFindings,
    AdapterRegistry,
    SourceAdapter,
    UniversalWebAdapter,
    merge_findings,
)
from migrator.cir import CanonicalIR, compile_cir
from migrator.models import ProjectInventory, WesleyAssessment
from migrator.models import MigrationBlueprint
from migrator.migration import build_migration_blueprint
from migrator.wesley import assess_project


MAX_ARCHIVE_BYTES = 15 * 1024 * 1024
MAX_FILE_COUNT = 800
MAX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 300 * 1024
MAX_CONTEXT_CHARS = 120_000
MAX_ASSET_BYTES = 5 * 1024 * 1024

SOURCE_EXTENSIONS = {
    ".aspx", ".asp", ".cfm", ".cs", ".css", ".erb", ".go", ".html", ".htm",
    ".java", ".js", ".jsx", ".json", ".jsp", ".md", ".php", ".phtml", ".py",
    ".rb", ".rs", ".sql", ".svelte", ".ts", ".tsx", ".txt", ".vue", ".xml",
}
ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".otf"}
SENSITIVE_NAMES = {
    ".env", ".htpasswd", "config.php", "credentials.json", "database.php",
    "id_ed25519", "id_rsa", "secrets.json", "settings.php", "wp-config.php",
}
@dataclass(frozen=True)
class ProjectAsset:
    source_path: str
    output_path: str
    content: bytes


@dataclass(frozen=True)
class ProjectSnapshot:
    inventory: ProjectInventory
    source_context: str
    assets: list[ProjectAsset]
    findings: list[AdapterFindings] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    cir: CanonicalIR | None = None
    wesley: WesleyAssessment | None = None
    migration: MigrationBlueprint | None = None


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


def inspect_project(
    data: bytes,
    filename: str = "project.zip",
    adapter: SourceAdapter | None = None,
    registry: AdapterRegistry | None = None,
) -> ProjectSnapshot:
    """Inspect an archive in memory without extracting or executing its contents."""
    if adapter is not None and registry is not None:
        raise ValueError("Pass either adapter or registry, not both.")
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

    if adapter is not None:
        findings = [adapter.inspect(sources)]
        if not findings[0].adapter_name:
            findings[0] = AdapterFindings(
                findings[0].detected_technologies,
                findings[0].route_candidates,
                findings[0].database_tables,
                findings[0].behavior_signals,
                findings[0].graph,
                adapter.name,
            )
    else:
        findings = (registry or AdapterRegistry.with_defaults()).inspect(sources)
    merged = merge_findings(findings)
    asset_urls = ["/" + asset.output_path.removeprefix("public/") for asset in assets]
    project_name = re.sub(r"\.zip$", "", PurePosixPath(filename).name, flags=re.IGNORECASE) or "migrated-project"
    inventory = ProjectInventory(
        project_name=project_name,
        adapter=merged.adapter_name,
        file_count=len(members),
        source_file_count=len(sources),
        asset_count=len(assets),
        source_files=sorted(sources),
        asset_urls=asset_urls,
        detected_technologies=merged.detected_technologies,
        route_candidates=merged.route_candidates or ["/"],
        database_tables=merged.database_tables,
        behavior_signals=merged.behavior_signals,
        skipped_sensitive_files=sorted(skipped_sensitive),
        truncated=truncated,
        adapter_sources=[finding.adapter_name for finding in findings],
    )
    snapshot = ProjectSnapshot(
        inventory=inventory,
        source_context="".join(context_parts),
        assets=assets,
        findings=findings,
        sources=sources,
        cir=compile_cir(inventory, sources, assets, findings),
    )
    wesley = assess_project(inventory, sources)
    return ProjectSnapshot(
        inventory=snapshot.inventory,
        source_context=snapshot.source_context,
        assets=snapshot.assets,
        findings=snapshot.findings,
        sources=snapshot.sources,
        cir=snapshot.cir,
        wesley=wesley,
        migration=build_migration_blueprint(snapshot.cir, wesley) if snapshot.cir else None,
    )


# Kept as a small compatibility alias for existing callers while the generic
# inspection API becomes the primary integration point.
LampProject = ProjectSnapshot


def inspect_lamp_zip(data: bytes, filename: str = "lamp-project.zip") -> ProjectSnapshot:
    """Compatibility wrapper retaining the original single-adapter behavior."""
    return inspect_project(data, filename, adapter=UniversalWebAdapter())
