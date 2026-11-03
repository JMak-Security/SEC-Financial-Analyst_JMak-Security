"""Shared data types for filing and statement processing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Filing:
    cik: str
    company_name: str
    form: str
    accession_number: str
    filing_date: str
    period_end: str
    primary_document: str = ""
    acceptance_timestamp: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class FinancialStatements:
    filing: Filing
    balance_sheet: dict[str, float | None]
    income_statement: dict[str, float | None]
    cash_flow_statement: dict[str, float | None]
    source_tags: dict[str, str]
    currency: str
    fact_lineage: dict[str, dict[str, Any]] | None = None
    reported_non_gaap: dict[str, float | None] | None = None
    non_gaap_reconciliation: dict[str, dict[str, float | None]] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "filing": self.filing.as_dict(),
            "balance_sheet": self.balance_sheet,
            "income_statement": self.income_statement,
            "cash_flow_statement": self.cash_flow_statement,
            "source_tags": self.source_tags,
            "currency": self.currency,
            "fact_lineage": self.fact_lineage or {},
            "reported_non_gaap": self.reported_non_gaap or {},
            "non_gaap_reconciliation": self.non_gaap_reconciliation or {},
        }
