# Official compliance baseline

This file is the normative source map for the Skill. **Only official Anthropic/Claude documentation may justify an `OFFICIAL-*` finding.** Community repositories and internal conventions are non-normative.

Baseline rechecked: **2026-08-13**.

## Source hierarchy

1. Claude Code / Agent SDK product behavior: `https://code.claude.com/docs/`
2. Agent Skills standard and authoring best practices: `https://platform.claude.com/docs/`
3. If two official pages appear to differ, prefer the page specific to the runtime/product being reviewed and mark ambiguity/version sensitivity explicitly.

## Official rules used by this Skill

### O-001 — Filesystem configuration sources in Agent SDK

Official sources:
- `https://code.claude.com/docs/en/agent-sdk/claude-code-features`
- `https://code.claude.com/docs/en/agent-sdk/typescript`
- Python SDK reference linked from the same Agent SDK documentation family.

Current behavior:
- When `settingSources` / `setting_sources` is omitted, `query()` loads the same filesystem sources as Claude Code CLI: user, project, and local.
- When sources are supplied explicitly, only those selected sources load their corresponding filesystem configuration.
- Project instructions/settings/Skills/MCP that rely on project sources will not be effective if `project` is omitted from an explicit source list.

Review consequence: a project may contain correct `.claude` configuration that is not effective in its SDK runtime.

### O-002 — CLAUDE.md and rules are context, not enforcement

Official source:
- `https://code.claude.com/docs/en/memory`

Current behavior:
- CLAUDE.md provides persistent instructions/context.
- Official docs explicitly describe CLAUDE.md and auto memory as context rather than enforced configuration.
- Multi-step procedures or narrowly scoped instructions should move to Skills or path-scoped rules when appropriate.

Review consequence: do not credit a prompt prohibition as an execution boundary.

### O-003 — Skills and custom commands

Official sources:
- `https://code.claude.com/docs/en/slash-commands`
- `https://code.claude.com/docs/en/agent-sdk/slash-commands`

Current behavior:
- `.claude/skills/<name>/SKILL.md` is the current recommended reusable workflow format.
- `.claude/commands/` remains supported but is explicitly described as the legacy format in Agent SDK documentation.
- A command and Skill can both create slash-command entries; duplicate names should be reviewed for ambiguity/duplication.

Compliance classification: `.claude/commands/` is `OFFICIAL-LEGACY`, not invalid.

### O-004 — Skill `allowed-tools`

Official sources:
- `https://code.claude.com/docs/en/slash-commands`
- `https://code.claude.com/docs/en/agent-sdk/skills`

Current behavior:
- In Claude Code CLI, SKILL.md `allowed-tools` pre-approves listed tools while the Skill is active. It does **not** restrict the set of callable tools; baseline permission settings still govern other tools.
- In Agent SDK, SKILL.md `allowed-tools` is only supported when using Claude Code CLI directly and does **not** apply when Skills are used through the SDK. SDK tool access must be controlled through SDK permission configuration such as `allowedTools`/`allowed_tools` and the permission model.

Review consequence: treating SKILL.md `allowed-tools` as an SDK security allowlist is an `OFFICIAL-SEMANTIC-ERROR`.

### O-005 — SDK `allowedTools` / `allowed_tools` is pre-approval, not intrinsically restrictive

Official source:
- `https://code.claude.com/docs/en/agent-sdk/permissions`

Current behavior:
- `allowedTools`/`allowed_tools` adds allow rules; tools not listed can still fall through to the permission mode/callback.
- For a locked-down unattended agent, official docs show pairing an allow list with `permissionMode: "dontAsk"` so unapproved tools are denied instead of prompting.
- `bypassPermissions` is broader: an allow list does not constrain it. Use deny/disallowed rules and hooks for operations that must remain blocked.

### O-006 — Subagent frontmatter and tool inheritance

Official source:
- `https://code.claude.com/docs/en/sub-agents`

Current behavior:
- Custom subagents require `name` and `description`.
- `tools` is optional; if omitted, the subagent inherits all tools from the main conversation.
- `disallowedTools` removes tools from the inherited/specified pool.
- `Agent(agent_type)` can restrict child types when an agent runs as the main thread with `claude --agent`; subagents themselves cannot spawn subagents.
- The former `Task` tool was renamed to `Agent` in v2.1.63; existing `Task(...)` references remain aliases.

Review consequence: omitted `tools` is not noncompliant, but may be a least-privilege risk.

### O-007 — Skills with `context: fork`

Official source:
- `https://code.claude.com/docs/en/slash-commands`

Current behavior:
- `context: fork` runs the Skill in an isolated subagent context.
- The Skill content becomes the task prompt and the fork does not have the parent conversation history.
- Fork mode only makes sense for Skills with an actionable task/input.

Review consequence: a forked Skill that depends on implicit parent-conversation state is an execution-design risk, not necessarily syntax noncompliance.

### O-008 — Permission path syntax

Official source:
- `https://code.claude.com/docs/en/permissions`

