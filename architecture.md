# Transit Architecture

Transit is a technology-neutral modernization pipeline. It does not translate
one language directly into another. It collects evidence from a legacy system,
represents that evidence in a canonical model, and generates a validated target
implementation.

```text
Legacy project
     |
     v
Source adapters
     |
     v
Canonical intermediate representation
     |
     v
Migration strategy + capability matrix
     |
     v
Target stack profile
     |
     v
Analysis and approved migration plan
     |
     v
Target generation
     |
     v
Target-specific validation
```

## 1. General Architecture

The system is divided into independent stages:

```text
Intake
  -> Evidence collection
  -> Canonical model
  -> Migration planning
  -> Human approval
  -> Target generation
  -> Validation
  -> Export
```

The intake boundary is responsible for archive limits, path safety, sensitive
file filtering, credential redaction, and bounded source context. No later
stage should bypass that boundary or access the original archive directly.

The core runtime consists of:

- `SourceAdapter`: interprets normalized legacy evidence.
- `ProjectSnapshot`: stores the validated inventory, source context, assets, and adapter findings.
- `MigrationPlan`: describes the proposed modernization.
- `TargetProfile`: describes the desired output stack and its rules.
- `Generator`: produces target source files from the approved plan.
- `Validator`: checks output using target-specific rules.

The stages should be deterministic where possible and independently retryable
in production.

## 2. Source Adapters

Source adapters collect evidence from legacy websites and applications. They
interpret source files but do not execute them, make model calls, or access
credentials.

The adapter layer is composed rather than limited to one framework adapter:

```text
Universal web adapter
       +
Structural graph adapter
       +
Optional framework recognizer
       +
Optional deployment recognizer
       |
       v
Merged adapter findings
```

Typical evidence includes:

- Languages and technologies
- Routes and templates
- Components and symbols
- Imports and file dependencies
- Forms and user inputs
- Database tables and query signals
- Authentication and session signals
- External integrations
- Uploads, email, and background behavior
- Static assets
- Build and deployment configuration

The `AdapterRegistry` selects and composes adapters using deterministic
evidence such as manifests, file extensions, and directory shape. Explicit
adapter selection remains available for known internal platforms.

## 3. Canonical Intermediate Representation

The canonical intermediate representation, or CIR, describes application
behavior without depending on PHP, Rails, Django, Next.js, or another specific
technology.

It is the contract between source analysis and target generation.

Example route representation:

```yaml
route: /products/:id
purpose: Product detail
inputs:
  - product ID
data_dependencies:
  - products table
behavior: server-rendered page
auth: public
assets:
  - product images
```

The CIR should represent concepts such as:

### Routes

- Source path or endpoint
- Canonical route pattern
- HTTP methods
- Inputs and outputs
- Rendering mode
- Authentication requirements

### Data Entities

- Entity name
- Fields and types
- Relationships
- Read/write operations
- Migration confidence

### Behaviors

- Forms
- Authentication
- Sessions
- Uploads
- Email delivery
- Payments
- Search
- Background jobs
- External API calls

### Assets and Content

- Asset path
- Usage locations
- Content type
- Whether it is shared, generated, or user-provided

The CIR must preserve uncertainty and provenance. A guessed route should not
look identical to a route confirmed by configuration or runtime evidence.

## 4. Target Stack Profiles

A target stack profile defines how the CIR becomes a working project. It is
more than a framework name.

```yaml
name: nextjs-app-router
language: typescript
framework: next.js
ui_library: react
rendering: server-components-by-default
scaffold: nextjs-typescript
allowed_roots:
  - app
  - components
  - content
  - lib
validation:
  - typecheck
  - production-build
```

A profile owns:

- Project scaffold
- Routing conventions
- Component conventions
- Rendering model
- Data-access conventions
- Authentication integration points
- Dependency allowlist
- File and import rules
- Build and test commands
- Deployment assumptions
- Security validators

Potential profiles include:

- Next.js and TypeScript
- Nuxt and Vue
- React and Vite
- SvelteKit
- Astro
- Django
- Rails
- Laravel
- FastAPI
- Spring Boot
- Headless CMS output

