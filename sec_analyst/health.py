"""Evidence-first company health writeups enriched with optional live APIs."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, Sequence

import pandas as pd

from portfolio_risk.engine import RiskEngine

from .market import MarketDataError, YahooFinanceClient
from .models import FinancialStatements
from .ratios import calculate_ratios
from .search import BraveSearchClient, SearchResult, WebSearchError


class FinancialHealthAnalyst:
    """Coordinate statement, market-risk, and web-research analysis tools."""

    def __init__(
        self,
        market_client: YahooFinanceClient | None = None,
        search_client: BraveSearchClient | None = None,
    ) -> None:
        self.market_client = market_client or YahooFinanceClient()
        self.search_client = search_client or BraveSearchClient()

    async def analyze(
        self,
        company_name: str,
        statements: Sequence[FinancialStatements],
        ticker: str | None = None,
        use_live_sources: bool = False,
    ) -> dict[str, Any]:
        ordered = sorted(
            statements, key=lambda item: item.filing.period_end, reverse=True
        )
        ratio_rows = [calculate_ratios(statement) for statement in ordered]
        market_snapshot: dict[str, Any] | None = None
        market_risk: dict[str, Any] | None = None
        search_results: list[SearchResult] = []
        limitations: list[str] = []
        tool_trace = [
            "normalize and validate available financial statements",
            "calculate liquidity, solvency, profitability, and cash-flow ratios",
            "map evidence-backed findings to practical remediation options",
        ]
        if use_live_sources and ticker:
            tool_trace.append("retrieve read-only live equity quote and daily closes")
            market_task = asyncio.to_thread(self.market_client.fetch, ticker)
        else:
            market_task = None
            if use_live_sources:
                limitations.append(
                    "Live market data was not queried because no public ticker is known."
                )
        if use_live_sources and self.search_client.configured:
            tool_trace.append("search public web for company-specific financial context")
            search_task = asyncio.to_thread(
                self.search_client.search, company_name, 5
            )
        else:
            search_task = None
            if use_live_sources:
                limitations.append(
                    "Web research was not run; configure BRAVE_SEARCH_API_KEY to enable it."
                )
        if not use_live_sources:
            limitations.append(
                "Live market data and web research were not queried for this offline analysis."
            )
        tasks = [task for task in (market_task, search_task) if task is not None]
        results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
        result_index = 0
        if market_task is not None:
            result = results[result_index]
            result_index += 1
            if isinstance(result, BaseException):
                if not isinstance(result, (MarketDataError, ValueError)):
                    raise result
                limitations.append(f"Live market data unavailable: {result}")
            else:
                market_snapshot = result.as_dict()
                try:
                    returns = pd.DataFrame({result.ticker: result.daily_returns})
                    engine = RiskEngine(returns, {result.ticker: 1.0})
                    risk = engine.calculate(10_000.0, confidence=0.95)
                    monte_carlo = await engine.simulate_monte_carlo_async(
                        10_000.0, confidence=0.95, simulations=2_000, seed=42
                    )
                    stress = engine.stress_test(
                        {"Illustrative 20% equity-price shock": {result.ticker: -0.2}},
                        10_000.0,
                    )
                    market_risk = {
                        "interpretation": (
                            "Public equity price-history risk only; not a measure of "
                            "balance-sheet solvency, business value, or a forecast."
                        ),
                        "risk": asdict(risk),
                        "monte_carlo": asdict(monte_carlo),
                        "stress_results": [asdict(item) for item in stress],
                    }
                    tool_trace.extend(
                        [
                            "calculate 95% historical and parametric VaR/CVaR",
                            "run seeded 2,000-path Monte Carlo simulation",
                            "apply an illustrative equity-price stress scenario",
                        ]
                    )
                except ValueError as exc:
                    limitations.append(f"Market risk metrics unavailable: {exc}")
        if search_task is not None:
            result = results[result_index]
            if isinstance(result, BaseException):
                if not isinstance(result, (WebSearchError, ValueError)):
                    raise result
                limitations.append(f"Web research unavailable: {result}")
            else:
                search_results = result

        findings, recommendations = self._financial_findings(ordered, ratio_rows)
        if not ordered:
            status = "insufficient data"
            summary = (
                "No company-specific financial statements were supplied or found. "
                "A financial condition cannot be responsibly assessed from the "
                "company name or public search snippets alone."
            )
            recommendations = [
                {
                    "priority": "data",
                    "action": (
                        "Provide at least two reporting periods of balance sheets, "
                        "income statements, and cash-flow statements; identify "
                        "currency, accounting basis, and audit status."
                    ),
                    "reason": "No quantitative company financial evidence is available.",
                },
                {
                    "priority": "data",
                    "action": (
                        "For a private company, reconcile management accounts to "
                        "bank statements, debt schedules, and tax filings before "
                        "relying on a health assessment."
                    ),
                    "reason": "Private-company data is not standardized in SEC CompanyFacts.",
                },
            ]
            limitations.append(
                "No standardized SEC statements were available; search results are "
                "discovery leads, not verified financial statements."
            )
        elif any(item["severity"] == "high" for item in findings):
            status = "high-priority review"
            summary = (
                "The latest supplied filing contains at least one material liquidity "
                "or cash-flow watch item. Validate the cited source facts and "
                "management assumptions before taking action."
            )
        elif findings:
            status = "watch"
            summary = (
                "The latest supplied filing contains financial watch items that "
                "warrant owner-level review and monitoring."
            )
        else:
            status = "no configured red flags"
            summary = (
                "Available standardized facts did not cross this screening's "
                "configured liquidity, leverage, profitability, or cash-flow "
                "thresholds. This does not establish financial health."
            )
        if ordered and len(ordered) == 1:
            limitations.append(
                "Only one reporting period is available; trend and seasonality "
                "cannot be assessed."
            )
        sources = [
            {
                "type": item.filing.form,
                "name": item.filing.company_name,
                "period_end": item.filing.period_end,
                "currency": item.currency,
                "accession_number": item.filing.accession_number,
                "source_tags": item.source_tags,
            }
            for item in ordered
        ]
        return {
            "company_name": company_name,
            "ticker": ticker,
            "status": status,
            "executive_summary": summary,
            "findings": findings,
            "recommendations": recommendations,
            "financial_evidence": [
                {
                    "period_end": item.filing.period_end,
                    "form": item.filing.form,
                    "ratios": ratios,
                    "currency": item.currency,
                }
                for item, ratios in zip(ordered, ratio_rows, strict=True)
            ],
            "sources": sources,
            "market_snapshot": market_snapshot,
            "market_risk": market_risk,
            "web_research": [item.as_dict() for item in search_results],
            "tool_trace": tool_trace,
            "limitations": limitations,
            "disclaimer": (
                "Decision-support screening only; not an audit, credit rating, "
                "valuation, investment recommendation, or substitute for "
                "professional advice."
            ),
        }

    @staticmethod
    def _financial_findings(
        statements: Sequence[FinancialStatements],
        ratio_rows: Sequence[dict[str, float | None]],
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        if not statements:
            return [], []
        latest = statements[0]
        ratios = ratio_rows[0]
        period = latest.filing.period_end
        findings: list[dict[str, str]] = []
        recommendations: list[dict[str, str]] = []

        def add(
            metric: str,
            severity: str,
            title: str,
            evidence: str,
            action: str,
        ) -> None:
            findings.append(
                {
                    "metric": metric,
                    "severity": severity,
                    "title": title,
                    "evidence": evidence,
                    "period_end": period,
                }
            )
            recommendations.append(
                {"priority": severity, "action": action, "reason": evidence}
            )

        current_ratio = ratios.get("current_ratio")
        if current_ratio is not None and current_ratio < 1:
            add(
                "current_ratio",
                "high",
                "Short-term liquidity pressure",
                f"Current ratio was {current_ratio:.2f}x at {period}; current assets "
                "were below current liabilities.",
                "Build a rolling 13-week cash forecast, accelerate collectible "
                "receivables, review inventory commitments, and renegotiate "
                "supplier/payment timing before liquidity is urgent.",
            )
        quick_ratio = ratios.get("quick_ratio")
        if quick_ratio is not None and quick_ratio < 1:
            add(
                "quick_ratio",
                "medium",
                "Limited liquid-asset coverage",
                f"Quick ratio was {quick_ratio:.2f}x at {period}.",
                "Set a minimum cash and near-cash buffer; review collections, "
                "customer credit terms, and the quality/aging of receivables.",
            )
        debt_assets = ratios.get("liabilities_to_assets")
        if debt_assets is not None and debt_assets > 0.6:
            add(
                "liabilities_to_assets",
                "medium",
                "Elevated balance-sheet leverage",
                f"Liabilities-to-assets was {debt_assets:.1%} at {period}.",
                "Map debt maturities, covenant headroom, and interest-rate exposure; "
                "prioritize refinancing options and cash retention before new "
                "discretionary borrowing.",
            )
        net_margin = ratios.get("net_margin")
        if net_margin is not None and net_margin < 0:
            add(
                "net_margin",
                "medium",
                "Negative net profitability",
                f"Net margin was {net_margin:.1%} at {period}.",
                "Break down contribution margin by product/customer, validate "
                "pricing and cost-to-serve, and gate discretionary spend against "
                "measurable unit-economics milestones.",
            )
        operating_cash = latest.cash_flow_statement.get("operating_cash_flow")
        if operating_cash is not None and operating_cash < 0:
            add(
                "operating_cash_flow",
                "high",
                "Operating activities consumed cash",
                f"Operating cash flow was {operating_cash:,.2f} "
                f"{latest.currency} for the period ending {period}.",
                "Reconcile earnings to working-capital movements, refresh a "
                "13-week cash forecast, and agree near-term cash actions with "
                "budget owners.",
            )
        free_cash_flow = ratios.get("free_cash_flow")
        if free_cash_flow is not None and free_cash_flow < 0:
            add(
                "free_cash_flow",
                "medium",
                "Negative free cash flow",
                f"Free cash flow was {free_cash_flow:,.2f} {latest.currency} "
                f"for the period ending {period}.",
                "Rank capital projects by risk-adjusted payback, stage or defer "
                "low-return spend, and distinguish temporary growth investment "
                "from structural operating cash burn.",
            )
        if not findings:
            recommendations.append(
                {
                    "priority": "monitor",
                    "action": (
                        "Maintain quarterly ratio and cash-flow monitoring, "
                        "validate assumptions against management forecasts, and "
                        "review debt maturities and customer concentration."
                    ),
                    "reason": (
                        "No configured threshold was crossed; missing or "
                        "non-standard facts can still hide material risks."
                    ),
                }
            )
        return findings, recommendations


def render_health_markdown(report: dict[str, Any]) -> str:
    """Render a portable writeup without treating web snippets as verified facts."""
    lines = [
        f"# Financial health analysis: {report['company_name']}",
        "",
        f"**Screening status:** {report['status']}",
        "",
        report["executive_summary"],
        "",
        "## Evidence-backed findings",
    ]
    if report["findings"]:
        for finding in report["findings"]:
            lines.extend(
                [
                    f"- **{finding['severity'].upper()} — {finding['title']}** "
                    f"({finding['period_end']}): {finding['evidence']}",
                ]
            )
    else:
        lines.append("- No threshold-triggered findings from available statements.")
    lines.extend(["", "## Potential solutions"])
    for recommendation in report["recommendations"]:
        lines.append(
            f"- **{recommendation['priority'].upper()}:** "
            f"{recommendation['action']} _Why: {recommendation['reason']}_"
        )
    if report["financial_evidence"]:
        lines.extend(["", "## Financial evidence"])
        for item in report["financial_evidence"]:
            shown_ratios = ", ".join(
                f"{key}={value:.4g}"
                for key, value in item["ratios"].items()
                if value is not None
            )
            lines.append(
                f"- {item['period_end']} ({item['form']}, {item['currency']}): "
                f"{shown_ratios or 'no computable ratios'}"
            )
    market_risk = report.get("market_risk")
    if market_risk:
        risk = market_risk["risk"]
        lines.extend(
            [
                "",
                "## Live market risk context",
                market_risk["interpretation"],
                f"- {report['market_snapshot']['ticker']} last price: "
                f"{report['market_snapshot']['price']:,.4g} "
                f"{report['market_snapshot']['currency']} "
                f"(observed {report['market_snapshot']['observed_at']}).",
                f"- {risk['observations']} daily return observations; daily "
                f"volatility {risk['daily_volatility']:.2%}.",
                f"- One-day 95% historical VaR/CVaR on a notional 10,000: "
                f"{risk['historical_var']:,.2f} / {risk['historical_cvar']:,.2f}; "
                f"parametric VaR/CVaR: {risk['parametric_var']:,.2f} / "
                f"{risk['parametric_cvar']:,.2f}.",
                f"- Seeded Monte Carlo VaR/CVaR: "
                f"{market_risk['monte_carlo']['var']:,.2f} / "
                f"{market_risk['monte_carlo']['cvar']:,.2f}.",
            ]
        )
        for stress in market_risk["stress_results"]:
            lines.append(
                f"- {stress['scenario']}: estimated illustrative loss "
                f"{stress['loss']:,.2f} on a notional 10,000."
            )
    if report["web_research"]:
        lines.extend(
            [
                "",
                "## Web research leads (unverified)",
                "Search snippets are discovery leads; validate claims in original sources.",
            ]
        )
        for item in report["web_research"]:
            lines.append(f"- [{item['title']}]({item['url']}): {item['snippet']}")
    if report["sources"]:
        lines.extend(["", "## Financial statement sources"])
        for source in report["sources"]:
            lines.append(
                f"- {source['name']}, {source['type']} period ending "
                f"{source['period_end']} ({source['currency']}); accession "
                f"{source['accession_number']}."
            )
            if source["source_tags"]:
                tags = ", ".join(
                    f"{metric}: {tag}"
                    for metric, tag in sorted(source["source_tags"].items())
                )
                lines.append(f"  - XBRL line-item tags: {tags}.")
    if report["limitations"]:
        lines.extend(["", "## Limitations"])
        lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(["", f"> {report['disclaimer']}", ""])
    return "\n".join(lines)
