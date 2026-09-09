from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pcc.archive_audit import audit_archive
from pcc.control import load_project, run_command, run_gate, status


class PccFoundationTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        control = {
            "schema_version": 1,
            "project": {"id": "fixture", "name": "Fixture"},
            "requirements": [{"tool": sys.executable, "required": True}],
            "commands": [
                {
                    "key": "read.ok",
                    "label": "Read",
                    "program": sys.executable,
                    "args": ["-B", "-c", "print('ok')"],
                    "risk": "read_only",
                    "side_effects": [],
                },
                {
                    "key": "source.write",
                    "label": "Source mutation",
                    "program": sys.executable,
                    "args": ["-B", "-c", "print('mutate')"],
                    "risk": "source_mutation",
                    "side_effects": ["source_files"],
                },
            ],
            "quality_gates": [
                {"key": "safe", "label": "Safe", "stages": ["read.ok"]},
                {"key": "unsafe", "label": "Unsafe", "stages": ["source.write"]},
            ],
        }
        (root / "project.control.json").write_text(json.dumps(control), encoding="utf-8")
        return root

    def test_status_and_exact_read_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = load_project(self.make_project(Path(tmp)))
            self.assertTrue(status(control)["ready"])
            result = run_command(control, "read.ok", stream=False)
            self.assertTrue(result["success"])
            self.assertEqual(result["tail"], ["ok"])

    def test_mutation_requires_explicit_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = load_project(self.make_project(Path(tmp)))
            with self.assertRaises(PermissionError):
                run_command(control, "source.write", stream=False)

    def test_quality_gate_rejects_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control = load_project(self.make_project(Path(tmp)))
            self.assertTrue(run_gate(control, "safe", stream=False)["success"])
            with self.assertRaises(PermissionError):
                run_gate(control, "unsafe", stream=False)

    def test_archive_audit_is_read_only_and_reports_parity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            (root / "sample.txt").write_text("same", encoding="utf-8")
            with zipfile.ZipFile(root / "donor.zip", "w") as archive:
                archive.writestr("sample.txt", "same")
                archive.writestr("only-in-archive.txt", "archive")
            result = audit_archive(root, "donor.zip")
            self.assertEqual(result["equal_file_count"], 1)
            self.assertEqual(result["changed_file_count"], 0)
            self.assertIn("only-in-archive.txt", result["archive_only_paths"])

    def test_archive_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_project(root)
            with self.assertRaises(ValueError):
                audit_archive(root, "../outside.zip")


if __name__ == "__main__":
    unittest.main()
