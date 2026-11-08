#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
CLASSIFICATION_PATH = ROOT / "custom_factions" / "custom_law_runtime_completion_classification.json"
INVENTORY_PATH = ROOT / "custom_factions" / "custom_law_effect_plan_inventory.json"
OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"
SOURCE_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
DEFAULT_MD = ROOT / "artifacts" / "custom_law_static" / "custom_law_runtime_claim_audit.md"
DEFAULT_JSON = ROOT / "artifacts" / "custom_law_static" / "custom_law_runtime_claim_audit.json"
DEFAULT_CORE_ZIP = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)

RUNTIME_CANDIDATE = "candidate-runtime-implemented"
NATIVE_IMPLEMENTED = "native-data-implemented"
HARD_CASE = "named-hard-case"
DISABLED = "disabled-no-implemented-surface"

FORBIDDEN_IMPLEMENTED_CLAIM_PHRASES = (
    "mutation=disabled",
    "Diagnostic observation only",
    "has no implemented mutator",
    "diagnostic-only",
    "planned-only",
)

OWNER_TOKEN_RE = re.compile(
    r"\b(?:Homm3[A-Za-z0-9]*(?:Runtime|NativeAdapter|Registry|State|Guard|Handler)|"
    r"Homm3BattleLocalLawState|Homm3FocusNativeAdapter)\b"
)
MUTATION_EVIDENCE_RE = re.compile(
    r"\b(?:Apply|Applied|TryApply|Mutate|Mutated|Grant|Granted|Reduce|Reduced|Restore|Restored|"
    r"Mark|Marked|Consume|Consumed|Arm|Armed|Set|Write|Credit|Register|Patch)\b"
)

FAMILY_LABEL_BY_INDEX = {
    2: "Vision",
    6: "TrainingDamage",
    13: "CounterattackDoctrine",
    15: "SpellSchool",
    18: "Formation",
    19: "Formation",
    21: "RewardEconomy",
    22: "MoralePackage",
    25: "MoraleTrigger",
    27: "SpellSchool",
    28: "Construction",
    33: "Calendar",
    34: "SpellCooldown",
}


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_targets(path: Path) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    doc = load_json(path)
    families_raw = doc.get("families")
    rows = doc.get("targets")
    if not isinstance(families_raw, dict) or not isinstance(rows, list):
        raise ValueError(f"{rel(path)} must contain families and targets")
    families: dict[int, dict[str, Any]] = {}
    for key, value in families_raw.items():
        if not isinstance(value, dict):
            raise ValueError(f"{rel(path)} family {key!r} must be an object")
        families[int(key)] = value
    return families, rows


def load_classifications(path: Path) -> dict[str, dict[str, Any]]:
    doc = load_json(path)
    rows = doc.get("classifications")
    if not isinstance(rows, list):
        raise ValueError(f"{rel(path)} must contain classifications")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("lawSid"), str):
            raise ValueError(f"{rel(path)} contains invalid classification row: {row!r}")
        result[row["lawSid"]] = row
    return result


def load_inventory(path: Path) -> list[dict[str, Any]]:
    doc = load_json(path)
    rows = doc.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"{rel(path)} must contain rows")
    return [row for row in rows if isinstance(row, dict)]


