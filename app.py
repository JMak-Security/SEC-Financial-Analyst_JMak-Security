"""Streamlit interface for SEC filing ingestion and analysis."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import streamlit as st

from sec_analyst.agent import AnalysisResult, FinancialAnalystAgent
from sec_analyst.edgar import SecApiError, SecEdgarClient
from sec_analyst.health import FinancialHealthAnalyst
from sec_analyst.health import render_health_markdown
from sec_analyst.workspace import WorkspaceManager


def _show_result(result: AnalysisResult) -> None:
    identity = f"CIK {result.cik}" if result.cik else result.source
    st.subheader(f"{result.company_name} · {identity}")
    st.markdown("### Conclusion")
    st.write(result.conclusion)
    st.markdown("### Key points")
    for point in result.key_points:
        st.markdown(f"- {point}")
    if result.health_report:
        report = result.health_report
        st.markdown("## Financial health writeup")
        st.markdown(f"**Screening status:** {report['status']}")
        st.write(report["executive_summary"])
        if report["findings"]:
            st.markdown("### Evidence-backed findings")
            for finding in report["findings"]:
                st.markdown(
                    f"- **{finding['severity'].upper()} — {finding['title']}** "
                    f"({finding['period_end']}): {finding['evidence']}"
                )
        else:
            st.info("No configured financial thresholds were triggered.")
        st.markdown("### Potential solutions")
        for recommendation in report["recommendations"]:
            st.markdown(
                f"- **{recommendation['priority'].upper()}:** "
                f"{recommendation['action']} "
                f"_Why: {recommendation['reason']}_"
            )
        if report["market_snapshot"]:
            snapshot = report["market_snapshot"]
            st.markdown("### Live equity-market context")
            st.caption(
                f"{snapshot['ticker']} last price {snapshot['price']:,.4g} "
                f"{snapshot['currency']} on {snapshot['exchange']} "
                f"(observed {snapshot['observed_at']}; source: Yahoo Finance)."
            )
        if report["market_risk"]:
            risk = report["market_risk"]["risk"]
            st.caption(report["market_risk"]["interpretation"])
            st.write(
                f"One-day 95% historical VaR/CVaR on a notional 10,000: "
                f"{risk['historical_var']:,.2f} / {risk['historical_cvar']:,.2f}; "
                f"parametric VaR/CVaR: {risk['parametric_var']:,.2f} / "
                f"{risk['parametric_cvar']:,.2f}."
            )
            monte_carlo = report["market_risk"]["monte_carlo"]
            st.write(
                f"Seeded Monte Carlo VaR/CVaR: {monte_carlo['var']:,.2f} / "
                f"{monte_carlo['cvar']:,.2f}."
            )
            st.dataframe(
                report["market_risk"]["stress_results"],
                use_container_width=True,
                hide_index=True,
            )
            st.markdown("#### Reference stress tests (illustrative)")
            st.caption(report["market_risk"]["stress_framework_note"])
            st.dataframe(
                [
                    {
                        "Scenario": item["scenario"]["title"],
                        "Estimated loss": item["loss"],
                        "Reference": item["scenario"]["reference_url"],
                    }
                    for item in report["market_risk"]["reference_stress_results"]
                ],
                use_container_width=True,
                hide_index=True,
            )
        if report["web_research"]:
            st.markdown("### Web research leads (unverified)")
            st.caption(
                "Search snippets are discovery leads, not verified claims; "
                "open and validate each original source."
            )
            for item in report["web_research"]:
                st.markdown(f"- [{item['title']}]({item['url']}): {item['snippet']}")
        if report["tool_trace"]:
            with st.expander("Agent workflow"):
                for step in report["tool_trace"]:
                    st.markdown(f"- {step}")
        if report["limitations"]:
            with st.expander("Health-analysis limitations"):
                for limitation in report["limitations"]:
                    st.warning(limitation)
        st.caption(report["disclaimer"])
        st.download_button(
            "Download financial health writeup (Markdown)",
            data=render_health_markdown(report),
            file_name=(
                f"{result.cik or WorkspaceManager.safe_name(result.company_name)}"
                "_health.md"
            ),
            mime="text/markdown",
        )
    if result.warnings:
        st.markdown("### Data limitations")
        for warning in result.warnings:
            st.warning(warning)
    st.markdown("### Filing ratios")
    st.dataframe(result.ratios, use_container_width=True, hide_index=True)
    st.markdown("### Normalized statements")
    for statement in result.statements:
        filing = statement["filing"]
        with st.expander(f'{filing["form"]} · {filing["period_end"]}'):
            for name in (
                "balance_sheet",
                "income_statement",
                "cash_flow_statement",
            ):
                st.markdown(f"**{name.replace('_', ' ').title()}**")
                st.json(statement[name])
    st.download_button(
        "Download analysis JSON",
        data=json.dumps(result.as_dict(), indent=2),
        file_name=(
            f"{result.cik or WorkspaceManager.safe_name(result.company_name)}"
            "_analysis.json"
        ),
        mime="application/json",
    )


def main() -> None:
    st.set_page_config(page_title="SEC Financial Analyst", layout="wide")
    st.title("SEC Financial Analyst")
    st.caption(
        "Local-first 10-K/10-Q ingestion, normalized statements, financial ratios, "
        "and evidence-based analyst notes."
    )

    with st.sidebar:
        st.header("Managed folder")
        default_folder = str(Path.cwd() / "data")
        folder_text = st.text_input(
            "Folder to search and manage",
            value=st.session_state.get("workspace_path", default_folder),
            help=(
                "This folder is the boundary for uploads, SEC cache, SQLite data, "
                "and reports."
            ),
        )
        if st.button("Use this folder"):
            try:
                workspace = WorkspaceManager(folder_text, create=True)
                st.session_state["workspace_path"] = str(workspace.root)
                st.success(f"Managing: {workspace.root}")
            except (OSError, ValueError) as exc:
                st.error(str(exc))

        active_path = st.session_state.get("workspace_path", default_folder)
        try:
            workspace = WorkspaceManager(active_path, create=True)
            st.caption(f"Active folder: `{workspace.root}`")
            st.caption("Application-managed: incoming/, sec_cache/, reports/, SQLite DB")
        except (OSError, ValueError) as exc:
            workspace = None
            st.error(f"Choose a usable folder: {exc}")

        st.header("SEC contact")
        contact_email = st.text_input(
            "Contact email for SEC User-Agent",
            value=os.environ.get("SEC_CONTACT_EMAIL", ""),
            help="A real contact email is required by SEC fair-access guidance.",
        )
        filing_count = st.slider("Recent filings", min_value=1, max_value=8, value=4)
        market_simulations = st.number_input(
            "Market-risk Monte Carlo paths",
            min_value=100,
            max_value=1_000_000,
            value=20_000,
            step=10_000,
            help="Chunked simulation. Runtime depends on hardware, horizon, and asset count.",
        )
        risk_backend = st.selectbox(
            "Simulation execution",
            options=["local", "dask"],
            help=(
                "Dask starts a local distributed worker pool. Configure "
                "DASK_SCHEDULER_ADDRESS to use an existing cluster."
            ),
        )

    if workspace is None:
        return

    st.markdown("### Analyze SEC filings")
    with st.form("sec_analysis"):
        company = st.text_input(
            "Company, ticker, or CIK",
            placeholder="e.g. NVIDIA, Nividia, NVDA, or 0000789019",
        )
        fetch_submitted = st.form_submit_button("Retrieve and analyze")
    if fetch_submitted:
        try:
            client = SecEdgarClient(contact_email)
            health_analyst = FinancialHealthAnalyst(
                market_simulations=int(market_simulations),
                risk_backend=risk_backend,
            )
            result = asyncio.run(
                FinancialAnalystAgent(
                    workspace, client, health_analyst=health_analyst
                ).analyze_sec(
                    company, filing_count
                )
            )
            st.session_state["analysis_result"] = result.as_dict()
        except (SecApiError, ValueError, OSError) as exc:
            st.error(str(exc))

    st.markdown("### Private or non-SEC company financials")
    st.write(
        "Upload a UTF-8 CSV with dated statement rows to analyze a private company, "
        "research lab, or organization without standardized SEC CompanyFacts. "
        "Blank cells remain unavailable; do not enter estimates as reported facts."
    )
    template = (
        Path(__file__).resolve().parent
        / "samples"
        / "company_financials_template.csv"
    )
    st.download_button(
        "Download blank financials CSV template",
        data=template.read_bytes(),
        file_name="company_financials_template.csv",
        mime="text/csv",
    )
    st.caption(
        "CSV columns: period_end, currency, cash_and_equivalents, "
        "short_term_investments, receivables, inventory, prepaid_expenses, "
        "current_assets, property_plant_equipment, total_assets, "
        "current_liabilities, long_term_debt, total_liabilities, "
        "shareholders_equity, revenue, cost_of_revenue, gross_profit, "
        "operating_income, net_income, operating_cash_flow, capital_expenditures. "
        "Use ISO dates (YYYY-MM-DD) and one row per period."
    )
    with st.form("manual_financials"):
        manual_company = st.text_input(
            "Company or organization name",
            placeholder="Votee AI, Wonderful, or PwC",
        )
        manual_ticker = st.text_input(
            "Optional public-market ticker",
            placeholder="NVDA",
            help="Used only for read-only public price history.",
        )
        manual_upload = st.file_uploader(
            "Financial statements CSV",
            type=["csv"],
            key="manual_financials_upload",
        )
        manual_submitted = st.form_submit_button("Analyze supplied statements")
    if manual_submitted:
        try:
            if manual_upload is None:
                raise ValueError("Upload a financial statements CSV to continue.")
            result = asyncio.run(
                FinancialAnalystAgent(workspace).analyze_manual(
                    manual_company,
                    manual_upload.getvalue(),
                    ticker=manual_ticker.strip() or None,
                    health_analyst=FinancialHealthAnalyst(
                        market_simulations=int(market_simulations),
                        risk_backend=risk_backend,
                    ),
                )
            )
            st.session_state["analysis_result"] = result.as_dict()
        except (OSError, ValueError, RuntimeError) as exc:
            st.error(str(exc))

    st.markdown("### Optional issuer taxonomy crosswalk")
    st.caption(
        "Upload a mapping for issuer extension tags and explicitly labeled "
        "non-GAAP values. The report keeps non-GAAP amounts separate and "
        "does not silently substitute them into GAAP ratios."
    )
    taxonomy_upload = st.file_uploader(
        "Taxonomy mapping JSON",
        type=["json"],
        key="taxonomy_mapping_upload",
        help=(
            'Example: {"custom_gaap":{"revenue":"issuer:Revenue"},'
            '"non_gaap":{"net_income":"issuer:AdjustedNetIncome"}}'
        ),
    )
    if taxonomy_upload and st.button("Save taxonomy mapping to managed folder"):
        try:
            from sec_analyst.taxonomy import TaxonomyMappings

            TaxonomyMappings.from_json(taxonomy_upload.getvalue())
            mapping_path = workspace.root / "taxonomy_mappings.json"
            mapping_path.write_bytes(taxonomy_upload.getvalue())
            st.success("Validated mapping saved to the active managed folder.")
        except (OSError, ValueError) as exc:
            st.error(str(exc))

    st.markdown("### Analyze local SEC JSON")
    st.write(
        "Upload both a SEC submissions JSON and a CompanyFacts JSON file, or place "
        "them anywhere inside the selected folder."
    )
    uploads = st.file_uploader(
        "SEC JSON files",
        type=["json"],
        accept_multiple_files=True,
        help="Synthetic samples are available in the project's samples folder.",
    )
    if st.button("Save uploads to managed folder", disabled=not uploads):
        try:
            saved: list[str] = []
            for upload in uploads:
                saved_path = workspace.save_upload(upload.name, upload.getvalue())
                saved.append(str(saved_path.relative_to(workspace.root)))
            st.success("Saved: " + ", ".join(saved))
        except (OSError, ValueError) as exc:
            st.error(str(exc))

    if st.button("Run offline analysis"):
        try:
            result = asyncio.run(FinancialAnalystAgent(workspace).analyze_local(filing_count))
            st.session_state["analysis_result"] = result.as_dict()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            st.error(str(exc))

    result_payload: dict[str, Any] | None = st.session_state.get("analysis_result")
    if result_payload:
        st.divider()
        result = AnalysisResult(**result_payload)
        _show_result(result)

    st.markdown("### JSON files in active folder")
    try:
        json_files = workspace.list_json_files()
        if json_files:
            st.code("\n".join(json_files))
        else:
            st.caption("No JSON files found in this folder yet.")
    except OSError as exc:
        st.error(f"Could not list the selected folder: {exc}")


if __name__ == "__main__":
    main()
