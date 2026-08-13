from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from scripts import validate_review


class ReviewContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.catalog_path = Path(self.temp_dir.name) / "catalog.md"
        self.catalog_path.write_text(
            "# Catalog\n\n"
            "- [A-001] [SCANNER] Resolve target.\n"
            "- [H-001] [REVIEWER] Review hook.\n",
            encoding="utf-8",
        )
        self.catalog = validate_review.load_catalog(self.catalog_path)
        applicability = {
            "STATIC_CONFIG": {"status": "APPLIES", "rationale": "Target evidence applies.", "evidence_ids": ["E-HOOK"]},
            "OFFICIAL_SEMANTICS": {"status": "APPLIES", "rationale": "Official semantics apply.", "evidence_ids": ["E-OFFICIAL"]},
            "INSTALLED_VERSION": {"status": "DOES_NOT_APPLY", "rationale": "Not version-sensitive.", "evidence_ids": []},
            "SDK_RUNTIME": {"status": "DOES_NOT_APPLY", "rationale": "CLI fixture.", "evidence_ids": []},
            "LIVE_DEPLOYMENT": {"status": "DOES_NOT_APPLY", "rationale": "Static finding.", "evidence_ids": []},
        }
        self.valid = {
            "schema_version": validate_review.SCHEMA_VERSION,
            "status": "COMPLETE",
            "scope": {
                "host_agent": "codex",
                "requested_target": "fixture",
                "normalized_target": "/fixture",
                "target_kind": "project-root",
                "runtime_mode": "cli",
                "requested_runtime_root": None,
                "normalized_runtime_root": "/fixture",
                "excluded_assets": [".agents"],
            },
            "coverage": [
                {"check_id": "A-001", "status": "PASS", "evidence_ids": ["E-TARGET"], "finding_ids": []},
                {"check_id": "H-001", "status": "FINDING", "evidence_ids": ["E-HOOK"], "finding_ids": ["F-001"]},
            ],
            "candidates": [
                {"id": "C-001", "rule_id": "A-HOOK-REFERENCE", "severity": "P1", "check_ids": ["H-001"], "evidence_ids": ["E-HOOK"]}
            ],
            "candidate_dispositions": [
                {"candidate_id": "C-001", "disposition": "CONFIRMED", "rationale": "Confirmed by target and docs.", "evidence_ids": [], "finding_ids": ["F-001"]}
            ],
            "findings": [
                {"id": "F-001", "severity": "P1", "class": "OFFICIAL-SEMANTIC-ERROR", "title": "Unsafe hook", "check_ids": ["H-001"], "root_cause_id": "R-001", "evidence_ids": ["E-HOOK", "E-OFFICIAL"], "applicability": applicability}
            ],
            "evidence": [
                {"id": "E-TARGET", "type": "STATIC_CONFIG", "summary": "Target resolved.", "check_ids": ["A-001"], "path": ".claude/settings.json"},
                {"id": "E-HOOK", "type": "STATIC_CONFIG", "summary": "Hook uses shell form.", "check_ids": ["H-001"], "path": ".claude/settings.json", "line": 4},
                {"id": "E-OFFICIAL", "type": "OFFICIAL_SEMANTICS", "summary": "Current hook semantics.", "check_ids": ["H-001"], "source_url": "https://code.claude.com/docs/en/hooks"},
            ],
            "root_causes": [
                {"id": "R-001", "title": "Hook contract drift", "finding_ids": ["F-001"], "evidence_ids": ["E-HOOK", "E-OFFICIAL"]}
            ],
        }
        self.scan = {
            "schema_version": validate_review.SCAN_SCHEMA_VERSION,
            "target": "/fixture",
            "runtime_root": "/fixture",
            "candidates": [
                {
                    "candidate_id": "C-001",
                    "rule_id": "A-HOOK-REFERENCE",
                    "severity": "P1",
                    "evidence": [{"path": ".claude/settings.json", "line": 4}],
                }
            ],
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_valid_contract_and_markdown_indexes(self) -> None:
        result = validate_review.validate_review(self.valid, self.catalog, self.scan)
        markdown = validate_review.render_markdown(result, self.catalog)

        self.assertIn("| A-001 | SCANNER | PASS |", markdown)
        self.assertIn("[F-001] [P1] Unsafe hook", markdown)
        self.assertIn("| C-001 | P1 | CONFIRMED |", markdown)

    def test_invalid_contracts_are_rejected_table_driven(self) -> None:
        cases = {
            "missing catalog coverage": lambda value: value["coverage"].pop(),
            "duplicate P1 disposition": lambda value: value["candidate_dispositions"].append(copy.deepcopy(value["candidate_dispositions"][0])),
            "PASS without evidence": lambda value: value["coverage"][0].update(evidence_ids=[]),
            "PASS with inference only": lambda value: value["evidence"][0].update(type="INFERENCE"),
            "official finding without official evidence": lambda value: value["findings"][0].update(evidence_ids=["E-HOOK"]),
            "finding without applicability layer": lambda value: value["findings"][0]["applicability"].pop("LIVE_DEPLOYMENT"),
            "root cause not bidirectional": lambda value: value["root_causes"][0].update(finding_ids=[]),
            "finding absent from coverage": lambda value: value["coverage"][1].update(status="PASS", finding_ids=[], evidence_ids=["E-HOOK"]),
            "root cause drops evidence": lambda value: value["root_causes"][0].update(evidence_ids=["E-HOOK"]),
            "unknown finding class": lambda value: value["findings"][0].update(**{"class": "OFFICIAL_NONCOMPLIANT"}),
            "applicability without layer evidence": lambda value: value["findings"][0]["applicability"]["LIVE_DEPLOYMENT"].update(status="APPLIES"),
            "malformed root evidence ids": lambda value: value["root_causes"][0].update(evidence_ids=1),
            "malformed applicability": lambda value: value["findings"][0].update(applicability=[]),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                value = copy.deepcopy(self.valid)
                mutate(value)
                with self.assertRaises(validate_review.ReviewValidationError):
                    validate_review.validate_review(value, self.catalog, self.scan)

    def test_complete_report_must_match_scan_candidate_closure(self) -> None:
        without_candidate = copy.deepcopy(self.valid)
        without_candidate["candidates"] = []
        without_candidate["candidate_dispositions"] = []
        with self.assertRaisesRegex(validate_review.ReviewValidationError, "exact closure"):
            validate_review.validate_review(without_candidate, self.catalog, self.scan)

        with self.assertRaisesRegex(validate_review.ReviewValidationError, "must be validated against"):
            validate_review.validate_review(self.valid, self.catalog)

        dropped_locator = copy.deepcopy(self.scan)
        dropped_locator["candidates"][0]["evidence"][0]["line"] = 9
        with self.assertRaisesRegex(validate_review.ReviewValidationError, "drops a scan evidence locator"):
            validate_review.validate_review(self.valid, self.catalog, dropped_locator)

        wrong_scope = copy.deepcopy(self.scan)
        wrong_scope["candidates"][0]["evidence"][0]["scope"] = "runtime"
        with self.assertRaisesRegex(validate_review.ReviewValidationError, "drops a scan evidence locator"):
            validate_review.validate_review(self.valid, self.catalog, wrong_scope)

        missing_identity = copy.deepcopy(self.scan)
        missing_identity["candidates"].append(
            {"rule_id": "O-MISSING-ID", "severity": "P0", "evidence": [{"scope": "target", "path": ".claude/settings.json", "line": 1}]}
        )
        with self.assertRaisesRegex(validate_review.ReviewValidationError, "candidate_id"):
            validate_review.validate_review(self.valid, self.catalog, missing_identity)

    def test_disposition_graph_rejects_cycles_and_severity_evasion(self) -> None:
        cycle = copy.deepcopy(self.valid)
        cycle["status"] = "INCOMPLETE"
        cycle["candidates"].append(
            {"id": "C-002", "rule_id": "A-HOOK-REFERENCE", "severity": "P1", "check_ids": ["H-001"], "evidence_ids": ["E-HOOK"]}
        )
        cycle["candidate_dispositions"] = [
            {"candidate_id": "C-001", "disposition": "DUPLICATE", "canonical_candidate_id": "C-002", "rationale": "Same cause.", "evidence_ids": [], "finding_ids": []},
            {"candidate_id": "C-002", "disposition": "DUPLICATE", "canonical_candidate_id": "C-001", "rationale": "Same cause.", "evidence_ids": [], "finding_ids": []},
        ]
        with self.assertRaisesRegex(validate_review.ReviewValidationError, "forms a cycle"):
            validate_review.validate_review(cycle, self.catalog)

        severity = copy.deepcopy(self.valid)
        severity["findings"][0]["severity"] = "P3"
        with self.assertRaisesRegex(validate_review.ReviewValidationError, "retain its severity"):
            validate_review.validate_review(severity, self.catalog, self.scan)

    def test_unverified_state_requires_incomplete_status(self) -> None:
        value = copy.deepcopy(self.valid)
        value["coverage"][0] = {
            "check_id": "A-001", "status": "UNVERIFIED", "evidence_ids": [],
            "finding_ids": [], "rationale": "Runtime unavailable.",
            "next_action": "Run in an isolated runtime.",
        }
        with self.assertRaisesRegex(validate_review.ReviewValidationError, "status must be INCOMPLETE"):
            validate_review.validate_review(value, self.catalog, self.scan)
        value["status"] = "INCOMPLETE"
        validate_review.validate_review(value, self.catalog, self.scan)

    def test_catalog_rejects_unlabelled_check_bullets(self) -> None:
        self.catalog_path.write_text("# Catalog\n\n- Missing stable metadata.\n", encoding="utf-8")
        with self.assertRaisesRegex(validate_review.ReviewValidationError, "malformed"):
            validate_review.load_catalog(self.catalog_path)


if __name__ == "__main__":
    unittest.main()
