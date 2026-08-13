#!/usr/bin/env python3
"""校验并运行八个合成评估夹具；不会执行夹具中的任何代码。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "evals" / "cases.json"
DEFAULT_SCANNER = ROOT / "scripts" / "scan_project.py"
CATALOG = ROOT / "references" / "check-catalog.md"
SUITE_SCHEMA = "agent-config-reviewer-evals/v2"
CASE_SCHEMA = "agent-config-reviewer-eval-case/v2"
CASE_IDS = (
    "normal-clean",
    "hook-shell-paths",
    "hook-exec-paths",
    "hook-unresolved",
    "split-runtime-root",
    "state-store-isolation",
    "route-capability-bypass",
    "wrong-context-noise",
)
CATEGORIES = {"normal", "edge", "adversarial", "wrong-context"}
SEVERITIES = {"P0", "P1", "P2", "P3"}
DISPOSITIONS = {"CONFIRMED", "DOWNGRADED", "DISMISSED", "DUPLICATE", "UNVERIFIED"}
APPLICABILITY = {
    "STATIC_CONFIG", "OFFICIAL_SEMANTICS", "INSTALLED_VERSION",
    "SDK_RUNTIME", "LIVE_DEPLOYMENT",
}
CATALOG_ID = re.compile(r"^- \[([A-N]-\d{3})\] \[(?:SCANNER|REVIEWER|LIVE)\] ", re.M)


class EvalError(ValueError):
    """表示 suite、夹具、scanner 或 review artifact 不满足评估契约。"""


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise EvalError(f"duplicate JSON key: {key}")
        obj[key] = value
    return obj


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvalError(f"JSON root must be an object: {path}")
    return value


def exact_keys(value: dict[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise EvalError(f"{where}: keys mismatch; missing={missing}, extra={extra}")


def contained(base: Path, raw: str, kind: str) -> Path:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise EvalError(f"{kind} must be a non-empty relative path: {raw!r}")
    path = base / raw
    try:
        resolved_base = base.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_base)
    except (OSError, RuntimeError, ValueError) as exc:
        raise EvalError(f"{kind} escapes or does not exist: {raw}") from exc
    if path.is_symlink():
        raise EvalError(f"{kind} must not be a symbolic link: {raw}")
    return resolved


def assert_no_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise EvalError(f"fixture contains a symbolic link: {path}")


def validate_locator(locator: Any, roots: dict[str, Path], where: str) -> None:
    if not isinstance(locator, dict):
        raise EvalError(f"{where} must be an object")
    allowed = {"scope", "path", "line", "anchor"}
    if set(locator) - allowed or not {"scope", "path", "anchor"} <= set(locator):
        raise EvalError(f"{where} must contain scope/path/anchor and optional line")
    scope = locator["scope"]
    if scope not in roots:
        raise EvalError(f"{where}.scope has no fixture root: {scope!r}")
    path = contained(roots[scope], locator["path"], f"{where}.path")
    if not path.is_file():
        raise EvalError(f"{where}.path must be a file: {locator['path']}")
    anchor = locator["anchor"]
    if not isinstance(anchor, str) or not anchor:
        raise EvalError(f"{where}.anchor must be a non-empty string")
    text = path.read_text(encoding="utf-8", errors="replace")
    line = locator.get("line")
    if line is not None:
        if not isinstance(line, int) or line < 1:
            raise EvalError(f"{where}.line must be a positive integer")
        lines = text.splitlines()
        if line > len(lines) or anchor not in lines[line - 1]:
            raise EvalError(f"{where}: anchor is absent from declared line")
    elif anchor not in text:
        raise EvalError(f"{where}: anchor is absent from fixture source")


def validate_expected_item(item: Any, roots: dict[str, Path], where: str, finding: bool) -> None:
    if not isinstance(item, dict):
        raise EvalError(f"{where} must be an object")
    required = {"finding_id", "severity", "class", "evidence", "applicability"} if finding else {"rule_id", "severity", "evidence"}
    exact_keys(item, required, where)
    identity = item["finding_id"] if finding else item["rule_id"]
    if not isinstance(identity, str) or not identity:
        raise EvalError(f"{where} identity must be a non-empty string")
    if item["severity"] not in SEVERITIES:
        raise EvalError(f"{where}.severity is invalid")
    evidence = item["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise EvalError(f"{where}.evidence must be a non-empty array")
    for index, locator in enumerate(evidence):
        validate_locator(locator, roots, f"{where}.evidence[{index}]")
    if finding:
        if not isinstance(item["class"], str) or not item["class"]:
            raise EvalError(f"{where}.class must be non-empty")
        layers = item["applicability"]
        if not isinstance(layers, list) or not layers or len(layers) != len(set(layers)):
            raise EvalError(f"{where}.applicability must be a unique non-empty array")
        if not set(layers) <= APPLICABILITY:
            raise EvalError(f"{where}.applicability contains an unknown layer")


def validate_case(path: Path, expected_id: str) -> dict[str, Any]:
    case = load_json(path)
    exact_keys(case, {"schema_version", "id", "category", "target", "runtime_root", "runtime", "expectations"}, str(path))
    if case["schema_version"] != CASE_SCHEMA or case["id"] != expected_id:
        raise EvalError(f"case identity/schema mismatch: {path}")
    if case["category"] not in CATEGORIES:
        raise EvalError(f"invalid category in {path}")
    if case["runtime"] not in {"auto", "cli", "agent-sdk", "both", "unknown"}:
        raise EvalError(f"invalid runtime in {path}")
    case_root = path.parent.resolve()
    assert_no_symlinks(case_root)
    target = contained(case_root, case["target"], "target")
    if not target.is_dir() or path.resolve() == target or target in path.resolve().parents:
        raise EvalError(f"case gold must remain outside target: {path}")
    roots = {"target": target}
    runtime_raw = case["runtime_root"]
    if runtime_raw is not None:
        runtime = contained(case_root, runtime_raw, "runtime_root")
        if not runtime.is_dir() or runtime == target:
            raise EvalError("explicit runtime_root must be a distinct directory")
        roots["runtime"] = runtime
    expectations = case["expectations"]
    if not isinstance(expectations, dict):
        raise EvalError(f"expectations must be an object: {path}")
    exact_keys(expectations, {"candidates", "findings", "dispositions", "forbidden_official_ids"}, f"{path}.expectations")
    for field in ("candidates", "findings", "dispositions", "forbidden_official_ids"):
        if not isinstance(expectations[field], list):
            raise EvalError(f"{path}.expectations.{field} must be an array")
    for index, item in enumerate(expectations["candidates"]):
        validate_expected_item(item, roots, f"{path}.candidates[{index}]", False)
    for index, item in enumerate(expectations["findings"]):
        validate_expected_item(item, roots, f"{path}.findings[{index}]", True)
    for index, item in enumerate(expectations["dispositions"]):
        if not isinstance(item, dict):
            raise EvalError(f"{path}.dispositions[{index}] must be an object")
        exact_keys(item, {"rule_id", "disposition"}, f"{path}.dispositions[{index}]")
        if not isinstance(item["rule_id"], str) or item["disposition"] not in DISPOSITIONS:
            raise EvalError(f"invalid expected disposition in {path}")
    forbidden = expectations["forbidden_official_ids"]
    if any(not isinstance(item, str) or not item for item in forbidden) or len(forbidden) != len(set(forbidden)):
        raise EvalError(f"forbidden_official_ids must contain unique strings: {path}")
    case["_path"] = str(path)
    return case


def load_suite(path: Path, selected: set[str] | None = None) -> list[dict[str, Any]]:
    suite = load_json(path)
    exact_keys(suite, {"schema_version", "cases"}, str(path))
    if suite["schema_version"] != SUITE_SCHEMA or not isinstance(suite["cases"], list):
        raise EvalError("invalid eval suite schema")
    entries = suite["cases"]
    ids: list[str] = []
    cases: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise EvalError(f"cases[{index}] must be an object")
        exact_keys(entry, {"id", "path"}, f"cases[{index}]")
        ids.append(entry["id"])
        case_path = contained(path.parent, entry["path"], f"cases[{index}].path")
        if selected is None or entry["id"] in selected:
            cases.append(validate_case(case_path, entry["id"]))
    if tuple(ids) != CASE_IDS:
        raise EvalError(f"suite must contain exactly the eight canonical cases in order: {CASE_IDS}")
    if selected is not None and selected - set(ids):
        raise EvalError(f"unknown case IDs: {sorted(selected - set(ids))}")
    return cases


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise EvalError(f"symbolic links are forbidden in eval workspaces: {relative}")
        digest.update(relative.encode("utf-8") + b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def run_scanner(case: dict[str, Any], scanner: Path) -> dict[str, Any]:
    source = Path(case["_path"]).parent
    with tempfile.TemporaryDirectory(prefix=f"agent-config-reviewer-eval-{case['id']}-") as temporary:
        workspace = Path(temporary) / "fixture"
        shutil.copytree(source, workspace)
        target = workspace / case["target"]
        before = tree_hash(workspace)
        command = [sys.executable, str(scanner), "--target", str(target), "--runtime", case["runtime"], "--format", "json"]
        if case["runtime_root"] is not None:
            command.extend(["--runtime-root", str(workspace / case["runtime_root"])])
        completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=30)
        after = tree_hash(workspace)
        if before != after:
            raise EvalError(f"scanner modified fixture {case['id']}")
        if completed.returncode != 0:
            raise EvalError(f"scanner failed for {case['id']}: {completed.stderr.strip()}")
        try:
            output = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise EvalError(f"scanner returned invalid JSON for {case['id']}: {exc}") from exc
        if not isinstance(output, dict):
            raise EvalError(f"scanner output must be an object for {case['id']}")
        return output


def actual_candidates(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    values = artifact.get("candidates")
    if not isinstance(values, list):
        values = artifact.get("findings", [])
    return hydrate_evidence(artifact, values)


def actual_findings(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    if artifact.get("schema_version") == "agent-config-reviewer-scan/v2":
        return []
    values = artifact.get("findings", [])
    return hydrate_evidence(artifact, values)


def hydrate_evidence(artifact: dict[str, Any], values: Any) -> list[dict[str, Any]]:
    """兼容 scanner 内联证据与 report/v2 的 evidence_ids 引用。"""
    if not isinstance(values, list):
        return []
    registry = {
        item["id"]: item
        for item in artifact.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    hydrated: list[dict[str, Any]] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if not isinstance(item.get("evidence"), list):
            item["evidence"] = [
                registry[evidence_id]
                for evidence_id in item.get("evidence_ids", [])
                if evidence_id in registry
            ]
        hydrated.append(item)
    return hydrated


def identity(item: dict[str, Any]) -> str:
    return str(item.get("rule_id") or item.get("finding_id") or item.get("id") or "")


def evidence_matches(locator: dict[str, Any], evidence: dict[str, Any]) -> bool:
    if evidence.get("path") != locator["path"]:
        return False
    if evidence.get("scope") is not None and evidence["scope"] != locator["scope"]:
        return False
    if "line" in locator and evidence.get("line") != locator["line"]:
        return False
    # scanner 提供原始 text，可直接核验 anchor；report/v2 只要求摘要，不能依赖措辞匹配。
    if isinstance(evidence.get("text"), str):
        return locator["anchor"] in evidence["text"]
    return True


def item_matches(expected: dict[str, Any], actual: dict[str, Any], finding: bool) -> bool:
    expected_id = expected["finding_id"] if finding else expected["rule_id"]
    if (not finding and identity(actual) != expected_id) or actual.get("severity") != expected["severity"]:
        return False
    if finding and actual.get("class") != expected["class"]:
        return False
    if finding:
        applicability = actual.get("applicability")
        if not isinstance(applicability, dict) or any(
            not isinstance(applicability.get(layer), dict)
            or applicability[layer].get("status") != "APPLIES"
            for layer in expected["applicability"]
        ):
            return False
    evidence = actual.get("evidence", [])
    if not isinstance(evidence, list):
        return False
    return all(any(isinstance(item, dict) and evidence_matches(locator, item) for item in evidence) for locator in expected["evidence"])


def match_items(expected: list[dict[str, Any]], actual: list[dict[str, Any]], finding: bool) -> tuple[int, list[int]]:
    used: set[int] = set()
    matched = 0
    for wanted in expected:
        for index, item in enumerate(actual):
            if index not in used and item_matches(wanted, item, finding):
                used.add(index)
                matched += 1
                break
    return matched, sorted(used)


def metric(numerator: int, denominator: int, target: int | None = None) -> dict[str, Any]:
    if denominator == 0:
        return {"status": "INVALID", "numerator": numerator, "denominator": denominator, "value": None}
    value = numerator / denominator
    desired = denominator if target is None else target
    return {"status": "PASS" if numerator == desired else "FAIL", "numerator": numerator, "denominator": denominator, "value": value}


def invalid_metric(reason: str) -> dict[str, Any]:
    return {"status": "INVALID", "numerator": None, "denominator": None, "value": None, "reason": reason}


def count_metric(value: int, expected: int = 0) -> dict[str, Any]:
    return {"status": "PASS" if value == expected else "FAIL", "value": value, "expected": expected}


def catalog_ids() -> set[str]:
    ids = CATALOG_ID.findall(CATALOG.read_text(encoding="utf-8"))
    if not ids or len(ids) != len(set(ids)):
        raise EvalError("catalog IDs are empty or duplicated")
    return set(ids)


def score(cases: list[dict[str, Any]], artifacts: dict[str, dict[str, Any]], review_mode: bool) -> dict[str, Any]:
    critical_total = critical_matched = 0
    false_official = 0
    disposition_total = disposition_ok = 0
    coverage_total = coverage_ok = 0
    finding_total = finding_ok = 0
    missing_review_layer = False
    all_catalog = catalog_ids()
    case_results: list[dict[str, Any]] = []
    for case in cases:
        artifact = artifacts[case["id"]]
        candidates = actual_candidates(artifact)
        findings = actual_findings(artifact)
        expectations = case["expectations"]
        candidate_matches, _ = match_items(expectations["candidates"], candidates, False)
        finding_matches, _ = match_items(expectations["findings"], findings, True)
        expected_critical_candidates = [item for item in expectations["candidates"] if item["severity"] in {"P0", "P1"}]
        matched_critical_candidates, _ = match_items(expected_critical_candidates, candidates, False)
        critical_total += len(expected_critical_candidates)
        critical_matched += matched_critical_candidates
        if review_mode:
            expected_critical_findings = [item for item in expectations["findings"] if item["severity"] in {"P0", "P1"}]
            matched_critical_findings, _ = match_items(expected_critical_findings, findings, True)
            critical_total += len(expected_critical_findings)
            critical_matched += matched_critical_findings
        forbidden = set(expectations["forbidden_official_ids"])
        for item in [*candidates, *findings]:
            item_id = identity(item)
            item_class = str(item.get("class") or item.get("cls") or "")
            if item_id.startswith("O-") or item_class.startswith("OFFICIAL-"):
                if item_id in forbidden:
                    false_official += 1
        if review_mode:
            dispositions = artifact.get("candidate_dispositions")
            coverage = artifact.get("coverage")
            if not isinstance(dispositions, list) or not isinstance(coverage, list):
                missing_review_layer = True
            else:
                expected_dispositions = Counter(
                    (item["rule_id"], item["disposition"])
                    for item in expectations["dispositions"]
                )
                expected_rules = {item["rule_id"] for item in expectations["dispositions"]}
                disposition_by_candidate: dict[str, list[dict[str, Any]]] = {}
                for item in dispositions:
                    if isinstance(item, dict):
                        disposition_by_candidate.setdefault(str(item.get("candidate_id", "")), []).append(item)
                for candidate in candidates:
                    if candidate.get("severity") not in {"P0", "P1"}:
                        continue
                    disposition_total += 1
                    entries = disposition_by_candidate.get(str(candidate.get("id") or candidate.get("candidate_id") or ""), [])
                    if len(entries) != 1 or entries[0].get("disposition") not in DISPOSITIONS:
                        continue
                    rule_id = identity(candidate)
                    pair = (rule_id, entries[0]["disposition"])
                    if rule_id in expected_rules:
                        if expected_dispositions[pair] == 0:
                            continue
                        expected_dispositions[pair] -= 1
                    disposition_ok += 1
                missing_expected = sum(expected_dispositions.values())
                disposition_total += missing_expected
                rows: dict[str, list[dict[str, Any]]] = {}
                for item in coverage:
                    if isinstance(item, dict):
                        rows.setdefault(str(item.get("check_id", "")), []).append(item)
                coverage_total += len(all_catalog)
                coverage_ok += sum(
                    len(rows.get(check_id, [])) == 1
                    and rows[check_id][0].get("status") in {"PASS", "FINDING", "NA", "UNVERIFIED"}
                    for check_id in all_catalog
                )
            for finding in findings:
                finding_total += 1
                evidence = finding.get("evidence_ids")
                applicability = finding.get("applicability")
                valid_layers = (
                    isinstance(applicability, dict)
                    and set(applicability) == APPLICABILITY
                    and all(
                        isinstance(item, dict)
                        and item.get("status") in {"APPLIES", "DOES_NOT_APPLY", "UNVERIFIED"}
                        for item in applicability.values()
                    )
                )
                if isinstance(evidence, list) and evidence and valid_layers:
                    finding_ok += 1
        case_results.append({
            "id": case["id"],
            "expected_candidates": len(expectations["candidates"]),
            "matched_candidates": candidate_matches,
            "expected_findings": len(expectations["findings"]),
            "matched_findings": finding_matches,
        })
    metrics: dict[str, Any] = {
        "critical_recall": metric(critical_matched, critical_total),
        "false_official": count_metric(false_official),
    }
    if review_mode and not missing_review_layer:
        metrics["disposition_coverage"] = metric(disposition_ok, disposition_total)
        metrics["catalog_coverage"] = metric(coverage_ok, coverage_total)
        metrics["finding_completeness"] = metric(finding_ok, finding_total)
    else:
        reason = "scanner-only artifacts do not contain reviewer disposition/coverage/applicability"
        metrics["disposition_coverage"] = invalid_metric(reason)
        metrics["catalog_coverage"] = invalid_metric(reason)
        metrics["finding_completeness"] = invalid_metric(reason)
    status = "PASS"
    if any(value["status"] == "FAIL" for value in metrics.values()):
        status = "FAIL"
    elif review_mode and any(value["status"] == "INVALID" for value in metrics.values()):
        status = "INVALID"
    return {"schema_version": "agent-config-reviewer-eval-result/v2", "status": status, "mode": "review" if review_mode else "scanner-only", "cases": case_results, "metrics": metrics}


def format_text(result: dict[str, Any]) -> str:
    lines = [f"Eval status: {result['status']}", f"Mode: {result.get('mode', 'validate-only')}"]
    if "validated_cases" in result:
        lines.append(f"Validated cases: {result['validated_cases']}")
    for name, value in result.get("metrics", {}).items():
        rendered = "INVALID" if value["value"] is None else f"{value['value']:.3f}"
        lines.append(f"- {name}: {value['status']} ({rendered})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default=str(DEFAULT_SUITE))
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--scanner", default=str(DEFAULT_SCANNER))
    parser.add_argument("--reports-dir")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        selected = set(args.cases) if args.cases else None
        cases = load_suite(Path(args.suite).resolve(strict=True), selected)
        if args.validate_only:
            result = {"schema_version": "agent-config-reviewer-eval-result/v2", "status": "PASS", "mode": "validate-only", "validated_cases": len(cases)}
        else:
            review_mode = args.reports_dir is not None
            artifacts: dict[str, dict[str, Any]] = {}
            if review_mode:
                reports = Path(args.reports_dir).resolve(strict=True)
                for case in cases:
                    artifacts[case["id"]] = load_json(contained(reports, f"{case['id']}.json", "review report"))
            else:
                scanner = Path(args.scanner).resolve(strict=True)
                if not scanner.is_file():
                    raise EvalError("scanner must be a file")
                artifacts = {case["id"]: run_scanner(case, scanner) for case in cases}
            result = score(cases, artifacts, review_mode)
    except (EvalError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"eval error: {exc}", file=sys.stderr)
        return 2
    content = json.dumps(result, ensure_ascii=False, indent=2) if args.format == "json" else format_text(result)
    if args.output:
        Path(args.output).write_text(content + "\n", encoding="utf-8")
    else:
        print(content)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
