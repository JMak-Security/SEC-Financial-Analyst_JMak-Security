"""SQLite persistence for normalized statements and calculated ratios."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from .models import FinancialStatements


class FinancialStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.executescript(schema_path.read_text(encoding="utf-8"))

    def save_analysis(
        self, statements: FinancialStatements, ratios: dict[str, float | None]
    ) -> None:
        filing = statements.filing
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute(
                """
                INSERT INTO filings
                    (cik, accession_number, company_name, form, filing_date,
                     period_end, primary_document)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cik, accession_number) DO UPDATE SET
                    company_name=excluded.company_name,
                    form=excluded.form,
                    filing_date=excluded.filing_date,
                    period_end=excluded.period_end,
                    primary_document=excluded.primary_document
                """,
                (
                    filing.cik,
                    filing.accession_number,
                    filing.company_name,
                    filing.form,
                    filing.filing_date,
                    filing.period_end,
                    filing.primary_document,
                ),
            )
            for statement_name, values in (
                ("balance_sheet", statements.balance_sheet),
                ("income_statement", statements.income_statement),
                ("cash_flow_statement", statements.cash_flow_statement),
            ):
                for metric, value in values.items():
                    connection.execute(
                        """
                        INSERT INTO statement_items
                            (cik, accession_number, statement, metric, value,
                             unit, source_tag)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(cik, accession_number, statement, metric)
                        DO UPDATE SET value=excluded.value, unit=excluded.unit,
                                      source_tag=excluded.source_tag
                        """,
                        (
                            filing.cik,
                            filing.accession_number,
                            statement_name,
                            metric,
                            value,
                            statements.currency,
                            statements.source_tags.get(metric),
                        ),
                    )
            for metric, value in ratios.items():
                connection.execute(
                    """
                    INSERT INTO ratios (cik, accession_number, metric, value)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(cik, accession_number, metric)
                    DO UPDATE SET value=excluded.value
                    """,
                    (filing.cik, filing.accession_number, metric, value),
                )
