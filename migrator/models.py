"""Structured contracts shared by archive inspection, Azure OpenAI, and the UI."""

from pydantic import BaseModel, Field


class ProjectInventory(BaseModel):
    project_name: str
    file_count: int
    source_file_count: int
    asset_count: int
    source_files: list[str]
    asset_urls: list[str]
    detected_technologies: list[str]
    route_candidates: list[str]
    database_tables: list[str]
    behavior_signals: list[str]
    skipped_sensitive_files: list[str]
    truncated: bool = False


class RoutePlan(BaseModel):
    source: str
    target: str
    purpose: str


class MigrationPlan(BaseModel):
    project_summary: str
    routes: list[RoutePlan]
    shared_components: list[str]
    content_strategy: str
    styling_strategy: str
    data_entities: list[str]
    preserved_behaviors: list[str]
    unsupported_behaviors: list[str]
    risks: list[str]
    assumptions: list[str]


class GeneratedFile(BaseModel):
    path: str
    content: str
    purpose: str


class GeneratedProject(BaseModel):
    files: list[GeneratedFile] = Field(min_length=3, max_length=60)
    migration_notes: list[str]