Source adapters and target profiles must remain independent. Adding Rails as a
source should not require rewriting the Next.js generator.

## 5. Migration Strategies

Transit should support multiple migration strategies because a full rewrite is
not always the safest or most valuable option.

### Visual Rebuild

Preserve visible content, navigation, layout, styles, and assets while
recreating the presentation layer in the target stack.

### Replatform

Move existing behavior to a new runtime with minimal product changes.

### Backend Replacement

Preserve the user experience while replacing legacy APIs, databases, or
services.

### Strangler Migration

Migrate selected routes or bounded domains while the legacy system continues
serving the remaining application.

### Static Extraction

Convert pages with no meaningful runtime behavior into static pages or content
files.

### CMS Migration

Extract content and map it into a headless or traditional CMS.

### Analysis Only

Produce an application map, risks, and migration backlog without generating a
replacement project.

The selected strategy should be based on evidence, risk, business priority,
and the target profile's capabilities.

## 6. Capability Matrix

The capability matrix prevents the product from promising unsupported behavior.
It describes what each source-target combination can preserve automatically.

| Capability | PHP to Next.js | Rails to Next.js | WordPress to Headless CMS |
|---|---:|---:|---:|
| Routes | Supported | Beta | Supported |
| Templates and layout | Supported | Beta | Supported |
| Static assets | Supported | Supported | Supported |
| Content extraction | Supported | Beta | Supported |
| Database schema analysis | Partial | Partial | Partial |
| Database behavior migration | Manual | Manual | Manual |
| Authentication | Manual | Manual | Manual |
| Forms and email | Manual | Manual | Manual |
| Payments | Manual | Manual | Manual |
| Background jobs | Not generated | Not generated | Not generated |
| Build validation | Target-dependent | Target-dependent | Target-dependent |

Each capability should include a status:

- `supported`: deterministic and validated
- `partial`: generated with review requirements
- `manual`: identified but not automatically implemented
- `unsupported`: outside the profile boundary

The migration plan should include the capability status and evidence behind it.

## 7. Separate Analysis from Generation

Analysis and generation must be separate stages with separate contracts.

```text
Source evidence
     |
     v
Analysis
     |
     v
Canonical model + risks + assumptions
     |
     v
Human review and approval
     |
     v
Generation
     |
     v
Target project
```

### Analysis Responsibilities

- Interpret source evidence
- Build the canonical model
- Map routes and data entities
- Identify preserved behavior
- Identify unsupported behavior
- Select a migration strategy
- Record risks, confidence, and assumptions

### Generation Responsibilities

- Consume only the approved plan and sanitized evidence
- Follow the selected target profile
- Generate target source files
- Avoid inventing backend behavior
- Produce migration notes for unresolved work

Generation must not decide that a behavior is safe merely because the model
described it. Every generated artifact must pass deterministic validation.

## 8. Target-Specific Validation

Validation is both generic and target-specific.

### Generic Validation

- Safe relative paths
- Allowed file extensions
- No duplicate files
- No secrets
- No unsafe APIs
- No undeclared dependencies
- Required output files present
- Source-to-target traceability

### Target Validation

For Next.js:

- TypeScript typecheck
- Production build
- Route checks
- Asset checks
- Import and dependency validation

For Django:

- Python compilation
- Migration checks
- URL resolution
- Application checks
- Test suite execution

For Rails:

- Ruby syntax validation
- Route checks
- Database migration checks
- Test suite execution

For frontend targets generally:

- Screenshot comparison
- Accessibility checks
- Responsive layout checks
- Browser smoke tests

Builds and browser validation must run in isolated workers with no access to
application secrets. The migration service should never execute uploaded source
or generated code in the control-plane process.

## Design Invariants

- Source intake is untrusted and bounded.
- Adapters interpret evidence only.
- The CIR is technology-neutral and preserves uncertainty.
- Source adapters and target profiles are independently extensible.
- Analysis is reviewable before generation.
- Generated code is untrusted until validated.
- Unsupported behavior is reported, not silently invented.
- Every target profile defines its own validation contract.
