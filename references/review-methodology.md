# Review methodology

## 1. Establish the effective runtime

Record:
- project root / active cwd;
- Claude Code version if safely discoverable;
- CLI, Agent SDK, or both;
- SDK language/version if discoverable;
- effective filesystem setting sources;
- whether user/local configuration is intentionally in scope.

Project review should not automatically inspect or modify `~/.claude` merely because it can affect behavior. Report external configuration as an environmental dependency unless the user asks for an effective-environment audit.

## 2. Separate evidence types

For every conclusion label the evidence:
- `STATIC`: file content/config graph;
- `OFFICIAL`: current Claude documentation;
- `RUNTIME`: actual SDK/CLI trace;
- `EVAL`: project test/evaluation result;
- `INFERENCE`: reviewer reasoning requiring validation.

Do not present inference as observed runtime fact.

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

## 4. Validate two properties

**Reachability:** every intended critical flow has at least one valid path.

**Unreachability:** every explicitly forbidden flow has no alternate available path through another tool, parent agent, shell/process, Skill, or permission mode.

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

## 6. Severity

- `P0`: official happy path impossible, direct privilege/safety invariant contradiction, or severe control bypass with strong evidence.
- `P1`: high-probability security/runtime failure, fail-open guard, broad privilege exposure, or major SDK semantic mismatch.
- `P2`: portability, maintainability, drift, context quality, ambiguous ownership, or moderate runtime risk.
- `P3`: modernization, clarity, hygiene, low-risk optimization.

Severity and official-compliance class are independent. A severe security issue may be fully valid Claude syntax.
