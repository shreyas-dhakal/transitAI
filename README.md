# Transit

A lightweight legacy web-project migration prototype powered by Azure OpenAI. Connect a GitHub repository or upload a project ZIP, review a structured migration plan, and download a guarded Next.js App Router starter.

Transit uses a universal web source adapter rather than coupling archive intake to one
language or framework. The adapter produces deterministic evidence for routes, assets,
technologies, data access, and behavior. Framework-specific recognizers can enrich that
evidence later without changing the migration pipeline.

## What It Does

1. Connects to a GitHub repository through a GitHub token or App installation credentials, or accepts a bounded ZIP upload.
2. Pins the GitHub branch or tag to an exact commit SHA and downloads GitHub's source archive for that commit.
3. Validates ZIP paths, file counts, and compressed/uncompressed size limits.
4. Reads bounded source files as text without extracting or executing the project.
5. Omits sensitive filenames and redacts common inline credential assignments before model calls.
6. Inventories likely routes, assets, database tables, and server-side behaviors locally.
7. Classifies the source into the Wesley Spectrum (`Retain`, `Replace`, `Evolve`, `Reengineer`, `Migrate`, or `Coexist`) using deterministic static signals.
8. Uses Azure OpenAI structured output to produce a migration plan informed by that classification.
9. Uses a second structured call to generate presentation-focused Next.js files.
10. Rejects unsafe paths, API routes, unsupported imports, dangerous APIs, and incomplete output.
11. Packages deterministic configuration, generated source, copied assets, and a migration report.
12. For GitHub sources, creates a new branch with one migration commit in the same repository.

Migration planning is modular and produces a deterministic roadmap before
generation: strategy, target profile, migration units, capability statuses,
ordered waves, validation gates, and approval state. Azure enriches that
roadmap but does not choose around Wesley classifications or unsupported
capabilities.

The MVP deliberately does not recreate authentication, database access, email delivery, uploads, or arbitrary PHP behavior. It reports those as manual migration work and never executes uploaded or generated code.

## Setup

```bash
uv sync
cp .env.example .env
```

Configure these values in `.env`:

```text
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_DEPLOYMENT=your-deployment-name

# Local GitHub access. Use a fine-grained token with Contents read/write for branch export.
GITHUB_TOKEN=

# Production GitHub App installation access.
GITHUB_APP_ID=
GITHUB_INSTALLATION_ID=
GITHUB_PRIVATE_KEY=""
```

The deployment value is your Azure deployment identifier, not necessarily the underlying model name.

## Run

```bash
uv run streamlit run app.py
```

Open the URL printed by Streamlit. The preferred source is **GitHub repository**. Paste a repository URL such as `https://github.com/acme/legacy-site`, or a branch URL such as `https://github.com/acme/legacy-site/tree/staging`. Transit resolves the ref to a commit SHA, downloads the source archive, and passes it through the same safe inspector used for ZIP uploads.

For local testing with the included fixture:

```bash
zip -r lamp-site.zip examples/lamp-site
```

Select **ZIP upload**, upload `lamp-site.zip`, run analysis, review the plan, and generate the Next.js ZIP.

### GitHub Access

For local development, set `GITHUB_TOKEN` to a fine-grained token with `Contents: Read and write` access to the target repository. Transit never displays or sends this token to Azure OpenAI.

For hosted production use, create a GitHub App with the minimum permissions:

| Permission | Access |
|---|---|
| Repository metadata | Read |
| Repository contents | Read and write |
| Pull requests | None initially |
| Actions | None |
| Administration | None |

Set `GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID`, and `GITHUB_PRIVATE_KEY`. Transit creates a short-lived installation token, resolves the selected ref to a SHA, downloads the archive for that SHA, and can create a new migration branch with one commit. It does not clone, run hooks, install dependencies, or execute repository code.

The current UI assumes the GitHub App has already been installed and its installation ID is configured. OAuth installation and repository selection are the next control-plane layer for a multi-tenant hosted product.

## Tests

The tests use a fake structured-output model and do not consume Azure tokens:

```bash
uv run python -m unittest discover -s tests -v
uv run python -m compileall app.py main.py migrator tests
```

## Current Boundary

- Input: GitHub repository ref or one ZIP up to 15 MB compressed and 40 MB uncompressed
- Source: common web-project files including PHP, HTML, CSS, JavaScript, TypeScript, SQL, and common web assets
- Output: Next.js App Router, React 19, TypeScript, content in a ZIP or a new GitHub branch
- LLM: Azure OpenAI through `AzureChatOpenAI`
- Safety: no repository cloning, source execution, generated execution, or arbitrary dependencies

## System Architecture

### 1. Architecture Goals

