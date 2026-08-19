"""Dependency-light tests for the migration safety boundary and happy path."""

import unittest
import json
import zipfile
from dataclasses import replace
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
from migrator.reverse_documentation import DiagramArtifact, ProductPlan, ReverseDocumentation, render_reverse_artifacts
from migrator.service import LLMRateLimitError
from migrator.archive import MAX_ARCHIVE_BYTES
from migrator import github as github_module
from migrator.models import GeneratedFile, GeneratedProject, MigrationPlan, MigrationUnit, RoutePlan
from migrator.specification import AgentResult, Claim, EvidenceRef, LegacySpecification
from migrator.usage import UsageLedger, extract_token_usage
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


def wordpress_archive() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "site/wp-content/plugins/order-sync/order-sync.php",
            """<?php
/*
Plugin Name: Order Sync
*/
add_action('woocommerce_checkout_order_processed', 'sync_order');
add_action('woocommerce_order_status_completed', 'notify_fulfillment');
wp_schedule_event(time(), 'hourly', 'sync_orders');
function sync_order($order_id) { wp_remote_post('https://example.test/orders'); }
""",
        )
        archive.writestr(
            "site/wp-content/plugins/forms/forms.php",
            "<?php add_action('form_plugin_webhook', 'send_form_webhook');\n"
            "wp_remote_post('https://example.test/forms');",
        )
    return output.getvalue()


def plan(approval_status: str = "approved") -> MigrationPlan:
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
        approval_status=approval_status,
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


class CapturingDocumentationClient:
    def __init__(self, response):
        self.response = response
        self.messages = []

    def with_structured_output(self, schema, **kwargs):
        model = self

        class CapturingModel:
            def invoke(self, messages):
                model.messages.append(messages)
                return model.response

        return CapturingModel()


