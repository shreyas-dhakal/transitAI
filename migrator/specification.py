"""Typed contracts for reconciled legacy-system understanding."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from migrator.cir import CanonicalIR, EvidenceSpan
from migrator.models import ProjectInventory, WesleyAssessment


ClaimCategory = Literal[
    "architecture",
    "business-rule",
    "component",
    "data-flow",
    "dependency",
    "integration",
    "permission",
    "route",
    "security",
    "state-machine",
    "workflow",
]
ClaimStatus = Literal["confirmed", "inferred", "contested", "gap"]
Confidence = Literal["high", "medium", "low"]
EvidenceSource = Literal["adapter", "cir", "wesley", "agent", "git"]


class EvidenceRef(BaseModel):
    """Stable pointer from a claim back to bounded project evidence."""

    source: EvidenceSource
    file: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    node_id: str | None = None
    excerpt_hash: str | None = None


class Claim(BaseModel):
    """One traceable fact or interpretation about the legacy system."""

    claim_id: str
    category: ClaimCategory
    statement: str
    status: ClaimStatus
    confidence: Confidence
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    supporting_agents: list[str] = Field(default_factory=list)
    contradicting_agents: list[str] = Field(default_factory=list)
    human_review_required: bool = False


class AgentResult(BaseModel):
    """Structured output from one specialist understanding agent."""

    agent_name: str
    run_id: str
    claims: list[Claim] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_artifact: str | None = None
    model: str | None = None
    prompt_version: str | None = None


class LegacySpecification(BaseModel):
    """Reconciled, machine-readable understanding of a legacy project."""

    schema_version: str = "1.0"
    project_name: str
    project_summary: str = ""
    system_boundaries: list[str] = Field(default_factory=list)
    runtime_architecture: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    state_machines: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    data_flows: list[str] = Field(default_factory=list)
    integrations: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    security_findings: list[str] = Field(default_factory=list)
    technical_debt: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    source_hash: str | None = None
    agent_results: list[AgentResult] = Field(default_factory=list)


def _span_refs(source: str, spans: list[EvidenceSpan], node_id: str | None = None) -> list[EvidenceRef]:
    return [
        EvidenceRef(
            source=source, file=span.file, start_line=span.start_line,
            end_line=span.end_line, node_id=node_id,
        )
        for span in spans
    ]


def _claim(
    claim_id: str,
    category: ClaimCategory,
    statement: str,
    evidence_refs: list[EvidenceRef],
) -> Claim:
    return Claim(
        claim_id=claim_id,
        category=category,
        statement=statement,
        status="confirmed",
        confidence="high",
        evidence_refs=evidence_refs,
        supporting_agents=["deterministic-seed"],
    )


def build_specification_seed(
    inventory: ProjectInventory,
    cir: CanonicalIR,
    wesley: WesleyAssessment,
) -> LegacySpecification:
    """Build the confirmed specification baseline without an LLM."""
    claims: list[Claim] = []
    routes: list[str] = []
    for route in cir.routes:
        routes.append(route.pattern)
        refs = _span_refs("cir", route.evidence_spans, route.route_id)
        refs.extend(EvidenceRef(source="cir", file=path, node_id=route.route_id) for path in route.source_paths)
        claims.append(_claim(
            f"claim:{route.route_id}", "route",
            f"The system exposes route {route.pattern}.", refs,
        ))

    entities: list[str] = []
    for entity in cir.entities:
        entities.append(entity.name)
        claims.append(_claim(
            f"claim:{entity.entity_id}", "data-flow",
            f"The system contains data entity {entity.name}.",
            _span_refs("cir", entity.evidence_spans, entity.entity_id),
        ))

    workflows: list[str] = []
    for behavior in cir.behaviors:
        for observed in behavior.observed_claims:
            workflows.append(observed.text)
            claims.append(_claim(
                f"claim:{behavior.unit_id}:{observed.claim_id}",
                "workflow",
                observed.text,
                _span_refs("cir", observed.evidence_spans, behavior.unit_id),
            ))

    security_findings: list[str] = []
    unknowns = list(wesley.limitations)
    for signal in wesley.signals:
        if signal.status in {"detected", "stale"} and signal.severity in {"critical", "high"}:
            finding = signal.value or signal.name
            security_findings.append(finding)
            refs = [EvidenceRef(source="wesley", file=item) for item in signal.evidence]
            claims.append(_claim(
                f"claim:security:{signal.name}:{finding}",
                "security",
                f"Static analysis detected {finding}.",
                refs,
            ))

    modules = sorted({
        node.label
        for node in cir.structural_nodes
        if node.kind == "file"
    })
    dependencies = list(dict.fromkeys(inventory.detected_technologies))
    claims.extend(
        _claim(
            f"claim:technology:{index}",
            "dependency",
            f"The source uses {technology}.",
            [EvidenceRef(source="adapter")],
        )
        for index, technology in enumerate(dependencies)
    )
    return LegacySpecification(
        project_name=inventory.project_name,
        project_summary=f"Deterministic evidence baseline for {inventory.project_name}.",
        runtime_architecture=dependencies,
        modules=modules,
        routes=routes,
        workflows=list(dict.fromkeys(workflows)),
        entities=entities,
        dependencies=dependencies,
        security_findings=list(dict.fromkeys(security_findings)),
        claims=claims,
        unknowns=list(dict.fromkeys(unknowns)),
        source_hash=cir.provenance.source_hash,
    )
