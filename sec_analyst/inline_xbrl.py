"""Bounded parser for SEC Inline XBRL facts in a filing's primary HTML document."""

from __future__ import annotations

from html.parser import HTMLParser
import math
import re
from typing import Any


class InlineXbrlError(ValueError):
    """Raised when a filing's Inline XBRL document is malformed or too large."""


def _local_name(name: str) -> str:
    return name.rsplit(":", 1)[-1].lower()


class _InlineFactsParser(HTMLParser):
    def __init__(
        self, accession: str, form: str, filing_date: str, period_end: str
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.accession = accession
        self.form = form
        self.filing_date = filing_date
        self.period_end = period_end
        self.contexts: dict[str, dict[str, str]] = {}
        self.units: dict[str, str] = {}
        self.facts: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._active_context: str | None = None
        self._context_stack: list[str] = []
        self._active_unit: str | None = None
        self._unit_stack: list[str] = []
        self._active_capture: tuple[str, str] | None = None
        self._fact_stack: list[dict[str, Any]] = []
        self._capture_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        name = _local_name(tag)
        if name == "context" and attributes.get("id"):
            self._active_context = attributes["id"]
            self._context_stack.append(self._active_context)
            self.contexts[self._active_context] = {}
        elif name == "unit" and attributes.get("id"):
            self._active_unit = attributes["id"]
            self._unit_stack.append(self._active_unit)
            self.units[self._active_unit] = ""
        if name == "explicitmember" and self._active_context:
            dimension = attributes.get("dimension")
            if dimension:
                self._active_capture = ("dimension", dimension)
        if name in {"startdate", "enddate", "instant"} and self._active_context:
            self._active_capture = ("context", name)
        elif name == "measure" and self._active_unit:
            self._active_capture = ("unit", self._active_unit)
        if tag.lower() in {"ix:nonfraction", "ix:nonnumeric"}:
            qualified_name = attributes.get("name", "")
            context_ref = attributes.get("contextref", "")
            if not qualified_name or not context_ref:
                return
            self._fact_stack.append(
                {
                    "tag": tag.lower(),
                    "name": qualified_name,
                    "context_ref": context_ref,
                    "unit_ref": attributes.get("unitref", ""),
                    "scale": attributes.get("scale", "0"),
                    "sign": attributes.get("sign", ""),
                    "format": attributes.get("format", ""),
                    "id": attributes.get("id", ""),
                    "text": "",
                    "nested": 0,
                }
            )
            self._capture_depth = 1
        elif self._fact_stack:
            self._fact_stack[-1]["nested"] += 1

    def handle_endtag(self, tag: str) -> None:
        name = _local_name(tag)
        if self._active_capture and name in {
            "startdate",
            "enddate",
            "instant",
            "measure",
            "explicitmember",
        }:
            self._active_capture = None
        if name == "context" and self._context_stack:
            self._context_stack.pop()
            self._active_context = (
                self._context_stack[-1] if self._context_stack else None
            )
        if name == "unit" and self._unit_stack:
            self._unit_stack.pop()
            self._active_unit = self._unit_stack[-1] if self._unit_stack else None
        if not self._fact_stack:
            return
        if tag.lower() in {"ix:nonfraction", "ix:nonnumeric"}:
            fact = self._fact_stack.pop()
            self._finish_fact(fact)
            return
        self._fact_stack[-1]["nested"] = max(
            0, self._fact_stack[-1]["nested"] - 1
        )

    def handle_data(self, data: str) -> None:
        if self._active_capture:
            kind, key = self._active_capture
            if kind == "context" and self._active_context:
                current = self.contexts[self._active_context]
                current[key] = current.get(key, "") + data.strip()
            elif kind == "unit" and self._active_unit:
                self.units[self._active_unit] += data.strip()
            elif kind == "dimension" and self._active_context:
                current = self.contexts[self._active_context]
                dimensions = current.setdefault("dimensions", {})
                dimensions[key] = dimensions.get(key, "") + data.strip()
        if self._fact_stack:
            self._fact_stack[-1]["text"] += data

    def _finish_fact(self, fact: dict[str, Any]) -> None:
        raw_value = re.sub(r"\s+", "", fact["text"])
        if fact["tag"] == "ix:nonnumeric":
            return
        if not raw_value:
            return
        try:
            scale = int(fact["scale"] or "0")
            if not -30 <= scale <= 30:
                raise ValueError("fact scale is outside the supported -30..30 range")
            if len(raw_value) > 256:
                raise ValueError("numeric fact text exceeds the 256-character limit")
            value = float(raw_value.replace(",", ""))
            value *= 10**scale
            if fact["sign"] == "-":
                value = -abs(value)
            if not math.isfinite(value):
                raise ValueError("non-finite fact")
        except (OverflowError, ValueError) as exc:
            raise InlineXbrlError(
                f"Invalid Inline XBRL numeric value for {fact['name']}: {exc}."
            ) from exc
        context = self.contexts.get(fact["context_ref"])
        unit = self.units.get(fact["unit_ref"])
        if context is None or not unit:
            return
        taxonomy, separator, concept = fact["name"].partition(":")
        if not separator or not taxonomy or not concept:
            return
        unit_name = unit.rsplit(":", 1)[-1]
        period_end = context.get("enddate") or context.get("instant")
        entry: dict[str, Any] = {
            "val": value,
            "accn": self.accession,
            "form": self.form,
            "filed": self.filing_date,
            "end": period_end or self.period_end,
            "unit": unit_name,
            "context_ref": fact["context_ref"],
            "element_id": fact["id"],
            "inline_format": fact["format"],
            "scale": fact["scale"],
            "dimensions": context.get("dimensions", {}),
        }
        if context.get("startdate"):
            entry["start"] = context["startdate"]
        namespace = self.facts.setdefault(taxonomy, {})
        concept_units = namespace.setdefault(concept, {}).setdefault("units", {})
        concept_units.setdefault(unit_name, []).append(entry)


def parse_inline_xbrl(
    content: bytes,
    *,
    accession: str,
    form: str,
    filing_date: str,
    period_end: str,
    max_bytes: int = 20_000_000,
) -> dict[str, Any]:
    if not isinstance(content, bytes) or len(content) > max_bytes:
        raise InlineXbrlError(
            f"Inline XBRL document must be bytes no larger than {max_bytes:,}."
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InlineXbrlError("Inline XBRL document must be valid UTF-8.") from exc
    parser = _InlineFactsParser(accession, form, filing_date, period_end)
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, AssertionError) as exc:
        raise InlineXbrlError(f"Could not parse Inline XBRL document: {exc}") from exc
    if not parser.facts:
        raise InlineXbrlError("No supported Inline XBRL numeric facts were found.")
    return {"facts": parser.facts, "contexts": len(parser.contexts)}
