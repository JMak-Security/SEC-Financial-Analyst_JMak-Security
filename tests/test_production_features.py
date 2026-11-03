from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import math
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from typing import Any
from unittest.mock import Mock, patch

import pandas as pd

from portfolio_risk.engine import RiskEngine
from portfolio_risk.stress import (
    apply_reference_scenario,
    historical_replay,
    reference_scenarios,
)
from portfolio_risk.streaming import (
    AlpacaKafkaConfig,
    run_alpaca_kafka_stream,
)
from sec_analyst.duckdb_store import DuckDBFinancialStore
from sec_analyst.inline_xbrl import InlineXbrlError, parse_inline_xbrl
from sec_analyst.models import Filing, FinancialStatements
from sec_analyst.normalize import normalize_companyfacts
from sec_analyst.taxonomy import TaxonomyMappings, reconcile_non_gaap
from sec_analyst.xbrl_validation import (
    XbrlValidationError,
    validate_companyfacts,
)


ROOT = Path(__file__).resolve().parents[1]


def build_statement(value: float = 10.0) -> FinancialStatements:
    filing = Filing(
        cik="0000000001",
        company_name="Test Holdings",
        form="10-Q",
        accession_number="0000000001-26-000001",
        filing_date="2026-11-01",
        period_end="2026-09-30",
        primary_document="filing.htm",
        acceptance_timestamp="2026-11-01T10:00:00.000Z",
    )
    return FinancialStatements(
        filing=filing,
        balance_sheet={"current_assets": value},
        income_statement={"revenue": 100.0, "net_income": 12.0},
        cash_flow_statement={},
        source_tags={"revenue": "us-gaap:Revenues"},
        currency="USD",
        fact_lineage={
            "revenue": {
                "taxonomy_concept": "us-gaap:Revenues",
                "accession_number": filing.accession_number,
                "filing_document_url": "https://www.sec.gov/Archives/edgar/data/1/1/filing.htm",
                "page_number": None,
            }
        },
        reported_non_gaap={"net_income": 15.0},
        non_gaap_reconciliation={
            "net_income": {
                "gaap_value": 12.0,
                "reported_non_gaap_value": 15.0,
                "absolute_difference": 3.0,
                "relative_difference": 0.25,
            }
        },
    )


class DistributedRiskTests(unittest.TestCase):
    def test_chunked_simulation_supports_one_million_paths(self) -> None:
        returns = pd.DataFrame(
            {
                "EQUITY": [-0.05, -0.02, 0.01, 0.02, 0.04, 0.03],
                "BOND": [0.01, 0.005, -0.003, 0.002, 0.004, 0.0],
            }
        )
        engine = RiskEngine(returns, {"EQUITY": 0.7, "BOND": 0.3})
        report = engine.simulate_monte_carlo(
            1_000_000.0,
            confidence=0.99,
            simulations=1_000_000,
            seed=90210,
            chunk_size=25_000,
        )
        self.assertEqual(report.simulations, 1_000_000)
        self.assertTrue(math.isfinite(report.var))
        self.assertGreaterEqual(report.cvar, report.var)

    def test_dask_backend_runs_distributed_chunks(self) -> None:
        returns = pd.DataFrame({"BTC": [-0.02, 0.01, 0.03, -0.01]})
        engine = RiskEngine(returns, {"BTC": 1.0})
        first = engine.simulate_monte_carlo(
            100_000, simulations=500, seed=13, backend="dask", chunk_size=100
        )
        second = engine.simulate_monte_carlo(
            100_000, simulations=500, seed=13, backend="dask", chunk_size=100
        )
        self.assertEqual(first, second)

    def test_rejects_bad_chunk_and_backend(self) -> None:
        engine = RiskEngine(pd.DataFrame({"BTC": [-0.02, 0.01]}), {"BTC": 1})
        with self.assertRaisesRegex(ValueError, "Chunk size"):
            engine.simulate_monte_carlo(1000, chunk_size=0)
        with self.assertRaisesRegex(ValueError, "Backend"):
            engine.simulate_monte_carlo(1000, backend="unknown")


