"""Build a versioned source ZIP without local data, secrets, or caches."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "data",
    "dist",
    "incoming",
    "sec_cache",
    "reports",
}
EXCLUDED_FILES = {
    ".env",
    "financials.sqlite",
    "financials.sqlite3",
    "secrets.toml",
}


def version() -> str:
    value = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError(f"VERSION must contain a semantic version, got {value!r}.")
    return value


def is_release_file(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts[:-1]):
        return False
    if path.name in EXCLUDED_FILES or path.suffix.lower() in {".pyc", ".pyo"}:
        return False
    if path.name.startswith(".env."):
        return False
    return path.is_file()


def canonical_readme() -> Path:
    for name in ("README.md", "README-2.md"):
        candidate = ROOT / name
        if candidate.is_file():
            return candidate
    raise RuntimeError("Required release file missing: README.md")


def build_release(output_dir: Path) -> Path:
    release_version = version()
    archive_name = f"SEC-Financial-Health-Analyst-v{release_version}.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / archive_name
    root_folder = archive_name.removesuffix(".zip")
    readme = canonical_readme()
    release_files = sorted(
        (
            path
            for path in ROOT.rglob("*")
            if is_release_file(path) and path.name != "README-2.md"
        ),
        key=lambda item: item.relative_to(ROOT).as_posix().casefold(),
    )
    if readme not in release_files:
        release_files.append(readme)
    required = {"VERSION", "README.md", "RELEASE_README.md", "start_analyst.bat"}
    included = {
        "README.md" if path == readme else path.relative_to(ROOT).as_posix()
        for path in release_files
    }
    missing = required - included
    if missing:
        raise RuntimeError(f"Required release files missing: {', '.join(sorted(missing))}")
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in release_files:
            relative = (
                "README.md"
                if path == readme
                else path.relative_to(ROOT).as_posix()
            )
            archive.write(path, f"{root_folder}/{relative}")
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="Directory for the generated release ZIP (default: project dist/).",
    )
    args = parser.parse_args()
    archive = build_release(args.output_dir.expanduser().resolve())
    print(f"Built {archive} ({archive.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
