# Claude Code Configuration Review

## 1. Scope

- Host agent: Claude Code / Codex / other compatible host
- Requested target:
- Normalized Claude project root:
- Target kind: project root / project `.claude` directory
- Target Claude runtime mode: CLI / Agent SDK / both / unknown
- Claude Code version:
- SDK version/language:
- Effective setting sources:
- Review target scope:
- Eval/runtime execution scope:
- Excluded/non-target assets:

Do not list Codex host configuration as Claude configuration. Record `.agents/` and `.codex/` as excluded host assets when present.

## 2. Executive summary

Summarize P0/P1 issues, official compliance state, major architecture risks, and whether safe runtime validation was available.

## 3. Official compliance findings

For every finding:

### [ID] [Severity] Title

- Class: `OFFICIAL-NONCOMPLIANT | OFFICIAL-SEMANTIC-ERROR | OFFICIAL-LEGACY | UNVERIFIED`
- Evidence: project-relative path + line
- Official source: current `code.claude.com` / `platform.claude.com` URL
- Current documented behavior:
- Why current configuration differs:
- Root cause:
- Impact:
- Remediation:
- Validation:

## 4. Security / architecture / portability findings

Use the same structure but do not label non-official guidance as compliance failure.

## 5. Cross-file contract graph

Describe critical flows and contradictions:

```text
entry -> skill/agent -> tool -> permission -> hook -> sandbox/control-plane -> output
```

Record happy-path reachability and forbidden-path unreachability.

## 6. Root causes

Group symptoms into systemic causes rather than repeating one issue per file.

## 7. Prioritized remediation plan

- P0/P1 first.
- One atomic remediation hypothesis per candidate round.
- Note coordinated files that must change together.

## 8. Validation assets

- Existing project eval/test harness discovered:
- Safe environment classification:
- Baseline results:
- Critical gates:
- Adversarial cases:
- Regression cases:

## 9. Candidate optimization result (if applied)

- Candidate ID:
- Target finding:
- Files changed:
- Deterministic gate:
- Runtime/eval gate:
- No-regression gate:
- Soft paired comparison:
- Decision: `KEEP | REVERT | REVISE`

## 10. Unknowns / unverified items

List version-sensitive or environment-dependent claims that could not be proven.