class StressFrameworkTests(unittest.TestCase):
    def test_historical_replay_compounds_observed_returns(self) -> None:
        returns = pd.DataFrame(
            {"EQ": [-0.1, 0.05, -0.2]},
            index=pd.date_range("2008-01-01", periods=3, freq="D"),
        )
        report = historical_replay(
            returns, {"EQ": 1.0}, 100_000, "2008-01-01", "2008-01-03"
        )
        expected = (0.9 * 1.05 * 0.8) - 1
        self.assertAlmostEqual(report.portfolio_return, expected)
        self.assertAlmostEqual(report.loss, -expected * 100_000)
        self.assertEqual(
            report.scenario.classification, "observed-replay-not-forecast"
        )

    def test_parallel_curve_shift_uses_duration_and_labels_approximation(self) -> None:
        scenario = next(
            item
            for item in reference_scenarios()
            if item.scenario_id == "parallel-rates-up-200bp"
        )
        report = apply_reference_scenario(
            scenario,
            {"bond": 1_000_000, "equity": 1_000_000},
            {"bond": "rates", "equity": "equity"},
            2_000_000,
            modified_durations={"bond": 5.0},
        )
        self.assertAlmostEqual(report.asset_impacts["bond"], -0.1)
        self.assertAlmostEqual(report.portfolio_return, -0.05)
        self.assertTrue(any("not a Basel/FRTB" in item for item in report.assumptions))

    def test_historical_replay_rejects_bad_windows_and_unaligned_weights(self) -> None:
        frame = pd.DataFrame(
            {"EQ": [0.01, 0.02]},
            index=pd.date_range("2020-01-01", periods=2, freq="D"),
        )
        with self.assertRaisesRegex(ValueError, "No market observations"):
            historical_replay(
                frame, {"EQ": 1}, 1000, "2022-01-01", "2022-01-02"
            )
        with self.assertRaisesRegex(ValueError, "weights must match"):
            historical_replay(
                frame, {"OTHER": 1}, 1000, "2020-01-01", "2020-01-02"
            )


