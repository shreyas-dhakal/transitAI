"""Deterministic Wesley Spectrum classification from static project evidence."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from migrator.models import ProjectInventory, WesleyAssessment, WesleyComponent, WesleySignal


SPECTRUM = {"retain", "replace", "evolve", "reengineer", "migrate", "coexist"}
MANIFEST_NAMES = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
    "pnpm-lock.yaml", "composer.json", "composer.lock", "requirements.txt",
    "pyproject.toml", "pipfile", "pipfile.lock", "gemfile", "gemfile.lock",
    "go.mod", "go.sum", "pom.xml", "build.gradle", "cargo.toml", "cargo.lock",
}
TEST_PARTS = {"test", "tests", "spec", "specs", "__tests__"}


def _signal(
    name: str,
    status: str,
    severity: str = "info",
    value: str | None = None,
    evidence: list[str] | None = None,
) -> WesleySignal:
    return WesleySignal(
        name=name,
        status=status,
        severity=severity,
        value=value,
        evidence=evidence or [],
    )


def _version(value: str) -> tuple[int, ...] | None:
    match = re.search(r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?", value)
    return tuple(int(part or 0) for part in match.groups()) if match else None


def _runtime_signals(sources: dict[str, str]) -> list[WesleySignal]:
    signals: list[WesleySignal] = []
    combined = "\n".join(sources.values())
    runtime_rules = [
        ("PHP", r"(?:php[\"']?(?:\s*version|[-_]version)?\s*[=:>]\s*[\"']?|FROM\s+php:)([0-9]+(?:\.[0-9]+){0,2})", (8, 2)),
        ("Python", r"(?:python[\"']?(?:[-_ ]version)?\s*[=:>]\s*[\"']?|requires-python\s*=\s*[\"']\s*>=\s*)([0-9]+(?:\.[0-9]+){0,2})", (3, 10)),
        ("Node.js", r"(?:node[\"']?(?:[-_ ]version)?\s*[=:>]\s*[\"']?|FROM\s+node:)([0-9]+(?:\.[0-9]+){0,2})", (20,)),
    ]
    for runtime, pattern, minimum in runtime_rules:
        match = re.search(pattern, combined, re.IGNORECASE)
        if not match:
            signals.append(_signal(f"{runtime} runtime version", "unknown"))
            continue
        version = _version(match.group(1))
        if version is None:
            signals.append(_signal(f"{runtime} runtime version", "unknown"))
            continue
        status = "stale" if version < minimum else "supported"
        signals.append(_signal(
            f"{runtime} runtime version", status,
            "high" if status == "stale" else "info", match.group(1),
            [f"detected {runtime} {match.group(1)}; baseline is {'.'.join(map(str, minimum))}"],
        ))
    return signals


def _dependency_signals(sources: dict[str, str]) -> list[WesleySignal]:
    paths = {PurePosixPath(path).name.lower(): path for path in sources}
    manifests = sorted(path for name, path in paths.items() if name in MANIFEST_NAMES)
    if not manifests:
        return [
            _signal("dependency manifests", "unknown", evidence=["no supported manifest or lockfile found"]),
            _signal("dependency age", "unknown", evidence=["no dependency metadata was available"]),
            _signal("dependency CVEs", "unknown", evidence=["no advisory database was queried"]),
            _signal("maintainer activity", "unknown", evidence=["repository history is unavailable to static ZIP inspection"]),
        ]

    result = [_signal("dependency manifests", "observed", value=str(len(manifests)), evidence=manifests)]
    stale_patterns = [
        (r"\bjquery\s*[\"']?\s*[:=]\s*[\"']?1\.", "legacy jQuery 1.x"),
        (r"\bbootstrap\s*[\"']?\s*[:=]\s*[\"']?3\.", "legacy Bootstrap 3.x"),
        (r"\b(requests|lodash|log4j)\b", "dependency requires advisory verification"),
    ]
    manifest_text = "\n".join(sources[path] for path in manifests)
    for pattern, label in stale_patterns:
        if re.search(pattern, manifest_text, re.IGNORECASE):
            result.append(_signal("dependency version lag", "stale", "medium", evidence=[label]))
    result.extend([
        _signal("dependency age", "unknown", evidence=["package age is not derivable from a manifest alone"]),
        _signal("dependency CVEs", "unknown", evidence=["no advisory database was queried"]),
        _signal("maintainer activity", "unknown", evidence=["repository history is unavailable to static ZIP inspection"]),
    ])
    return result


def _source_signals(sources: dict[str, str], inventory: ProjectInventory) -> list[WesleySignal]:
    combined = "\n".join(sources.values())
    result: list[WesleySignal] = []
    insecure_patterns = [
        (r"\bmysql_(?:query|connect|fetch|real_escape_string)\s*\(", "PHP mysql_* API", "critical"),
        (r"\beval\s*\(|\bassert\s*\(", "dynamic code evaluation", "critical"),
        (r"\b(?:exec|shell_exec|system|passthru)\s*\(", "shell execution API", "high"),
        (r"\bmd5\s*\([^)]*(?:password|pass|secret)", "weak password hashing", "high"),
        (r"\bunserialize\s*\(", "unsafe deserialization", "high"),
    ]
    for pattern, label, severity in insecure_patterns:
        matches = [path for path, content in sources.items() if re.search(pattern, content, re.IGNORECASE)]
        if matches:
            result.append(_signal("known-insecure patterns", "detected", severity, label, matches))
    test_paths = [path for path in sources if any(part.lower() in TEST_PARTS for part in PurePosixPath(path).parts)]
    result.append(_signal("test coverage", "observed" if test_paths else "unknown", evidence=test_paths))
    result.extend([
        _signal("test churn", "unknown", evidence=["commit history is unavailable to static ZIP inspection"]),
        _signal("commit recency", "unknown", evidence=["commit history is unavailable to static ZIP inspection"]),
        _signal("framework EOL", "unknown", evidence=["framework release metadata is not bundled with source"]),
    ])
    if inventory.truncated:
        result.append(_signal("inspection completeness", "partial", "medium", evidence=["source context or files were truncated"]))
    return result


def _classify(signals: list[WesleySignal], inventory: ProjectInventory) -> tuple[str, str, list[str]]:
    critical = [signal for signal in signals if signal.severity == "critical" and signal.status == "detected"]
    high = [signal for signal in signals if signal.severity == "high" and signal.status in {"detected", "stale"}]
    stale = [signal for signal in signals if signal.status == "stale"]
    behaviors = len(inventory.behavior_signals)
    if critical:
        return "reengineer", "high", [signal.value or signal.name for signal in critical]
    if high and behaviors:
        return "coexist", "medium", [signal.value or signal.name for signal in high]
    if high or stale:
        return "replace", "medium", [signal.value or signal.name for signal in high + stale]
    if behaviors or inventory.database_tables:
        return "evolve", "medium", ["runtime behavior requires incremental migration review"]
    return "retain", "low", ["no blocking static risk detected"]


def assess_project(inventory: ProjectInventory, sources: dict[str, str]) -> WesleyAssessment:
    """Classify a project without executing source or consulting an LLM."""
    signals = _runtime_signals(sources) + _dependency_signals(sources) + _source_signals(sources, inventory)
    classification, confidence, reasons = _classify(signals, inventory)
    components = [WesleyComponent(
        component="codebase",
        classification=classification,
        confidence=confidence,
        reasons=reasons,
        signals=[signal.name for signal in signals if signal.status not in {"unknown", "supported", "observed"}],
    )]
    limitations = sorted({
        evidence
        for signal in signals if signal.status == "unknown"
        for evidence in signal.evidence
    })
    return WesleyAssessment(
        overall_classification=classification,
        confidence=confidence,
        components=components,
        signals=signals,
        limitations=limitations,
    )