def load_overrides(directory: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    result: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(directory.glob("homm3_*.json")):
        doc = load_json(path)
        laws = doc.get("lawOverrides") or doc.get("laws")
        if laws is None and isinstance(doc, dict):
            laws = doc
        if not isinstance(laws, dict):
            raise ValueError(f"{rel(path)} must contain lawOverrides or laws object")
        for sid, row in laws.items():
            if isinstance(sid, str) and isinstance(row, dict):
                result[sid] = (path, row)
    return result


def load_source_files(directory: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(directory.glob("*.cs")):
        result[path.name] = path.read_text(encoding="utf-8-sig", errors="replace")
    return result


def load_core_rows(core_zip: Path | None) -> dict[str, dict[str, Any]]:
    if core_zip is None or not core_zip.exists():
        return {}
    rows_by_sid: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(core_zip) as archive:
        for name in archive.namelist():
            if not name.startswith("DB/fractions_laws/fractions_laws_table_homm3_") or not name.endswith(".json"):
                continue
            doc = json.loads(archive.read(name).decode("utf-8-sig"))
            rows = doc.get("array")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sid = row.get("sid") or row.get("id")
                if isinstance(sid, str):
                    rows_by_sid[sid] = row
    return rows_by_sid


def faction_sid(faction: str) -> str:
    return faction if faction.startswith("homm3_") else "homm3_" + faction


def matching_inventory_rows(inventory_rows: list[dict[str, Any]], target: dict[str, Any]) -> list[dict[str, Any]]:
    expected_faction = faction_sid(str(target.get("faction", "")))
    expected_name = target.get("name")
    family = FAMILY_LABEL_BY_INDEX.get(int(target.get("lawIndex", -1)))
    matches: list[dict[str, Any]] = []
    for row in inventory_rows:
        if row.get("factionSid") != expected_faction:
            continue
        if row.get("lawName") != expected_name:
            continue
        if family is not None and row.get("family") != family:
            continue
        matches.append(row)
    return matches


def extract_owner_tokens(*texts: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not isinstance(text, str):
            continue
        for match in OWNER_TOKEN_RE.finditer(text):
            token = match.group(0)
            if token not in seen:
                tokens.append(token)
                seen.add(token)
    return tokens


def source_file_for_owner(source_files: dict[str, str], owner: str) -> tuple[str | None, str | None]:
    direct_name = owner + ".cs"
    if direct_name in source_files:
        return direct_name, source_files[direct_name]
    for name, text in source_files.items():
        if owner in text:
            return name, text
    return None, None


def source_has_mutation_evidence(source_files: dict[str, str], owners: list[str], effect_keys: list[str]) -> bool:
    for owner in owners:
        _name, text = source_file_for_owner(source_files, owner)
        if text and MUTATION_EVIDENCE_RE.search(text):
            return True
    for effect_key in effect_keys:
        if not effect_key:
            continue
        for text in source_files.values():
            if effect_key in text and MUTATION_EVIDENCE_RE.search(text):
                return True
    return False


def summarize_bonus(row: dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return "missing"
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list):
        return "none"
    summaries: list[str] = []
    for index, level in enumerate(levels, start=1):
        bonuses = level.get("bonuses") if isinstance(level, dict) else None
        if not isinstance(bonuses, list) or not bonuses:
            summaries.append(f"L{index}:empty")
            continue
        rendered: list[str] = []
        for bonus in bonuses:
            if not isinstance(bonus, dict):
                continue
            bonus_type = bonus.get("type") or bonus.get("bonusType") or "bonus"
            fields = []
            for key in ("subtype", "value", "values", "sid", "count"):
                if key in bonus:
                    fields.append(f"{key}={bonus[key]}")
            rendered.append(str(bonus_type) + ("(" + ",".join(fields) + ")" if fields else ""))
        summaries.append(f"L{index}:" + "|".join(rendered))
    return "; ".join(summaries) if summaries else "none"


def deployed_core_status(sid: str, core_rows: dict[str, dict[str, Any]]) -> str:
    if not core_rows:
        return "not-checked"
    return "present" if sid in core_rows else "missing"


def expected_to_work(classification: str, reason: str, notes: str) -> str:
    combined = (reason + " " + notes).lower()
    if classification == NATIVE_IMPLEMENTED:
        return "yes-native-data"
    if classification == RUNTIME_CANDIDATE:
        if "runtime-proven" in combined and "runtime proof still required" not in combined:
            return "yes-runtime-proven"
        return "no-runtime-unproven-candidate"
    if classification in {HARD_CASE, DISABLED}:
        return "no-disabled"
    return "unknown"


def build_audit(
    targets: list[dict[str, Any]],
    families: dict[int, dict[str, Any]],
    classifications: dict[str, dict[str, Any]],
    overrides: dict[str, tuple[Path, dict[str, Any]]],
    inventory_rows: list[dict[str, Any]],
    source_files: dict[str, str],
    core_rows: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    audit_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for target in targets:
        sid = target.get("lawSid")
        if not isinstance(sid, str):
            errors.append(f"target row has invalid lawSid: {target!r}")
            continue
        law_index = int(target.get("lawIndex"))
        family = families.get(law_index, {})
        classification_row = classifications.get(sid, {})
        classification = str(classification_row.get("classification", "missing-classification"))
        reason = str(classification_row.get("reason", ""))
        override_path, override_row = overrides.get(sid, (Path("missing"), {}))
        notes = str(override_row.get("notes", ""))
        description = str(override_row.get("descriptionText", ""))
        inventory_matches = matching_inventory_rows(inventory_rows, target)
        effect_keys = [
            row.get("effectKey")
            for row in inventory_matches
            if isinstance(row.get("effectKey"), str)
        ]
        owners = extract_owner_tokens(reason, notes)
        owner_sources = []
        for owner in owners:
            source_name, _source_text = source_file_for_owner(source_files, owner)
            owner_sources.append(f"{owner}:{source_name or 'missing-source'}")
        combined_claim = "\n".join([reason, notes, description])
        row_errors: list[str] = []
        if classification == RUNTIME_CANDIDATE:
            for phrase in FORBIDDEN_IMPLEMENTED_CLAIM_PHRASES:
                if phrase in combined_claim:
                    row_errors.append(f"candidate runtime claim contains diagnostic-only phrase {phrase!r}")
            if not owners:
                row_errors.append("candidate runtime claim names no Homm3 runtime owner")
            for owner in owners:
                source_name, _source_text = source_file_for_owner(source_files, owner)
                if source_name is None:
                    row_errors.append(f"candidate runtime owner {owner} is not present in source")
            if not inventory_matches and law_index in FAMILY_LABEL_BY_INDEX:
                row_errors.append("candidate runtime claim has no matching effect-plan inventory row")
            if not source_has_mutation_evidence(source_files, owners, effect_keys):
                row_errors.append("candidate runtime claim has no source mutation evidence for its owner/effect key")
        audit_row = {
            "faction": target.get("faction"),
            "lawIndex": law_index,
            "lawSid": sid,
            "name": target.get("name"),
            "packet": family.get("packet", "unknown"),
            "family": FAMILY_LABEL_BY_INDEX.get(law_index, family.get("label", "unknown")),
            "classification": classification,
            "expectedToWork": expected_to_work(classification, reason, notes),
            "nativeBonuses": summarize_bonus(override_row),
            "runtimeProfiles": ", ".join(effect_keys) if effect_keys else "none",
            "mutationOwners": ", ".join(owners) if owners else "none",
            "ownerSources": ", ".join(owner_sources) if owner_sources else "none",
            "deployedCore": deployed_core_status(sid, core_rows),
            "overridePath": rel(override_path) if override_path != Path("missing") else "missing",
            "claimErrors": row_errors,
        }
        audit_rows.append(audit_row)
        for error in row_errors:
            errors.append(f"{sid}: {error}")
    return audit_rows, errors


def markdown_escape(value: Any) -> str:
    text = str(value).replace("\n", " ")
    return text.replace("|", "\\|")


def write_markdown(path: Path, rows: list[dict[str, Any]], errors: list[str], core_zip: Path | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Custom Law Runtime Claim Audit",
        "",
        "Static audit only. This does not prove runtime behavior.",
        "",
        f"Core source: {core_zip if core_zip and core_zip.exists() else 'not checked'}",
        "",
        "| faction | law | sid | name | packet | family | classification | expected | profiles | owners | core | claim errors |",
        "|---|---:|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                markdown_escape(row[key])
                for key in (
                    "faction",
                    "lawIndex",
                    "lawSid",
                    "name",
                    "packet",
                    "family",
                    "classification",
                    "expectedToWork",
                    "runtimeProfiles",
                    "mutationOwners",
                    "deployedCore",
                )
            )
            + " | "
            + markdown_escape("; ".join(row["claimErrors"]) if row["claimErrors"] else "none")
            + " |"
        )
    lines.extend(["", "## Validation Errors", ""])
    if errors:
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("- none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate candidate runtime custom-law claims against source-backed mutation owners "
            "and optionally write a law-by-law audit table."
        )
    )
    parser.add_argument("--targets", type=Path, default=TARGETS_PATH)
    parser.add_argument("--classification", type=Path, default=CLASSIFICATION_PATH)
    parser.add_argument("--inventory", type=Path, default=INVENTORY_PATH)
    parser.add_argument("--override-dir", type=Path, default=OVERRIDE_DIR)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--core-zip", type=Path, default=DEFAULT_CORE_ZIP)
    parser.add_argument("--skip-core", action="store_true")
    parser.add_argument("--out-md", type=Path)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--write-defaults", action="store_true")
    args = parser.parse_args()

    try:
        families, targets = load_targets(args.targets)
        classifications = load_classifications(args.classification)
        inventory_rows = load_inventory(args.inventory)
        overrides = load_overrides(args.override_dir)
        source_files = load_source_files(args.source_dir)
        core_zip = None if args.skip_core else args.core_zip
        core_rows = load_core_rows(core_zip)
        audit_rows, errors = build_audit(
            targets,
            families,
            classifications,
            overrides,
            inventory_rows,
            source_files,
            core_rows,
        )
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"custom law runtime claim audit failed: {exc}")
        return 1

    out_json = DEFAULT_JSON if args.write_defaults else args.out_json
    out_md = DEFAULT_MD if args.write_defaults else args.out_md
    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(
            json.dumps(
                {
                    "purpose": "Static audit of custom law runtime implementation claims. This is not runtime proof.",
                    "coreZip": str(core_zip) if core_zip and core_zip.exists() else None,
                    "errorCount": len(errors),
                    "errors": errors,
                    "rows": audit_rows,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    if out_md:
        write_markdown(out_md, audit_rows, errors, core_zip)

    if errors:
        print("custom law runtime claim audit failed:")
        for error in errors:
            print("  - " + error)
        return 1
    print(f"custom law runtime claim audit passed: {len(audit_rows)} target rows checked")
    if core_zip and core_zip.exists():
        print(f"deployed Core rows checked from {core_zip}")
    else:
        print("deployed Core rows not checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
