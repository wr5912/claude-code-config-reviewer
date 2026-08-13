# Non-normative inspirations

These ideas influence the optimization workflow only. They are **not** sources of Claude compliance requirements.

## Microsoft SkillOpt / SkillOpt-style ideas

Useful concepts:
- repeated rollout/reflection/update loops;
- bounded edit budget rather than uncontrolled rewrites;
- validation gates before accepting a candidate;
- rejected-edit memory to avoid repeating known-bad changes;
- slow/meta learning from recurring failure patterns.

Adaptation here:
- optimize a configuration system, not only one SKILL.md;
- use an atomic logical change set that may span multiple config files;
- hard security/contract gates precede qualitative judgment.

## Darwin-style ideas

Useful concepts:
- baseline versus candidate comparison;
- keep/revert discipline;
- paired evaluation for noisy qualitative judgments;
- human-in-the-loop adoption.

Adaptation here:
- paired LLM judges are only for soft qualities;
- deterministic Claude semantics, permissions, hooks, schema, and reachability are verified by code/runtime evidence;
- live side-effect production rollout is prohibited as an optimization experiment.
