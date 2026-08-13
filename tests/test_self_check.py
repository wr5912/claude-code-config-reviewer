from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import self_check


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class OpenAIMetadataValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "openai.yaml"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def validate(self, content: str) -> None:
        self.path.write_text(content, encoding="utf-8")
        self_check.validate_openai_metadata(self.path, "agent-config-reviewer")

    def test_generated_metadata_is_valid(self) -> None:
        self.validate(
            "interface:\n"
            '  display_name: "Agent Config Reviewer"\n'
            '  short_description: "Review Claude Code configuration safely"\n'
            '  default_prompt: "Use $agent-config-reviewer to review the target."\n'
        )

    def test_ambiguous_or_malformed_plain_scalars_are_rejected(self) -> None:
        invalid_values = ("foo: bar", "[unterminated", "abc # comment")
        for value in invalid_values:
            with self.subTest(value=value):
                content = (
                    "interface:\n"
                    f"  display_name: {value}\n"
                    '  short_description: "Review Claude Code configuration safely"\n'
                    '  default_prompt: "Use $agent-config-reviewer to review the target."\n'
                )
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        self.validate(content)

    def test_default_prompt_rejects_a_longer_skill_name_prefix(self) -> None:
        content = (
            "interface:\n"
            '  display_name: "Agent Config Reviewer"\n'
            '  short_description: "Review Claude Code configuration safely"\n'
            '  default_prompt: "Use $agent-config-reviewer-malicious instead."\n'
        )

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.validate(content)


class SkillFrontmatterValidationTests(unittest.TestCase):
    def test_package_skill_frontmatter_is_valid(self) -> None:
        text = (REPOSITORY_ROOT / "SKILL.md").read_text(encoding="utf-8")

        name, _body, _line_count = self_check.validate_skill(text)

        self.assertEqual("agent-config-reviewer", name)

    def test_ambiguous_or_malformed_plain_scalars_are_rejected(self) -> None:
        invalid_values = ("foo: bar", "[unterminated", "abc # comment")
        for value in invalid_values:
            with self.subTest(value=value):
                content = (
                    "---\n"
                    'name: "agent-config-reviewer"\n'
                    f"description: {value}\n"
                    "---\n"
                    "# Body\n"
                )
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        self_check.validate_skill(content)


class PackageSelfCheckTests(unittest.TestCase):
    def test_hidden_payload_directory_is_not_implicitly_ignored(self) -> None:
        self.assertFalse(
            self_check.is_ignored_payload(Path("references/.payload/hidden.md"))
        )

    def test_repository_layout_rejects_undeclared_top_level_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "undeclared.py").write_text("pass\n", encoding="utf-8")

            with mock.patch.object(self_check, "ROOT", root):
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        self_check.validate_repository_layout()

    def test_payload_enumeration_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "package"
            references = root / "references"
            references.mkdir(parents=True)
            external = base / "external.md"
            external.write_text("outside\n", encoding="utf-8")
            (references / "linked.md").symlink_to(external)

            with mock.patch.object(self_check, "ROOT", root):
                with mock.patch.object(
                    self_check, "EXPECTED_PACKAGE_ROOTS", ["references"]
                ):
                    with mock.patch.object(
                        self_check, "EXPECTED_TOP_LEVEL_FILES", []
                    ):
                        with contextlib.redirect_stdout(io.StringIO()):
                            with self.assertRaises(SystemExit):
                                self_check.expected_payload_files()

    def test_payload_enumeration_rejects_top_level_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "package"
            root.mkdir()
            external = base / "README.md"
            external.write_text("outside\n", encoding="utf-8")
            (root / "README.md").symlink_to(external)

            with mock.patch.object(self_check, "ROOT", root):
                with mock.patch.object(self_check, "EXPECTED_PACKAGE_ROOTS", []):
                    with mock.patch.object(
                        self_check, "EXPECTED_TOP_LEVEL_FILES", ["README.md"]
                    ):
                        with contextlib.redirect_stdout(io.StringIO()):
                            with self.assertRaises(SystemExit):
                                self_check.expected_payload_files()

    def test_direct_resource_reference_cannot_escape_the_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "package"
            (root / "references").mkdir(parents=True)
            (root / "references" / "inside.md").write_text(
                "inside\n", encoding="utf-8"
            )

            with mock.patch.object(self_check, "ROOT", root):
                invalid_references = (
                    "references/../../outside.md",
                    "../references/inside.md",
                    "/tmp/references/inside.md",
                    "https://evil.example/references/inside.md",
                )
                for reference in invalid_references:
                    with self.subTest(reference=reference):
                        with contextlib.redirect_stdout(io.StringIO()):
                            with self.assertRaises(SystemExit):
                                self_check.validate_direct_references(
                                    f"Read {reference} before reviewing."
                                )

    def test_skill_dir_placeholder_is_a_valid_package_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "scripts" / "scan_project.py"
            script.parent.mkdir()
            script.write_text("pass\n", encoding="utf-8")

            with mock.patch.object(self_check, "ROOT", root):
                count = self_check.validate_direct_references(
                    "Run <skill-dir>/scripts/scan_project.py once."
                )

            self.assertEqual(1, count)

    def test_manifest_identity_matches_skill_and_release_contract(self) -> None:
        manifest = json.loads(
            (REPOSITORY_ROOT / "PACKAGE-MANIFEST.json").read_text(encoding="utf-8")
        )
        skill_name = (
            (REPOSITORY_ROOT / "SKILL.md")
            .read_text(encoding="utf-8")
            .split("name:", 1)[1]
            .splitlines()[0]
            .strip()
            .strip('"')
        )

        self.assertEqual(skill_name, manifest["package"])
        self.assertEqual(self_check.EXPECTED_PACKAGE_VERSION, manifest["version"])
        self.assertEqual(
            self_check.EXPECTED_BASELINE_DATE,
            manifest["official_baseline_checked"],
        )

    def test_repository_package_passes_self_check(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/self_check.py"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
