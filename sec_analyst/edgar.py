"""SEC EDGAR submissions and CompanyFacts API client."""

from __future__ import annotations

import re
from typing import Any

import requests

from .companies import identify_company
from .models import Filing


class SecApiError(RuntimeError):
    """Raised when an SEC request or response cannot be used."""


class SecEdgarClient:
    BASE_URL = "https://data.sec.gov"
    TICKER_URL = "https://www.sec.gov/files/company_tickers.json"

    def __init__(self, contact_email: str, timeout: float = 25.0) -> None:
        email = contact_email.strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("Provide a valid contact email for the SEC User-Agent.")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"SEC-Financial-Analyst/1.0 ({email})",
                "Accept-Encoding": "gzip, deflate",
            }
        )

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise SecApiError(f"SEC request failed for {url}: {exc}") from exc
        except ValueError as exc:
            raise SecApiError(f"SEC returned invalid JSON for {url}.") from exc
        if not isinstance(payload, dict):
            raise SecApiError(f"SEC returned an unexpected response for {url}.")
        return payload

    def resolve_cik(self, company: str) -> str:
        value = company.strip()
        identity = identify_company(value)
        if identity.cik:
            return identity.cik.zfill(10)
        if identity.ticker:
            value = identity.ticker
        if value.isdigit():
            return value.zfill(10)
        if not value:
            raise ValueError("Enter a company ticker or CIK.")

        payload = self._get_json(self.TICKER_URL)
        ticker = value.upper()
        for company_row in payload.values():
            if (
                isinstance(company_row, dict)
                and str(company_row.get("ticker", "")).upper() == ticker
            ):
                return str(company_row["cik_str"]).zfill(10)
        raise ValueError(f"Ticker {ticker} was not found in the SEC ticker list.")

    def fetch_company(self, company: str) -> tuple[dict[str, Any], dict[str, Any]]:
        cik = self.resolve_cik(company)
        padded_cik = cik.zfill(10)
        submissions = self._get_json(
            f"{self.BASE_URL}/submissions/CIK{padded_cik}.json"
        )
        facts = self._get_json(
            f"{self.BASE_URL}/api/xbrl/companyfacts/CIK{padded_cik}.json"
        )
        return submissions, facts


def recent_filings(submissions: dict[str, Any], cik: str, limit: int) -> list[Filing]:
    """Return recent, non-amended 10-K/10-Q filings with a reported period end."""
    if limit < 1:
        raise ValueError("Filing count must be at least one.")
    company_name = str(submissions.get("name") or "Unknown company")
    cik_value = str(submissions.get("cik") or cik).zfill(10)
    filing_data = submissions.get("filings")
    if not isinstance(filing_data, dict):
        raise ValueError("SEC submissions JSON is missing its filings object.")
    recent = filing_data.get("recent")
    if not isinstance(recent, dict):
        raise ValueError("SEC submissions JSON is missing recent filing data.")
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    documents = recent.get("primaryDocument", [])
    if not isinstance(forms, list) or not isinstance(accessions, list):
        raise ValueError("SEC submissions filing arrays have an invalid format.")
    if not isinstance(filing_dates, list) or not isinstance(report_dates, list):
        raise ValueError("SEC submissions filing dates have an invalid format.")
    if not isinstance(documents, list):
        documents = []

    filings: list[Filing] = []
    for index, form in enumerate(forms):
        if form not in {"10-K", "10-Q"}:
            continue
        if index >= len(accessions) or index >= len(report_dates):
            continue
        period_end = str(report_dates[index] or "")
        accession = str(accessions[index] or "")
        if not period_end or not accession:
            continue
        filings.append(
            Filing(
                cik=cik_value,
                company_name=company_name,
                form=str(form),
                accession_number=accession,
                filing_date=str(filing_dates[index] or ""),
                period_end=period_end,
                primary_document=(
                    str(documents[index] or "") if index < len(documents) else ""
                ),
            )
        )
        if len(filings) == limit:
            break
    return filings
