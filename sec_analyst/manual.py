"""Validated CSV ingestion for private or non-SEC company financials."""

from __future__ import annotations

import csv
from datetime import date
import io
import math
from typing import Any

from .models import Filing, FinancialStatements

STATEMENT_FIELDS = {
    "cash_and_equivalents": "balance_sheet",
    "short_term_investments": "balance_sheet",
    "receivables": "balance_sheet",
    "inventory": "balance_sheet",
    "prepaid_expenses": "balance_sheet",
    "current_assets": "balance_sheet",
    "property_plant_equipment": "balance_sheet",
    "total_assets": "balance_sheet",
    "current_liabilities": "balance_sheet",
    "long_term_debt": "balance_sheet",
    "total_liabilities": "balance_sheet",
    "shareholders_equity": "balance_sheet",
    "revenue": "income_statement",
    "cost_of_revenue": "income_statement",
    "gross_profit": "income_statement",
    "operating_income": "income_statement",
    "net_income": "income_statement",
    "operating_cash_flow": "cash_flow_statement",
    "capital_expenditures": "cash_flow_statement",
}
_ALLOWED_COLUMNS = {"period_end", "currency", *STATEMENT_FIELDS}


def parse_manual_financials_csv(
    content: bytes, company_name: str
) -> list[FinancialStatements]:
    """Parse 1–12 dated rows; blank cells remain unavailable, never zero-filled."""
    if not isinstance(content, bytes) or len(content) > 1_000_000:
        raise ValueError("Financials CSV must be bytes no larger than 1 MB.")
    if not isinstance(company_name, str) or not company_name.strip():
        raise ValueError("Enter the company name for the uploaded financials.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Financials CSV must use UTF-8 encoding.") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "period_end" not in reader.fieldnames:
        raise ValueError("Financials CSV must include a period_end column.")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("Financials CSV column names must be unique.")
    unknown_columns = set(reader.fieldnames) - _ALLOWED_COLUMNS
    if unknown_columns:
        raise ValueError(
            "Financials CSV contains unsupported columns: "
            + ", ".join(sorted(unknown_columns))
        )
    periods: set[str] = set()
    statements: list[FinancialStatements] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(
                f"Row {row_number}: found more values than the CSV header allows."
            )
        if len(statements) >= 12:
            raise ValueError("Financials CSV may contain at most 12 periods.")
        period_end = (row.get("period_end") or "").strip()
        try:
            date.fromisoformat(period_end)
        except ValueError as exc:
            raise ValueError(
                f"Row {row_number}: period_end must use YYYY-MM-DD."
            ) from exc
        if period_end in periods:
            raise ValueError(f"Row {row_number}: duplicate period_end {period_end}.")
        periods.add(period_end)
        values: dict[str, float | None] = {}
        for field in STATEMENT_FIELDS:
            raw_value = (row.get(field) or "").strip()
            if not raw_value:
                values[field] = None
                continue
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise ValueError(
                    f"Row {row_number}: {field} must be a finite number or blank."
                ) from exc
            if not math.isfinite(value):
                raise ValueError(f"Row {row_number}: {field} must be finite.")
            values[field] = value
        if not any(value is not None for value in values.values()):
            raise ValueError(f"Row {row_number}: enter at least one financial value.")
        currency = (row.get("currency") or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError(
                f"Row {row_number}: provide an explicit 3-letter currency code."
            )
        filing = Filing(
            cik="",
            company_name=company_name.strip(),
            form="MANUAL",
            accession_number=f"manual-{period_end}",
            filing_date=period_end,
            period_end=period_end,
        )
        grouped: dict[str, dict[str, Any]] = {
            "balance_sheet": {},
            "income_statement": {},
            "cash_flow_statement": {},
        }
        for field, statement_name in STATEMENT_FIELDS.items():
            grouped[statement_name][field] = values[field]
        statements.append(
            FinancialStatements(
                filing=filing,
                balance_sheet=grouped["balance_sheet"],
                income_statement=grouped["income_statement"],
                cash_flow_statement=grouped["cash_flow_statement"],
                source_tags={},
                currency=currency,
            )
        )
    if not statements:
        raise ValueError("Financials CSV must contain at least one data row.")
    return statements
