from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import scan_project


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class TargetCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.project = self.base / "Claude project with spaces"
        self.claude_dir = self.project / ".claude"
        self.claude_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_project_root_and_project_claude_directory_normalize_to_same_root(self) -> None:
        root = scan_project.normalize_target(str(self.project))
        claude = scan_project.normalize_target(str(self.claude_dir))

        self.assertEqual(self.project.resolve(), root.root)
        self.assertEqual(root.root, claude.root)
        self.assertEqual("project-root", root.target_kind)
        self.assertEqual("project-claude-dir", claude.target_kind)

    def test_relative_space_path_and_symlink_are_resolved(self) -> None:
        link = self.base / "linked-project"
        link.symlink_to(self.project, target_is_directory=True)

        with working_directory(self.base):
            relative = scan_project.normalize_target("Claude project with spaces/.claude")
            symlink = scan_project.normalize_target("linked-project")

        self.assertEqual(self.project.resolve(), relative.root)
        self.assertEqual(self.project.resolve(), symlink.root)
        self.assertEqual("project-claude-dir", relative.target_kind)
        self.assertEqual("project-root", symlink.target_kind)

    def test_missing_target_fails_with_code_two_and_never_scans_cwd(self) -> None:
        (self.base / "CLAUDE.md").write_text("must not be scanned", encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()

        with working_directory(self.base), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = scan_project.main(["--target", "missing", "--format", "json"])

        self.assertEqual(2, result)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("does not exist", stderr.getvalue())

    def test_invalid_runtime_root_fails_with_code_two_without_cwd_fallback(self) -> None:
        runtime_file = self.base / "runtime.py"
        runtime_file.write_text("from claude_agent_sdk import query\n", encoding="utf-8")
        for runtime_root in ("", str(self.base / "missing-runtime"), str(runtime_file)):
            with self.subTest(runtime_root=runtime_root):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = scan_project.main(
                        [
                            "--target", str(self.project),
                            "--runtime-root", runtime_root,
                            "--format", "json",
                        ]
                    )

                self.assertEqual(2, result)
                self.assertEqual("", stdout.getvalue())
                self.assertIn("Runtime root", stderr.getvalue())

    def test_regular_file_is_rejected(self) -> None:
        target = self.base / "not-a-directory"
        target.write_text("content", encoding="utf-8")

        with self.assertRaisesRegex(scan_project.TargetValidationError, "must be a directory"):
            scan_project.normalize_target(str(target))

    def test_unreadable_directory_is_rejected(self) -> None:
        target = self.base / "unreadable"
        target.mkdir()
        original_access = scan_project.os.access

        def access(path: os.PathLike[str], mode: int) -> bool:
            if Path(path) == target.resolve():
                return False
            return original_access(path, mode)

        with mock.patch.object(scan_project.os, "access", side_effect=access):
            with self.assertRaisesRegex(scan_project.TargetValidationError, "not readable"):
                scan_project.normalize_target(str(target))

    def test_user_level_claude_directory_is_rejected(self) -> None:
        fake_home = self.base / "home"
        user_claude = fake_home / ".claude"
        user_claude.mkdir(parents=True)

        with mock.patch.object(scan_project.Path, "home", return_value=fake_home):
            with self.assertRaisesRegex(scan_project.TargetValidationError, "User-level"):
                scan_project.normalize_target(str(user_claude))

    def test_user_level_claude_descendant_is_rejected(self) -> None:
        fake_home = self.base / "home"
        user_skill = fake_home / ".claude" / "skills" / "user-skill"
        user_skill.mkdir(parents=True)

        with mock.patch.object(scan_project.Path, "home", return_value=fake_home):
            with self.assertRaisesRegex(scan_project.TargetValidationError, "User-level"):
                scan_project.normalize_target(str(user_skill))

    def test_user_level_claude_symlink_alias_is_rejected_before_resolution(self) -> None:
        fake_home = self.base / "home"
        user_projects = fake_home / ".claude" / "projects"
        user_projects.mkdir(parents=True)
        outside = self.base / "outside-project"
        outside.mkdir()
        alias = user_projects / "alias"
        alias.symlink_to(outside, target_is_directory=True)

        with mock.patch.object(scan_project.Path, "home", return_value=fake_home):
            with self.assertRaisesRegex(scan_project.TargetValidationError, "User-level"):
                scan_project.normalize_target(str(alias))

    def test_project_claude_descendant_is_not_accepted_as_a_project_root(self) -> None:
        rules = self.claude_dir / "rules"
        rules.mkdir()

        with self.assertRaisesRegex(scan_project.TargetValidationError, "project root"):
            scan_project.normalize_target(str(rules))

    def test_host_configuration_subtrees_and_aliases_are_rejected(self) -> None:
        host_target = self.project / ".agents" / "skills" / "host-skill"
        host_target.mkdir(parents=True)
        alias = self.base / "host-alias"
        alias.symlink_to(host_target, target_is_directory=True)

        for target in (host_target, alias):
            with self.subTest(target=target):
                with self.assertRaisesRegex(scan_project.TargetValidationError, "host configuration"):
                    scan_project.normalize_target(str(target))

    def test_empty_null_and_unknown_user_targets_fail_without_fallback(self) -> None:
        for target in ("", "bad\0path", "~agent_config_reviewer_missing_user/project"):
            with self.subTest(target=repr(target)):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result = scan_project.main(["--target", target, "--format", "json"])

                self.assertEqual(2, result)
                self.assertEqual("", stdout.getvalue())
                self.assertTrue(stderr.getvalue().strip())

    def test_symlinked_project_claude_normalizes_to_lexical_parent_and_is_scanned(self) -> None:
        self.claude_dir.rmdir()
        shared_claude = self.base / "shared-claude"
        shared_claude.mkdir()
        (shared_claude / "settings.json").write_text("{not-json", encoding="utf-8")
        self.claude_dir.symlink_to(shared_claude, target_is_directory=True)
        (self.project / "CLAUDE.md").write_text("mcp__demo__tool", encoding="utf-8")

        target = scan_project.normalize_target(str(self.claude_dir))
        result = scan_project.ReviewScanner(
            target.root,
            "auto",
            requested_target=target.requested_target,
            target_kind=target.target_kind,
            claude_dir=target.claude_dir,
        ).run()

        self.assertEqual(self.project.resolve(), target.root)
        self.assertEqual("project-claude-dir", target.target_kind)
        evidence_paths = {
            evidence["path"]
            for finding in result["findings"]
            for evidence in finding["evidence"]
        }
        self.assertIn(".claude/settings.json", evidence_paths)
        self.assertIn("CLAUDE.md", evidence_paths)

    def test_project_claude_must_not_link_to_user_configuration(self) -> None:
        self.claude_dir.rmdir()
        fake_home = self.base / "home"
        user_claude = fake_home / ".claude"
        user_claude.mkdir(parents=True)
        self.claude_dir.symlink_to(user_claude, target_is_directory=True)

        with mock.patch.object(scan_project.Path, "home", return_value=fake_home):
            with self.assertRaisesRegex(scan_project.TargetValidationError, "user-level"):
                scan_project.normalize_target(str(self.project))

    def test_json_and_markdown_echo_requested_and_normalized_targets(self) -> None:
        requested = str(self.claude_dir)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = scan_project.main(["--target", requested, "--format", "json"])

        self.assertEqual(0, result)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(requested, payload["requested_target"])
        self.assertEqual(str(self.project.resolve()), payload["target"])
        self.assertEqual("project-claude-dir", payload["target_kind"])

        markdown = scan_project.markdown(payload)
        self.assertIn(f"Requested target: `{requested}`", markdown)
        self.assertIn(f"Normalized target: `{self.project.resolve()}`", markdown)
        self.assertIn("Target Claude runtime:", markdown)

    def test_markdown_safely_delimits_a_target_containing_backticks(self) -> None:
        payload = {
            "requested_target": "project`\nname/.claude",
            "target": "/tmp/project`\rname",
            "target_kind": "project-claude-dir",
            "runtime": "unknown",
            "claude_version": None,
            "eval_assets": ["test`\n **FORGED-ASSET**"],
            "findings": [
                {
                    "severity": "P2",
                    "id": "SAFE-MARKDOWN",
                    "title": "Static title",
                    "cls": "UNVERIFIED",
                    "confidence": "candidate",
                    "official_source": None,
                    "message": "Static message.",
                    "evidence": [
                        {
                            "path": "bad`\r **FORGED-PATH**.py",
                            "line": 1,
                            "text": "`\r\n\x1b]8;;https://evil.example\x07 **FORGED-TEXT**",
                        }
                    ],
                }
            ],
        }

        report = scan_project.markdown(payload)

        self.assertIn(r"Requested target: ``project`\nname/.claude``", report)
        self.assertIn(r"Normalized target: ``/tmp/project`\rname``", report)
        self.assertIn(r"- ``test`\n **FORGED-ASSET**``", report)
        self.assertIn(r"``bad`\r **FORGED-PATH**.py:1``", report)
        self.assertIn(
            r"`` `\r\n\x1b]8;;https://evil.example\x07 **FORGED-TEXT** ``",
            report,
        )
        self.assertNotIn("\x1b", report)

class ScannerIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def scan(self) -> tuple[scan_project.ReviewScanner, dict[str, object]]:
        scanner = scan_project.ReviewScanner(self.project, "auto")
        return scanner, scanner.run()

    def test_docker_exec_form_claude_entrypoint_is_cli_runtime(self) -> None:
        (self.project / "Dockerfile").write_text(
            'ENTRYPOINT ["claude", "--model", "sonnet", "--print", "hello"]\n',
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("cli", result["runtime"])
        self.assertEqual("Dockerfile", result["runtime_evidence"][0]["path"])

    def test_host_directories_and_markdown_references_do_not_influence_runtime(self) -> None:
        (self.project / "README.md").write_text("claude_agent_sdk ClaudeAgentOptions", encoding="utf-8")
        reference = self.project / "references"
        reference.mkdir()
        (reference / "sdk.md").write_text("@anthropic-ai/claude-agent-sdk", encoding="utf-8")
        for host_dir in (".agents", ".codex"):
            hidden = self.project / host_dir / "skills" / "example"
            hidden.mkdir(parents=True)
            (hidden / "runtime.py").write_text("from claude_agent_sdk import query\n", encoding="utf-8")
            (hidden / "tests").mkdir()
        (self.project / "AGENTS.md").write_text(
            "from claude_agent_sdk import query\n", encoding="utf-8"
        )

        scanner, result = self.scan()

        self.assertEqual("unknown", result["runtime"])
        self.assertEqual([], result["runtime_evidence"])
        self.assertFalse(any(".agents" in scanner.rel(path) or ".codex" in scanner.rel(path) for path in scanner.files))
        self.assertFalse(any(path.name == "AGENTS.md" for path in scanner.files))
        self.assertFalse(any(asset.startswith((".agents", ".codex")) for asset in result["eval_assets"]))

    def test_real_sdk_source_and_dependency_are_detected(self) -> None:
        (self.project / "app.py").write_text(
            "from claude_agent_sdk import ClaudeAgentOptions\n"
            "options = ClaudeAgentOptions(setting_sources=['project'])\n",
            encoding="utf-8",
        )
        (self.project / "requirements.txt").write_text("claude-agent-sdk>=0.1\n", encoding="utf-8")

        _scanner, result = self.scan()

        self.assertEqual("agent-sdk", result["runtime"])
        evidence_paths = {item["path"] for item in result["runtime_evidence"]}
        self.assertEqual({"app.py", "requirements.txt"}, evidence_paths)

    def test_external_runtime_root_is_a_separate_scanning_and_evidence_scope(self) -> None:
        runtime_temp = tempfile.TemporaryDirectory()
        self.addCleanup(runtime_temp.cleanup)
        runtime_root = Path(runtime_temp.name) / "Runtime source with spaces"
        runtime_root.mkdir()
        (self.project / "app.py").write_text(
            "import subprocess\nsubprocess.run(['claude', '--print'])\n",
            encoding="utf-8",
        )
        (self.project / ".claude").mkdir()
        (self.project / ".claude" / "settings.json").write_text("{bad", encoding="utf-8")
        (runtime_root / "app.py").write_text(
            "from claude_agent_sdk import query\n", encoding="utf-8"
        )
        (runtime_root / ".claude").mkdir()
        (runtime_root / ".claude" / "settings.json").write_text("{also-bad", encoding="utf-8")

        result = scan_project.ReviewScanner(
            self.project,
            "auto",
            runtime_root=runtime_root,
            requested_runtime_root=str(runtime_root),
        ).run()

        self.assertEqual("agent-config-reviewer-scan/v2", result["schema_version"])
        self.assertEqual("agent-sdk", result["runtime"])
        self.assertEqual(str(runtime_root.resolve()), result["runtime_root"])
        self.assertTrue(result["runtime_root_explicit"])
        self.assertEqual(["app.py"], result["runtime_files"])
        self.assertIn("app.py", result["target_files"])
        self.assertEqual("runtime", result["runtime_evidence"][0]["scope"])
        json_findings = [item for item in result["findings"] if item["id"] == "O-JSON"]
        self.assertEqual(1, len(json_findings))
        self.assertEqual("target", json_findings[0]["evidence"][0]["scope"])
        self.assertNotIn("also-bad", json.dumps(result))

    def test_comments_strings_and_templates_do_not_trigger_runtime_detection(self) -> None:
        (self.project / "app.py").write_text(
            "# from claude_agent_sdk import query\n"
            "EXAMPLE = 'ClaudeAgentOptions()'\n",
            encoding="utf-8",
        )
        (self.project / "requirements.txt").write_text(
            "# claude-agent-sdk is intentionally not installed\n", encoding="utf-8"
        )
        (self.project / "launch.sh").write_text("# claude -p ignored\n", encoding="utf-8")
        (self.project / "example.js").write_text(
            "const docs = `import '@anthropic-ai/claude-agent-sdk'`;\n",
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("unknown", result["runtime"])
        self.assertEqual([], result["runtime_evidence"])

    def test_python_future_syntax_falls_back_to_tokenized_sdk_import(self) -> None:
        (self.project / "future.py").write_text(
            "from claude_agent_sdk import query\n"
            "match value:\n"
            "    case 1:\n"
            "        pass\n",
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("agent-sdk", result["runtime"])
        self.assertEqual("future.py", result["runtime_evidence"][0]["path"])

    def test_javascript_sdk_import_forms_are_detected_without_template_false_positive(self) -> None:
        sources = {
            "bare.js": "import '@anthropic-ai/claude-agent-sdk';\n",
            "static.ts": "import { query }\nfrom '@anthropic-ai/claude-agent-sdk';\n",
            "common.cjs": "const sdk = require('@anthropic-ai/claude-agent-sdk');\n",
            "dynamic.mjs": "const sdk = await import('@anthropic-ai/claude-agent-sdk');\n",
            "template.js": "const docs = `import '@anthropic-ai/claude-agent-sdk'`;\n",
        }
        for name, content in sources.items():
            (self.project / name).write_text(content, encoding="utf-8")

        _scanner, result = self.scan()

        self.assertEqual("agent-sdk", result["runtime"])
        evidence_paths = {item["path"] for item in result["runtime_evidence"]}
        self.assertEqual({"bare.js", "static.ts", "common.cjs", "dynamic.mjs"}, evidence_paths)

    def test_python_and_javascript_process_calls_detect_cli_runtime(self) -> None:
        (self.project / "runner.py").write_text(
            "import subprocess\nsubprocess.run(['claude', '-p', 'hello'])\n",
            encoding="utf-8",
        )
        (self.project / "runner.js").write_text(
            "import { spawn } from 'node:child_process';\n"
            "spawn('/usr/bin/claude', ['--verbose', '--print', 'hello']);\n",
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("cli", result["runtime"])
        evidence_paths = {item["path"] for item in result["runtime_evidence"]}
        self.assertEqual({"runner.py", "runner.js"}, evidence_paths)

    def test_javascript_child_process_calls_follow_imported_bindings(self) -> None:
        sources = {
            "named.js": (
                "import { spawn as launch } from 'node:child_process';\n"
                "launch('claude', ['--verbose', '--print']);\n"
            ),
            "destructured.cjs": (
                "const { spawn: launch } = require('child_process');\n"
                "launch('/opt/bin/claude', ['--agent', 'reviewer']);\n"
            ),
            "namespace.mts": (
                "import * as cp from 'node:child_process';\n"
                "cp.spawn('claude', ['--worktree']);\n"
            ),
            "module.cts": (
                "const cp = require('child_process');\n"
                "cp.execFile('claude', ['--print']);\n"
            ),
            "local.js": (
                "import * as cp from 'node:child_process';\n"
                "function spawn(command, args) { return [command, args]; }\n"
                "spawn('claude', ['--print']);\n"
            ),
        }
        for name, content in sources.items():
            (self.project / name).write_text(content, encoding="utf-8")

        _scanner, result = self.scan()

        self.assertEqual("cli", result["runtime"])
        evidence_paths = {item["path"] for item in result["runtime_evidence"]}
        self.assertEqual(
            {"named.js", "destructured.cjs", "namespace.mts", "module.cts"},
            evidence_paths,
        )

    def test_javascript_local_const_shadows_imported_process_binding(self) -> None:
        (self.project / "shadowed.js").write_text(
            "import { spawn } from 'node:child_process';\n"
            "function run() {\n"
            "  const spawn = localSpawn;\n"
            "  spawn('claude', ['--print']);\n"
            "}\n",
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("unknown", result["runtime"])
        self.assertEqual([], result["runtime_evidence"])

    def test_javascript_function_parameter_shadows_imported_process_alias(self) -> None:
        (self.project / "parameter.js").write_text(
            "import { spawn as launch } from 'node:child_process';\n"
            "function run(launch) {\n"
            "  launch('claude', ['--print']);\n"
            "}\n",
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("unknown", result["runtime"])
        self.assertEqual([], result["runtime_evidence"])

    def test_javascript_secondary_alias_from_direct_binding_is_detected(self) -> None:
        (self.project / "direct-alias.js").write_text(
            "import { spawn } from 'node:child_process';\n"
            "const launch = spawn;\n"
            "launch('claude', ['--print']);\n",
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("cli", result["runtime"])
        self.assertEqual("direct-alias.js", result["runtime_evidence"][0]["path"])

    def test_javascript_secondary_alias_from_namespace_binding_is_detected(self) -> None:
        (self.project / "namespace-alias.js").write_text(
            "import * as cp from 'node:child_process';\n"
            "const launch = cp.spawn;\n"
            "launch('claude', ['--print']);\n",
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("cli", result["runtime"])
        self.assertEqual("namespace-alias.js", result["runtime_evidence"][0]["path"])

    def test_javascript_secondary_alias_from_require_property_is_detected(self) -> None:
        (self.project / "require-alias.cjs").write_text(
            "const launch = require('node:child_process').spawn;\n"
            "launch('claude', ['--print']);\n",
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("cli", result["runtime"])
        self.assertEqual("require-alias.cjs", result["runtime_evidence"][0]["path"])

    def test_cli_detection_requires_claude_as_argv_zero(self) -> None:
        (self.project / "negative.sh").write_text("echo claude -p\n", encoding="utf-8")
        (self.project / "negative.py").write_text(
            "import subprocess\nsubprocess.run(['echo', 'claude', '--print'])\n",
            encoding="utf-8",
        )
        (self.project / "negative.js").write_text(
            "import { spawn } from 'node:child_process';\n"
            "spawn('echo', ['claude', '--agent']);\n",
            encoding="utf-8",
        )
        (self.project / "package.json").write_text(
            json.dumps({"scripts": {"docs": "echo claude --print"}}),
            encoding="utf-8",
        )
        (self.project / "positive.sh").write_text(
            "/usr/local/bin/claude --verbose --print hello\n", encoding="utf-8"
        )

        _scanner, result = self.scan()

        self.assertEqual("cli", result["runtime"])
        self.assertEqual(
            {"positive.sh"},
            {item["path"] for item in result["runtime_evidence"]},
        )

    def test_local_run_and_spawn_helpers_do_not_imply_cli_runtime(self) -> None:
        (self.project / "local.py").write_text(
            "def run(args):\n    return args\nrun(['claude', '-p'])\n",
            encoding="utf-8",
        )
        (self.project / "local.js").write_text(
            "function spawn(cmd, args) { return [cmd, args]; }\n"
            "spawn('claude', ['--print']);\n",
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("unknown", result["runtime"])

    def test_pep621_single_line_dependency_is_detected(self) -> None:
        (self.project / "pyproject.toml").write_text(
            "[project]\n"
            'description = "claude-agent-sdk is mentioned in prose"\n'
            'dependencies = ["claude-agent-sdk>=0.1"]\n',
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("agent-sdk", result["runtime"])
        self.assertEqual("pyproject.toml", result["runtime_evidence"][0]["path"])
        self.assertIn("dependencies", result["runtime_evidence"][0]["text"])

    def test_poetry_dependency_is_detected_independently(self) -> None:
        (self.project / "pyproject.toml").write_text(
            "[tool.poetry.dependencies]\n"
            'python = "^3.11"\n'
            'claude-agent-sdk = "^0.1"\n',
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("agent-sdk", result["runtime"])
        self.assertIn("claude-agent-sdk", result["runtime_evidence"][0]["text"])

    def test_pyproject_description_is_not_dependency_evidence(self) -> None:
        (self.project / "pyproject.toml").write_text(
            "[project]\n"
            'name = "example"\n'
            'description = "claude-agent-sdk"\n',
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("unknown", result["runtime"])
        self.assertEqual([], result["runtime_evidence"])

    def test_mts_and_cts_sdk_imports_are_runtime_sources(self) -> None:
        (self.project / "entry.mts").write_text(
            "import '@anthropic-ai/claude-agent-sdk';\n", encoding="utf-8"
        )
        (self.project / "worker.cts").write_text(
            "const sdk = require('@anthropic-ai/claude-agent-sdk');\n", encoding="utf-8"
        )

        _scanner, result = self.scan()

        self.assertEqual("agent-sdk", result["runtime"])
        self.assertEqual(
            {"entry.mts", "worker.cts"},
            {item["path"] for item in result["runtime_evidence"]},
        )

    def test_versioned_pnpm_lock_key_is_detected(self) -> None:
        (self.project / "pnpm-lock.yaml").write_text(
            "packages:\n"
            "  '@anthropic-ai/claude-agent-sdk@0.2.0':\n"
            "    resolution: {integrity: sha512-example}\n",
            encoding="utf-8",
        )

        _scanner, result = self.scan()

        self.assertEqual("agent-sdk", result["runtime"])
        self.assertEqual("pnpm-lock.yaml", result["runtime_evidence"][0]["path"])

    def test_root_level_eval_files_are_assets_not_runtime_sources_by_default(self) -> None:
        test_file = self.project / "test_runtime.py"
        test_file.write_text("from claude_agent_sdk import query\n", encoding="utf-8")

        scanner, result = self.scan()
        included = scan_project.ReviewScanner(
            self.project, "auto", include_eval_targets=True
        ).run()

        self.assertEqual("unknown", result["runtime"])
        self.assertNotIn(test_file, scanner.files)
        self.assertIn("test_runtime.py", result["eval_assets"])
        self.assertEqual("agent-sdk", included["runtime"])

    def test_noxfile_is_an_eval_asset_not_a_runtime_source_by_default(self) -> None:
        noxfile = self.project / "noxfile.py"
        noxfile.write_text("from claude_agent_sdk import query\n", encoding="utf-8")

        scanner, result = self.scan()

        self.assertEqual("unknown", result["runtime"])
        self.assertNotIn(noxfile, scanner.files)
        self.assertIn("noxfile.py", result["eval_assets"])

    def test_skill_named_test_is_not_pruned_as_an_eval_directory(self) -> None:
        skill = self.project / ".claude" / "skills" / "test" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: test-skill\n---\n", encoding="utf-8")

        scanner, result = self.scan()

        self.assertIn(skill, scanner.files)
        evidence_paths = {
            item["path"]
            for finding in result["findings"]
            if finding["id"] == "A-SKILL-DESC"
            for item in finding["evidence"]
        }
        self.assertEqual({".claude/skills/test/SKILL.md"}, evidence_paths)

    def test_static_scanner_does_not_execute_a_claude_binary_from_path(self) -> None:
        binary = self.project / "claude"
        marker = self.project / "executed"
        binary.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
        binary.chmod(0o755)

        with mock.patch.dict(os.environ, {"PATH": str(self.project)}):
            _scanner, result = self.scan()

        self.assertIsNone(result["claude_version"])
        self.assertFalse(marker.exists())


class ScannerSymlinkBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.project = self.base / "project"
        self.claude_dir = self.project / ".claude"
        self.claude_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_configuration_file_symlinks_are_reported_without_reading_targets(self) -> None:
        external_instruction = self.base / "external-instruction.md"
        external_instruction.write_text("mcp__secret__exfiltrate", encoding="utf-8")
        external_settings = self.base / "external-settings.json"
        external_settings.write_text("{not-json", encoding="utf-8")
        (self.project / "CLAUDE.md").symlink_to(external_instruction)
        (self.claude_dir / "settings.json").symlink_to(external_settings)

        result = scan_project.ReviewScanner(self.project, "auto").run()

        symlink_findings = [
            finding for finding in result["findings"]
            if finding["id"] == "A-CONFIG-SYMLINK"
        ]
        self.assertEqual(2, len(symlink_findings))
        evidence_paths = {
            evidence["path"]
            for finding in symlink_findings
            for evidence in finding["evidence"]
        }
        self.assertEqual({"CLAUDE.md", ".claude/settings.json"}, evidence_paths)
        serialized = json.dumps(result)
        self.assertNotIn("mcp__secret__exfiltrate", serialized)
        self.assertNotIn("not-json", serialized)

    def test_nested_configuration_directory_symlink_is_reported_without_reading_it(self) -> None:
        external_rules = self.base / "external-rules"
        external_rules.mkdir()
        (external_rules / "security.md").write_text(
            "mcp__secret__exfiltrate", encoding="utf-8"
        )
        (self.claude_dir / "rules").symlink_to(
            external_rules, target_is_directory=True
        )

        result = scan_project.ReviewScanner(self.project, "auto").run()

        symlink_findings = [
            finding for finding in result["findings"]
            if finding["id"] == "A-CONFIG-SYMLINK"
        ]
        self.assertEqual(1, len(symlink_findings))
        self.assertEqual(
            ".claude/rules", symlink_findings[0]["evidence"][0]["path"]
        )
        self.assertNotIn("mcp__secret__exfiltrate", json.dumps(result))

    def test_referenced_hook_symlink_cannot_escape_the_authorized_roots(self) -> None:
        hooks = self.project / "hooks"
        hooks.mkdir()
        external = self.base / "outside.py"
        external.write_text("mcp__secret__exfiltrate", encoding="utf-8")
        (hooks / "guard.py").symlink_to(external)
        (self.claude_dir / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "python",
                                        "args": ["./hooks/guard.py"],
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        result = scan_project.ReviewScanner(self.project, "auto").run()

        self.assertNotIn("mcp__secret__exfiltrate", json.dumps(result))

    def test_hook_inside_linked_project_claude_directory_is_scanned_logically(self) -> None:
        self.claude_dir.rmdir()
        shared = self.base / "shared-claude"
        hook = shared / "hooks" / "guard.py"
        hook.parent.mkdir(parents=True)
        hook.write_text("mcp__linked__guard", encoding="utf-8")
        (shared / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "python",
                                        "args": [
                                            "${CLAUDE_PROJECT_DIR}/.claude/hooks/guard.py"
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        self.claude_dir.symlink_to(shared, target_is_directory=True)

        target = scan_project.normalize_target(str(self.project))
        result = scan_project.ReviewScanner(
            target.root,
            "auto",
            claude_dir=target.claude_dir,
        ).run()

        evidence = [
            item
            for finding in result["findings"]
            if finding["id"] == "P-HOOK-PHYS"
            for item in finding["evidence"]
        ]
        self.assertEqual(".claude/hooks/guard.py", evidence[0]["path"])

    def test_shell_form_hook_command_is_tokenized_and_scanned(self) -> None:
        hook = self.project / "hooks" / "guard.py"
        hook.parent.mkdir()
        hook.write_text(
            "try:\n"
            "    check()\n"
            "except Exception:\n"
            "    return True\n",
            encoding="utf-8",
        )
        (self.claude_dir / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": 'python "${CLAUDE_PROJECT_DIR}/hooks/guard.py"',
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        result = scan_project.ReviewScanner(self.project, "auto").run()

        fail_open = [finding for finding in result["findings"] if finding["id"] == "R-HOOK-FAILOPEN"]
        self.assertEqual(1, len(fail_open))
        self.assertEqual("hooks/guard.py", fail_open[0]["evidence"][0]["path"])

    def test_linked_claude_scans_only_config_shapes_and_referenced_hooks(self) -> None:
        self.claude_dir.rmdir()
        shared = self.base / "shared-claude"
        hook = shared / "hooks" / "guard.py"
        hook.parent.mkdir(parents=True)
        hook.write_text(
            "try:\n"
            "    check()\n"
            "except Exception:\n"
            "    return True\n",
            encoding="utf-8",
        )
        sensitive = shared / "sensitive" / "runtime.py"
        sensitive.parent.mkdir()
        sensitive.write_text(
            "from claude_agent_sdk import query\nmcp__secret__exfiltrate\n",
            encoding="utf-8",
        )
        (shared / "runtime.py").write_text(
            "from claude_agent_sdk import query\n", encoding="utf-8"
        )
        (shared / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": 'python "${CLAUDE_PROJECT_DIR}/.claude/hooks/guard.py"',
                                    }
                                ],
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        self.claude_dir.symlink_to(shared, target_is_directory=True)

        target = scan_project.normalize_target(str(self.project))
        scanner = scan_project.ReviewScanner(
            target.root, "auto", claude_dir=target.claude_dir
        )
        result = scanner.run()

        self.assertEqual("unknown", result["runtime"])
        self.assertFalse(any(path.name == "runtime.py" for path in scanner.files))
        self.assertNotIn("mcp__secret__exfiltrate", json.dumps(result))
        fail_open = [finding for finding in result["findings"] if finding["id"] == "R-HOOK-FAILOPEN"]
        self.assertEqual(1, len(fail_open))
        self.assertEqual(".claude/hooks/guard.py", fail_open[0]["evidence"][0]["path"])


class HookReferenceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.project = self.base / "Claude project"
        self.claude_dir = self.project / ".claude"
        self.claude_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_hooks(self, event: str, handlers: list[dict[str, object]]) -> None:
        (self.claude_dir / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        event: [
                            {
                                "matcher": "Bash",
                                "hooks": handlers,
                            }
                        ]
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def test_shell_and_exec_forms_resolve_space_paths_and_preserve_occurrences(self) -> None:
        hook = self.project / "hooks with spaces" / "guard.py"
        hook.parent.mkdir()
        hook.write_text(
            "try:\n    check()\nexcept Exception:\n    return True\n",
            encoding="utf-8",
        )
        relative = "hooks with spaces/guard.py"
        self.write_hooks(
            "PreToolUse",
            [
                {"type": "command", "command": f'python "${{CLAUDE_PROJECT_DIR}}/{relative}"'},
                {"type": "command", "command": f'python "$CLAUDE_PROJECT_DIR/{relative}"'},
                {"type": "command", "command": f'pwsh -File "$env:CLAUDE_PROJECT_DIR/{relative}"'},
                {
                    "type": "command",
                    "command": "python",
                    "args": [f"${{CLAUDE_PROJECT_DIR}}/{relative}"],
                },
                {
                    "type": "command",
                    "command": f"${{CLAUDE_PROJECT_DIR}}/{relative}",
                    "args": [],
                },
                {
                    "type": "command",
                    "command": "python",
                    "args": [f"$CLAUDE_PROJECT_DIR/{relative}"],
                },
            ],
        )

        first = scan_project.ReviewScanner(self.project, "auto").run()
        second = scan_project.ReviewScanner(self.project, "auto").run()

        self.assertEqual(
            ["RESOLVED", "RESOLVED", "RESOLVED", "RESOLVED", "RESOLVED", "DYNAMIC"],
            [item["status"] for item in first["hook_references"]],
        )
        self.assertEqual(6, len(first["hook_references"]))
        self.assertTrue(all(item["json_pointer"].startswith("/hooks/PreToolUse/") for item in first["hook_references"]))
        self.assertEqual(
            1,
            sum(item["id"] == "R-HOOK-FAILOPEN" for item in first["findings"]),
        )
        unresolved = [item for item in first["candidates"] if item["rule_id"] == "A-HOOK-REFERENCE"]
        self.assertEqual(1, len(unresolved))
        self.assertEqual("P1", unresolved[0]["severity"])
        self.assertEqual("hook-reference-resolution", unresolved[0]["root_cause_hint"])
        self.assertEqual("target", unresolved[0]["evidence"][0]["scope"])
        self.assertEqual(first["candidates"], first["findings"])
        self.assertEqual(
            [item["candidate_id"] for item in first["candidates"]],
            [item["candidate_id"] for item in second["candidates"]],
        )

    def test_unquoted_shell_project_variable_is_not_resolved_through_space_path(self) -> None:
        hook = self.project / "hooks" / "guard"
        hook.parent.mkdir()
        hook.write_text("exit 0\n", encoding="utf-8")

        self.write_hooks(
            "PreToolUse",
            [
                {"type": "command", "command": "sh $CLAUDE_PROJECT_DIR/hooks/guard"},
                {"type": "command", "command": "sh ${CLAUDE_PROJECT_DIR}/hooks/guard"},
                {"type": "command", "command": 'sh "$CLAUDE_PROJECT_DIR/hooks/guard"'},
                {
                    "type": "command",
                    "command": 'sh "$CLAUDE_PROJECT_DIR/hooks/guard" ${CLAUDE_PROJECT_DIR}/hooks/guard',
                },
            ],
        )

        result = scan_project.ReviewScanner(self.project, "auto").run()
        self.assertEqual(
            ["MALFORMED", "MALFORMED", "RESOLVED", "RESOLVED", "MALFORMED"],
            [item["status"] for item in result["hook_references"]],
        )

    def test_unresolved_statuses_are_explicit_and_never_read_outside_roots(self) -> None:
        hooks = self.project / "hooks"
        hooks.mkdir()
        unreadable = hooks / "unreadable.py"
        unreadable.write_text("print('not scanned')\n", encoding="utf-8")
        outside = self.base / "outside.py"
        outside.write_text("mcp__secret__exfiltrate\n", encoding="utf-8")
        (hooks / "outside.py").symlink_to(outside)
        self.write_hooks(
            "PostToolUse",
            [
                {"type": "command", "command": 'python "${CLAUDE_PROJECT_DIR}/hooks/missing.py"'},
                {"type": "command", "command": 'python "${CLAUDE_PROJECT_DIR}/hooks/outside.py"'},
                {"type": "command", "command": 'python "${CLAUDE_PROJECT_DIR}/hooks/bad.py'},
                {"type": "command", "command": 'python "$HOOK_ROOT/guard.py"'},
                {
                    "type": "command",
                    "command": "python",
                    "args": ["${CLAUDE_PROJECT_DIR}/hooks/unreadable.py"],
                },
            ],
        )
        original_access = scan_project.os.access

        def access(path: os.PathLike[str], mode: int) -> bool:
            if Path(path) == unreadable.resolve() and mode == os.R_OK:
                return False
            return original_access(path, mode)

        with mock.patch.object(scan_project.os, "access", side_effect=access):
            result = scan_project.ReviewScanner(self.project, "auto").run()

        self.assertEqual(
            {"MISSING", "OUTSIDE_ROOT", "MALFORMED", "DYNAMIC", "READ_FAILED"},
            {item["status"] for item in result["hook_references"]},
        )
        unresolved = [item for item in result["candidates"] if item["rule_id"] == "A-HOOK-REFERENCE"]
        self.assertEqual(5, len(unresolved))
        self.assertTrue(all(item["severity"] == "P2" for item in unresolved))
        self.assertTrue(all(item["candidate_id"] for item in result["hook_references"]))
        serialized = json.dumps(result)
        self.assertNotIn("mcp__secret__exfiltrate", serialized)
        self.assertNotIn("R-HOOK-UNRESOLVED", serialized)

    def test_sensitive_evidence_values_are_redacted(self) -> None:
        (self.project / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "example": {
                            "headers": {"Authorization": "Bearer top-secret-value"}
                        }
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        result = scan_project.ReviewScanner(self.project, "auto").run()
        credential = [item for item in result["findings"] if item["id"] == "R-MCP-CREDENTIAL"]

        self.assertEqual(1, len(credential))
        self.assertIn("[REDACTED]", credential[0]["evidence"][0]["text"])
        self.assertNotIn("top-secret-value", json.dumps(result))

        samples = (
            '"Authorization": "Token plain-secret-value"',
            '"Authorization": "Bearer bearer-secret"',
            '"api_key": "sk-live-secret"',
            "token=plain-token",
            'password: "secret with spaces"',
        )
        for sample in samples:
            with self.subTest(sample=sample):
                redacted = scan_project.ReviewScanner.redact_sensitive_text(sample)
                self.assertIn("[REDACTED]", redacted)
                self.assertNotRegex(
                    redacted,
                    r"plain-secret|bearer-secret|sk-live|plain-token|secret with",
                )


class DualHostPackageContractTests(unittest.TestCase):
    def test_readmes_document_both_host_install_scopes_and_invocations(self) -> None:
        expected = (
            "<project-root>/.claude/skills/agent-config-reviewer/",
            "~/.claude/skills/agent-config-reviewer/",
            "<project-root>/.agents/skills/agent-config-reviewer/",
            "$HOME/.agents/skills/agent-config-reviewer/",
            "/agent-config-reviewer",
            "$agent-config-reviewer",
        )
        for name in ("README.md", "README_en.md"):
            with self.subTest(readme=name):
                text = (REPOSITORY_ROOT / name).read_text(encoding="utf-8")
                for marker in expected:
                    self.assertIn(marker, text)

    def test_skill_frontmatter_uses_portable_fields(self) -> None:
        text = (REPOSITORY_ROOT / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]

        self.assertIn("name:", frontmatter)
        self.assertIn("description:", frontmatter)
        self.assertNotIn("argument-hint:", frontmatter)

    def test_codex_metadata_invokes_the_skill_explicitly(self) -> None:
        text = (REPOSITORY_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

        self.assertIn("default_prompt:", text)
        self.assertIn("$agent-config-reviewer", text)


if __name__ == "__main__":
    unittest.main()
