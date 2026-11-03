from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.generate_samples import build_payloads
from sec_analyst.agent import FinancialAnalystAgent
from sec_analyst.edgar import SecEdgarClient, recent_filings
from sec_analyst.models import Filing, FinancialStatements
from sec_analyst.normalize import normalize_companyfacts
from sec_analyst.ratios import calculate_ratios
from sec_analyst.storage import FinancialStore
from sec_analyst.workspace import WorkspaceManager


def sample_filing() -> Filing:
    return Filing(
        cik="0000000001",
        company_name="Synthetic Co",
        form="10-Q",
        accession_number="0000000001-26-000003",
        filing_date="2026-11-01",
        period_end="2026-09-30",
    )


class NormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        _, self.companyfacts = build_payloads()

    def test_selects_filing_accession_and_quarter_duration(self) -> None:
        statements = normalize_companyfacts(self.companyfacts, sample_filing())
        self.assertEqual(
            statements.income_statement["revenue"], 250_000_000.0
        )
        self.assertEqual(
            statements.cash_flow_statement["operating_cash_flow"], 35_000_000.0
        )
        self.assertEqual(
            statements.balance_sheet["current_assets"], 430_000_000.0
        )
        self.assertEqual(
            statements.source_tags["revenue"],
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        )

    def test_missing_fact_is_none_not_zero(self) -> None:
        facts = {"facts": {"us-gaap": {}}}
        statements = normalize_companyfacts(facts, sample_filing())
        self.assertIsNone(statements.income_statement["revenue"])

    def test_selects_reporting_currency_when_usd_is_not_present(self) -> None:
        for concept in self.companyfacts["facts"]["us-gaap"].values():
            concept["units"]["EUR"] = concept["units"].pop("USD")
        statements = normalize_companyfacts(self.companyfacts, sample_filing())
        self.assertEqual(statements.currency, "EUR")
        self.assertEqual(
            statements.income_statement["revenue"], 250_000_000.0
        )

    def test_excludes_other_accessions_and_wrong_period_duration(self) -> None:
        facts = {
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {
                                    "accn": "other-accession",
                                    "form": "10-Q",
                                    "start": "2026-07-01",
                                    "end": "2026-09-30",
                                    "val": 999,
                                },
                                {
                                    "accn": sample_filing().accession_number,
                                    "form": "10-Q",
                                    "start": "2026-01-01",
                                    "end": "2026-09-30",
                                    "val": 800,
                                },
                            ]
                        }
                    }
                }
            }
        }
        statements = normalize_companyfacts(facts, sample_filing())
        self.assertIsNone(statements.income_statement["revenue"])


class RatioTests(unittest.TestCase):
    def test_zero_denominators_and_missing_values_are_not_infinite(self) -> None:
        edge_cases = json.loads(
            (Path(__file__).resolve().parents[1] / "samples" / "edge_cases.json")
            .read_text(encoding="utf-8")
        )
        case = edge_cases["cases"][0]
        statements = FinancialStatements(
            filing=sample_filing(),
            balance_sheet=case["balance_sheet"],
            income_statement=case["income_statement"],
            cash_flow_statement=case["cash_flow_statement"],
            source_tags={},
            currency="USD",
        )
        ratios = calculate_ratios(statements)
        for metric, expected in case["expected"].items():
            self.assertEqual(ratios[metric], expected)

    def test_derived_gross_profit_and_quick_ratio(self) -> None:
        edge_cases = json.loads(
            (Path(__file__).resolve().parents[1] / "samples" / "edge_cases.json")
            .read_text(encoding="utf-8")
        )
        case = edge_cases["cases"][2]
        statements = FinancialStatements(
            filing=sample_filing(),
            balance_sheet={"current_assets": 100.0, "inventory": 20.0,
                           "prepaid_expenses": 5.0, "current_liabilities": 50.0},
            income_statement=case["income_statement"],
            cash_flow_statement=case["cash_flow_statement"],
            source_tags={},
            currency="USD",
        )
        ratios = calculate_ratios(statements)
        self.assertEqual(ratios["quick_ratio"], 1.5)
        self.assertEqual(ratios["gross_margin"], case["expected"]["gross_margin"])

    def test_missing_inventory_makes_quick_ratio_unavailable(self) -> None:
        edge_cases = json.loads(
            (Path(__file__).resolve().parents[1] / "samples" / "edge_cases.json")
            .read_text(encoding="utf-8")
        )
        case = edge_cases["cases"][1]
        statements = FinancialStatements(
            filing=sample_filing(),
            balance_sheet=case["balance_sheet"],
            income_statement=case["income_statement"],
            cash_flow_statement=case["cash_flow_statement"],
            source_tags={},
            currency="USD",
        )
        self.assertIsNone(calculate_ratios(statements)["quick_ratio"])


