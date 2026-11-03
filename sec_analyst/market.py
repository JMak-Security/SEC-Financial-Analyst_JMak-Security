"""Read-only public market quotes and daily closes from Yahoo Finance chart API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from numbers import Real
import re
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class MarketDataError(RuntimeError):
    """Raised when live market data cannot be retrieved or validated."""


@dataclass(frozen=True)
class MarketSnapshot:
    ticker: str
    currency: str
    exchange: str
    observed_at: str
    price: float
    daily_returns: list[float]
    source_url: str

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("daily_returns")
        data["return_observations"] = len(self.daily_returns)
        return data


class YahooFinanceClient:
    """Fetch read-only equity price history; this is not an order/trading client."""

    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

    def __init__(self, timeout: float = 12.0) -> None:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, Real)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("Market-data timeout must be a positive finite number.")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SEC-Financial-Analyst/1.0"})
        self.session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
                    total=4,
                    connect=4,
                    read=2,
                    status=4,
                    backoff_factor=0.5,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=frozenset({"GET"}),
                    respect_retry_after_header=True,
                    raise_on_status=False,
                )
            ),
        )

    def fetch(self, ticker: str) -> MarketSnapshot:
        if not isinstance(ticker, str) or not re.fullmatch(
            r"[A-Za-z0-9.^=-]{1,15}", ticker.strip()
        ):
            raise ValueError("Enter a valid public-market ticker symbol.")
        symbol = ticker.strip().upper()
        url = f"{self.BASE_URL}/{quote(symbol, safe='.-^=')}"
        try:
            response = self.session.get(
                url, params={"range": "1y", "interval": "1d"}, timeout=self.timeout
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise MarketDataError(f"Market-data request failed: {exc}") from exc
        except ValueError as exc:
            raise MarketDataError("Market-data API returned invalid JSON.") from exc
        try:
            chart = payload["chart"]
            if chart.get("error"):
                raise MarketDataError(
                    f"Market-data API rejected {symbol}: {chart['error']}."
                )
            result = chart["result"][0]
            meta = result["meta"]
            timestamps = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
            if len(timestamps) != len(closes):
                raise ValueError("timestamp and close lengths differ")
            normalized_closes: list[float | None] = []
            previous_timestamp = 0
            for timestamp, close in zip(timestamps, closes, strict=True):
                timestamp_value = int(timestamp)
                if timestamp_value <= previous_timestamp:
                    raise ValueError("timestamps must be strictly increasing")
                previous_timestamp = timestamp_value
                if close is None:
                    normalized_closes.append(None)
                    continue
                close_value = float(close)
                normalized_closes.append(
                    close_value
                    if math.isfinite(close_value) and close_value > 0
                    else None
                )
            returns = []
            for previous, current in zip(
                normalized_closes, normalized_closes[1:], strict=False
            ):
                if previous is not None and current is not None:
                    returns.append(current / previous - 1.0)
            price = float(meta["regularMarketPrice"])
            observed_timestamp = int(meta["regularMarketTime"])
            observed_at = datetime.fromtimestamp(
                observed_timestamp, tz=timezone.utc
            ).isoformat()
            if not math.isfinite(price) or price <= 0:
                raise ValueError("regular market price is not positive and finite")
            if len(returns) < 2:
                raise ValueError("at least three valid daily closes are required")
            return MarketSnapshot(
                ticker=symbol,
                currency=str(meta.get("currency") or "unknown"),
                exchange=str(meta.get("exchangeName") or "unknown"),
                observed_at=observed_at,
                price=price,
                daily_returns=returns,
                source_url=url,
            )
        except MarketDataError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
            raise MarketDataError(
                f"Market-data API returned an unusable response for {symbol}: {exc}."
            ) from exc
