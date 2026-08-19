"""Streamlit UI for the lightweight web-project migration prototype."""

from __future__ import annotations

import hashlib
import html
import os
import re
import time
from dataclasses import replace
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
from migrator.service import LLMRateLimitError
from migrator.usage import UsageLedger


ROOT = Path(__file__).resolve().parent
AZURE_RATE_LIMIT_COOLDOWN_SECONDS = 60


def azure_rate_limit_active() -> bool:
    return st.session_state.get("azure_rate_limited_until", 0) > time.time()


def mark_azure_rate_limited() -> None:
    st.session_state["azure_rate_limited_until"] = (
        time.time() + AZURE_RATE_LIMIT_COOLDOWN_SECONDS
    )


def record_activity(message: str, key: str | None = None) -> None:
    if key:
        recorded = st.session_state.setdefault("activity_keys", set())
        if key in recorded:
            return
        recorded.add(key)
    events = st.session_state.setdefault("activity_log", [])
    events.append({"time": time.strftime("%H:%M:%S"), "message": message})
    st.session_state["activity_log"] = events[-40:]


def reset_activity() -> None:
    st.session_state["activity_log"] = []
    st.session_state["activity_keys"] = set()
    st.session_state["activity_progress"] = 0.0
    st.session_state["activity_stage"] = "Waiting for source"


def set_activity_progress(value: float, stage: str) -> None:
    st.session_state["activity_progress"] = max(0.0, min(1.0, value))
    st.session_state["activity_stage"] = stage


def render_activity_log(target=None) -> None:
    events = st.session_state.get("activity_log", [])
    progress = st.session_state.get("activity_progress", 0.0)
    stage = st.session_state.get("activity_stage", "Waiting for source")
    rows = "".join(
        f'<div class="activity-row"><span class="activity-time">{html.escape(item["time"])}</span>'
        f'<span>{html.escape(item["message"])}</span></div>'
        for item in reversed(events)
    ) or '<div class="activity-empty">No activity yet.</div>'
    markup = (
        '<div class="activity-panel">'
        '<div class="eyebrow">LIVE ACTIVITY</div>'
        '<div class="activity-stage">'
        f'<div class="activity-stage-label">{html.escape(stage)}</div>'
        f'<div class="activity-track"><div class="activity-fill" style="width:{progress * 100:.1f}%"></div></div>'
        f'<div class="activity-percent">{progress * 100:.0f}%</div>'
        '</div>'
        f'<div class="activity-list">{rows}</div>'
        '</div>'
    )
    (target or st).markdown(markup, unsafe_allow_html=True)


def report_azure_rate_limit(delay: float, attempt: int) -> None:
    record_activity(f"Azure rate limit reached; waiting {delay:g}s (retry {attempt})")
    render_activity_log(st.session_state.get("activity_target"))


def usage_ledger() -> UsageLedger:
    ledger = st.session_state.get("usage_ledger")
    if not isinstance(ledger, UsageLedger):
        ledger = UsageLedger.from_environment()
        st.session_state["usage_ledger"] = ledger
    return ledger


