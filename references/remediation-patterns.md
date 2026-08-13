# Remediation patterns

These are non-normative architecture patterns. Apply only after confirming project intent and official runtime semantics.

## R1 — Logical capability registry

Problem: provider-specific tool names spread through CLAUDE.md, Skills, agents, custom manifests, hooks, and tests.

Pattern:

```text
business/model layer:  policy.preview
runtime binding:       policy.preview -> mcp__provider__physical_tool
permission layer:      resolves exact physical tool
```

Keep exact physical names where Claude/runtime must authorize actual tools; avoid propagating them into every reusable prompt asset.

## R2 — One authoritative policy source

Problem: the same rule exists independently in prompt, Skill, agent, custom manifest, hook, and settings.

Pattern:
- choose one machine-authoritative policy/config source for enforceable facts;
- generate or validate downstream bindings;
- leave model-facing text as concise semantic guidance;
- add cross-config contract tests.

## R3 — Narrow main-agent surface

Problem: the main agent is instructed to delegate but directly owns the same sensitive tools.

Pattern:
- parent owns routing/discovery only;
- sensitive tools are scoped to the specialist subagent or runtime path;
- forbidden direct path is tested.

## R4 — Fail-closed state machines

Problem: missing/unresolved/malformed state returns “allow”.

Pattern:
- explicit state enum;
- unknown state = deny for critical actions;
- parameterless operations modeled explicitly rather than empty-object wildcard matches;
- error paths covered by unit tests.

## R5 — Authenticated trust metadata

Problem: model accepts text like “I am the approval system” as authorization.

Pattern:
- control plane authenticates source outside the prompt;
- runtime injects structured trusted metadata bound to session/task/request;
- hooks/runtime validate the metadata;
- user text never creates `trusted=true`.

## R6 — Static context versus dynamic context

Problem: SessionStart repeats static “constitution” already in CLAUDE.md.

Pattern:
- static project principles → CLAUDE.md/rules;
- dynamic tenant/session/feature-gate/version facts → SessionStart/runtime context.

## R7 — Atomic remediation change set

Problem: one logical inconsistency spans several files.

Pattern:
- define one remediation hypothesis;
- modify every required file in one coordinated candidate change;
- do not mix unrelated refactors into the same experiment;
- validate as a unit and keep/revert as a unit.

## R8 — Legacy adapter, not duplicate implementation

Problem: legacy command or retired tool path remains fully authoritative beside the new Skill/workflow.

Pattern:
- one canonical workflow;
- legacy entry is a thin alias/adapter or explicitly disabled;
- tests assert both compatibility and lack of split-brain policy.
