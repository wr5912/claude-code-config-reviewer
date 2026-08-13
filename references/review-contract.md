# Review result contract v2

The authoritative review artifact is JSON. Markdown is a human-readable view
rendered only after the JSON passes `scripts/validate_review.py`.

## Command

```bash
python3 scripts/validate_review.py review.json --scan scan.json
python3 scripts/validate_review.py review.json --scan scan.json --markdown review.md
python3 scripts/validate_review.py review.json --scan scan.json --markdown -
```

The default catalog is `references/check-catalog.md`; `--catalog PATH` is
available for fixture tests. A `COMPLETE` result requires `--scan` with the
successful `agent-config-reviewer-scan/v2` artifact whose target, runtime root,
and complete candidate set match the report. Without a scan, the result must be
`INCOMPLETE`. Exit status is `0` for a valid review, `1` for a contract
violation, and `2` for unreadable/invalid input or output errors.

## Top-level object

Required fields:

| Field | Contract |
|---|---|
| `schema_version` | Exactly `agent-config-reviewer-report/v2` |
| `status` | `COMPLETE` or `INCOMPLETE` |
| `scope` | Review boundary described below |
| `coverage` | One entry for every catalog check |
| `candidates` | Deterministic scanner candidates considered by the reviewer |
| `candidate_dispositions` | Reviewer decisions for candidates |
| `findings` | Final review findings |
| `evidence` | Evidence records referenced by the other collections |
| `root_causes` | Root-cause groups for findings |

Unknown additive fields are allowed for producer metadata, but they do not
change any validation rule.

`scope` requires non-empty `host_agent`, `requested_target`,
`normalized_target`, `normalized_runtime_root`, and `target_kind`;
`runtime_mode` is one of `cli`, `agent-sdk`, `both`, or `unknown`. It also
records nullable `requested_runtime_root`, plus an
`excluded_assets` string list. Version and setting-source metadata may be
added without changing the review verdict.

## Coverage ledger

Each entry has `check_id`, `status`, `evidence_ids`, and `finding_ids`.
Every stable ID in `check-catalog.md` must occur exactly once and no unknown ID
is accepted.

| Status | Required proof |
|---|---|
| `PASS` | Locatable non-inference evidence bound back to this check, and no finding ID |
| `FINDING` | At least one finding ID; every linked finding includes the same check ID |
| `NA` | Non-empty `rationale` and no finding ID |
| `UNVERIFIED` | Non-empty `rationale` and `next_action`, and no finding ID |

Any `UNVERIFIED` coverage or disposition, or any unverified applicability
layer, makes the top-level status `INCOMPLETE`. Otherwise it is `COMPLETE`.

## Evidence, candidates, and dispositions

Evidence requires a unique `id`, a non-empty `summary`, one or more
`check_ids`, and one type:

```text
STATIC_CONFIG | OFFICIAL_SEMANTICS | INSTALLED_VERSION | SDK_RUNTIME |
LIVE_DEPLOYMENT | TEST_FIXTURE | INFERENCE
```

It may carry `path`, positive integer `line`, `json_pointer`, `source_url`, or
`command`. Evidence used to close `PASS` or `DISMISSED` must be non-`INFERENCE`
and have a locator. A SCANNER-owned PASS needs deterministic static, installed-
version, or fixture evidence; a REVIEWER-owned PASS needs reviewable non-
inference evidence; a LIVE-owned PASS needs SDK-runtime or live-deployment
evidence. `OFFICIAL_SEMANTICS` requires an HTTPS URL under
`code.claude.com/docs/` or `platform.claude.com/docs/`.

A candidate requires a unique `id`, stable scanner `rule_id`, `severity` (`P0`
through `P3`), at least one valid `check_id`, and at least one evidence ID.
When `--scan` is supplied, the candidate ID, rule ID, severity, complete
candidate set, and every scan evidence path/line locator must match the scan
artifact. Every P0/P1 candidate must have
exactly one disposition. P2/P3 dispositions are optional but, when present,
follow the same contract.

Every disposition includes `candidate_id`, `disposition`, and a non-empty
`rationale`:

| Disposition | Additional requirement |
|---|---|
| `CONFIRMED` | Linked findings at the same severity, sharing a check and evidence |
| `DOWNGRADED` | Linked findings whose severity is lower than the candidate |
| `DISMISSED` | Locatable non-inference refuting evidence; no linked finding |
| `DUPLICATE` | Different existing canonical candidate; chains terminate and cannot cycle |
| `UNVERIFIED` | Non-empty `next_action`; no linked finding |

`PENDING` is not a valid final disposition.

## Findings, applicability, and root causes

A finding requires a unique `id`, `severity`, one class from the Skill's fixed
class list, and a non-empty `title`,
one or more catalog `check_ids`, one `root_cause_id`, and one or more
`evidence_ids`. A class beginning with `OFFICIAL-` must directly reference:

1. an `OFFICIAL_SEMANTICS` evidence record from an allowed official domain;
2. target evidence of type `STATIC_CONFIG`, `INSTALLED_VERSION`,
   `SDK_RUNTIME`, `LIVE_DEPLOYMENT`, or `TEST_FIXTURE`.

`applicability` contains every layer below exactly once as object keys:

```text
STATIC_CONFIG | OFFICIAL_SEMANTICS | INSTALLED_VERSION |
SDK_RUNTIME | LIVE_DEPLOYMENT
```

Each layer has `status` (`APPLIES`, `DOES_NOT_APPLY`, or `UNVERIFIED`), a
non-empty `rationale`, and `evidence_ids`. `APPLIES` needs evidence of the same
layer; `UNVERIFIED` needs `next_action`. This prevents a static observation from silently being
presented as installed-version, SDK-runtime, or live-deployment proof.

A root cause requires a unique `id`, non-empty `title`, at least one
`finding_id`, and an `evidence_ids` list. Finding-to-root-cause references are
bidirectional: both sides must identify each other. Aggregation never removes
the evidence retained by individual findings.