Transit is designed as an evidence-driven migration pipeline rather than an unconstrained code-generation agent.

The system must:

- Convert small LAMP marketing websites into maintainable Next.js projects.
- Preserve visible content, routes, navigation, styles, and static assets where possible.
- Identify server-side behavior that requires manual engineering.
- Keep uploaded source code and generated code outside the execution path.
- Produce reproducible, reviewable output.
- Fail closed when input, model output, or generated code violates safety rules.

### 2. Scope And Non-Goals

#### Supported in the MVP

- PHP, HTML, CSS, JavaScript, and SQL source files.
- Common static assets such as images, fonts, SVGs, and icons.
- Small ZIP uploads from a trusted user.
- Next.js App Router with TypeScript and React Server Components.
- Content stored as files in the generated Git project.
- Azure OpenAI structured analysis and code generation.

#### Not automatically migrated

- Authentication and authorization.
- PHP sessions.
- Database reads and writes.
- Email delivery.
- File uploads.
- Payment flows.
- Admin dashboards.
- Arbitrary PHP execution.
- User-generated content.
- Third-party backend integrations.

These behaviors are detected and reported in `MIGRATION.md`; they are never invented or silently replaced.

### 3. High-Level Architecture

```text
                         ┌────────────────────────┐
                         │ Streamlit Control UI   │
                         │ Connect / Review / ZIP│
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │ Archive Intake Layer   │
                         │ Limits / Paths / MIME  │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                          │ Intake + Adapter Layer│
                          │ Limits / Redaction    │
                          │ Routes / Graph / SQL  │
                         └────────────┬───────────┘
                                      │
                           ProjectInventory +
                           bounded source context
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │ Azure OpenAI Planner    │
                         │ Structured MigrationPlan│
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │ Azure OpenAI Generator  │
                         │ Structured source files │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │ Generated Output Guard  │
                         │ Paths / Imports / APIs  │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                          │ Deterministic Packager  │
                          │ Next.js scaffold + ZIP  │
                         └────────────────────────┘
```

The current implementation is a modular monolith. The UI, inspector, Azure client, validator, and packager run in one Python process. The module boundaries are intentionally explicit so long-running production jobs can later be moved to workers without redesigning the migration contracts.

### 4. Repository Components

```text
app.py                     Streamlit application and review flow
main.py                    CLI entrypoint and developer guidance
migrator/models.py         Pydantic data contracts
migrator/archive.py        Safe ZIP intake and snapshot assembly
migrator/adapters.py       Registry, composition, evidence, and graph findings
migrator/cir.py            Canonical Intermediate Representation
migrator/wesley.py         Deterministic Wesley Spectrum assessment
migrator/migration.py      Modular migration blueprint and capability planning
migrator/service.py        Azure calls, generated-code validation, packaging
examples/lamp-site/        Small PHP fixture for manual testing
sourcebot/                 Existing local Sourcebot integration files
reversa-integration.md     Reversa methodology and integration contract
```

Responsibilities are separated as follows:

| Component | Responsibility | Must not do |
|---|---|---|
| `app.py` | Collect GitHub or ZIP input, show inventory and plan, trigger stages, download output | Inspect or execute PHP directly |
| `archive.py` | Validate ZIPs, sanitize source text, assemble snapshots, copy assets | Execute source or make LLM calls |
| `adapters.py` | Detect, compose, and interpret normalized source evidence | Read raw archives or execute source |
| `models.py` | Define validated inventory, plan, and generated-file contracts | Contain business logic |
| `service.py` | Call Azure OpenAI, validate output, build the generated ZIP | Execute generated code |
| `tests/` | Verify security boundary and packaging behavior | Require Azure credentials |

### 5. Migration Lifecycle

```text
UPLOAD
  │
  ▼
VALIDATE_ARCHIVE
  │
  ▼
INSPECT_SOURCE
  │
  ▼
REVIEW_INVENTORY
  │
  ▼
PLAN_WITH_AZURE
  │
  ▼
REVIEW_PLAN
  │
  ▼
GENERATE_WITH_AZURE
  │
  ▼
VALIDATE_GENERATED_FILES
  │
  ▼
PACKAGE_PROJECT
  │
  ▼
DOWNLOAD_FOR_HUMAN_REVIEW
  │
  ▼
CREATE_NEW_GITHUB_BRANCH (GitHub source only)
```

Each stage has a different authority:

- Deterministic inspection is authoritative for file names, file sizes, asset availability, likely routes, and detected patterns.
- The migration plan is an AI-assisted interpretation of the evidence.
- Generated source is a proposal and must pass deterministic validation.
- Backend behavior is never inferred as implemented merely because the model describes it.

### 6. Input And Archive Boundary

