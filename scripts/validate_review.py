#!/usr/bin/env python3
"""校验结构化审查结果，并可渲染简洁的 Markdown 报告。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "agent-config-reviewer-report/v2"
SCAN_SCHEMA_VERSION = "agent-config-reviewer-scan/v2"
CATALOG_PATTERN = re.compile(
    r"^- \[([A-N]-\d{3})\] \[(SCANNER|REVIEWER|LIVE)\] (.+)$"
)
SEVERITIES = {"P0", "P1", "P2", "P3"}
COVERAGE_STATUSES = {"PASS", "FINDING", "NA", "UNVERIFIED"}
DISPOSITIONS = {
    "CONFIRMED", "DOWNGRADED", "DISMISSED", "DUPLICATE", "UNVERIFIED"
}
EVIDENCE_TYPES = {
    "STATIC_CONFIG", "OFFICIAL_SEMANTICS", "INSTALLED_VERSION",
    "SDK_RUNTIME", "LIVE_DEPLOYMENT", "TEST_FIXTURE", "INFERENCE",
}
APPLICABILITY_LAYERS = {
    "STATIC_CONFIG", "OFFICIAL_SEMANTICS", "INSTALLED_VERSION",
    "SDK_RUNTIME", "LIVE_DEPLOYMENT",
}
APPLICABILITY_STATUSES = {"APPLIES", "DOES_NOT_APPLY", "UNVERIFIED"}
OFFICIAL_HOSTS = {"code.claude.com", "platform.claude.com"}
FINDING_CLASSES = {
    "OFFICIAL-NONCOMPLIANT",
    "OFFICIAL-SEMANTIC-ERROR",
    "OFFICIAL-LEGACY",
    "SECURITY-RISK",
    "ARCHITECTURE-RISK",
    "MAINTAINABILITY-RISK",
    "PORTABILITY-RISK",
    "OPTIMIZATION",
    "PROJECT-EXTENSION",
    "UNVERIFIED",
}
LOCATOR_FIELDS = {"path", "json_pointer", "source_url", "command"}
APPLICABILITY_EVIDENCE_TYPES = {
    "STATIC_CONFIG": {"STATIC_CONFIG"},
    "OFFICIAL_SEMANTICS": {"OFFICIAL_SEMANTICS"},
    "INSTALLED_VERSION": {"INSTALLED_VERSION"},
    "SDK_RUNTIME": {"SDK_RUNTIME"},
    "LIVE_DEPLOYMENT": {"LIVE_DEPLOYMENT"},
}


class ReviewValidationError(ValueError):
    """表示审查结果违反可聚合展示的契约。"""


def _object(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return {}
    return value


def _list(value: Any, label: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return []
    return value


def _strings(value: Any, label: str, errors: list[str]) -> list[str]:
    items = _list(value, label, errors)
    if not all(isinstance(item, str) and item for item in items):
        errors.append(f"{label} must contain non-empty strings")
    return [item for item in items if isinstance(item, str) and item]


def _string_values(value: Any) -> list[str]:
    """仅供错误聚合后的关系检查使用，不再假设输入类型正确。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _text(obj: dict[str, Any], key: str, label: str, errors: list[str]) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}.{key} must be a non-empty string")
        return ""
    return value.strip()


