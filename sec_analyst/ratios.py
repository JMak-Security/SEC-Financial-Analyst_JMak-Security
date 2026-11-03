"""Financial ratio calculations with explicit missing-data behavior."""

from __future__ import annotations

from .models import FinancialStatements


def _divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def calculate_ratios(statements: FinancialStatements) -> dict[str, float | None]:
    bs = statements.balance_sheet
    income = statements.income_statement
    cash_flow = statements.cash_flow_statement

    current_assets = bs.get("current_assets")
    inventory = bs.get("inventory")
    prepaid = bs.get("prepaid_expenses")
    quick_assets = (
        current_assets - inventory - (prepaid or 0.0)
        if current_assets is not None and inventory is not None
        else None
    )
    revenue = income.get("revenue")
    gross_profit = income.get("gross_profit")
    if gross_profit is None and revenue is not None:
        cost = income.get("cost_of_revenue")
        if cost is not None:
            gross_profit = revenue - cost

    operating_cash_flow = cash_flow.get("operating_cash_flow")
    capital_expenditures = cash_flow.get("capital_expenditures")
    free_cash_flow = (
        operating_cash_flow - abs(capital_expenditures)
        if operating_cash_flow is not None and capital_expenditures is not None
        else None
    )
    total_assets = bs.get("total_assets")
    total_liabilities = bs.get("total_liabilities")
    equity = bs.get("shareholders_equity")
    current_liabilities = bs.get("current_liabilities")
    net_income = income.get("net_income")

    return {
        "current_ratio": _divide(current_assets, current_liabilities),
        "quick_ratio": _divide(quick_assets, current_liabilities),
        "cash_ratio": _divide(
            bs.get("cash_and_equivalents"), current_liabilities
        ),
        "liabilities_to_assets": _divide(total_liabilities, total_assets),
        "liabilities_to_equity": _divide(total_liabilities, equity),
        "gross_margin": _divide(gross_profit, revenue),
        "operating_margin": _divide(income.get("operating_income"), revenue),
        "net_margin": _divide(net_income, revenue),
        "return_on_assets": _divide(net_income, total_assets),
        "return_on_equity": _divide(net_income, equity),
        "operating_cash_flow_ratio": _divide(
            operating_cash_flow, current_liabilities
        ),
        "free_cash_flow": free_cash_flow,
    }