class InlineXbrlAndTaxonomyTests(unittest.TestCase):
    def test_parses_extension_facts_contexts_dimensions_and_inline_provenance(self) -> None:
        document = b"""<html><body>
        <xbrli:context id="c1"><xbrli:entity/><xbrli:period>
        <xbrli:startDate>2026-07-01</xbrli:startDate>
        <xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period>
        <xbrli:scenario><xbrldi:explicitMember dimension="issuer:RegionAxis">
        issuer:North</xbrldi:explicitMember></xbrli:scenario></xbrli:context>
        <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
        <ix:nonFraction id="fact-1" name="issuer:AdjustedRevenue"
        contextRef="c1" unitRef="usd" scale="6" sign="-">1,234</ix:nonFraction>
        </body></html>"""
        result = parse_inline_xbrl(
            document,
            accession="0000000001-26-000001",
            form="10-Q",
            filing_date="2026-11-01",
            period_end="2026-09-30",
        )
        entry = result["facts"]["issuer"]["AdjustedRevenue"]["units"]["USD"][0]
        self.assertEqual(entry["val"], -1_234_000_000)
        self.assertEqual(entry["element_id"], "fact-1")
        self.assertEqual(entry["dimensions"]["issuer:RegionAxis"], "issuer:North")

    def test_inline_parser_rejects_empty_oversized_and_invalid_content(self) -> None:
        arguments = {
            "accession": "a",
            "form": "10-Q",
            "filing_date": "2026-01-01",
            "period_end": "2025-12-31",
        }
        with self.assertRaisesRegex(InlineXbrlError, "No supported"):
            parse_inline_xbrl(b"<html/>", **arguments)
        with self.assertRaisesRegex(InlineXbrlError, "20,000,000"):
            parse_inline_xbrl(b"x" * 20_000_001, **arguments)
        with self.assertRaises(InlineXbrlError):
            parse_inline_xbrl(b"\xff", **arguments)
        invalid_scale = b"""<html><body>
        <xbrli:context id="c"><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant>
        </xbrli:period></xbrli:context>
        <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
        <ix:nonFraction name="us-gaap:Assets" contextRef="c" unitRef="usd"
        scale="999">1</ix:nonFraction></body></html>"""
        with self.assertRaisesRegex(InlineXbrlError, "scale"):
            parse_inline_xbrl(invalid_scale, **arguments)

    def test_strict_companyfacts_validation_and_accession_check(self) -> None:
        payload = {
            "cik": 1,
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {
                                    "val": 100,
                                    "accn": "accession",
                                    "form": "10-K",
                                    "filed": "2026-03-01",
                                    "end": "2025-12-31",
                                }
                            ]
                        }
                    }
                }
            },
        }
        self.assertEqual(
            validate_companyfacts(
                payload, expected_cik="0000000001", filing_accession="accession"
            ),
            [],
        )
        payload["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] = "NaN"
        with self.assertRaises(XbrlValidationError):
            validate_companyfacts(payload)

    def test_companyfacts_retries_are_bounded_and_cover_sec_rate_limits(self) -> None:
        from sec_analyst.edgar import SecApiError, SecEdgarClient

        client = SecEdgarClient("analyst@example.com")
        retries = client.session.get_adapter(
            "https://data.sec.gov"
        ).max_retries
        self.assertEqual(retries.total, 5)
        self.assertEqual(retries.backoff_factor, 0.75)
        self.assertIn(429, retries.status_forcelist)
        self.assertTrue(retries.respect_retry_after_header)
        self.assertTrue(SecApiError("rate-limited", retryable=True).retryable)
        self.assertFalse(SecApiError("bad payload").retryable)

    def test_crosswalk_validation_and_explicit_non_gaap_reconciliation(self) -> None:
        mappings = TaxonomyMappings.from_payload(
            {
                "custom_gaap": {"revenue": "issuer:Revenue"},
                "non_gaap": {"net_income": "issuer:AdjustedNetIncome"},
            }
        )
        self.assertEqual(mappings.custom_gaap["revenue"], "issuer:Revenue")
        with self.assertRaisesRegex(ValueError, "qualified XBRL tag"):
            TaxonomyMappings.from_payload(
                {"custom_gaap": {"revenue": "not-qualified"}}
            )
        results = reconcile_non_gaap(
            {"net_income": 10.0}, {"net_income": 12.0}
        )
        self.assertEqual(results["net_income"]["absolute_difference"], 2.0)
        self.assertEqual(results["net_income"]["relative_difference"], 0.2)

    def test_custom_gaap_and_non_gaap_inline_tags_are_explicitly_reconciled(self) -> None:
        payload = {
            "cik": 1,
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {
                                    "val": 100,
                                    "accn": "0000000001-26-000001",
                                    "form": "10-Q",
                                    "filed": "2026-11-01",
                                    "start": "2026-07-01",
                                    "end": "2026-09-30",
                                }
                            ]
                        }
                    }
                },
                "issuer": {
                    "Revenue": {
                        "units": {
                            "USD": [
                                {
                                    "val": 120,
                                    "accn": "0000000001-26-000001",
                                    "form": "10-Q",
                                    "filed": "2026-11-01",
                                    "start": "2026-07-01",
                                    "end": "2026-09-30",
                                    "element_id": "gaap-extension",
                                }
                            ]
                        }
                    },
                    "AdjustedRevenue": {
                        "units": {
                            "USD": [
                                {
                                    "val": 130,
                                    "accn": "0000000001-26-000001",
                                    "form": "10-Q",
                                    "filed": "2026-11-01",
                                    "start": "2026-07-01",
                                    "end": "2026-09-30",
                                }
                            ]
                        }
                    },
                },
            },
        }
        filing = Filing(
            cik="0000000001",
            company_name="Extension Co",
            form="10-Q",
            accession_number="0000000001-26-000001",
            filing_date="2026-11-01",
            period_end="2026-09-30",
            primary_document="filing.htm",
        )
        mappings = TaxonomyMappings(
            {"revenue": "issuer:Revenue"},
            {"revenue": "issuer:AdjustedRevenue"},
        )
        result = normalize_companyfacts(
            payload,
            filing,
            custom_tag_mappings=mappings.custom_gaap,
            non_gaap_tag_mappings=mappings.non_gaap,
        )
        self.assertEqual(result.income_statement["revenue"], 120.0)
        self.assertEqual(result.reported_non_gaap["revenue"], 130.0)
        self.assertEqual(
            result.non_gaap_reconciliation["revenue"]["absolute_difference"],
            10.0,
        )
        self.assertEqual(
            result.fact_lineage["revenue"]["inline_element_id"],
            "gaap-extension",
        )


