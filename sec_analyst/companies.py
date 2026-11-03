"""Curated aliases for the companies used in the analyst's example workflows."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CompanyIdentity:
    query: str
    display_name: str
    ticker: str | None
    cik: str | None
    public_filing_status: str


_ALIASES: dict[str, CompanyIdentity] = {}


def _register(
    aliases: tuple[str, ...],
    display_name: str,
    ticker: str | None,
    cik: str | None,
    filing_status: str,
) -> None:
    identity = CompanyIdentity("", display_name, ticker, cik, filing_status)
    for alias in aliases:
        _ALIASES[re.sub(r"[^a-z0-9]", "", alias.casefold())] = identity


_register(
    ("nvidia", "nividia", "nvidia corporation", "nvda"),
    "NVIDIA Corporation",
    "NVDA",
    "0001045810",
    "sec_filer",
)
_register(
    ("pwc", "pricewaterhousecoopers", "pricewaterhousecoopers international"),
    "PwC",
    None,
    None,
    "private_or_network_structure",
)
_register(("votee ai", "votee"), "Votee AI", None, None, "private_or_unverified")
_register(("wonderful",), "Wonderful", None, None, "ambiguous_private_company")


def identify_company(query: str) -> CompanyIdentity:
    """Resolve known aliases without implying financial data availability."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Enter a company name, ticker, or CIK.")
    normalized = re.sub(r"[^a-z0-9]", "", query.casefold())
    identity = _ALIASES.get(normalized)
    if identity is not None:
        return CompanyIdentity(
            query=query.strip(),
            display_name=identity.display_name,
            ticker=identity.ticker,
            cik=identity.cik,
            public_filing_status=identity.public_filing_status,
        )
    if query.strip().isdigit():
        return CompanyIdentity(query.strip(), query.strip(), None, query.strip().zfill(10), "cik_lookup")
    return CompanyIdentity(query.strip(), query.strip(), None, None, "lookup_required")
