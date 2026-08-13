#!/usr/bin/env python3
"""仅使用标准库校验 Skill 包的完整性与双宿主兼容契约。"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "PACKAGE-MANIFEST.json",
    "README.md",
    "references/official-compliance.md",
    "references/check-catalog.md",
    "references/eval-harness.md",
    "references/optimization-loop.md",
    "templates/review-report.md",
    "evals/cases.json",
    "scripts/scan_project.py",
)

SKILL_FRONTMATTER_KEYS = {"name", "description"}
OPENAI_INTERFACE_KEYS = {
    "display_name",
    "short_description",
    "default_prompt",
}
EXPECTED_PACKAGE_ROOTS = [
    "agents",
    "evals",
    "references",
    "scripts",
    "templates",
    "tests",
]
EXPECTED_TOP_LEVEL_FILES = ["LICENSE", "README.md", "README_en.md", "SKILL.md"]
EXPECTED_PACKAGE_NAME = "agent-config-reviewer"
EXPECTED_PACKAGE_VERSION = "2.0.0-final"
EXPECTED_BASELINE_DATE = "2026-08-13"
EXPECTED_HOST_COMPATIBILITY = {
    "claude_code": {
        "project_install": ".claude/skills/agent-config-reviewer/",
        "user_install": "~/.claude/skills/agent-config-reviewer/",
        "invocation": "/agent-config-reviewer",
    },
    "codex": {
        "project_install": ".agents/skills/agent-config-reviewer/",
        "user_install": "$HOME/.agents/skills/agent-config-reviewer/",
        "invocation": "$agent-config-reviewer",
    },
}
EXPECTED_TARGET_CONTRACT = {
    "default": "current-working-directory",
    "accepted": ["project-root", "project-.claude-directory"],
    "reject": [
        "missing",
        "unreadable",
        "file",
        "user-home-.claude",
        "host-config-directory",
    ],
    "explicit_invalid_fallback": False,
}
IGNORED_DIRECTORY_NAMES = {
    "__pycache__",
    "node_modules",
}
IGNORED_FILE_NAMES = {
    ".DS_Store",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def load_json(path: Path, label: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = value
        return result

    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream, object_pairs_hook=reject_duplicate_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        fail(f"cannot parse {label}: {exc}")


def parse_string_scalar(raw_value: str, label: str) -> str:
    value = raw_value.strip()
    if not value:
        fail(f"{label} must be a non-empty string")

    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            fail(f"{label} has an invalid double-quoted string: {exc.msg}")
        if not isinstance(parsed, str):
            fail(f"{label} must be a string")
        return parsed

    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            fail(f"{label} has an unterminated single-quoted string")
        return value[1:-1].replace("''", "'")

    if value.endswith(("'", '"')):
        fail(f"{label} has mismatched quotes")
    if value in {"|", ">", "|-", ">-", "|+", ">+"}:
        fail(f"{label} must use a one-line string")
    if value.lower() in {"null", "true", "false", "~"}:
        fail(f"{label} must be a string")
    return value


def parse_skill(skill_text: str) -> tuple[dict[str, str], str, int]:
    lines = skill_text.splitlines()
    if not lines or lines[0] != "---":
        fail("SKILL.md missing YAML frontmatter")
    try:
        closing_index = lines.index("---", 1)
    except ValueError:
        fail("SKILL.md frontmatter is not closed")

    frontmatter: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:closing_index], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace() or "\t" in line:
            fail(f"SKILL.md frontmatter line {line_number} is not a flat mapping")
        match = re.fullmatch(r"([A-Za-z0-9_-]+):\s*(.*)", line)
        if not match:
            fail(f"SKILL.md frontmatter line {line_number} is invalid")
        key, raw_value = match.groups()
        if key in frontmatter:
            fail(f"SKILL.md frontmatter repeats {key!r}")
        if not raw_value.strip().startswith('"'):
            fail(
                "SKILL.md frontmatter values must use "
                "JSON-compatible double-quoted strings"
            )
        frontmatter[key] = parse_string_scalar(
            raw_value, f"SKILL.md frontmatter {key!r}"
        )

    missing = SKILL_FRONTMATTER_KEYS - frontmatter.keys()
    extra = frontmatter.keys() - SKILL_FRONTMATTER_KEYS
    if missing:
        fail(f"SKILL.md frontmatter missing fields: {', '.join(sorted(missing))}")
    if extra:
        fail(f"SKILL.md frontmatter has unsupported fields: {', '.join(sorted(extra))}")

    body_lines = lines[closing_index + 1 :]
    # 保留原有统计口径：正文行数包含 frontmatter 结束分隔符后的换行。
    closing_delimiters = list(re.finditer(r"(?m)^---\r?$", skill_text))
    body_line_count = len(skill_text[closing_delimiters[1].end() :].splitlines())
    return frontmatter, "\n".join(body_lines), body_line_count


def validate_skill(skill_text: str) -> tuple[str, str, int]:
    frontmatter, body, body_line_count = parse_skill(skill_text)
    name = frontmatter["name"]
    description = frontmatter["description"]

    if not re.fullmatch(r"[a-z0-9-]{1,64}", name):
        fail(f"invalid Skill name: {name}")
    if "claude" in name or "anthropic" in name:
        fail("Skill name uses a reserved Agent Skills term")
    if not description.strip():
        fail("SKILL.md missing description")
    if len(description) > 1024:
        fail("description exceeds 1024 characters")
    if body_line_count > 500:
        fail(f"SKILL.md body exceeds 500 lines: {body_line_count}")

    return name, body, body_line_count


def validate_openai_metadata(path: Path, skill_name: str) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        fail(f"cannot read agents/openai.yaml: {exc}")

    interface_seen = False
    interface: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" in line:
            fail(f"agents/openai.yaml line {line_number} contains a tab")

        if not line[:1].isspace():
            if not re.fullmatch(r"interface:\s*", line):
                fail(
                    "agents/openai.yaml only supports the top-level interface mapping"
                )
            if interface_seen:
                fail("agents/openai.yaml repeats the interface mapping")
            interface_seen = True
            continue

        if not interface_seen:
            fail(
                f"agents/openai.yaml line {line_number} appears before interface"
            )
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*(.*)", line)
        if not match:
            fail(
                f"agents/openai.yaml line {line_number} must be a two-space interface field"
            )
        key, raw_value = match.groups()
        if key in interface:
            fail(f"agents/openai.yaml repeats interface.{key}")
        if not raw_value.strip().startswith('"'):
            fail(
                "agents/openai.yaml interface values must use "
                "JSON-compatible double-quoted strings"
            )
        interface[key] = parse_string_scalar(
            raw_value, f"agents/openai.yaml interface.{key}"
        )

    if not interface_seen:
        fail("agents/openai.yaml missing interface mapping")
    missing = OPENAI_INTERFACE_KEYS - interface.keys()
    extra = interface.keys() - OPENAI_INTERFACE_KEYS
    if missing:
        fail(
            "agents/openai.yaml missing interface fields: "
            + ", ".join(sorted(missing))
        )
    if extra:
        fail(
            "agents/openai.yaml has unsupported interface fields: "
            + ", ".join(sorted(extra))
        )

    short_description = interface["short_description"]
    if not 25 <= len(short_description) <= 64:
        fail(
            "agents/openai.yaml interface.short_description must contain "
            f"25-64 characters, got {len(short_description)}"
        )
    invocation = f"${skill_name}"
    if not re.search(
        rf"(?<![A-Za-z0-9_-]){re.escape(invocation)}(?![A-Za-z0-9_-])",
        interface["default_prompt"],
    ):
        fail(
            "agents/openai.yaml interface.default_prompt must contain "
            f"{invocation}"
        )


def validate_direct_references(skill_body: str) -> int:
    resource_pattern = (
        r"(?:references|templates|scripts)/"
        r"(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+"
    )
    occurrence_pattern = re.compile(resource_pattern)
    valid_pattern = re.compile(
        r"(?<![A-Za-z0-9_./:\\-])"
        r"(?:<skill-dir>/)?"
        rf"(?P<resource>{resource_pattern})"
    )
    valid_matches = {
        match.span("resource"): match.group("resource").rstrip(".,;:!?")
        for match in valid_pattern.finditer(skill_body)
    }
    for match in occurrence_pattern.finditer(skill_body):
        if match.span() not in valid_matches:
            fail(
                "SKILL.md contains a non-package resource reference near "
                f"{match.group(0)!r}"
            )

    references = set(valid_matches.values())
    for relative_path in sorted(references):
        path = ROOT / relative_path
        try:
            resolved_path = path.resolve(strict=True)
            resolved_path.relative_to(ROOT.resolve())
        except (FileNotFoundError, OSError, ValueError):
            fail(f"SKILL.md references missing or external file {relative_path}")
        if not resolved_path.is_file():
            fail(f"SKILL.md references missing file {relative_path}")
    return len(references)


def is_ignored_payload(relative_path: Path) -> bool:
    if relative_path.name in IGNORED_FILE_NAMES:
        return True
    return any(
        part in IGNORED_DIRECTORY_NAMES for part in relative_path.parts[:-1]
    )


def validate_repository_layout() -> None:
    allowed_top_level = {
        *EXPECTED_PACKAGE_ROOTS,
        *EXPECTED_TOP_LEVEL_FILES,
        ".git",
        ".code-review-graph",
        "PACKAGE-MANIFEST.json",
    }
    unexpected = sorted(
        path.name for path in ROOT.iterdir() if path.name not in allowed_top_level
    )
    if unexpected:
        fail(
            "repository root contains undeclared files or directories: "
            + ", ".join(unexpected)
        )


def manifest_path(raw_path: Any) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path:
        fail("PACKAGE-MANIFEST.json file path must be a non-empty string")
    if "\\" in raw_path:
        fail(f"PACKAGE-MANIFEST.json path must use forward slashes: {raw_path}")

    pure_path = PurePosixPath(raw_path)
    if (
        pure_path.is_absolute()
        or ".." in pure_path.parts
        or "." in pure_path.parts
        or pure_path.as_posix() != raw_path
    ):
        fail(f"PACKAGE-MANIFEST.json has unsafe or non-canonical path: {raw_path}")
    if raw_path == "PACKAGE-MANIFEST.json":
        fail("PACKAGE-MANIFEST.json must not list itself")

    path = ROOT.joinpath(*pure_path.parts)
    try:
        path.resolve(strict=True).relative_to(ROOT.resolve())
    except (FileNotFoundError, OSError, ValueError):
        fail(f"PACKAGE-MANIFEST.json lists missing or external file: {raw_path}")
    if not path.is_file():
        fail(f"PACKAGE-MANIFEST.json path is not a file: {raw_path}")
    return raw_path, path


def expected_payload_files() -> set[str]:
    expected = set(EXPECTED_TOP_LEVEL_FILES)
    for relative_path in EXPECTED_TOP_LEVEL_FILES:
        path = ROOT / relative_path
        if path.is_symlink():
            fail(f"package payload must not contain symbolic links: {relative_path}")
        if not path.is_file():
            fail(f"missing top-level payload file {relative_path}")

    for root_name in EXPECTED_PACKAGE_ROOTS:
        package_root = ROOT / root_name
        if package_root.is_symlink():
            fail(f"package payload must not contain symbolic links: {root_name}")
        if not package_root.is_dir():
            fail(f"missing package root {root_name}/")
        for path in package_root.rglob("*"):
            if path.is_symlink():
                fail(
                    "package payload must not contain symbolic links: "
                    + path.relative_to(ROOT).as_posix()
                )
            if not path.is_file():
                continue
            relative_path = path.relative_to(ROOT)
            if is_ignored_payload(relative_path):
                continue
            expected.add(relative_path.as_posix())
    return expected


def validate_manifest(path: Path) -> int:
    manifest = load_json(path, "PACKAGE-MANIFEST.json")
    if not isinstance(manifest, dict):
        fail("PACKAGE-MANIFEST.json root must be an object")

    if manifest.get("package") != EXPECTED_PACKAGE_NAME:
        fail(
            f'PACKAGE-MANIFEST.json package must be "{EXPECTED_PACKAGE_NAME}"'
        )
    if manifest.get("version") != EXPECTED_PACKAGE_VERSION:
        fail(
            f'PACKAGE-MANIFEST.json version must be "{EXPECTED_PACKAGE_VERSION}"'
        )
    if manifest.get("official_baseline_checked") != EXPECTED_BASELINE_DATE:
        fail(
            "PACKAGE-MANIFEST.json official_baseline_checked must be "
            f'"{EXPECTED_BASELINE_DATE}"'
        )
    if manifest.get("review_subject") != "claude-code-config":
        fail('PACKAGE-MANIFEST.json review_subject must be "claude-code-config"')
    if manifest.get("host_compatibility") != EXPECTED_HOST_COMPATIBILITY:
        fail("PACKAGE-MANIFEST.json host_compatibility does not match the host contract")
    if manifest.get("target_contract") != EXPECTED_TARGET_CONTRACT:
        fail("PACKAGE-MANIFEST.json target_contract does not match the target contract")
    if manifest.get("package_roots") != EXPECTED_PACKAGE_ROOTS:
        fail("PACKAGE-MANIFEST.json package_roots does not match the package layout")
    if manifest.get("top_level_files") != EXPECTED_TOP_LEVEL_FILES:
        fail("PACKAGE-MANIFEST.json top_level_files does not match the package layout")

    entries = manifest.get("files")
    if not isinstance(entries, list):
        fail("PACKAGE-MANIFEST.json files must be an array")

    listed_paths: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"PACKAGE-MANIFEST.json files[{index}]"
        if not isinstance(entry, dict):
            fail(f"{label} must be an object")
        required_keys = {"path", "bytes", "sha256"}
        if not required_keys.issubset(entry):
            missing = required_keys - entry.keys()
            fail(f"{label} missing fields: {', '.join(sorted(missing))}")

        relative_path, payload_path = manifest_path(entry["path"])
        if relative_path in listed_paths:
            fail(f"PACKAGE-MANIFEST.json repeats file {relative_path}")
        listed_paths.add(relative_path)

        try:
            payload = payload_path.read_bytes()
        except OSError as exc:
            fail(f"cannot read manifest payload {relative_path}: {exc}")
        declared_size = entry["bytes"]
        if type(declared_size) is not int or declared_size < 0:
            fail(f"{label}.bytes must be a non-negative integer")
        if declared_size != len(payload):
            fail(
                f"{relative_path} byte size mismatch: "
                f"declared {declared_size}, actual {len(payload)}"
            )

        declared_hash = entry["sha256"]
        if not isinstance(declared_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", declared_hash
        ):
            fail(f"{label}.sha256 must be a lowercase SHA256 digest")
        actual_hash = hashlib.sha256(payload).hexdigest()
        if declared_hash != actual_hash:
            fail(
                f"{relative_path} SHA256 mismatch: "
                f"declared {declared_hash}, actual {actual_hash}"
            )

    expected_paths = expected_payload_files()
    missing_paths = expected_paths - listed_paths
    unexpected_paths = listed_paths - expected_paths
    if missing_paths:
        fail(
            "PACKAGE-MANIFEST.json omits payload files: "
            + ", ".join(sorted(missing_paths))
        )
    if unexpected_paths:
        fail(
            "PACKAGE-MANIFEST.json lists files outside the declared payload: "
            + ", ".join(sorted(unexpected_paths))
        )
    return len(listed_paths)


def validate_evals(path: Path) -> int:
    data = load_json(path, "evals/cases.json")
    if not isinstance(data, dict):
        fail("evals/cases.json root must be an object")
    cases = data.get("cases")
    if not isinstance(cases, list):
        fail("evals/cases.json cases must be an array")
    if len(cases) < 3:
        fail("fewer than 3 eval cases")

    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            fail(f"evals/cases.json cases[{index}] must be an object")
        required_keys = {
            "id",
            "category",
            "prompt",
            "must_include",
            "must_not_include",
        }
        if set(case) != required_keys:
            fail(
                f"evals/cases.json cases[{index}] must contain exactly: "
                + ", ".join(sorted(required_keys))
            )
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            fail(f"evals/cases.json cases[{index}] has an invalid id")
        if case_id in seen_ids:
            fail(f"evals/cases.json repeats case id {case_id!r}")
        seen_ids.add(case_id)
        for field in ("category", "prompt"):
            value = case[field]
            if not isinstance(value, str) or not value.strip():
                fail(
                    f"evals/cases.json cases[{index}].{field} "
                    "must be a non-empty string"
                )
        for field in ("must_include", "must_not_include"):
            values = case[field]
            if (
                not isinstance(values, list)
                or not all(isinstance(value, str) and value for value in values)
            ):
                fail(
                    f"evals/cases.json cases[{index}].{field} "
                    "must be an array of non-empty strings"
                )
    return len(cases)


def main() -> None:
    validate_repository_layout()
    for relative_path in REQUIRED_FILES:
        if not (ROOT / relative_path).is_file():
            fail(f"missing {relative_path}")

    try:
        skill_text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(f"cannot read SKILL.md: {exc}")

    name, body, body_line_count = validate_skill(skill_text)
    if name != EXPECTED_PACKAGE_NAME:
        fail("SKILL.md name does not match the package identity")
    validate_openai_metadata(ROOT / "agents/openai.yaml", name)
    direct_reference_count = validate_direct_references(body)
    eval_case_count = validate_evals(ROOT / "evals/cases.json")
    manifest_file_count = validate_manifest(ROOT / "PACKAGE-MANIFEST.json")

    print("PASS")
    print(f"name={name}")
    print(f"body_lines={body_line_count}")
    print(f"direct_references={direct_reference_count}")
    print(f"eval_cases={eval_case_count}")
    print(f"manifest_files={manifest_file_count}")


if __name__ == "__main__":
    main()
