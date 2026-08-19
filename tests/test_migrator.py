"""Dependency-light tests for the migration safety boundary and happy path."""

import unittest
import json
import zipfile
from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import patch

from migrator import (
    AdapterFindings,
    AdapterRegistry,
    AzureLampMigrator,
    GitHubClient,
    GitHubSource,
    build_project_zip,
    inspect_lamp_zip,
    inspect_project,
    parse_repository_url,
)
from migrator.cir import (
    BehaviorClaim,
    BehaviorExtraction,
    BehaviorSample,
    SampleMetadata,
    aggregate_claims,
)
from migrator import github as github_module
from migrator.models import GeneratedFile, GeneratedProject, MigrationPlan, MigrationUnit, RoutePlan
from migrator.wesley import assess_project


def project_archive() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("legacy/index.php", "<?php include 'header.php'; ?><h1>Legacy home</h1><form method='post'></form>")
        archive.writestr("legacy/config.php", "<?php $password = 'do-not-send'; $db = new mysqli('localhost');")
        archive.writestr("legacy/page.php", "<?php $api_key = 'also-do-not-send'; ?><p>Page</p>")
        archive.writestr("legacy/schema.sql", "CREATE TABLE messages (id INT PRIMARY KEY);")
        archive.writestr("legacy/assets/logo.svg", "<svg xmlns='http://www.w3.org/2000/svg'></svg>")
        archive.writestr("legacy/.env", "API_KEY=secret")
    return output.getvalue()


def plan() -> MigrationPlan:
    return MigrationPlan(
        project_summary="A small public marketing site.",
        routes=[RoutePlan(source="/", target="/", purpose="Home page")],
        shared_components=["SiteHeader"],
        content_strategy="Typed content in Git",
        styling_strategy="Global design tokens",
        data_entities=["messages"],
        preserved_behaviors=["Navigation"],
        unsupported_behaviors=["Form delivery"],
        risks=["Backend destination is unknown"],
        assumptions=["Public site"],
    )


def generated(import_line: str = "") -> GeneratedProject:
    return GeneratedProject(
        files=[
            GeneratedFile(path="app/layout.tsx", content='import "./globals.css";\nexport default function Layout({ children }: { children: React.ReactNode }) { return <html><body>{children}</body></html>; }', purpose="Layout"),
            GeneratedFile(path="app/page.tsx", content=f'{import_line}\nexport default function Page() {{ return <main><h1>Legacy home</h1></main>; }}', purpose="Home"),
            GeneratedFile(path="app/globals.css", content="body { margin: 0; }", purpose="Styles"),
        ],
        migration_notes=["Configure a form provider manually."],
    )


class FakeStructuredModel:
    def __init__(self, response):
        self.response = response

    def invoke(self, messages):
        return self.response


class FakeClient:
    def __init__(self, generated_project=None):
        self.generated_project = generated_project or generated()

    def with_structured_output(self, schema):
        return FakeStructuredModel(plan() if schema is MigrationPlan else self.generated_project)


