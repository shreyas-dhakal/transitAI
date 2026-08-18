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
from migrator.github import GitHubClient, GitHubPushResult, GitHubSource, parse_repository_url
from migrator.service import AzureLampMigrator, AzureMigrationEngine, build_project_files, build_project_zip

LampProject = ProjectSnapshot
inspect_lamp_zip = inspect_project

__all__ = [
    "AzureLampMigrator",
    "AzureMigrationEngine",
    "AdapterFindings",
    "AdapterMatch",
    "AdapterRegistry",
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
    "build_project_zip",
    "build_project_files",
    "inspect_lamp_zip",
    "parse_repository_url",
]
