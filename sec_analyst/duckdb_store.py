"""Append-only DuckDB snapshots for queryable financial statement lineage."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from typing import Any

import duckdb

from .models import FinancialStatements


class DuckDBFinancialStore:
    """Persist each analysis as an immutable versioned snapshot."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_versions (
                    run_id VARCHAR PRIMARY KEY,
                    observed_at TIMESTAMP NOT NULL,
                    cik VARCHAR NOT NULL,
                    accession_number VARCHAR NOT NULL,
                    company_name VARCHAR NOT NULL,
                    form VARCHAR NOT NULL,
                    filing_date VARCHAR NOT NULL,
                    acceptance_timestamp VARCHAR NOT NULL,
                    period_end VARCHAR NOT NULL,
                    document_url VARCHAR NOT NULL,
                    statements_json JSON NOT NULL,
                    ratios_json JSON NOT NULL,
                    lineage_json JSON NOT NULL,
                    payload_sha256 VARCHAR NOT NULL
                )
                """
            )

    @staticmethod
    def _canonical_json(payload: Any) -> str:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )

    def save_analysis(
        self,
        statements: FinancialStatements,
        ratios: dict[str, float | None],
    ) -> str:
        filing = statements.filing
        normalized = {
            "balance_sheet": statements.balance_sheet,
            "income_statement": statements.income_statement,
            "cash_flow_statement": statements.cash_flow_statement,
            "currency": statements.currency,
            "reported_non_gaap": statements.reported_non_gaap or {},
            "non_gaap_reconciliation": (
                statements.non_gaap_reconciliation or {}
            ),
        }
        statements_json = self._canonical_json(normalized)
        ratios_json = self._canonical_json(ratios)
        lineage_json = self._canonical_json(
            {
                "source_tags": statements.source_tags,
                "facts": statements.fact_lineage or {},
                "sec_source": "SEC EDGAR CompanyFacts",
                "accession_number": filing.accession_number,
                "filing_date": filing.filing_date,
                "acceptance_timestamp": filing.acceptance_timestamp,
            }
        )
        canonical_payload = self._canonical_json(
            {
                "statements": normalized,
                "ratios": ratios,
                "lineage": json.loads(lineage_json),
            }
        )
        digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
        run_id = str(uuid.uuid4())
        cik_digits = filing.cik.lstrip("0") or "0"
        accession_path = filing.accession_number.replace("-", "")
        document_url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{cik_digits}/{accession_path}/{filing.primary_document}"
            if filing.primary_document
            else ""
        )
        with duckdb.connect(str(self.database_path)) as connection:
            connection.execute(
                """
                INSERT INTO analysis_versions VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_id,
                    datetime.now(timezone.utc).replace(tzinfo=None),
                    filing.cik,
                    filing.accession_number,
                    filing.company_name,
                    filing.form,
                    filing.filing_date,
                    filing.acceptance_timestamp,
                    filing.period_end,
                    document_url,
                    statements_json,
                    ratios_json,
                    lineage_json,
                    digest,
                ],
            )
        return run_id

    def versions_for_accession(self, accession_number: str) -> list[dict[str, Any]]:
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            cursor = connection.execute(
                """
                SELECT run_id, observed_at, cik, accession_number, company_name,
                       form, filing_date, acceptance_timestamp, period_end,
                       document_url, statements_json, ratios_json, lineage_json,
                       payload_sha256
                FROM analysis_versions
                WHERE accession_number = ?
                ORDER BY observed_at, run_id
                """,
                [accession_number],
            )
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

    def as_of(
        self, accession_number: str, observed_at: datetime
    ) -> dict[str, Any] | None:
        utc_naive = (
            observed_at.astimezone(timezone.utc).replace(tzinfo=None)
            if observed_at.tzinfo is not None
            else observed_at
        )
        with duckdb.connect(str(self.database_path), read_only=True) as connection:
            cursor = connection.execute(
                """
                SELECT run_id, observed_at, cik, accession_number, company_name,
                       form, filing_date, acceptance_timestamp, period_end,
                       document_url, statements_json, ratios_json, lineage_json,
                       payload_sha256
                FROM analysis_versions
                WHERE accession_number = ? AND observed_at <= ?
                ORDER BY observed_at DESC, run_id DESC
                LIMIT 1
                """,
                [accession_number, utc_naive],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(
                zip((item[0] for item in cursor.description), row, strict=True)
            )