def _index(
    items: list[Any], label: str, errors: list[str]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    result: dict[str, dict[str, Any]] = {}
    for position, raw in enumerate(items):
        row = _object(raw, f"{label}[{position}]", errors)
        item_id = _text(row, "id", f"{label}[{position}]", errors)
        if item_id in result:
            errors.append(f"{label} repeats id {item_id!r}")
        elif item_id:
            result[item_id] = row
        rows.append(row)
    return rows, result


def load_catalog(path: Path) -> dict[str, dict[str, str]]:
    """从唯一权威 Markdown 中读取稳定检查 ID。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ReviewValidationError(f"cannot read catalog: {exc}") from exc

    catalog: dict[str, dict[str, str]] = {}
    malformed: list[int] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.startswith("- "):
            continue
        match = CATALOG_PATTERN.fullmatch(line)
        if not match:
            malformed.append(line_number)
            continue
        check_id, owner, title = match.groups()
        if check_id in catalog:
            raise ReviewValidationError(f"catalog repeats check ID {check_id!r}")
        catalog[check_id] = {"owner": owner, "title": title}
    if malformed:
        raise ReviewValidationError(
            "catalog has malformed check bullets on lines "
            + ", ".join(map(str, malformed))
        )
    if not catalog:
        raise ReviewValidationError("catalog contains no check entries")
    return catalog


def _official_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme == "https" and parsed.hostname in OFFICIAL_HOSTS and parsed.path.startswith("/docs/")
    except ValueError:
        return False


def _has_locator(row: dict[str, Any]) -> bool:
    return any(isinstance(row.get(field), str) and row[field].strip() for field in LOCATOR_FIELDS)


def _evidence_supports_check(row: dict[str, Any], check_id: str) -> bool:
    return check_id in _string_values(row.get("check_ids"))


def _validate_scope(payload: dict[str, Any], errors: list[str]) -> None:
    scope = _object(payload.get("scope"), "scope", errors)
    for key in ("host_agent", "requested_target", "normalized_target", "target_kind"):
        _text(scope, key, "scope", errors)
    if scope.get("runtime_mode") not in {"cli", "agent-sdk", "both", "unknown"}:
        errors.append("scope.runtime_mode must be cli, agent-sdk, both, or unknown")
    if scope.get("requested_runtime_root") is not None and not isinstance(scope.get("requested_runtime_root"), str):
        errors.append("scope.requested_runtime_root must be a string or null")
    _text(scope, "normalized_runtime_root", "scope", errors)
    _strings(scope.get("excluded_assets"), "scope.excluded_assets", errors)


def validate_review(
    payload: Any,
    catalog: dict[str, dict[str, str]],
    scan: Any | None = None,
) -> dict[str, Any]:
    """返回已校验对象；一次报告所有可定位的契约错误。"""
    errors: list[str] = []
    document = _object(payload, "review", errors)
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")
    if document.get("status") not in {"COMPLETE", "INCOMPLETE"}:
        errors.append("status must be COMPLETE or INCOMPLETE")
    _validate_scope(document, errors)

    evidence_rows, evidence = _index(
        _list(document.get("evidence"), "evidence", errors), "evidence", errors
    )
    for row in evidence_rows:
        evidence_id = row.get("id", "?")
        if row.get("type") not in EVIDENCE_TYPES:
            errors.append(f"evidence {evidence_id!r} has invalid type")
        _text(row, "summary", f"evidence {evidence_id!r}", errors)
        check_ids = _strings(row.get("check_ids"), f"evidence {evidence_id!r}.check_ids", errors)
        if not check_ids:
            errors.append(f"evidence {evidence_id!r} must reference a check")
        for check_id in check_ids:
            if check_id not in catalog:
                errors.append(f"evidence {evidence_id!r} references unknown check {check_id!r}")
        if "line" in row and (not isinstance(row["line"], int) or isinstance(row["line"], bool) or row["line"] < 1):
            errors.append(f"evidence {evidence_id!r}.line must be a positive integer")
        if row.get("type") == "OFFICIAL_SEMANTICS" and not _official_url(row.get("source_url")):
            errors.append(f"evidence {evidence_id!r} must use an allowed official docs URL")

    finding_rows, findings = _index(
        _list(document.get("findings"), "findings", errors), "findings", errors
    )
    root_rows, roots = _index(
        _list(document.get("root_causes"), "root_causes", errors), "root_causes", errors
    )
    candidate_rows, candidates = _index(
        _list(document.get("candidates"), "candidates", errors), "candidates", errors
    )

    for row in candidate_rows:
        candidate_id = row.get("id", "?")
        _text(row, "rule_id", f"candidate {candidate_id!r}", errors)
        if row.get("severity") not in SEVERITIES:
            errors.append(f"candidate {candidate_id!r} has invalid severity")
        check_ids = _strings(row.get("check_ids"), f"candidate {candidate_id!r}.check_ids", errors)
        evidence_ids = _strings(row.get("evidence_ids"), f"candidate {candidate_id!r}.evidence_ids", errors)
        if not check_ids:
            errors.append(f"candidate {candidate_id!r} must reference a check")
        if not evidence_ids:
            errors.append(f"candidate {candidate_id!r} must reference evidence")
        for check_id in check_ids:
            if check_id not in catalog:
                errors.append(f"candidate {candidate_id!r} references unknown check {check_id!r}")
        for evidence_id in evidence_ids:
            if evidence_id not in evidence:
                errors.append(f"candidate {candidate_id!r} references unknown evidence {evidence_id!r}")
            elif not set(check_ids).intersection(_string_values(evidence[evidence_id].get("check_ids"))):
                errors.append(f"candidate {candidate_id!r} evidence {evidence_id!r} is not bound to one of its checks")

    severity_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    for row in finding_rows:
        finding_id = row.get("id", "?")
        if row.get("severity") not in SEVERITIES:
            errors.append(f"finding {finding_id!r} has invalid severity")
        finding_class = _text(row, "class", f"finding {finding_id!r}", errors)
        if finding_class not in FINDING_CLASSES:
            errors.append(f"finding {finding_id!r} has invalid class")
        _text(row, "title", f"finding {finding_id!r}", errors)
        check_ids = _strings(row.get("check_ids"), f"finding {finding_id!r}.check_ids", errors)
        evidence_ids = _strings(row.get("evidence_ids"), f"finding {finding_id!r}.evidence_ids", errors)
        if not check_ids:
            errors.append(f"finding {finding_id!r} must reference a check")
        if not evidence_ids:
            errors.append(f"finding {finding_id!r} must reference evidence")
        for check_id in check_ids:
            if check_id not in catalog:
                errors.append(f"finding {finding_id!r} references unknown check {check_id!r}")
        linked_evidence = [evidence[item] for item in evidence_ids if item in evidence]
        for evidence_id in evidence_ids:
            if evidence_id not in evidence:
                errors.append(f"finding {finding_id!r} references unknown evidence {evidence_id!r}")
            elif not set(check_ids).intersection(_string_values(evidence[evidence_id].get("check_ids"))):
                errors.append(f"finding {finding_id!r} evidence {evidence_id!r} is not bound to one of its checks")
        root_id = _text(row, "root_cause_id", f"finding {finding_id!r}", errors)
        if root_id and root_id not in roots:
            errors.append(f"finding {finding_id!r} references unknown root cause {root_id!r}")
        if finding_class in {"OFFICIAL-NONCOMPLIANT", "OFFICIAL-SEMANTIC-ERROR", "OFFICIAL-LEGACY"}:
            types = {item.get("type") for item in linked_evidence}
            if "OFFICIAL_SEMANTICS" not in types:
                errors.append(f"official finding {finding_id!r} lacks OFFICIAL_SEMANTICS evidence")
            if not types.intersection(EVIDENCE_TYPES - {"OFFICIAL_SEMANTICS", "INFERENCE"}):
                errors.append(f"official finding {finding_id!r} lacks target evidence")
        applicability = _object(row.get("applicability"), f"finding {finding_id!r}.applicability", errors)
        if set(applicability) != APPLICABILITY_LAYERS:
            errors.append(f"finding {finding_id!r}.applicability must contain exactly all five layers")
        for layer in APPLICABILITY_LAYERS:
            item = _object(applicability.get(layer), f"finding {finding_id!r}.applicability.{layer}", errors)
            if item.get("status") not in APPLICABILITY_STATUSES:
                errors.append(f"finding {finding_id!r}.applicability.{layer} has invalid status")
            _text(item, "rationale", f"finding {finding_id!r}.applicability.{layer}", errors)
            layer_evidence_ids = _strings(
                item.get("evidence_ids", []),
                f"finding {finding_id!r}.applicability.{layer}.evidence_ids",
                errors,
            )
            for evidence_id in layer_evidence_ids:
                if evidence_id not in evidence:
                    errors.append(f"finding {finding_id!r}.applicability.{layer} references unknown evidence {evidence_id!r}")
                if evidence_id not in evidence_ids:
                    errors.append(f"finding {finding_id!r}.applicability.{layer} uses evidence outside the finding")
            if item.get("status") == "APPLIES":
                allowed_types = APPLICABILITY_EVIDENCE_TYPES[layer]
                if not any(evidence.get(item_id, {}).get("type") in allowed_types for item_id in layer_evidence_ids):
                    errors.append(f"finding {finding_id!r}.applicability.{layer} lacks matching layer evidence")
            if item.get("status") == "UNVERIFIED":
                _text(item, "next_action", f"finding {finding_id!r}.applicability.{layer}", errors)

    for row in root_rows:
        root_id = row.get("id", "?")
        _text(row, "title", f"root cause {root_id!r}", errors)
        finding_ids = _strings(row.get("finding_ids"), f"root cause {root_id!r}.finding_ids", errors)
        root_evidence_ids = _strings(row.get("evidence_ids"), f"root cause {root_id!r}.evidence_ids", errors)
        if not finding_ids:
            errors.append(f"root cause {root_id!r} must reference a finding")
        for finding_id in finding_ids:
            if finding_id not in findings:
                errors.append(f"root cause {root_id!r} references unknown finding {finding_id!r}")
            elif findings[finding_id].get("root_cause_id") != root_id:
                errors.append(f"root cause {root_id!r} and finding {finding_id!r} are not bidirectional")
        for evidence_id in root_evidence_ids:
            if evidence_id not in evidence:
                errors.append(f"root cause {root_id!r} references unknown evidence {evidence_id!r}")

    disposition_rows = _list(document.get("candidate_dispositions"), "candidate_dispositions", errors)
    dispositions: dict[str, dict[str, Any]] = {}
    for position, raw in enumerate(disposition_rows):
        row = _object(raw, f"candidate_dispositions[{position}]", errors)
        candidate_id = _text(row, "candidate_id", f"candidate_dispositions[{position}]", errors)
        if candidate_id in dispositions:
            errors.append(f"candidate {candidate_id!r} has multiple dispositions")
        elif candidate_id:
            dispositions[candidate_id] = row
        if candidate_id not in candidates:
            errors.append(f"disposition references unknown candidate {candidate_id!r}")
        disposition = row.get("disposition")
        if disposition not in DISPOSITIONS:
            errors.append(f"candidate {candidate_id!r} has invalid disposition")
        _text(row, "rationale", f"candidate {candidate_id!r} disposition", errors)
        evidence_ids = _strings(row.get("evidence_ids", []), f"candidate {candidate_id!r} disposition.evidence_ids", errors)
        finding_ids = _strings(row.get("finding_ids", []), f"candidate {candidate_id!r} disposition.finding_ids", errors)
        for evidence_id in evidence_ids:
            if evidence_id not in evidence:
                errors.append(f"candidate {candidate_id!r} disposition references unknown evidence {evidence_id!r}")
        for finding_id in finding_ids:
            if finding_id not in findings:
                errors.append(f"candidate {candidate_id!r} disposition references unknown finding {finding_id!r}")
        if disposition == "CONFIRMED" and not finding_ids:
            errors.append(f"confirmed candidate {candidate_id!r} must link a finding")
        if disposition == "CONFIRMED":
            candidate = candidates.get(candidate_id, {})
            for finding_id in finding_ids:
                finding = findings.get(finding_id, {})
                if finding.get("severity") != candidate.get("severity"):
                    errors.append(f"confirmed candidate {candidate_id!r} must retain its severity")
                if not set(_string_values(candidate.get("check_ids"))).intersection(_string_values(finding.get("check_ids"))):
                    errors.append(f"confirmed candidate {candidate_id!r} and finding {finding_id!r} share no check")
                if not set(_string_values(candidate.get("evidence_ids"))).intersection(_string_values(finding.get("evidence_ids"))):
                    errors.append(f"confirmed candidate {candidate_id!r} and finding {finding_id!r} share no evidence")
        if disposition == "DOWNGRADED":
            if not finding_ids:
                errors.append(f"downgraded candidate {candidate_id!r} must link a finding")
            candidate_severity = candidates.get(candidate_id, {}).get("severity")
            for finding_id in finding_ids:
                finding = findings.get(finding_id, {})
                finding_severity = finding.get("severity")
                if candidate_severity in severity_rank and finding_severity in severity_rank and severity_rank[finding_severity] <= severity_rank[candidate_severity]:
                    errors.append(f"downgraded candidate {candidate_id!r} links a non-lower-severity finding")
                if not set(_string_values(candidates.get(candidate_id, {}).get("check_ids"))).intersection(_string_values(finding.get("check_ids"))):
                    errors.append(f"downgraded candidate {candidate_id!r} and finding {finding_id!r} share no check")
                if not set(_string_values(candidates.get(candidate_id, {}).get("evidence_ids"))).intersection(_string_values(finding.get("evidence_ids"))):
                    errors.append(f"downgraded candidate {candidate_id!r} and finding {finding_id!r} share no evidence")
        if disposition == "DISMISSED":
            refuting = [evidence[item] for item in evidence_ids if item in evidence]
            if not evidence_ids or finding_ids or not any(item.get("type") != "INFERENCE" and _has_locator(item) for item in refuting):
                errors.append(f"dismissed candidate {candidate_id!r} needs locatable non-inference evidence and no finding")
        if disposition == "DUPLICATE":
            canonical = row.get("canonical_candidate_id")
            if not isinstance(canonical, str) or canonical not in candidates or canonical == candidate_id or finding_ids:
                errors.append(f"duplicate candidate {candidate_id!r} needs a different canonical candidate and no finding")
            else:
                original_severity = candidates.get(candidate_id, {}).get("severity")
                canonical_severity = candidates[canonical].get("severity")
                if original_severity in severity_rank and canonical_severity in severity_rank and severity_rank[canonical_severity] > severity_rank[original_severity]:
                    errors.append(f"duplicate candidate {candidate_id!r} cannot point to a lower-severity canonical candidate")
        if disposition == "UNVERIFIED":
            _text(row, "next_action", f"candidate {candidate_id!r} disposition", errors)
            if finding_ids:
                errors.append(f"unverified candidate {candidate_id!r} must not link a finding")

    for candidate_id, row in candidates.items():
        if row.get("severity") in {"P0", "P1"} and candidate_id not in dispositions:
            errors.append(f"P0/P1 candidate {candidate_id!r} has no disposition")
    for candidate_id, row in dispositions.items():
        if row.get("disposition") != "DUPLICATE":
            continue
        seen = {candidate_id}
        current = row.get("canonical_candidate_id")
        while current in dispositions and dispositions[current].get("disposition") == "DUPLICATE":
            if current in seen:
                errors.append(f"duplicate candidate {candidate_id!r} forms a cycle")
                break
            seen.add(current)
            current = dispositions[current].get("canonical_candidate_id")

    coverage_rows = _list(document.get("coverage"), "coverage", errors)
    coverage: dict[str, dict[str, Any]] = {}
    for position, raw in enumerate(coverage_rows):
        row = _object(raw, f"coverage[{position}]", errors)
        check_id = _text(row, "check_id", f"coverage[{position}]", errors)
        if check_id in coverage:
            errors.append(f"coverage repeats check ID {check_id!r}")
        elif check_id:
            coverage[check_id] = row
        if check_id not in catalog:
            errors.append(f"coverage references unknown check {check_id!r}")
        status = row.get("status")
        if status not in COVERAGE_STATUSES:
            errors.append(f"coverage {check_id!r} has invalid status")
        evidence_ids = _strings(row.get("evidence_ids", []), f"coverage {check_id!r}.evidence_ids", errors)
        finding_ids = _strings(row.get("finding_ids", []), f"coverage {check_id!r}.finding_ids", errors)
        for evidence_id in evidence_ids:
            if evidence_id not in evidence:
                errors.append(f"coverage {check_id!r} references unknown evidence {evidence_id!r}")
        for finding_id in finding_ids:
            if finding_id not in findings:
                errors.append(f"coverage {check_id!r} references unknown finding {finding_id!r}")
            elif check_id not in _string_values(findings[finding_id].get("check_ids")):
                errors.append(f"coverage {check_id!r} links finding {finding_id!r} without the check")
        if status == "PASS" and (not evidence_ids or finding_ids):
            errors.append(f"PASS coverage {check_id!r} needs evidence and no finding")
        if status == "PASS":
            support = [evidence[item] for item in evidence_ids if item in evidence]
            owner = catalog.get(check_id, {}).get("owner")
            allowed_types = {
                "SCANNER": {"STATIC_CONFIG", "INSTALLED_VERSION", "TEST_FIXTURE"},
                "REVIEWER": EVIDENCE_TYPES - {"INFERENCE"},
                "LIVE": {"SDK_RUNTIME", "LIVE_DEPLOYMENT"},
            }.get(owner, set())
            if not any(
                item.get("type") in allowed_types
                and _has_locator(item)
                and _evidence_supports_check(item, check_id)
                for item in support
            ):
                errors.append(f"PASS coverage {check_id!r} needs locatable non-inference evidence bound to the check")
        if status == "FINDING" and not finding_ids:
            errors.append(f"FINDING coverage {check_id!r} must link a finding")
        if status in {"NA", "UNVERIFIED"}:
            _text(row, "rationale", f"coverage {check_id!r}", errors)
            if finding_ids:
                errors.append(f"{status} coverage {check_id!r} must not link a finding")
        if status == "UNVERIFIED":
            _text(row, "next_action", f"coverage {check_id!r}", errors)
    missing = set(catalog) - set(coverage)
    if missing:
        errors.append("coverage is missing catalog IDs: " + ", ".join(sorted(missing)))
    for finding_id, finding in findings.items():
        for check_id in _string_values(finding.get("check_ids")):
            ledger = coverage.get(check_id, {})
            if ledger.get("status") != "FINDING" or finding_id not in _string_values(ledger.get("finding_ids")):
                errors.append(
                    f"finding {finding_id!r} is not represented by FINDING coverage {check_id!r}"
                )
    for root_id, root in roots.items():
        retained = set(_strings(root.get("evidence_ids", []), f"root cause {root_id!r}.evidence_ids", errors))
        required = {
            evidence_id
            for finding_id in _string_values(root.get("finding_ids"))
            for evidence_id in _string_values(findings.get(finding_id, {}).get("evidence_ids"))
        }
        if not required.issubset(retained):
            errors.append(
                f"root cause {root_id!r} drops finding evidence: "
                + ", ".join(sorted(required - retained))
            )
    for finding_id, finding in findings.items():
        root_id = finding.get("root_cause_id")
        if root_id in roots and finding_id not in _string_values(roots[root_id].get("finding_ids")):
            errors.append(f"finding {finding_id!r} is missing from root cause {root_id!r}")

    scan_document = _object(scan, "scan", errors) if scan is not None else None
    if scan_document is not None:
        if scan_document.get("schema_version") != SCAN_SCHEMA_VERSION:
            errors.append(f"scan.schema_version must be {SCAN_SCHEMA_VERSION!r}")
        scope = _object(document.get("scope"), "scope", errors)
        if scope.get("normalized_target") != scan_document.get("target"):
            errors.append("report scope.normalized_target does not match scan target")
        if scope.get("normalized_runtime_root") != scan_document.get("runtime_root"):
            errors.append("report scope.normalized_runtime_root does not match scan runtime_root")
        scan_rows = _list(scan_document.get("candidates"), "scan.candidates", errors)
        scan_candidates: dict[str, dict[str, Any]] = {}
        for position, raw in enumerate(scan_rows):
            row = _object(raw, f"scan.candidates[{position}]", errors)
            candidate_id = _text(
                row,
                "candidate_id",
                f"scan.candidates[{position}]",
                errors,
            )
            _text(row, "rule_id", f"scan.candidates[{position}]", errors)
            if row.get("severity") not in SEVERITIES:
                errors.append(f"scan candidate {candidate_id!r} has invalid severity")
            scan_evidence = _list(
                row.get("evidence"),
                f"scan candidate {candidate_id!r}.evidence",
                errors,
            )
            if not scan_evidence:
                errors.append(f"scan candidate {candidate_id!r} must retain evidence")
            if candidate_id in scan_candidates:
                errors.append(f"scan.candidates repeats candidate_id {candidate_id!r}")
            elif candidate_id:
                scan_candidates[candidate_id] = row
        if set(scan_candidates) != set(candidates):
            errors.append("report candidates do not form an exact closure over scan candidates")
        for candidate_id, scan_candidate in scan_candidates.items():
            report_candidate = candidates.get(candidate_id, {})
            if report_candidate.get("severity") != scan_candidate.get("severity"):
                errors.append(f"candidate {candidate_id!r} severity does not match scan")
            if report_candidate.get("rule_id") != scan_candidate.get("rule_id"):
                errors.append(f"candidate {candidate_id!r} rule_id does not match scan")
            report_evidence = [
                evidence[item]
                for item in _string_values(report_candidate.get("evidence_ids"))
                if item in evidence
            ]
            for scan_evidence in _list(
                scan_candidate.get("evidence"),
                f"scan candidate {candidate_id!r}.evidence",
                errors,
            ):
                if not isinstance(scan_evidence, dict):
                    errors.append(f"scan candidate {candidate_id!r} evidence must be an object")
                    continue
                if not any(
                    item.get("scope") == scan_evidence.get("scope")
                    and item.get("path") == scan_evidence.get("path")
                    and item.get("line") == scan_evidence.get("line")
                    for item in report_evidence
                ):
                    errors.append(f"candidate {candidate_id!r} drops a scan evidence locator")
    elif document.get("status") == "COMPLETE":
        errors.append("COMPLETE reports must be validated against a scan/v2 artifact")

    incomplete = any(row.get("status") == "UNVERIFIED" for row in coverage.values())
    incomplete |= any(row.get("disposition") == "UNVERIFIED" for row in dispositions.values())
    incomplete |= any(
        item.get("status") == "UNVERIFIED"
        for row in finding_rows
        for item in (row.get("applicability") if isinstance(row.get("applicability"), dict) else {}).values()
        if isinstance(item, dict)
    )
    incomplete |= scan_document is None
    expected_status = "INCOMPLETE" if incomplete else "COMPLETE"
    if document.get("status") != expected_status:
        errors.append(f"status must be {expected_status} for the recorded verification state")

    if errors:
        raise ReviewValidationError("\n".join(f"- {message}" for message in errors))
    return document


def _cell(value: Any) -> str:
    return str(value or "—").replace("|", r"\|").replace("\r", " ").replace("\n", " ")


def render_markdown(review: dict[str, Any], catalog: dict[str, dict[str, str]]) -> str:
    """从已校验对象渲染全量索引与 P0/P1 详情。"""
    scope = review["scope"]
    evidence = {row["id"]: row for row in review["evidence"]}
    findings = {row["id"]: row for row in review["findings"]}
    dispositions = {row["candidate_id"]: row for row in review["candidate_dispositions"]}
    lines = [
        "# Claude Code Configuration Review", "",
        "## Review status and scope", "",
        f"- Status: `{_cell(review['status'])}`",
        f"- Host agent: `{_cell(scope['host_agent'])}`",
        f"- Requested target: `{_cell(scope['requested_target'])}`",
        f"- Normalized target: `{_cell(scope['normalized_target'])}`", "",
        "## Full coverage index", "",
        "| Check | Owner | Status | Findings | Evidence | Rationale / next action |",
        "|---|---|---|---|---|---|",
    ]
    for row in review["coverage"]:
        meta = catalog[row["check_id"]]
        note = row.get("next_action") or row.get("rationale") or ""
        lines.append("| " + " | ".join(map(_cell, (
            row["check_id"], meta["owner"], row["status"],
            ", ".join(row.get("finding_ids", [])),
            ", ".join(row.get("evidence_ids", [])), note,
        ))) + " |")
    lines.extend(["", "## Full finding index", "", "| Finding | Severity | Class | Checks | Root cause | Evidence |", "|---|---|---|---|---|---|"])
    for row in review["findings"]:
        lines.append("| " + " | ".join(map(_cell, (
            row["id"], row["severity"], row["class"], ", ".join(row["check_ids"]),
            row["root_cause_id"], ", ".join(row["evidence_ids"]),
        ))) + " |")
    lines.extend(["", "## P0/P1 detailed findings", ""])
    critical = [row for row in review["findings"] if row["severity"] in {"P0", "P1"}]
    if not critical:
        lines.append("No P0/P1 findings.")
    for row in critical:
        lines.extend([f"### [{_cell(row['id'])}] [{row['severity']}] {_cell(row['title'])}", "", f"- Class: `{_cell(row['class'])}`", f"- Checks: `{_cell(', '.join(row['check_ids']))}`", f"- Root cause: `{_cell(row['root_cause_id'])}`", "- Evidence:"])
        for evidence_id in row["evidence_ids"]:
            item = evidence[evidence_id]
            location = item.get("source_url") or item.get("path") or item.get("command") or "structured assertion"
            lines.append(f"  - `{_cell(evidence_id)}` [{_cell(item['type'])}] {_cell(location)} — {_cell(item['summary'])}")
        lines.append("- Applicability:")
        for layer in sorted(APPLICABILITY_LAYERS):
            item = row["applicability"][layer]
            lines.append(f"  - `{layer}`: `{item['status']}` — {_cell(item['rationale'])}")
        lines.append("")
    lines.extend(["## P0/P1 candidate disposition ledger", "", "| Candidate | Severity | Disposition | Finding/canonical | Evidence | Rationale / next action |", "|---|---|---|---|---|---|"])
    for candidate in review["candidates"]:
        if candidate["severity"] not in {"P0", "P1"}:
            continue
        row = dispositions[candidate["id"]]
        destination = row.get("canonical_candidate_id") or ", ".join(row.get("finding_ids", []))
        note = row.get("next_action") or row.get("rationale")
        lines.append("| " + " | ".join(map(_cell, (candidate["id"], candidate["severity"], row["disposition"], destination, ", ".join(row.get("evidence_ids", [])), note))) + " |")
    lines.extend(["", "## Root causes", ""])
    for row in review["root_causes"]:
        lines.append(f"- **{_cell(row['id'])} — {_cell(row['title'])}**: {_cell(', '.join(row['finding_ids']))}")
    lines.extend(["", "## Unknowns / unverified items", ""])
    unknowns: list[str] = []
    unknowns.extend(f"Coverage {row['check_id']}: {row.get('next_action')}" for row in review["coverage"] if row["status"] == "UNVERIFIED")
    unknowns.extend(f"Candidate {key}: {row.get('next_action')}" for key, row in dispositions.items() if row["disposition"] == "UNVERIFIED")
    lines.extend(f"- {_cell(item)}" for item in unknowns)
    if not unknowns:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def _load_json(path: Path) -> Any:
    def unique(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    with path.open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=unique)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an agent-config-reviewer report")
    parser.add_argument("review", type=Path)
    parser.add_argument("--catalog", type=Path, default=ROOT / "references/check-catalog.md")
    parser.add_argument("--scan", type=Path, help="bind the report to an agent-config-reviewer-scan/v2 artifact")
    parser.add_argument("--markdown", metavar="PATH", help="write Markdown to PATH or - for stdout")
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        scan = _load_json(args.scan) if args.scan else None
        review = validate_review(_load_json(args.review), catalog, scan)
    except ReviewValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.markdown:
        content = render_markdown(review, catalog)
        try:
            if args.markdown == "-":
                sys.stdout.write(content)
            else:
                Path(args.markdown).write_text(content, encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    else:
        print("PASS: review contract is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
