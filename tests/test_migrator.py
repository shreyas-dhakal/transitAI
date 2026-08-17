"""Dependency-light tests for the migration safety boundary and happy path."""

import unittest
import zipfile
from io import BytesIO
from unittest.mock import patch

from migrator import AzureLampMigrator, GitHubClient, build_project_zip, inspect_lamp_zip, parse_repository_url
from migrator import github as github_module
from migrator.models import GeneratedFile, GeneratedProject, MigrationPlan, RoutePlan


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

    def test_end_to_end_generation_packages_scaffold_and_assets(self):
        project = inspect_lamp_zip(project_archive(), "legacy.zip")
        migrator = AzureLampMigrator(client=FakeClient())
        migration_plan = migrator.analyze(project)
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


if __name__ == "__main__":
    unittest.main()
