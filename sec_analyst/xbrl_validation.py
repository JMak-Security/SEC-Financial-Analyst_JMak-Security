"""Structural and filing-period validation for SEC CompanyFacts payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import math
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }


class XbrlValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        summary = "; ".join(
            f"{issue.path}: {issue.message}"
            for issue in issues
            if issue.severity == "error"
        )
        super().__init__(f"SEC XBRL validation failed: {summary}")


def validate_companyfacts(
    payload: dict[str, Any],
    *,
    expected_cik: str | None = None,
    filing_accession: str | None = None,
) -> list[ValidationIssue]:
    """Validate all supplied standardized facts and identify filing mismatches."""
    issues: list[ValidationIssue] = []
    if not isinstance(payload, dict):
        raise XbrlValidationError(
            [ValidationIssue("error", "$", "payload must be a JSON object")]
        )
    cik = payload.get("cik")
    if cik is not None and not str(cik).isdigit():
        issues.append(ValidationIssue("error", "cik", "must be a numeric CIK"))
    if expected_cik is not None and cik is not None:
        if str(cik).zfill(10) != str(expected_cik).zfill(10):
            issues.append(
                ValidationIssue("error", "cik", "does not match the selected filing")
            )
    facts_root = payload.get("facts")
    if not isinstance(facts_root, dict) or not facts_root:
        issues.append(
            ValidationIssue("error", "facts", "must contain at least one taxonomy")
        )
    elif not any(
        isinstance(namespace, dict) and namespace
        for namespace in facts_root.values()
    ):
        issues.append(
            ValidationIssue("error", "facts", "taxonomies must contain concepts")
        )
    if any(issue.severity == "error" for issue in issues):
        raise XbrlValidationError(issues)

    matched_accession = False
    for namespace_name, concepts in facts_root.items():
        if not isinstance(concepts, dict):
            issues.append(
                ValidationIssue(
                    "error", f"facts.{namespace_name}", "taxonomy must be an object"
                )
            )
            continue
        for concept_name, concept in concepts.items():
            path = f"facts.{namespace_name}.{concept_name}"
            if not isinstance(concept, dict):
                issues.append(ValidationIssue("error", path, "concept must be an object"))
                continue
            units = concept.get("units")
            if not isinstance(units, dict) or not units:
                issues.append(
                    ValidationIssue("error", f"{path}.units", "must be a non-empty object")
                )
                continue
            for unit, entries in units.items():
                unit_path = f"{path}.units.{unit}"
                if not isinstance(unit, str) or not unit.strip():
                    issues.append(ValidationIssue("error", unit_path, "unit is blank"))
                if not isinstance(entries, list):
                    issues.append(
                        ValidationIssue("error", unit_path, "unit facts must be a list")
                    )
                    continue
                seen: set[tuple[str, str, str, str, str]] = set()
                for index, entry in enumerate(entries):
                    entry_path = f"{unit_path}[{index}]"
                    if not isinstance(entry, dict):
                        issues.append(
                            ValidationIssue("error", entry_path, "fact must be an object")
                        )
                        continue
                    value = entry.get("val")
                    if isinstance(value, bool):
                        valid_number = False
                    else:
                        try:
                            valid_number = math.isfinite(float(value))
                        except (TypeError, ValueError, OverflowError):
                            valid_number = False
                    if not valid_number:
                        issues.append(
                            ValidationIssue(
                                "error", f"{entry_path}.val", "must be a finite number"
                            )
                        )
                    for date_field in ("start", "end", "filed"):
                        raw_date = entry.get(date_field)
                        if raw_date is None:
                            continue
                        try:
                            date.fromisoformat(str(raw_date))
                        except ValueError:
                            issues.append(
                                ValidationIssue(
                                    "error",
                                    f"{entry_path}.{date_field}",
                                    "must be an ISO 8601 date",
                                )
                            )
                    start = entry.get("start")
                    end = entry.get("end")
                    if start and end:
                        try:
                            if date.fromisoformat(str(start)) > date.fromisoformat(str(end)):
                                issues.append(
                                    ValidationIssue(
                                        "error",
                                        entry_path,
                                        "duration start must not follow end",
                                    )
                                )
                        except ValueError:
                            pass
                    accession = str(entry.get("accn") or "")
                    form = str(entry.get("form") or "")
                    if accession and form and end:
                        dimensions = entry.get("dimensions", {})
                        dimension_key = (
                            json.dumps(dimensions, sort_keys=True)
                            if isinstance(dimensions, dict)
                            else str(dimensions)
                        )
                        key = (
                            accession,
                            form,
                            str(start or ""),
                            str(end),
                            dimension_key,
                        )
                        if key in seen:
                            issues.append(
                                ValidationIssue(
                                    "warning",
                                    entry_path,
                                    "duplicate accession/form/period fact context",
                                )
                            )
                        seen.add(key)
                    if filing_accession and accession == filing_accession:
                        matched_accession = True
    if filing_accession and not matched_accession:
        issues.append(
            ValidationIssue(
                "error",
                "facts",
                f"no fact is associated with filing accession {filing_accession}",
            )
        )
    if any(issue.severity == "error" for issue in issues):
        raise XbrlValidationError(issues)
    return issues
