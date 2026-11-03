"""Optional Alpaca minute-bar to Kafka stream with rolling risk updates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import math
import os
import ssl
from typing import Any, Awaitable, Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from .engine import RiskEngine

logger = logging.getLogger(__name__)
StatusCallback = Callable[[str, Mapping[str, Any]], Awaitable[None] | None]


class StreamAuthenticationError(RuntimeError):
    """Raised when the market-data provider rejects stream credentials."""


@dataclass(frozen=True)
class AlpacaKafkaConfig:
    api_key: str = field(repr=False)
    api_secret: str = field(repr=False)
    kafka_bootstrap_servers: str
    feed: str = "iex"
    market_topic: str = "market.bars"
    risk_topic: str = "risk.snapshots"
    kafka_security_protocol: str = "PLAINTEXT"
    kafka_sasl_mechanism: str | None = None
    kafka_sasl_username: str | None = None
    kafka_sasl_password: str | None = field(default=None, repr=False)
    kafka_ssl_cafile: str | None = None
    kafka_ssl_certfile: str | None = None
    kafka_ssl_keyfile: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.api_key.strip() or not self.api_secret.strip():
            raise ValueError("Alpaca API credentials must not be blank.")
        if not self.kafka_bootstrap_servers.strip():
            raise ValueError("Kafka bootstrap servers must not be blank.")
        if self.feed not in {"iex", "sip"}:
            raise ValueError("Alpaca feed must be 'iex' or 'sip'.")
        if self.kafka_security_protocol not in {
            "PLAINTEXT",
            "SSL",
            "SASL_PLAINTEXT",
            "SASL_SSL",
        }:
            raise ValueError("Unsupported Kafka security protocol.")
        if self.kafka_security_protocol.startswith("SASL_"):
            if not self.kafka_sasl_username or not self.kafka_sasl_password:
                raise ValueError("Kafka SASL username and password are required.")
            if self.kafka_sasl_mechanism not in {
                "PLAIN",
                "SCRAM-SHA-256",
                "SCRAM-SHA-512",
            }:
                raise ValueError("A supported Kafka SASL mechanism is required.")
        if bool(self.kafka_ssl_certfile) != bool(self.kafka_ssl_keyfile):
            raise ValueError("Kafka client certificate and key must be supplied together.")
        if self.kafka_ssl_cafile or self.kafka_ssl_certfile:
            if not self.kafka_security_protocol.endswith("SSL"):
                raise ValueError("Kafka SSL certificates require an SSL protocol.")

    @classmethod
    def from_environment(cls) -> AlpacaKafkaConfig:
        required = (
            "ALPACA_API_KEY",
            "ALPACA_API_SECRET",
            "KAFKA_BOOTSTRAP_SERVERS",
        )
        missing = [name for name in required if not os.environ.get(name, "").strip()]
        if missing:
            raise ValueError(f"Missing streaming settings: {', '.join(missing)}.")
        return cls(
            api_key=os.environ["ALPACA_API_KEY"],
            api_secret=os.environ["ALPACA_API_SECRET"],
            kafka_bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"],
            feed=os.environ.get("ALPACA_FEED", "iex").strip().lower(),
            kafka_security_protocol=os.environ.get(
                "KAFKA_SECURITY_PROTOCOL", "PLAINTEXT"
            ).strip().upper(),
            kafka_sasl_mechanism=os.environ.get("KAFKA_SASL_MECHANISM"),
            kafka_sasl_username=os.environ.get("KAFKA_SASL_USERNAME"),
            kafka_sasl_password=os.environ.get("KAFKA_SASL_PASSWORD"),
            kafka_ssl_cafile=os.environ.get("KAFKA_SSL_CAFILE"),
            kafka_ssl_certfile=os.environ.get("KAFKA_SSL_CERTFILE"),
            kafka_ssl_keyfile=os.environ.get("KAFKA_SSL_KEYFILE"),
        )


async def run_alpaca_kafka_stream(
    config: AlpacaKafkaConfig,
    symbols: Sequence[str],
    weights: Mapping[str, float],
    portfolio_value: float,
    *,
    history_observations: int = 500,
    reconnect_limit: int = 8,
    status_callback: StatusCallback | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Stream Alpaca minute bars into Kafka and publish rolling 95% risk snapshots.

    Credentials are read only from the provided config/environment. The stream
    publishes market events and computed risk summaries, never order messages.
    """
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("Streaming symbols must be a non-empty unique sequence.")
    normalized_symbols = [symbol.strip().upper() for symbol in symbols]
    if any(not symbol for symbol in normalized_symbols):
        raise ValueError("Streaming symbols must not be blank.")
    if set(normalized_symbols) != set(weights):
        raise ValueError("Streaming weights must match the subscribed symbols.")
    if history_observations < 2:
        raise ValueError("At least two history observations are required.")
    if reconnect_limit < 0:
        raise ValueError("reconnect_limit must be non-negative.")
    if not config.market_topic.strip() or not config.risk_topic.strip():
        raise ValueError("Kafka market and risk topic names must not be blank.")
    try:
        import websockets
        from websockets.exceptions import ConnectionClosed
        from aiokafka import AIOKafkaProducer
    except ImportError as exc:
        raise RuntimeError(
            "Streaming requires the optional packages in "
            "production_requirements.txt."
        ) from exc
    stop = stop_event or asyncio.Event()
    url = f"wss://stream.data.alpaca.markets/v2/{config.feed}"
    producer_options: dict[str, Any] = {
        "bootstrap_servers": config.kafka_bootstrap_servers,
        "value_serializer": None,
        "key_serializer": None,
        "security_protocol": config.kafka_security_protocol,
    }
    if config.kafka_security_protocol.startswith("SASL_"):
        producer_options.update(
            {
                "sasl_mechanism": config.kafka_sasl_mechanism,
                "sasl_plain_username": config.kafka_sasl_username,
                "sasl_plain_password": config.kafka_sasl_password,
            }
        )
    if config.kafka_security_protocol.endswith("SSL"):
        ssl_context = ssl.create_default_context(cafile=config.kafka_ssl_cafile)
        if config.kafka_ssl_certfile and config.kafka_ssl_keyfile:
            ssl_context.load_cert_chain(
                config.kafka_ssl_certfile, config.kafka_ssl_keyfile
            )
        producer_options["ssl_context"] = ssl_context
    producer = AIOKafkaProducer(
        **producer_options,
    )
    await producer.start()
    previous_close: dict[str, float] = {}
    return_rows: dict[str, dict[str, float]] = {}
    attempts = 0

    async def notify(event: str, details: Mapping[str, Any]) -> None:
        if status_callback is None:
            logger.info("%s: %s", event, details)
            return
        callback_result = status_callback(event, details)
        if callback_result is not None:
            await callback_result

    async def process_message(raw_message: str) -> None:
        nonlocal attempts
        try:
            messages = json.loads(raw_message)
        except json.JSONDecodeError as exc:
            await notify("malformed_provider_message", {"error": str(exc)})
            return
        if not isinstance(messages, list):
            raise RuntimeError("Alpaca WebSocket response must be a JSON array.")
        for message in messages:
            if not isinstance(message, dict):
                raise RuntimeError("Alpaca WebSocket event must be a JSON object.")
            if "error" in message:
                await notify("provider_error", {"message": str(message["error"])})
                raise RuntimeError(f"Alpaca stream error: {message['error']}")
            if message.get("T") != "b":
                continue
            symbol = message.get("S")
            timestamp = message.get("t")
            close = message.get("c")
            if symbol not in normalized_symbols:
                continue
            try:
                close_value = float(close)
                bar_time = datetime.fromisoformat(
                    str(timestamp).replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except (TypeError, ValueError) as exc:
                await notify(
                    "invalid_bar",
                    {"symbol": symbol, "error": str(exc)},
                )
                continue
            if not math.isfinite(close_value) or close_value <= 0:
                await notify("invalid_bar", {"symbol": symbol, "close": close})
                continue
            event = {
                "type": "bar",
                "symbol": symbol,
                "timestamp": bar_time.isoformat(),
                "close": close_value,
            }
            await producer.send_and_wait(
                config.market_topic,
                json.dumps(event, separators=(",", ":")).encode(),
                key=symbol.encode(),
            )
            bar_key = bar_time.isoformat()
            old_close = previous_close.get(symbol)
            previous_close[symbol] = close_value
            if old_close is None:
                continue
            return_rows.setdefault(bar_key, {})[symbol] = close_value / old_close - 1
            row = return_rows[bar_key]
            if set(row) != set(normalized_symbols):
                continue
            observation = {name: row[name] for name in normalized_symbols}
            aligned = pd.DataFrame.from_records(
                [dict(values) for _, values in sorted(return_rows.items())
                 if set(values) == set(normalized_symbols)],
                columns=normalized_symbols,
            )
            if len(aligned) > history_observations:
                aligned = aligned.tail(history_observations).reset_index(drop=True)
            if len(aligned) < 2:
                continue
            risk = RiskEngine(aligned, weights).calculate(
                portfolio_value, confidence=0.95
            )
            snapshot = {
                "type": "rolling_risk",
                "timestamp": bar_key,
                "assets": normalized_symbols,
                "latest_asset_returns": observation,
                "risk": {
                    "confidence": risk.confidence,
                    "historical_var": risk.historical_var,
                    "historical_cvar": risk.historical_cvar,
                    "parametric_var": risk.parametric_var,
                    "parametric_cvar": risk.parametric_cvar,
                    "observations": risk.observations,
                    "portfolio_value": risk.portfolio_value,
                },
                "source": "Alpaca minute bars",
                "not_an_order": True,
            }
            await producer.send_and_wait(
                config.risk_topic,
                json.dumps(snapshot, separators=(",", ":")).encode(),
                key=b"rolling-portfolio",
            )
            attempts = 0
            await notify("risk_snapshot", snapshot["risk"])
            if len(return_rows) > history_observations * 2:
                keep_keys = sorted(return_rows)[-history_observations:]
                retained_rows = [(key, return_rows[key]) for key in keep_keys]
                return_rows.clear()
                return_rows.update(retained_rows)

    try:
        while not stop.is_set():
            try:
                connected_at = asyncio.get_running_loop().time()
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=1_000_000,
                ) as websocket:
                    await websocket.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": config.api_key,
                                "secret": config.api_secret,
                            }
                        )
                    )
                    auth_reply = json.loads(await asyncio.wait_for(websocket.recv(), 10))
                    if not isinstance(auth_reply, list) or not any(
                        isinstance(item, dict)
                        and item.get("T") == "success"
                        and item.get("msg") == "authenticated"
                        for item in auth_reply
                    ):
                        raise StreamAuthenticationError(
                            "Alpaca WebSocket authentication failed."
                        )
                    await websocket.send(
                        json.dumps(
                            {
                                "action": "subscribe",
                                "bars": normalized_symbols,
                            }
                        )
                    )
                    await notify(
                        "connected",
                        {"feed": config.feed, "symbols": normalized_symbols},
                    )
                    while not stop.is_set():
                        try:
                            raw_message = await asyncio.wait_for(
                                websocket.recv(), timeout=1.0
                            )
                        except asyncio.TimeoutError:
                            continue
                        await process_message(raw_message)
            except asyncio.CancelledError:
                raise
            except StreamAuthenticationError:
                await notify(
                    "authentication_failed",
                    {"feed": config.feed, "symbols": normalized_symbols},
                )
                raise
            except (
                ConnectionClosed,
                OSError,
                RuntimeError,
                asyncio.TimeoutError,
            ) as exc:
                if "connected_at" in locals() and (
                    asyncio.get_running_loop().time() - connected_at >= 60
                ):
                    attempts = 0
                attempts += 1
                await notify(
                    "stream_disconnected",
                    {"attempt": attempts, "error": str(exc)},
                )
                if attempts > reconnect_limit:
                    raise RuntimeError(
                        "Alpaca stream exceeded its reconnect limit."
                    ) from exc
                await asyncio.sleep(min(2 ** (attempts - 1), 60))
    finally:
        await producer.stop()
