#!/usr/bin/env python3
"""Fail-closed validator for the HoMM3 SoD+HotA artifact port.

Checks catalog completeness against extracted icons/map frames, curated
mechanics (no empty/text_only bonuses), and generated Core overlay members.
Does not prove runtime equip or billboard behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "custom_factions" / "artifacts" / "homm3_artifact_catalog.json"
MECHANICS = ROOT / "custom_factions" / "artifacts" / "homm3_artifact_mechanics.json"
SETS = ROOT / "custom_factions" / "artifacts" / "homm3_artifact_sets.json"
SLOT_OVERRIDES = (
    ROOT / "custom_factions" / "artifacts" / "homm3_artifact_slot_overrides.json"
)
ASSETS = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "artifacts"
)
OVERLAY = ROOT / "custom_factions" / "artifacts" / "generated_core_overlay"
DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)

SLOT_TO_ITEM_FILE = {
    "head": "DB/items/items/head.json",
    "armor": "DB/items/items/armor.json",
    "back": "DB/items/items/back.json",
    "belt": "DB/items/items/belt.json",
    "boots": "DB/items/items/boots.json",
    "left_hand": "DB/items/items/right_hand.json",
    "right_hand": "DB/items/items/left_hand.json",
    "ring": "DB/items/items/ring.json",
    "item_slot": "DB/items/items/item_slot.json",
    "unic_slot": "DB/items/items/unic_slot.json",
}


ALLOWED_MECHANICS_STATUS = {"native_exact", "native_substitute"}

# Fallback OE equip capacities if the overrides file omits oeSlotCapacity.
# OE accessory pouch is 4; H3 Misc is 5 — that gap is why Statue of Legion needs a remap.
DEFAULT_OE_SLOT_CAPACITY = {
    "head": 1,
    "armor": 1,
    "back": 1,
    "belt": 1,
    "boots": 1,
    "left_hand": 1,
    "right_hand": 1,
    "ring": 2,
    "item_slot": 4,
    "unic_slot": 1,
}


def _fail(errors: list[str], msg: str) -> None:
    errors.append(msg)


def _bonus_key(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def validate_slot_overrides_and_set_wearability(
    arts: list[dict], errors: list[str]
) -> None:
    """Fail closed: curated slot remaps applied, and every set tier is wearable."""
    if not SLOT_OVERRIDES.is_file():
        _fail(errors, f"missing slot overrides {SLOT_OVERRIDES}")
        return
    ov_doc = json.loads(SLOT_OVERRIDES.read_text(encoding="utf-8"))
    capacity_raw = ov_doc.get("oeSlotCapacity") or DEFAULT_OE_SLOT_CAPACITY
    if not isinstance(capacity_raw, dict) or not capacity_raw:
        _fail(errors, "slot overrides missing oeSlotCapacity{}")
        return
    capacity: dict[str, int] = {}
    for slot, n in capacity_raw.items():
        try:
            capacity[str(slot)] = int(n)
        except (TypeError, ValueError):
            _fail(errors, f"bad oeSlotCapacity for {slot!r}: {n!r}")
            return

    overrides = ov_doc.get("overrides")
    if not isinstance(overrides, list) or not overrides:
        _fail(errors, "slot overrides missing overrides[]")
        return
    arts_by_sid = {a["sid"]: a for a in arts if isinstance(a.get("sid"), str)}
    seen_sids: set[str] = set()
    for row in overrides:
        if not isinstance(row, dict):
            _fail(errors, "slot override row is not an object")
            continue
        sid = row.get("sid")
        want = row.get("slotOe")
        if not isinstance(sid, str) or sid in seen_sids:
            _fail(errors, f"bad/duplicate slot override sid {sid!r}")
            continue
        seen_sids.add(sid)
        if not isinstance(want, str) or want not in SLOT_TO_ITEM_FILE:
            _fail(errors, f"{sid}: override slotOe {want!r} not in SLOT_TO_ITEM_FILE")
            continue
        art = arts_by_sid.get(sid)
        if art is None:
            _fail(errors, f"slot override for unknown catalog sid {sid}")
            continue
        if art.get("slotOe") != want:
            _fail(
                errors,
                f"{sid}: catalog slotOe {art.get('slotOe')!r} != override {want!r}",
            )
        member = SLOT_TO_ITEM_FILE[want]
        overlay_item = OVERLAY / member
        if overlay_item.is_file():
            arr = json.loads(overlay_item.read_text(encoding="utf-8")).get("array") or []
            orow = next((r for r in arr if isinstance(r, dict) and r.get("id") == sid), None)
            if not orow:
                _fail(errors, f"{sid}: overlay missing after slot override in {member}")
            elif orow.get("slot_") != want:
                _fail(
                    errors,
                    f"{sid}: overlay slot_ {orow.get('slot_')!r} != override {want!r}",
                )

    if not SETS.is_file():
        return
    set_defs = json.loads(SETS.read_text(encoding="utf-8")).get("sets") or []
    arts_by_h3 = {int(a["h3Id"]): a for a in arts if isinstance(a.get("h3Id"), int)}
    for aset in set_defs:
        set_id = aset.get("id")
        if not isinstance(set_id, str):
            continue
        slot_counts: dict[str, int] = {}
        for h3_id in aset.get("componentH3Ids") or []:
            art = arts_by_h3.get(int(h3_id))
            if not art:
                continue
            slot = str(art.get("slotOe") or "item_slot")
            slot_counts[slot] = slot_counts.get(slot, 0) + 1
        wearable = 0
        for slot, count in slot_counts.items():
            cap = capacity.get(slot)
            if cap is None:
                _fail(errors, f"{set_id}: component uses unknown slot {slot!r}")
                continue
            if count > cap:
                # Surface the capacity clash explicitly (Statue of Legion / Misc→accessory).
                _fail(
                    errors,
                    f"{set_id}: {count} components use slot {slot!r} but OE capacity is "
                    f"{cap}; remap via {SLOT_OVERRIDES.name} or lower requiredItemsAmount",
                )
            wearable += min(count, cap if cap is not None else 0)
        for tier in aset.get("bonuses") or []:
            try:
                need = int(tier.get("requiredItemsAmount"))
            except (TypeError, ValueError):
                _fail(errors, f"{set_id}: bad requiredItemsAmount {tier.get('requiredItemsAmount')!r}")
                continue
            if need > wearable:
                _fail(
                    errors,
                    f"{set_id}: requiredItemsAmount {need} exceeds wearable capacity "
                    f"{wearable} under OE slot limits {dict(slot_counts)}",
                )


def validate_mechanics_contract(arts: list[dict], errors: list[str]) -> None:
    """Fail closed: every artifact has curated non-empty bonuses and matching overlay/Lang."""
    if not MECHANICS.is_file():
        _fail(errors, f"missing curated mechanics table {MECHANICS}")
        return
    mech_doc = json.loads(MECHANICS.read_text(encoding="utf-8"))
    mech_arts = mech_doc.get("artifacts")
    if not isinstance(mech_arts, dict) or not mech_arts:
        _fail(errors, "homm3_artifact_mechanics.json missing artifacts{}")
        return

    catalog_sids = {a["sid"] for a in arts if isinstance(a.get("sid"), str)}
    mech_sids = set(mech_arts)
    for sid in sorted(catalog_sids - mech_sids):
        _fail(errors, f"mechanics table missing catalog sid {sid}")
    for sid in sorted(mech_sids - catalog_sids):
        _fail(errors, f"mechanics table has unknown sid {sid}")

    lang_path = OVERLAY / "Lang/english/texts/artifacts.json"
    lang_sids: set[str] = set()
    lang_text: dict[str, str] = {}
    if lang_path.is_file():
        lang_doc = json.loads(lang_path.read_text(encoding="utf-8"))
        for t in (lang_doc.get("array") or []) + (lang_doc.get("tokens") or []):
            if isinstance(t, dict) and isinstance(t.get("sid"), str):
                lang_sids.add(t["sid"])
                if isinstance(t.get("text"), str):
                    lang_text[t["sid"]] = t["text"]

    for art in arts:
        sid = art.get("sid")
        if not isinstance(sid, str):
            continue
        status = art.get("mechanicsStatus")
        if status not in ALLOWED_MECHANICS_STATUS:
            _fail(
                errors,
                f"{sid}: mechanicsStatus {status!r} not allowed "
                f"(want {sorted(ALLOWED_MECHANICS_STATUS)}; text_only/mapped/partial forbidden)",
            )
        bonuses = art.get("bonuses") or []
        if not isinstance(bonuses, list) or not bonuses:
            _fail(errors, f"{sid}: empty catalog bonuses")
            continue
        # Duplicate bonus rows are a known prior defect; forbid them.
        seen: set[str] = set()
        for row in bonuses:
            if not isinstance(row, dict):
                _fail(errors, f"{sid}: non-object bonus row")
                continue
            key = _bonus_key(row)
            if key in seen:
                _fail(errors, f"{sid}: duplicate bonus row {key[:120]}")
            seen.add(key)

        mech = mech_arts.get(sid)
        if isinstance(mech, dict):
            if list(mech.get("bonuses") or []) != list(bonuses):
                _fail(errors, f"{sid}: catalog bonuses != mechanics table")
            if str(mech.get("description") or "").strip() != str(art.get("description") or "").strip():
                _fail(errors, f"{sid}: catalog description != mechanics table")
            if mech.get("mechanicsStatus") != status:
                _fail(errors, f"{sid}: catalog status != mechanics table")

        slot = art.get("slotOe") or "item_slot"
        member = SLOT_TO_ITEM_FILE.get(slot, SLOT_TO_ITEM_FILE["item_slot"])
        overlay_item = OVERLAY / member
        if overlay_item.is_file():
            arr = json.loads(overlay_item.read_text(encoding="utf-8")).get("array") or []
            row = next((r for r in arr if isinstance(r, dict) and r.get("id") == sid), None)
            if not row:
                _fail(errors, f"{sid}: overlay item missing for mechanics check")
            else:
                if list(row.get("bonuses") or []) != list(bonuses):
                    _fail(errors, f"{sid}: overlay bonuses != catalog bonuses")
                if not (row.get("bonuses") or []):
                    _fail(errors, f"{sid}: overlay bonuses empty")

        for suffix in ("_name", "_description", "_narrativeDescription"):
            want = sid + suffix
            if want not in lang_sids:
                _fail(errors, f"lang missing {want}")
        desc_sid = f"{sid}_description"
        if desc_sid in lang_text:
            want_desc = str(art.get("description") or "").strip()
            if lang_text[desc_sid].strip() != want_desc:
                _fail(errors, f"{sid}: lang description text != catalog description")


def validate(core: Path | None) -> list[str]:
    errors: list[str] = []
    if not CATALOG.is_file():
        return [f"missing catalog {CATALOG}"]
    doc = json.loads(CATALOG.read_text(encoding="utf-8"))
    arts = doc.get("artifacts") or []
    if len(arts) < 140:
        _fail(errors, f"catalog too small: {len(arts)} (expected SoD+HotA >= 140)")

    ids = set()
    for art in arts:
        sid = art.get("sid")
        h3_id = art.get("h3Id")
        if not isinstance(sid, str) or not sid.startswith("homm3_artifact_"):
            _fail(errors, f"bad sid {sid!r}")
            continue
        if not isinstance(h3_id, int):
            _fail(errors, f"{sid}: bad h3Id")
            continue
        if h3_id in ids:
            _fail(errors, f"duplicate h3Id {h3_id}")
        ids.add(h3_id)

        icon = ASSETS / "icons" / f"{sid}.png"
        if not icon.is_file():
            _fail(errors, f"missing icon {icon}")
        map_png = ASSETS / "map" / sid / "00_00.png"
        if not map_png.is_file():
            _fail(errors, f"missing map frame {map_png}")
        else:
            try:
                from PIL import Image

                rgba = Image.open(map_png).convert("RGBA")
                opaque = sum(1 for p in rgba.getdata() if p[3] > 0)
                if opaque < 1:
                    _fail(errors, f"{sid}: map frame has no opaque subject pixels")
                # Soft DEF shadows should already be culled; near-black partial-alpha is a regress.
                soft_shadow = sum(
                    1
                    for r, g, b, a in rgba.getdata()
                    if a > 0 and a < 200 and max(r, g, b) <= 8
                )
                if soft_shadow > 0:
                    _fail(errors, f"{sid}: map frame still has {soft_shadow} DEF soft-shadow pixels")
            except Exception as ex:  # noqa: BLE001 — surface as contract failure
                _fail(errors, f"{sid}: map frame unreadable ({ex})")

        slot = art.get("slotOe") or "item_slot"
        member = SLOT_TO_ITEM_FILE.get(slot, SLOT_TO_ITEM_FILE["item_slot"])
        overlay_item = OVERLAY / member
        if overlay_item.is_file():
            arr = json.loads(overlay_item.read_text(encoding="utf-8")).get("array") or []
            if not any(isinstance(r, dict) and r.get("id") == sid for r in arr):
                _fail(errors, f"overlay item missing {sid} in {member}")
        else:
            _fail(errors, f"missing generated overlay member {member}")

    validate_mechanics_contract(arts, errors)
    validate_slot_overrides_and_set_wearability(arts, errors)

    # Combination item sets
    if not SETS.is_file():
        _fail(errors, f"missing sets definition {SETS}")
    else:
        set_doc = json.loads(SETS.read_text(encoding="utf-8"))
        set_defs = set_doc.get("sets") or []
        if len(set_defs) < 12:
            _fail(errors, f"too few sets: {len(set_defs)} (expected SoD+HotA combinations)")
        arts_by_h3 = {int(a["h3Id"]): a for a in arts if isinstance(a.get("h3Id"), int)}
        overlay_sets_path = OVERLAY / "DB/items/item_sets/item_sets.json"
        overlay_sets = {}
        if overlay_sets_path.is_file():
            overlay_sets = {
                r.get("id"): r
                for r in (json.loads(overlay_sets_path.read_text(encoding="utf-8")).get("array") or [])
                if isinstance(r, dict) and r.get("id")
            }
        else:
            _fail(errors, "missing generated overlay DB/items/item_sets/item_sets.json")

        lang_path = OVERLAY / "Lang/english/texts/artifacts.json"
        lang_tokens = []
        if lang_path.is_file():
            lang_doc = json.loads(lang_path.read_text(encoding="utf-8"))
            lang_tokens = (lang_doc.get("array") or []) + (lang_doc.get("tokens") or [])
        lang_sids = {t.get("sid") for t in lang_tokens if isinstance(t, dict)}

        claimed: dict[int, str] = {}
        for aset in set_defs:
            set_id = aset.get("id")
            if not isinstance(set_id, str) or not set_id.startswith("homm3_"):
                _fail(errors, f"bad set id {set_id!r}")
                continue
            components = aset.get("componentH3Ids") or []
            if len(components) < 2:
                _fail(errors, f"{set_id}: need >=2 components")
            want_sids = []
            for h3_id in components:
                h3_id = int(h3_id)
                art = arts_by_h3.get(h3_id)
                if not art:
                    _fail(errors, f"{set_id}: missing catalog h3Id {h3_id}")
                    continue
                if art.get("setId") != set_id:
                    _fail(errors, f"{art['sid']}: catalog setId want {set_id} got {art.get('setId')}")
                if h3_id in claimed:
                    _fail(errors, f"h3Id {h3_id} in both {claimed[h3_id]} and {set_id}")
                claimed[h3_id] = set_id
                want_sids.append(art["sid"])

                slot = art.get("slotOe") or "item_slot"
                member = SLOT_TO_ITEM_FILE.get(slot, SLOT_TO_ITEM_FILE["item_slot"])
                overlay_item = OVERLAY / member
                if overlay_item.is_file():
                    arr = json.loads(overlay_item.read_text(encoding="utf-8")).get("array") or []
                    row = next((r for r in arr if isinstance(r, dict) and r.get("id") == art["sid"]), None)
                    if not row:
                        _fail(errors, f"overlay missing set member {art['sid']}")
                    elif row.get("itemSet") != set_id:
                        _fail(errors, f"{art['sid']}: overlay itemSet want {set_id} got {row.get('itemSet')}")

            orow = overlay_sets.get(set_id)
            if not orow:
                _fail(errors, f"overlay item_sets missing {set_id}")
            else:
                got = list(orow.get("itemsInSet") or [])
                if got != want_sids:
                    _fail(errors, f"{set_id}: itemsInSet mismatch")
                if not (orow.get("bonuses") or []):
                    _fail(errors, f"{set_id}: empty bonuses")
            if set_id not in lang_sids:
                _fail(errors, f"lang missing set name {set_id}")
            for tier in aset.get("bonuses") or []:
                desc = tier.get("desc")
                if desc and desc not in lang_sids:
                    _fail(errors, f"lang missing set desc {desc}")

    # Lang / map / logic members
    for member in (
        "DB/map/objects/6_artifacts.json",
        "DB/objects_logic/items/artifacts.json",
        "Lang/english/texts/artifacts.json",
    ):
        path = OVERLAY / member
        if not path.is_file():
            _fail(errors, f"missing overlay member {member}")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if member.endswith("artifacts.json") and "Lang/" in member:
            tokens = (data.get("array") or []) + (data.get("tokens") or [])
            for art in arts:
                sid = art["sid"]
                for suffix in ("_name", "_description"):
                    want = sid + suffix
                    if not any(isinstance(t, dict) and t.get("sid") == want for t in tokens):
                        _fail(errors, f"lang missing {want}")
        else:
            arr = data.get("array") or []
            for art in arts:
                sid = art["sid"]
                if not any(isinstance(r, dict) and r.get("id") == sid for r in arr):
                    _fail(errors, f"{member} missing id {sid}")

    # Billboard asset manifest must cover every catalog SID (map + icon paths).
    # Catalog SIDs are the billboard lookup keys; donor map prefs are intentional shells.
    manifest_path = ASSETS / "artifact_asset_manifest.json"
    if not manifest_path.is_file():
        _fail(errors, f"missing billboard manifest {manifest_path}")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("artifacts") if isinstance(manifest, dict) else None
        if not isinstance(entries, dict):
            _fail(errors, "artifact_asset_manifest.json missing artifacts{} map")
        else:
            catalog_sids = {a["sid"] for a in arts if isinstance(a.get("sid"), str)}
            manifest_sids = set(entries)
            missing_manifest = sorted(catalog_sids - manifest_sids)
            extra_manifest = sorted(manifest_sids - catalog_sids)
            if missing_manifest:
                _fail(
                    errors,
                    f"manifest missing {len(missing_manifest)} catalog SID(s); "
                    f"sample {missing_manifest[:5]}",
                )
            if extra_manifest:
                _fail(
                    errors,
                    f"manifest has {len(extra_manifest)} SID(s) not in catalog; "
                    f"sample {extra_manifest[:5]}",
                )
            for sid in sorted(catalog_sids & manifest_sids):
                row = entries.get(sid) or {}
                map_rel = row.get("map")
                icon_rel = row.get("icon")
                if not isinstance(map_rel, str) or not map_rel.strip():
                    _fail(errors, f"manifest {sid}: missing map path")
                else:
                    map_path = (
                        ROOT
                        / "Heroes of Might & Magic Olden Era Playtest"
                        / "OfflineUnlockMod"
                        / map_rel.replace("\\", "/")
                    )
                    if not map_path.is_file():
                        _fail(errors, f"manifest {sid}: map file missing {map_rel}")
                if not isinstance(icon_rel, str) or not icon_rel.strip():
                    _fail(errors, f"manifest {sid}: missing icon path")
                else:
                    icon_path = (
                        ROOT
                        / "Heroes of Might & Magic Olden Era Playtest"
                        / "OfflineUnlockMod"
                        / icon_rel.replace("\\", "/")
                    )
                    if not icon_path.is_file():
                        _fail(errors, f"manifest {sid}: icon file missing {icon_rel}")

            # Overlay map objects must keep a donor pref shell so adventure Init has a host.
            map_objs_path = OVERLAY / "DB/map/objects/6_artifacts.json"
            if map_objs_path.is_file():
                arr = json.loads(map_objs_path.read_text(encoding="utf-8")).get("array") or []
                by_id = {
                    r.get("id"): r
                    for r in arr
                    if isinstance(r, dict) and isinstance(r.get("id"), str)
                }
                for sid in sorted(catalog_sids):
                    row = by_id.get(sid)
                    if not row:
                        continue
                    prefs = row.get("prefs") or []
                    if not isinstance(prefs, list) or not prefs:
                        _fail(errors, f"map object {sid}: empty prefs (billboard needs donor shell)")

    # Phase 2: staged AssetBundle membership (when present — required after first Unity build).
    # Asset names: artifact_map_billboard_<sid>. Catalog SIDs must match manifest exactly.
    bundle_stage = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "homm3_artifact_map_billboards"
    )
    bundle_file = bundle_stage / "homm3_artifact_map_billboards"
    bundle_manifest = bundle_stage / "manifest.json"
    if bundle_file.is_file() or bundle_manifest.is_file():
        if not bundle_file.is_file():
            _fail(errors, f"artifact map billboard bundle missing {bundle_file}")
        if not bundle_manifest.is_file():
            _fail(errors, f"artifact map billboard manifest missing {bundle_manifest}")
        else:
            bman = json.loads(bundle_manifest.read_text(encoding="utf-8"))
            if bman.get("bundle") != "homm3_artifact_map_billboards":
                _fail(
                    errors,
                    f"artifact map billboard manifest bundle mismatch: {bman.get('bundle')!r}",
                )
            assets = bman.get("assets")
            if not isinstance(assets, list):
                _fail(errors, "artifact map billboard manifest missing assets[]")
            else:
                catalog_sids = {a["sid"] for a in arts if isinstance(a.get("sid"), str)}
                expected = {f"artifact_map_billboard_{sid}" for sid in catalog_sids}
                got = set(assets)
                missing_b = sorted(expected - got)
                extra_b = sorted(got - expected)
                if missing_b:
                    _fail(
                        errors,
                        f"artifact map billboard bundle missing {len(missing_b)} catalog SID(s); "
                        f"sample {missing_b[:5]}",
                    )
                if extra_b:
                    _fail(
                        errors,
                        f"artifact map billboard bundle has {len(extra_b)} asset(s) not in catalog; "
                        f"sample {extra_b[:5]}",
                    )

    if core and core.is_file():
        with zipfile.ZipFile(core) as zf:
            names = set(zf.namelist())
            # Soft check: if overlay already applied, Core contains SIDs.
            if "DB/map/objects/6_artifacts.json" in names:
                arr = json.loads(zf.read("DB/map/objects/6_artifacts.json")).get("array") or []
                present = {r.get("id") for r in arr if isinstance(r, dict)}
                sample = [a["sid"] for a in arts[:5]]
                missing_core = [s for s in sample if s not in present]
                if missing_core:
                    # Not an hard error — overlay may not be installed yet.
                    print(
                        "NOTE: live Core.zip missing sample artifact SIDs "
                        f"{missing_core} (run apply_release_core_overlay to install)",
                        file=sys.stderr,
                    )
            if "DB/items/item_sets/item_sets.json" in names and SETS.is_file():
                core_sets = {
                    r.get("id")
                    for r in (json.loads(zf.read("DB/items/item_sets/item_sets.json")).get("array") or [])
                    if isinstance(r, dict)
                }
                set_defs = json.loads(SETS.read_text(encoding="utf-8")).get("sets") or []
                missing_sets = [s["id"] for s in set_defs if s.get("id") not in core_sets]
                if missing_sets:
                    print(
                        "NOTE: live Core.zip missing sample item sets "
                        f"{missing_sets[:3]} (run apply_release_core_overlay to install)",
                        file=sys.stderr,
                    )

    return errors


def validate_plugin_billboard_assets(plugin_root: Path, arts: list[dict]) -> list[str]:
    """Fail-closed: deployed plugin must carry map/icon PNGs for every catalog SID."""
    errors: list[str] = []
    if not plugin_root.is_dir():
        return [f"missing plugin root {plugin_root}"]
    for art in arts:
        sid = art.get("sid")
        if not isinstance(sid, str) or not sid.startswith("homm3_artifact_"):
            continue
        map_png = plugin_root / "homm3_runtime_assets" / "artifacts" / "map" / sid / "00_00.png"
        icon_png = plugin_root / "homm3_runtime_assets" / "artifacts" / "icons" / f"{sid}.png"
        if not map_png.is_file():
            errors.append(f"plugin missing map frame {map_png.relative_to(plugin_root)}")
        if not icon_png.is_file():
            errors.append(f"plugin missing icon {icon_png.relative_to(plugin_root)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--require-core-installed", action="store_true")
    parser.add_argument(
        "--require-plugin-assets",
        type=Path,
        default=None,
        help="Fail if plugin deploy dir is missing catalog map/icon PNGs.",
    )
    args = parser.parse_args()
    errors = validate(args.core if args.core.is_file() else None)
    if args.require_core_installed and args.core.is_file():
        with zipfile.ZipFile(args.core) as zf:
            arr = json.loads(zf.read("DB/map/objects/6_artifacts.json")).get("array") or []
            present = {r.get("id") for r in arr if isinstance(r, dict)}
            doc = json.loads(CATALOG.read_text(encoding="utf-8"))
            for art in doc.get("artifacts") or []:
                sid = art["sid"]
                if sid not in present:
                    errors.append(f"installed Core missing map object {sid}")
            set_defs = json.loads(SETS.read_text(encoding="utf-8")).get("sets") or []
            core_sets = {
                r.get("id"): r
                for r in (json.loads(zf.read("DB/items/item_sets/item_sets.json")).get("array") or [])
                if isinstance(r, dict)
            }
            for aset in set_defs:
                set_id = aset["id"]
                if set_id not in core_sets:
                    errors.append(f"installed Core missing item set {set_id}")
                    continue
                arts_by_h3 = {
                    int(a["h3Id"]): a
                    for a in (doc.get("artifacts") or [])
                    if isinstance(a.get("h3Id"), int)
                }
                want = [arts_by_h3[int(h)]["sid"] for h in aset.get("componentH3Ids") or []]
                got = list(core_sets[set_id].get("itemsInSet") or [])
                if got != want:
                    errors.append(f"installed Core {set_id} itemsInSet mismatch")
    if args.require_plugin_assets is not None:
        doc = json.loads(CATALOG.read_text(encoding="utf-8"))
        errors.extend(validate_plugin_billboard_assets(args.require_plugin_assets, doc.get("artifacts") or []))
    if errors:
        print(f"FAIL ({len(errors)}):")
        for e in errors[:80]:
            print(" -", e)
        if len(errors) > 80:
            print(f" ... {len(errors) - 80} more")
        return 1
    print("OK: HoMM3 artifact port catalog/assets/overlay validated (generated-artifact).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
