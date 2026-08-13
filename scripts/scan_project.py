#!/usr/bin/env python3
"""Portable static candidate scanner for Claude Code / Claude Agent SDK projects.

Design goals:
- target defaults to current project/workspace;
- no organization-specific paths or product names;
- no execution of project hooks/tests/application code;
- separate official semantics from security/portability heuristics;
- tests/evals are not review targets by default, but candidate harnesses are discovered.

The scanner is intentionally conservative. It is not the compliance authority; every
OFFICIAL-* candidate must be checked against current official Claude documentation.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import shlex
import sys
import tokenize
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 fallback remains conservative.
    tomllib = None  # type: ignore

OFFICIAL = {
    "settings": "https://code.claude.com/docs/en/settings",
    "sdk_features": "https://code.claude.com/docs/en/agent-sdk/claude-code-features",
    "sdk_skills": "https://code.claude.com/docs/en/agent-sdk/skills",
    "sdk_permissions": "https://code.claude.com/docs/en/agent-sdk/permissions",
    "skills": "https://code.claude.com/docs/en/slash-commands",
    "subagents": "https://code.claude.com/docs/en/sub-agents",
    "permissions": "https://code.claude.com/docs/en/permissions",
    "hooks": "https://code.claude.com/docs/en/hooks",
    "mcp": "https://code.claude.com/docs/en/mcp",
    "memory": "https://code.claude.com/docs/en/memory",
    "commands_sdk": "https://code.claude.com/docs/en/agent-sdk/slash-commands",
    "output_styles": "https://code.claude.com/docs/en/output-styles",
    "worktrees": "https://code.claude.com/docs/en/worktrees",
    "skill_best_practices": "https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices",
}

BUILD_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", "target",
    ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".next", ".turbo", "coverage", ".coverage", ".idea", ".vscode",
}
HOST_CONFIG_DIRS = {".agents", ".codex"}
EVAL_DIR_NAMES = {
    "test", "tests", "__tests__", "spec", "specs", "eval", "evals", "evaluation",
    "evaluations", "benchmark", "benchmarks",
}
TEXT_EXTENSIONS = {
    ".md", ".json", ".jsonc", ".yaml", ".yml", ".py", ".js", ".mjs", ".cjs",
    ".ts", ".tsx", ".jsx", ".mts", ".cts", ".sh", ".ps1", ".toml", ".ini", ".cfg", ".txt", ".lock",
}
JAVASCRIPT_SOURCE_EXTENSIONS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".mts", ".cts"}
RUNTIME_SOURCE_EXTENSIONS = {".py", *JAVASCRIPT_SOURCE_EXTENSIONS}
RUNTIME_SCRIPT_EXTENSIONS = {".sh", ".ps1"}
DEPENDENCY_FILE_NAMES = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "poetry.lock", "uv.lock", "Pipfile", "Pipfile.lock",
}
RUNTIME_ENTRY_FILE_NAMES = {"Makefile", "Dockerfile", "Procfile", "Taskfile.yml", "justfile"}
MCP_NAME = re.compile(r"\bmcp__[A-Za-z0-9._-]+__[A-Za-z0-9._*:-]+\b")
SINGLE_SLASH_HOST_PATH = re.compile(r"\b(Read|Edit|Write|Glob|NotebookEdit|MultiEdit)\(/(?:etc|home|Users|var|tmp|opt|srv|data|mnt|root|c/)([^)]*)\)")
PATH_QUALIFIED_IGNORED_TOOL = re.compile(r"\b(Write|Glob|NotebookEdit|MultiEdit)\([^)]*[/*~][^)]*\)")
TASK_TOKEN = re.compile(r"\bTask(?:\(|\b)")
HOOK_PLACEHOLDER = re.compile(r"\$\{CLAUDE_(?:PROJECT_DIR|PLUGIN_ROOT|PLUGIN_DATA)\}")
BROAD_MCP_ALLOW = re.compile(r"^mcp__[A-Za-z0-9._-]+__(?:\*|.+\*)$")
BROAD_SHELL_ALLOW = re.compile(r"^(?:Bash|PowerShell)\((?:bash|sh|python|python3|node|perl|ruby|env|printenv|cat|find|jq) \*\)$")
CLAUDE_CLI_INVOCATION = re.compile(r"(?<![\w.-])claude\s+(?:-p|--print|--agent|--worktree)\b")
CLAUDE_CLI_OPTIONS = {"-p", "--print", "--agent", "--worktree"}


class TargetValidationError(ValueError):
    """当 --target 无法定位可读的 Claude 项目时抛出。"""


@dataclass(frozen=True)
class TargetSelection:
    requested_target: str
    root: Path
    target_kind: str
    claude_dir: Path | None = None


def normalize_target(requested_target: str) -> TargetSelection:
    """校验 --target，并将项目级 .claude 目录规范化到项目根。"""
    if not requested_target or not requested_target.strip():
        raise TargetValidationError("Target must not be empty")

    try:
        requested_path = Path(requested_target).expanduser()
        lexical_path = Path(os.path.abspath(requested_path))
        resolved_path = requested_path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise TargetValidationError(f"Target does not exist or cannot be resolved: {requested_target} ({exc})") from exc

    if not resolved_path.is_dir():
        raise TargetValidationError(f"Target must be a directory: {requested_target}")

    if any(part in HOST_CONFIG_DIRS for part in (*lexical_path.parts, *resolved_path.parts)):
        raise TargetValidationError(f"Codex host configuration is not a Claude project target: {requested_target}")

    try:
        lexical_user_claude_dir = Path(os.path.abspath(Path.home() / ".claude"))
        user_claude_dir = lexical_user_claude_dir.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        lexical_user_claude_dir = Path.home() / ".claude"
        user_claude_dir = Path.home() / ".claude"
    if (
        lexical_path == lexical_user_claude_dir
        or lexical_user_claude_dir in lexical_path.parents
        or resolved_path == user_claude_dir
        or user_claude_dir in resolved_path.parents
    ):
        raise TargetValidationError(
            f"User-level Claude configuration is not a project review target: {requested_target}"
        )

    if (
        (".claude" in lexical_path.parts and lexical_path.name != ".claude")
        or (".claude" in resolved_path.parts and resolved_path.name != ".claude")
    ):
        raise TargetValidationError(
            "Target must be a Claude project root or its direct .claude directory: "
            f"{requested_target}"
        )

    if requested_path.name == ".claude":
        try:
            root = lexical_path.parent.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise TargetValidationError(
                f"Claude project root does not exist or cannot be resolved: {lexical_path.parent} ({exc})"
            ) from exc
        claude_dir = resolved_path
        target_kind = "project-claude-dir"
    elif resolved_path.name == ".claude":
        root = resolved_path.parent
        claude_dir = resolved_path
        target_kind = "project-claude-dir"
    else:
        root = resolved_path
        claude_dir = None
        target_kind = "project-root"

    project_claude = root / ".claude"
    if project_claude.is_symlink():
        try:
            linked_claude = project_claude.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise TargetValidationError(
                f"Project .claude directory cannot be resolved: {project_claude} ({exc})"
            ) from exc
        if linked_claude == user_claude_dir or user_claude_dir in linked_claude.parents:
            raise TargetValidationError(
                f"Project .claude must not link to user-level Claude configuration: {requested_target}"
            )
        if any(part in HOST_CONFIG_DIRS for part in linked_claude.parts):
            raise TargetValidationError(
                f"Project .claude must not link to Codex host configuration: {requested_target}"
            )
        if not linked_claude.is_dir():
            raise TargetValidationError(f"Project .claude target must be a directory: {project_claude}")
        claude_dir = linked_claude

    for path in {resolved_path, root, *([claude_dir] if claude_dir is not None else [])}:
        if not path.is_dir() or not os.access(path, os.R_OK | os.X_OK):
            raise TargetValidationError(f"Target directory is not readable: {requested_target}")

    return TargetSelection(
        requested_target=requested_target,
        root=root,
        target_kind=target_kind,
        claude_dir=claude_dir,
    )


@dataclass
class Evidence:
    path: str
    line: int
    text: str


@dataclass
class Finding:
    id: str
    severity: str
    cls: str
    title: str
    message: str
    evidence: list[Evidence]
    official_source: str | None = None
    confidence: str = "candidate"


class ReviewScanner:
    def __init__(self, root: Path, runtime: str, include_eval_targets: bool = False,
                 requested_target: str | None = None, target_kind: str = "project-root",
                 claude_dir: Path | None = None):
        self.root = root.resolve()
        project_claude = self.root / ".claude"
        self.claude_dir = None
        if project_claude.is_symlink():
            try:
                linked_claude = project_claude.resolve(strict=True)
                if linked_claude.is_dir():
                    self.claude_dir = linked_claude
            except (OSError, RuntimeError):
                pass
        elif claude_dir is not None and claude_dir.resolve() != project_claude.resolve(strict=False):
            self.claude_dir = claude_dir.resolve()
        self.requested_target = requested_target if requested_target is not None else str(root)
        self.target_kind = target_kind
        self.runtime_requested = runtime
        self.include_eval_targets = include_eval_targets
        self.files: list[Path] = []
        self.logical_paths: dict[Path, str] = {}
        self.text: dict[Path, str] = {}
        self.findings: list[Finding] = []
        self.settings: list[tuple[Path, dict[str, Any]]] = []
        self.project_deny_rules: set[str] = set()
        self.agent_tools: dict[Path, list[str]] = {}
        self.runtime_mode = "unknown"
        self.runtime_evidence: list[Evidence] = []
        self.sdk_files: list[Path] = []
        self.eval_assets: list[str] = []
        # 静态 helper 不执行 PATH 中的任何二进制；宿主可在受信环境中另行记录版本。
        self.claude_version: str | None = None

    def rel(self, p: Path) -> str:
        if p in self.logical_paths:
            return self.logical_paths[p]
        try:
            return p.resolve().relative_to(self.root).as_posix()
        except Exception:
            return p.as_posix()

    def read(self, p: Path) -> str:
        if p not in self.text:
            try:
                self.text[p] = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                self.text[p] = ""
        return self.text[p]

    def ev(self, p: Path, line: int, text: str | None = None) -> Evidence:
        if text is None:
            lines = self.read(p).splitlines()
            text = lines[line - 1] if 1 <= line <= len(lines) else ""
        return Evidence(self.rel(p), line, text.strip()[:320])

    def find_line(self, p: Path, needle: str) -> Evidence:
        for i, line in enumerate(self.read(p).splitlines(), 1):
            if needle in line:
                return self.ev(p, i, line)
        return self.ev(p, 1)

    def regex_evidence(self, p: Path, rx: re.Pattern[str], limit: int = 12) -> list[Evidence]:
        out: list[Evidence] = []
        for i, line in enumerate(self.read(p).splitlines(), 1):
            if rx.search(line):
                out.append(self.ev(p, i, line))
                if len(out) >= limit:
                    break
        return out

    def add(self, fid: str, severity: str, cls: str, title: str, message: str,
            evidence: Iterable[Evidence] = (), official_source: str | None = None,
            confidence: str = "candidate") -> None:
        self.findings.append(Finding(fid, severity, cls, title, message, list(evidence), official_source, confidence))

    @staticmethod
    def is_eval_file(p: Path) -> bool:
        name = p.name.lower()
        if p.suffix.lower() == ".py":
            return name in {"conftest.py", "noxfile.py"} or name.startswith("test_") or name.endswith("_test.py")
        if p.suffix.lower() in JAVASCRIPT_SOURCE_EXTENSIONS:
            return bool(re.search(r"\.(?:test|spec)\.(?:[cm]?[jt]sx?)$", name))
        return False

    @staticmethod
    def is_claude_config_path(path: Path) -> bool:
        return bool(path.parts) and path.parts[0] == ".claude"

    @staticmethod
    def linked_claude_directory_allowed(relative: Path) -> bool:
        if not relative.parts:
            return True
        head = relative.parts[0]
        if head in {"rules", "commands"}:
            return True
        if head == "skills":
            return len(relative.parts) <= 2
        if head in {"agents", "output-styles"}:
            return len(relative.parts) == 1
        return False

    @staticmethod
    def linked_claude_file_allowed(relative: Path) -> bool:
        parts = relative.parts
        if len(parts) == 1:
            return relative.name in {"CLAUDE.md", "settings.json", "settings.local.json"}
        head = parts[0]
        if head == "rules":
            return relative.suffix == ".md"
        if head == "skills":
            return len(parts) == 3 and relative.name == "SKILL.md"
        if head == "agents":
            return len(parts) == 2 and relative.suffix == ".md"
        if head == "commands":
            return relative.suffix == ".md"
        if head == "output-styles":
            return len(parts) == 2 and relative.suffix == ".md"
        return False

    def collect_tree(self, scan_root: Path, logical_prefix: str | None = None) -> None:
        restricted_linked_claude = logical_prefix == ".claude"
        for base, dirs, names in os.walk(scan_root, followlinks=False):
            b = Path(base)
            keep_dirs = []
            for d in dirs:
                if d in BUILD_DIRS or d in HOST_CONFIG_DIRS:
                    continue
                if logical_prefix is None and b == self.root and d == ".claude" and (b / d).is_symlink():
                    continue
                directory = b / d
                relative_directory = directory.relative_to(scan_root)
                if restricted_linked_claude and not self.linked_claude_directory_allowed(relative_directory):
                    continue
                logical_directory = relative_directory
                if logical_prefix is not None:
                    logical_directory = Path(logical_prefix) / logical_directory
                if directory.is_symlink():
                    logical_text = logical_directory.as_posix()
                    if logical_text == ".claude" or logical_text.startswith(".claude/"):
                        self.add(
                            "A-CONFIG-SYMLINK",
                            "P2",
                            "UNVERIFIED",
                            "Claude configuration directory is a symbolic link",
                            "Static review does not follow nested configuration directory symbolic links. Verify the target and effective contents separately.",
                            [Evidence(logical_text, 1, "symbolic link target not read")],
                        )
                    continue
                if (
                    not self.include_eval_targets
                    and not self.is_claude_config_path(logical_directory)
                    and d.lower() in EVAL_DIR_NAMES
                ):
                    continue
                keep_dirs.append(d)
            dirs[:] = keep_dirs
            for name in names:
                p = b / name
                if name in {"AGENTS.md", "AGENTS.override.md"}:
                    continue
                logical = p.relative_to(scan_root)
                if restricted_linked_claude and not self.linked_claude_file_allowed(logical):
                    continue
                if logical_prefix is not None:
                    logical = Path(logical_prefix) / logical
                if (
                    not self.include_eval_targets
                    and not self.is_claude_config_path(logical)
                    and self.is_eval_file(p)
                ):
                    continue
                if logical_prefix is not None or p.is_symlink():
                    logical = logical.as_posix()
                    self.logical_paths[p] = logical
                if p.is_symlink():
                    if self.classify(p) != "other":
                        self.add(
                            "A-CONFIG-SYMLINK",
                            "P2",
                            "UNVERIFIED",
                            "Claude configuration file is a symbolic link",
                            "Static review does not follow configuration file symbolic links. Verify the target and effective contents separately.",
                            [Evidence(self.rel(p), 1, "symbolic link target not read")],
                        )
                    continue
                try:
                    if p.stat().st_size > 5 * 1024 * 1024:
                        continue
                except OSError:
                    continue
                if p.suffix in TEXT_EXTENSIONS or name in {
                    "CLAUDE.md", "CLAUDE.local.md", ".mcp.json", ".worktreeinclude", "Makefile",
                    *DEPENDENCY_FILE_NAMES, *RUNTIME_ENTRY_FILE_NAMES,
                }:
                    if logical_prefix is not None:
                        resolved = p.resolve()
                        self.files = [existing for existing in self.files if existing.resolve() != resolved]
                    self.files.append(p)

    def collect_files(self) -> None:
        self.collect_tree(self.root)
        if self.claude_dir is not None:
            self.collect_tree(self.claude_dir, ".claude")

    def classify(self, p: Path) -> str:
        r = self.rel(p)
        if r in {"CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"}:
            return "instructions"
        if r in {".claude/settings.json", ".claude/settings.local.json"}:
            return "settings"
        if r == ".mcp.json":
            return "mcp"
        if r == ".worktreeinclude":
            return "worktreeinclude"
        if r.startswith(".claude/rules/") and p.suffix == ".md":
            return "rule"
        if r.startswith(".claude/skills/") and p.name == "SKILL.md":
            return "skill"
        if r.startswith(".claude/agents/") and p.suffix == ".md":
            return "agent"
        if r.startswith(".claude/commands/") and p.suffix == ".md":
            return "command"
        if r.startswith(".claude/output-styles/") and p.suffix == ".md":
            return "output-style"
        return "other"

    def parse_frontmatter(self, p: Path) -> tuple[dict[str, Any], str, int, str | None]:
        raw = self.read(p)
        lines = raw.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, raw, 1, None
        end = None
        for i in range(1, min(len(lines), 300)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            return {}, raw, 1, "unterminated YAML frontmatter"
        fm_text = "\n".join(lines[1:end])
        body = "\n".join(lines[end + 1:])
        if yaml is not None:
            try:
                value = yaml.safe_load(fm_text)
                return (value if isinstance(value, dict) else {}), body, end + 2, None
            except Exception as e:
                return {}, body, end + 2, f"YAML parse error: {e}"
        # Dependency-free shallow parser for common scalar/list fields.
        data: dict[str, Any] = {}
        current: str | None = None
        for line in fm_text.splitlines():
            m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
            if m:
                key, val = m.group(1), m.group(2).strip()
                current = key
                if val == "":
                    data[key] = []
                elif val.lower() in {"true", "false"}:
                    data[key] = val.lower() == "true"
                else:
                    data[key] = val.strip("\"'")
            elif current and re.match(r"^\s*-\s+", line):
                item = re.sub(r"^\s*-\s+", "", line).strip().strip("\"'")
                if not isinstance(data.get(current), list):
                    data[current] = []
                data[current].append(item)
        return data, body, end + 2, None

    @staticmethod
    def as_list(v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            # Claude frontmatter often accepts comma- or space-separated tool lists.
            if "," in v:
                return [x.strip() for x in v.split(",") if x.strip()]
            return [v.strip()] if v.strip() else []
        return [str(v)]

    def is_runtime_candidate(self, p: Path) -> bool:
        if self.classify(p) != "other":
            return False
        name = p.name
        return (
            p.suffix.lower() in RUNTIME_SOURCE_EXTENSIONS | RUNTIME_SCRIPT_EXTENSIONS
            or name in DEPENDENCY_FILE_NAMES
            or name in RUNTIME_ENTRY_FILE_NAMES
            or (name.startswith("requirements") and p.suffix.lower() == ".txt")
            or name.startswith("Dockerfile.")
            or name.startswith("docker-compose.")
            or name.startswith("compose.")
        )

    def pyproject_dependency_evidence(self, p: Path) -> list[Evidence]:
        if tomllib is not None:
            try:
                tomllib.loads(self.read(p))
            except Exception:
                return []
        lines = self.read(p).splitlines()
        hit_lines: list[int] = []
        section = ""
        dependency_list_open = False
        dependency_literal = re.compile(
            r"[\"']claude-agent-sdk(?:\[[^]]+\])?(?:\s*[<>=!~].*?)?[\"']",
            re.I,
        )
        for index, line in enumerate(lines, 1):
            active = line.split("#", 1)[0].strip()
            section_match = re.match(r"^\[([^]]+)\]$", active)
            if section_match:
                section = section_match.group(1)
                dependency_list_open = False
                continue
            if section in {"project", "project.optional-dependencies"}:
                assignment = re.match(r"^([A-Za-z0-9_.-]+)\s*=\s*(.*)$", active)
                starts_dependency_list = bool(
                    assignment
                    and "[" in assignment.group(2)
                    and (section == "project.optional-dependencies" or assignment.group(1) == "dependencies")
                )
                if starts_dependency_list:
                    dependency_list_open = assignment.group(2).count("[") > assignment.group(2).count("]")
                    if dependency_literal.search(assignment.group(2)):
                        hit_lines.append(index)
                elif dependency_list_open:
                    if dependency_literal.search(active):
                        hit_lines.append(index)
                    dependency_list_open = active.count("[") + int(dependency_list_open) > active.count("]")
            if section == "tool.poetry.dependencies" and re.match(
                r"^[\"']?claude-agent-sdk(?:\[[^]]+\])?[\"']?\s*=", active, re.I
            ):
                hit_lines.append(index)
        return [self.ev(p, line) for line in sorted(set(hit_lines))[:8]]

    def dependency_evidence(self, p: Path) -> list[Evidence]:
        if p.name == "pyproject.toml":
            return self.pyproject_dependency_evidence(p)
        hits: list[Evidence] = []
        requirement = p.name.startswith("requirements") and p.suffix.lower() == ".txt"
        for i, line in enumerate(self.read(p).splitlines(), 1):
            active = line.split("#", 1)[0].strip()
            if not active:
                continue
            if requirement:
                matched = bool(re.match(r"^(?:claude-agent-sdk|claude_agent_sdk)(?:\[[^]]+\])?\s*(?:[<>=!~].*)?(?:;.*)?$", active, re.I))
            elif p.name == "package.json":
                matched = bool(re.search(r"[\"']@anthropic-ai/claude-agent-sdk[\"']\s*:", active))
            else:
                matched = bool(
                    re.search(
                        r"[\"']@anthropic-ai/claude-agent-sdk"
                        r"(?:@[^\"']+)?[\"']\s*[:=]",
                        active,
                    )
                    or re.match(
                        r"^(?:name\s*=\s*[\"'])?claude-agent-sdk"
                        r"(?:[\"']|\s*[:=@<>=!~])",
                        active,
                        re.I,
                    )
                    or re.search(
                        r"[\"']claude-agent-sdk(?:\[[^]]+\])?"
                        r"(?:[<>=!~].*?)?[\"']\s*(?:,|\]|$)",
                        active,
                        re.I,
                    )
                    or re.match(
                        r"^claude-agent-sdk\s*=\s*[\"'][^\"']+[\"']",
                        active,
                        re.I,
                    )
                )
            if matched:
                hits.append(self.ev(p, i, line))
                if len(hits) >= 8:
                    break
        return hits

    def python_sdk_evidence(self, p: Path) -> list[Evidence]:
        if "claude_agent_sdk" not in self.read(p):
            return []
        try:
            tree = ast.parse(self.read(p), filename=str(p))
        except (SyntaxError, ValueError):
            hit_lines: set[int] = set()
            try:
                tokens = list(tokenize.generate_tokens(io.StringIO(self.read(p)).readline))
            except (tokenize.TokenError, IndentationError):
                tokens = []
            significant = [token for token in tokens if token.type not in {
                tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                tokenize.ENCODING,
            }]
            for index, token in enumerate(significant):
                if token.type != tokenize.NAME or token.string not in {"from", "import"}:
                    continue
                following = significant[index + 1:index + 3]
                if following and following[0].type == tokenize.NAME and following[0].string == "claude_agent_sdk":
                    hit_lines.add(token.start[0])
            return [self.ev(p, line) for line in sorted(hit_lines)[:8]]
        lines = self.read(p).splitlines()
        hit_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "claude_agent_sdk" or alias.name.startswith("claude_agent_sdk.") for alias in node.names):
                    hit_lines.add(node.lineno)
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module == "claude_agent_sdk" or node.module.startswith("claude_agent_sdk.")):
                    hit_lines.add(node.lineno)
        return [self.ev(p, line, lines[line - 1]) for line in sorted(hit_lines)[:8]]

    @staticmethod
    def javascript_tokens(text: str) -> list[tuple[str, str, int]]:
        tokens: list[tuple[str, str, int]] = []
        i = 0
        line = 1
        while i < len(text):
            ch = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if ch.isspace():
                line += ch == "\n"
                i += 1
            elif ch == "/" and nxt == "/":
                end = text.find("\n", i + 2)
                i = len(text) if end < 0 else end
            elif ch == "/" and nxt == "*":
                end = text.find("*/", i + 2)
                segment = text[i:] if end < 0 else text[i:end + 2]
                line += segment.count("\n")
                i = len(text) if end < 0 else end + 2
            elif ch in {"'", '"', "`"}:
                quote = ch
                start_line = line
                value: list[str] = []
                i += 1
                while i < len(text):
                    ch = text[i]
                    if ch == "\\" and i + 1 < len(text):
                        value.extend((ch, text[i + 1]))
                        line += text[i + 1] == "\n"
                        i += 2
                    elif ch == quote:
                        i += 1
                        break
                    else:
                        value.append(ch)
                        line += ch == "\n"
                        i += 1
                tokens.append(("template" if quote == "`" else "string", "".join(value), start_line))
            elif ch.isalpha() or ch in {"_", "$"}:
                start = i
                while i < len(text) and (text[i].isalnum() or text[i] in {"_", "$"}):
                    i += 1
                tokens.append(("name", text[start:i], line))
            else:
                tokens.append(("punct", ch, line))
                i += 1
        return tokens

    def javascript_sdk_evidence(self, p: Path) -> list[Evidence]:
        if "@anthropic-ai/claude-agent-sdk" not in self.read(p):
            return []
        tokens = self.javascript_tokens(self.read(p))
        hit_lines: set[int] = set()
        module = "@anthropic-ai/claude-agent-sdk"
        for index, token in enumerate(tokens):
            if token[:2] not in {("name", "import"), ("name", "require")}:
                continue
            line = token[2]
            following = tokens[index + 1:index + 40]
            if following and following[0][:2] == ("punct", "("):
                if len(following) > 1 and following[1][:2] == ("string", module):
                    hit_lines.add(line)
            elif token[1] == "import":
                for offset, candidate in enumerate(following):
                    if candidate[:2] == ("string", module) and (
                        offset == 0 or following[offset - 1][:2] == ("name", "from")
                    ):
                        hit_lines.add(line)
                        break
                    if candidate[:2] == ("punct", ";"):
                        break
        return [self.ev(p, line) for line in sorted(hit_lines)[:8]]

    @staticmethod
    def command_uses_claude_cli(arguments: list[str]) -> bool:
        if not arguments or Path(arguments[0]).name != "claude":
            return False
        return any(option in CLAUDE_CLI_OPTIONS for option in arguments[1:])

    def python_cli_evidence(self, p: Path) -> Evidence | None:
        text = self.read(p)
        if "claude" not in text:
            return None
        try:
            tree = ast.parse(text, filename=str(p))
        except (SyntaxError, ValueError):
            return None

        imported_process_calls: set[str] = set()
        module_aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in {"os", "subprocess"}:
                        module_aliases[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                for alias in node.names:
                    if alias.name in {"call", "check_call", "check_output", "Popen", "run"}:
                        imported_process_calls.add(alias.asname or alias.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            is_process_call = False
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
            ):
                module = module_aliases.get(node.func.value.id)
                is_process_call = (
                    module == "subprocess"
                    and node.func.attr in {"call", "check_call", "check_output", "Popen", "run"}
                ) or (module == "os" and node.func.attr == "system")
            elif isinstance(node.func, ast.Name):
                is_process_call = node.func.id in imported_process_calls
            if not is_process_call:
                continue

            first = node.args[0]
            arguments: list[str] = []
            if isinstance(first, (ast.List, ast.Tuple)):
                for element in first.elts:
                    if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
                        arguments = []
                        break
                    arguments.append(element.value)
            elif isinstance(first, ast.Constant) and isinstance(first.value, str):
                try:
                    arguments = shlex.split(first.value)
                except ValueError:
                    arguments = []
            if self.command_uses_claude_cli(arguments):
                return self.ev(p, node.lineno)
        return None

    @staticmethod
    def javascript_child_process_bindings(
        tokens: list[tuple[str, str, int]],
    ) -> tuple[
        dict[int, dict[str, str | None]],
        dict[int, int | None],
        list[int],
    ]:
        process_calls = {"exec", "execFile", "execSync", "spawn", "spawnSync"}
        process_modules = {"child_process", "node:child_process"}
        opening = {"(": ")", "[": "]", "{": "}"}
        closing = {value: key for key, value in opening.items()}
        pairs: dict[int, int] = {}
        stacks: dict[str, list[int]] = {key: [] for key in opening}
        for index, token in enumerate(tokens):
            if token[0] != "punct":
                continue
            value = token[1]
            if value in opening:
                stacks[value].append(index)
            elif value in closing and stacks[closing[value]]:
                start = stacks[closing[value]].pop()
                pairs[start] = index
                pairs[index] = start

        def previous_boundary(index: int) -> int:
            while index > 0 and tokens[index - 1][:2] not in {
                ("punct", ";"), ("punct", "{"), ("punct", "}"),
            }:
                index -= 1
            return index

        non_scope_braces: set[int] = set()
        for start, end in list(pairs.items()):
            if start > end or tokens[start][:2] != ("punct", "{"):
                continue
            boundary = previous_boundary(start)
            prefix = tokens[boundary:start]
            suffix = tokens[end + 1:min(len(tokens), end + 4)]
            if any(token[:2] == ("name", "import") for token in prefix) \
                    and any(token[:2] == ("name", "from") for token in suffix):
                non_scope_braces.add(start)
            elif suffix and suffix[0][:2] == ("punct", "=") \
                    and any(token[:2] in {
                        ("name", "const"), ("name", "let"), ("name", "var"),
                    } for token in prefix):
                non_scope_braces.add(start)

        scope_parent: dict[int, int | None] = {0: None}
        scope_bindings: dict[int, dict[str, str | None]] = {0: {}}
        token_scope = [0] * len(tokens)
        scope_open_to_id: dict[int, int] = {}
        scope_stack = [0]
        next_scope = 1
        for index, token in enumerate(tokens):
            token_scope[index] = scope_stack[-1]
            if token[:2] == ("punct", "{") and index not in non_scope_braces:
                scope_id = next_scope
                next_scope += 1
                scope_open_to_id[index] = scope_id
                scope_parent[scope_id] = scope_stack[-1]
                scope_bindings[scope_id] = {}
                scope_stack.append(scope_id)
            elif token[:2] == ("punct", "}"):
                start = pairs.get(index)
                if start in scope_open_to_id and len(scope_stack) > 1:
                    scope_stack.pop()

        def resolve(scope: int, name: str) -> str | None:
            current: int | None = scope
            while current is not None:
                if name in scope_bindings[current]:
                    return scope_bindings[current][name]
                current = scope_parent[current]
            return None

        def statement_end(index: int) -> int:
            paren = bracket = brace = 0
            while index < len(tokens):
                token = tokens[index]
                if token[0] == "punct":
                    if token[1] == "(":
                        paren += 1
                    elif token[1] == ")":
                        paren = max(0, paren - 1)
                    elif token[1] == "[":
                        bracket += 1
                    elif token[1] == "]":
                        bracket = max(0, bracket - 1)
                    elif token[1] == "{":
                        brace += 1
                    elif token[1] == "}":
                        if brace == 0:
                            return index
                        brace -= 1
                    elif token[1] == ";" and paren == bracket == brace == 0:
                        return index
                index += 1
            return len(tokens)

        declarations: list[tuple[int, int, str, int, int]] = []
        declaration_keywords = {"const", "let", "var"}
        for index, token in enumerate(tokens):
            if token[0] != "name" or token[1] not in declaration_keywords:
                continue
            scope = token_scope[index]
            lhs = index + 1
            end = statement_end(lhs)
            if lhs >= end:
                continue
            if tokens[lhs][0] == "name":
                name = tokens[lhs][1]
                scope_bindings[scope][name] = None
                if lhs + 1 < end and tokens[lhs + 1][:2] == ("punct", "="):
                    declarations.append((index, scope, name, lhs + 2, end))
            elif tokens[lhs][:2] == ("punct", "{") and lhs in pairs:
                close = pairs[lhs]
                if close >= end:
                    continue
                pattern = tokens[lhs + 1:close]
                offset = 0
                while offset < len(pattern):
                    candidate = pattern[offset]
                    if candidate[0] != "name":
                        offset += 1
                        continue
                    bound = candidate[1]
                    if offset + 2 < len(pattern) \
                            and pattern[offset + 1][:2] == ("punct", ":") \
                            and pattern[offset + 2][0] == "name":
                        bound = pattern[offset + 2][1]
                        offset += 2
                    scope_bindings[scope][bound] = None
                    offset += 1
                if close + 1 < end and tokens[close + 1][:2] == ("punct", "="):
                    declarations.append((index, scope, "", close + 2, end))

        for index, token in enumerate(tokens):
            if token[:2] != ("name", "function"):
                continue
            cursor = index + 1
            if cursor < len(tokens) and tokens[cursor][0] == "name":
                scope_bindings[token_scope[index]][tokens[cursor][1]] = None
                cursor += 1
            while cursor < len(tokens) and tokens[cursor][:2] != ("punct", "("):
                if tokens[cursor][:2] in {("punct", ";"), ("punct", "{")}:
                    break
                cursor += 1
            close = pairs.get(cursor)
            if close is None:
                continue
            body = close + 1
            while body < len(tokens) and tokens[body][:2] != ("punct", "{"):
                body += 1
            body_scope = scope_open_to_id.get(body)
            if body_scope is None:
                continue
            for parameter in tokens[cursor + 1:close]:
                if parameter[0] == "name":
                    scope_bindings[body_scope][parameter[1]] = None

        for index in range(len(tokens) - 1):
            if tokens[index][:2] != ("punct", "=") or tokens[index + 1][:2] != ("punct", ">"):
                continue
            body = index + 2
            if body >= len(tokens) or tokens[body][:2] != ("punct", "{"):
                continue
            body_scope = scope_open_to_id.get(body)
            if body_scope is None:
                continue
            if index > 0 and tokens[index - 1][:2] == ("punct", ")"):
                start = pairs.get(index - 1)
                parameters = tokens[start + 1:index - 1] if start is not None else []
            else:
                parameters = tokens[index - 1:index]
            for parameter in parameters:
                if parameter[0] == "name":
                    scope_bindings[body_scope][parameter[1]] = None

        def add_named_imports(
            scope: int, segment: list[tuple[str, str, int]], separator: str,
        ) -> None:
            offset = 0
            while offset < len(segment):
                candidate = segment[offset]
                if candidate[0] != "name" or candidate[1] not in process_calls:
                    offset += 1
                    continue
                alias = candidate[1]
                if offset + 2 < len(segment) \
                        and segment[offset + 1][:2] in {("name", "as"), ("punct", separator)} \
                        and segment[offset + 2][0] == "name":
                    alias = segment[offset + 2][1]
                    offset += 2
                scope_bindings[scope][alias] = candidate[1]
                offset += 1

        for index, token in enumerate(tokens):
            if token[:2] != ("name", "import"):
                continue
            end = statement_end(index + 1)
            statement = tokens[index + 1:end]
            module_positions = [
                offset for offset, candidate in enumerate(statement)
                if candidate[0] == "string" and candidate[1] in process_modules
            ]
            if not module_positions:
                continue
            module_pos = module_positions[0]
            spec = statement[:module_pos]
            if spec and spec[-1][:2] == ("name", "from"):
                spec = spec[:-1]
            scope = token_scope[index]
            if spec and spec[0][:2] == ("punct", "{"):
                add_named_imports(scope, spec, ":")
            elif len(spec) >= 3 and spec[0][:2] == ("punct", "*") \
                    and spec[1][:2] == ("name", "as") and spec[2][0] == "name":
                scope_bindings[scope][spec[2][1]] = "namespace"
            elif spec and spec[0][0] == "name":
                scope_bindings[scope][spec[0][1]] = "namespace"

        # Declaration expressions are evaluated in source order. Pre-registered local
        # names make lexical shadowing visible even before their declaration token.
        for declaration_index, scope, name, expression_start, expression_end in declarations:
            expression = tokens[expression_start:expression_end]
            if not expression:
                continue
            is_require = len(expression) >= 3 \
                and expression[0][:2] == ("name", "require") \
                and expression[1][:2] == ("punct", "(") \
                and expression[2][0] == "string" \
                and expression[2][1] in process_modules
            if not name:
                if not is_require:
                    continue
                lhs_start = declaration_index + 1
                lhs_close = pairs.get(lhs_start)
                if lhs_close is not None:
                    add_named_imports(scope, tokens[lhs_start + 1:lhs_close], ":")
                continue

            value: str | None = None
            if is_require:
                if len(expression) >= 6 \
                        and expression[3][:2] == ("punct", ")") \
                        and expression[4][:2] == ("punct", ".") \
                        and expression[5][0] == "name" \
                        and expression[5][1] in process_calls:
                    value = expression[5][1]
                elif len(expression) >= 4 and expression[3][:2] == ("punct", ")"):
                    value = "namespace"
            elif expression[0][0] == "name":
                source = resolve(scope, expression[0][1])
                if len(expression) >= 3 \
                        and expression[1][:2] == ("punct", ".") \
                        and expression[2][0] == "name" \
                        and expression[2][1] in process_calls:
                    if source == "namespace":
                        value = expression[2][1]
                elif source in process_calls:
                    value = source
            if value is not None:
                scope_bindings[scope][name] = value

        return scope_bindings, scope_parent, token_scope

    @staticmethod
    def javascript_call_arguments(
        tokens: list[tuple[str, str, int]], open_paren: int, shell_form: bool,
    ) -> list[str]:
        groups: list[list[tuple[str, str, int]]] = [[]]
        paren_depth = 1
        bracket_depth = 0
        brace_depth = 0
        for token in tokens[open_paren + 1:]:
            kind, value, _line = token
            if kind == "punct":
                if value == "(":
                    paren_depth += 1
                elif value == ")":
                    paren_depth -= 1
                    if paren_depth == 0:
                        break
                elif value == "[":
                    bracket_depth += 1
                elif value == "]":
                    bracket_depth = max(0, bracket_depth - 1)
                elif value == "{":
                    brace_depth += 1
                elif value == "}":
                    brace_depth = max(0, brace_depth - 1)
                elif value == "," and paren_depth == 1 and bracket_depth == 0 and brace_depth == 0:
                    groups.append([])
                    continue
            groups[-1].append(token)

        if not groups or len(groups[0]) != 1 or groups[0][0][0] != "string":
            return []
        executable_or_command = groups[0][0][1]
        if shell_form:
            try:
                return shlex.split(executable_or_command)
            except ValueError:
                return []
        arguments = [executable_or_command]
        if len(groups) >= 2 and groups[1] and groups[1][0][:2] == ("punct", "["):
            arguments.extend(token[1] for token in groups[1] if token[0] == "string")
        return arguments

    def javascript_cli_evidence(self, p: Path) -> Evidence | None:
        text = self.read(p)
        if "claude" not in text:
            return None
        tokens = self.javascript_tokens(text)
        process_calls = {"exec", "execFile", "execSync", "spawn", "spawnSync"}
        scope_bindings, scope_parent, token_scope = self.javascript_child_process_bindings(tokens)
        if not any(bindings for bindings in scope_bindings.values()):
            return None

        def resolve(scope: int, name: str) -> str | None:
            current: int | None = scope
            while current is not None:
                if name in scope_bindings[current]:
                    return scope_bindings[current][name]
                current = scope_parent[current]
            return None

        for index, token in enumerate(tokens):
            method: str | None = None
            open_paren: int | None = None
            if token[0] == "name" and index + 1 < len(tokens) \
                    and tokens[index + 1][:2] == ("punct", "("):
                resolved = resolve(token_scope[index], token[1])
                if resolved in process_calls:
                    method = resolved
                    open_paren = index + 1
            elif (
                token[0] == "name"
                and index + 3 < len(tokens)
                and tokens[index + 1][:2] == ("punct", ".")
                and tokens[index + 2][0] == "name"
                and tokens[index + 2][1] in process_calls
                and tokens[index + 3][:2] == ("punct", "(")
                and resolve(token_scope[index], token[1]) == "namespace"
            ):
                method = tokens[index + 2][1]
                open_paren = index + 3
            if method is None or open_paren is None:
                continue
            arguments = self.javascript_call_arguments(
                tokens, open_paren, shell_form=method in {"exec", "execSync"}
            )
            if self.command_uses_claude_cli(arguments):
                return self.ev(p, token[2])
        return None

    def sdk_evidence(self, p: Path) -> list[Evidence]:
        if not self.is_runtime_candidate(p):
            return []
        dependency = p.name in DEPENDENCY_FILE_NAMES or (
            p.name.startswith("requirements") and p.suffix.lower() == ".txt"
        )
        if dependency:
            return self.dependency_evidence(p)
        if p.suffix.lower() == ".py":
            return self.python_sdk_evidence(p)
        if p.suffix.lower() in JAVASCRIPT_SOURCE_EXTENSIONS:
            return self.javascript_sdk_evidence(p)
        return []

    def cli_evidence(self, p: Path) -> Evidence | None:
        if "claude" not in self.read(p):
            return None
        if p.name == "package.json":
            try:
                scripts = json.loads(self.read(p)).get("scripts", {})
            except (AttributeError, json.JSONDecodeError):
                scripts = {}
            if isinstance(scripts, dict):
                for command in scripts.values():
                    if not isinstance(command, str):
                        continue
                    try:
                        arguments = shlex.split(command)
                    except ValueError:
                        arguments = []
                    if self.command_uses_claude_cli(arguments):
                        return self.find_line(p, command)
            return None
        if p.suffix.lower() == ".py":
            return self.python_cli_evidence(p)
        if p.suffix.lower() in JAVASCRIPT_SOURCE_EXTENSIONS:
            return self.javascript_cli_evidence(p)
        if p.suffix.lower() not in RUNTIME_SCRIPT_EXTENSIONS and p.name not in RUNTIME_ENTRY_FILE_NAMES \
                and not p.name.startswith(("Dockerfile.", "docker-compose.", "compose.")):
            return None
        for i, line in enumerate(self.read(p).splitlines(), 1):
            command = line
            if p.name == "Dockerfile" or p.name.startswith("Dockerfile."):
                directive = re.match(r"^\s*(?:ENTRYPOINT|CMD)\s+(.+?)\s*$", line, re.I)
                if not directive:
                    continue
                command = directive.group(1)
                if command.startswith("["):
                    try:
                        arguments = json.loads(command)
                    except json.JSONDecodeError:
                        arguments = []
                    if (
                        isinstance(arguments, list)
                        and all(isinstance(argument, str) for argument in arguments)
                        and self.command_uses_claude_cli(arguments)
                    ):
                        return self.ev(p, i, line)
                    continue
            try:
                tokens = shlex.split(command, comments=True, posix=True)
            except ValueError:
                continue
            if self.command_uses_claude_cli(tokens):
                return self.ev(p, i, line)
        return None

    def detect_runtime(self) -> None:
        sdk_hits: list[Evidence] = []
        cli_hits: list[Evidence] = []
        self.sdk_files = []
        for p in self.files:
            if not self.is_runtime_candidate(p):
                continue
            file_sdk_hits = self.sdk_evidence(p)
            if file_sdk_hits:
                self.sdk_files.append(p)
                sdk_hits.extend(file_sdk_hits)
            cli_hit = self.cli_evidence(p)
            if cli_hit is not None:
                cli_hits.append(cli_hit)
        if self.runtime_requested != "auto":
            self.runtime_mode = self.runtime_requested
        elif sdk_hits and cli_hits:
            self.runtime_mode = "both"
        elif sdk_hits:
            self.runtime_mode = "agent-sdk"
        elif cli_hits:
            self.runtime_mode = "cli"
        else:
            self.runtime_mode = "unknown"
        self.runtime_evidence = sdk_hits[:8] + cli_hits[:4]

    def discover_eval_assets(self) -> None:
        candidates: list[str] = []
        for name in ["package.json", "pyproject.toml", "Makefile", "tox.ini", "noxfile.py", "pytest.ini", "Taskfile.yml", "justfile"]:
            p = self.root / name
            if p.exists():
                candidates.append(name)
        for base, dirs, names in os.walk(self.root, followlinks=False):
            b = Path(base)
            dirs[:] = [d for d in dirs if d not in BUILD_DIRS and d not in HOST_CONFIG_DIRS]
            for name in names:
                p = b / name
                if self.is_eval_file(p):
                    candidates.append(self.rel(p))
            for d in dirs:
                if d.lower() in EVAL_DIR_NAMES:
                    candidates.append(self.rel(b / d))
            if len(candidates) >= 30:
                break
        ci = self.root / ".github" / "workflows"
        if ci.is_dir():
            candidates.append(".github/workflows/")
        self.eval_assets = sorted(set(candidates))[:30]

    def parse_json_configs(self) -> None:
        for p in self.files:
            typ = self.classify(p)
            if typ not in {"settings", "mcp"}:
                continue
            try:
                data = json.loads(self.read(p))
            except Exception as e:
                self.add("O-JSON", "P1", "OFFICIAL-NONCOMPLIANT", "JSON configuration does not parse",
                         f"{self.rel(p)} is expected to be JSON but could not be parsed: {e}", [self.ev(p, 1)],
                         OFFICIAL["settings"] if "settings" in OFFICIAL else None, "confirmed")
                continue
            if typ == "settings" and isinstance(data, dict):
                self.settings.append((p, data))
                perms = data.get("permissions")
                if isinstance(perms, dict):
                    for x in perms.get("deny", []) or []:
                        if isinstance(x, str):
                            self.project_deny_rules.add(x)

    def scan_instructions(self, p: Path) -> None:
        mcp = self.regex_evidence(p, MCP_NAME)
        if mcp:
            self.add("P-CLAUDE-PHYS", "P2", "PORTABILITY-RISK", "Physical MCP tool names in always-on project instructions",
                     "This is valid text, but repeated provider-specific names in reusable always-on context increase rename/migration drift. Review whether logical capability language is sufficient.", mcp)

    def scan_skill(self, p: Path) -> None:
        fm, body, body_line, err = self.parse_frontmatter(p)
        if err:
            self.add("O-SKILL-YAML", "P1", "OFFICIAL-NONCOMPLIANT", "Skill frontmatter is malformed",
                     err, [self.ev(p, 1)], OFFICIAL["skills"], "confirmed")
            return
        name = fm.get("name")
        if isinstance(name, str) and name:
            if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
                self.add("O-SKILL-NAME", "P2", "OFFICIAL-NONCOMPLIANT", "Skill name violates documented naming format",
                         "When an explicit Skill name is provided, use lowercase letters, numbers, and hyphens within the documented length constraints.",
                         [self.ev(p, 1)], OFFICIAL["skills"])
            if "claude" in name or "anthropic" in name:
                self.add("A-SKILL-PORTABLE-NAME", "P2", "OPTIMIZATION", "Skill name uses a reserved portable Agent Skills term",
                         "Claude Code can derive names from directories, but the portable Agent Skills standard reserves `claude` and `anthropic` in Skill names. Rename if cross-tool portability matters.",
                         [self.ev(p, 1)], OFFICIAL["skill_best_practices"])
        desc = fm.get("description")
        if not isinstance(desc, str) or not desc.strip():
            self.add("A-SKILL-DESC", "P3", "OPTIMIZATION", "Skill has no explicit description",
                     "Claude Code recommends a description so Claude can decide when to apply the Skill; include what it does and when to use it.",
                     [self.ev(p, 1)], OFFICIAL["skills"])
        allowed = self.as_list(fm.get("allowed-tools"))
        if allowed and self.runtime_mode in {"agent-sdk", "both"}:
            self.add("O-SKILL-ALLOWED-SDK", "P1", "OFFICIAL-SEMANTIC-ERROR", "SKILL.md allowed-tools does not apply through Agent SDK",
                     "Current official Agent SDK docs state that SKILL.md `allowed-tools` is CLI-only. SDK authorization must be implemented in SDK/runtime permission configuration.",
                     [self.ev(p, 1)], OFFICIAL["sdk_skills"], "confirmed")
        if any(x in {"Agent", "Skill"} for x in allowed):
            self.add("R-SKILL-BROAD-ORCH", "P2", "SECURITY-RISK", "Skill pre-approves a broad orchestration tool",
                     "Bare `Agent` or `Skill` is broader than a specific permission rule. This is not syntax-invalid; review whether broad pre-approval is intentional.",
                     [self.ev(p, 1)])
        if fm.get("context") == "fork":
            has_args = "$ARGUMENTS" in body or bool(fm.get("argument-hint")) or bool(fm.get("arguments"))
            if not has_args:
                self.add("R-SKILL-FORK-INPUT", "P2", "MAINTAINABILITY-RISK", "Forked Skill has no obvious explicit input contract",
                         "`context: fork` does not carry parent conversation history. Review whether the Skill task is fully self-contained and receives the needed request/state explicitly.",
                         [self.ev(p, 1)], OFFICIAL["skills"])
        task_hits = self.regex_evidence(p, TASK_TOKEN)
        if task_hits:
            self.add("A-TASK-ALIAS", "P3", "OPTIMIZATION", "Legacy Task terminology appears in Skill",
                     "Current Claude Code renamed Task to Agent; existing Task(...) references remain compatibility aliases.",
                     task_hits, OFFICIAL["subagents"], "confirmed")
        mcp = []
        for i, line in enumerate(body.splitlines(), body_line):
            if MCP_NAME.search(line):
                mcp.append(self.ev(p, i, line))
                if len(mcp) >= 10:
                    break
        if mcp:
            self.add("P-SKILL-PHYS", "P2", "PORTABILITY-RISK", "Skill body repeats physical MCP tool names",
                     "Provider-specific tool names in prose increase coupling. Keep them only where the model genuinely needs exact names; otherwise prefer stable capability semantics.", mcp)

    def scan_agent(self, p: Path) -> None:
        fm, body, body_line, err = self.parse_frontmatter(p)
        if err:
            self.add("O-AGENT-YAML", "P1", "OFFICIAL-NONCOMPLIANT", "Subagent frontmatter is malformed", err,
                     [self.ev(p, 1)], OFFICIAL["subagents"], "confirmed")
            return
        for required in ("name", "description"):
            if not isinstance(fm.get(required), str) or not str(fm.get(required)).strip():
                self.add(f"O-AGENT-{required.upper()}", "P1", "OFFICIAL-NONCOMPLIANT", f"Subagent is missing required `{required}`",
                         "Current official subagent docs require both `name` and `description`.", [self.ev(p, 1)], OFFICIAL["subagents"], "confirmed")
        tools = self.as_list(fm.get("tools"))
        self.agent_tools[p] = tools
        if "tools" not in fm:
            self.add("R-AGENT-INHERIT", "P2", "SECURITY-RISK", "Subagent inherits the main conversation's tool set",
                     "This is documented behavior and not noncompliance. For sensitive roles, review whether inheritance violates least privilege.",
                     [self.ev(p, 1)], OFFICIAL["subagents"])
        if any(x.startswith("Agent(") or x == "Agent" for x in tools):
            self.add("A-AGENT-NEST", "P3", "OPTIMIZATION", "Agent tool appears in a subagent tool list",
                     "Official docs state subagents cannot spawn other subagents, so Agent(agent_type) restrictions do not create nested delegation there. Review whether this entry is meaningful.",
                     [self.ev(p, 1)], OFFICIAL["subagents"])
        task_hits = self.regex_evidence(p, TASK_TOKEN)
        if task_hits:
            self.add("A-AGENT-TASK", "P3", "OPTIMIZATION", "Legacy Task terminology appears in subagent definition",
                     "Current Claude Code uses Agent; Task references remain aliases for compatibility.", task_hits, OFFICIAL["subagents"], "confirmed")
        mcp = []
        for i, line in enumerate(body.splitlines(), body_line):
            if MCP_NAME.search(line):
                mcp.append(self.ev(p, i, line))
        if mcp:
            self.add("P-AGENT-PHYS", "P2", "PORTABILITY-RISK", "Subagent prompt body repeats physical MCP identifiers",
                     "Exact physical names may be required in the `tools` surface, but duplicating them in prose increases drift when bindings change.", mcp[:10])

    def scan_command(self, p: Path) -> None:
        self.add("O-COMMAND-LEGACY", "P3", "OFFICIAL-LEGACY", "Legacy custom-command format is in use",
                 "`.claude/commands/` remains supported, but current Agent SDK documentation calls it the legacy format and recommends Skills for new reusable workflows.",
                 [self.ev(p, 1)], OFFICIAL["commands_sdk"], "confirmed")

    def scan_output_style(self, p: Path) -> None:
        fm, body, _line, err = self.parse_frontmatter(p)
        if err:
            self.add("O-STYLE-YAML", "P2", "OFFICIAL-NONCOMPLIANT", "Output-style frontmatter is malformed", err,
                     [self.ev(p, 1)], OFFICIAL["output_styles"])
        if MCP_NAME.search(body):
            self.add("R-STYLE-TOOLS", "P2", "MAINTAINABILITY-RISK", "Output style contains physical tool integration details",
                     "Official output-style guidance positions this feature for role/tone/default response format, not project tool integration policy.",
                     self.regex_evidence(p, MCP_NAME), OFFICIAL["output_styles"])

    def scan_mcp(self, p: Path) -> None:
        # Parse done earlier. Explicitly avoid flagging ${VAR}: this is supported syntax.
        txt = self.read(p)
        if re.search(r'(?i)"(?:authorization|x-api-key|api-key)"\s*:\s*"(?![^"\n]*\$\{)[^"\n]+"', txt):
            self.add("R-MCP-CREDENTIAL", "P1", "SECURITY-RISK", "MCP credential-like header may be hard-coded",
                     "Official examples support environment placeholders in `.mcp.json`. Review whether this value should come from the environment/secret provider.",
                     [self.find_line(p, "Authorization")], OFFICIAL["mcp"])

    def scan_settings(self, p: Path, data: dict[str, Any]) -> None:
        txt = self.read(p)
        for ev in self.regex_evidence(p, SINGLE_SLASH_HOST_PATH):
            self.add("O-PERM-ABS", "P1", "OFFICIAL-SEMANTIC-ERROR", "Single-leading-slash permission rule looks like an intended host absolute path",
                     "Current official permission syntax uses `//path` for filesystem-root absolute paths; `/path` is anchored to the settings source.",
                     [ev], OFFICIAL["permissions"], "confirmed")
        ignored = self.regex_evidence(p, PATH_QUALIFIED_IGNORED_TOOL)
        if ignored:
            self.add("O-PERM-PATH-TOOL", "P1", "OFFICIAL-SEMANTIC-ERROR", "Path-qualified permission rule uses a tool current docs do not consult for path matching",
                     "Current official docs say file path permission rules are checked with Read/Edit; path-qualified Write/Glob/NotebookEdit/legacy MultiEdit rules are accepted but not consulted as intended path rules in current documented behavior.",
                     ignored, OFFICIAL["permissions"])
        perms = data.get("permissions") if isinstance(data, dict) else None
        if isinstance(perms, dict):
            allow = [x for x in (perms.get("allow") or []) if isinstance(x, str)]
            for rule in allow:
                if BROAD_MCP_ALLOW.match(rule):
                    self.add("R-MCP-WILDCARD", "P1", "SECURITY-RISK", "Broad MCP wildcard is pre-approved",
                             "MCP wildcards are documented and valid, but future tools under the same server can inherit approval. Review least privilege for high-risk providers.",
                             [self.find_line(p, rule)], OFFICIAL["permissions"])
                if BROAD_SHELL_ALLOW.match(rule):
                    self.add("R-SHELL-WIDE", "P1", "SECURITY-RISK", "Broad shell/tool pre-approval has a large capability surface",
                             "This rule may expose more filesystem/process behavior than a narrow deterministic command. Review exact need and sandbox coverage.",
                             [self.find_line(p, rule)])
            if perms.get("defaultMode") == "bypassPermissions":
                self.add("R-BYPASS", "P1", "SECURITY-RISK", "Project uses bypassPermissions",
                         "Official docs warn that bypassPermissions auto-approves all tool uses; allow lists do not constrain it. Confirm strong external containment and explicit denies/hooks.",
                         [self.find_line(p, "bypassPermissions")], OFFICIAL["sdk_permissions"])
        hooks = data.get("hooks") if isinstance(data, dict) else None
        if isinstance(hooks, dict):
            self.scan_hooks_config(p, hooks)

    def scan_hooks_config(self, p: Path, hooks: dict[str, Any]) -> None:
        for event, groups in hooks.items():
            if not isinstance(groups, list):
                continue
            matchers = []
            for group in groups:
                if not isinstance(group, dict):
                    continue
                matchers.append(str(group.get("matcher", "")))
                handlers = group.get("hooks")
                if not isinstance(handlers, list):
                    continue
                for h in handlers:
                    if not isinstance(h, dict) or h.get("type") != "command":
                        continue
                    cmd = str(h.get("command", ""))
                    args = h.get("args")
                    if HOOK_PLACEHOLDER.search(cmd) and args is None:
                        self.add("A-HOOK-EXECFORM", "P3", "OPTIMIZATION", "Hook path placeholder uses shell form",
                                 "Current official hook docs recommend setting `args` when path placeholders are referenced so exec form avoids shell quoting/tokenization issues, unless shell behavior is intentional.",
                                 [self.find_line(p, cmd[:50])], OFFICIAL["hooks"])
                    self.scan_referenced_hook_script(p, cmd, args)
            if event == "PreToolUse" and len(matchers) > 1 and any(m in {"", ".*", "*"} for m in matchers):
                self.add("R-HOOK-OVERLAP", "P2", "MAINTAINABILITY-RISK", "Catch-all and narrower PreToolUse hooks coexist",
                         "Multiple matching hooks can participate in the same event. Ensure security decisions do not rely on a human-assumed serial order and that handlers are independent/idempotent.",
                         [self.find_line(p, '"PreToolUse"')], OFFICIAL["hooks"])

    def scan_referenced_hook_script(self, settings_path: Path, cmd: str, args: Any) -> None:
        tokens: list[str] = []
        expanded_command = cmd.replace("${CLAUDE_PROJECT_DIR}", str(self.root))
        try:
            tokens.extend(shlex.split(expanded_command, posix=True))
        except ValueError:
            pass
        if isinstance(args, list):
            tokens.extend(str(x) for x in args)
        for token in tokens:
            # Resolve only project-root placeholders and obvious relative paths; never execute.
            normalized = token.replace("${CLAUDE_PROJECT_DIR}", str(self.root)).strip().strip('"\'')
            candidates: list[Path] = []
            raw_candidate = Path(normalized)
            if raw_candidate.is_absolute():
                candidates.append(raw_candidate)
            elif normalized.startswith("./"):
                candidates.append(self.root / normalized[2:])
            for c in candidates:
                try:
                    resolved = c.resolve(strict=True)
                except (OSError, RuntimeError, ValueError):
                    continue
                authorized = False
                for allowed_root in [self.root, *([self.claude_dir] if self.claude_dir is not None else [])]:
                    try:
                        resolved.relative_to(allowed_root)
                        authorized = True
                        break
                    except ValueError:
                        continue
                if authorized and resolved.is_file() and resolved.suffix in {".py", ".sh", ".js", ".mjs", ".cjs", ".ts", ".ps1"}:
                    if self.claude_dir is not None:
                        try:
                            logical = Path(".claude") / resolved.relative_to(self.claude_dir)
                            self.logical_paths[resolved] = logical.as_posix()
                        except ValueError:
                            pass
                    self.scan_hook_script(resolved)

    def scan_hook_script(self, p: Path) -> None:
        txt = self.read(p)
        lines = txt.splitlines()
        if len(lines) > 1000:
            self.add("R-HOOK-SIZE", "P2", "MAINTAINABILITY-RISK", "Hook script contains a large policy/runtime implementation",
                     f"{self.rel(p)} has {len(lines)} lines. Consider extracting policy/state/schema logic into separately tested runtime modules and keeping the hook adapter thin.",
                     [self.ev(p, 1)])
        mcp = self.regex_evidence(p, MCP_NAME)
        if mcp:
            self.add("P-HOOK-PHYS", "P2", "PORTABILITY-RISK", "Hook hard-codes physical MCP tool names",
                     "Review whether a stable capability/binding registry can localize provider-specific names without weakening exact runtime authorization.", mcp)
        # Conservative fail-open heuristic.
        for i, line in enumerate(lines, 1):
            if re.search(r"except\s+(?:Exception|BaseException)\b", line):
                window = "\n".join(lines[i-1:min(len(lines), i+12)])
                if re.search(r"\breturn\s+(?:True|0|None)\b|sys\.exit\(0\)", window):
                    self.add("R-HOOK-FAILOPEN", "P1", "SECURITY-RISK", "Security hook may fail open after a broad exception",
                             "Broad exception handling near an apparent success/allow return needs manual control-flow validation. Critical guard errors should normally block rather than silently allow.",
                             [self.ev(p, i, line)])
                    break
        if "argument_resolution_status" in txt and re.search(r"!=\s*[\"']ready[\"'][\s\S]{0,300}?return\s+True", txt):
            self.add("R-HOOK-UNRESOLVED", "P1", "SECURITY-RISK", "Frozen-argument guard may allow unresolved state",
                     "In a frozen-plan security model, unresolved/unknown argument state usually needs explicit fail-closed handling. Confirm project intent and add a regression case.",
                     [self.find_line(p, "argument_resolution_status")])
        if re.search(r"get_trace\|cleanup|\(get_trace\|cleanup\)", txt):
            self.add("R-HOOK-TRACE-CLEAN", "P1", "SECURITY-RISK", "Diagnostic trace-read and cleanup share a gate",
                     "Read-only diagnostics and runtime-owned cleanup usually have different authorization/lifecycle semantics. Review them separately.",
                     self.regex_evidence(p, re.compile(r"get_trace.*cleanup|cleanup.*get_trace"), 4))

    def scan_sdk_semantics(self) -> None:
        if self.runtime_mode not in {"agent-sdk", "both"}:
            return
        explicit_sources = []
        allowed_without_lockdown = []
        bypass_combo = []
        for p in self.sdk_files:
            txt = self.read(p)
            for i, line in enumerate(txt.splitlines(), 1):
                if re.search(r"setting_sources\s*=|settingSources\s*:", line):
                    explicit_sources.append(self.ev(p, i, line))
                if re.search(r"allowed_tools\s*=|allowedTools\s*:", line):
                    # File-level heuristic: no dontAsk near same config block.
                    chunk = txt[max(0, txt.find(line)-1000): txt.find(line)+2000]
                    if "dontAsk" not in chunk and "can_use_tool" not in chunk and "canUseTool" not in chunk:
                        allowed_without_lockdown.append(self.ev(p, i, line))
                if "bypassPermissions" in line:
                    if re.search(r"allowed_tools|allowedTools", txt):
                        bypass_combo.append(self.ev(p, i, line))
        if allowed_without_lockdown:
            self.add("O-SDK-ALLOWLIST", "P1", "OFFICIAL-SEMANTIC-ERROR", "SDK allowedTools may be treated as a restrictive allowlist without a denying permission mode/callback",
                     "Official SDK docs state allowedTools adds pre-approval; unlisted tools fall through to the permission mode/callback. Validate the effective permission flow.",
                     allowed_without_lockdown[:8], OFFICIAL["sdk_permissions"])
        if bypass_combo:
            self.add("O-SDK-BYPASS", "P1", "OFFICIAL-SEMANTIC-ERROR", "SDK allowlist assumptions may be invalid under bypassPermissions",
                     "Official docs state allowedTools does not constrain bypassPermissions; use disallowed tools/deny rules/hooks for operations that must remain blocked.",
                     bypass_combo[:6], OFFICIAL["sdk_permissions"])
        # If project config exists, explicit source expressions deserve manual verification.
        project_config_exists = any((self.root / x).exists() for x in ["CLAUDE.md", ".claude/settings.json", ".mcp.json", ".claude/skills"])
        if project_config_exists and explicit_sources:
            self.add("A-SDK-SOURCES", "P2", "UNVERIFIED", "Agent SDK explicitly sets filesystem setting sources",
                     "Explicit settingSources/setting_sources changes which project/user/local configuration loads. Verify that `project` is present wherever project CLAUDE.md/settings/Skills/.mcp.json are expected. Static text alone may not resolve dynamically constructed options.",
                     explicit_sources[:8], OFFICIAL["sdk_features"])

    def cross_file_checks(self) -> None:
        for p, tools in self.agent_tools.items():
            for tool in tools:
                if tool in self.project_deny_rules:
                    evs = [self.find_line(p, tool)]
                    for sp, _ in self.settings:
                        if tool in self.read(sp):
                            evs.append(self.find_line(sp, tool))
                    self.add("X-REQUIRED-DENY", "P0", "SECURITY-RISK", "Subagent-declared tool is globally denied",
                             "A configured agent tool surface and project deny rule directly contradict each other. Determine whether this is an intentionally retired path or an unreachable intended workflow.",
                             evs, confidence="confirmed")
        # Duplicate command/Skill slash names.
        commands: dict[str, Path] = {}
        skills: dict[str, Path] = {}
        for p in self.files:
            typ = self.classify(p)
            if typ == "command":
                commands[p.stem] = p
            elif typ == "skill":
                fm, _, _, _ = self.parse_frontmatter(p)
                name = str(fm.get("name") or p.parent.name)
                skills[name] = p
        for name in sorted(set(commands) & set(skills)):
            self.add("X-CMD-SKILL-DUP", "P2", "MAINTAINABILITY-RISK", "Legacy command and Skill define the same slash name",
                     f"Both entries can create `/{name}`. Keep one canonical implementation or document the compatibility behavior.",
                     [self.ev(commands[name], 1), self.ev(skills[name], 1)], OFFICIAL["skills"], "confirmed")

    def run(self) -> dict[str, Any]:
        self.collect_files()
        self.detect_runtime()
        self.discover_eval_assets()
        self.parse_json_configs()
        for p in self.files:
            typ = self.classify(p)
            if typ == "instructions":
                self.scan_instructions(p)
            elif typ == "skill":
                self.scan_skill(p)
            elif typ == "agent":
                self.scan_agent(p)
            elif typ == "command":
                self.scan_command(p)
            elif typ == "output-style":
                self.scan_output_style(p)
            elif typ == "mcp":
                self.scan_mcp(p)
            elif typ == "settings":
                for sp, data in self.settings:
                    if sp == p:
                        self.scan_settings(p, data)
                        break
        self.scan_sdk_semantics()
        self.cross_file_checks()
        order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        self.findings.sort(key=lambda f: (order.get(f.severity, 9), f.cls, f.id, f.evidence[0].path if f.evidence else ""))
        return {
            "requested_target": self.requested_target,
            "target": str(self.root),
            "target_kind": self.target_kind,
            "runtime": self.runtime_mode,
            "claude_version": self.claude_version,
            "runtime_evidence": [asdict(x) for x in self.runtime_evidence],
            "eval_assets": self.eval_assets,
            "findings": [asdict(x) for x in self.findings],
        }


def markdown(result: dict[str, Any]) -> str:
    findings = result["findings"]
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    def visible_text(value: Any) -> str:
        visible: list[str] = []
        for character in str(value):
            codepoint = ord(character)
            if character == "\r":
                visible.append("\\r")
            elif character == "\n":
                visible.append("\\n")
            elif character == "\t":
                visible.append("\\t")
            elif codepoint < 0x20 or codepoint == 0x7F:
                visible.append(f"\\x{codepoint:02x}")
            else:
                visible.append(character)
        return "".join(visible)

    def inline_code(value: Any) -> str:
        raw = visible_text(value)
        longest = max((len(x) for x in re.findall(r"`+", raw)), default=0)
        fence = "`" * (longest + 1)
        padding = " " if raw.startswith("`") or raw.endswith("`") else ""
        return f"{fence}{padding}{raw}{padding}{fence}"

    lines = [
        "# Static configuration scan",
        "",
        f"- Requested target: {inline_code(result['requested_target'])}",
        f"- Normalized target: {inline_code(result['target'])}",
        f"- Target kind: `{result['target_kind']}`",
        f"- Target Claude runtime: `{result['runtime']}`",
        f"- Claude version: `{result['claude_version'] or 'unknown'}`",
        f"- Findings: " + ", ".join(f"{k}={counts.get(k, 0)}" for k in ["P0", "P1", "P2", "P3"]),
        "- This output is a candidate inventory. Validate official findings against current official Claude docs before finalizing a review.",
        "",
        "## Discovered validation assets",
        "",
    ]
    if result["eval_assets"]:
        lines.extend(f"- {inline_code(x)}" for x in result["eval_assets"])
    else:
        lines.append("- None discovered automatically; accept a user-supplied safe eval command if optimization is requested.")
    lines.append("")
    for idx, f in enumerate(findings, 1):
        lines += [
            f"## {idx}. [{f['severity']}] {f['id']} — {visible_text(f['title'])}",
            "",
            f"- Class: `{f['cls']}`",
            f"- Confidence: `{f['confidence']}`",
        ]
        if f.get("official_source"):
            lines.append(f"- Official source: `{f['official_source']}`")
        lines += ["", visible_text(f["message"]), ""]
        for e in f["evidence"]:
            location = f"{e['path']}:{e['line']}"
            lines.append(f"- {inline_code(location)} — {inline_code(e['text'])}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--target",
        default=".",
        help="Claude project/workspace root or its project-level .claude directory; defaults to current directory",
    )
    ap.add_argument("--runtime", choices=["auto", "cli", "agent-sdk", "both", "unknown"], default="auto")
    ap.add_argument("--include-eval-targets", action="store_true", help="Include test/eval directories in review targets (off by default)")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--output", help="Optional output file")
    args = ap.parse_args(argv)

    try:
        target = normalize_target(args.target)
    except TargetValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = ReviewScanner(
        target.root,
        args.runtime,
        args.include_eval_targets,
        requested_target=target.requested_target,
        target_kind=target.target_kind,
        claude_dir=target.claude_dir,
    ).run()
    content = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else markdown(result)
    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