class MigratorTests(unittest.TestCase):
    def test_github_url_parser_accepts_repository_and_branch_links(self):
        self.assertEqual(
            parse_repository_url("https://github.com/acme/legacy-site.git"),
            ("acme", "legacy-site", None),
        )
        self.assertEqual(
            parse_repository_url("https://github.com/acme/legacy-site/tree/feature/home"),
            ("acme", "legacy-site", "feature/home"),
        )
        with self.assertRaisesRegex(ValueError, "GitHub repository URL"):
            parse_repository_url("https://gitlab.com/acme/legacy-site")

    def test_archive_is_bounded_redacted_and_inventoried(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        self.assertEqual(project.inventory.route_candidates, ["/", "/page"])
        self.assertEqual(project.inventory.database_tables, ["messages"])
        self.assertIn("HTML form submission", project.inventory.behavior_signals)
        self.assertEqual(project.inventory.skipped_sensitive_files, [".env", "config.php"])
        self.assertNotIn("also-do-not-send", project.source_context)
        self.assertIn("[REDACTED]", project.source_context)
        self.assertEqual(project.inventory.asset_urls, ["/legacy/assets/logo.svg"])

    def test_rejects_archive_path_traversal(self):
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("../outside.php", "<?php echo 'bad';")
        with self.assertRaisesRegex(ValueError, "Unsafe archive member path"):
            inspect_lamp_zip(output.getvalue())

    def test_universal_adapter_inspects_non_php_web_sources(self):
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("site/home.html", "<form action='/contact'><input type='file'></form>")
            archive.writestr("site/server.py", "users = db.execute('SELECT * FROM users')")
            archive.writestr("site/schema.sql", "CREATE TABLE users (id INT PRIMARY KEY);")

        project = inspect_project(output.getvalue(), "site.zip")

        self.assertEqual(project.inventory.adapter, "universal-web+structural-graph")
        self.assertEqual(project.inventory.adapter_sources, ["universal-web", "structural-graph"])
        self.assertEqual(project.inventory.route_candidates, ["/home"])
        self.assertIn("Python", project.inventory.detected_technologies)
        self.assertIn("Database reads or writes", project.inventory.behavior_signals)
        self.assertIsNotNone(project.findings[1].graph)

    def test_snapshot_contains_deterministic_cir_with_provenance(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")

        self.assertIsNotNone(project.cir)
        self.assertEqual(project.cir.provenance.schema_version, "1.0")
        self.assertEqual(project.cir.provenance.source_hash, inspect_lamp_zip(project_archive(), "legacy.zip").cir.provenance.source_hash)
        self.assertEqual(project.cir.routes[0].pattern, "/")
        self.assertIn("messages", [entity.name for entity in project.cir.entities])
        self.assertTrue(project.cir.provenance.sample_set_hash)
        self.assertIsNotNone(project.migration)
        self.assertEqual(project.migration.target_profile, "nextjs-app-router")
        self.assertTrue(project.migration.waves)

    def test_migration_blueprint_is_carried_into_azure_plan(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        migration_plan = AzureLampMigrator(client=FakeClient()).analyze(project)

        self.assertEqual(migration_plan.strategy, project.migration.strategy)
        self.assertEqual(
            [unit.unit_id for unit in migration_plan.migration_units],
            [unit.unit_id for unit in project.migration.units],
        )
        self.assertEqual(migration_plan.approval_status, "pending")

    def test_wesley_reengineers_known_insecure_php(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        assessment = assess_project(project.inventory, {"index.php": "<?php mysql_query($query);"})

        self.assertEqual(assessment.overall_classification, "reengineer")
        self.assertTrue(any(
            signal.value == "PHP mysql_* API"
            for signal in assessment.signals
        ))

    def test_wesley_preserves_unknown_repository_signals(self):
        inventory = project_archive()
        project = inspect_lamp_zip(inventory, "legacy.zip")
        unknown = {signal.name for signal in project.wesley.signals if signal.status == "unknown"}

        self.assertIn("commit recency", unknown)
        self.assertIn("test churn", unknown)
        self.assertIn("dependency CVEs", unknown)
        self.assertTrue(project.wesley.limitations)

    def test_wesley_detects_runtime_and_dependency_lag(self):
        sources = {
            "index.php": "<?php echo 'home';",
            "composer.json": '{"require":{"jquery":"1.12.4"},"config":{"php":"7.4"}}',
        }
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        assessment = assess_project(project.inventory, sources)
        statuses = {(signal.name, signal.status) for signal in assessment.signals}

        self.assertIn(("PHP runtime version", "stale"), statuses)
        self.assertIn(("dependency version lag", "stale"), statuses)
        self.assertIn(assessment.overall_classification, {"replace", "reengineer", "coexist"})

    def test_cir_claim_aggregation_preserves_disagreement(self):
        def sample(sample_id, model, text):
            return BehaviorSample(
                sample_id=sample_id,
                unit_id="behavior:form-submission",
                claims=[BehaviorClaim(kind="delivery", text=text)],
                metadata=SampleMetadata(
                    sample_id=sample_id,
                    model=model,
                    framing="route-first",
                    context_hash="context",
                ),
            )

        claims = aggregate_claims(
            "behavior:form-submission",
            [
                sample("one", "model-a", "sends an email"),
                sample("two", "model-b", "sends an email"),
                sample("three", "model-a", "stores a message"),
                sample("four", "model-b", "stores a message"),
            ],
            structural_check="consistent",
        )

        self.assertEqual([claim.confidence_tier for claim in claims], ["contested", "contested"])
        self.assertEqual(claims[0].support, 0.5)
        self.assertTrue(all(claim.cross_model_agreement for claim in claims))

    def test_cir_claim_confirmation_requires_structural_corroboration(self):
        sample = BehaviorSample(
            sample_id="one",
            unit_id="behavior:database",
            claims=[BehaviorClaim(kind="operation", text="reads products")],
            metadata=SampleMetadata(
                sample_id="one", model="model-a", framing="top-down", context_hash="context"
            ),
        )

        self.assertEqual(aggregate_claims("behavior:database", [sample], "consistent")[0].confidence_tier, "confirmed")
        self.assertEqual(aggregate_claims("behavior:database", [sample], "not_checkable")[0].confidence_tier, "likely")

    def test_engine_samples_a_behavior_unit_without_mutating_snapshot(self):
        class SamplingModel:
            def __init__(self):
                self.calls = 0

            def invoke(self, messages):
                self.calls += 1
                return BehaviorExtraction(claims=[BehaviorClaim(kind="signal", text="HTML form submission")])

        class SamplingClient:
            def __init__(self):
                self.model = SamplingModel()

            def with_structured_output(self, schema):
                self.assert_schema = schema
                return self.model

        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        client = SamplingClient()
        sampled = AzureLampMigrator(client=client).sample_behavior(
            project, "behavior:html-form-submission", sample_count=2
        )

        unit = next(item for item in sampled.behaviors if item.unit_id == "behavior:html-form-submission")
        self.assertEqual(len(unit.samples), 2)
        self.assertEqual(unit.claims[0].confidence_tier, "confirmed")
        self.assertEqual(len(project.cir.behaviors[0].samples), 0)

    def test_registry_composes_registered_adapters(self):
        class CustomAdapter:
            name = "custom-runtime"

            def detect(self, sources):
                return (0.8, ["custom manifest"])

            def inspect(self, sources):
                return AdapterFindings(["Custom runtime"], ["/custom"], [], [])

        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("project/index.html", "<main />")

        registry = AdapterRegistry.with_defaults()
        registry.register(CustomAdapter())
        project = inspect_project(output.getvalue(), registry=registry)

        self.assertIn("custom-runtime", project.inventory.adapter_sources)
        self.assertIn("Custom runtime", project.inventory.detected_technologies)

    def test_custom_source_adapter_can_enrich_snapshot(self):
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("project/main.txt", "evidence")

        class CustomAdapter:
            name = "custom-runtime"

            def inspect(self, sources):
                return AdapterFindings(
                    detected_technologies=["Custom runtime"],
                    route_candidates=["/custom"],
                    database_tables=[],
                    behavior_signals=["Custom behavior"],
                )

        project = inspect_project(output.getvalue(), adapter=CustomAdapter())

        self.assertEqual(project.inventory.adapter, "custom-runtime")
        self.assertEqual(project.inventory.route_candidates, ["/custom"])
        self.assertEqual(project.inventory.detected_technologies, ["Custom runtime"])

    def test_end_to_end_generation_packages_scaffold_and_assets(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        migrator = AzureLampMigrator(client=FakeClient())
        migration_plan = migrator.analyze(project)
        migration_plan = migration_plan.model_copy(update={"approval_status": "approved"})
        generated_project = migrator.generate(project, migration_plan)
        result = build_project_zip(project, migration_plan, generated_project)
        with zipfile.ZipFile(BytesIO(result)) as archive:
            names = set(archive.namelist())
        self.assertIn("package.json", names)
        self.assertIn("app/page.tsx", names)
        self.assertIn("public/legacy/assets/logo.svg", names)
        self.assertIn("MIGRATION.md", names)

    def test_rejects_unsupported_generated_import(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        migrator = AzureLampMigrator(client=FakeClient(generated('import axios from "axios";')))
        with self.assertRaisesRegex(ValueError, "unsupported import"):
            migrator.generate(project, plan())

    def test_generation_rejects_unapproved_migration_roadmap(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        migration_plan = plan().model_copy(update={
            "migration_units": [MigrationUnit(
                unit_id="route:/",
                source_scope="/",
                classification="migrate",
                action="recreate route",
                target_scope="app/page.tsx",
            )],
        })

        with self.assertRaisesRegex(ValueError, "approved"):
            AzureLampMigrator(client=FakeClient()).generate(project, migration_plan)

    def test_github_intake_pins_ref_and_reuses_archive_inspector(self):
        archive = project_archive()
        responses = [
            b'{"default_branch":"main"}',
            b'{"sha":"0123456789abcdef0123456789abcdef01234567"}',
            archive,
        ]

        class FakeResponse:
            def __init__(self, body):
                self.body = body
                self.headers = {"Content-Length": str(len(body))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                body, self.body = self.body, b""
                return body[:size]

        requests = []

        def fake_urlopen(request, timeout=30):
            requests.append(request.full_url)
            return FakeResponse(responses.pop(0))

        with patch.object(github_module, "urlopen", side_effect=fake_urlopen):
            project, source = GitHubClient(token="test-token").fetch_project("acme", "legacy-site", "feature/home")

        self.assertEqual(source.ref, "feature/home")
        self.assertEqual(source.sha, "0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(project.inventory.route_candidates, ["/", "/page"])
        self.assertIn("/commits/feature%2Fhome", requests[1])
        self.assertIn("/zipball/0123456789abcdef0123456789abcdef01234567", requests[2])

    def test_github_push_creates_blobs_tree_commit_and_branch(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        responses = [
            b'{"sha":"blob-sha"}',
            b'{"sha":"tree-sha"}',
            b'{"sha":"commit-sha"}',
            b'{"ref":"refs/heads/transit/migrate-site"}',
        ]

        class FakeResponse:
            def __init__(self, body):
                self.body = body
                self.headers = {"Content-Length": str(len(body))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                body, self.body = self.body, b""
                return body[:size]

        requests = []

        def fake_urlopen(request, timeout=30):
            requests.append((request.full_url, request.method, json.loads(request.data)))
            return FakeResponse(responses.pop(0))

        source = GitHubSource("acme", "legacy-site", "main", sha, "main")
        with patch.object(github_module, "urlopen", side_effect=fake_urlopen):
            result = GitHubClient(token="test-token").push_project(
                source, {"app/page.tsx": b"export default function Page() {}"}, "transit/migrate-site"
            )

        self.assertEqual(result.commit_sha, "commit-sha")
        self.assertEqual([request[1] for request in requests], ["POST", "POST", "POST", "POST"])
        self.assertEqual(requests[1][2]["base_tree"], sha)
        self.assertEqual(requests[2][2]["parents"], [sha])
        self.assertEqual(requests[3][2]["ref"], "refs/heads/transit/migrate-site")

    def test_github_write_permission_error_is_actionable(self):
        def denied_urlopen(request, timeout=30):
            raise HTTPError(
                request.full_url,
                403,
                "Forbidden",
                {},
                BytesIO(b'{"message":"Resource not accessible by personal access token"}'),
            )

        source = GitHubSource("acme", "legacy-site", "main", "0" * 40, "main")
        with patch.object(github_module, "urlopen", side_effect=denied_urlopen):
            with self.assertRaisesRegex(RuntimeError, "Contents: Read and write"):
                GitHubClient(token="test-token").push_project(source, {"app/page.tsx": b"page"}, "transit/migrate")


if __name__ == "__main__":
    unittest.main()
