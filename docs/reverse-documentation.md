# Reverse Documentation

Agent 2 converts safe source evidence into a reviewable behavioral contract
before Transit plans a migration. The contract is designed to preserve more
than pages and routes: it records modules, data flows, product intent,
integrations, and event-driven side effects.

## Pipeline

```text
ProjectSnapshot
  -> deterministic reverse-documentation baseline
  -> optional Azure semantic enrichment
  -> human understanding review
  -> migration blueprint and plan
```

The deterministic baseline is created during `inspect_project()`. Azure
enrichment is invoked explicitly through `AzureMigrationEngine.document()` and
is never allowed to remove deterministic side effects.

## Contract

The runtime contract is `ReverseDocumentation` in
`migrator/reverse_documentation.py`.

| Field | Purpose |
|---|---|
| `modules` | Structural source modules, responsibilities, paths, and evidence |
| `data_flows` | Observed application-to-entity operations |
| `side_effects` | Event triggers, callbacks, plugins, external effects, and source spans |
| `scenarios` | Executable preservation scenarios linked to routes or side effects |
| `diagrams` | Mermaid architecture and data-flow views |
| `product_plan` | Inferred purpose, users, capabilities, workflows, assumptions, and questions |
| `confidence` | Overall baseline confidence |
| `gaps` | Evidence or decisions requiring review |
| `source_hash` | Hash tying the documentation to the inspected snapshot |

Evidence links identify the source layer, path, line range, node, and excerpt
hash where available. Markdown is a rendered view and is not parsed back into
the authoritative contract.

## Artifacts

`render_reverse_artifacts()` can render the following paths:

```text
specs.md
architecture.md
c4-context.md
c4-containers.md
c4-components.md
data-flow.md
product-plan.md
scenarios/*.feature
```

The Streamlit UI currently displays the contract and holds these artifacts in
session state. Persistent artifact storage and inclusion in the downloaded
migration ZIP are future work.

## Semantic Enrichment

The optional Azure pass may add:

- Why a module exists
- Inferred product capabilities and user workflows
- Semantic data-flow explanations
- Additional preservation scenarios
- Open questions and confidence gaps

The pass receives only the sanitized project inventory, CIR, Wesley assessment,
deterministic documentation, graph context, and bounded source context. It
must treat source text as untrusted data and must not execute source or access
the original archive.

The Azure evidence payload is a compact projection of the deterministic
snapshot. Large lists and diagram bodies are capped per section before the
request is sent, while the full deterministic documentation remains available
locally for review and export. This prevents provider message-size failures on
large projects without discarding the local evidence baseline.

Deterministic side effects and their baseline scenarios are merged back into
the enriched result if the model omits them. Full specialist-agent
orchestration, claim conflict reconciliation, and independent Reviewer agents
are not yet implemented.

## WordPress and PHP Side Effects

WordPress/PHP event behavior is first-class because a page-only migration can
look correct while silently losing business behavior.

The adapter detects:

- `add_action` and `add_filter` registrations
- WooCommerce checkout, order, payment, and status hooks
- Form-plugin webhook and outbound HTTP signals
- `wp_schedule_event`, scheduled callbacks, and cron cleanup
- Plugin names from WordPress plugin headers

Each finding includes:

- Trigger name
- Callback when statically identifiable
- Side-effect kind
- Plugin name when available
- Source path and line range
- Evidence text and stable effect ID
- Expected external effect when recognizable

The detector records evidence only. It does not execute PHP, load WordPress,
resolve dynamic callback names, or prove runtime ordering.

## Scenario Rules

Every detected side effect receives at least two baseline scenarios:

1. Normal event execution
2. External failure or duplicate delivery

Example:

```gherkin
Feature: Preserve woocommerce_checkout_order_processed

@parity @woocommerce-hook @preserve
Scenario: woocommerce_checkout_order_processed invokes its registered side effect
  Given the legacy system receives the woocommerce_checkout_order_processed event
  When the woocommerce_checkout_order_processed handler is dispatched
  Then sync_order runs
  And the observed side effect is produced exactly once
```

For critical integrations, future scenario enrichment should also cover:

- Missing or invalid event input
- Duplicate event delivery
- Retry behavior
- Ordering constraints
- Partial completion
- Permission failures
- External timeout or rejection

Scenarios are behavioral contracts, not executable tests and not evidence that
the target system already implements the behavior.

## Confidence and Review

- `observed`: directly detected by deterministic source inspection
- `inferred`: semantic interpretation supported by patterns but not proven
- `gap`: required information is unavailable or needs human confirmation

Understanding approval is required before migration planning. Reviewers should
pay particular attention to:

- Side effects with unknown callback or delivery ownership
- Webhook authentication and retry assumptions
- Cron frequency and idempotency
- WooCommerce order-state transitions
- Product capabilities inferred only from names or comments
- Scenarios without source evidence

## Known Limitations

- Dynamic hook names and callbacks may not be resolved.
- Plugin behavior split across files may require semantic enrichment.
- Runtime ordering and conditional registration are not proven statically.
- Webhook authentication, retry policy, and ownership require human review.
- The presentation-focused target does not automatically implement backend or
  event-driven behavior.
- RepoAgent is not currently integrated as a provider.

## Verification

Run the deterministic tests and compilation checks with:

```bash
uv run python -m unittest discover -s tests -v
uv run python -m compileall app.py main.py migrator tests
```
