# Agent Config Reviewer

A portable Skill that can be installed and run in both **Claude Code** and **Codex**. It reviews, validates, and optimizes the **effective configuration system** of a Claude Code project across project instructions, settings, permissions, rules, Skills, subagents, hooks, MCP, commands, output styles, worktrees, and Claude Agent SDK bootstrap code.

Codex is only one host for running this Skill. The review subject remains Claude Code configuration; `AGENTS.md`, `.agents/`, and `.codex/` are not reviewed as Claude configuration.

## Install

Copy the complete Skill package, not only `SKILL.md`.

### Claude Code

Project scope:

```text
<project-root>/.claude/skills/agent-config-reviewer/
```

User scope:

```text
~/.claude/skills/agent-config-reviewer/
```

### Codex

Project scope:

```text
<project-root>/.agents/skills/agent-config-reviewer/
```

User scope:

```text
$HOME/.agents/skills/agent-config-reviewer/
```

You can also ask `$skill-installer` in Codex to install the Skill from GitHub. The Skill is located at this repository's root, so specify the repository, source path `.`, and destination name:

```text
Use $skill-installer to install repository wr5912/claude-code-config-reviewer at path . and name the Skill agent-config-reviewer.
```

`$skill-installer` uses a Codex-managed user Skill directory. Do not also copy the same named Skill into `$HOME/.agents/skills`, because duplicate names can both appear in selectors. Restart Codex if a newly installed Skill does not appear.

The neutral `agent-config-reviewer` name follows portable Agent Skills naming constraints and stays identical in both hosts.

## Invocation and target paths

Claude Code uses `/` for explicit invocation:

```text
/agent-config-reviewer review
/agent-config-reviewer review /path/to/claude-project
/agent-config-reviewer review "/path/with spaces/.claude"
/agent-config-reviewer optimize /path/to/claude-project
/agent-config-reviewer validate /path/to/claude-project
```

Codex uses `$` for explicit invocation:

```text
$agent-config-reviewer review
$agent-config-reviewer review /path/to/claude-project
$agent-config-reviewer review "/path/with spaces/.claude"
$agent-config-reviewer optimize /path/to/claude-project
$agent-config-reviewer validate /path/to/claude-project
```

The input contract is `[review|optimize|validate] [target]`. The operation defaults to `review`; the target defaults to the current working directory only when no target was supplied.

`target` accepts a Claude project root or that project's direct `.claude` directory. `<project>/.claude` is normalized to `<project>` so sibling `CLAUDE.md`, `.mcp.json`, `.worktreeinclude`, and relevant Agent SDK bootstrap code stay in scope. Missing, unreadable, file, user-level `~/.claude`, and host configuration directory `.agents`/`.codex` targets fail explicitly and never fall back to the current directory.

## Safety model

Static review does not execute project hooks or arbitrary project code. Existing tests/evals are treated as validation assets rather than production-configuration targets. Runtime validation is allowed only after a safe non-production/mock/replay harness is identified or supplied by the user.

## Verify the Skill package

```bash
python3 -B scripts/self_check.py
python3 -B -m unittest discover -s tests -v
```

The first command verifies the package manifest, file hashes, dual-host metadata, and target contract. The second covers explicit path normalization, host-configuration isolation, and target Claude runtime detection. Both use only the Python standard library.

## Normative findings and host compatibility

Only current official Anthropic/Claude documentation can support `OFFICIAL-*` findings about Claude configuration. Official OpenAI documentation supports Codex installation, discovery, and invocation compatibility only; it cannot justify a Claude configuration compliance verdict. Security, portability, architecture, and maintainability guidance is labeled separately.

## Package contents

```text
agent-config-reviewer/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
├── scripts/
│   ├── scan_project.py
│   └── self_check.py
├── evals/
├── templates/
├── tests/
├── LICENSE
├── PACKAGE-MANIFEST.json
├── README.md
└── README_en.md
```

## Bundled official baseline

The bundled Claude configuration source baseline and dual-host installation contract were rechecked on **2026-08-13**. Claude Code and Codex both change quickly. When network access is available, refresh version-sensitive claims from each product's current official documentation. Claude configuration findings that cannot be verified must be marked `UNVERIFIED` rather than asserted as violations.