The ZIP is an untrusted input boundary. Transit processes it in memory and does not extract it to the application filesystem.

Current limits:

- 15 MB compressed archive limit.
- 40 MB total uncompressed member limit.
- 800 file limit.
- 300 KB per source-file context limit.
- 120,000-character total model-context limit.
- 5 MB per copied asset limit.
- Encrypted ZIP members are rejected.
- Absolute paths, drive-qualified paths, empty path segments, `.` segments, and `..` traversal are rejected.
- Duplicate paths after common-root normalization are rejected.

Sensitive files are omitted before model context construction. The current deny list includes `.env`, credential files, private keys, database configuration files, WordPress configuration, and files under secrets or credentials directories. Common inline values assigned to passwords, API keys, tokens, and database passwords are redacted.

This filtering is defense in depth, not a guarantee that secrets cannot exist in arbitrary source text. Production deployments should add secret scanning and customer-side data retention controls.

### 7. Deterministic Source Inspection

`migrator/archive.py` enforces the intake boundary. `migrator/adapters.py` interprets normalized evidence without executing source.

The inspector currently identifies:

- Source file inventory.
- Static asset inventory.
- Page and template route candidates.
- Optional file and symbol dependency graph findings.
- Common frameworks and libraries such as PHP, MySQL, WordPress, jQuery, Bootstrap, and Apache.
- SQL `CREATE TABLE` names.
- HTML forms.
- Session usage.
- Database queries.
- Email delivery calls.
- File upload signals.
- Server-side includes.
- AJAX usage.

The inspector also creates a bounded source context ordered approximately as:

1. PHP and PHTML.
2. HTML.
3. CSS.
4. JavaScript.
5. SQL and other text files.

The context includes file delimiters so the model can distinguish evidence from instructions contained inside source files.

### 8. Azure OpenAI Integration

Transit uses two separate structured-output calls.

#### Planning call

Input:

- `ProjectInventory` JSON.
- Redacted and bounded source context.
- System instructions describing the supported Next.js target.

Output:

- `MigrationPlan`.
- Route mappings.
- Shared component suggestions.
- Content and styling strategy.
- Preserved behaviors.
- Unsupported behaviors.
- Risks and assumptions.

#### Generation call

Input:

- Approved `MigrationPlan`.
- Available asset URLs.
- The same bounded source evidence.

Output:

- `GeneratedProject`.
- A list of source files with paths, contents, and purposes.
- Migration notes.

The model is not allowed to determine whether a build succeeded, execute commands, access the filesystem, access credentials, or create backend behavior. Azure output is treated as untrusted data until it passes local validation.

### 9. Prompt-Injection Boundary

Legacy source files can contain comments, strings, markup, or documentation that attempts to influence the model. The system treats all uploaded source as data.

Controls:

- Source is placed after system instructions in the user message.
- Prompts explicitly instruct the model not to follow source-file instructions.
- Source is bounded and delimited by file markers.
- Sensitive files are excluded before the model call.
- The model cannot invoke tools in this application.
- Structured Pydantic output is required.
- Generated output is validated independently of the model.

This does not eliminate prompt injection risk. A production system should log model versions and prompts, add adversarial fixtures, use Azure content-safety controls where appropriate, and require human approval before export or deployment.

### 10. Generated Project Contract

The deterministic scaffold contains:

```text
package.json
tsconfig.json
next-env.d.ts
next.config.ts
.gitignore
README.md
MIGRATION.md
```

The model may generate files only under:

```text
app/
components/
content/
lib/
```

Required generated files:

```text
app/layout.tsx
app/page.tsx
app/globals.css
```

The generated project is intended to use:

- Next.js App Router.
- TypeScript.
- React Server Components by default.
- Client Components only when interaction requires them.
- Semantic HTML.
- Relative or `@/*` internal imports.
- Copied assets under `/legacy/...`.
- Content files that can be edited in Git.

### 11. Generated-Code Validation

Before packaging, Transit validates every model-generated file:

- Path must be relative and normalized.
- Root directory must be allowlisted.
- Extension must be allowlisted.
- Duplicate paths are rejected.
- API routes are rejected.
- Required files must exist.
- External package imports are rejected.
- `dangerouslySetInnerHTML`, `eval`, `new Function`, `child_process`, and `document.write` are rejected.
- Per-file and total generated-source size limits are enforced.
- Generated files cannot overwrite deterministic scaffold files.

The current validator is intentionally conservative. It does not claim that accepted TypeScript is correct or secure; it only establishes a first deterministic safety boundary.

### 12. Trust Boundaries

