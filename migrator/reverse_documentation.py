"""Reverse-documentation contracts, deterministic seed, and artifact rendering."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from migrator.adapters import AdapterFindings
from migrator.cir import CanonicalIR
from migrator.models import ProjectInventory, WesleyAssessment


ScenarioPriority = Literal["critical", "high", "normal"]
ScenarioStatus = Literal["observed", "inferred", "gap"]


class TraceabilityLink(BaseModel):
    source: Literal["adapter", "cir", "wesley", "agent", "git"]
    file: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    node_id: str | None = None
    excerpt_hash: str | None = None


class ModuleDocumentation(BaseModel):
    module_id: str
    name: str
    responsibilities: list[str] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    evidence: list[TraceabilityLink] = Field(default_factory=list)


class DataFlow(BaseModel):
    flow_id: str
    source: str
    destination: str
    operation: str
    trigger: str | None = None
    evidence: list[TraceabilityLink] = Field(default_factory=list)


class SideEffect(BaseModel):
    effect_id: str
    trigger: str
    callback: str | None = None
    kind: str
    source_path: str
    start_line: int
    end_line: int
    evidence: str
    external_effect: str | None = None
    plugin: str | None = None
    status: ScenarioStatus = "observed"
    preservation_priority: ScenarioPriority = "high"


class BehaviorScenario(BaseModel):
    scenario_id: str
    title: str
    feature: str
    priority: ScenarioPriority = "normal"
    status: ScenarioStatus = "observed"
    tags: list[str] = Field(default_factory=list)
    given: list[str] = Field(default_factory=list)
    when: str
    then: list[str] = Field(default_factory=list)
    evidence: list[TraceabilityLink] = Field(default_factory=list)
    side_effect_id: str | None = None


class DiagramArtifact(BaseModel):
    artifact_id: str
    title: str
    diagram_type: Literal["c4-context", "c4-containers", "c4-components", "data-flow"]
    mermaid: str
    evidence: list[TraceabilityLink] = Field(default_factory=list)


class ProductPlan(BaseModel):
    purpose: str
    users: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class ReverseDocumentation(BaseModel):
    schema_version: str = "1.0"
    project_name: str
    summary: str
    modules: list[ModuleDocumentation] = Field(default_factory=list)
    data_flows: list[DataFlow] = Field(default_factory=list)
    side_effects: list[SideEffect] = Field(default_factory=list)
    scenarios: list[BehaviorScenario] = Field(default_factory=list)
    diagrams: list[DiagramArtifact] = Field(default_factory=list)
    product_plan: ProductPlan
    confidence: Literal["high", "medium", "low"] = "medium"
    gaps: list[str] = Field(default_factory=list)
    source_hash: str | None = None


def _hash_excerpt(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _link(source: str, path: str | None = None, start: int | None = None,
          end: int | None = None, node_id: str | None = None,
          excerpt: str | None = None) -> TraceabilityLink:
    return TraceabilityLink(
        source=source, file=path, start_line=start, end_line=end,
        node_id=node_id, excerpt_hash=_hash_excerpt(excerpt) if excerpt else None,
    )


def _effect_scenarios(effect: SideEffect) -> list[BehaviorScenario]:
    base_tags = ["parity", effect.kind]
    evidence = [_link("adapter", effect.source_path, effect.start_line, effect.end_line, effect.effect_id, effect.evidence)]
    trigger = effect.trigger
    callback = effect.callback or "the registered callback"
    normal = BehaviorScenario(
        scenario_id=f"scenario:{effect.effect_id}:normal",
        title=f"{trigger} invokes its registered side effect",
        feature=f"Preserve {trigger}", priority=effect.preservation_priority,
        tags=base_tags + ["critical" if effect.preservation_priority == "critical" else "preserve"],
        given=[f"the legacy system receives the {trigger} event"],
        when=f"the {trigger} handler is dispatched",
        then=[f"{callback} runs", "the observed side effect is produced exactly once"],
        evidence=evidence, side_effect_id=effect.effect_id,
    )
    failure = BehaviorScenario(
        scenario_id=f"scenario:{effect.effect_id}:failure",
        title=f"{trigger} records an external failure",
        feature=f"Preserve {trigger} failure behavior", priority="high",
        tags=base_tags + ["failure", "idempotency"],
        given=[f"the {trigger} event is valid", "the external effect is unavailable"],
        when=f"the {trigger} handler attempts delivery",
        then=["the failure is observable", "repeating the event does not silently duplicate the side effect"],
        evidence=evidence, side_effect_id=effect.effect_id,
    )
    return [normal, failure]


def _diagram(inventory: ProjectInventory, cir: CanonicalIR,
             effects: list[SideEffect]) -> list[DiagramArtifact]:
    tech = ", ".join(inventory.detected_technologies) or "web runtime"
    external = sorted({effect.external_effect for effect in effects if effect.external_effect})
    context_lines = ["flowchart LR", f"  User[User] --> App[{inventory.project_name}]", f"  App --> Runtime[{tech}]"]
    for index, item in enumerate(external):
        context_lines.append(f"  App --> External{index}[{item}]")
    container_lines = ["flowchart TD", f"  Source[Legacy source] --> App[{inventory.project_name}]"]
    for index, route in enumerate(cir.routes):
        container_lines.append(f"  App --> Route{index}[{route.pattern}]")
    for index, effect in enumerate(effects):
        container_lines.append(f"  App --> Effect{index}[{effect.trigger}]")
    data_lines = ["flowchart LR"]
    for index, entity in enumerate(cir.entities):
        data_lines.append(f"  Route{index}[Application behavior] --> Data{index}[{entity.name}]")
    if len(data_lines) == 1:
        data_lines.append("  Source[Observed source] --> Behavior[Observed behavior]")
    component_lines = ["flowchart TD"]
    for index, module in enumerate(cir.structural_nodes):
        if module.kind == "file":
            component_lines.append(f"  Module{index}[{module.label}] --> Responsibility{index}[Observed module behavior]")
    return [
        DiagramArtifact(artifact_id="diagram:c4-context", title="System context", diagram_type="c4-context", mermaid="\n".join(context_lines)),
        DiagramArtifact(artifact_id="diagram:c4-containers", title="Application containers and behaviors", diagram_type="c4-containers", mermaid="\n".join(container_lines)),
        DiagramArtifact(artifact_id="diagram:c4-components", title="Module components", diagram_type="c4-components", mermaid="\n".join(component_lines)),
        DiagramArtifact(artifact_id="diagram:data-flow", title="Observed data flow", diagram_type="data-flow", mermaid="\n".join(data_lines)),
    ]


def build_reverse_documentation(
    inventory: ProjectInventory,
    cir: CanonicalIR,
    wesley: WesleyAssessment,
    findings: list[AdapterFindings],
) -> ReverseDocumentation:
    """Build the deterministic Agent 2 baseline from bounded source evidence."""
    effects: list[SideEffect] = []
    for finding in findings:
        for raw in finding.side_effects or []:
            effects.append(SideEffect(**raw.__dict__))
    effects.sort(key=lambda item: item.effect_id)
    modules = []
    for node in cir.structural_nodes:
        if node.kind != "file":
            continue
        modules.append(ModuleDocumentation(
            module_id=node.node_id, name=node.label,
            responsibilities=["source module; semantic responsibilities require review"],
            source_paths=node.source_paths,
            evidence=[_link("cir", path, node_id=node.node_id) for path in node.source_paths],
        ))
    flows = [
        DataFlow(
            flow_id=f"flow:{entity.entity_id}", source="application behavior",
            destination=entity.name, operation=", ".join(entity.operations) or "observed access",
            evidence=[_link("cir", span.file, span.start_line, span.end_line, entity.entity_id) for span in entity.evidence_spans],
        )
        for entity in cir.entities
    ]
    scenarios = [scenario for effect in effects for scenario in _effect_scenarios(effect)]
    scenarios.extend(
        BehaviorScenario(
            scenario_id=f"scenario:{route.route_id}:route",
            title=f"Public route {route.pattern} renders its preserved presentation",
            feature="Preserve public routes", tags=["parity", "route"],
            given=["the route is requested"], when=f"the client requests {route.pattern}",
            then=["the route resolves", "its observed visible content is available"],
            evidence=[_link("cir", path, node_id=route.route_id) for path in route.source_paths],
        ) for route in cir.routes
    )
    gaps = list(wesley.limitations)
    if any(effect.kind == "webhook" for effect in effects):
        gaps.append("Webhook authentication, retry policy, and delivery ownership require human confirmation.")
    if effects:
        gaps.append("Side-effect parity is specified but not implemented by the presentation-only target profile.")
    product_plan = ProductPlan(
        purpose=f"Preserve the user-visible and event-driven behavior of {inventory.project_name}.",
        users=["public site visitor"],
        capabilities=list(dict.fromkeys(inventory.route_candidates + [effect.trigger for effect in effects])),
        workflows=[scenario.title for scenario in scenarios if scenario.priority in {"critical", "high"}],
        assumptions=["Static inspection is authoritative only for observed source structure."],
        open_questions=gaps,
    )
    return ReverseDocumentation(
        project_name=inventory.project_name,
        summary=f"Reverse documentation baseline for {inventory.project_name}.",
        modules=modules, data_flows=flows, side_effects=effects, scenarios=scenarios,
        diagrams=_diagram(inventory, cir, effects), product_plan=product_plan,
        confidence="low" if gaps else "medium", gaps=list(dict.fromkeys(gaps)),
        source_hash=cir.provenance.source_hash,
    )


def _scenario_markdown(scenario: BehaviorScenario) -> str:
    lines = [f"@{' @'.join(scenario.tags)}" if scenario.tags else "", f"Scenario: {scenario.title}"]
    lines.extend(f"  Given {item}" for item in scenario.given)
    lines.append(f"  When {scenario.when}")
    lines.extend(f"  Then {item}" for item in scenario.then)
    return "\n".join(line for line in lines if line) + "\n"


def render_reverse_artifacts(documentation: ReverseDocumentation) -> dict[str, str]:
    """Render deterministic Markdown and Gherkin artifacts for review/export."""
    architecture = ["# Architecture", "", documentation.summary, "", "## Modules", ""]
    architecture.extend(f"- `{module.name}`: {'; '.join(module.responsibilities)}" for module in documentation.modules)
    data_flow = ["# Data Flow", ""] + [
        f"- `{flow.source}` -> `{flow.destination}` ({flow.operation})" for flow in documentation.data_flows
    ]
    plan = documentation.product_plan
    product = ["# Inferred Product Plan", "", f"**Purpose:** {plan.purpose}", "", "## Capabilities", ""]
    product.extend(f"- {item}" for item in plan.capabilities)
    product.extend(["", "## Open Questions", ""])
    product.extend(f"- {item}" for item in plan.open_questions)
    specs = ["# Reverse Documentation", "", documentation.summary, "", "## Critical Behaviors", ""]
    specs.extend(f"- `{effect.trigger}` via `{effect.callback or 'registered callback'}` ({effect.source_path}:{effect.start_line})" for effect in documentation.side_effects)
    specs.extend(["", "## Scenarios", ""])
    specs.extend(f"- `{scenario.scenario_id}` {scenario.title}" for scenario in documentation.scenarios)
    artifacts = {
        "specs.md": "\n".join(specs) + "\n",
        "architecture.md": "\n".join(architecture) + "\n",
        "data-flow.md": "\n".join(data_flow) + "\n",
        "product-plan.md": "\n".join(product) + "\n",
    }
    artifacts.update({
        f"scenarios/{scenario.scenario_id.removeprefix('scenario:').replace(':', '-')}.feature":
        f"Feature: {scenario.feature}\n\n" + _scenario_markdown(scenario)
        for scenario in documentation.scenarios
    })
    artifacts.update({
        f"{diagram.diagram_type}.md": f"# {diagram.title}\n\n```mermaid\n{diagram.mermaid}\n```\n"
        for diagram in documentation.diagrams
    })
    return artifacts
