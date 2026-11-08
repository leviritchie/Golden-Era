"""Fail-closed input manifest checks (paths + expect_present; no invented dump contents)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from olden_cs_recovery.paths import INPUT_MANIFEST_PATH, REPO_ROOT
from olden_cs_recovery.schema_validate import validate_file


def resolve_input_path(entry: dict[str, Any]) -> Path:
    raw = entry["path"]
    if entry.get("path_is_absolute"):
        return Path(raw)
    return (REPO_ROOT / raw).resolve()


def check_entry(entry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    path = resolve_input_path(entry)
    required = bool(entry.get("required"))
    exists = path.exists()
    if not exists:
        if required:
            errors.append(f"missing required path [{entry['id']}]: {path}")
        return errors

    for rel in entry.get("expect_present") or []:
        child = path / rel
        if not child.exists():
            msg = f"missing expect_present [{entry['id']}]: {child}"
            if required:
                errors.append(msg)
            else:
                errors.append(f"optional warning: {msg}")
    return errors


def validate_manifest(*, allow_optional_gaps: bool = False) -> dict[str, Any]:
    validate_file("input_manifest.schema.json", INPUT_MANIFEST_PATH)
    manifest = json.loads(INPUT_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    hard_errors: list[str] = []
    soft_errors: list[str] = []
    checked: list[dict[str, Any]] = []

    for entry in manifest["inputs"]:
        path = resolve_input_path(entry)
        errs = check_entry(entry)
        checked.append(
            {
                "id": entry["id"],
                "required": entry["required"],
                "path": str(path),
                "exists": path.exists(),
                "errors": errs,
            }
        )
        for err in errs:
            if err.startswith("optional warning:"):
                soft_errors.append(err)
            else:
                hard_errors.append(err)

    if hard_errors:
        raise SystemExit(
            json.dumps(
                {
                    "ok": False,
                    "hard_errors": hard_errors,
                    "soft_errors": soft_errors,
                    "checked": checked,
                },
                indent=2,
            )
        )

    if soft_errors and not allow_optional_gaps:
        # Soft errors are only from optional entries' expect_present; report but pass.
        pass

    return {"ok": True, "checked": checked, "soft_errors": soft_errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate pinned recovery inputs (fail closed).")
    parser.add_argument(
        "--allow-optional-gaps",
        action="store_true",
        help="Reserved; optional gaps are never promoted to success for required entries.",
    )
    args = parser.parse_args(argv)
    result = validate_manifest(allow_optional_gaps=args.allow_optional_gaps)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
