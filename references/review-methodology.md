# Review methodology

## 1. Establish the effective runtime

Record:
- host agent;
- requested target and invocation cwd;
- normalized Claude project root;
- Claude Code version if safely discoverable;
- CLI, Agent SDK, or both;
- SDK language/version if discoverable;
- effective filesystem setting sources;
- whether user/local configuration is intentionally in scope.

Project review should not automatically inspect or modify `~/.claude` merely because it can affect behavior. Report external configuration as an environmental dependency unless the user asks for an effective-environment audit.

When the target is a project-local `.claude` directory, normalize it to the parent project root before discovery. Reject invalid explicit targets rather than falling back to cwd. Exclude host-only `.agents/` and `.codex/` configuration from the Claude configuration graph.

## 2. Separate evidence layers

For every conclusion label the evidence layer:

- `STATIC_CONFIG`: file content, parsed configuration, or configuration graph;
- `OFFICIAL_SEMANTICS`: current Anthropic/Claude documentation;
- `INSTALLED_VERSION`: locally observed Claude Code or Agent SDK version;
- `SDK_RUNTIME`: actual CLI/SDK trace from an explicitly safe harness;
- `LIVE_DEPLOYMENT`: observation from an explicitly authorized deployment probe;
- `TEST_FIXTURE`: deterministic fixture or project evaluation result;
- `INFERENCE`: reviewer reasoning that still requires validation.

Do not present inference as observed runtime fact. Do not promote a static
configuration observation into an SDK-runtime or live-deployment conclusion.
An `OFFICIAL-*` finding requires both target evidence and
`OFFICIAL_SEMANTICS` evidence. When the official behavior is version-sensitive,
also require `INSTALLED_VERSION` evidence or report the conclusion as
`UNVERIFIED`.

## 3. Build a configuration graph

Nodes can include:
- entry route;
- project instruction/rule;
- Skill;
- subagent;
- logical capability;
- physical Claude/MCP tool;
- permission rule;
- hook decision;
- sandbox/runtime boundary;
- external approval/lifecycle state;
- structured output contract.

Edges should answer “what enables/blocks/depends on what?”

For a business route or stateful guard, use this generic model instead of
project-specific variable names:

```text
trusted actor/event
  -> guard
  -> capability + side-effect class
  -> state read/write
  -> next state / deny / defer / error
```

Record the following dimensions when they are explicit in the target:

- route: initial state, event, guard, capability, next state, and failure path;
- state store: backend, authority, tenant/session/request/task binding, TTL,
  lifecycle, concurrency, and integrity behavior;
- capability effect: `READ_STATE`, `WRITE_STATE`, `DELETE_STATE`, `EXECUTE`,
  `EXTERNAL_IO`, `AUTHORITY_CHANGE`, or `UNKNOWN`.

The static scanner may inventory explicit facts and contradictions only. Treat
dynamic data flow, actual isolation, race behavior, and real external effects as
`UNVERIFIED` until a safe runtime or fixture supplies evidence.

## 4. Validate two properties

**Reachability:** every intended critical flow has at least one valid path.

**Unreachability:** every explicitly forbidden flow has no alternate available path through another tool, parent agent, shell/process, Skill, or permission mode.

For stateful controls, also falsify isolation assumptions: reuse the same
session identifier across two tenants, issue concurrent requests in one
session, replay a stale request, and exercise missing/malformed/stale state.
Perform these checks with synthetic fixtures or a proven safe harness, never by
invoking production side effects.

## 5. Root-cause classification

Prefer root causes such as:
- multiple sources of truth;
- CLI/SDK semantic confusion;
- prompt used as enforcement;
- broad inheritance/wildcards;
- provider/tool-name coupling;
- product-name coupling;
- missing runtime trust provenance;
- fail-open state machine;
- custom manifest without schema ownership/versioning;
- tests measuring text presence instead of effective behavior;
- legacy and new paths simultaneously authoritative.

Aggregate only when the evidence supports one explicit root cause and subject.
Keep every original occurrence and evidence locator. Do not merge findings by
text similarity alone.

## 6. Severity

- `P0`: official happy path impossible, direct privilege/safety invariant contradiction, or severe control bypass with strong evidence.
- `P1`: high-probability security/runtime failure, fail-open guard, broad privilege exposure, or major SDK semantic mismatch.
- `P2`: portability, maintainability, drift, context quality, ambiguous ownership, or moderate runtime risk.
- `P3`: modernization, clarity, hygiene, low-risk optimization.

Severity and official-compliance class are independent. A severe security issue may be fully valid Claude syntax.
