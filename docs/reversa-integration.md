# Reversa Integration

Transit uses Reversa as a source of reverse-documentation methodology, agent
roles, confidence rules, artifact templates, and migration knowledge. Transit
does not delegate its security boundary or canonical data model to Reversa.

## Current Status

Transit currently has the deterministic intake, adapter, CIR, Wesley, and
migration-blueprint phases. The typed `EvidenceRef`, `Claim`, `AgentResult`,
and `LegacySpecification` contracts are implemented in
`migrator/specification.py`. The Agent 2 reverse-documentation contracts and
deterministic artifact renderer are implemented in
`migrator/reverse_documentation.py`. Every snapshot now gets a reverse-documentation
model that can render architecture, data-flow, product-plan, and executable
scenario artifacts, including
first-class WordPress/PHP plugin hooks, WooCommerce events, form webhooks,
and WP-Cron side effects. `AzureMigrationEngine.document()` optionally adds
semantic explanations and inferred product behavior while preserving the
deterministic baseline. Full specialist-agent orchestration and claim
reconciliation are the next layer; deterministic source facts remain
authoritative.

## Why They Are Combined

Transit is strong at deterministic evidence:

- Safe archive and GitHub intake
- Secret filtering and bounded source context
- Source adapters
- Structural dependency graph
- Canonical Intermediate Representation (CIR)
- Wesley Spectrum classification
- Migration capability boundaries
- Generated-code validation

Reversa is strong at interpretation:

- Module-level code archaeology
- Implicit business rules
- State machines and permissions
- Architecture and integration synthesis
- Operational, traceable specifications
- Cross-agent review and gap discovery
- Migration strategy and parity thinking

The combined product uses deterministic Transit evidence as the foundation and
Reversa-style agents as a controlled interpretation layer.

## Combined Pipeline

```text
Source intake
  -> Transit adapters
  -> Transit CIR
  -> Wesley Spectrum
  -> Agent 2 deterministic reverse-documentation baseline
  -> Optional Azure semantic enrichment
  -> Understanding review
  -> Reversa-style discovery agents (planned)
  -> Claim reconciliation (planned)
  -> LegacySpecification / reverse artifacts
  -> MigrationBlueprint
  -> Azure MigrationPlan
  -> Human approval
  -> Target generation
  -> Validation and export
```

The phases are modular. Each phase has a contract, an artifact, and an
independent test boundary.

The running product currently implements the first two Agent 2 layers: safe
deterministic extraction and one optional Azure structured-output enrichment
call. The Reversa roles below describe the intended specialist pipeline and
are not currently invoked as independent agents.

## Reversa Roles

### Scout

Maps the project surface:

- Languages and frameworks
- Entry points
- Modules
- Configuration
- Dependencies
- Test locations
- Database surface

Transit adapters already provide much of this information. The integrated
Scout should enrich adapter findings, not replace them.

### Archaeologist

Analyzes one module or bounded context at a time:

- Control flow
- Algorithms and transformations
- Data structures
- Validation logic
- Error handling
- Configuration and feature flags

The Archaeologist receives graph-ranked source context and links every claim to
CIR nodes or source spans.

### Detective

Interprets behavior after the Archaeologist has cataloged it:

- Implicit business rules
- State transitions
- Permissions
- Retroactive architecture decisions
- TODO and FIXME intent
- Git history when repository metadata is available

Detective conclusions are normally `inferred` unless directly corroborated by
deterministic evidence.

### Architect

Produces structural understanding:

- System boundaries
- C4 context, container, and component views
- Data relationships and ERD
- External integrations
- Technical debt
- Impact relationships between components

The Architect should consume the CIR graph and entities rather than rebuild a
second incompatible graph.

### Writer

Converts reconciled findings into operational specifications. The Writer does
not independently decide whether a claim is true. It renders the reconciled
`LegacySpecification` into `specs.md` and supporting artifacts.

### Reviewer

Cross-checks:

- Agent disagreements
- Claims without citations
- Missing modules or routes
- Business rules that contradict observed behavior
- Unsupported migration assumptions
- Low-confidence areas requiring human review

### Agent 2 Reverse-Documentation Outputs

Agent 2 produces a behavior contract before migration planning:

- Architecture diagrams: C4 context, containers, components, and data flow
- Module map: source modules, responsibilities, dependencies, and evidence
- Inferred product plan: purpose, users, capabilities, workflows, assumptions, and questions
- Executable scenarios: Gherkin-style preservation scenarios for routes and event behavior
- Side-effect register: callbacks, triggers, plugins, external effects, and source spans

#### WordPress/PHP Side Effects

WordPress event behavior is treated as first-class functionality, not as an
implementation detail. The deterministic adapter records:

- `add_action` and `add_filter` registrations
- WooCommerce order, checkout, payment, and status hooks
- Form-plugin webhook and outbound HTTP signals
- `wp_schedule_event`, scheduled callbacks, and cron cleanup

Each detected side effect produces scenarios for normal execution and external
failure or duplicate delivery. Scenarios are preservation contracts, not proof
that the target implementation exists. The presentation-only Next.js profile
continues to classify these behaviors as manual engineering work.

## Evidence Model

All agent results are normalized into claims:

```text
Claim
  id
  category
  statement
  status: confirmed | inferred | contested | gap
  confidence: high | medium | low
  evidence_refs[]
  supporting_agents[]
  contradicting_agents[]
  human_review_required
```

