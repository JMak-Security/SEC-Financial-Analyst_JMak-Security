"""Map SEC standardized XBRL facts to normalized statement line items."""

from __future__ import annotations

from datetime import date
from typing import Any

from .models import Filing, FinancialStatements

BALANCE_TAGS: dict[str, tuple[str, ...]] = {
    "cash_and_equivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "short_term_investments": (
        "ShortTermInvestments",
        "AvailableForSaleSecuritiesCurrent",
    ),
    "receivables": (
        "AccountsReceivableNetCurrent",
        "AccountsNotesAndLoansReceivableNetCurrent",
    ),
    "inventory": ("InventoryNet",),
    "prepaid_expenses": (
        "PrepaidExpenseCurrent",
        "PrepaidExpenseCurrentAndNoncurrent",
    ),
    "current_assets": ("AssetsCurrent",),
    "property_plant_equipment": ("PropertyPlantAndEquipmentNet",),
    "total_assets": ("Assets",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "long_term_debt": (
        "LongTermDebtNoncurrent",
        "LongTermDebt",
        "LongTermDebtAndFinanceLeaseObligations",
    ),
    "total_liabilities": ("Liabilities",),
    "shareholders_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
}

INCOME_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "OperatingRevenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ),
    "cost_of_revenue": (
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
}

CASH_FLOW_TAGS: dict[str, tuple[str, ...]] = {
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capital_expenditures": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
}


def _entry_matches_filing(entry: dict[str, Any], filing: Filing) -> bool:
    if entry.get("end") != filing.period_end:
        return False
    entry_form = str(entry.get("form") or "")
    if entry_form and entry_form != filing.form:
        return False
    accession = str(entry.get("accn") or "")
    return not accession or accession == filing.accession_number


def _duration_days(entry: dict[str, Any]) -> int | None:
    start = entry.get("start")
    end = entry.get("end")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _select_value(
    facts: dict[str, Any],
    aliases: tuple[str, ...],
    filing: Filing,
    is_instant: bool,
    currency: str,
) -> tuple[float | None, str | None]:
    namespaces = facts.get("facts", {}).get("us-gaap", {})
    for tag in aliases:
        concept = namespaces.get(tag)
        if not isinstance(concept, dict):
            continue
        units = concept.get("units", {})
        entries = units.get(currency, [])
        candidates = [
            entry
            for entry in entries
            if isinstance(entry, dict) and _entry_matches_filing(entry, filing)
        ]
        exact_accession = [
            entry
            for entry in candidates
            if entry.get("accn") == filing.accession_number
        ]
        if exact_accession:
            candidates = exact_accession
        if is_instant:
            candidates = [
                entry for entry in candidates if _duration_days(entry) is None
            ]
            selected = max(
                candidates,
                key=lambda entry: (entry.get("filed", ""), entry.get("accn", "")),
                default=None,
            )
        else:
            target_days = 365 if filing.form == "10-K" else 91
            candidates = [
                entry
                for entry in candidates
                if _duration_days(entry) is not None
                and (
                    300 <= _duration_days(entry) <= 400
                    if filing.form == "10-K"
                    else 60 <= _duration_days(entry) <= 120
                )
            ]
            selected = min(
                candidates,
                key=lambda entry: abs((_duration_days(entry) or target_days) - target_days),
                default=None,
            )
        if selected is not None:
            try:
                return float(selected["val"]), tag
            except (KeyError, TypeError, ValueError):
                continue
    return None, None


def _currency_for_filing(facts: dict[str, Any], filing: Filing) -> str:
    namespaces = facts.get("facts", {}).get("us-gaap", {})
    revenue_concepts = INCOME_TAGS["revenue"]
    available: set[str] = set()
    for tag in revenue_concepts:
        concept = namespaces.get(tag)
        if not isinstance(concept, dict):
            continue
        for unit, entries in concept.get("units", {}).items():
            if not isinstance(entries, list):
                continue
            if any(
                isinstance(entry, dict)
                and _entry_matches_filing(entry, filing)
                and _duration_days(entry) is not None
                for entry in entries
            ):
                available.add(unit)
    if "USD" in available:
        return "USD"
    currencies = sorted(
        unit
        for unit in available
        if len(unit) == 3 and unit.isalpha() and unit.isupper()
    )
    return currencies[0] if currencies else "USD"


def normalize_companyfacts(
    companyfacts: dict[str, Any], filing: Filing
) -> FinancialStatements:
    """Extract one filing's balance-sheet, income, and cash-flow values."""
    facts_root = companyfacts.get("facts")
    facts = facts_root.get("us-gaap") if isinstance(facts_root, dict) else None
    if not isinstance(facts, dict):
        raise ValueError("CompanyFacts payload has no standardized us-gaap facts.")

    currency = _currency_for_filing(companyfacts, filing)
    statements: dict[str, dict[str, float | None]] = {
        "balance_sheet": {},
        "income_statement": {},
        "cash_flow_statement": {},
    }
    source_tags: dict[str, str] = {}
    for statement_name, tag_map, is_instant in (
        ("balance_sheet", BALANCE_TAGS, True),
        ("income_statement", INCOME_TAGS, False),
        ("cash_flow_statement", CASH_FLOW_TAGS, False),
    ):
        for metric, aliases in tag_map.items():
            value, tag = _select_value(
                companyfacts, aliases, filing, is_instant, currency
            )
            statements[statement_name][metric] = value
            if tag:
                source_tags[metric] = f"us-gaap:{tag}"

    return FinancialStatements(
        filing=filing,
        balance_sheet=statements["balance_sheet"],
        income_statement=statements["income_statement"],
        cash_flow_statement=statements["cash_flow_statement"],
        source_tags=source_tags,
        currency=currency,
    )