class RetryingClient:
    def __init__(self, failures=2):
        self.failures = failures
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        client = self

        class RetryingModel:
            def invoke(self, messages):
                client.calls += 1
                if client.calls <= client.failures:
                    error = RuntimeError("rate limit exceeded")
                    error.status_code = 429
                    raise error
                return plan()

        return RetryingModel()


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
        self.assertEqual(project.inventory.adapter, "universal-web")
        self.assertEqual(project.inventory.route_candidates, ["/", "/page"])
        self.assertEqual(project.inventory.database_tables, ["messages"])
        self.assertIn("HTML form submission", project.inventory.behavior_signals)
        self.assertEqual(project.inventory.skipped_sensitive_files, [".env", "config.php"])
        self.assertNotIn("also-do-not-send", project.source_context)
        self.assertIn("[REDACTED]", project.source_context)
        self.assertEqual(project.inventory.asset_urls, ["/legacy/assets/logo.svg"])

    def test_archive_limit_allows_archives_up_to_100_mb(self):
        self.assertEqual(MAX_ARCHIVE_BYTES, 100 * 1024 * 1024)
        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("legacy/large-asset.bin", b"x" * (16 * 1024 * 1024))

        project = inspect_project(output.getvalue(), "large.zip")

        self.assertEqual(project.inventory.file_count, 1)

    def test_archive_automatically_ignores_generated_and_dependency_files(self):
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("legacy/index.php", "<?php echo 'home';")
            for index in range(801):
                archive.writestr(
                    f"legacy/node_modules/package-{index}/index.js",
                    "module.exports = {};",
                )

        project = inspect_project(output.getvalue(), "large-project.zip")

        self.assertEqual(project.inventory.file_count, 1)
        self.assertEqual(project.inventory.source_file_count, 1)
        self.assertEqual(project.inventory.skipped_ignored_file_count, 801)
        self.assertEqual(len(project.inventory.skipped_ignored_files), 100)

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
        self.assertIsNotNone(project.specification)
        self.assertEqual(project.specification.source_hash, project.cir.provenance.source_hash)
        self.assertTrue(any(claim.category == "route" for claim in project.specification.claims))
        self.assertTrue(any(claim.category == "data-flow" for claim in project.specification.claims))
        self.assertIsNotNone(project.migration)
        self.assertEqual(project.migration.target_profile, "nextjs-app-router")
        self.assertTrue(project.migration.waves)

    def test_wordpress_side_effects_are_first_class_reverse_documentation(self):
        project = inspect_project(wordpress_archive(), "wordpress.zip")

        self.assertIn("WordPress", project.inventory.detected_technologies)
        self.assertIsNotNone(project.reverse_documentation)
        documentation = project.reverse_documentation
        kinds = {effect.kind for effect in documentation.side_effects}
        triggers = {effect.trigger for effect in documentation.side_effects}
        self.assertIn("woocommerce-hook", kinds)
        self.assertIn("wordpress-cron", kinds)
        self.assertIn("webhook", kinds)
        self.assertIn("woocommerce_checkout_order_processed", triggers)
        self.assertTrue(all(effect.start_line >= 1 for effect in documentation.side_effects))
        self.assertTrue(any(scenario.side_effect_id for scenario in documentation.scenarios))

        artifacts = render_reverse_artifacts(documentation)
        self.assertIn("architecture.md", artifacts)
        self.assertIn("product-plan.md", artifacts)
        scenario_files = [path for path in artifacts if path.endswith(".feature")]
        self.assertGreaterEqual(len(scenario_files), 6)
        self.assertTrue(any("woocommerce" in artifacts[path].lower() for path in scenario_files))

    def test_semantic_documentation_cannot_drop_deterministic_side_effects(self):
        project = inspect_project(wordpress_archive(), "wordpress.zip")

        class SemanticClient:
            def with_structured_output(self, schema, **kwargs):
                return FakeStructuredModel(ReverseDocumentation(
                    project_name="wordpress",
                    summary="Semantic product summary.",
                    product_plan=ProductPlan(purpose="Synchronize orders."),
                ))

        enriched = AzureLampMigrator(client=SemanticClient()).document(project)
        self.assertEqual(enriched.summary, "Semantic product summary.")
        self.assertEqual(
            {effect.effect_id for effect in enriched.side_effects},
            {effect.effect_id for effect in project.reverse_documentation.side_effects},
        )
        self.assertTrue(enriched.scenarios)

    def test_semantic_documentation_receives_deterministic_evidence(self):
        project = inspect_project(wordpress_archive(), "wordpress.zip")
        client = CapturingDocumentationClient(ReverseDocumentation(
            project_name="wordpress",
            summary="Semantic product summary.",
            product_plan=ProductPlan(purpose="Synchronize orders."),
        ))

        AzureLampMigrator(client=client).document(project)

        payload = client.messages[0][1]["content"]
        self.assertIn("DETERMINISTIC REVERSE DOCUMENTATION:", payload)
        self.assertIn("woocommerce_checkout_order_processed", payload)

    def test_semantic_documentation_payload_stays_below_provider_limit(self):
        project = inspect_project(wordpress_archive(), "wordpress.zip")
        documentation = project.reverse_documentation.model_copy(update={
            "diagrams": [DiagramArtifact(
                artifact_id="diagram:large",
                title="Large diagram",
                diagram_type="c4-components",
                mermaid="x" * 20_000_000,
            )],
        })
        project = replace(project, reverse_documentation=documentation)
        client = CapturingDocumentationClient(ReverseDocumentation(
            project_name="wordpress",
            summary="Semantic product summary.",
            product_plan=ProductPlan(purpose="Synchronize orders."),
        ))

        AzureLampMigrator(client=client).document(project)

        payload = client.messages[0][1]["content"]
        self.assertLess(len(payload.encode("utf-8")), 10 * 1024 * 1024)
        self.assertIn("[truncated]", payload)

    def test_llm_rate_limits_are_retried_with_exponential_backoff(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        client = RetryingClient(failures=2)

        with patch("migrator.service.time.sleep") as sleep:
            result = AzureLampMigrator(client=client).analyze(project)

        self.assertEqual(result.project_summary, "A small public marketing site.")
        self.assertEqual(client.calls, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2.0, 4.0])

    def test_exhausted_llm_rate_limit_becomes_a_specific_error(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        client = RetryingClient(failures=10)

        with patch("migrator.service.time.sleep"), patch(
            "migrator.service.os.getenv", return_value="4"
        ):
            with self.assertRaises(LLMRateLimitError) as context:
                AzureLampMigrator(client=client).analyze(project)

        self.assertEqual(client.calls, 5)
        self.assertIn("rate limit persisted", str(context.exception))

    def test_legacy_specification_contract_preserves_claim_traceability(self):
        evidence = EvidenceRef(
            source="cir",
            file="index.php",
            start_line=4,
            end_line=8,
            node_id="file:index.php",
            excerpt_hash="abc123",
        )
        claim = Claim(
            claim_id="claim:route-home",
            category="route",
            statement="The application serves a public home route.",
            status="confirmed",
            confidence="high",
            evidence_refs=[evidence],
            supporting_agents=["deterministic-seed"],
        )
        result = AgentResult(
            agent_name="archaeologist",
            run_id="run-1",
            claims=[claim],
            model="test-model",
            prompt_version="test-1",
        )
        specification = LegacySpecification(
            project_name="legacy",
            project_summary="A legacy site.",
            routes=["/"],
            claims=[claim],
            agent_results=[result],
            source_hash="source-hash",
        )

        self.assertEqual(specification.claims[0].evidence_refs[0].source, "cir")
        self.assertEqual(specification.agent_results[0].claims[0].claim_id, "claim:route-home")

    def test_legacy_specification_rejects_uncontrolled_claim_values(self):
        with self.assertRaises(ValueError):
            Claim(
                claim_id="claim:invalid",
                category="guess",
                statement="Unsupported category",
                status="confirmed",
                confidence="high",
            )

    def test_usage_ledger_extracts_langchain_metadata_and_estimates_cost(self):
        response = {
            "response_metadata": {
                "model_name": "gpt-test",
                "token_usage": {
                    "prompt_tokens": 1_000,
                    "completion_tokens": 500,
                    "total_tokens": 1_500,
                },
            }
        }
        self.assertEqual(extract_token_usage(response), (1_000, 500, 1_500))
        ledger = UsageLedger(input_cost_per_million=1.0, output_cost_per_million=2.0)
        ledger.record(response, "migration_analysis")

        self.assertEqual(ledger.total_tokens, 1_500)
        self.assertEqual(ledger.prompt_tokens, 1_000)
        self.assertEqual(ledger.completion_tokens, 500)
        self.assertEqual(ledger.estimated_cost, 0.002)
        self.assertIn("1.5k tokens", ledger.compact_summary())

    def test_usage_ledger_reports_cost_unavailable_without_rates(self):
        ledger = UsageLedger()
        ledger.record({"usage_metadata": {"input_tokens": 10, "output_tokens": 5}}, "target_generation")

        self.assertIsNone(ledger.estimated_cost)
        self.assertIn("cost unavailable", ledger.compact_summary())

    def test_migration_blueprint_has_resolvable_waves_and_dependencies(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        blueprint = project.migration
        unit_ids = {unit.unit_id for unit in blueprint.units}
        wave_ids = [wave.wave_id for wave in blueprint.waves]

        self.assertEqual(len(wave_ids), len(set(wave_ids)))
        self.assertTrue(all(
            unit_id in unit_ids
            for wave in blueprint.waves
            for unit_id in wave.unit_ids
        ))
        self.assertTrue(all(
            dependency in unit_ids
            for unit in blueprint.units
            for dependency in unit.dependencies
        ))

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

    def test_rejects_unresolved_internal_generated_import(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        migrator = AzureLampMigrator(client=FakeClient(generated('import Missing from "./missing";')))

        with self.assertRaisesRegex(ValueError, "unresolved internal import"):
            migrator.generate(project, plan())

    def test_rejects_absolute_generated_paths(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        unsafe = generated()
        unsafe.files[1].path = "/app/page.tsx"

        with self.assertRaisesRegex(ValueError, "absolute path"):
            AzureLampMigrator(client=FakeClient(unsafe)).generate(project, plan())

    def test_rejects_duplicate_generated_paths_after_normalization(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        duplicate = generated()
        duplicate.files.append(GeneratedFile(
            path="app//page.tsx",
            content="export default function Duplicate() { return null; }",
            purpose="Duplicate",
        ))

        with self.assertRaisesRegex(ValueError, "duplicate file"):
            AzureLampMigrator(client=FakeClient(duplicate)).generate(project, plan())

    def test_generation_rejects_unapproved_migration_roadmap(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        migration_plan = plan(approval_status="pending").model_copy(update={
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

    def test_generation_rejects_unapproved_plan_without_migration_units(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")

        with self.assertRaisesRegex(ValueError, "approved"):
            AzureLampMigrator(client=FakeClient()).generate(
                project, plan(approval_status="pending")
            )

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