class DuckDBLineageTests(unittest.TestCase):
    def test_append_only_versions_and_as_of_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DuckDBFinancialStore(Path(temp_dir) / "lineage.duckdb")
            first_id = store.save_analysis(build_statement(10), {"current_ratio": 1.2})
            versions = store.versions_for_accession("0000000001-26-000001")
            self.assertEqual(len(versions), 1)
            first = versions[0]
            lineage = json.loads(first["lineage_json"])
            self.assertEqual(
                lineage["facts"]["revenue"]["accession_number"],
                "0000000001-26-000001",
            )
            self.assertIsNone(lineage["facts"]["revenue"]["page_number"])
            self.assertEqual(
                lineage["facts"]["revenue"]["filing_document_url"].split("#")[0],
                "https://www.sec.gov/Archives/edgar/data/1/1/filing.htm",
            )
            as_of_first = store.as_of(
                "0000000001-26-000001",
                first["observed_at"] + timedelta(seconds=1),
            )
            self.assertEqual(as_of_first["run_id"], first_id)
            second_id = store.save_analysis(
                build_statement(20), {"current_ratio": 1.5}
            )
            versions = store.versions_for_accession("0000000001-26-000001")
            self.assertEqual(len(versions), 2)
            self.assertNotEqual(
                versions[0]["payload_sha256"], versions[1]["payload_sha256"]
            )
            self.assertNotEqual(first_id, second_id)
            before_first = store.as_of(
                "0000000001-26-000001",
                first["observed_at"] - timedelta(seconds=1),
            )
            self.assertIsNone(before_first)

    def test_existing_sec_pipeline_persists_duckdb_fact_versions(self) -> None:
        from scripts.generate_samples import build_payloads
        from sec_analyst.agent import FinancialAnalystAgent
        from sec_analyst.workspace import WorkspaceManager

        submissions, facts = build_payloads()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = WorkspaceManager(temp_dir, create=True)
            manager = FinancialAnalystAgent(workspace)
            result = asyncio.run(
                manager._analyze_payloads(
                    submissions, facts, "0000000001", 2, "test"
                )
            )
            self.assertTrue(result.health_report)
            versions = manager.lineage_store.versions_for_accession(
                "0000000001-26-000003"
            )
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0]["form"], "10-Q")


@unittest.skipUnless(
    importlib.util.find_spec("prefect"),
    "Prefect is an optional production dependency.",
)
class PrefectOrchestrationTests(unittest.TestCase):
    def test_prefect_flow_calls_pipeline_task_with_retry_policy(self) -> None:
        from sec_analyst import prefect_flow
        from prefect.states import Failed
        from sec_analyst.edgar import SecApiError

        fake_result = Mock()
        fake_result.as_dict.return_value = {"status": "ok"}
        fake_agent = Mock()
        fake_agent.analyze_sec.return_value = asyncio.sleep(0, result=fake_result)
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(prefect_flow, "SecEdgarClient", return_value=Mock()),
            patch.object(
                prefect_flow, "FinancialAnalystAgent", return_value=fake_agent
            ),
        ):
            result = prefect_flow.analyze_company_flow(
                "NVDA", "analyst@example.com", temp_dir, filing_count=2
            )
        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(prefect_flow.analyze_company_task.retries, 4)
        self.assertTrue(
            prefect_flow.retry_transient_failure(
                None, None, Failed(data=SecApiError("busy", retryable=True))
            )
        )
        self.assertFalse(
            prefect_flow.retry_transient_failure(
                None, None, Failed(data=SecApiError("invalid data"))
            )
        )
        self.assertFalse(
            prefect_flow.retry_transient_failure(
                None, None, Failed(data=ValueError("invalid input"))
            )
        )


