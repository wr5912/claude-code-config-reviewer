---
name: "agent-config-reviewer"
description: "Review, validate, and optimize a target Claude Code configuration and Claude Agent SDK integration from Claude Code or Codex. Use for audits or remediations involving CLAUDE.md, .claude settings/rules/skills/agents/hooks/commands/output styles, .mcp.json, worktrees, permissions, sandboxing, SDK setting sources, tool surfaces, cross-file reachability, and regression validation."
---

# Agent Config Reviewer

Review the **effective Claude Code configuration system**, not isolated files. Separate official Claude compliance from security/architecture advice, then validate remediations with the project's own safe evaluation assets when available.

## Host and target contract

Run this Skill from either Claude Code or Codex. The host agent only executes the workflow; the review subject remains Claude Code configuration and Claude Agent SDK integration.

Interpret invocation input as:

```text
[review|optimize|validate] [target] [--runtime-root <path>]
```

- Default the operation to `review` when omitted.
- Default `target` to the active working directory only when the user does not provide a path.
- Accept either a Claude project/workspace root or that project's direct `.claude` directory.
- Resolve an explicit relative path from the invocation working directory. Preserve paths containing spaces and resolve symlinks.
- Normalize `<project>/.claude` to `<project>` so sibling `CLAUDE.md`, `.mcp.json`, `.worktreeinclude`, and relevant Agent SDK bootstrap code remain in the effective-configuration review.
- Reject a missing, unreadable, or non-directory target. Reject user-level `~/.claude` and host configuration directories `.agents`/`.codex` as project targets. Never silently fall back to the current directory after an explicit target fails.
- Echo both the requested target and normalized project root before presenting findings.
- Default the runtime root to the normalized project root. When the user
  explicitly supplies `--runtime-root`, accept a separate readable directory,
  including one outside the target project. Use it only for Agent SDK bootstrap,
  dependency, and runtime evidence; it never changes the Claude configuration
  root or `${CLAUDE_PROJECT_DIR}` semantics.
- Reject an invalid explicit runtime root and never fall back to the target or
  current directory. Echo both requested and normalized runtime roots.

Do not review Codex host configuration such as `AGENTS.md`, `.agents/`, or `.codex/` as Claude configuration. Read `references/host-compatibility.md` only when installation, discovery, invocation, or host compatibility is part of the task.

## Non-negotiable rules

1. **Official compliance is authoritative-only.**
   - A finding labeled `OFFICIAL-NONCOMPLIANT`, `OFFICIAL-SEMANTIC-ERROR`, or `OFFICIAL-LEGACY` MUST be supported by current Anthropic/Claude official documentation.
   - Community projects, blog posts, prior reviews, internal conventions, and this Skill's heuristics MUST NOT be used as the normative basis for a Claude compliance verdict.
   - Prefer `code.claude.com` for Claude Code and Agent SDK behavior; use `platform.claude.com` for Agent Skills standards/best practices where applicable.
   - If the installed Claude Code version or current official documentation cannot be resolved and behavior may be version-sensitive, report `UNVERIFIED` instead of asserting noncompliance.

2. **Never assume a repository layout beyond Claude's documented locations.**
   - Honor an explicit target path before using the current project/workspace default.
   - Normalize a project-local `.claude` target to its parent project root.
   - Do not hard-code `/data`, `workspace/`, product-specific directories, test directories, tenant names, platform names, or organization-specific paths.
   - Treat non-Claude files such as custom manifests as project extensions unless the project explicitly documents their contract.

3. **Tests/evals are validation assets, not review targets by default.**
   - Do not include test/eval source files in the production-configuration review unless the user explicitly asks.
   - Discover existing evaluation harnesses generically from project metadata, CI, task runners, test/eval/benchmark conventions, or a user-supplied command.
   - Use them to establish a baseline, falsify findings, validate candidate changes, and prevent regressions.

4. **Do not execute untrusted project hooks or arbitrary project code during static review.**
   - Reading files is allowed if current permissions allow it.
   - Runtime/eval execution requires an explicit safe harness or user request and an environment classified as test/mock/replay/non-production.
   - Never exercise real destructive/side-effect production capabilities merely to validate a configuration change.

