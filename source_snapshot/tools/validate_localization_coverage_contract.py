#!/usr/bin/env python3
"""Audit that every localization key the Core DB references resolves in Lang.

The game shows "LOC: [<key>]" for any unresolved localization key and does not
log the miss, so this is a static audit of a Core.zip:

1. Collect every key defined in ``Lang/<language>/texts/*.json`` (``tokens`` and
   ``array`` rows).
2. Walk the DB / campaign JSON and collect localization references. The
   reference conventions are learned from vanilla rows in the same Core rather
   than hard-coded per file:
   * explicit fields: a field path (array indices stripped) is a localization
     path when its field name is name/desc/description/title/... and at least
     half of the vanilla values at that path resolve in English. Paths that only
     custom content uses are accepted on the field name alone.
   * id-derived keys: ``<id><suffix>`` (``_name``, ``_desc``, ...) is a
     reference for a DB file when at least 90% of that file's vanilla row ids
     resolve with the suffix.
3. Report unresolved references grouped by content area, split into our custom
   content and gaps that already exist in vanilla. Only custom misses fail.

Custom/vanilla split: a key is ours when the key, its owning row id or its Core
member path names HoMM3 content (``homm3``/``h3_``/``landon``), unless the key
itself is not HoMM3-named and vanilla rows leave the same value unresolved at
the same path (shared sentinels such as ``default``). With ``--vanilla-core``
a key that the unmodded Core's English resolves but this Core lacks is also
reported as ours (a vanilla row the mod lost). Rows with
``"localization": false`` show literal text and are skipped.

``--apply-overlay`` virtually applies the Core overlay source
(tools/release_port/apply_release_core_overlay.py ``build_overlay``) to the
given Core in memory, so the candidate a rebuild would produce is audited
without writing a ZIP.

Proof tier: source/static or generated-artifact only. A pass does not prove
which collection the game's UI reads or that a screen shows the text.

Measured on the installed Golden Era Core (21k entries): about 2-3 s and
under 400 MB peak RSS without ``--apply-overlay``; ``--apply-overlay`` adds the
overlay's own in-memory build (about 25-35 s). CPU only: JSON/ZIP I/O.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import pathlib
import re
import sys
import time
import zipfile
from typing import Any, Iterable

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CORE = pathlib.Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
OVERLAY_SOURCE = REPO_ROOT / "tools" / "release_port" / "apply_release_core_overlay.py"
ENGLISH = "english"

# Field names that carry localization keys. Paths are still gated by the vanilla
# resolution ratio below, so e.g. resource "name" fields inside cost rows drop out.
LOC_FIELD_RE = re.compile(
    r"^(name|names|desc|description|descriptions|narrativeDesc|narrativeDescription|"
    r"narrativeDescriptions|title|subtitle|motto|cityNames|upgradeDescription|infoDescription|"
    r"excaptionInTooltip|upEffectDescription|rewardNotificationDesc|label|locNameBuild|"
    r"locNameUnit|alternativeDesc|text|titleSid|descriptionSid|nameSid)$"
)
# Dialog slide titles nest the key as {"title": {"sid": ...}}.
NESTED_SID_PARENTS = {"title"}
EXPLICIT_PATH_MIN_RATIO = 0.5
ID_SUFFIXES = ("_name", "_desc", "_description", "_title")
ID_SUFFIX_MIN_RATIO = 0.9
ID_SUFFIX_MIN_VANILLA_ROWS = 5
CUSTOM_RE = re.compile(r"(?i)homm3|(?:^|[^a-z0-9])h3_|landon")
SCANNED_PREFIXES = ("DB/", "campaigns/")
# Only bulk unit lists; probed: no localization-shaped fields.
SKIPPED_PREFIXES = ("DB/squads/",)

AREA_RULES: tuple[tuple[str, str], ...] = (
    ("DB/fractions_laws/", "faction laws"),
    ("DB/fractions/", "factions"),
    ("DB/heroes_abilities/", "hero battle abilities (faction ability buttons)"),
    ("DB/heroes_skills/", "hero skills / subskills"),
    ("DB/heroes_specializations/", "hero specializations"),
    ("DB/heroes_sub_classes/", "hero classes"),
    ("DB/heroes/", "heroes"),
    ("DB/units/", "units / unit abilities"),
    ("DB/objects_logic/cities/", "town buildings"),
    ("DB/objects_logic/", "map objects"),
    ("DB/magics/", "spells"),
    ("DB/items/", "artifacts"),
    ("DB/buffs/", "buffs"),
    ("DB/side_buffs/", "buffs"),
    ("DB/heroes_buffs/", "buffs"),
    ("DB/map/", "map content"),
    ("DB/dialogs/", "dialogs"),
    ("campaigns/", "campaigns"),
)


def area_for_member(member: str) -> str:
    for prefix, area in AREA_RULES:
        if member.startswith(prefix):
            return area
    return "other (" + "/".join(member.split("/")[:2]) + ")"


def read_doc(zf: zipfile.ZipFile, overlay: dict[str, bytes], member: str) -> Any:
    raw = overlay[member] if member in overlay else zf.read(member)
    return json.loads(raw.decode("utf-8-sig"))


def lang_keys(zf: zipfile.ZipFile, overlay: dict[str, bytes], names: Iterable[str]) -> dict[str, set[str]]:
    keys: dict[str, set[str]] = collections.defaultdict(set)
    for member in names:
        parts = member.split("/")
        if len(parts) != 4 or parts[0] != "Lang" or parts[2] != "texts" or not member.endswith(".json"):
            continue
        doc = read_doc(zf, overlay, member)
        if not isinstance(doc, dict):
            continue
        for list_key in ("tokens", "array"):
            for row in doc.get(list_key) or []:
                if isinstance(row, dict) and isinstance(row.get("sid"), str):
                    keys[parts[1]].add(row["sid"])
    return keys


def is_metadata_field(name: str) -> bool:
    # Mod-owned xHomm3* metadata and fields the game disables with a trailing "_".
    return name.endswith("_") or bool(re.match(r"^x[A-Z]", name))


def iter_rows(doc: Any) -> list[dict[str, Any]]:
    if isinstance(doc, dict) and isinstance(doc.get("array"), list):
        return [row for row in doc["array"] if isinstance(row, dict)]
    if isinstance(doc, list):
        return [row for row in doc if isinstance(row, dict)]
    return [doc] if isinstance(doc, dict) else []


def collect_references(doc: Any) -> list[tuple[str, str, str]]:
    """Return (path, value, owning row id) for every loc-shaped string field."""
    out: list[tuple[str, str, str]] = []

    def walk(value: Any, path: str, field: str | None, parent: str | None, owner: str) -> None:
        if isinstance(value, dict):
            if value.get("localization") is False:
                # Rows that opt out show their strings literally (e.g. stock-map dialogs).
                return
            row_id = value.get("id") if isinstance(value.get("id"), str) else owner
            for key, child in value.items():
                if is_metadata_field(key):
                    continue
                walk(child, f"{path}/{key}", key, field, row_id)
        elif isinstance(value, list):
            for child in value:
                walk(child, path, field, parent, owner)
        elif isinstance(value, str) and field is not None:
            if LOC_FIELD_RE.match(field) or (field == "sid" and parent in NESTED_SID_PARENTS):
                out.append((path, value, owner))

    walk(doc, "", None, None, "")
    return out


def load_vanilla_reference_strings(vanilla_core: pathlib.Path) -> tuple[set[str], set[str]]:
    strings: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str):
            strings.add(value)

    with zipfile.ZipFile(vanilla_core) as zf:
        names = zf.namelist()
        english = lang_keys(zf, {}, names).get(ENGLISH, set())
        for member in names:
            if member.startswith(SCANNED_PREFIXES) and member.endswith(".json") and not member.startswith(SKIPPED_PREFIXES):
                try:
                    walk(read_doc(zf, {}, member))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
    return strings, english


def build_overlay(core: pathlib.Path) -> dict[str, bytes]:
    overlay_dir = OVERLAY_SOURCE.parent
    if str(overlay_dir) not in sys.path:
        sys.path.insert(0, str(overlay_dir))
    spec = importlib.util.spec_from_file_location("localization_coverage_overlay", OVERLAY_SOURCE)
    if spec is None or spec.loader is None:
        raise SystemExit(f"localization-coverage: cannot import overlay source {OVERLAY_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    overlay, _notes = module.build_overlay(core)
    return overlay


def audit(core: pathlib.Path, overlay: dict[str, bytes], vanilla_core: pathlib.Path | None) -> dict[str, Any]:
    started = time.perf_counter()
    with zipfile.ZipFile(core) as zf:
        names = sorted(set(zf.namelist()) | set(overlay))
        keys = lang_keys(zf, overlay, names)
        english = keys.get(ENGLISH, set())
        if not english:
            raise SystemExit("localization-coverage: Core has no Lang/english texts")

        # member -> [(path, value, owner)], member -> row ids
        refs_by_member: dict[str, list[tuple[str, str, str]]] = {}
        ids_by_member: dict[str, list[str]] = {}
        for member in names:
            if not member.startswith(SCANNED_PREFIXES) or member.startswith(SKIPPED_PREFIXES) or not member.endswith(".json"):
                continue
            try:
                doc = read_doc(zf, overlay, member)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            refs_by_member[member] = collect_references(doc)
            if member.startswith("DB/"):
                ids_by_member[member] = [row["id"] for row in iter_rows(doc) if isinstance(row.get("id"), str)]

    def is_custom(*values: str) -> bool:
        return any(CUSTOM_RE.search(v) for v in values if v)

    # Learn explicit localization paths from vanilla rows.
    path_stats: dict[tuple[str, str], list[int]] = collections.defaultdict(lambda: [0, 0])
    vanilla_unresolved_values: set[str] = set()
    for member, refs in refs_by_member.items():
        top = "/".join(member.split("/")[:2])
        for path, value, owner in refs:
            if value and not is_custom(value, owner, member):
                stat = path_stats[(top, path)]
                stat[0] += 1
                stat[1] += value in english
                if value not in english:
                    vanilla_unresolved_values.add(value)

    def explicit_path_is_loc(member: str, path: str) -> bool:
        total, resolved = path_stats.get(("/".join(member.split("/")[:2]), path), (0, 0))
        if total == 0:
            return True
        return resolved / total >= EXPLICIT_PATH_MIN_RATIO

    # Learn id-derived conventions per DB member.
    id_suffixes_by_member: dict[str, list[str]] = {}
    for member, ids in ids_by_member.items():
        vanilla_ids = [i for i in ids if not is_custom(i, member)]
        if len(vanilla_ids) < ID_SUFFIX_MIN_VANILLA_ROWS:
            continue
        suffixes = [
            suffix
            for suffix in ID_SUFFIXES
            if sum(f"{i}{suffix}" in english for i in vanilla_ids) / len(vanilla_ids) >= ID_SUFFIX_MIN_RATIO
        ]
        if suffixes:
            id_suffixes_by_member[member] = suffixes

    vanilla_strings: set[str] = set()
    vanilla_english: set[str] = set()
    if vanilla_core is not None:
        vanilla_strings, vanilla_english = load_vanilla_reference_strings(vanilla_core)

    def classify(key: str, owner: str, member: str) -> str:
        if vanilla_core is not None and key not in english and key in vanilla_english and key in vanilla_strings:
            # Vanilla resolves it; if this Core cannot, the mod lost the row.
            return "custom"
        if not is_custom(key) and key in vanilla_unresolved_values:
            return "vanilla"
        return "custom" if is_custom(key, owner, member) else "vanilla"

    references: dict[str, dict[str, Any]] = {}

    def add_ref(key: str, member: str, path: str, owner: str, kind: str) -> None:
        entry = references.get(key)
        if entry is None:
            entry = {"key": key, "kind": kind, "sites": [], "area": area_for_member(member)}
            references[key] = entry
        if len(entry["sites"]) < 5:
            entry["sites"].append({"member": member, "path": path, "owner": owner})
        entry.setdefault("_owners", set()).add(owner)
        entry.setdefault("_members", set()).add(member)

    for member, refs in refs_by_member.items():
        for path, value, owner in refs:
            if not value or value.isdigit() or not explicit_path_is_loc(member, path):
                continue
            add_ref(value, member, path, owner, "field")
    for member, suffixes in id_suffixes_by_member.items():
        for row_id in ids_by_member[member]:
            for suffix in suffixes:
                add_ref(f"{row_id}{suffix}", member, f"/array/id+{suffix}", row_id, "id-derived")

    missing = {"custom": collections.defaultdict(list), "vanilla": collections.defaultdict(list)}
    custom_resolved: list[str] = []
    for key, entry in sorted(references.items()):
        owners = entry.pop("_owners")
        members = entry.pop("_members")
        origin = "custom" if any(classify(key, o, m) == "custom" for o in owners for m in members) else "vanilla"
        if key in english:
            if origin == "custom":
                custom_resolved.append(key)
            continue
        missing[origin][entry["area"]].append(entry)

    languages = sorted(lang for lang in keys if lang != ENGLISH)
    language_gaps = {
        lang: sorted(key for key in custom_resolved if key not in keys[lang]) for lang in languages
    }
    return {
        "core": str(core),
        "overlayApplied": bool(overlay),
        "classification": "name-pattern+vanilla-core-lost-rows" if vanilla_core is not None else "name-pattern",
        "englishKeys": len(english),
        "referencedKeys": len(references),
        "customResolved": len(custom_resolved),
        "learnedIdConventions": {m: s for m, s in sorted(id_suffixes_by_member.items())},
        "missing": {origin: {area: rows for area, rows in sorted(by_area.items())} for origin, by_area in missing.items()},
        "customKeysMissingPerLanguage": {lang: len(v) for lang, v in language_gaps.items()},
        "customKeysMissingPerLanguageSample": {lang: v[:10] for lang, v in language_gaps.items() if v},
        "seconds": round(time.perf_counter() - started, 3),
    }


def print_report(report: dict[str, Any], max_keys: int) -> None:
    print(f"core: {report['core']} (overlay applied: {report['overlayApplied']}; classification: {report['classification']})")
    print(f"english keys {report['englishKeys']}, referenced keys {report['referencedKeys']}, custom resolved {report['customResolved']}")
    for origin in ("custom", "vanilla"):
        by_area = report["missing"][origin]
        total = sum(len(rows) for rows in by_area.values())
        print(f"{origin} missing English keys: {total}")
        for area, rows in by_area.items():
            print(f"  {area}: {len(rows)}")
            if origin == "custom":
                for entry in rows[:max_keys]:
                    site = entry["sites"][0]
                    print(f"    {entry['key']}  [{entry['kind']}] {site['member']} {site['path']} owner={site['owner']}")
                if len(rows) > max_keys:
                    print(f"    ... {len(rows) - max_keys} more")
    gaps = {lang: n for lang, n in report["customKeysMissingPerLanguage"].items() if n}
    print("custom keys resolved in English but missing per language: " + (json.dumps(gaps) if gaps else "none"))
    print(f"audit seconds: {report['seconds']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--core", type=pathlib.Path, default=DEFAULT_CORE)
    parser.add_argument("--vanilla-core", type=pathlib.Path, default=None, help="unmodded Core.zip for the custom/vanilla split")
    parser.add_argument("--apply-overlay", action="store_true", help="audit the in-memory overlay candidate built from --core")
    parser.add_argument("--json-out", type=pathlib.Path, default=None)
    parser.add_argument("--max-keys", type=int, default=40, help="custom keys listed per area")
    parser.add_argument("--report-only", action="store_true", help="exit 0 even when custom keys are missing")
    args = parser.parse_args()

    if not args.core.is_file():
        print(f"localization-coverage: missing Core.zip {args.core}", file=sys.stderr)
        return 1
    if args.vanilla_core is not None and not args.vanilla_core.is_file():
        print(f"localization-coverage: missing vanilla Core.zip {args.vanilla_core}", file=sys.stderr)
        return 1
    overlay = build_overlay(args.core) if args.apply_overlay else {}
    report = audit(args.core, overlay, args.vanilla_core)
    print_report(report, args.max_keys)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    custom_missing = sum(len(rows) for rows in report["missing"]["custom"].values())
    if custom_missing and not args.report_only:
        print(f"localization-coverage: {custom_missing} custom localization key(s) do not resolve in English", file=sys.stderr)
        return 1
    print("localization-coverage: OK" if not custom_missing else "localization-coverage: report only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