class FilingAndWorkspaceTests(unittest.TestCase):
    def test_sec_client_requires_contact_email(self) -> None:
        with self.assertRaisesRegex(ValueError, "contact email"):
            SecEdgarClient("not-an-email")

    def test_sec_client_fetches_submissions_and_companyfacts(self) -> None:
        client = SecEdgarClient("analyst@example.com")
        requested_urls: list[str] = []

        def fake_get_json(url: str) -> dict[str, int]:
            requested_urls.append(url)
            return {"cik": 1}

        client._get_json = fake_get_json
        submissions, companyfacts = client.fetch_company("1")
        self.assertEqual(submissions["cik"], 1)
        self.assertEqual(companyfacts["cik"], 1)
        self.assertEqual(
            requested_urls,
            [
                "https://data.sec.gov/submissions/CIK0000000001.json",
                "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
            ],
        )

    def test_filing_selection_skips_nonfinancial_forms(self) -> None:
        submissions, _ = build_payloads()
        recent = submissions["filings"]["recent"]
        row_values = {
            "form": "8-K",
            "filingDate": "2026-11-02",
            "reportDate": "2026-10-30",
            "accessionNumber": "0000000001-26-000004",
            "primaryDocument": "sample-8k.htm",
        }
        for field, value in row_values.items():
            recent[field].insert(1, value)
        filings = recent_filings(submissions, "0000000001", 2)
        self.assertEqual([filing.form for filing in filings], ["10-Q", "10-Q"])

    def test_upload_path_is_confined_and_json_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = WorkspaceManager(temp_dir, create=True)
            destination = manager.save_upload(r"..\..\payload.json", b"{}")
            self.assertTrue(destination.is_relative_to(manager.root))
            with self.assertRaises(ValueError):
                manager.save_upload("notes.txt", b"not JSON")

    def test_local_discovery_rejects_multiple_companies(self) -> None:
        submissions, companyfacts = build_payloads()
        second_submissions = json.loads(json.dumps(submissions))
        second_facts = json.loads(json.dumps(companyfacts))
        second_submissions["cik"] = 2
        second_facts["cik"] = 2
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = WorkspaceManager(temp_dir, create=True)
            for name, payload in (
                ("one_submissions.json", submissions),
                ("one_companyfacts.json", companyfacts),
                ("two_submissions.json", second_submissions),
                ("two_companyfacts.json", second_facts),
            ):
                manager.save_upload(name, json.dumps(payload).encode("utf-8"))
            with self.assertRaisesRegex(ValueError, "multiple companies"):
                manager.discover_sec_payloads()

    def test_offline_agent_creates_report_and_sql_rows(self) -> None:
        samples = Path(__file__).resolve().parents[1] / "samples"
        submissions = json.loads(
            (samples / "sample_submissions.json").read_text(encoding="utf-8")
        )
        companyfacts = json.loads(
            (samples / "sample_companyfacts.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = WorkspaceManager(temp_dir, create=True)
            manager.save_upload(
                "submissions.json",
                json.dumps(submissions).encode("utf-8"),
            )
            manager.save_upload(
                "companyfacts.json",
                json.dumps(companyfacts).encode("utf-8"),
            )
            result = asyncio.run(FinancialAnalystAgent(manager).analyze_local(2))
            self.assertEqual(result.company_name, "Example Synthetic Holdings")
            self.assertEqual(len(result.ratios), 2)
            self.assertTrue(result.key_points)
            self.assertTrue(result.conclusion)
            self.assertIsNotNone(result.health_report)
            self.assertTrue(list((manager.root / "reports").glob("*_analysis.json")))
            self.assertTrue(list((manager.root / "reports").glob("*_health.md")))
            with closing(sqlite3.connect(manager.root / "financials.sqlite3")) as connection:
                count = connection.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
            self.assertEqual(count, 2)

    def test_sqlite_upsert_is_idempotent(self) -> None:
        _, companyfacts = build_payloads()
        statement = normalize_companyfacts(companyfacts, sample_filing())
        ratios = calculate_ratios(statement)
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FinancialStore(Path(temp_dir) / "store.sqlite3")
            store.save_analysis(statement, ratios)
            store.save_analysis(statement, ratios)
            with closing(sqlite3.connect(store.database_path)) as connection:
                count = connection.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