Evidence references use stable source identifiers:

```text
EvidenceRef
  source: adapter | cir | wesley | agent | git
  file
  start_line
  end_line
  node_id
  excerpt_hash
```

Rules:

- Deterministic adapter and CIR facts outrank agent guesses.
- Agreement between agents without source evidence remains `inferred`.
- Conflicting claims remain `contested`.
- Unavailable evidence becomes `gap`.
- Agent output cannot remove a Wesley security blocker.
- Every migration unit must link to at least one specification claim.

## Canonical Specification

`LegacySpecification` is the source of truth after reconciliation. Its initial
typed contract is implemented and should contain:

- Project summary
- System boundaries
- Runtime and deployment architecture
- Modules and responsibilities
- Routes and workflows
- Business rules
- State machines
- Permissions
- Entities and data flows
- External integrations
- Dependencies and technical debt
- Security findings
- Unknowns and contested claims
- Confidence report
- Code-to-spec traceability

`specs.md` is generated from this model. It is an output view, not an input
contract.

## Artifact Layout

Transit uses its own artifact layout to avoid coupling runtime contracts to
Reversa's installer conventions:

```text
artifacts/understanding/
  specs.md
  inventory.md
  code-analysis.md
  domain.md
  architecture.md
  c4-context.md
  c4-containers.md
  c4-components.md
  data-flow.md
  product-plan.md
  dependencies.md
  confidence-report.md
  gaps.md
  scenarios/*.feature
  traceability/code-spec-matrix.md

artifacts/migration/
  migration-brief.md
  paradigm-decision.md
  migration-strategy.md
  target-architecture.md
  target-domain-model.md
  target-data-model.md
  data-migration-plan.md
  parity-specs.md
  cutover-plan.md
  risk-register.md
  ambiguity-log.md
  handoff.md
```

An optional exporter can produce Reversa-compatible `_reversa_sdd/` artifacts
for users who want to continue using Reversa's external agent workflows.

## Reversa Source Disposition

The cloned Reversa repository is MIT licensed. Preserve its copyright and
license notice for adapted substantial portions.

### Retain or adapt

```text
agents/reversa-scout/
agents/reversa-archaeologist/
agents/reversa-detective/
agents/reversa-architect/
agents/reversa-writer/
agents/reversa-reviewer/
agents/reversa-data-master/
agents/reversa-design-system/
agents/reversa-extract-soul/

agents/reversa-migrate/
agents/reversa-paradigm-advisor/
agents/reversa-curator/
agents/reversa-strategist/
agents/reversa-designer/
agents/reversa-screen-translator/
agents/reversa-inspector/

templates/migration/catalogs/
templates/migration/artifacts/
```

These are methodology inputs. They should be adapted into Transit analyzer
prompts, structured output schemas, and deterministic renderers.

### Do not include in the Transit runtime

```text
bin/
lib/installer/
templates/engines/
templates/documentation/
```

These implement Reversa's standalone npm installer, external-engine setup, and
documentation viewer. They are not needed by the Transit service.

The standalone Reversa forward, greenfield, pricing, and debugger workflows
remain optional future integrations. They should not be copied into the core
migration pipeline until their contracts are explicitly needed.

## Execution Model

Reversa's original workflow is driven by skills installed into an external AI
coding agent. Transit cannot depend on that host being available. The Transit
implementation therefore uses an analyzer protocol:

```text
LegacyAnalyzer
  analyze(EvidencePack) -> AnalyzerResult
```

Planned implementations include:

- `DeterministicAnalyzer`: adapters, CIR, and Wesley evidence
- `ScoutAnalyzer`
- `ArchaeologistAnalyzer`
- `DetectiveAnalyzer`
- `ArchitectAnalyzer`
- `WriterAnalyzer`
- `ReviewerAnalyzer`

Each analyzer may use Azure structured output, but it must return the same
typed claim contract. Agents can run sequentially where later agents depend on
earlier artifacts and in parallel where their evidence scopes are independent.

## Security Boundary

Reversa agents operate on sanitized Transit evidence only. They must not:

- Read raw uploaded archives
- Execute legacy code
- Execute generated code
- Write outside the configured artifact directory
- Access application credentials
- Follow instructions found inside source files
- Treat source comments as agent instructions

The source remains untrusted data throughout the understanding phase.

## Human Gates

The combined workflow has two review points:

1. **Understanding review**
   - Review `specs.md`
   - Resolve contested claims
   - Confirm gaps and business rules
   - Approve the specification baseline

2. **Migration review**
   - Review strategy and migration waves
   - Review capability limitations
   - Approve coexistence and cutover assumptions
   - Approve the `MigrationPlan`

Generation is blocked until the migration plan is approved.

## Implementation Sequence

1. Port Reversa discovery prompts and confidence rules into Transit analyzer modules.
2. Add typed claim, evidence, analyzer-result, and specification contracts.
3. Build the reconciliation phase against adapter, CIR, and Wesley evidence.
4. Render `specs.md` and supporting understanding artifacts deterministically.
5. Update migration planning to consume `LegacySpecification`.
6. Add the understanding review stage to the Streamlit UI.
7. Add tests for evidence precedence, conflicts, gaps, and traceability.
8. Add optional Reversa-compatible artifact export.
9. Remove only the vendored Reversa files that are no longer needed after the
   adapted implementation is covered by tests.
