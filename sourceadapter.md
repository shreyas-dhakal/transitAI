# Layer 0: Source Intake and Adapters

Layer 0 separates safe project intake from source interpretation. It produces
the sanitized `ProjectSnapshot` consumed by Layer 1, the Canonical Intermediate
Representation.

```text
ZIP/GitHub archive
        |
        v
inspect_project()
        |
        v
  Intake boundary
  limits, paths, sensitive files, redaction
        |
        v
  AdapterRegistry
  detect and compose adapters
        |
        v
  AdapterFindings per adapter
        |
        v
  merged findings + ProjectSnapshot
```

The intake boundary runs first. Adapters receive only normalized, bounded,
secret-filtered source text. They never execute source, access the filesystem,

## Current Implementation

### Universal Web Adapter

`UniversalWebAdapter` is the framework-independent baseline. It detects:

- Likely languages and technologies
- Page and template route candidates
- SQL table definitions
- Forms, sessions, database access, email, uploads, includes, and AJAX

### Adapter Registry

`AdapterRegistry` selects and composes registered adapters deterministically.
The default registry includes:

- `UniversalWebAdapter`
- `StructuralGraphAdapter`, when structural source files are present

Adapters may expose `detect(sources)` and return a confidence score with reasons.
Adapters without a detector are included when explicitly registered.

```python
from migrator import AdapterRegistry, inspect_project

registry = AdapterRegistry.with_defaults()
registry.register(InternalPlatformAdapter())

snapshot = inspect_project(
    project_zip_bytes,
    "legacy-project.zip",
    registry=registry,
)
```

Explicit selection still overrides registry selection:

```python
snapshot = inspect_project(
    project_zip_bytes,
    "project.zip",
    adapter=InternalPlatformAdapter(),
)
```

Passing both `adapter` and `registry` is rejected to avoid ambiguous behavior.

### Adapter Composition

Multiple adapters inspect the same normalized source map. Their list findings
are unioned and de-duplicated. Graph nodes are merged by node ID and graph
edges by source, target, and relationship type.

The merged inventory records adapter names in `adapter_sources`; the original
per-adapter results remain available through `ProjectSnapshot.findings`.

```python
print(snapshot.inventory.adapter_sources)
for finding in snapshot.findings:
    print(finding.adapter_name, finding.behavior_signals)
```

### Structural Graph Adapter

`StructuralGraphAdapter` provides a dependency-light structural pass. It
creates file and symbol nodes and records resolvable import and definition
edges without executing code.

```python
graph = snapshot.findings[-1].graph
if graph:
    for node in sorted(graph.nodes, key=lambda item: item.rank, reverse=True)[:10]:
        print(node.label, node.rank)
```

The graph contract is deliberately independent of the parser implementation:

```python
GraphNode(node_id, kind, label, rank)
GraphEdge(source, target, kind)
GraphFindings(nodes, edges, budget_tokens=None)
```

The current adapter uses safe lexical structural extraction. A future
Tree-sitter adapter can provide richer AST-level definitions and references
without changing `GraphFindings` or downstream consumers.

## Custom Adapter

Implement the `SourceAdapter` protocol:

```python
from migrator import AdapterFindings


class InternalPlatformAdapter:
    name = "internal-platform"

    def detect(self, sources: dict[str, str]):
        if "platform.manifest" in sources:
            return 1.0, ["platform manifest"]
        return None

    def inspect(self, sources: dict[str, str]) -> AdapterFindings:
        return AdapterFindings(
            detected_technologies=["Internal platform"],
            route_candidates=["/"],
            database_tables=[],
            behavior_signals=[],
        )
```

`detect` is optional. Its result may be:

- `None` or `False`: adapter is not selected
- `True`: adapter is selected with full confidence
- `(confidence, reasons)`: adapter is selected with explicit metadata

`inspect` must return deterministic evidence only.

## Snapshot Contract

- `ProjectInventory`: compact validated summary for planning and UI consumers.
- `ProjectSnapshot`: inventory, bounded source context, copied assets, and per-adapter findings.
- `AdapterFindings`: technologies, routes, tables, behavior signals, and optional graph data.

`ProjectInventory` is the aggregate summary. Detailed graph and adapter
provenance stay on `ProjectSnapshot` rather than making the inventory large.

## Safety Invariants

- Archive limits and path validation run before adapters.
- Sensitive files are skipped before adapter inspection.
- Common inline credentials are redacted before adapter inspection.
- Source files are never extracted or executed by the adapter layer.
- Adapters do not access credentials, the filesystem, or external services.
- Downstream planning consumes the validated snapshot, not raw archive members.

## Future Enhancements

### GitHub Linguist

Use Linguist or the GitHub Languages API as a repository profile layer for:

- Language percentages
- Generated and vendored file classification
- Documentation and test detection
- Adapter selection hints

Linguist should inform selection and filtering, not replace semantic adapters.
For ZIP uploads, a local Linguist worker is optional; extension-based detection
remains the safe fallback.

### Tree-sitter

Replace or augment `StructuralGraphAdapter` with Tree-sitter parsers for richer:

- Symbol definitions and references
- Call relationships
- Framework-independent AST structure
- Graph-ranked context selection

The parser must remain isolated and resource-bounded for untrusted source.

### Repomix Context Packs

Repomix should be a derived model-context layer after intake and redaction:

```text
sanitized ProjectSnapshot
        |
        v
Repomix token-aware pack
        |
        v
Azure planning context
```

It can improve token counting, repository-tree context, and graph-ranked file
selection. It must not be the authoritative snapshot or the security filter.

### MCP Query Server

After snapshots are persisted as artifacts, an optional read-only MCP server
can expose bounded queries such as:

- `get_inventory()`
- `get_graph(max_nodes=...)`
- `get_route(path, max_chars=...)`
- `get_symbol_context(name, max_chars=...)`

MCP should query an already-computed sanitized snapshot. It must not gain
arbitrary filesystem access, rerun intake, or execute source code.

## Compatibility

`inspect_lamp_zip`, `LampProject`, and `AzureLampMigrator` remain available for
existing callers. New integrations should use `inspect_project`,
`ProjectSnapshot`, and `AdapterRegistry`.
