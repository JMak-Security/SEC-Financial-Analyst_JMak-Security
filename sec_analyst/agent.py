"""Evidence-first analyst agents and asynchronous workflow coordinator."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .edgar import SecEdgarClient, recent_filings
from .duckdb_store import DuckDBFinancialStore
from .health import FinancialHealthAnalyst, render_health_markdown
from .inline_xbrl import InlineXbrlError
from .manual import parse_manual_financials_csv
from .models import Filing, FinancialStatements
from .normalize import normalize_companyfacts
from .ratios import calculate_ratios
from .storage import FinancialStore
from .taxonomy import TaxonomyMappings
from .workspace import WorkspaceManager
from .xbrl_validation import XbrlValidationError, validate_companyfacts


@dataclass
class AnalysisResult:
    company_name: str
    cik: str
    filings: list[dict[str, Any]]
    statements: list[dict[str, Any]]
    ratios: list[dict[str, Any]]
    key_points: list[str]
    conclusion: str
    warnings: list[str]
    source: str
    health_report: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "company_name": self.company_name,
            "cik": self.cik,
            "filings": self.filings,
            "statements": self.statements,
            "ratios": self.ratios,
            "key_points": self.key_points,
            "conclusion": self.conclusion,
            "warnings": self.warnings,
            "source": self.source,
            "health_report": self.health_report,
        }


class FilingRetrievalAgent:
    def __init__(self, client: SecEdgarClient) -> None:
        self.client = client

    async def retrieve(
        self, company: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return await asyncio.to_thread(self.client.fetch_company, company)


class StatementNormalizationAgent:
    def normalize(
        self,
        companyfacts: dict[str, Any],
        filings: list[Filing],
        taxonomies: TaxonomyMappings | None = None,
    ) -> list[FinancialStatements]:
        taxonomies = taxonomies or TaxonomyMappings({}, {})
        return [
            normalize_companyfacts(
                companyfacts,
                filing,
                custom_tag_mappings=taxonomies.custom_gaap,
                non_gaap_tag_mappings=taxonomies.non_gaap,
            )
            for filing in filings
        ]


class RatioAnalysisAgent:
    def analyze(
        self, statements: list[FinancialStatements]
    ) -> list[dict[str, float | None]]:
        return [calculate_ratios(statement) for statement in statements]


class SynthesisAgent:
    RATIO_LABELS = {
        "current_ratio": "current ratio",
        "quick_ratio": "quick ratio",
        "liabilities_to_assets": "liabilities-to-assets",
        "net_margin": "net margin",
        "operating_cash_flow_ratio": "operating-cash-flow ratio",
    }

    def synthesize(
        self,
        statements: list[FinancialStatements],
        ratio_rows: list[dict[str, float | None]],
    ) -> tuple[list[str], str, list[str]]:
        if not statements:
            return [], "No eligible 10-K/10-Q statements were available.", [
                "No supported SEC filing facts were found for the selected period."
            ]
        latest = ratio_rows[0]
        latest_statement = statements[0]
        points: list[str] = []
        warnings: list[str] = []

        for metric, label in (
            ("current_ratio", "Current ratio"),
            ("quick_ratio", "Quick ratio"),
            ("liabilities_to_assets", "Liabilities-to-assets"),
            ("net_margin", "Net margin"),
            ("operating_cash_flow_ratio", "Operating cash flow/current liabilities"),
        ):
            value = latest.get(metric)
            if value is not None:
                display = f"{value:.2f}x" if metric.endswith("ratio") else f"{value:.1%}"
                points.append(f"{label}: {display} ({latest_statement.filing.period_end}).")
            else:
                warnings.append(
                    f"{label} is unavailable because a required SEC fact is missing "
                    "or its denominator is zero."
                )

        current_ratio = latest.get("current_ratio")
        if current_ratio is not None and current_ratio < 1:
            points.append(
                "Near-term liquidity flag: current assets are below current liabilities."
            )
        if current_ratio is not None and current_ratio >= 1.5:
            points.append("Current assets provide a buffer against current liabilities.")
        debt_assets = latest.get("liabilities_to_assets")
        if debt_assets is not None and debt_assets > 0.6:
            points.append(
                "Leverage watch: reported liabilities exceed 60% of reported assets."
            )
        net_margin = latest.get("net_margin")
        if net_margin is not None and net_margin < 0:
            points.append("Profitability flag: the latest reported net margin is negative.")
        operating_cash = latest_statement.cash_flow_statement.get(
            "operating_cash_flow"
        )
        if operating_cash is not None and operating_cash < 0:
            points.append("Cash-flow flag: operating activities used cash in this period.")
        if latest_statement.income_statement.get("revenue") is None:
            warnings.append(
                "Revenue was not found in the standardized SEC facts; custom issuer "
                "XBRL concepts may be needed."
            )

        if len(ratio_rows) > 1:
            earlier = ratio_rows[-1]
            for metric in ("current_ratio", "net_margin"):
                new_value = latest.get(metric)
                old_value = earlier.get(metric)
                if new_value is not None and old_value is not None:
                    delta = new_value - old_value
                    label = self.RATIO_LABELS[metric]
                    unit = "percentage points" if metric == "net_margin" else "turns"
                    scaled_delta = delta * 100 if metric == "net_margin" else delta
                    direction = "increased" if delta > 0 else "decreased"
                    points.append(
                        f"{label.capitalize()} {direction} by "
                        f"{abs(scaled_delta):.2f} {unit} versus the oldest analyzed filing."
                    )

        if not points:
            points.append("Insufficient standardized facts for a quantitative signal.")
        severe_flags = [
            current_ratio is not None and current_ratio < 1,
            net_margin is not None and net_margin < 0,
            operating_cash is not None and operating_cash < 0,
            debt_assets is not None and debt_assets > 0.6,
        ]
        if sum(severe_flags) >= 2:
            conclusion = (
                "The selected filing shows multiple balance-sheet or earnings "
                "watch items; review the cited line items and filing disclosures "
                "before drawing a conclusion."
            )
        elif any(severe_flags):
            conclusion = (
                "The selected filing shows at least one financial watch item, "
                "while the available standardized facts are not a complete "
                "assessment of the business."
            )
        else:
            conclusion = (
                "The available standardized facts do not trigger the configured "
                "liquidity, leverage, profitability, or operating-cash-flow flags. "
                "This is a screening result, not a valuation or investment view."
            )
        return points, conclusion, warnings


class FinancialAnalystAgent:
    """Coordinate retrieval, normalization, ratio, persistence, and synthesis tools."""

    def __init__(
        self,
        workspace: WorkspaceManager,
        client: SecEdgarClient | None = None,
        health_analyst: FinancialHealthAnalyst | None = None,
    ) -> None:
        self.workspace = workspace
        self.client = client
        self.store = FinancialStore(self.workspace.root / "financials.sqlite3")
        self.lineage_store = DuckDBFinancialStore(
            self.workspace.root / "financial_lineage.duckdb"
        )
        self.normalizer = StatementNormalizationAgent()
        self.ratio_agent = RatioAnalysisAgent()
        self.synthesizer = SynthesisAgent()
        self.health_analyst = health_analyst or FinancialHealthAnalyst()

    async def analyze_sec(self, company: str, filing_count: int = 4) -> AnalysisResult:
        if self.client is None:
            raise ValueError("A SEC client with a contact email is required for EDGAR.")
        submissions, companyfacts = await FilingRetrievalAgent(
            self.client
        ).retrieve(company)
        cik = str(companyfacts.get("cik") or submissions.get("cik") or "").zfill(10)
        self.workspace.save_json(
            f"sec_cache/{cik}_submissions.json", submissions
        )
        self.workspace.save_json(
            f"sec_cache/{cik}_companyfacts.json", companyfacts
        )
        selected_filings = recent_filings(submissions, cik, filing_count)
        inline_warnings: list[str] = []
        for filing in selected_filings:
            try:
                inline_facts = await asyncio.to_thread(
                    self.client.fetch_inline_xbrl_facts, filing
                )
            except (SecApiError, InlineXbrlError, ValueError) as exc:
                inline_warnings.append(
                    f"Inline XBRL for {filing.accession_number} could not be "
                    f"loaded; custom-tag mapping may be incomplete: {exc}"
                )
                continue
            facts_root = companyfacts.setdefault("facts", {})
            for namespace, concepts in inline_facts.items():
                target_namespace = facts_root.setdefault(namespace, {})
                for concept, details in concepts.items():
                    target_concept = target_namespace.setdefault(
                        concept, {"units": {}}
                    )
                    target_units = target_concept.setdefault("units", {})
                    for unit, entries in details["units"].items():
                        existing = target_units.setdefault(unit, [])
                        known_contexts = {
                            (
                                item.get("accn"),
                                item.get("form"),
                                item.get("start"),
                                item.get("end"),
                            )
                            for item in existing
                            if isinstance(item, dict)
                        }
                        existing.extend(
                            entry
                            for entry in entries
                            if (
                                entry.get("accn"),
                                entry.get("form"),
                                entry.get("start"),
                                entry.get("end"),
                            )
                            not in known_contexts
                        )
        return await self._analyze_payloads(
            submissions,
            companyfacts,
            cik,
            filing_count,
            "SEC EDGAR",
            ticker=self._company_ticker(company, submissions),
            use_live_sources=True,
            ingestion_warnings=inline_warnings,
        )

    async def analyze_local(self, filing_count: int = 4) -> AnalysisResult:
        submissions, companyfacts = self.workspace.discover_sec_payloads()
        cik = str(companyfacts.get("cik") or submissions.get("cik") or "")
        if not cik:
            raise ValueError("The selected SEC JSON files do not include a CIK.")
        return await self._analyze_payloads(
            submissions,
            companyfacts,
            cik.zfill(10),
            filing_count,
            "Local SEC JSON",
        )

    async def analyze_manual(
        self,
        company_name: str,
        content: bytes,
        ticker: str | None = None,
        use_live_sources: bool = True,
        health_analyst: FinancialHealthAnalyst | None = None,
    ) -> AnalysisResult:
        statements = parse_manual_financials_csv(content, company_name)
        ordered = sorted(
            statements, key=lambda item: item.filing.period_end, reverse=True
        )
        ratio_rows = self.ratio_agent.analyze(ordered)
        for statement, ratios in zip(ordered, ratio_rows, strict=True):
            await asyncio.to_thread(
                self.lineage_store.save_analysis, statement, ratios
            )
        active_health_analyst = health_analyst or self.health_analyst
        health_report = await active_health_analyst.analyze(
            company_name,
            ordered,
            ticker=ticker,
            use_live_sources=use_live_sources,
        )
        result = AnalysisResult(
            company_name=company_name.strip(),
            cik="",
            filings=[statement.filing.as_dict() for statement in ordered],
            statements=[statement.as_dict() for statement in ordered],
            ratios=[
                {
                    "period_end": statement.filing.period_end,
                    "form": statement.filing.form,
                    **ratios,
                }
                for statement, ratios in zip(ordered, ratio_rows, strict=True)
            ],
            key_points=[
                finding["evidence"] for finding in health_report["findings"]
            ],
            conclusion=health_report["executive_summary"],
            warnings=health_report["limitations"],
            source="User-supplied financial statements",
            health_report=health_report,
        )
        safe_company = self.workspace.safe_name(company_name).lower()
        period_end = ordered[0].filing.period_end
        base_name = f"reports/{safe_company}_{period_end}_health"
        self.workspace.save_json(f"{base_name}.json", result.as_dict())
        self.workspace.save_text(
            f"{base_name}.md", render_health_markdown(health_report)
        )
        return result

    async def _analyze_payloads(
        self,
        submissions: dict[str, Any],
        companyfacts: dict[str, Any],
        cik: str,
        filing_count: int,
        source: str,
        ticker: str | None = None,
        use_live_sources: bool = False,
        ingestion_warnings: list[str] | None = None,
    ) -> AnalysisResult:
        filings = recent_filings(submissions, cik, filing_count)
        if not filings:
            raise ValueError("No eligible SEC 10-K/10-Q filings were found.")
        validation_issues = validate_companyfacts(companyfacts, expected_cik=cik)
        for filing in filings:
            validation_issues.extend(
                validate_companyfacts(
                    companyfacts,
                    expected_cik=cik,
                    filing_accession=filing.accession_number,
                )
            )
        mappings_path = self.workspace.root / "taxonomy_mappings.json"
        taxonomies = (
            TaxonomyMappings.from_json(mappings_path.read_bytes())
            if mappings_path.is_file()
            else TaxonomyMappings({}, {})
        )
        statements = self.normalizer.normalize(companyfacts, filings, taxonomies)
        ratio_rows = self.ratio_agent.analyze(statements)
        for statement, ratios in zip(statements, ratio_rows, strict=True):
            await asyncio.to_thread(self.store.save_analysis, statement, ratios)
            await asyncio.to_thread(
                self.lineage_store.save_analysis, statement, ratios
            )
        points, conclusion, warnings = self.synthesizer.synthesize(
            statements, ratio_rows
        )
        health_report = await self.health_analyst.analyze(
            filings[0].company_name,
            statements,
            ticker=ticker,
            use_live_sources=use_live_sources,
        )
        warnings.extend(health_report["limitations"])
        warnings.extend(ingestion_warnings or [])
        warnings.extend(
            f"XBRL validation warning at {issue.path}: {issue.message}"
            for issue in validation_issues
            if issue.severity == "warning"
        )
        result = AnalysisResult(
            company_name=filings[0].company_name,
            cik=cik,
            filings=[filing.as_dict() for filing in filings],
            statements=[statement.as_dict() for statement in statements],
            ratios=[
                {
                    "period_end": statement.filing.period_end,
                    "form": statement.filing.form,
                    **ratios,
                }
                for statement, ratios in zip(statements, ratio_rows, strict=True)
            ],
            key_points=points,
            conclusion=conclusion,
            warnings=warnings,
            source=source,
            health_report=health_report,
        )
        report_name = f"reports/{cik}_{filings[0].period_end}_analysis.json"
        self.workspace.save_json(report_name, result.as_dict())
        self.workspace.save_text(
            f"reports/{cik}_{filings[0].period_end}_health.md",
            render_health_markdown(health_report),
        )
        return result

    @staticmethod
    def _company_ticker(company: str, submissions: dict[str, Any]) -> str | None:
        from .companies import identify_company

        identity = identify_company(company)
        if identity.ticker:
            return identity.ticker
        tickers = submissions.get("tickers")
        if isinstance(tickers, list):
            for ticker in tickers:
                if isinstance(ticker, str) and ticker.strip():
                    return ticker.strip().upper()
        return None
