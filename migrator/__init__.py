"""Safe, lightweight source-adapter and migration helpers."""

from migrator.adapters import (
    AdapterFindings,
    AdapterMatch,
    AdapterRegistry,
    GraphEdge,
    GraphFindings,
    GraphNode,
    SourceAdapter,
    StructuralGraphAdapter,
    UniversalWebAdapter,
)
from migrator.archive import ProjectSnapshot, inspect_project
from migrator.cir import (
    AggregatedClaim,
    BehaviorClaim,
    BehaviorExtraction,
    BehaviorSample,
    BehavioralUnit,
    CanonicalIR,
    CanonicalAsset,
    CanonicalEntity,
    CanonicalRoute,
    EvidenceSpan,
    add_behavior_samples,
    aggregate_claims,
    compile_cir,
)
from migrator.github import GitHubClient, GitHubPushResult, GitHubSource, parse_repository_url
from migrator.service import AzureLampMigrator, AzureMigrationEngine, build_project_files, build_project_zip
from migrator.migration import build_migration_blueprint
from migrator.models import (
    CapabilityAssessment,
    MigrationBlueprint,
    MigrationUnit,
    MigrationWave,
    WesleyAssessment,
    WesleyComponent,
    WesleySignal,
)
from migrator.wesley import assess_project

LampProject = ProjectSnapshot
inspect_lamp_zip = inspect_project

__all__ = [
    "AzureLampMigrator",
    "AzureMigrationEngine",
    "AdapterFindings",
    "AdapterMatch",
    "AdapterRegistry",
    "AggregatedClaim",
    "BehaviorClaim",
    "BehaviorExtraction",
    "BehaviorSample",
    "BehavioralUnit",
    "CanonicalAsset",
    "CanonicalEntity",
    "CanonicalIR",
    "CanonicalRoute",
    "EvidenceSpan",
    "GitHubClient",
    "GitHubPushResult",
    "GitHubSource",
    "LampProject",
    "ProjectSnapshot",
    "GraphEdge",
    "GraphFindings",
    "GraphNode",
    "SourceAdapter",
    "StructuralGraphAdapter",
    "UniversalWebAdapter",
    "WesleyAssessment",
    "WesleyComponent",
    "WesleySignal",
    "assess_project",
    "CapabilityAssessment",
    "MigrationBlueprint",
    "MigrationUnit",
    "MigrationWave",
    "build_migration_blueprint",
    "build_project_zip",
    "build_project_files",
    "add_behavior_samples",
    "aggregate_claims",
    "compile_cir",
    "inspect_lamp_zip",
    "parse_repository_url",
]
