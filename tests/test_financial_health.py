from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

from sec_analyst.agent import FinancialAnalystAgent
from sec_analyst.companies import identify_company
from sec_analyst.edgar import SecEdgarClient
from sec_analyst.health import FinancialHealthAnalyst, render_health_markdown
from sec_analyst.manual import parse_manual_financials_csv
from sec_analyst.market import MarketDataError, YahooFinanceClient
from sec_analyst.models import Filing, FinancialStatements
from sec_analyst.search import BraveSearchClient, SearchResult, WebSearchError
from sec_analyst.workspace import WorkspaceManager
from portfolio_risk.engine import RiskEngine


ROOT = Path(__file__).resolve().parents[1]


def statement(
    *,
    name: str = "Synthetic Example Co",
    current_assets: float | None = 80.0,
    current_liabilities: float | None = 100.0,
    inventory: float | None = 20.0,
    total_assets: float | None = 200.0,
    total_liabilities: float | None = 150.0,
    equity: float | None = 50.0,
    revenue: float | None = 100.0,
    net_income: float | None = -5.0,
    operating_cash_flow: float | None = -10.0,
    capex: float | None = 4.0,
) -> FinancialStatements:
    filing = Filing(
        cik="",
        company_name=name,
        form="MANUAL",
        accession_number="manual-2025-12-31",
        filing_date="2026-03-01",
        period_end="2025-12-31",
    )
    return FinancialStatements(
        filing=filing,
        balance_sheet={
            "current_assets": current_assets,
            "current_liabilities": current_liabilities,
            "inventory": inventory,
            "prepaid_expenses": None,
            "cash_and_equivalents": 10.0,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "shareholders_equity": equity,
        },
        income_statement={"revenue": revenue, "net_income": net_income},
        cash_flow_statement={
            "operating_cash_flow": operating_cash_flow,
            "capital_expenditures": capex,
        },
        source_tags={},
        currency="USD",
    )


class CompanyIdentityTests(unittest.TestCase):
    def test_requested_company_routing_cases(self) -> None:
        fixture = json.loads(
            (ROOT / "samples" / "company_profiles.json").read_text(
                encoding="utf-8"
            )
        )
        for case in fixture["cases"]:
            with self.subTest(company=case["query"]):
                identity = identify_company(case["query"])
                self.assertEqual(identity.display_name, case["display_name"])
                self.assertEqual(identity.ticker, case["ticker"])
                self.assertEqual(identity.cik, case["cik"])
                self.assertEqual(
                    identity.public_filing_status, case["filing_status"]
                )

    def test_nividia_alias_resolves_without_network(self) -> None:
        client = SecEdgarClient("analyst@example.com")
        self.assertEqual(client.resolve_cik("Nividia"), "0001045810")
        self.assertEqual(client.resolve_cik("NVIDIA"), "0001045810")

    def test_blank_company_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "company name"):
            identify_company("  ")


