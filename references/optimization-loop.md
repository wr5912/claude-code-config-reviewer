# Validation-gated optimization loop

This is a non-normative optimization method inspired by iterative Skill/config optimization systems. It must never override official Claude semantics.

## Loop

```text
baseline
  -> review finding
  -> root-cause hypothesis
  -> bounded atomic change set
  -> deterministic gates
  -> safe runtime/eval gates
  -> paired soft-quality comparison (optional)
  -> keep or revert
  -> accepted/rejected remediation memory
```

## Bounded change budget

Prefer one logical hypothesis per round. A hypothesis may touch multiple files if required for consistency.

Example:
- good: “Replace one obsolete policy-preview binding across the agent, permission, and hook contract.”
- bad: “Also rewrite CLAUDE.md, rename every Skill, refactor all hooks, and change output format in the same experiment.”

## Keep/revert decision

`KEEP` only when:
- all applicable hard gates pass;
- no new critical regression appears;
- the target finding is actually resolved;
- runtime/eval evidence is at least as strong as the baseline where comparable.

Otherwise `REVERT` or return a revised candidate.

## Paired judging for soft quality

For qualities that are inherently judgmental, compare baseline and candidate side-by-side using the same rubric, e.g.:
- clarity of routing rules;
- redundancy reduction;
- actionable specificity;
- failure-mechanism explanation;
- context efficiency.

Do **not** use LLM voting to decide deterministic facts such as whether a permission rule matches, a hook fails open, a schema parses, or a required tool is denied.

## Accepted/rejected remediation memory

When the project already has an appropriate governed location, record:
- finding signature/root cause;
- candidate change;
- validation evidence;
- keep/revert outcome;
- why rejected changes failed.

Never create hidden persistent state in an arbitrary project merely because this Skill exists. If no governed location exists, include the learning in the report instead.

## Promotion of recurring knowledge

When repeated reviews demonstrate the same root cause:

`repeated evidence -> root-cause pattern -> deterministic scanner rule or review rule -> regression eval`

A heuristic should not become a hard compliance rule unless official Claude documentation supports it.
