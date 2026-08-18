"""Streamlit UI for the lightweight web-project migration prototype."""

from __future__ import annotations

import hashlib
import html
import os
import re
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from migrator import (
    AzureMigrationEngine,
    GitHubClient,
    build_project_files,
    build_project_zip,
    inspect_project,
    parse_repository_url,
)
from migrator.models import MigrationPlan


ROOT = Path(__file__).resolve().parent


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        :root { --paper: #f4f0e7; --ink: #17211b; --moss: #315b42; --lime: #c9ef72;
                --rust: #be5738; --line: #c9c2b4; --panel: #fffdf7; }
        .stApp { background: var(--paper); color: var(--ink); }
        [data-testid="stHeader"] { background: rgba(244, 240, 231, .88); }
        [data-testid="stSidebar"] { background: #e9e3d7; border-right: 1px solid var(--line); }
        .block-container { max-width: 1180px; padding-top: 2.4rem; padding-bottom: 4rem; }
        h1, h2, h3 { color: var(--ink); letter-spacing: -.035em; }
        h1 { font-size: clamp(2.5rem, 7vw, 5.5rem) !important; line-height: .88 !important; max-width: 900px; }
        .eyebrow { color: var(--moss); font: 800 .72rem/1.2 monospace; letter-spacing: .16em; text-transform: uppercase; }
        .lede { color: #536057; font-size: 1.08rem; line-height: 1.55; max-width: 690px; margin: 1.2rem 0 2rem; }
        .rule { border-top: 1px solid var(--line); margin: 1.7rem 0; }
        .metric { background: var(--panel); border: 1px solid var(--line); border-radius: 4px; padding: 1rem 1.1rem; box-shadow: 5px 5px 0 #d8d1c4; }
        .metric-label { color: #6b756d; font: 700 .68rem monospace; letter-spacing: .1em; text-transform: uppercase; }
        .metric-value { color: var(--ink); font-size: 1.35rem; font-weight: 800; margin-top: .35rem; }
        .tag { display: inline-block; background: #dde8d8; border: 1px solid #9fb19f; border-radius: 99px; color: #294b37; font: 700 .72rem monospace; margin: 0 .35rem .35rem 0; padding: .3rem .55rem; }
        .warning-tag { background: #f4ded4; border-color: #d5a38f; color: #77341f; }
        .route { display: grid; grid-template-columns: 1fr auto 1.6fr; gap: .8rem; align-items: center; border-bottom: 1px solid #ddd6c9; padding: .65rem 0; font-family: monospace; }
        .route-arrow { color: var(--rust); font-weight: 900; }
        .stButton > button[kind="primary"], .stDownloadButton > button { background: var(--ink); border: 1px solid var(--ink); border-radius: 2px; color: var(--lime); font-weight: 800; }
        .stButton > button[kind="primary"]:hover, .stDownloadButton > button:hover { background: var(--moss); border-color: var(--moss); color: white; }
        [data-testid="stFileUploaderDropzone"] { background: var(--panel); border: 1px dashed var(--moss); border-radius: 3px; }
        code { color: var(--moss) !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    load_dotenv(ROOT / ".env", override=False)
    required = ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_DEPLOYMENT"]
    configured = all(os.getenv(name) for name in required)
    github_configured = bool(os.getenv("GITHUB_TOKEN")) or all(
        os.getenv(name) for name in ("GITHUB_APP_ID", "GITHUB_INSTALLATION_ID", "GITHUB_PRIVATE_KEY")
    )
    with st.sidebar:
        st.markdown('<div class="eyebrow">TRANSIT / MIGRATION LAB</div>', unsafe_allow_html=True)
        st.markdown("## Conversion boundary")
        st.markdown("**Input**  \nLegacy web project ZIP")
        st.markdown("**Output**  \nNext.js App Router")
        st.markdown("**Content**  \nTypeScript files in Git")
        st.divider()
        if configured:
            st.success("Azure OpenAI configured")
        else:
            st.error("Azure OpenAI is not configured")
            st.caption("Set the four `AZURE_OPENAI_*` values in `.env`.")
        if github_configured:
            st.success("GitHub repository access configured")
        else:
            st.warning("GitHub access is not configured")
            st.caption("Set `GITHUB_TOKEN` locally or GitHub App credentials for repository intake and branch export.")
        st.divider()
        st.caption("Uploaded source is inspected as text. It is never extracted or executed. Generated code is packaged but not run.")


def render_inventory() -> None:
    inventory = st.session_state["project_snapshot"].inventory
    columns = st.columns(4)
    values = [
        ("Source files", inventory.source_file_count),
        ("Static assets", inventory.asset_count),
        ("Routes found", len(inventory.route_candidates)),
        ("DB tables", len(inventory.database_tables)),
    ]
    for column, (label, value) in zip(columns, values):
        column.markdown(f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)
    st.markdown("### Local inspection")
    st.markdown("".join(f'<span class="tag">{html.escape(item)}</span>' for item in inventory.detected_technologies), unsafe_allow_html=True)
    if inventory.behavior_signals:
        st.caption("Behavior requiring migration review")
        st.markdown("".join(f'<span class="tag warning-tag">{html.escape(item)}</span>' for item in inventory.behavior_signals), unsafe_allow_html=True)
    if inventory.skipped_sensitive_files:
        st.warning(f"Skipped {len(inventory.skipped_sensitive_files)} potentially sensitive files before preparing the model context.")
    if inventory.truncated:
        st.info("The source context was bounded or one or more oversized files were omitted.")
    with st.expander("Inspect source inventory"):
        st.code("\n".join(inventory.source_files) or "No readable source files", language="text")


def render_plan(plan: MigrationPlan) -> None:
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">02 / ARCHITECTURE MAP</div>', unsafe_allow_html=True)
    st.header("Migration plan")
    st.markdown(plan.project_summary)
    for route in plan.routes:
        st.markdown(f'<div class="route"><span>{html.escape(route.source)}</span><span class="route-arrow">→</span><span>{html.escape(route.target)} · {html.escape(route.purpose)}</span></div>', unsafe_allow_html=True)
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Shared components")
        for item in plan.shared_components:
            st.markdown(f"- {item}")
        st.markdown("#### Preserved behavior")
        for item in plan.preserved_behaviors:
            st.markdown(f"- {item}")
    with right:
        st.markdown("#### Requires manual work")
        for item in plan.unsupported_behaviors:
            st.markdown(f"- {item}")
        st.markdown("#### Risks")
        for item in plan.risks:
            st.markdown(f"- {item}")


def main() -> None:
    st.set_page_config(page_title="Transit · Migration Lab", page_icon="↗", layout="wide")
    inject_theme()
    render_sidebar()
    st.markdown('<div class="eyebrow">LEGACY WEB → MODERN STACK / CONTROLLED CONVERSION</div>', unsafe_allow_html=True)
    st.title("Move the site. Leave the legacy behind.")
    st.markdown('<p class="lede">Upload a legacy web project. Transit inventories its routes, assets, data signals, and server behavior, then uses Azure OpenAI to produce a reviewable migration plan and clean modern starter.</p>', unsafe_allow_html=True)
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">01 / SOURCE INTAKE</div>', unsafe_allow_html=True)
    source_kind = st.radio("Source", ["GitHub repository", "ZIP upload"], horizontal=True)
    if source_kind == "GitHub repository":
        repository_url = st.text_input(
            "GitHub repository URL",
            placeholder="https://github.com/acme/legacy-site",
            help="You can also paste a branch URL such as https://github.com/acme/legacy-site/tree/staging.",
        )
        repository_key = f"github:{repository_url.strip()}"
        if st.button("Connect and inspect repository", type="primary", use_container_width=True):
            try:
                owner, repository, ref = parse_repository_url(repository_url)
                with st.status("Connecting to GitHub...", expanded=True) as status:
                    st.write("Resolving the selected ref to an immutable commit SHA")
                    project, source = GitHubClient().fetch_project(owner, repository, ref)
                    st.session_state["project_snapshot"] = project
                    st.session_state["project_source"] = repository_key
                    st.session_state["github_source"] = source
                    for key in ("migration_plan", "generated_project", "project_zip", "github_push_result", "migration_branch_name"):
                        st.session_state.pop(key, None)
                    status.update(label=f"Pinned to {source.sha[:12]}", state="complete")
            except (RuntimeError, ValueError) as error:
                st.error(f"GitHub intake failed: {error}")
        if st.session_state.get("project_source") != repository_key:
            st.info("Connect a repository to begin. Transit downloads the pinned GitHub archive and does not clone or execute it.")
            return
        source = st.session_state.get("github_source")
        if source:
            st.caption(f"Read-only source: `{source.label}` · ref `{source.ref}` · default branch `{source.default_branch}`")
    else:
        uploaded = st.file_uploader("Legacy web project ZIP", type=["zip"], help="Maximum upload: 15 MB compressed and 40 MB uncompressed.")
        if uploaded is None:
            st.info("Try the included `examples/lamp-site` project: ZIP that directory and upload it here.")
            return
        data = uploaded.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        zip_key = f"zip:{digest}"
        if st.session_state.get("project_source") != zip_key:
            try:
                st.session_state["project_snapshot"] = inspect_project(data, uploaded.name)
                st.session_state["project_source"] = zip_key
                for key in ("migration_plan", "generated_project", "project_zip", "github_source", "github_push_result", "migration_branch_name"):
                    st.session_state.pop(key, None)
            except ValueError as error:
                st.error(str(error))
                return

    render_inventory()
    if st.button("Analyze migration with Azure OpenAI", type="primary", use_container_width=True):
        try:
            with st.status("Reading the legacy shape...", expanded=True) as status:
                st.write("Sending bounded, secret-filtered source evidence to Azure OpenAI")
                plan = AzureMigrationEngine().analyze(st.session_state["project_snapshot"])
                st.session_state["migration_plan"] = plan
                st.session_state.pop("generated_project", None)
                st.session_state.pop("project_zip", None)
                status.update(label="Migration plan ready", state="complete")
        except Exception as error:
            st.error(f"Azure analysis failed: {error}")

    plan = st.session_state.get("migration_plan")
    if not plan:
        return
    render_plan(plan)
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">03 / CODE GENERATION</div>', unsafe_allow_html=True)
    st.header("Build the modern starter")
    st.caption("Generation is constrained to presentation files. Backend behavior remains an explicit migration task.")
    if st.button("Generate guarded Next.js project", type="primary", use_container_width=True):
        try:
            with st.status("Compiling the migration...", expanded=True) as status:
                st.write("Generating schema-constrained Next.js source")
                generated = AzureMigrationEngine().generate(st.session_state["project_snapshot"], plan)
                st.write("Validating paths, imports, required files, and unsafe APIs")
                st.session_state["generated_project"] = generated
                st.session_state["project_zip"] = build_project_zip(st.session_state["project_snapshot"], plan, generated)
                status.update(label="Next.js starter ready", state="complete")
        except Exception as error:
            st.error(f"Generation stopped safely: {error}")

    generated = st.session_state.get("generated_project")
    if not generated:
        return
    st.success(f"Generated {len(generated.files)} source files and copied {st.session_state['project_snapshot'].inventory.asset_count} static assets.")
    with st.expander("Generated file manifest", expanded=True):
        for item in generated.files:
            st.markdown(f"`{item.path}` · {item.purpose}")
    for note in generated.migration_notes:
        st.markdown(f"- {note}")
    st.download_button(
        "Download Next.js project ZIP",
        data=st.session_state["project_zip"],
        file_name=f"{st.session_state['project_snapshot'].inventory.project_name}-nextjs.zip",
        mime="application/zip",
        use_container_width=True,
    )
    github_source = st.session_state.get("github_source")
    if github_source:
        st.markdown("### Push to a new GitHub branch")
        st.caption("The source ref stays unchanged. Transit creates one commit from the pinned source SHA.")
        project_slug = re.sub(r"[^a-z0-9-]+", "-", st.session_state["project_snapshot"].inventory.project_name.lower()).strip("-") or "project"
        default_branch = f"transit/migrate-{project_slug[:80]}"
        branch_name = st.text_input("New branch name", value=default_branch, key="migration_branch_name")
        if st.button("Create migration branch", type="primary", use_container_width=True):
            try:
                with st.status("Writing the migration to GitHub...", expanded=True) as status:
                    st.write("Creating generated file blobs")
                    files = build_project_files(st.session_state["project_snapshot"], plan, generated)
                    result = GitHubClient().push_project(
                        github_source,
                        files,
                        branch_name,
                        commit_message=f"Add Transit migration for {st.session_state['project_snapshot'].inventory.project_name}",
                    )
                    st.session_state["github_push_result"] = result
                    status.update(label="Migration branch created", state="complete")
            except (RuntimeError, ValueError) as error:
                st.error(f"GitHub export failed: {error}")
        result = st.session_state.get("github_push_result")
        if result:
            st.success(f"Created `{result.branch}` at commit `{result.commit_sha[:12]}`.")
            st.link_button("Open migration branch on GitHub", result.url, use_container_width=True)


if __name__ == "__main__":
    main()
