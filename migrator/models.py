"""Structured contracts shared by archive inspection, Azure OpenAI, and the UI."""

from pydantic import BaseModel, Field


class ProjectInventory(BaseModel):
    project_name: str
    adapter: str = "universal-web"
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
    skipped_ignored_files: list[str] = Field(default_factory=list)
    skipped_ignored_file_count: int = 0
    truncated: bool = False
    adapter_sources: list[str] = Field(default_factory=list)


class WesleySignal(BaseModel):
    name: str
    status: str
    severity: str = "info"
    value: str | None = None
    evidence: list[str] = Field(default_factory=list)


class WesleyComponent(BaseModel):
    component: str
    classification: str
    confidence: str
    reasons: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)


class WesleyAssessment(BaseModel):
    overall_classification: str
    confidence: str
    components: list[WesleyComponent] = Field(default_factory=list)
    signals: list[WesleySignal] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MigrationUnit(BaseModel):
    unit_id: str
    source_scope: str
    classification: str
    action: str
    target_scope: str
    dependencies: list[str] = Field(default_factory=list)
    preserved_behavior: list[str] = Field(default_factory=list)
    unsupported_behavior: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    validation_gates: list[str] = Field(default_factory=list)
    coexistence_required: bool = False


class CapabilityAssessment(BaseModel):
    capability: str
    status: str
    evidence: list[str] = Field(default_factory=list)


class MigrationWave(BaseModel):
    wave_id: str
    title: str
    unit_ids: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)


class MigrationBlueprint(BaseModel):
    strategy: str
    target_profile: str
    units: list[MigrationUnit] = Field(default_factory=list)
    capabilities: list[CapabilityAssessment] = Field(default_factory=list)
    waves: list[MigrationWave] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    approval_status: str = "pending"


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
    strategy: str = "strangler-migration"
    target_profile: str = "nextjs-app-router"
    migration_units: list[MigrationUnit] = Field(default_factory=list)
    capabilities: list[CapabilityAssessment] = Field(default_factory=list)
    migration_waves: list[MigrationWave] = Field(default_factory=list)
    approval_status: str = "pending"


class GeneratedFile(BaseModel):
    path: str
    content: str
    purpose: str


class GeneratedProject(BaseModel):
    files: list[GeneratedFile] = Field(min_length=3, max_length=60)
    migration_notes: list[str]