```text
Trusted application code
  ├── Streamlit UI
  ├── deterministic inspector
  ├── Pydantic validators
  └── deterministic packager

Untrusted data
  ├── uploaded ZIP names and contents
  ├── legacy PHP/HTML/JS/SQL text
  ├── Azure-generated file paths and source
  └── copied static assets

External services
  └── Azure OpenAI API
```

The current prototype does not execute either untrusted zone. If build validation is added, it must run in a disposable isolated worker with no access to application secrets or the control-plane filesystem.

### 13. Production Evolution

The next production architecture should separate the synchronous control plane from asynchronous migration workers:

```text
Browser
  │
  ▼
Web/API service ───── PostgreSQL
  │                     │
  │                     └── migrations, stages, users, approvals
  ▼
Durable job queue / workflow engine
  │
  ├── Intake worker
  ├── Analysis worker
  ├── Azure OpenAI worker
  ├── Generation worker
  ├── Isolated build worker
  └── Packaging worker
  │
  └── Object storage for source snapshots, evidence, reports, and ZIPs
```

Recommended production additions:

- PostgreSQL for migration state and audit records.
- Object storage for immutable artifacts.
- A durable workflow engine such as Temporal for retries, cancellation, and resumability.
- Short-lived worker credentials.
- Per-tenant quotas and rate limits.
- Encryption at rest and in transit.
- Artifact expiration and user-requested deletion.
- OpenTelemetry traces and structured audit logs.
- Human approval state before repository export.
- Build validation in a disposable sandbox such as gVisor-backed containers.
- Network-denied build workers, except for a separately controlled dependency-fetch phase.
- GitHub App integration with least-privilege installation permissions.

### 14. Reliability And Idempotency

Every production stage should be independently retryable and idempotent.

Recommended stage identity:

```text
migration_id + stage_name + source_hash + prompt_version + generator_version
```

The system should persist:

- Upload hash.
- Source inventory hash.
- Azure model and deployment identifier.
- Prompt version.
- Migration-plan JSON.
- Generated-project JSON.
- Validator results.
- Final ZIP hash.
- Human approval decisions.

If the same inputs and versions are processed again, the system should be able to explain any output difference.

### 15. Validation Strategy

Current validation is static and package-level. The target validation matrix is:

| Check | Purpose |
|---|---|
| Archive validation | Prevent traversal, bombs, encryption, and oversized inputs |
| Inventory validation | Confirm routes, assets, tables, and behaviors are recorded |
| Schema validation | Ensure Azure responses match application contracts |
| Generated path validation | Prevent writes outside the target project boundary |
| Import validation | Prevent undeclared or arbitrary dependencies |
| Unsafe API scan | Detect dangerous generated code patterns |
| Typecheck | Confirm TypeScript structure |
| Production build | Confirm the generated project compiles |
| Route checks | Confirm expected routes resolve |
| Asset checks | Confirm first-party assets are present |
| Screenshot comparison | Identify visual regressions |
| Accessibility scan | Detect common WCAG issues |
| Human review | Confirm behavior and content are acceptable |

Build, browser, and dependency validation must happen outside the Streamlit process in production.

### 16. Security Requirements

Before exposing Transit to untrusted users, add:

- Authentication and tenant isolation.
- Upload rate limiting.
- Content-length enforcement before buffering.
- Malware and archive-bomb scanning.
- Secret scanning with user notification.
- Strict object-storage access policies.
- Short-lived download URLs.
- API-key storage in a managed secret store.
- Azure private networking where required.
- Complete deletion of source and generated artifacts.
- Audit logs for upload, analysis, generation, review, and download.
- SSRF protections if URL crawling is later introduced.
- Sandboxed execution if builds or previews are later introduced.

### 17. Architecture Decisions

| Decision | Rationale |
|---|---|
| Python modular monolith | Small operational footprint and fast iteration for the MVP |
| Streamlit UI | Lightweight upload and review experience |
| Pydantic contracts | Strong validation at the model boundary |
| Two Azure calls | Separates architecture reasoning from code generation |
| Deterministic local inspection | Reduces hallucination and makes evidence auditable |
| Generated-file allowlist | Limits the model's filesystem and dependency surface |
| No source execution | Prevents uploaded PHP and scripts from becoming a code-execution path |
| Git-based content output | Keeps migrated content editable and reviewable |
| Manual backend review | Avoids inventing business-critical behavior |

### 18. Open Decisions For The Next Version

- Whether to add GitHub OAuth installation and repository selection for multi-tenant hosted use.
- Whether to add URL-based runtime capture for authorized sites.
- Whether to support a headless CMS output mode.
- Whether to create pull requests directly after human approval.
- Which sandbox runtime will run Next.js builds.
- How visual similarity should be scored and reviewed.
- How customer data retention and deletion should be exposed.
- Whether migration workflows require a durable orchestration service immediately or after beta usage.
