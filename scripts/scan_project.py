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
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

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
EVAL_DIR_NAMES = {
    "test", "tests", "__tests__", "spec", "specs", "eval", "evals", "evaluation",
    "evaluations", "benchmark", "benchmarks",
}
TEXT_EXTENSIONS = {
    ".md", ".json", ".jsonc", ".yaml", ".yml", ".py", ".js", ".mjs", ".cjs",
    ".ts", ".tsx", ".jsx", ".sh", ".ps1", ".toml", ".ini", ".cfg", ".txt",
}
MCP_NAME = re.compile(r"\bmcp__[A-Za-z0-9._-]+__[A-Za-z0-9._*:-]+\b")
SINGLE_SLASH_HOST_PATH = re.compile(r"\b(Read|Edit|Write|Glob|NotebookEdit|MultiEdit)\(/(?:etc|home|Users|var|tmp|opt|srv|data|mnt|root|c/)([^)]*)\)")
PATH_QUALIFIED_IGNORED_TOOL = re.compile(r"\b(Write|Glob|NotebookEdit|MultiEdit)\([^)]*[/*~][^)]*\)")
TASK_TOKEN = re.compile(r"\bTask(?:\(|\b)")
HOOK_PLACEHOLDER = re.compile(r"\$\{CLAUDE_(?:PROJECT_DIR|PLUGIN_ROOT|PLUGIN_DATA)\}")
BROAD_MCP_ALLOW = re.compile(r"^mcp__[A-Za-z0-9._-]+__(?:\*|.+\*)$")
BROAD_SHELL_ALLOW = re.compile(r"^(?:Bash|PowerShell)\((?:bash|sh|python|python3|node|perl|ruby|env|printenv|cat|find|jq) \*\)$")


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
    def __init__(self, root: Path, runtime: str, include_eval_targets: bool = False):
        self.root = root.resolve()
        self.runtime_requested = runtime
        self.include_eval_targets = include_eval_targets
        self.files: list[Path] = []
        self.text: dict[Path, str] = {}
        self.findings: list[Finding] = []
        self.settings: list[tuple[Path, dict[str, Any]]] = []
        self.project_deny_rules: set[str] = set()
        self.agent_tools: dict[Path, list[str]] = {}
        self.runtime_mode = "unknown"
        self.runtime_evidence: list[Evidence] = []
        self.eval_assets: list[str] = []
        self.claude_version = self.detect_claude_version()

    def detect_claude_version(self) -> str | None:
        exe = shutil.which("claude")
        if not exe:
            return None
        try:
            cp = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=3, check=False)
            out = (cp.stdout or cp.stderr or "").strip()
            return out[:200] if out else None
        except Exception:
            return None

    def rel(self, p: Path) -> str:
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

    def collect_files(self) -> None:
        for base, dirs, names in os.walk(self.root, followlinks=False):
            b = Path(base)
            keep_dirs = []
            for d in dirs:
                if d in BUILD_DIRS:
                    continue
                if not self.include_eval_targets and d.lower() in EVAL_DIR_NAMES:
                    continue
                keep_dirs.append(d)
            dirs[:] = keep_dirs
            for name in names:
                p = b / name
                if p.is_symlink():
                    continue
                try:
                    if p.stat().st_size > 5 * 1024 * 1024:
                        continue
                except OSError:
                    continue
                if p.suffix in TEXT_EXTENSIONS or name in {
                    "CLAUDE.md", "CLAUDE.local.md", ".mcp.json", ".worktreeinclude", "Makefile"
                }:
                    self.files.append(p)

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

    def detect_runtime(self) -> None:
        sdk_hits: list[Evidence] = []
        cli_hits: list[Evidence] = []
        patterns = [
            re.compile(r"\bclaude_agent_sdk\b"),
            re.compile(r"@anthropic-ai/claude-agent-sdk"),
            re.compile(r"\bClaudeAgentOptions\b"),
            re.compile(r"\bsetting_sources\b|\bsettingSources\b"),
        ]
        for p in self.files:
            if self.classify(p) != "other":
                continue
            txt = self.read(p)
            if any(rx.search(txt) for rx in patterns):
                for i, line in enumerate(txt.splitlines(), 1):
                    if any(rx.search(line) for rx in patterns):
                        sdk_hits.append(self.ev(p, i, line))
                        if len(sdk_hits) >= 8:
                            break
            if re.search(r"\bclaude\s+(?:-p|--print|--agent|--worktree)\b", txt):
                cli_hits.append(self.find_line(p, "claude"))
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
        for base, dirs, _names in os.walk(self.root, followlinks=False):
            b = Path(base)
            dirs[:] = [d for d in dirs if d not in BUILD_DIRS]
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
        if isinstance(args, list):
            tokens.extend(str(x) for x in args)
        tokens.append(cmd)
        for token in tokens:
            # Resolve only project-root placeholders and obvious relative paths; never execute.
            normalized = token.replace("${CLAUDE_PROJECT_DIR}", str(self.root)).strip().strip('"\'')
            candidates = []
            if normalized.startswith(str(self.root)):
                candidates.append(Path(normalized))
            elif normalized.startswith("./"):
                candidates.append(self.root / normalized[2:])
            for c in candidates:
                if c.is_file() and c.suffix in {".py", ".sh", ".js", ".mjs", ".cjs", ".ts", ".ps1"}:
                    self.scan_hook_script(c)

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
        sdk_files = []
        for p in self.files:
            if self.classify(p) != "other":
                continue
            txt = self.read(p)
            if re.search(r"claude_agent_sdk|@anthropic-ai/claude-agent-sdk|ClaudeAgentOptions", txt):
                sdk_files.append(p)
        explicit_sources = []
        allowed_without_lockdown = []
        bypass_combo = []
        for p in sdk_files:
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
            "target": str(self.root),
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
    lines = [
        "# Static configuration scan",
        "",
        f"- Target: `{result['target']}`",
        f"- Runtime: `{result['runtime']}`",
        f"- Claude version: `{result['claude_version'] or 'unknown'}`",
        f"- Findings: " + ", ".join(f"{k}={counts.get(k, 0)}" for k in ["P0", "P1", "P2", "P3"]),
        "- This output is a candidate inventory. Validate official findings against current official Claude docs before finalizing a review.",
        "",
        "## Discovered validation assets",
        "",
    ]
    if result["eval_assets"]:
        lines.extend(f"- `{x}`" for x in result["eval_assets"])
    else:
        lines.append("- None discovered automatically; accept a user-supplied safe eval command if optimization is requested.")
    lines.append("")
    for idx, f in enumerate(findings, 1):
        lines += [
            f"## {idx}. [{f['severity']}] {f['id']} — {f['title']}",
            "",
            f"- Class: `{f['cls']}`",
            f"- Confidence: `{f['confidence']}`",
        ]
        if f.get("official_source"):
            lines.append(f"- Official source: `{f['official_source']}`")
        lines += ["", f["message"], ""]
        for e in f["evidence"]:
            safe = e["text"].replace("`", "\\`")
            lines.append(f"- `{e['path']}:{e['line']}` — `{safe}`")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=".", help="Project/workspace root; defaults to current directory")
    ap.add_argument("--runtime", choices=["auto", "cli", "agent-sdk", "both", "unknown"], default="auto")
    ap.add_argument("--include-eval-targets", action="store_true", help="Include test/eval directories in review targets (off by default)")
    ap.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--output", help="Optional output file")
    args = ap.parse_args()

    root = Path(args.target)
    if not root.is_dir():
        print(f"Target must be a directory: {root}", file=sys.stderr)
        return 2
    result = ReviewScanner(root, args.runtime, args.include_eval_targets).run()
    content = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else markdown(result)
    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
