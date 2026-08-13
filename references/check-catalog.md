# Review check catalog

This Markdown file is the sole authoritative catalog. Every check bullet has a
stable ID and one primary owner: `SCANNER` for deterministic extraction,
`REVIEWER` for evidence-based judgment, or `LIVE` for behavior that requires a
safe runtime observation. Explanatory notes must be paragraphs, not list items.

Only checks linked to `official-compliance.md` can produce `OFFICIAL-*`
findings.

## A. Runtime / loading

- [A-001] [REVIEWER] Record the host agent separately from the target Claude runtime.
- [A-002] [SCANNER] Resolve an explicit project root or project-local `.claude` target and echo its normalized root.
- [A-003] [SCANNER] Reject invalid explicit targets without falling back to cwd.
- [A-004] [SCANNER] Exclude `.agents/` and `.codex/` host configuration from Claude findings and runtime detection.
- [A-005] [SCANNER] Detect CLI versus Agent SDK versus both.
- [A-006] [SCANNER] Locate SDK bootstrap and effective `cwd`.
- [A-007] [SCANNER] Inspect explicit `settingSources` / `setting_sources`.
- [A-008] [REVIEWER] Confirm project source is loaded when project settings/Skills/MCP are expected.
- [A-009] [SCANNER] Inspect SDK `skills`, `tools`, `allowedTools`, `disallowedTools`, permission mode, `canUseTool`, hooks, MCP configuration, system-prompt mode.
- [A-010] [REVIEWER] Flag reliance on implicit user/local config when reproducibility is a requirement.
- [A-011] [SCANNER] Default the runtime root to the normalized Claude project root and echo both roots.
- [A-012] [SCANNER] Resolve an explicit external runtime root without allowing it to redefine the Claude configuration root or `${CLAUDE_PROJECT_DIR}`.
- [A-013] [SCANNER] Reject an invalid explicit runtime root without falling back to the target or cwd.

## B. CLAUDE.md / rules

- [B-001] [REVIEWER] Is always-on content project-wide and stable?
- [B-002] [REVIEWER] Are task-specific multi-step procedures better represented as Skills?
- [B-003] [REVIEWER] Are path-specific rules scoped rather than loaded globally?
- [B-004] [REVIEWER] Are hard security requirements backed by enforcement?
- [B-005] [REVIEWER] Are the same rules duplicated in CLAUDE.md, rules, Skills, agents, hooks, and runtime code?
- [B-006] [REVIEWER] Are provider/product implementation names unnecessarily embedded in model-facing reusable context?
- [B-007] [REVIEWER] Are dynamic session facts incorrectly baked into static instructions?

## C. Skills

- [C-001] [SCANNER] Validate Claude Code frontmatter semantics and portable Agent Skills naming guidance.
- [C-002] [REVIEWER] Description says what the Skill does and when to use it.
- [C-003] [REVIEWER] Progressive disclosure; supporting resources are only loaded when needed.
- [C-004] [SCANNER] `disable-model-invocation` and `user-invocable` match intended invocation.
- [C-005] [REVIEWER] `allowed-tools` is not treated as a restrictive allowlist.
- [C-006] [REVIEWER] In Agent SDK, SKILL.md `allowed-tools` is not treated as effective SDK authorization.
- [C-007] [REVIEWER] `context: fork` Skills have explicit actionable input and do not rely on invisible conversation state.
- [C-008] [REVIEWER] High-risk workflow is not automatically invoked unless explicitly intended and safely gated.
- [C-009] [REVIEWER] Physical MCP names are not repeated unnecessarily through prose.

## D. Subagents

- [D-001] [SCANNER] `name` and `description` present and valid.
- [D-002] [REVIEWER] `tools` omission/inheritance is intentional.
- [D-003] [REVIEWER] Exact/narrow tools for sensitive roles.
- [D-004] [SCANNER] `disallowedTools` does not contradict required tools.
- [D-005] [REVIEWER] `skills` preloading is limited to relevant knowledge.
- [D-006] [REVIEWER] No assumption that a subagent can spawn another subagent.
- [D-007] [REVIEWER] `Task` compatibility aliases are identified as legacy terminology, not treated as invalid.
- [D-008] [REVIEWER] `permissionMode` is compatible with parent mode and intended unattended behavior.
- [D-009] [REVIEWER] MCP server exposure is scoped where possible.

## E. Settings / permissions

- [E-001] [SCANNER] JSON parses.
- [E-002] [SCANNER] Permission path syntax matches documented anchors (`//`, `~/`, `/`, relative).
- [E-003] [REVIEWER] Do not use path-qualified Write/Glob/etc. where current docs say only Read/Edit path rules are consulted.
- [E-004] [REVIEWER] `allow`/`allowedTools` is not mistaken for a restrictive capability surface.
- [E-005] [REVIEWER] `bypassPermissions` does not undermine an assumed allowlist.
- [E-006] [REVIEWER] Broad Bash/PowerShell approvals are justified.
- [E-007] [REVIEWER] Broad MCP server wildcards are risk-assessed for future tool growth.
- [E-008] [REVIEWER] Deny rules do not make a required official workflow unreachable.
- [E-009] [REVIEWER] Local/user/project precedence/loading assumptions are explicit.

## F. Sandbox / isolation