class ManualStatementTests(unittest.TestCase):
    def test_parses_multiple_periods_and_preserves_blank_as_missing(self) -> None:
        payload = (
            "period_end,currency,current_assets,current_liabilities,inventory,"
            "total_assets,total_liabilities,shareholders_equity,revenue,net_income,"
            "operating_cash_flow,capital_expenditures\n"
            "2024-12-31,USD,50,80,10,120,90,30,60,-2,-4,5\n"
            "2025-12-31,USD,80,100,20,200,150,50,100,-5,-10,4\n"
        ).encode()
        statements = parse_manual_financials_csv(payload, "Votee AI")
        self.assertEqual(len(statements), 2)
        self.assertIsNone(statements[0].balance_sheet["cash_and_equivalents"])
        self.assertEqual(statements[1].income_statement["net_income"], -5.0)
        self.assertEqual(statements[1].filing.company_name, "Votee AI")

    def test_rejects_bad_dates_duplicates_nan_extra_cells_and_unknown_columns(self) -> None:
        prefix = "period_end,currency,current_assets\n"
        cases = (
            (prefix + "not-a-date,USD,1\n", "YYYY-MM-DD"),
            (
                prefix + "2025-12-31,USD,1\n2025-12-31,USD,2\n",
                "duplicate period",
            ),
            (prefix + "2025-12-31,USD,NaN\n", "must be finite"),
            (prefix + "2025-12-31,USD,1,extra\n", "more values"),
            ("period_end,unsupported\n2025-12-31,1\n", "unsupported columns"),
        )
        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    parse_manual_financials_csv(payload.encode(), "Example Co")

    def test_rejects_empty_or_oversized_csv_and_invalid_currency(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one data row"):
            parse_manual_financials_csv(b"period_end,current_assets\n", "Example Co")
        with self.assertRaisesRegex(ValueError, "1 MB"):
            parse_manual_financials_csv(b"x" * 1_000_001, "Example Co")
        with self.assertRaisesRegex(ValueError, "3-letter"):
            parse_manual_financials_csv(
                b"period_end,currency,current_assets\n2025-12-31,US,1\n",
                "Example Co",
            )
        with self.assertRaisesRegex(ValueError, "explicit"):
            parse_manual_financials_csv(
                b"period_end,current_assets\n2025-12-31,1\n", "Example Co"
            )

    def test_private_company_analysis_writes_json_and_markdown(self) -> None:
        payload = (
            "period_end,currency,current_assets,current_liabilities,inventory,"
            "total_assets,total_liabilities,shareholders_equity,revenue,net_income,"
            "operating_cash_flow,capital_expenditures\n"
            "2025-12-31,USD,80,100,20,200,150,50,100,-5,-10,4\n"
        ).encode()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = WorkspaceManager(temp_dir, create=True)
            result = asyncio.run(
                FinancialAnalystAgent(workspace).analyze_manual(
                    "Votee AI", payload, use_live_sources=False
                )
            )
            self.assertEqual(result.source, "User-supplied financial statements")
            self.assertEqual(result.health_report["status"], "high-priority review")
            self.assertTrue(
                list((workspace.root / "reports").glob("votee_ai_*_health.json"))
            )
            markdown = list(
                (workspace.root / "reports").glob("votee_ai_*_health.md")
            )
            self.assertEqual(len(markdown), 1)
            self.assertIn("Potential solutions", markdown[0].read_text("utf-8"))


class FinancialHealthTests(unittest.TestCase):
    def test_findings_include_evidence_and_actionable_solutions(self) -> None:
        report = asyncio.run(
            FinancialHealthAnalyst().analyze(
                "Synthetic Example Co", [statement()], use_live_sources=False
            )
        )
        metrics = {finding["metric"] for finding in report["findings"]}
        self.assertTrue(
            {
                "current_ratio",
                "quick_ratio",
                "net_margin",
                "operating_cash_flow",
                "free_cash_flow",
            }.issubset(metrics)
        )
        self.assertTrue(report["recommendations"])
        self.assertTrue(all(item["evidence"] for item in report["findings"]))
        self.assertIn("13-week cash forecast", report["recommendations"][0]["action"])
        markdown = render_health_markdown(report)
        self.assertIn("Evidence-backed findings", markdown)
        self.assertIn("Potential solutions", markdown)
        self.assertIn("not queried for this offline analysis", " ".join(report["limitations"]))

    def test_missing_financials_do_not_create_company_health_claims(self) -> None:
        report = asyncio.run(
            FinancialHealthAnalyst().analyze(
                "Wonderful", [], use_live_sources=True
            )
        )
        self.assertEqual(report["status"], "insufficient data")
        self.assertEqual(report["findings"], [])
        self.assertIn("cannot be responsibly assessed", report["executive_summary"])
        self.assertIn("BRAVE_SEARCH_API_KEY", " ".join(report["limitations"]))
        self.assertIn("no public ticker", " ".join(report["limitations"]))

    def test_live_market_and_web_tools_are_orchestrated_with_mock_data(self) -> None:
        snapshot = Mock()
        snapshot.as_dict.return_value = {
            "ticker": "NVDA",
            "currency": "USD",
            "exchange": "NASDAQ",
            "observed_at": "2026-11-03",
            "price": 100.0,
            "source_url": "https://example.test/quote",
            "return_observations": 6,
        }
        snapshot.ticker = "NVDA"
        snapshot.daily_returns = [-0.08, -0.02, 0.01, 0.02, 0.03, 0.04]
        market_client = Mock()
        market_client.fetch.return_value = snapshot
        search_client = Mock()
        search_client.configured = True
        search_client.search.return_value = [
            SearchResult(
                "Company filing",
                "https://example.test/source",
                "Unverified source snippet.",
            )
        ]
        report = asyncio.run(
            FinancialHealthAnalyst(market_client, search_client).analyze(
                "NVIDIA Corporation",
                [statement(name="NVIDIA Corporation")],
                ticker="NVDA",
                use_live_sources=True,
            )
        )
        self.assertIsNotNone(report["market_risk"])
        self.assertEqual(report["web_research"][0]["title"], "Company filing")
        self.assertTrue(
            any("Monte Carlo" in item for item in report["tool_trace"])
        )
        market_client.fetch.assert_called_once_with("NVDA")
        search_client.search.assert_called_once_with("NVIDIA Corporation", 5)


class IntegratedPortfolioRiskTests(unittest.TestCase):
    def test_seeded_risk_metrics_and_stress_are_reproducible(self) -> None:
        returns = pd.DataFrame(
            {"NVDA": [-0.08, -0.02, 0.01, 0.02, 0.03, 0.04]}
        )
        engine = RiskEngine(returns, {"NVDA": 1.0})
        report = engine.calculate(10_000.0, confidence=0.95)
        first = engine.simulate_monte_carlo(
            10_000.0, simulations=500, seed=7
        )
        second = engine.simulate_monte_carlo(
            10_000.0, simulations=500, seed=7
        )
        stress = engine.stress_test(
            {"selloff": {"NVDA": -0.2}}, 10_000.0
        )
        self.assertEqual(first, second)
        self.assertGreaterEqual(report.historical_var, 0)
        self.assertGreaterEqual(report.historical_cvar, report.historical_var)
        self.assertGreaterEqual(first.cvar, first.var)
        self.assertEqual(stress[0].loss, 2_000.0)

    def test_risk_engine_rejects_bad_returns_and_confidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-finite"):
            RiskEngine(pd.DataFrame({"NVDA": [-0.1, float("nan")]}), {"NVDA": 1.0})
        engine = RiskEngine(
            pd.DataFrame({"NVDA": [-0.01, 0.02]}), {"NVDA": 1.0}
        )
        with self.assertRaisesRegex(ValueError, "Confidence"):
            engine.calculate(10_000.0, confidence=1.0)


class ExternalProviderTests(unittest.TestCase):
    def test_market_api_parses_prices_and_rejects_unusable_history(self) -> None:
        client = YahooFinanceClient()
        response = Mock()
        response.json.return_value = {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 12.0,
                            "regularMarketTime": 1_800_000_000,
                            "currency": "USD",
                            "exchangeName": "NASDAQ",
                        },
                        "timestamp": [1, 2, 3, 4, 5],
                        "indicators": {
                            "quote": [
                                {"close": [10.0, 11.0, None, 12.0, 13.0]}
                            ]
                        },
                    }
                ],
            }
        }
        response.raise_for_status.return_value = None
        client.session.get = Mock(return_value=response)
        result = client.fetch("nvda")
        self.assertEqual(result.ticker, "NVDA")
        self.assertAlmostEqual(result.daily_returns[0], 0.1)
        self.assertAlmostEqual(result.daily_returns[1], 13 / 12 - 1)
        self.assertEqual(result.as_dict()["return_observations"], 2)
        with self.assertRaisesRegex(ValueError, "ticker"):
            client.fetch("NVDA;bad")

    def test_market_api_surfaces_bad_response(self) -> None:
        client = YahooFinanceClient()
        response = Mock()
        response.json.return_value = {"chart": {"result": []}}
        response.raise_for_status.return_value = None
        client.session.get = Mock(return_value=response)
        with self.assertRaises(MarketDataError):
            client.fetch("NVDA")

    def test_search_requires_key_and_validates_result_count(self) -> None:
        client = BraveSearchClient(api_key="")
        with self.assertRaises(WebSearchError):
            client.search("NVIDIA")
        with self.assertRaises(ValueError):
            client.search("NVIDIA", max_results=11)

    def test_search_api_uses_company_query_and_returns_source_links(self) -> None:
        client = BraveSearchClient(api_key="test-key")
        response = Mock()
        response.json.return_value = {
            "web": {
                "results": [
                    {
                        "title": "Annual filing",
                        "url": "https://example.test/filing",
                        "description": "Open the filing to verify.",
                    }
                ]
            }
        }
        response.raise_for_status.return_value = None
        client.session.get = Mock(return_value=response)
        results = client.search("PwC")
        self.assertEqual(results[0].url, "https://example.test/filing")
        call = client.session.get.call_args
        self.assertEqual(call.kwargs["headers"]["X-Subscription-Token"], "test-key")
        self.assertIn('"PwC"', call.kwargs["params"]["q"])
        self.assertNotIn("revenue", call.kwargs["params"]["q"].lower())


if __name__ == "__main__":
    unittest.main()
