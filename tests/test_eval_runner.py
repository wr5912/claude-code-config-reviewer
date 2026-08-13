from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import run_evals


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class EvalRunnerTests(unittest.TestCase):
    def test_canonical_suite_contains_and_validates_exactly_eight_fixtures(self) -> None:
        cases = run_evals.load_suite(REPOSITORY_ROOT / "evals" / "cases.json")

        self.assertEqual(list(run_evals.CASE_IDS), [case["id"] for case in cases])
        self.assertEqual(
            {"normal", "edge", "adversarial", "wrong-context"},
            {case["category"] for case in cases},
        )

    def test_validate_only_cli_passes(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/run_evals.py", "--validate-only", "--format", "json"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual("PASS", result["status"])
        self.assertEqual(8, result["validated_cases"])

    def test_scanner_suite_reaches_critical_gate_without_claiming_review_layers(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/run_evals.py", "--format", "json"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual("PASS", result["status"])
        self.assertEqual("PASS", result["metrics"]["critical_recall"]["status"])
        self.assertEqual("PASS", result["metrics"]["false_official"]["status"])
        for name in ("disposition_coverage", "catalog_coverage", "finding_completeness"):
            self.assertEqual("INVALID", result["metrics"][name]["status"])

    def test_review_mode_scores_structured_layers_without_keyword_matching(self) -> None:
        cases = run_evals.load_suite(REPOSITORY_ROOT / "evals" / "cases.json")
        catalog = run_evals.catalog_ids()
        artifacts = {}
        for case in cases:
            evidence = []
            candidates = []
            findings = []
            dispositions = []
            disposition_values = iter(case["expectations"]["dispositions"])

            def add_evidence(locators):
                ids = []
                for locator in locators:
                    evidence_id = f"E-{len(evidence) + 1}"
                    row = {
                        "id": evidence_id,
                        "type": "STATIC_CONFIG",
                        "summary": "独立摘要，不复制 gold anchor。",
                        "path": locator["path"],
                    }
                    if "line" in locator:
                        row["line"] = locator["line"]
                    evidence.append(row)
                    ids.append(evidence_id)
                return ids

            for index, expected in enumerate(case["expectations"]["candidates"]):
                candidate_id = f"C-{index + 1}"
                candidates.append({
                    "id": candidate_id,
                    "rule_id": expected["rule_id"],
                    "severity": expected["severity"],
                    "evidence_ids": add_evidence(expected["evidence"]),
                })
                if expected["severity"] in {"P0", "P1"}:
                    disposition = next(disposition_values)
                    dispositions.append({
                        "candidate_id": candidate_id,
                        "disposition": disposition["disposition"],
                    })
            for index, expected in enumerate(case["expectations"]["findings"]):
                findings.append({
                    "id": f"F-{index + 1}",
                    "severity": expected["severity"],
                    "class": expected["class"],
                    "evidence_ids": add_evidence(expected["evidence"]),
                    "applicability": {
                        layer: {
                            "status": "APPLIES" if layer in expected["applicability"] else "DOES_NOT_APPLY"
                        }
                        for layer in run_evals.APPLICABILITY
                    },
                })
            artifacts[case["id"]] = {
                "schema_version": "agent-config-reviewer-report/v2",
                "evidence": evidence,
                "candidates": candidates,
                "candidate_dispositions": dispositions,
                "coverage": [
                    {"check_id": check_id, "status": "NA"}
                    for check_id in catalog
                ],
                "findings": findings,
            }

        result = run_evals.score(cases, artifacts, review_mode=True)

        self.assertEqual("PASS", result["status"])
        self.assertTrue(all(metric["status"] == "PASS" for metric in result["metrics"].values()))

    def test_case_path_cannot_escape_suite_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            suite = {
                "schema_version": run_evals.SUITE_SCHEMA,
                "cases": [
                    {"id": case_id, "path": "../outside.json"}
                    for case_id in run_evals.CASE_IDS
                ],
            }
            path = root / "cases.json"
            path.write_text(json.dumps(suite), encoding="utf-8")

            with self.assertRaisesRegex(run_evals.EvalError, "escapes or does not exist"):
                run_evals.load_suite(path)

    def test_anchor_validation_rejects_stale_gold(self) -> None:
        source = run_evals.load_suite(REPOSITORY_ROOT / "evals" / "cases.json")[3]
        case = copy.deepcopy(source)
        case.pop("_path", None)
        case["expectations"]["candidates"][0]["evidence"][0]["anchor"] = "absent-anchor"
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "fixture"
            source_root = Path(source["_path"]).parent
            import shutil

            shutil.copytree(source_root, destination)
            path = destination / "case.json"
            path.write_text(json.dumps(case), encoding="utf-8")

            with self.assertRaisesRegex(run_evals.EvalError, "anchor is absent"):
                run_evals.validate_case(path, source["id"])

    def test_zero_denominator_is_invalid(self) -> None:
        self.assertEqual("INVALID", run_evals.metric(0, 0)["status"])


if __name__ == "__main__":
    unittest.main()
