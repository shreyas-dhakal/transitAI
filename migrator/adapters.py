"""Technology-neutral source interpretation for bounded project evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Protocol


@dataclass(frozen=True)
class AdapterFindings:
    """Facts inferred from source text by an inspection adapter."""

    detected_technologies: list[str]
    route_candidates: list[str]
    database_tables: list[str]
    behavior_signals: list[str]
    graph: GraphFindings | None = None
    adapter_name: str = ""
    side_effects: list[SideEffectFinding] | None = None


@dataclass(frozen=True)
class SideEffectFinding:
    """A statically observed event-driven behavior in legacy source."""

    effect_id: str
    trigger: str
    callback: str | None
    kind: str
    source_path: str
    start_line: int
    end_line: int
    evidence: str
    external_effect: str | None = None
    plugin: str | None = None


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: str
    label: str
    rank: float = 0.0


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: str


@dataclass(frozen=True)
class GraphFindings:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    budget_tokens: int | None = None


class SourceAdapter(Protocol):
    """Interpret source evidence without reading archives or executing code."""

    name: str

    def inspect(self, sources: dict[str, str]) -> AdapterFindings:
        """Return deterministic findings for normalized source files."""


@dataclass(frozen=True)
class AdapterMatch:
    adapter: SourceAdapter
    confidence: float
    reasons: list[str]


class AdapterRegistry:
    """Deterministically select and compose adapters for one source snapshot."""

    def __init__(self, adapters: list[SourceAdapter] | None = None) -> None:
        self._adapters: list[SourceAdapter] = list(adapters or [])

    @classmethod
    def with_defaults(cls) -> "AdapterRegistry":
        return cls([UniversalWebAdapter(), StructuralGraphAdapter()])

    def register(self, adapter: SourceAdapter) -> None:
        if any(existing.name == adapter.name for existing in self._adapters):
            raise ValueError(f"An adapter named '{adapter.name}' is already registered.")
        self._adapters.append(adapter)

    def matches(self, sources: dict[str, str]) -> list[AdapterMatch]:
        matches: list[AdapterMatch] = []
        for adapter in self._adapters:
            detector = getattr(adapter, "detect", None)
            if detector is None:
                matches.append(AdapterMatch(adapter, 1.0, ["registered adapter"]))
                continue
            result = detector(sources)
            if result is True:
                result = (1.0, ["adapter detection rule matched"])
            if not result:
                continue
            confidence, reasons = result
            matches.append(AdapterMatch(adapter, max(0.0, min(1.0, confidence)), reasons))
        return matches

    def inspect(self, sources: dict[str, str]) -> list[AdapterFindings]:
        findings: list[AdapterFindings] = []
        for match in self.matches(sources):
            result = match.adapter.inspect(sources)
            if not result.adapter_name:
                result = replace(result, adapter_name=match.adapter.name)
            findings.append(result)
        return findings


def merge_findings(findings: list[AdapterFindings]) -> AdapterFindings:
    """Merge composed adapter output while retaining graph node identity."""
    if not findings:
        return AdapterFindings([], [], [], [], adapter_name="none")
    detected = list(dict.fromkeys(value for finding in findings for value in finding.detected_technologies))
    routes = list(dict.fromkeys(value for finding in findings for value in finding.route_candidates))
    tables = list(dict.fromkeys(value for finding in findings for value in finding.database_tables))
    behaviors = list(dict.fromkeys(value for finding in findings for value in finding.behavior_signals))
    graph_findings = [finding.graph for finding in findings if finding.graph]
    graph = None
    if graph_findings:
        nodes: dict[str, GraphNode] = {}
        edges: dict[tuple[str, str, str], GraphEdge] = {}
        for item in graph_findings:
            for node in item.nodes:
                previous = nodes.get(node.node_id)
                if previous is None or node.rank > previous.rank:
                    nodes[node.node_id] = node
            for edge in item.edges:
                edges[(edge.source, edge.target, edge.kind)] = edge
        graph = GraphFindings(list(nodes.values()), list(edges.values()), min(
            (item.budget_tokens for item in graph_findings if item.budget_tokens is not None),
            default=None,
        ))
    return AdapterFindings(
        detected, routes, tables, behaviors, graph,
        adapter_name="+".join(finding.adapter_name for finding in findings),
        side_effects=[
            effect
            for finding in findings
            for effect in (finding.side_effects or [])
        ] or None,
    )


WEB_PAGE_EXTENSIONS = {
    ".asp", ".aspx", ".cfm", ".erb", ".htm", ".html", ".jsp", ".php",
    ".phtml", ".svelte", ".vue",
}
NON_ROUTE_DIRECTORIES = {
    "config", "controllers", "includes", "lib", "partials", "src", "tests",
    "vendor", "views",
}
NON_ROUTE_STEMS = {
    "app", "bootstrap", "config", "database", "db", "footer", "functions",
    "header", "helpers", "layout", "routes",
}


def _file_route(path: PurePosixPath) -> str:
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1].lower() in {"index", "default"}:
        parts.pop()
    return "/" + "/".join(parts)


def _route_candidates(paths: list[str]) -> list[str]:
    routes = set()
    for raw_path in paths:
        path = PurePosixPath(raw_path)
        if path.suffix.lower() not in WEB_PAGE_EXTENSIONS:
            continue
        if path.stem.lower() in NON_ROUTE_STEMS:
            continue
        if any(part.lower() in NON_ROUTE_DIRECTORIES for part in path.parts[:-1]):
            continue
        routes.add(_file_route(path))
    return sorted(routes)


def _technology_signals(paths: list[str], combined_text: str) -> list[str]:
    lowered_paths = [path.lower() for path in paths]
    checks = [
        ("PHP", any(path.endswith((".php", ".phtml")) for path in lowered_paths)),
        ("Python", any(path.endswith(".py") for path in lowered_paths)),
        ("Ruby", any(path.endswith((".rb", ".erb")) for path in lowered_paths)),
        ("Java", any(path.endswith((".java", ".jsp")) for path in lowered_paths)),
        ("C#", any(path.endswith((".cs", ".aspx")) for path in lowered_paths)),
        ("JavaScript/TypeScript", any(path.endswith((".js", ".jsx", ".ts", ".tsx")) for path in lowered_paths)),
        ("Vue", any(path.endswith(".vue") for path in lowered_paths)),
        ("Svelte", any(path.endswith(".svelte") for path in lowered_paths)),
        ("MySQL", bool(re.search(r"(?i)\b(mysql|mysqli|pdo)\b", combined_text))),
        ("PostgreSQL", bool(re.search(r"(?i)\b(postgres|postgresql|psycopg)\b", combined_text))),
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
        ("Session-backed behavior", r"(?i)\bsession_start\s*\(|\$_SESSION|req\.session\("),
        ("Database reads or writes", r"(?i)\b(SELECT|INSERT|UPDATE|DELETE)\b|->query\s*\(|sequelize|\.objects\.(get|filter)\("),
        ("Email delivery", r"(?i)\bmail\s*\(|nodemailer|sendgrid|ActionMailer"),
        ("File uploads", r"(?i)multipart/form-data|\$_FILES|multer|FileField"),
        ("Server-side includes", r"(?i)\b(include|require)(_once)?\s*[\s(]|extends\s+[\"']|{%\s*extends"),
        ("AJAX requests", r"(?i)\b(fetch|XMLHttpRequest|\$\.ajax|axios)\b"),
    ]
    return [label for label, pattern in checks if re.search(pattern, combined_text)]


def _line_number(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _callback_name(content: str, start: int) -> str | None:
    window = content[start:start + 400]
    match = re.search(r"(?:function\s+|['\"])([A-Za-z_][\w-]*)", window)
    return match.group(1) if match else None


def _wordpress_side_effects(sources: dict[str, str]) -> list[SideEffectFinding]:
    """Extract WordPress event registrations without executing PHP."""
    effects: list[SideEffectFinding] = []
    hook_pattern = re.compile(
        r"(?i)\b(add_action|add_filter)\s*\(\s*['\"]([^'\"]+)['\"]"
    )
    cron_pattern = re.compile(
        r"(?i)\b(wp_schedule_event|wp_next_scheduled|wp_clear_scheduled_hook)\s*\("
    )
    webhook_pattern = re.compile(
        r"(?i)\b(webhook|wp_remote_(?:get|post|request)|curl_exec)"
    )
    for path, content in sorted(sources.items()):
        lowered = path.lower()
        is_php = lowered.endswith((".php", ".phtml"))
        if not is_php:
            continue
        plugin_match = re.search(r"(?im)^\s*\*?\s*plugin\s+name\s*:\s*(.+?)\s*$", content)
        plugin = plugin_match.group(1).strip() if plugin_match else None
        for match in hook_pattern.finditer(content):
            trigger = match.group(2)
            callback = _callback_name(content, match.end())
            kind = "woocommerce-hook" if trigger.lower().startswith(("woocommerce_", "woocommerce")) else "wordpress-hook"
            external = "order or commerce side effect" if kind == "woocommerce-hook" else None
            effects.append(SideEffectFinding(
                effect_id=f"side-effect:{path}:{_line_number(content, match.start())}:{trigger}",
                trigger=trigger,
                callback=callback,
                kind=kind,
                source_path=path,
                start_line=_line_number(content, match.start()),
                end_line=_line_number(content, match.end()),
                evidence=match.group(0),
                external_effect=external,
                plugin=plugin,
            ))
        for match in cron_pattern.finditer(content):
            effects.append(SideEffectFinding(
                effect_id=f"side-effect:{path}:{_line_number(content, match.start())}:cron",
                trigger="wp-cron",
                callback=_callback_name(content, match.end()),
                kind="wordpress-cron",
                source_path=path,
                start_line=_line_number(content, match.start()),
                end_line=_line_number(content, match.end()),
                evidence=match.group(0),
                external_effect="scheduled background work",
                plugin=plugin,
            ))
        if webhook_pattern.search(content):
            match = webhook_pattern.search(content)
            assert match is not None
            effects.append(SideEffectFinding(
                effect_id=f"side-effect:{path}:{_line_number(content, match.start())}:webhook",
                trigger="form or integration webhook",
                callback=None,
                kind="webhook",
                source_path=path,
                start_line=_line_number(content, match.start()),
                end_line=_line_number(content, match.end()),
                evidence=match.group(0),
                external_effect="outbound HTTP delivery",
                plugin=plugin,
            ))
    return effects


class UniversalWebAdapter:
    """Broad web-project adapter with no required framework assumption.

    It relies on file and text evidence first. Framework-specific recognizers can
    later enrich the same contract without changing archive intake or generation.
    """

    name = "universal-web"

    def detect(self, sources: dict[str, str]) -> tuple[float, list[str]]:
        paths = list(sources)
        web_files = sum(
            PurePosixPath(path).suffix.lower() in WEB_PAGE_EXTENSIONS
            for path in paths
        )
        return (1.0 if web_files else 0.35, [f"{web_files} web page/template files"])

    def inspect(self, sources: dict[str, str]) -> AdapterFindings:
        combined_text = "\n".join(sources.values())
        side_effects = _wordpress_side_effects(sources)
        behavior_signals = _behavior_signals(combined_text)
        behavior_signals.extend(
            effect.trigger
            for effect in side_effects
            if effect.trigger not in behavior_signals
        )
        return AdapterFindings(
            detected_technologies=_technology_signals(list(sources), combined_text),
            route_candidates=_route_candidates(list(sources)),
            database_tables=sorted(
                set(
                    re.findall(
                        r"(?i)CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?([A-Za-z0-9_]+)",
                        combined_text,
                    )
                )
            ),
            behavior_signals=behavior_signals,
            side_effects=side_effects,
        )


STRUCTURAL_EXTENSIONS = {
    ".cs", ".go", ".java", ".js", ".jsx", ".php", ".py", ".rb", ".rs",
    ".ts", ".tsx", ".vue",
}
IMPORT_PATTERNS = (
    re.compile(r"(?m)^\s*import\s+(?:.+?\s+from\s+)?[\"'](.+?)[\"']"),
    re.compile(r"(?m)^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))"),
)
DEFINITION_PATTERN = re.compile(
    r"(?m)^\s*(?:export\s+)?(?:async\s+)?(?:function|class|def|func|fn)\s+([A-Za-z_][\w]*)"
)


def _resolve_import(source_path: str, imported: str, paths: set[str]) -> str | None:
    if not imported.startswith("."):
        return None
    base = PurePosixPath(source_path).parent / imported
    candidates = [base.as_posix(), *(f"{base.as_posix()}{suffix}" for suffix in (".js", ".jsx", ".ts", ".tsx", ".vue", ".py"))]
    candidates.extend(f"{base.as_posix()}/index{suffix}" for suffix in (".js", ".ts", ".tsx", ".py"))
    return next((candidate for candidate in candidates if candidate in paths), None)


class StructuralGraphAdapter:
    """Build a bounded file/symbol dependency graph without executing source.

    This is a dependency-light structural pass. A Tree-sitter implementation can
    replace it later while preserving the GraphFindings contract.
    """

    name = "structural-graph"

    def detect(self, sources: dict[str, str]) -> tuple[float, list[str]] | None:
        count = sum(PurePosixPath(path).suffix.lower() in STRUCTURAL_EXTENSIONS for path in sources)
        return (0.9, [f"{count} structured source files"]) if count else None

    def inspect(self, sources: dict[str, str]) -> AdapterFindings:
        paths = set(sources)
        nodes: dict[str, GraphNode] = {
            f"file:{path}": GraphNode(f"file:{path}", "file", path)
            for path in sorted(paths)
            if PurePosixPath(path).suffix.lower() in STRUCTURAL_EXTENSIONS
        }
        edges: dict[tuple[str, str, str], GraphEdge] = {}
        for path in sorted(paths):
            if f"file:{path}" not in nodes:
                continue
            content = sources[path]
            for match in IMPORT_PATTERNS[0].finditer(content):
                target = _resolve_import(path, match.group(1), paths)
                if target:
                    edge = GraphEdge(f"file:{path}", f"file:{target}", "imports")
                    edges[(edge.source, edge.target, edge.kind)] = edge
            for match in IMPORT_PATTERNS[1].finditer(content):
                imported = match.group(1) or match.group(2)
                target = _resolve_import(path, imported, paths)
                if target:
                    edge = GraphEdge(f"file:{path}", f"file:{target}", "imports")
                    edges[(edge.source, edge.target, edge.kind)] = edge
            for symbol in DEFINITION_PATTERN.findall(content):
                node_id = f"symbol:{path}:{symbol}"
                nodes[node_id] = GraphNode(node_id, "symbol", symbol)
                edge = GraphEdge(f"file:{path}", node_id, "defines")
                edges[(edge.source, edge.target, edge.kind)] = edge

        incoming: dict[str, int] = {node_id: 0 for node_id in nodes}
        for edge in edges.values():
            incoming[edge.target] = incoming.get(edge.target, 0) + 1
        ranked = [
            replace(node, rank=incoming.get(node.node_id, 0))
            for node in nodes.values()
        ]
        return AdapterFindings([], [], [], [], GraphFindings(ranked, list(edges.values())), self.name)
