# Agent Config Reviewer

A portable Claude Code project Skill for reviewing, validating, and optimizing the **effective configuration system** across project instructions, settings, permissions, rules, Skills, subagents, hooks, MCP, commands, output styles, worktrees, and Claude Agent SDK bootstrap code.

## Install

Project scope:

```text
<project-root>/.claude/skills/agent-config-reviewer/
```

User scope:

```text
~/.claude/skills/agent-config-reviewer/
```

The Skill intentionally uses the name `agent-config-reviewer` rather than putting `claude` in the Skill name so the package follows Anthropic Agent Skills naming constraints while still reviewing Claude Code configuration.

## Invocation examples

```text
/agent-config-reviewer review
/agent-config-reviewer review current project configuration
/agent-config-reviewer optimize the configuration and validate with the existing safe eval harness
/agent-config-reviewer validate the last configuration change
```

The Skill does **not** require a particular repository layout. It starts from the current project/workspace and discovers documented Claude Code locations. It does not assume `workspace/`, `/data`, a particular tests directory, a particular runtime wrapper, or any named platform/product.

## Safety model

Static review does not execute project hooks or arbitrary project code. Existing tests/evals are treated as validation assets rather than production-configuration targets. Runtime validation is allowed only after a safe non-production/mock/replay harness is identified or supplied by the user.

## Normative versus advisory findings

Only current official Anthropic/Claude documentation can support `OFFICIAL-*` findings. Security, portability, architecture, and maintainability guidance is clearly labeled separately. Community methods such as bounded edits, paired comparison, accepted/rejected remediation memory, and validation-gated optimization are used only as non-normative optimization techniques.

## Package contents

```text
agent-config-reviewer/
├── SKILL.md
├── README.md
├── references/
│   ├── official-compliance.md
│   ├── config-responsibility-matrix.md
│   ├── check-catalog.md
│   ├── review-methodology.md
│   ├── remediation-patterns.md
│   ├── eval-harness.md
│   ├── optimization-loop.md
│   └── non-normative-inspirations.md
├── scripts/
│   ├── scan_project.py
│   └── self_check.py
├── evals/
│   └── cases.json
└── templates/
    └── review-report.md
```

## Bundled official baseline

The bundled official-source baseline was rechecked on **2026-08-13**. Claude Code changes quickly. When network access is available, the reviewer should refresh version-sensitive claims from current official documentation before making a compliance verdict. When that cannot be done, version-sensitive findings must be marked `UNVERIFIED` rather than asserted as violations.
