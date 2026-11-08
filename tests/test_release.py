from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts.build_release import ROOT, build_release, version


class ReleasePackageTests(unittest.TestCase):
    def test_release_version_is_semantic_and_matches_zip_and_guides(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = build_release(Path(temp_dir))
            self.assertEqual(
                archive_path.name,
                f"SEC-Financial-Health-Analyst-v{version()}.zip",
            )
            with ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                root = archive_path.stem
                self.assertIn(f"{root}/VERSION", names)
                self.assertIn(f"{root}/README.md", names)
                self.assertIn(f"{root}/RELEASE_README.md", names)
                self.assertIn(f"{root}/start_analyst.bat", names)
                self.assertTrue(
                    (archive.read(f"{root}/VERSION").decode("utf-8").strip())
                    == version()
                )
                project_readme = archive.read(f"{root}/README.md")
                release_readme = archive.read(f"{root}/RELEASE_README.md")
                self.assertNotEqual(project_readme, release_readme)
                self.assertIn(
                    f"v{version()}".encode("utf-8"), project_readme
                )
                self.assertIn(
                    f"v{version()}".encode("utf-8"), release_readme
                )
                self.assertNotIn("/data/", "\n".join(names).replace("\\", "/"))
                self.assertFalse(any("__pycache__" in name for name in names))
                self.assertFalse(any(".pyc" in name for name in names))

    def test_release_source_contains_no_local_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = build_release(Path(temp_dir))
            with ZipFile(archive_path) as archive:
                forbidden_names = {
                    "financials.sqlite",
                    "financials.sqlite3",
                    "secrets.toml",
                    ".env",
                }
                for name in archive.namelist():
                    if Path(name).name in forbidden_names:
                        self.fail(f"Local-only file is in the release: {name}")


if __name__ == "__main__":
    unittest.main()