- [F-001] [LIVE] Claimed file/network isolation matches actual sandbox/container configuration.
- [F-002] [REVIEWER] Built-in Read/Edit denies are not assumed to block arbitrary subprocess I/O.
- [F-003] [LIVE] Any unsandboxed fallback is intentional.
- [F-004] [REVIEWER] Side-effect validation does not rely on model refusal alone.
- [F-005] [REVIEWER] Worktree isolation is used where concurrent editing risk warrants it.

## G. MCP

- [G-001] [SCANNER] `.mcp.json` parses.
- [G-002] [SCANNER] Environment placeholders are treated as supported syntax, not an error.
- [G-003] [SCANNER] Credentials are not unnecessarily hard-coded.
- [G-004] [REVIEWER] Server/tool names are understood as physical binding identifiers.
- [G-005] [REVIEWER] Agent SDK loads `project` source if `.mcp.json` is expected.
- [G-006] [REVIEWER] High-risk servers are not overexposed to parents/subagents unnecessarily.
- [G-007] [REVIEWER] Provider/tool rename impact is localized where feasible.

## H. Hooks

- [H-001] [SCANNER] Hook type/event/matcher fields align with current official reference.
- [H-002] [SCANNER] Command path placeholders use current exec-form guidance where applicable.
- [H-003] [REVIEWER] Security-critical hooks fail closed on malformed/missing/unexpected state.
- [H-004] [SCANNER] No broad `except` path silently turns a policy-engine failure into allow.
- [H-005] [REVIEWER] PreToolUse decisions are independent of assumed handler ordering.
- [H-006] [REVIEWER] PostToolUse is not expected to undo an already executed action.
- [H-007] [REVIEWER] Static context is not repeatedly injected via SessionStart when CLAUDE.md is sufficient.
- [H-008] [REVIEWER] Hook scripts are thin adapters when possible; large policy engines get their own tested runtime module.
- [H-009] [LIVE] Trust decisions use runtime-authenticated metadata, not user prose.
- [H-010] [REVIEWER] Review every capability-bearing Route transition and alternate path, not only the happy path.
- [H-011] [REVIEWER] State stores declare authority, tenant/session/request binding, lifecycle/TTL, concurrency, integrity, and failure behavior.
- [H-012] [LIVE] Critical state transitions are verified under missing, malformed, stale, and concurrent state without relying on business-specific field names.
- [H-013] [REVIEWER] Capability effects are explicit; unknown or unbounded reads, writes, execution, external I/O, and authority changes remain `UNVERIFIED`.

## I. Commands

- [I-001] [SCANNER] `.claude/commands/` is recognized as supported legacy format.
- [I-002] [REVIEWER] New reusable workflows prefer Skills.
- [I-003] [REVIEWER] Legacy commands retained as thin aliases do not duplicate policy/SOP content.
- [I-004] [REVIEWER] Duplicate slash names between command and Skill are intentional.

## J. Output styles

- [J-001] [REVIEWER] Used for response role/tone/default format.
- [J-002] [REVIEWER] Project architecture/security policy is not hidden here.
- [J-003] [REVIEWER] `keep-coding-instructions` is evaluated against actual role, not mandated blindly.

## K. Worktrees / memory

- [K-001] [REVIEWER] `.worktreeinclude` behavior is understood; secret copying is intentional.
- [K-002] [REVIEWER] Worktree isolation matches concurrent modification risk.
- [K-003] [REVIEWER] Persistent subagent memory does not become an uncontrolled source of policy/security truth.
- [K-004] [REVIEWER] Stable rules promoted into governed configuration rather than left only in learned memory when reproducibility matters.

## L. Custom project extensions

- [L-001] [SCANNER] Identify custom manifests/registries/lifecycle files only through project discovery.
- [L-002] [REVIEWER] Require project-owned schema/version/validator before calling them machine contracts.
- [L-003] [REVIEWER] Never call a custom file “Claude noncompliant” unless it contains or generates official Claude configuration that violates current docs.
- [L-004] [REVIEWER] Separate logical capability declarations from physical provider/tool binding when portability matters.

## M. Cross-file contradictions

- [M-001] [REVIEWER] Required tool vs global deny.
- [M-002] [REVIEWER] Parent capability bypassing mandatory delegation.
- [M-003] [REVIEWER] Prompt says read-only while tool surface includes operational side effects.
- [M-004] [REVIEWER] New and retired tool/workflow names simultaneously authoritative.
- [M-005] [LIVE] Approval owner/trust source named in prompt but not verified by runtime.
- [M-006] [REVIEWER] Output contract demanded in prose but not validated where machine consumption requires strict structure.
- [M-007] [REVIEWER] Hooks/settings/sandbox enforce different versions of the same policy.

## N. Evaluation readiness

- [N-001] [SCANNER] Existing test/eval command discovered rather than assumed.
- [N-002] [LIVE] Runtime harness actually loads the same project sources/settings as production intent.
- [N-003] [SCANNER] Critical gates have deterministic assertions.
- [N-004] [REVIEWER] Adversarial prompts cover prompt injection and false trust claims.
- [N-005] [REVIEWER] Side-effect tools use mock/replay/test endpoints.
- [N-006] [LIVE] Baseline and candidate use comparable inputs.
- [N-007] [REVIEWER] No new critical regression is hidden by aggregate scoring.