5. **Do not conflate instruction with enforcement.**
   - `CLAUDE.md`, rules, Skill prose, agent prompts, and output styles influence model behavior.
   - Permissions, SDK permission options, `canUseTool`, hooks, sandboxing, and external control planes enforce execution boundaries.
   - A prompt-level prohibition is not proof that an operation is impossible.

6. **Do not conflate pre-approval with an allowlist.**
   - Follow current official semantics for `allowed-tools` / `allowedTools` / permission modes.
   - In particular, SKILL.md `allowed-tools` is CLI-only and does not apply to Skills through the Agent SDK; SDK tool access must be controlled in SDK/runtime configuration.

## Scope discovery

Start from the normalized target project/workspace root. Discover, when present:

- `CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, parent/project instruction sources that affect the active cwd
- `.claude/settings.json`, `.claude/settings.local.json`
- `.claude/rules/**/*.md`
- `.claude/skills/*/SKILL.md` and their directly referenced supporting resources
- `.claude/agents/*.md`
- `.claude/commands/**/*.md`
- `.claude/output-styles/*.md`
- `.mcp.json`
- `.worktreeinclude`
- project-local hook scripts referenced by settings, skills, or agents
- Agent SDK bootstrap/runtime code only as needed to determine `cwd`, `settingSources`/`setting_sources`, `skills`, `tools`, `allowedTools`/`allowed_tools`, `disallowedTools`/`disallowed_tools`, permission mode, hooks, MCP servers, and system-prompt behavior

Do not assume any custom `agent.yaml`/manifest exists. If discovered and relevant, review it as `PROJECT-EXTENSION`, not as an official Claude configuration artifact.

Exclude host-only Codex configuration and installed Skill copies under `.agents/` or `.codex/`. Their presence must not influence target runtime detection or Claude findings.

Read `references/official-compliance.md` before issuing official-compliance findings.
Read `references/config-responsibility-matrix.md` when assigning configuration responsibilities.
Read `references/check-catalog.md` for the full review catalog.
Read `references/review-contract.md` before constructing the coverage ledger or final report.
Read `references/gotchas.md` when reviewing hooks, split runtime roots, stateful guards, or business routing.

## Target Claude runtime mode

Determine whether the project uses:

- Claude Code CLI only;
- Claude Agent SDK;
- both;
- unknown.

For Agent SDK, determine the effective filesystem setting sources. Current SDK defaults load user/project/local sources when `settingSources`/`setting_sources` is omitted; explicit sources change what filesystem configuration loads. Verify this from official docs and project code before reasoning about effective configuration.

## Review phases and required gates

Each phase produces a required artifact. Do not skip a gate and still describe
the review as complete.

### Phase 0 — Scope gate

Record the host, requested target, normalized Claude project root, requested and
normalized runtime root, target runtime mode, installed versions when safely
discoverable, and exclusions. If an explicit path cannot be resolved, stop with
an input error instead of reviewing another directory.

### Phase 1 — Inventory and official syntax/semantics

Build an inventory of official Claude artifacts and project extensions. Parse JSON/YAML frontmatter without executing project code.

For every finding, assign exactly one primary class:

- `OFFICIAL-NONCOMPLIANT`: violates a documented requirement.
- `OFFICIAL-SEMANTIC-ERROR`: syntax may parse, but current documented Claude behavior makes the intended control ineffective or different.
- `OFFICIAL-LEGACY`: supported but explicitly documented as legacy/older format.
- `SECURITY-RISK`: potentially unsafe but not itself an official compliance violation.
- `PORTABILITY-RISK`: implementation coupling or environmental dependency.
- `MAINTAINABILITY-RISK`: duplication, drift, complexity, unclear ownership.
- `OPTIMIZATION`: quality/context/efficiency improvement.
- `PROJECT-EXTENSION`: project-defined contract outside official Claude configuration.
- `UNVERIFIED`: insufficient version/docs/runtime evidence.

Never upgrade a heuristic into `OFFICIAL-*` without an official source.

Create one coverage row for every stable check ID in
`references/check-catalog.md`. Assign exactly one state:

- `PASS`: checked with repeatable positive or negative evidence;
- `FINDING`: linked to at least one finding;
- `NA`: not applicable, with a reason;
- `UNVERIFIED`: required evidence is unavailable, with the missing evidence and
  next action stated.

This is the coverage gate. A missing/duplicate check row or any `UNVERIFIED`
row makes the review `INCOMPLETE`; absence of a finding is never implicit PASS.

### Phase 2 — Responsibility and single-source-of-truth review

Check whether each concern lives in the correct layer:

- always-on project facts/conventions → `CLAUDE.md` / scoped rules;
- task-specific reusable procedure → Skill;
- isolated specialist role/context/tool surface → subagent;
- user-visible legacy shortcut only when intentionally retained → command;
- response role/tone/default format → output style;
- external tool connection → MCP;
- deterministic tool-time guard/audit/validation → hooks;
- actual tool authorization → permissions / SDK permission configuration / `canUseTool` / sandbox;
- runtime/provider binding and product-specific adapters → runtime/integration layer, not reusable prompt knowledge unless business semantics require it.

Flag duplicated authoritative policy across layers when it can drift.

### Phase 3 — Cross-file contract and reachability

Construct a logical graph for each critical workflow:

`entry → skill/agent → capability/tool → permission → hook → sandbox/external gate → output contract`

Validate both:

- **happy-path reachability:** intended official flow can actually execute;
- **forbidden-path unreachability:** denied/unsafe flow cannot execute through another available path.

Pay special attention to:

- a tool required by an agent/workflow but denied globally;
- broad parent tool surfaces that bypass intended delegation;
- wildcard MCP approvals and future-tool drift;
- physical MCP tool names repeated across prompts/configs causing rename drift;
- SDK `allowedTools` used as if restrictive without a permission mode/callback that denies unlisted tools;
- `bypassPermissions` combined with assumptions that an allowlist still constrains access;
- security hooks that fail open on parse/state/error paths;
- user text being treated as proof of trusted platform/control-plane origin;
- sandbox read/write/network coverage versus the claimed isolation boundary.

For business routes and stateful controls, use the generic route/state/capability
model in `references/review-methodology.md`. Do not encode project-specific
field names as universal rules. Static evidence can establish explicit bindings
or contradictions, but actual multi-tenant/session/request isolation and real
side effects remain `UNVERIFIED` without a safe fixture or runtime probe.

### Phase 4 — Adversarial reasoning

Try to falsify every claimed boundary. Ask:

- What if the user claims to be a trusted control plane?
- What if a new MCP tool appears under an allowed wildcard?
- What if a hook state file is missing, stale, partial, or malformed?
- What if a frozen plan has unresolved or empty arguments?
- What if a subagent inherits tools because `tools` is omitted?
- What if a Skill is invoked directly versus model-invoked?
- What changes under CLI versus Agent SDK?
- What happens when an explicit SDK `settingSources` omits `project`?
- Can a general shell/process tool bypass a path restriction that only covers built-in file tools?

Do not invent exploitability; report assumptions and confidence.

Disposition every P0/P1 scanner candidate exactly once as `CONFIRMED`,
`DOWNGRADED`, `DISMISSED`, `DUPLICATE`, or `UNVERIFIED`:

- link `CONFIRMED`/`DOWNGRADED` to the final finding;
- link `DUPLICATE` to its canonical candidate;
- provide rationale and evidence for `DISMISSED`;
- state missing evidence and next action for `UNVERIFIED`.

There is no final `PENDING` state. Any undispositioned or multiply dispositioned
P0/P1 candidate fails the disposition gate. `UNVERIFIED` is a valid honest
disposition but keeps the report `INCOMPLETE`.

### Phase 5 — Remediation design

Use one **atomic remediation hypothesis** at a time. One hypothesis may require coordinated edits across several files; do not force a single-file patch if that creates inconsistent configuration.

Prefer these structural remedies:

- stable logical capability names above provider-specific physical tool names;
- one authoritative policy source with generated/validated downstream bindings;
- narrow subagent/tool surfaces;
- fail-closed deterministic guards for security-critical invariants;
- project/runtime role names instead of replaceable platform product names in reusable model-facing assets;
- structured runtime metadata for trust, never user prose as trust evidence;
- concise always-on context plus progressive disclosure through Skills/references.

Read `references/remediation-patterns.md` before proposing broad restructures.

### Phase 6 — Validation-gated optimization

If the user asks only for review, stop after findings/remediation recommendations.

If the user asks to optimize or apply changes:

1. Establish the current baseline.
2. Discover a safe project evaluation harness; never assume its path.
3. Add or identify a regression case that demonstrates the finding when practical.
4. Apply a bounded candidate change only after the user authorizes modification.
5. Run deterministic gates first.
6. Run safe runtime/eval gates if available.
7. Compare old/new behavior, not just aggregate pass rate.
8. Reject the candidate if any critical security, contract, happy-path, or no-regression gate fails.
9. Use paired LLM judgment only for soft qualities such as clarity, redundancy, routing description quality, or report quality—not for permission/security facts.
10. Record accepted and rejected remediation knowledge when the project has an appropriate location; otherwise report it without creating new project state.

Read `references/eval-harness.md` and `references/optimization-loop.md` for the full process.

### Final report gate

Write the authoritative result as `agent-config-reviewer-report/v2` JSON. Run:

```bash
python3 <skill-dir>/scripts/validate_review.py <review.json> --scan <scan.json> --markdown <report.md>
```

Do not hand-edit the rendered Markdown into a state inconsistent with the JSON.
The validator must bind the report to the successful scan artifact and confirm
scope/candidate closure, catalog closure, evidence links, applicability,
root-cause links, status totals, and P0/P1 disposition before the report is
presented as complete. If the scanner or Python is unavailable, reproduce what
is possible manually, mark SCANNER-owned checks `UNVERIFIED`, and keep the
report `INCOMPLETE`.

## Validation gates

Treat these as hard gates when applicable:

- official configuration parse/schema semantics;
- critical permission/security invariants;
- required workflow reachability;
- forbidden workflow unreachability;
- zero new failures in previously passing critical regression cases;
- no real production side effects during optimization evaluation.

A higher total score cannot compensate for failure of a critical gate.

## Output contract

For a review, produce authoritative JSON conforming to
`references/review-contract.md` and the rendered two-layer Markdown report:

1. Scope, assumptions, coverage counts, report completeness, and full catalog index.
2. Detailed P0/P1 findings and their dispositions.
3. Concise P2/P3 index, root causes, remediation priorities, validation assets, and unknowns.

For each substantive finding include:

- ID and severity (`P0`–`P3`);
- class;
- evidence with project-relative file/line references;
- official source when class is `OFFICIAL-*`;
- why it matters;
- root cause;
- impact/failure mode;
- remediation;
- how to validate the remediation;
- evidence layer and type;
- applicability for static configuration, official semantics, installed
  version, SDK runtime, and live deployment;
- linked catalog check IDs, candidate IDs, evidence IDs, and root-cause ID.

An `OFFICIAL-*` finding requires target evidence plus
`OFFICIAL_SEMANTICS` evidence. Do not use host documentation, community text,
or inference as that normative evidence. Preserve every original evidence
occurrence when several symptoms are aggregated under one root cause.

Use `templates/review-report.md` as the report structure.

## Optional helper

If Python 3 is already available, `scripts/scan_project.py` can produce a static candidate inventory without executing project hooks or tests:

```bash
python3 <skill-dir>/scripts/scan_project.py --target <project-root-or-project-.claude> --runtime auto --runtime-root <optional-runtime-root> --format json
```

Do not install Python packages merely to run the helper. The Skill must remain usable through the host agent's normal read-only file inspection when the helper is unavailable.

The helper is a candidate finder, not the compliance authority. Validate every `OFFICIAL-*` result against `references/official-compliance.md` and current official docs.

For package-maintainer regression checks, use the eight synthetic fixtures
described in `references/eval-harness.md`:

```bash
python3 <skill-dir>/scripts/run_evals.py
```

The deterministic runner does not call Claude Code, Codex, or any model and does
not execute fixture hooks. Real host Skill-on/Skill-off runs are a separate,
manual release gate.
