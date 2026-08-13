# Review check catalog

Use this catalog as a systematic checklist. Only checks linked to `official-compliance.md` can produce `OFFICIAL-*` findings.

## A. Runtime / loading

- Record the host agent separately from the target Claude runtime.
- Resolve an explicit project root or project-local `.claude` target and echo its normalized root.
- Reject invalid explicit targets without falling back to cwd.
- Exclude `.agents/` and `.codex/` host configuration from Claude findings and runtime detection.
- Detect CLI versus Agent SDK versus both.
- Locate SDK bootstrap and effective `cwd`.
- Inspect explicit `settingSources` / `setting_sources`.
- Confirm project source is loaded when project settings/Skills/MCP are expected.
- Inspect SDK `skills`, `tools`, `allowedTools`, `disallowedTools`, permission mode, `canUseTool`, hooks, MCP configuration, system-prompt mode.
- Flag reliance on implicit user/local config when reproducibility is a requirement.

## B. CLAUDE.md / rules

- Is always-on content project-wide and stable?
- Are task-specific multi-step procedures better represented as Skills?
- Are path-specific rules scoped rather than loaded globally?
- Are hard security requirements backed by enforcement?
- Are the same rules duplicated in CLAUDE.md, rules, Skills, agents, hooks, and runtime code?
- Are provider/product implementation names unnecessarily embedded in model-facing reusable context?
- Are dynamic session facts incorrectly baked into static instructions?

## C. Skills

- Validate Claude Code frontmatter semantics and portable Agent Skills naming guidance.
- Description says what the Skill does and when to use it.
- Progressive disclosure; supporting resources are only loaded when needed.
- `disable-model-invocation` and `user-invocable` match intended invocation.
- `allowed-tools` is not treated as a restrictive allowlist.
- In Agent SDK, SKILL.md `allowed-tools` is not treated as effective SDK authorization.
- `context: fork` Skills have explicit actionable input and do not rely on invisible conversation state.
- High-risk workflow is not automatically invoked unless explicitly intended and safely gated.
- Physical MCP names are not repeated unnecessarily through prose.

## D. Subagents

- `name` and `description` present and valid.
- `tools` omission/inheritance is intentional.
- Exact/narrow tools for sensitive roles.
- `disallowedTools` does not contradict required tools.
- `skills` preloading is limited to relevant knowledge.
- No assumption that a subagent can spawn another subagent.
- `Task` compatibility aliases are identified as legacy terminology, not treated as invalid.
- `permissionMode` is compatible with parent mode and intended unattended behavior.
- MCP server exposure is scoped where possible.

## E. Settings / permissions

- JSON parses.
- Permission path syntax matches documented anchors (`//`, `~/`, `/`, relative).
- Do not use path-qualified Write/Glob/etc. where current docs say only Read/Edit path rules are consulted.
- `allow`/`allowedTools` is not mistaken for a restrictive capability surface.
- `bypassPermissions` does not undermine an assumed allowlist.
- Broad Bash/PowerShell approvals are justified.
- Broad MCP server wildcards are risk-assessed for future tool growth.
- Deny rules do not make a required official workflow unreachable.
- Local/user/project precedence/loading assumptions are explicit.

## F. Sandbox / isolation

- Claimed file/network isolation matches actual sandbox/container configuration.
- Built-in Read/Edit denies are not assumed to block arbitrary subprocess I/O.
- Any unsandboxed fallback is intentional.
- Side-effect validation does not rely on model refusal alone.
- Worktree isolation is used where concurrent editing risk warrants it.

## G. MCP

- `.mcp.json` parses.
- Environment placeholders are treated as supported syntax, not an error.
- Credentials are not unnecessarily hard-coded.
- Server/tool names are understood as physical binding identifiers.
- Agent SDK loads `project` source if `.mcp.json` is expected.
- High-risk servers are not overexposed to parents/subagents unnecessarily.
- Provider/tool rename impact is localized where feasible.

## H. Hooks

- Hook type/event/matcher fields align with current official reference.
- Command path placeholders use current exec-form guidance where applicable.
- Security-critical hooks fail closed on malformed/missing/unexpected state.
- No broad `except` path silently turns a policy-engine failure into allow.
- PreToolUse decisions are independent of assumed handler ordering.
- PostToolUse is not expected to undo an already executed action.
- Static context is not repeatedly injected via SessionStart when CLAUDE.md is sufficient.
- Hook scripts are thin adapters when possible; large policy engines get their own tested runtime module.
- Trust decisions use runtime-authenticated metadata, not user prose.

## I. Commands

- `.claude/commands/` is recognized as supported legacy format.
- New reusable workflows prefer Skills.
- Legacy commands retained as thin aliases do not duplicate policy/SOP content.
- Duplicate slash names between command and Skill are intentional.

## J. Output styles

- Used for response role/tone/default format.
- Project architecture/security policy is not hidden here.
- `keep-coding-instructions` is evaluated against actual role, not mandated blindly.

## K. Worktrees / memory

- `.worktreeinclude` behavior is understood; secret copying is intentional.
- Worktree isolation matches concurrent modification risk.
- Persistent subagent memory does not become an uncontrolled source of policy/security truth.
- Stable rules promoted into governed configuration rather than left only in learned memory when reproducibility matters.

## L. Custom project extensions

- Identify custom manifests/registries/lifecycle files only through project discovery.
- Require project-owned schema/version/validator before calling them machine contracts.
- Never call a custom file “Claude noncompliant” unless it contains or generates official Claude configuration that violates current docs.
- Separate logical capability declarations from physical provider/tool binding when portability matters.

## M. Cross-file contradictions

- Required tool vs global deny.
- Parent capability bypassing mandatory delegation.
- Prompt says read-only while tool surface includes operational side effects.
- New and retired tool/workflow names simultaneously authoritative.
- Approval owner/trust source named in prompt but not verified by runtime.
- Output contract demanded in prose but not validated where machine consumption requires strict structure.
- Hooks/settings/sandbox enforce different versions of the same policy.

## N. Evaluation readiness

- Existing test/eval command discovered rather than assumed.
- Runtime harness actually loads the same project sources/settings as production intent.
- Critical gates have deterministic assertions.
- Adversarial prompts cover prompt injection and false trust claims.
- Side-effect tools use mock/replay/test endpoints.
- Baseline and candidate use comparable inputs.
- No new critical regression is hidden by aggregate scoring.
