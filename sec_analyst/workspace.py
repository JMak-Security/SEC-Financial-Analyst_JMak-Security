"""Folder-scoped storage and offline SEC JSON discovery."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class WorkspaceManager:
    MANAGED_DIRS = ("incoming", "sec_cache", "reports")

    def __init__(self, root: str | Path, create: bool = False) -> None:
        path = Path(root).expanduser()
        if create:
            path.mkdir(parents=True, exist_ok=True)
        if not path.exists() or not path.is_dir():
            raise ValueError(f"Workspace must be an existing folder: {path}")
        self.root = path.resolve(strict=True)
        for name in self.MANAGED_DIRS:
            (self.root / name).mkdir(exist_ok=True)

    @staticmethod
    def safe_name(filename: str) -> str:
        name = Path(filename.replace("\\", "/")).name
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._")
        if not safe or safe in {".", ".."}:
            raise ValueError("The uploaded file must have a usable filename.")
        return safe[:180]

    def save_upload(self, filename: str, content: bytes) -> Path:
        safe_name = self.safe_name(filename)
        if not safe_name.lower().endswith(".json"):
            raise ValueError("Only SEC JSON files are supported.")
        destination = (self.root / "incoming" / safe_name).resolve()
        if not destination.is_relative_to(self.root):
            raise ValueError("Upload path escapes the selected workspace.")
        destination.write_bytes(content)
        return destination

    def save_json(self, relative_path: str, payload: dict[str, Any]) -> Path:
        destination = (self.root / relative_path).resolve()
        if not destination.is_relative_to(self.root):
            raise ValueError("Output path escapes the selected workspace.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        return destination

    def save_text(self, relative_path: str, content: str) -> Path:
        destination = (self.root / relative_path).resolve()
        if not destination.is_relative_to(self.root):
            raise ValueError("Output path escapes the selected workspace.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return destination

    def discover_sec_payloads(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        submissions_by_cik: dict[str, list[tuple[float, dict[str, Any]]]] = {}
        facts_by_cik: dict[str, list[tuple[float, dict[str, Any]]]] = {}
        for path in self.root.rglob("*.json"):
            resolved = path.resolve()
            if not resolved.is_relative_to(self.root) or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            cik = payload.get("cik")
            if cik is None:
                continue
            cik_value = str(cik).zfill(10)
            if isinstance(payload.get("facts"), dict):
                facts_by_cik.setdefault(cik_value, []).append(
                    (path.stat().st_mtime, payload)
                )
            filings = payload.get("filings")
            if isinstance(filings, dict) and isinstance(
                filings.get("recent"), dict
            ):
                submissions_by_cik.setdefault(cik_value, []).append(
                    (path.stat().st_mtime, payload)
                )
        matching_ciks = sorted(set(submissions_by_cik) & set(facts_by_cik))
        if not matching_ciks:
            raise ValueError(
                "The selected folder must contain both SEC submissions JSON "
                "and CompanyFacts JSON files."
            )
        if len(matching_ciks) > 1:
            raise ValueError(
                "The selected folder contains SEC data for multiple companies. "
                "Choose a folder containing one company's submissions and CompanyFacts."
            )
        cik = matching_ciks[0]
        submissions = max(submissions_by_cik[cik], key=lambda item: item[0])[1]
        companyfacts = max(facts_by_cik[cik], key=lambda item: item[0])[1]
        return submissions, companyfacts

    def list_json_files(self) -> list[str]:
        files: list[str] = []
        for path in sorted(self.root.rglob("*.json")):
            if path.is_file() and path.resolve().is_relative_to(self.root):
                files.append(str(path.relative_to(self.root)))
        return files
