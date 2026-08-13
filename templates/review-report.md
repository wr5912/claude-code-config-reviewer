# Claude Code Configuration Review

The validated `review.json` is authoritative. Generate this Markdown view with
`python3 scripts/validate_review.py review.json --scan scan.json --markdown review.md`; do not
hand-edit fields that participate in validation.

## 1. Review status and scope

- Status: `COMPLETE | INCOMPLETE`
- Host agent:
- Requested target:
- Normalized Claude project root:
- Target kind: `project-root | project-claude-dir`
- Target Claude runtime: `cli | agent-sdk | both | unknown`
- Requested runtime root:
- Normalized runtime root:
- Excluded host/non-target assets:

Codex may host this Skill, but `.agents/`, `.codex/`, and `AGENTS.md` are not
Claude Code configuration findings.

## 2. Executive summary

Summarize P0/P1 findings, official-compliance state, systemic root causes, and
which applicability layers remain unverified. An `INCOMPLETE` review must not
claim full coverage.

## 3. Full coverage index

Include every catalog ID exactly once.

| Check | Owner | Status | Findings | Evidence | Rationale / next action |
|---|---|---|---|---|---|
| A-001 | REVIEWER | PASS / FINDING / NA / UNVERIFIED | ... | ... | ... |

## 4. Full finding index

Include P0 through P3. P2/P3 remain visible here even though only P0/P1 are
expanded below.

| Finding | Severity | Class | Checks | Root cause | Evidence | Applicability summary |
|---|---|---|---|---|---|---|

## 5. P0/P1 detailed findings

For every P0/P1 finding:

### [ID] [Severity] Title

- Class:
- Catalog checks:
- Root cause:
- Candidate dispositions:
- Evidence, including path/line or official URL:
- Static-config applicability (status, rationale, evidence IDs):
- Official-semantics applicability (status, rationale, evidence IDs):
- Installed-version applicability (status, rationale, evidence IDs):
- SDK-runtime applicability (status, rationale, evidence IDs):
- Live-deployment applicability (status, rationale, evidence IDs):
- Impact:
- Remediation:
- Validation:

An `OFFICIAL-*` item must cite both target evidence and a current source from
`code.claude.com/docs/` or `platform.claude.com/docs/`.

## 6. P0/P1 candidate disposition ledger

| Candidate | Severity | Disposition | Finding/canonical candidate | Evidence | Rationale / next action |
|---|---|---|---|---|---|

No P0/P1 candidate may remain absent or `PENDING`.

## 7. Root causes and cross-file contract graph

Group related symptoms without dropping individual evidence. Describe the
critical flow where useful:

```text
entry -> skill/agent -> tool -> permission -> hook -> sandbox/control-plane -> output
```

## 8. Prioritized remediation and validation

- P0/P1 first.
- One atomic remediation hypothesis per candidate round.
- List coordinated files that must change together.
- Record deterministic, safe runtime, adversarial, and regression gates.

## 9. Unknowns / unverified items

List every coverage item, candidate disposition, or applicability layer marked
`UNVERIFIED`, with the missing evidence and next action.
