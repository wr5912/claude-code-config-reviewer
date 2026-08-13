#!/usr/bin/env python3
"""Dependency-free self-check for this Skill package."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "SKILL.md",
    "README.md",
    "references/official-compliance.md",
    "references/check-catalog.md",
    "references/eval-harness.md",
    "references/optimization-loop.md",
    "templates/review-report.md",
    "evals/cases.json",
    "scripts/scan_project.py",
]


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)

for rel in REQUIRED:
    if not (ROOT / rel).is_file():
        fail(f"missing {rel}")

skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
if not skill.startswith("---\n"):
    fail("SKILL.md missing YAML frontmatter")
parts = skill.split("---", 2)
if len(parts) < 3:
    fail("SKILL.md frontmatter is not closed")
fm = parts[1]
m = re.search(r"(?m)^name:\s*([^\n]+)$", fm)
if not m:
    fail("SKILL.md missing name")
name = m.group(1).strip().strip('"\'')
if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
    fail(f"invalid Skill name: {name}")
if "claude" in name or "anthropic" in name:
    fail("Skill name uses a reserved Agent Skills term")
d = re.search(r"(?m)^description:\s*(.+)$", fm)
if not d or not d.group(1).strip():
    fail("SKILL.md missing description")
if len(d.group(1).strip()) > 1024:
    fail("description exceeds 1024 characters")
body_lines = parts[2].splitlines()
if len(body_lines) > 500:
    fail(f"SKILL.md body exceeds 500 lines: {len(body_lines)}")

with (ROOT / "evals/cases.json").open(encoding="utf-8") as f:
    data = json.load(f)
if len(data.get("cases", [])) < 3:
    fail("fewer than 3 eval cases")

print("PASS")
print(f"name={name}")
print(f"body_lines={len(body_lines)}")
print(f"eval_cases={len(data['cases'])}")
