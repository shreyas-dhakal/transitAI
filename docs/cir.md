# Layer 1: Canonical Intermediate Representation

Transit Layer 1 is the Canonical Intermediate Representation (CIR). It is the
contract between Layer 0 source evidence and migration planning. Layer 0 remains
the authority for bounded intake, sanitization, source inventory, adapter
findings, and structural evidence.

## Scope

Layer 1 combines deterministic structural normalization with sampled behavioral
claims. It must preserve uncertainty instead of flattening an interpretation into
an apparently certain fact.

```text
Layer 0 snapshot
    -> deterministic Layer 1 normalization
    -> sampled behavioral claims
    -> deterministic aggregation
    -> CanonicalIR artifact
```

The internal Layer 1 decomposition is:

| Internal layer | Responsibility | Current status |
|---|---|---|
| Source-anchored CST | Retain source identity and evidence spans | Source/file anchoring available; parser-specific CST is future work |
| Normalized AST | Stable technology-neutral structural nodes | Initial file and symbol nodes |
| Symbol and type graph | Relationships between structural nodes | Existing adapter graph is normalized into CIR edges |
| Control/data flow | Branch, call, and data-flow relationships | Contract is present; unavailable evidence is explicit |
| Behavioral specification | Sampled atomic claims and deterministic aggregation | Implemented with structured sample contracts |
| Runtime observation | Captured request/response behavior | Optional contract; not produced by the non-executing inspector |

## Determinism Boundary

Sampling is the only nondeterministic operation. The following are deterministic:

- Unit and claim identifiers.
- Structural normalization.
- Claim normalization and aggregation.
- Confidence tier thresholds.
- Provenance and sample-set hashes.
- Serialization of the final CIR.

Raw samples are retained in each behavioral unit. Re-aggregating the same samples
with the same aggregation version must produce the same result.

## Confidence

Agreement is evidence, not truth. A `confirmed` claim requires high sample support
and structural corroboration. Claims without corroborating structural or runtime
evidence remain `likely` even when samples agree. Disagreement is retained as
`contested`; unsupported or weakly supported claims are `gap`.

The initial aggregation uses exact structured claim keys. Embedding clustering is
deliberately deferred until a versioned, deterministic embedding dependency is
available.

## Initial Implementation

`migrator.cir` currently provides:

- `compile_cir()` for deterministic snapshot normalization.
- Stable route, entity, asset, structural-node, and edge identifiers.
- Source line spans for the baseline behavior signals.
- `BehaviorSample` and `BehaviorExtraction` contracts.
- `aggregate_claims()` for exact structured aggregation.
- `AzureMigrationEngine.sample_behavior()` for repeated structured extraction.
- `add_behavior_samples()` for immutable CIR updates.

The non-executing intake cannot provide runtime observations. It also does not
pretend that the existing lexical graph is a full parser-derived CST, AST, or
control/data-flow graph. Those fields remain extensible and explicitly bounded by
the evidence available from Layer 0.

## Product Boundary

The CIR compiler consumes only a sanitized `ProjectSnapshot`. It never reads the
archive, executes source, or calls external services. Azure extraction is an
optional later step that produces `BehaviorSample` values. The migration planner
can consume the CIR while raw Layer 0 evidence remains available for review.

## Reproducibility

Every CIR records:

- `source_hash`
- `extractor_version`
- `aggregation_version`
- `sample_set_hash`
- schema version

Source changes create a new source hash. Re-sampling unchanged source creates a
new sample-set hash and should be treated as a stability check.

## Planned Extensions

- Replace lexical structural extraction with resource-bounded CST/AST parsers.
- Add richer symbol/type and control/data-flow evidence.
- Add isolated runtime observation workers without changing the CIR contract.
- Add risk-based sampling budgets and cross-model agreement metadata.
