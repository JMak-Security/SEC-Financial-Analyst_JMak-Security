"""Transparent historical-replay and regulatory-reference stress scenarios."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


BASEL_MARKET_RISK_REFERENCE = "https://www.bis.org/basel_framework/chapter/MAR/21.htm"
FRB_STRESS_TEST_REFERENCE = (
    "https://www.federalreserve.gov/supervisionreg/stress-tests-capital-planning.htm"
)


@dataclass(frozen=True)
class StressScenario:
    scenario_id: str
    title: str
    framework: str
    shocks: dict[str, float]
    reference_url: str
    classification: str = "illustrative"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StressReport:
    scenario: StressScenario
    portfolio_return: float
    loss: float
    asset_impacts: dict[str, float]
    assumptions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario.as_dict(),
            "portfolio_return": self.portfolio_return,
            "loss": self.loss,
            "asset_impacts": self.asset_impacts,
            "assumptions": list(self.assumptions),
        }


def historical_replay(
    returns: pd.DataFrame,
    weights: Mapping[str, float],
    portfolio_value: float,
    start_date: str,
    end_date: str,
    scenario_name: str = "User-selected historical replay",
) -> StressReport:
    """Replay the compounded observed returns within an explicitly dated window."""
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise ValueError("Historical replay requires a DatetimeIndex.")
    if not returns.index.is_monotonic_increasing or returns.index.has_duplicates:
        raise ValueError("Historical replay dates must be unique and increasing.")
    if returns.index.hasnans:
        raise ValueError("Historical replay dates must not contain NaT.")
    try:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("Historical replay dates must be valid timestamps.") from exc
    if returns.index.tz is not None:
        start = start.tz_localize(returns.index.tz) if start.tz is None else start.tz_convert(returns.index.tz)
        end = end.tz_localize(returns.index.tz) if end.tz is None else end.tz_convert(returns.index.tz)
    elif start.tz is not None or end.tz is not None:
        raise ValueError("Historical replay dates and returns must use the same timezone.")
    if start > end:
        raise ValueError("Historical replay start_date must not follow end_date.")
    selected = returns.loc[(returns.index >= start) & (returns.index <= end)]
    if selected.empty:
        raise ValueError("No market observations fall within the selected period.")
    if not np.isfinite(portfolio_value) or portfolio_value <= 0:
        raise ValueError("Portfolio value must be finite and greater than zero.")
    if set(selected.columns) != set(weights):
        raise ValueError("Historical replay weights must match the selected assets.")
    try:
        raw_weights = np.asarray(
            [weights[name] for name in selected.columns], dtype=float
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Replay weights must be numeric.") from exc
    if not np.isfinite(raw_weights).all() or raw_weights.sum() <= 0:
        raise ValueError("Replay weights must be finite and have a positive sum.")
    normalized_weights = raw_weights / raw_weights.sum()
    values = selected.to_numpy(dtype=float)
    if not np.isfinite(values).all() or np.any(values < -1.0):
        raise ValueError("Historical replay returns must be finite and not below -100%.")
    asset_returns = np.prod(1.0 + values, axis=0) - 1.0
    asset_impacts = dict(zip(selected.columns, asset_returns.tolist(), strict=True))
    portfolio_return = float(asset_returns @ normalized_weights)
    scenario = StressScenario(
        scenario_id="historical-replay",
        title=scenario_name,
        framework="Observed historical market-data replay",
        shocks=asset_impacts,
        reference_url="user-supplied dated return observations",
        classification="observed-replay-not-forecast",
    )
    return StressReport(
        scenario=scenario,
        portfolio_return=portfolio_return,
        loss=-portfolio_return * float(portfolio_value),
        asset_impacts=asset_impacts,
        assumptions=(
            "Historical path compounded from the supplied observations.",
            "This is not a forecast and does not model liquidity or market impact.",
            "Portfolio weights are normalized to a positive net sum.",
        ),
    )


def reference_scenarios() -> list[StressScenario]:
    """Return parameterized reference shocks, explicitly not regulatory prescriptions."""
    return [
        StressScenario(
            scenario_id="frtb-equity-down-20",
            title="Illustrative equity down 20% (Basel MAR 21 reference)",
            framework="Basel market-risk framework reference (MAR 21)",
            shocks={"equity": -0.20},
            reference_url=BASEL_MARKET_RISK_REFERENCE,
        ),
        StressScenario(
            scenario_id="frtb-equity-up-15",
            title="Illustrative equity up 15% (Basel MAR 21 reference)",
            framework="Basel market-risk framework reference (MAR 21)",
            shocks={"equity": 0.15},
            reference_url=BASEL_MARKET_RISK_REFERENCE,
        ),
        StressScenario(
            scenario_id="parallel-rates-up-200bp",
            title="Parallel yield-curve shift up 200 bp",
            framework="User-configurable duration-based rate sensitivity",
            shocks={"rates_parallel_bps": 200.0},
            reference_url=BASEL_MARKET_RISK_REFERENCE,
        ),
        StressScenario(
            scenario_id="parallel-rates-down-200bp",
            title="Parallel yield-curve shift down 200 bp",
            framework="User-configurable duration-based rate sensitivity",
            shocks={"rates_parallel_bps": -200.0},
            reference_url=BASEL_MARKET_RISK_REFERENCE,
        ),
        StressScenario(
            scenario_id="gfc-equity-down-50",
            title="2008 crisis-scale equity drawdown",
            framework="Historical crisis-scale sensitivity",
            shocks={"equity": -0.50},
            reference_url=FRB_STRESS_TEST_REFERENCE,
        ),
        StressScenario(
            scenario_id="fx-usd-up-10",
            title="Foreign-exchange exposure shock",
            framework="User-configurable FX sensitivity",
            shocks={"fx": -0.10},
            reference_url=BASEL_MARKET_RISK_REFERENCE,
        ),
    ]


def apply_reference_scenario(
    scenario: StressScenario,
    market_values: Mapping[str, float],
    asset_classes: Mapping[str, str],
    portfolio_value: float,
    modified_durations: Mapping[str, float] | None = None,
) -> StressReport:
    """Apply factor shocks; rate shocks use duration-only first-order repricing."""
    if not np.isfinite(portfolio_value) or portfolio_value <= 0:
        raise ValueError("Portfolio value must be finite and greater than zero.")
    if not market_values or set(market_values) != set(asset_classes):
        raise ValueError("Every market value must have exactly one asset class.")
    values = np.asarray(list(market_values.values()), dtype=float)
    if not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("Market values must be finite and non-negative.")
    if values.sum() <= 0:
        raise ValueError("At least one market value must be positive.")
    if any(asset_class not in {"equity", "rates", "fx", "commodity"} for asset_class in asset_classes.values()):
        raise ValueError("Asset classes must be equity, rates, fx, or commodity.")
    durations = modified_durations or {}
    unknown_durations = set(durations) - set(market_values)
    if unknown_durations:
        raise ValueError(
            "Modified durations reference unknown assets: "
            + ", ".join(sorted(unknown_durations))
        )
    impacts: dict[str, float] = {}
    for asset, asset_class in asset_classes.items():
        if asset_class == "rates":
            shock_bps = scenario.shocks.get("rates_parallel_bps", 0.0)
            duration = float(durations.get(asset, 0.0))
            if not np.isfinite(duration) or duration < 0:
                raise ValueError(f"Modified duration for {asset} must be finite and non-negative.")
            impacts[asset] = -duration * shock_bps / 10_000.0
        else:
            impacts[asset] = float(scenario.shocks.get(asset_class, 0.0))
        if not np.isfinite(impacts[asset]) or impacts[asset] < -1.0:
            raise ValueError(f"Scenario shock for {asset} is invalid.")
    gross_market_value = float(values.sum())
    portfolio_return = sum(
        float(market_values[asset]) * impacts[asset]
        for asset in market_values
    ) / gross_market_value
    return StressReport(
        scenario=scenario,
        portfolio_return=portfolio_return,
        loss=-portfolio_return * float(portfolio_value),
        asset_impacts=impacts,
        assumptions=(
            "Factor mappings and market values are supplied by the user.",
            "Rate shocks use first-order modified-duration approximation; convexity is omitted.",
            "Reference shocks are illustrative and do not implement a regulatory capital calculation.",
            "This result is not a Basel/FRTB or supervisory compliance determination.",
        ),
    )
