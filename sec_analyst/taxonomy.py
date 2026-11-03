"""Validated user-provided taxonomy crosswalks and non-GAAP reconciliations."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping


SUPPORTED_METRICS = {
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "cash_and_equivalents",
    "current_assets",
    "current_liabilities",
    "total_assets",
    "total_liabilities",
    "shareholders_equity",
    "operating_cash_flow",
}
_TAG = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:[A-Za-z][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class TaxonomyMappings:
    custom_gaap: dict[str, str]
    non_gaap: dict[str, str]

    @classmethod
    def from_payload(cls, payload: Any) -> TaxonomyMappings:
        if not isinstance(payload, dict) or set(payload) - {"custom_gaap", "non_gaap"}:
            raise ValueError(
                "Taxonomy mapping JSON must contain only custom_gaap/non_gaap objects."
            )
        return cls(
            _validate_mapping(payload.get("custom_gaap", {}), "custom_gaap"),
            _validate_mapping(payload.get("non_gaap", {}), "non_gaap"),
        )

    @classmethod
    def from_json(cls, content: bytes) -> TaxonomyMappings:
        if not isinstance(content, bytes) or len(content) > 250_000:
            raise ValueError("Taxonomy mapping JSON must be bytes no larger than 250 KB.")
        try:
            payload = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Taxonomy mappings must be valid UTF-8 JSON.") from exc
        return cls.from_payload(payload)


def _validate_mapping(raw: Any, label: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a JSON object mapping metrics to XBRL tags.")
    if set(raw) - SUPPORTED_METRICS:
        raise ValueError(
            f"{label} contains unsupported metrics: "
            + ", ".join(sorted(set(raw) - SUPPORTED_METRICS))
        )
    mappings: dict[str, str] = {}
    for metric, tag in raw.items():
        if not isinstance(tag, str) or not _TAG.fullmatch(tag.strip()):
            raise ValueError(
                f"{label}.{metric} must be a qualified XBRL tag such as issuer:Revenue."
            )
        mappings[metric] = tag.strip()
    return mappings


def reconcile_non_gaap(
    gaap_values: Mapping[str, float | None],
    non_gaap_values: Mapping[str, float | None],
) -> dict[str, dict[str, float | None]]:
    """Report differences, never substitute non-GAAP figures into GAAP ratios."""
    reconciliations: dict[str, dict[str, float | None]] = {}
    for metric, reported in non_gaap_values.items():
        gaap = gaap_values.get(metric)
        if reported is None or gaap is None:
            continue
        reconciliations[metric] = {
            "gaap_value": float(gaap),
            "reported_non_gaap_value": float(reported),
            "absolute_difference": float(reported) - float(gaap),
            "relative_difference": (
                (float(reported) - float(gaap)) / abs(float(gaap))
                if gaap != 0
                else None
            ),
        }
    return reconciliations
