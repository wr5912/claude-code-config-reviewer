# Review gotchas

Read this file when a target uses hooks, stateful guards, split configuration
and runtime repositories, or business routing. These are regression-backed
failure patterns, not official Claude rules.

## G-001 — A resolved Hook string is not proof of an executable reference

Shell form and exec form have different tokenization and variable-expansion
semantics. Preserve the configured form, quote paths with spaces, and report a
missing, dynamic, malformed, unreadable, or out-of-scope reference explicitly.

Regression fixtures: `hook-shell-paths`, `hook-exec-paths`, `hook-unresolved`.

## G-002 — Configuration root and runtime root may be different

Resolve Claude configuration from the target project. Use an explicitly
provided runtime root only for SDK/bootstrap/dependency evidence. Never let a
runtime repository's `.claude`, `.agents`, or `.codex` subtree redefine the
target configuration.

Regression fixture: `split-runtime-root`.

## G-003 — A state file is not an isolation boundary by itself

Check who can write the state, which tenant/session/request/task identifiers
are bound into its key and payload, how freshness is enforced, and what happens
when the state is missing, malformed, stale, or concurrently updated. For a
security-critical action, an unknown state should not silently become allow.

Regression fixture: `state-store-isolation`.

## G-004 — One guarded route does not make alternate routes unreachable

Model every capability-bearing transition and side effect. Look for parent
agent tools, shell/process execution, wildcard MCP tools, duplicate commands,
or error paths that reach the same capability without the intended guard.

Regression fixture: `route-capability-bypass`.

## G-005 — Host configuration is review noise, not Claude target evidence

Codex may host this Skill, but `.agents`, `.codex`, and `AGENTS.md` are not
Claude Code configuration. Tests, evals, documentation examples, and comments
also must not change target runtime detection unless explicitly included as a
validation asset.

Regression fixture: `wrong-context-noise`.

## Adding a gotcha

Add a gotcha only after a concrete miss is reproduced. First add or update one
synthetic regression fixture, then describe the transferable root cause here.
Do not include real workspace names, tenants, sessions, credentials, or private
report content.
