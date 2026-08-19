"""Canonical Intermediate Representation compilation and aggregation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Iterable

from pydantic import BaseModel, Field

from migrator.adapters import AdapterFindings, GraphEdge, GraphNode, merge_findings
from migrator.models import ProjectInventory


CIR_SCHEMA_VERSION = "1.0"
EXTRACTOR_VERSION = "layer1-compiler-1"
AGGREGATION_VERSION = "exact-claims-1"


class EvidenceSpan(BaseModel):
    file: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class CIRProvenance(BaseModel):
    schema_version: str = CIR_SCHEMA_VERSION
    source_hash: str
    extractor_version: str = EXTRACTOR_VERSION
    aggregation_version: str = AGGREGATION_VERSION
    sample_set_hash: str


class CIRNode(BaseModel):
    node_id: str
    kind: str
    label: str
    source_paths: list[str] = Field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)


class CIREdge(BaseModel):
    source: str
    target: str
    kind: str


class CanonicalRoute(BaseModel):
    route_id: str
    pattern: str
    source_paths: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    rendering: str | None = None
    auth: str | None = None
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    status: str = "inferred"


class CanonicalEntity(BaseModel):
    entity_id: str
    name: str
    fields: list[str] = Field(default_factory=list)
    operations: list[str] = Field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    status: str = "observed"


class CanonicalAsset(BaseModel):
    asset_id: str
    source_path: str
    output_path: str
    content_type: str | None = None
    usage_locations: list[str] = Field(default_factory=list)
    ownership: str = "shared-or-static"
    status: str = "observed"


class SampleMetadata(BaseModel):
    sample_id: str
    model: str
    seed: str | None = None
    framing: str
    context_hash: str


class BehaviorClaim(BaseModel):
    """One atomic interpretation of one extraction unit."""

    kind: str
    text: str
    attributes: dict[str, str] = Field(default_factory=dict)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)

    def normalized_key(self) -> str:
        normalized_text = " ".join(self.text.lower().split())
        return json.dumps(
            {"kind": self.kind, "text": normalized_text, "attributes": self.attributes},
            sort_keys=True,
            separators=(",", ":"),
        )


class BehaviorSample(BaseModel):
    sample_id: str
    unit_id: str
    claims: list[BehaviorClaim] = Field(default_factory=list)
    metadata: SampleMetadata


class BehaviorExtraction(BaseModel):
    """Structured model response before Transit adds sample metadata."""

    claims: list[BehaviorClaim] = Field(default_factory=list)


class AggregatedClaim(BaseModel):
    claim_id: str
    kind: str
    text: str
    attributes: dict[str, str] = Field(default_factory=dict)
    support: float = Field(ge=0.0, le=1.0)
    n_samples: int = Field(ge=0)
    cross_model_agreement: bool = False
    confidence_tier: str
    structural_check: str = "not_checkable"
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    disagreeing_claims: list[str] = Field(default_factory=list)


class BehavioralUnit(BaseModel):
    unit_id: str
    source_node_ids: list[str] = Field(default_factory=list)
    samples: list[BehaviorSample] = Field(default_factory=list)
    observed_claims: list[AggregatedClaim] = Field(default_factory=list)
    claims: list[AggregatedClaim] = Field(default_factory=list)


class RuntimeObservation(BaseModel):
    observation_id: str
    unit_id: str
    request: dict[str, str] = Field(default_factory=dict)
    response: dict[str, str] = Field(default_factory=dict)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)


class CanonicalIR(BaseModel):
    project_name: str
    provenance: CIRProvenance
    technologies: list[str] = Field(default_factory=list)
    structural_nodes: list[CIRNode] = Field(default_factory=list)
    structural_edges: list[CIREdge] = Field(default_factory=list)
    routes: list[CanonicalRoute] = Field(default_factory=list)
    entities: list[CanonicalEntity] = Field(default_factory=list)
    behaviors: list[BehavioralUnit] = Field(default_factory=list)
    assets: list[CanonicalAsset] = Field(default_factory=list)
    runtime_observations: list[RuntimeObservation] = Field(default_factory=list)


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sample_set_hash(behaviors: Iterable[BehavioralUnit]) -> str:
    samples = [sample.model_dump(mode="json") for unit in behaviors for sample in unit.samples]
    return _hash_payload(samples)


def _source_hash(sources: dict[str, str], assets: Iterable[object]) -> str:
    asset_hashes = [
        {
            "path": asset.source_path,
            "output": asset.output_path,
            "content_hash": hashlib.sha256(asset.content).hexdigest(),
        }
        for asset in sorted(assets, key=lambda item: item.source_path)
    ]
    return _hash_payload({"sources": sorted(sources.items()), "assets": asset_hashes})


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "unknown"


def _source_span(path: str, content: str, pattern: str) -> list[EvidenceSpan]:
    match = re.search(pattern, content, re.IGNORECASE)
    if not match:
        return []
    return [EvidenceSpan(file=path, start_line=content.count("\n", 0, match.start()) + 1, end_line=content.count("\n", 0, match.end()) + 1)]


def _route_sources(route: str, sources: dict[str, str]) -> list[str]:
    result = []
    for path in sorted(sources):
        candidate = "/" + "/".join(PurePosixPath(path).with_suffix("").parts)
        if PurePosixPath(path).stem.lower() in {"index", "default"}:
            candidate = "/" + "/".join(PurePosixPath(path).parent.parts)
        if candidate.rstrip("/") or route == "/":
            if candidate.rstrip("/") == route.rstrip("/"):
                result.append(path)
    return result


def _structural_data(findings: list[AdapterFindings]) -> tuple[list[CIRNode], list[CIREdge]]:
    merged = merge_findings(findings)
    if not merged.graph:
        return [], []
    nodes = [
        CIRNode(node_id=node.node_id, kind=node.kind, label=node.label, source_paths=[node.label] if node.kind == "file" else [])
        for node in sorted(merged.graph.nodes, key=lambda item: item.node_id)
    ]
    edges = [CIREdge(source=edge.source, target=edge.target, kind=edge.kind) for edge in sorted(merged.graph.edges, key=lambda item: (item.source, item.target, item.kind))]
    return nodes, edges


def _behavior_units(inventory: ProjectInventory, sources: dict[str, str]) -> list[BehavioralUnit]:
    units: list[BehavioralUnit] = []
    for signal in inventory.behavior_signals:
        unit_id = f"behavior:{_slug(signal)}"
        spans: list[EvidenceSpan] = []
        source_node_ids: list[str] = []
        for path, content in sorted(sources.items()):
            if signal == "HTML form submission":
                pattern = r"<form\b"
            elif signal == "Database reads or writes":
                pattern = r"\b(select|insert|update|delete)\b|->query\s*\("
            else:
                pattern = re.escape(signal.split()[0])
            found = _source_span(path, content, pattern)
            if found:
                spans.extend(found)
                source_node_ids.append(f"file:{path}")
        claim = BehaviorClaim(kind="signal", text=signal, evidence_spans=spans)
        # The deterministic signal is retained as a baseline observation. Azure
        # samples can add or contest richer claims for the same unit later.
        observed = aggregate_claims(unit_id, [BehaviorSample(
            sample_id=f"deterministic:{unit_id}", unit_id=unit_id, claims=[claim], metadata=SampleMetadata(
                sample_id=f"deterministic:{unit_id}", model="layer0-adapter", framing="deterministic-signal", context_hash=""
            )
        )])
        units.append(BehavioralUnit(
            unit_id=unit_id,
            source_node_ids=source_node_ids,
            observed_claims=observed,
            claims=observed,
        ))
    return units


def aggregate_claims(unit_id: str, samples: list[BehaviorSample], structural_check: str = "not_checkable") -> list[AggregatedClaim]:
    """Aggregate structured claims without another model or unstable clustering."""
    if not samples:
        return []
    clusters: dict[str, list[tuple[BehaviorSample, BehaviorClaim]]] = {}
    for sample in samples:
        for claim in sample.claims:
            clusters.setdefault(claim.normalized_key(), []).append((sample, claim))
    result: list[AggregatedClaim] = []
    for key, occurrences in sorted(clusters.items()):
        supporting_samples = {sample.sample_id for sample, _ in occurrences}
        support = len(supporting_samples) / len(samples)
        models = {sample.metadata.model for sample, _ in occurrences}
        representative = occurrences[0][1]
        other_text = sorted({claim.text for _, claim in occurrences if claim.text != representative.text})
        if support >= 0.9 and structural_check == "consistent":
            tier = "confirmed"
        elif support >= 0.7:
            tier = "likely"
        elif support >= 0.3:
            tier = "contested"
        else:
            tier = "gap"
        result.append(AggregatedClaim(
            claim_id=_hash_payload({"unit_id": unit_id, "claim": key}),
            kind=representative.kind,
            text=representative.text,
            attributes=representative.attributes,
            support=round(support, 6),
            n_samples=len(samples),
            cross_model_agreement=len(models) > 1,
            confidence_tier=tier,
            structural_check=structural_check,
            evidence_spans=[span for _, claim in occurrences for span in claim.evidence_spans],
            disagreeing_claims=other_text,
        ))
    return result


def compile_cir(
    inventory: ProjectInventory,
    sources: dict[str, str],
    assets: list[object],
    findings: list[AdapterFindings],
) -> CanonicalIR:
    """Build the deterministic portion of Layer 1 from a sanitized snapshot."""
    nodes, edges = _structural_data(findings)
    routes = []
    for route in inventory.route_candidates:
        source_paths = _route_sources(route, sources)
        route_id = f"route:{route}"
        routes.append(CanonicalRoute(route_id=route_id, pattern=route, source_paths=source_paths))
    entities = [
        CanonicalEntity(entity_id=f"entity:{_slug(table)}", name=table, operations=["read-or-write"])
        for table in inventory.database_tables
    ]
    canonical_assets = [
        CanonicalAsset(
            asset_id=f"asset:{asset.source_path}",
            source_path=asset.source_path,
            output_path=asset.output_path,
            content_type=PurePosixPath(asset.source_path).suffix.lower().removeprefix(".") or None,
        )
        for asset in sorted(assets, key=lambda item: item.source_path)
    ]
    behaviors = _behavior_units(inventory, sources)
    sample_hash = _sample_set_hash(behaviors)
    return CanonicalIR(
        project_name=inventory.project_name,
        provenance=CIRProvenance(source_hash=_source_hash(sources, assets), sample_set_hash=sample_hash),
        technologies=inventory.detected_technologies,
        structural_nodes=nodes,
        structural_edges=edges,
        routes=routes,
        entities=entities,
        behaviors=behaviors,
        assets=canonical_assets,
    )


def add_behavior_samples(cir: CanonicalIR, samples: list[BehaviorSample]) -> CanonicalIR:
    """Return a new CIR with sampled claims deterministically re-aggregated."""
    by_unit: dict[str, list[BehaviorSample]] = {}
    for sample in samples:
        by_unit.setdefault(sample.unit_id, []).append(sample)
    units = []
    for unit in cir.behaviors:
        unit_samples = by_unit.get(unit.unit_id, [])
        if unit_samples:
            observed_keys = {claim.kind + ":" + claim.text.lower() for claim in unit.observed_claims}
            sample_keys = {claim.kind + ":" + claim.text.lower() for sample in unit_samples for claim in sample.claims}
            structural = "consistent" if observed_keys & sample_keys else "not_checkable"
            unit = unit.model_copy(update={"samples": unit_samples, "claims": aggregate_claims(unit.unit_id, unit_samples, structural)})
        units.append(unit)
    known_units = {unit.unit_id for unit in cir.behaviors}
    for unit_id, unit_samples in sorted(by_unit.items()):
        if unit_id not in known_units:
            units.append(BehavioralUnit(
                unit_id=unit_id,
                samples=unit_samples,
                claims=aggregate_claims(unit_id, unit_samples),
            ))
    updated = cir.model_copy(update={
        "behaviors": units,
        "provenance": cir.provenance.model_copy(update={"sample_set_hash": _sample_set_hash(units)}),
    })
    return updated
