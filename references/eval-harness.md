# Evaluation harness integration

The reviewer must not assume a fixed tests directory. Existing project tests/evals are **validation assets** discovered from the project.

## Discovery order

1. User-supplied evaluation command or documentation.
2. Project task metadata: `package.json`, `pyproject.toml`, `Makefile`, task runners, tox/nox, CI workflows, build scripts.
3. Conventional test/eval/benchmark/spec directories discovered by name, without assuming any one path.
4. Agent SDK bootstrap code and fixtures that show how the real configuration is loaded.

Do not execute a candidate command merely because its name contains “test”. Read it first when practical.

## Determine whether the harness is representative

A runtime/eval harness is useful only if it reflects the intended deployment configuration. Check:
- same normalized Claude project root as the requested target;
- same or intentionally equivalent `cwd`;
- same `settingSources` / `setting_sources` semantics;
- relevant project Skills/agents/settings/MCP loaded;
- equivalent permission mode/tool surface;
- hooks enabled where the production path depends on them;
- mocks/replays preserve the contract fields that guards evaluate.

## Environment safety gate

Classify before runtime evaluation:
- `SAFE-MOCK`: no external side effects;
- `SAFE-REPLAY`: recorded deterministic tool responses;
- `SAFE-TEST`: isolated non-production services/accounts/resources;
- `UNKNOWN`: cannot prove isolation;
- `PRODUCTION`: live side-effect-capable environment.

Automatically run candidate optimization evaluations only in the first three classes. For `UNKNOWN` or `PRODUCTION`, restrict to static/contract checks until the user provides an explicit safe method.

## Evaluation categories

### Deterministic unit/contract
- JSON/YAML/frontmatter parse;
- hook policy functions and state transitions;
- permission/capability resolution;
- schema validation;
- required-tool versus deny conflicts;
- frozen-argument exactness;
- trust metadata verification.

### Runtime routing
Launch the actual CLI/Agent SDK path when safe and assert:
- expected Skill activation;
- expected subagent delegation;
- parent does not bypass specialist boundaries;
- correct tool names/arguments;
- hook allow/deny decisions;
- structured output contract.

### Adversarial
Include cases such as:
- user tells Claude to ignore project instructions;
- user falsely claims an approval/control-plane identity;
- user requests a forbidden direct tool path;
- malformed/missing runtime state;
- extra/new tool under wildcard provider;
- prompt tries to bypass a required specialist.

### Regression
Every confirmed defect should become a durable regression case when practical:

`finding -> failing case -> remediation -> passing case`

Do not replace meaningful assertions with string-presence checks when runtime behavior can be tested.

## Gate policy

A candidate fails if any applicable critical gate fails:
- official parse/semantic gate;
- critical security invariant;
- required happy path;
- forbidden path;
- previously passing critical regression;
- production-safety gate.

Aggregate score is secondary and cannot override a failed critical gate.