class StreamingAdapterTests(unittest.TestCase):
    def test_config_validation_and_env_requirements(self) -> None:
        with self.assertRaisesRegex(ValueError, "credentials"):
            AlpacaKafkaConfig("", "", "localhost:9092")
        with self.assertRaisesRegex(ValueError, "feed"):
            AlpacaKafkaConfig("key", "secret", "localhost:9092", feed="bad")
        with self.assertRaisesRegex(ValueError, "SASL username and password"):
            AlpacaKafkaConfig(
                "key",
                "secret",
                "localhost:9092",
                kafka_security_protocol="SASL_SSL",
                kafka_sasl_mechanism="PLAIN",
            )
        secure_config = AlpacaKafkaConfig(
            "key",
            "secret",
            "localhost:9092",
            kafka_security_protocol="SASL_SSL",
            kafka_sasl_mechanism="SCRAM-SHA-256",
            kafka_sasl_username="user",
            kafka_sasl_password="password",
        )
        self.assertNotIn("password", repr(secure_config))
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "ALPACA_API_KEY"):
                AlpacaKafkaConfig.from_environment()

    def test_stream_rejects_bad_subscriptions_before_optional_imports(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            asyncio.run(
                run_alpaca_kafka_stream(
                    AlpacaKafkaConfig("key", "secret", "localhost:9092"),
                    ["A", "A"],
                    {"A": 1.0},
                    1000,
                )
            )

    def test_mocked_alpaca_stream_publishes_market_and_risk_events(self) -> None:
        async def run_test() -> None:
            sent_messages: list[tuple[str, bytes, bytes | None]] = []
            producer_instances: list[Any] = []

            class Producer:
                async def start(self) -> None:
                    return None

                async def stop(self) -> None:
                    return None

                async def send_and_wait(
                    self, topic: str, value: bytes, key: bytes | None = None
                ) -> None:
                    sent_messages.append((topic, value, key))

            class WebSocket:
                def __init__(self) -> None:
                    self.messages = [
                        json.dumps(
                            [{"T": "success", "msg": "authenticated"}]
                        ),
                        json.dumps(
                            [{"T": "b", "S": "A", "t": "2026-01-01T10:00:00Z", "c": 100}]
                        ),
                        json.dumps(
                            [{"T": "b", "S": "B", "t": "2026-01-01T10:00:00Z", "c": 50}]
                        ),
                        json.dumps(
                            [{"T": "b", "S": "A", "t": "2026-01-01T10:01:00Z", "c": 101}]
                        ),
                        json.dumps(
                            [{"T": "b", "S": "B", "t": "2026-01-01T10:01:00Z", "c": 49}]
                        ),
                        json.dumps(
                            [{"T": "b", "S": "A", "t": "2026-01-01T10:02:00Z", "c": 102}]
                        ),
                        json.dumps(
                            [{"T": "b", "S": "B", "t": "2026-01-01T10:02:00Z", "c": 48}]
                        ),
                    ]

                async def send(self, value: str) -> None:
                    return None

                async def recv(self) -> str:
                    return self.messages.pop(0)

            websocket = WebSocket()

            class WebSocketContext:
                async def __aenter__(self) -> WebSocket:
                    return websocket

                async def __aexit__(self, *args: Any) -> None:
                    return None

            async def status_callback(
                event: str, details: dict[str, Any]
            ) -> None:
                if event == "risk_snapshot":
                    stop.set()

            websocket_module = types.ModuleType("websockets")
            websocket_module.__path__ = []
            websocket_module.connect = Mock(
                side_effect=lambda *args, **kwargs: WebSocketContext()
            )
            exceptions_module = types.ModuleType("websockets.exceptions")
            exceptions_module.ConnectionClosed = type(
                "ConnectionClosed", (Exception,), {}
            )
            kafka_module = types.ModuleType("aiokafka")

            def create_producer(**kwargs: Any) -> Producer:
                producer = Producer()
                producer_instances.append(producer)
                return producer

            kafka_module.AIOKafkaProducer = create_producer
            stop = asyncio.Event()
            with patch.dict(
                sys.modules,
                {
                    "websockets": websocket_module,
                    "websockets.exceptions": exceptions_module,
                    "aiokafka": kafka_module,
                },
            ):
                await run_alpaca_kafka_stream(
                    AlpacaKafkaConfig(
                        "key", "secret", "localhost:9092"
                    ),
                    ["A", "B"],
                    {"A": 0.5, "B": 0.5},
                    10_000,
                    status_callback=status_callback,
                    stop_event=stop,
                )
            risk_events = [
                json.loads(value)
                for topic, value, _ in sent_messages
                if topic == "risk.snapshots"
            ]
            market_events = [
                item for item in sent_messages if item[0] == "market.bars"
            ]
            self.assertEqual(len(risk_events), 1)
            self.assertEqual(len(market_events), 6)
            self.assertTrue(risk_events[0]["not_an_order"])
            self.assertEqual(risk_events[0]["risk"]["observations"], 2)
            self.assertEqual(len(producer_instances), 1)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