Current behavior for Read/Edit path rules:
- `//path` = absolute filesystem path.
- `~/path` = home-relative.
- `/path` = relative to the settings source anchor, not filesystem root.
- `path` or `./path` = current-directory relative under documented semantics.
- Current docs also state path rules should use `Read(path)` and `Edit(path)`; path-qualified `Write`, `NotebookEdit`, `Glob`, or legacy `MultiEdit` rules are not consulted as path permission rules under current versions documented there.

Review consequence: a single-leading-slash rule intended as host absolute path is an `OFFICIAL-SEMANTIC-ERROR`.

### O-009 — Permissions and PreToolUse hooks

Official sources:
- `https://code.claude.com/docs/en/permissions`
- `https://code.claude.com/docs/en/hooks`

Current behavior:
- Deny/ask permission rules still apply regardless of an allow-like PreToolUse hook decision.
- A blocking PreToolUse hook can block a tool call before normal permission evaluation.
- Hooks are appropriate for deterministic runtime guard/audit logic; PostToolUse cannot undo an action already executed.

### O-010 — Hook command exec form

Official source:
- `https://code.claude.com/docs/en/hooks`

Current behavior:
- Command hooks support `command` plus optional `args`.
- When `args` is present, Claude Code spawns exec form without a shell.
- Current docs say to set `args` whenever a hook references a path placeholder such as `${CLAUDE_PROJECT_DIR}`, unless shell behavior is intentionally required.
- Command hooks execute with the user's permissions and must be reviewed as executable code.

Classification: shell form with path placeholders is usually an official recommendation issue unless it produces an actual semantic/security failure.

### O-011 — SessionStart static context

Official source:
- `https://code.claude.com/docs/en/hooks`

Current behavior:
- `SessionStart` is suitable for dynamic development/session context or environment setup.
- Official docs recommend CLAUDE.md instead for static context that does not require a script.

Classification: optimization/maintainability unless behavior is broken.

### O-012 — MCP configuration and environment variables

Official sources:
- `https://code.claude.com/docs/en/mcp`
- `https://code.claude.com/docs/en/agent-sdk/mcp`

Current behavior:
- Project MCP servers can be configured in `.mcp.json`.
- MCP tools are named `mcp__<server-name>__<tool-name>`.
- `.mcp.json` examples use `${ENV_VAR}` placeholders for environment values and Authorization headers.
- In Agent SDK, project `.mcp.json` depends on the project setting source being loaded.
- SDK `allowedTools` can use exact MCP names or documented server wildcards.

Review consequence: `${VAR}` in `.mcp.json` is normal and should not be flagged as malformed merely for being a placeholder.

### O-013 — Sandbox versus permission rules

Official sources:
- `https://code.claude.com/docs/en/permissions`
- `https://code.claude.com/docs/en/settings`

Current behavior:
- Read/Edit permission rules affect built-in file tooling and recognized Bash file commands on current documented versions, but arbitrary subprocesses can read/write paths indirectly.
- Official docs direct users to sandboxing for OS-level enforcement when subprocess path access must be blocked.

Review consequence: file permission rules alone are not proof of process-level filesystem isolation.

### O-014 — Output styles

Official source:
- `https://code.claude.com/docs/en/output-styles`

Current behavior:
- Output styles modify response/system-prompt behavior such as role, tone, and default format.
- Project conventions and codebase knowledge belong in CLAUDE.md instead.
- `keep-coding-instructions: true` retains Claude Code's built-in software-engineering instructions when desired; omission is intentional for non-coding roles and is not inherently invalid.

### O-015 — Worktree include

Official sources:
- `https://code.claude.com/docs/en/worktrees`
- `https://code.claude.com/docs/en/settings`

Current behavior:
- `.worktreeinclude` uses `.gitignore` syntax and copies matching gitignored files into Claude-created worktrees.
- Official docs explicitly show `.env` and secret-config examples; copying them is supported behavior, not itself noncompliance.

Review consequence: evaluate secret replication as a project security decision, not as a Claude compliance violation.

### O-016 — Agent Skills authoring standard/best practices

Official sources:
- `https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview`
- `https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices`

Current portable Agent Skills guidance includes:
- Skill `name` uses lowercase letters/numbers/hyphens, max 64, and excludes reserved `anthropic`/`claude` names.
- `description` should state what the Skill does and when to use it.
- Keep SKILL.md body under about 500 lines for optimal performance and use progressive disclosure for detail.
- Include evaluations for real usage scenarios.

Important product-specific nuance:
- Claude Code's filesystem Skill docs allow some frontmatter fields to be omitted and can derive the name from the directory. Do not mark a Claude Code Skill invalid solely because it omits `name` if current Claude Code docs still support that behavior.
- This package itself uses the stricter portable Agent Skills naming conventions.

## Version-sensitive verdict rule

When a finding depends on a documented minimum version, changed semantics, renamed tool, or newly introduced field:

1. Determine installed `claude --version` when safely possible.
2. Prefer current official docs for that version/current release.
3. If version cannot be determined or docs conflict, use `UNVERIFIED` and explain the ambiguity.

Never invent a version threshold.
