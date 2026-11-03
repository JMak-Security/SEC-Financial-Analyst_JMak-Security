"""Generate deterministic, synthetic SEC-shaped submissions and CompanyFacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"

FILINGS = [
    {
        "form": "10-Q",
        "filingDate": "2026-11-01",
        "reportDate": "2026-09-30",
        "accessionNumber": "0000000001-26-000003",
        "primaryDocument": "sample-q3.htm",
        "period_start": "2026-07-01",
        "days": 91,
        "fy": 2026,
        "fp": "Q3",
        "values": {
            "CashAndCashEquivalentsAtCarryingValue": 180_000_000,
            "ShortTermInvestments": 40_000_000,
            "AccountsReceivableNetCurrent": 120_000_000,
            "InventoryNet": 60_000_000,
            "PrepaidExpenseCurrent": 10_000_000,
            "AssetsCurrent": 430_000_000,
            "PropertyPlantAndEquipmentNet": 250_000_000,
            "Assets": 900_000_000,
            "LiabilitiesCurrent": 300_000_000,
            "LongTermDebtNoncurrent": 200_000_000,
            "Liabilities": 500_000_000,
            "StockholdersEquity": 400_000_000,
            "RevenueFromContractWithCustomerExcludingAssessedTax": 250_000_000,
            "CostOfRevenue": 150_000_000,
            "GrossProfit": 100_000_000,
            "OperatingIncomeLoss": 30_000_000,
            "NetIncomeLoss": 20_000_000,
            "NetCashProvidedByUsedInOperatingActivities": 35_000_000,
            "PaymentsToAcquirePropertyPlantAndEquipment": 12_000_000,
        },
    },
    {
        "form": "10-Q",
        "filingDate": "2026-08-01",
        "reportDate": "2026-06-30",
        "accessionNumber": "0000000001-26-000002",
        "primaryDocument": "sample-q2.htm",
        "period_start": "2026-04-01",
        "days": 90,
        "fy": 2026,
        "fp": "Q2",
        "values": {
            "CashAndCashEquivalentsAtCarryingValue": 160_000_000,
            "ShortTermInvestments": 35_000_000,
            "AccountsReceivableNetCurrent": 110_000_000,
            "InventoryNet": 65_000_000,
            "PrepaidExpenseCurrent": 10_000_000,
            "AssetsCurrent": 410_000_000,
            "PropertyPlantAndEquipmentNet": 245_000_000,
            "Assets": 870_000_000,
            "LiabilitiesCurrent": 320_000_000,
            "LongTermDebtNoncurrent": 205_000_000,
            "Liabilities": 525_000_000,
            "StockholdersEquity": 345_000_000,
            "RevenueFromContractWithCustomerExcludingAssessedTax": 220_000_000,
            "CostOfRevenue": 132_000_000,
            "GrossProfit": 88_000_000,
            "OperatingIncomeLoss": 25_000_000,
            "NetIncomeLoss": 16_000_000,
            "NetCashProvidedByUsedInOperatingActivities": 30_000_000,
            "PaymentsToAcquirePropertyPlantAndEquipment": 11_000_000,
        },
    },
    {
        "form": "10-K",
        "filingDate": "2026-03-01",
        "reportDate": "2025-12-31",
        "accessionNumber": "0000000001-26-000001",
        "primaryDocument": "sample-10k.htm",
        "period_start": "2025-01-01",
        "days": 364,
        "fy": 2025,
        "fp": "FY",
        "values": {
            "CashAndCashEquivalentsAtCarryingValue": 140_000_000,
            "ShortTermInvestments": 30_000_000,
            "AccountsReceivableNetCurrent": 100_000_000,
            "InventoryNet": 70_000_000,
            "PrepaidExpenseCurrent": 10_000_000,
            "AssetsCurrent": 390_000_000,
            "PropertyPlantAndEquipmentNet": 235_000_000,
            "Assets": 820_000_000,
            "LiabilitiesCurrent": 350_000_000,
            "LongTermDebtNoncurrent": 210_000_000,
            "Liabilities": 560_000_000,
            "StockholdersEquity": 260_000_000,
            "RevenueFromContractWithCustomerExcludingAssessedTax": 850_000_000,
            "CostOfRevenue": 535_000_000,
            "GrossProfit": 315_000_000,
            "OperatingIncomeLoss": 72_000_000,
            "NetIncomeLoss": 45_000_000,
            "NetCashProvidedByUsedInOperatingActivities": 88_000_000,
            "PaymentsToAcquirePropertyPlantAndEquipment": 40_000_000,
        },
    },
]

SUBMISSION_FIELDS = (
    "form",
    "filingDate",
    "reportDate",
    "accessionNumber",
    "primaryDocument",
)


def build_payloads() -> tuple[dict[str, Any], dict[str, Any]]:
    submissions: dict[str, Any] = {
        "cik": 1,
        "name": "Example Synthetic Holdings",
        "tickers": ["SYN"],
        "filings": {
            "recent": {
                field: [filing[field] for filing in FILINGS]
                for field in SUBMISSION_FIELDS
            }
        },
    }
    facts: dict[str, Any] = {
        "cik": 1,
        "entityName": "Example Synthetic Holdings",
        "facts": {"us-gaap": {}},
    }
    tags = sorted({tag for filing in FILINGS for tag in filing["values"]})
    for tag in tags:
        entries = []
        for filing in FILINGS:
            if tag not in filing["values"]:
                continue
            fact_entry: dict[str, Any] = {
                "accn": filing["accessionNumber"],
                "form": filing["form"],
                "filed": filing["filingDate"],
                "end": filing["reportDate"],
                "fy": filing["fy"],
                "fp": filing["fp"],
                "val": filing["values"][tag],
            }
            if tag not in {
                "CashAndCashEquivalentsAtCarryingValue",
                "ShortTermInvestments",
                "AccountsReceivableNetCurrent",
                "InventoryNet",
                "PrepaidExpenseCurrent",
                "AssetsCurrent",
                "PropertyPlantAndEquipmentNet",
                "Assets",
                "LiabilitiesCurrent",
                "LongTermDebtNoncurrent",
                "Liabilities",
                "StockholdersEquity",
            }:
                fact_entry["start"] = filing["period_start"]
            entries.append(fact_entry)
        facts["facts"]["us-gaap"][tag] = {
            "label": tag,
            "units": {"USD": entries},
        }
    return submissions, facts


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    submissions, facts = build_payloads()
    (SAMPLES / "sample_submissions.json").write_text(
        json.dumps(submissions, indent=2), encoding="utf-8"
    )
    (SAMPLES / "sample_companyfacts.json").write_text(
        json.dumps(facts, indent=2), encoding="utf-8"
    )
    print(f"Wrote synthetic SEC samples to {SAMPLES}")


if __name__ == "__main__":
    main()