def azure_engine() -> AzureMigrationEngine:
    """Attach session accounting without relying on a hot-reloaded constructor signature."""
    engine = AzureMigrationEngine(on_rate_limit=report_azure_rate_limit)
    engine.usage = usage_ledger()
    return engine


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
         .activity-panel { background: var(--panel); border: 1px solid var(--line); border-radius: 4px; padding: 1rem; position: sticky; top: 1rem; box-shadow: 5px 5px 0 #d8d1c4; }
         .activity-stage { margin: 1rem 0 1.1rem; }
         .activity-stage-label { color: var(--ink); font-size: .78rem; font-weight: 800; margin-bottom: .45rem; }
         .activity-track { background: #e1dbcf; border-radius: 99px; height: 5px; overflow: hidden; }
         .activity-fill { background: var(--moss); border-radius: 99px; height: 100%; transition: width .35s ease; }
         .activity-percent { color: #6b756d; font: 700 .65rem monospace; margin-top: .35rem; text-align: right; }
         .activity-list { border-top: 1px solid #e1dbcf; max-height: 32rem; overflow-y: auto; padding-top: .35rem; }
         .activity-row { border-bottom: 1px solid #eee9df; color: #344139; font-size: .75rem; line-height: 1.35; padding: .55rem 0; }
         .activity-time { color: var(--moss); display: block; font: 700 .62rem monospace; margin-bottom: .18rem; }
         .activity-empty { color: #7b837b; font-size: .78rem; padding: .8rem 0; }
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
        ledger = usage_ledger()
        if ledger.records:
            st.caption(f"Session usage · {ledger.compact_summary()}")
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
    st.caption(
        "Detected technologies: "
        + ", ".join(inventory.detected_technologies[:4])
        + (" …" if len(inventory.detected_technologies) > 4 else "")
    )
    with st.expander("Evidence details"):
        st.markdown("".join(f'<span class="tag">{html.escape(item)}</span>' for item in inventory.detected_technologies), unsafe_allow_html=True)
        if inventory.behavior_signals:
            st.caption("Behavior requiring migration review")
            st.markdown("".join(f'<span class="tag warning-tag">{html.escape(item)}</span>' for item in inventory.behavior_signals), unsafe_allow_html=True)
        if inventory.skipped_sensitive_files:
            st.warning(f"Skipped {len(inventory.skipped_sensitive_files)} potentially sensitive files before preparing the model context.")
        if inventory.skipped_ignored_file_count:
            st.info(
                f"Automatically excluded {inventory.skipped_ignored_file_count} generated or dependency files "
                "from analysis."
            )
        if inventory.truncated:
            st.info("The source context was bounded or one or more oversized files were omitted.")
        st.caption("Source inventory")
        st.code("\n".join(inventory.source_files) or "No readable source files", language="text")


def render_wesley() -> None:
    assessment = st.session_state["project_snapshot"].wesley
    if assessment is None:
        return
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">02 / WESLEY SPECTRUM</div>', unsafe_allow_html=True)
    st.header("Modernization disposition")
    st.markdown(
        f"**{assessment.overall_classification.upper()}** · {assessment.confidence} confidence"
    )
    st.caption(f"{len(assessment.signals)} static signals · {len(assessment.limitations)} evidence gaps")
    with st.expander("View classification evidence"):
        for component in assessment.components:
            for reason in component.reasons:
                st.markdown(f"- {html.escape(reason)}")
        for signal in assessment.signals:
            value = f" · {signal.value}" if signal.value else ""
            st.markdown(
                f"`{html.escape(signal.status)}` **{html.escape(signal.name)}**"
                f"{html.escape(value)} · {html.escape(signal.severity)}"
            )
            if signal.evidence:
                st.caption("; ".join(signal.evidence))
        if assessment.limitations:
            st.info("Unavailable evidence was not treated as healthy: " + "; ".join(assessment.limitations))


def render_migration_blueprint() -> None:
    blueprint = st.session_state["project_snapshot"].migration
    if blueprint is None:
        return
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">04 / MIGRATION ROADMAP</div>', unsafe_allow_html=True)
    st.header("Migration roadmap")
    st.markdown(
        f"**Strategy:** `{html.escape(blueprint.strategy)}`  \n"
        f"**Target:** `{html.escape(blueprint.target_profile)}`"
    )
    st.caption(f"{len(blueprint.waves)} migration waves · {len(blueprint.units)} units")
    with st.expander("View roadmap details"):
        for wave in blueprint.waves:
            st.markdown(f"**{wave.wave_id}: {wave.title}**")
            for unit_id in wave.unit_ids:
                unit = next((item for item in blueprint.units if item.unit_id == unit_id), None)
                if unit:
                    st.markdown(
                        f"- `{html.escape(unit.source_scope)}` → **{html.escape(unit.action)}** "
                        f"({html.escape(unit.classification)})"
                    )
            st.caption("Exit criteria: " + "; ".join(wave.exit_criteria))
        st.markdown("#### Capabilities")
        for capability in blueprint.capabilities:
                    st.markdown(f"- **{capability.capability}**: `{capability.status}`")


def render_reverse_documentation() -> None:
    documentation = st.session_state["project_snapshot"].reverse_documentation
    if documentation is None:
        return
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">03 / REVERSE DOCUMENTATION</div>', unsafe_allow_html=True)
    st.header("Legacy behavior contract")
    st.markdown(documentation.summary)
    columns = st.columns(4)
    for column, label, value in zip(
        columns,
        ("Modules", "Side effects", "Scenarios", "Open gaps"),
        (len(documentation.modules), len(documentation.side_effects), len(documentation.scenarios), len(documentation.gaps)),
    ):
        column.markdown(
            f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>',
            unsafe_allow_html=True,
        )
    with st.expander("View side effects and executable scenarios", expanded=bool(documentation.side_effects)):
        if documentation.side_effects:
            st.markdown("#### Event-driven behavior")
            for effect in documentation.side_effects:
                callback = effect.callback or "registered callback"
                st.markdown(
                    f"- **{html.escape(effect.trigger)}** via `{html.escape(callback)}` "
                    f"({html.escape(effect.source_path)}:{effect.start_line}) · `{html.escape(effect.kind)}`"
                )
        st.markdown("#### Scenarios")
        for scenario in documentation.scenarios:
            st.markdown(f"- `{html.escape(scenario.scenario_id)}` {html.escape(scenario.title)}")
        if documentation.gaps:
            st.warning("Open questions and evidence gaps")
            for gap in documentation.gaps:
                st.markdown(f"- {html.escape(gap)}")
    if not st.session_state.get("reverse_documentation_enriched", False):
        st.info("The baseline is deterministic. Azure can add semantic product intent and module explanations without overriding observed side effects.")
        if azure_rate_limit_active():
            st.warning("Azure is temporarily rate-limited. The deterministic baseline is still available; wait about a minute before retrying.")
        if st.button("Enrich reverse documentation with Azure", type="secondary", use_container_width=True, disabled=azure_rate_limit_active()):
            record_activity("Reverse documentation enrichment started")
            set_activity_progress(0.45, "Enriching reverse documentation")
            try:
                with st.status("Enriching reverse documentation...", expanded=True) as status:
                    enriched = azure_engine().document(st.session_state["project_snapshot"])
                    st.session_state["project_snapshot"] = replace(
                        st.session_state["project_snapshot"],
                        reverse_documentation=enriched,
                    )
                    st.session_state["reverse_documentation_enriched"] = True
                    record_activity("Reverse documentation enriched")
                    set_activity_progress(0.55, "Reverse documentation enriched")
                    status.update(label="Reverse documentation enriched", state="complete")
                    st.rerun()
            except LLMRateLimitError:
                mark_azure_rate_limited()
                record_activity("Azure retries exhausted; deterministic documentation preserved")
                st.warning("Azure is rate-limited. The deterministic reverse documentation remains available. Please retry after the cooldown.")
            except Exception as error:
                record_activity("Reverse documentation enrichment failed")
                st.error(f"Reverse documentation enrichment failed: {error}")
    if not st.session_state.get("reverse_documentation_approved", False):
        st.warning("Review the behavior contract before creating a migration plan.")
        if st.button("Approve reverse documentation", type="primary", use_container_width=True):
            st.session_state["reverse_documentation_approved"] = True
            st.rerun()


def render_plan(plan: MigrationPlan) -> None:
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">05 / ARCHITECTURE MAP</div>', unsafe_allow_html=True)
    st.header("Migration plan")
    st.markdown(plan.project_summary)
    with st.expander(f"Route mappings ({len(plan.routes)})"):
        for route in plan.routes:
            st.markdown(f'<div class="route"><span>{html.escape(route.source)}</span><span class="route-arrow">→</span><span>{html.escape(route.target)} · {html.escape(route.purpose)}</span></div>', unsafe_allow_html=True)
    left, right = st.columns(2, gap="large")
    with left:
        with st.expander(f"Preserved behavior ({len(plan.preserved_behaviors)})"):
            for item in plan.preserved_behaviors:
                st.markdown(f"- {item}")
        with st.expander(f"Shared components ({len(plan.shared_components)})"):
            for item in plan.shared_components:
                st.markdown(f"- {item}")
    with right:
        with st.expander(f"Manual work ({len(plan.unsupported_behaviors)})", expanded=True):
            for item in plan.unsupported_behaviors:
                st.markdown(f"- {item}")
        with st.expander(f"Risks ({len(plan.risks)})", expanded=True):
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
                    reset_activity()
                    set_activity_progress(0.2, "Source inspected")
                    record_activity(f"Pinned GitHub source to {source.sha[:12]}")
                    for key in ("migration_plan", "migration_approved", "reverse_documentation_enriched", "reverse_documentation_approved", "usage_ledger", "generated_project", "project_zip", "github_push_result", "migration_branch_name"):
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
        uploaded = st.file_uploader("Legacy web project ZIP", type=["zip"], help="Maximum upload: 100 MB compressed and 250 MB uncompressed. Common generated and dependency directories are excluded automatically.")
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
                reset_activity()
                set_activity_progress(0.2, "Source inspected")
                record_activity(f"Inspected ZIP source: {uploaded.name}")
                for key in ("migration_plan", "migration_approved", "reverse_documentation_enriched", "reverse_documentation_approved", "usage_ledger", "generated_project", "project_zip", "github_source", "github_push_result", "migration_branch_name"):
                    st.session_state.pop(key, None)
            except ValueError as error:
                st.error(str(error))
                return

    activity_target = st.empty()
    st.session_state["activity_target"] = activity_target
    set_activity_progress(0.3, "Reverse documentation ready")
    record_activity("Deterministic reverse documentation ready", key="baseline-ready")
    render_activity_log(activity_target)
    render_inventory()
    render_wesley()
    render_reverse_documentation()
    if not st.session_state.get("reverse_documentation_approved", False):
        return
    render_migration_blueprint()
    if azure_rate_limit_active():
        st.warning("Azure is temporarily rate-limited. Wait about a minute before starting another model request.")
    if st.button("Analyze migration with Azure OpenAI", type="primary", use_container_width=True, disabled=azure_rate_limit_active()):
        record_activity("Migration analysis started")
        set_activity_progress(0.65, "Analyzing migration")
        try:
            with st.status("Reading the legacy shape...", expanded=True) as status:
                st.write("Sending bounded, secret-filtered source evidence to Azure OpenAI")
                plan = azure_engine().analyze(st.session_state["project_snapshot"])
                st.session_state["migration_plan"] = plan
                st.session_state["migration_approved"] = False
                st.session_state.pop("generated_project", None)
                st.session_state.pop("project_zip", None)
                record_activity("Migration plan received")
                set_activity_progress(0.75, "Migration plan ready")
                status.update(label="Migration plan ready", state="complete")
        except LLMRateLimitError:
            mark_azure_rate_limited()
            record_activity("Azure retries exhausted; reviewed understanding preserved")
            st.warning("Azure is rate-limited. Your reviewed understanding is preserved; retry after the cooldown.")
        except Exception as error:
            record_activity("Migration analysis failed")
            st.error(f"Azure analysis failed: {error}")

    plan = st.session_state.get("migration_plan")
    if not plan:
        return
    render_plan(plan)
    if not st.session_state.get("migration_approved", False):
        st.warning("Review the migration roadmap and plan before generating target code.")
        if st.button("Approve migration plan", type="primary", use_container_width=True):
            st.session_state["migration_approved"] = True
            st.session_state["migration_plan"] = plan.model_copy(update={"approval_status": "approved"})
            record_activity("Migration plan approved")
            st.rerun()
        return
    st.markdown('<div class="rule"></div>', unsafe_allow_html=True)
    st.markdown('<div class="eyebrow">06 / CODE GENERATION</div>', unsafe_allow_html=True)
    st.header("Build the modern starter")
    st.caption("Generation is constrained to presentation files. Backend behavior remains an explicit migration task.")
    if st.button("Generate guarded Next.js project", type="primary", use_container_width=True, disabled=azure_rate_limit_active()):
        record_activity("Target code generation started")
        set_activity_progress(0.85, "Generating target project")
        try:
            with st.status("Compiling the migration...", expanded=True) as status:
                st.write("Generating schema-constrained Next.js source")
                generated = azure_engine().generate(st.session_state["project_snapshot"], plan)
                st.write("Validating paths, imports, required files, and unsafe APIs")
                st.session_state["generated_project"] = generated
                st.session_state["project_zip"] = build_project_zip(st.session_state["project_snapshot"], plan, generated)
                record_activity("Target files validated and packaged")
                set_activity_progress(1.0, "Migration package ready")
                status.update(label="Next.js starter ready", state="complete")
        except LLMRateLimitError:
            mark_azure_rate_limited()
            record_activity("Azure retries exhausted; approved plan preserved")
            st.warning("Azure is rate-limited. Your approved migration plan is preserved; retry after the cooldown.")
        except Exception as error:
            record_activity("Target generation failed")
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
            record_activity("GitHub migration branch export started")
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
                    record_activity("GitHub migration branch created")
                    status.update(label="Migration branch created", state="complete")
            except (RuntimeError, ValueError) as error:
                record_activity("GitHub branch export failed")
                st.error(f"GitHub export failed: {error}")
        result = st.session_state.get("github_push_result")
        if result:
            st.success(f"Created `{result.branch}` at commit `{result.commit_sha[:12]}`.")
            st.link_button("Open migration branch on GitHub", result.url, use_container_width=True)


if __name__ == "__main__":
    main()
