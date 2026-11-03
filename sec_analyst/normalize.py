"""Map SEC standardized XBRL facts to normalized statement line items."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .models import Filing, FinancialStatements
from .taxonomy import reconcile_non_gaap

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
) -> tuple[float | None, str | None, dict[str, Any] | None]:
    facts_root = facts.get("facts", {})
    tags = [
        (alias.split(":", 1)[0], alias.split(":", 1)[1])
        if ":" in alias
        else ("us-gaap", alias)
        for alias in aliases
    ]
    for namespace, tag in tags:
        concepts = facts_root.get(namespace, {})
        concept = concepts.get(tag) if isinstance(concepts, dict) else None
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
                return float(selected["val"]), f"{namespace}:{tag}", selected
            except (KeyError, TypeError, ValueError):
                continue
    return None, None, None


def _currency_for_filing(
    facts: dict[str, Any],
    filing: Filing,
    custom_tag_mappings: Mapping[str, str] | None = None,
    non_gaap_tag_mappings: Mapping[str, str] | None = None,
) -> str:
    facts_root = facts.get("facts", {})
    revenue_concepts = [
        ("us-gaap", tag) for tag in INCOME_TAGS["revenue"]
    ]
    for mapping in (custom_tag_mappings or {}, non_gaap_tag_mappings or {}):
        mapped_revenue = mapping.get("revenue")
        if mapped_revenue:
            namespace, tag = mapped_revenue.split(":", 1)
            revenue_concepts.append((namespace, tag))
    available: set[str] = set()
    for namespace, tag in revenue_concepts:
        namespace_facts = facts_root.get(namespace, {})
        concept = (
            namespace_facts.get(tag)
            if isinstance(namespace_facts, dict)
            else None
        )
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
    companyfacts: dict[str, Any],
    filing: Filing,
    custom_tag_mappings: Mapping[str, str] | None = None,
    non_gaap_tag_mappings: Mapping[str, str] | None = None,
) -> FinancialStatements:
    """Extract one filing's balance-sheet, income, and cash-flow values."""
    facts_root = companyfacts.get("facts")
    facts = facts_root.get("us-gaap") if isinstance(facts_root, dict) else None
    if not isinstance(facts, dict):
        raise ValueError("CompanyFacts payload has no standardized us-gaap facts.")

    custom_tag_mappings = custom_tag_mappings or {}
    non_gaap_tag_mappings = non_gaap_tag_mappings or {}
    currency = _currency_for_filing(
        companyfacts, filing, custom_tag_mappings, non_gaap_tag_mappings
    )
    statements: dict[str, dict[str, float | None]] = {
        "balance_sheet": {},
        "income_statement": {},
        "cash_flow_statement": {},
    }
    source_tags: dict[str, str] = {}
    fact_lineage: dict[str, dict[str, Any]] = {}
    for statement_name, tag_map, is_instant in (
        ("balance_sheet", BALANCE_TAGS, True),
        ("income_statement", INCOME_TAGS, False),
        ("cash_flow_statement", CASH_FLOW_TAGS, False),
    ):
        for metric, aliases in tag_map.items():
            tags = aliases
            custom_tag = custom_tag_mappings.get(metric)
            if custom_tag:
                tags = (custom_tag, *aliases)
            value, tag, selected = _select_value(
                companyfacts, tags, filing, is_instant, currency
            )
            statements[statement_name][metric] = value
            if tag and selected:
                source_tags[metric] = tag
                cik_digits = filing.cik.lstrip("0") or "0"
                accession_path = filing.accession_number.replace("-", "")
                document_url = (
                    "https://www.sec.gov/Archives/edgar/data/"
                    f"{cik_digits}/{accession_path}/{filing.primary_document}"
                    if filing.primary_document
                    else ""
                )
                element_id = str(selected.get("element_id") or "")
                fact_lineage[metric] = {
                    "taxonomy_concept": tag,
                    "unit": currency,
                    "value": value,
                    "accession_number": filing.accession_number,
                    "form": filing.form,
                    "period_start": str(selected.get("start") or ""),
                    "period_end": str(selected.get("end") or ""),
                    "fact_filed_date": str(selected.get("filed") or ""),
                    "acceptance_timestamp": filing.acceptance_timestamp,
                    "fiscal_year": selected.get("fy"),
                    "fiscal_period": str(selected.get("fp") or ""),
                    "frame": str(selected.get("frame") or ""),
                    "filing_document_url": document_url,
                    "companyfacts_url": (
                        f"https://data.sec.gov/api/xbrl/companyfacts/CIK"
                        f"{filing.cik.zfill(10)}.json"
                    ),
                    "page_number": None,
                    "page_number_note": (
                        "CompanyFacts does not provide printed page numbers; "
                        "see the accession-linked Inline XBRL filing document."
                    ),
                    "inline_element_id": element_id,
                    "inline_anchor_url": (
                        f"{document_url}#{element_id}"
                        if document_url and element_id
                        else document_url
                    ),
                    "inline_context_ref": str(selected.get("context_ref") or ""),
                    "inline_format": str(selected.get("inline_format") or ""),
                    "inline_scale": str(selected.get("scale") or ""),
                    "dimensions": selected.get("dimensions", {}),
                }

    reported_non_gaap: dict[str, float | None] = {}
    for metric, qualified_tag in non_gaap_tag_mappings.items():
        value, tag, selected = _select_value(
            companyfacts,
            (qualified_tag,),
            filing,
            is_instant=metric
            in {
                "cash_and_equivalents",
                "current_assets",
                "current_liabilities",
                "total_assets",
                "total_liabilities",
                "shareholders_equity",
            },
            currency=currency,
        )
        reported_non_gaap[metric] = value
        if tag and selected:
            source_key = f"non_gaap:{metric}"
            source_tags[source_key] = tag
            fact_lineage[source_key] = {
                "taxonomy_concept": tag,
                "unit": currency,
                "value": value,
                "accession_number": filing.accession_number,
                "form": filing.form,
                "period_start": str(selected.get("start") or ""),
                "period_end": str(selected.get("end") or ""),
                "fact_filed_date": str(selected.get("filed") or ""),
                "acceptance_timestamp": filing.acceptance_timestamp,
                "fiscal_year": selected.get("fy"),
                "fiscal_period": str(selected.get("fp") or ""),
                "frame": str(selected.get("frame") or ""),
                "filing_document_url": (
                    "https://www.sec.gov/Archives/edgar/data/"
                    f"{filing.cik.lstrip('0') or '0'}/"
                    f"{filing.accession_number.replace('-', '')}/"
                    f"{filing.primary_document}"
                    if filing.primary_document
                    else ""
                ),
                "companyfacts_url": (
                    f"https://data.sec.gov/api/xbrl/companyfacts/CIK"
                    f"{filing.cik.zfill(10)}.json"
                ),
                "inline_element_id": str(selected.get("element_id") or ""),
                "inline_context_ref": str(selected.get("context_ref") or ""),
                "inline_format": str(selected.get("inline_format") or ""),
                "inline_scale": str(selected.get("scale") or ""),
                "dimensions": selected.get("dimensions", {}),
                "page_number": None,
                "page_number_note": (
                    "CompanyFacts does not provide printed page numbers; "
                    "see the accession-linked Inline XBRL filing document."
                ),
            }
    gaap_values = {
        metric: statements[statement_name].get(metric)
        for statement_name, values in statements.items()
        for metric in values
    }

    return FinancialStatements(
        filing=filing,
        balance_sheet=statements["balance_sheet"],
        income_statement=statements["income_statement"],
        cash_flow_statement=statements["cash_flow_statement"],
        source_tags=source_tags,
        currency=currency,
        fact_lineage=fact_lineage,
        reported_non_gaap=reported_non_gaap,
        non_gaap_reconciliation=reconcile_non_gaap(
            gaap_values, reported_non_gaap
        ),
    )
