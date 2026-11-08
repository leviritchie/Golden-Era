#!/usr/bin/env python3
"""Merge HoMM3 artifact catalog rows into Core.zip overlay members.

Generated-artifact / install path only. Runtime equip proof is separate.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "custom_factions" / "artifacts" / "homm3_artifact_catalog.json"
SETS_PATH = ROOT / "custom_factions" / "artifacts" / "homm3_artifact_sets.json"
GENERATED_OVERLAY_DIR = ROOT / "custom_factions" / "artifacts" / "generated_core_overlay"

# OE packs main-hand (slot_ left_hand) under right_hand.json and off-hand under left_hand.json.
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

DONOR_MAP_PREFS = ["artifact/ukhtabar_seal_tabar_seal_artifact"]
MAP_OBJECT_TEMPLATE = {
    "tag": "Artifact",
    "isInteractable": True,
    "prefs": DONOR_MAP_PREFS,
    "selectionUiPrefabID": "1x1",
    "pivotX": 1,
    "pivotZ": 1,
    "sizeX": 3,
    "sizeZ": 3,
    "offsetX": 0,
    "offsetZ": 0,
    "nodes": [2, 2, 2, 2, 1, 2, 2, 2, 2],
}

RARITY_COST = {
    "common": (15, 10, 10),
    "rare": (30, 20, 20),
    "epic": (45, 30, 30),
    "legendary": (60, 40, 40),
}

RARITY_ROLL = {
    "common": 20,
    "rare": 12,
    "epic": 6,
    "legendary": 3,
}


def write_json(doc: Any) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def read_json_member(release_zip: zipfile.ZipFile, name: str) -> Any:
    return json.loads(release_zip.read(name).decode("utf-8-sig"))


def load_catalog() -> list[dict[str, Any]]:
    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(
            f"missing artifact catalog {CATALOG_PATH}; run tools/homm3_import/build_homm3_artifact_catalog.py"
        )
    doc = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    arts = doc.get("artifacts")
    if not isinstance(arts, list) or not arts:
        raise RuntimeError("artifact catalog has no artifacts[]")
    return arts


def load_sets() -> list[dict[str, Any]]:
    if not SETS_PATH.is_file():
        raise FileNotFoundError(f"missing artifact sets definition {SETS_PATH}")
    doc = json.loads(SETS_PATH.read_text(encoding="utf-8"))
    sets = doc.get("sets")
    if not isinstance(sets, list) or not sets:
        raise RuntimeError("artifact sets definition has no sets[]")
    return sets


def build_set_membership(arts: list[dict[str, Any]], sets: list[dict[str, Any]]) -> dict[int, str]:
    """Map component h3Id -> set id. Fail closed on unknown / duplicate membership."""
    by_h3 = {int(a["h3Id"]): a for a in arts if isinstance(a.get("h3Id"), int)}
    membership: dict[int, str] = {}
    for aset in sets:
        set_id = aset["id"]
        for h3_id in aset.get("componentH3Ids") or []:
            h3_id = int(h3_id)
            if h3_id not in by_h3:
                raise RuntimeError(f"{set_id}: missing component h3Id {h3_id} in catalog")
            if h3_id in membership and membership[h3_id] != set_id:
                raise RuntimeError(
                    f"h3Id {h3_id} claimed by both {membership[h3_id]} and {set_id}"
                )
            membership[h3_id] = set_id
        assembled = aset.get("assembledH3Id")
        if assembled is not None and int(assembled) in membership:
            raise RuntimeError(
                f"{set_id}: assembledH3Id {assembled} must not also be a component"
            )
    return membership


def sync_catalog_set_ids(arts: list[dict[str, Any]], membership: dict[int, str]) -> None:
    """Write setId onto catalog rows (components only) and persist catalog."""
    changed = False
    for art in arts:
        h3_id = art.get("h3Id")
        want = membership.get(int(h3_id)) if isinstance(h3_id, int) else None
        if art.get("setId") != want:
            if want is None:
                art.pop("setId", None)
            else:
                art["setId"] = want
            changed = True
    if not changed:
        return
    doc = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    doc["artifacts"] = arts
    CATALOG_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def make_item_row(art: dict[str, Any]) -> dict[str, Any]:
    sid = art["sid"]
    slot = art["slotOe"]
    rarity = art.get("rarityOe") or "common"
    cost_base, cost_per, reward = RARITY_COST.get(rarity, RARITY_COST["common"])
    row: dict[str, Any] = {
        "id": sid,
        "slot_": slot,
        "rarity": rarity,
        "icon": sid,
        "name": f"{sid}_name",
        "description": f"{sid}_description",
        "upgradeDescription": "artifact_tech_cannot_be_upgraded",
        "narrativeDescription": f"{sid}_narrativeDescription",
        "goodsValue": int(art.get("goodsValue") or 3000),
        "costBase": cost_base,
        "costPerLevel": cost_per,
        "rewardForDestroy": reward,
        "maxLevel": 1,
        "bonuses": list(art.get("bonuses") or []),
        "itemSet": art.get("setId"),
    }
    if art.get("isSpecialItem"):
        row["isSpecialItem"] = True
        row["useExpandTooltip"] = "false"
    return row


def make_set_row(aset: dict[str, Any], arts_by_h3: dict[int, dict[str, Any]]) -> dict[str, Any]:
    items: list[str] = []
    for h3_id in aset.get("componentH3Ids") or []:
        art = arts_by_h3[int(h3_id)]
        items.append(art["sid"])
    bonuses_out: list[dict[str, Any]] = []
    for tier in aset.get("bonuses") or []:
        bonuses_out.append(
            {
                "requiredItemsAmount": str(tier["requiredItemsAmount"]),
                "desc": tier["desc"],
                "heroBonuses": list(tier.get("heroBonuses") or []),
            }
        )
    return {
        "id": aset["id"],
        "name": aset["id"],
        "itemsInSet": items,
        "bonuses": bonuses_out,
    }


def make_set_lang_rows(aset: dict[str, Any]) -> list[dict[str, str]]:
    rows = [{"sid": aset["id"], "text": str(aset.get("name") or aset["id"])}]
    for tier in aset.get("bonuses") or []:
        desc_sid = tier.get("desc")
        desc_text = tier.get("descText")
        if desc_sid and desc_text:
            rows.append({"sid": str(desc_sid), "text": str(desc_text)})
    return rows


def make_map_row(art: dict[str, Any]) -> dict[str, Any]:
    row = dict(MAP_OBJECT_TEMPLATE)
    row["id"] = art["sid"]
    return row


def make_logic_row(art: dict[str, Any]) -> dict[str, Any]:
    return {"id": art["sid"], "goodsValue": int(art.get("goodsValue") or 3000)}


def make_market_row(art: dict[str, Any]) -> dict[str, Any]:
    rarity = art.get("rarityOe") or "common"
    return {
        "id": art["sid"],
        "sid": art["sid"],
        "costInGold": int(art.get("goodsValue") or 3000),
        "rollChance": RARITY_ROLL.get(rarity, 10),
    }


def make_lang_rows(art: dict[str, Any]) -> list[dict[str, str]]:
    sid = art["sid"]
    name = str(art.get("name") or sid)
    desc = str(art.get("description") or name)
    return [
        {"sid": f"{sid}_name", "text": name},
        {"sid": f"{sid}_description", "text": desc},
        {"sid": f"{sid}_narrativeDescription", "text": desc},
    ]


def upsert_array_by_id(doc: dict[str, Any], rows: list[dict[str, Any]], id_key: str = "id") -> int:
    arr = doc.get("array")
    if not isinstance(arr, list):
        arr = []
        doc["array"] = arr
    by_id = {
        str(item.get(id_key)): i
        for i, item in enumerate(arr)
        if isinstance(item, dict) and item.get(id_key) is not None
    }
    changed = 0
    for row in rows:
        rid = str(row[id_key])
        if rid in by_id:
            arr[by_id[rid]] = row
        else:
            arr.append(row)
        changed += 1
    return changed


def upsert_lang(doc: dict[str, Any], rows: list[dict[str, str]]) -> int:
    changed = 0
    for list_name in ("tokens", "array"):
        arr = doc.get(list_name)
        if not isinstance(arr, list):
            if list_name == "tokens":
                arr = []
                doc[list_name] = arr
            else:
                continue
        by_sid = {
            str(item.get("sid")): i
            for i, item in enumerate(arr)
            if isinstance(item, dict) and item.get("sid")
        }
        for row in rows:
            sid = row["sid"]
            if sid in by_sid:
                arr[by_sid[sid]] = row
            else:
                arr.append(row)
                by_sid[sid] = len(arr) - 1
            changed += 1
    return changed


def merge_homm3_artifacts_into_overlay(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str] | None = None,
) -> dict[str, bytes]:
    """Merge catalog artifacts into overlay member map. Mutates/returns output."""
    notes = notes if notes is not None else []
    arts = load_catalog()
    sets = load_sets()
    membership = build_set_membership(arts, sets)
    sync_catalog_set_ids(arts, membership)
    arts_by_h3 = {int(a["h3Id"]): a for a in arts if isinstance(a.get("h3Id"), int)}

    items_by_file: dict[str, list[dict[str, Any]]] = {path: [] for path in SLOT_TO_ITEM_FILE.values()}
    map_rows: list[dict[str, Any]] = []
    logic_rows: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    lang_rows: list[dict[str, str]] = []
    set_rows: list[dict[str, Any]] = []

    for art in arts:
        slot = art.get("slotOe") or "item_slot"
        member = SLOT_TO_ITEM_FILE.get(slot, SLOT_TO_ITEM_FILE["item_slot"])
        items_by_file[member].append(make_item_row(art))
        map_rows.append(make_map_row(art))
        logic_rows.append(make_logic_row(art))
        if not art.get("isSpecialItem"):
            market_rows.append(make_market_row(art))
        lang_rows.extend(make_lang_rows(art))

    for aset in sets:
        set_rows.append(make_set_row(aset, arts_by_h3))
        lang_rows.extend(make_set_lang_rows(aset))

    def load_member(name: str) -> dict[str, Any]:
        if name in output:
            return json.loads(output[name].decode("utf-8-sig"))
        return read_json_member(release_zip, name)

    for member, rows in items_by_file.items():
        if not rows:
            continue
        doc = load_member(member)
        upsert_array_by_id(doc, rows)
        output[member] = write_json(doc)
        notes.append(f"merge {len(rows)} HoMM3 artifacts into {member}")

    # Slot remaps can move an artifact between item files. Remove catalog SIDs from
    # non-target slot members so a prior accessory row cannot linger next to belt/etc.
    catalog_sids = {str(a["sid"]) for a in arts if isinstance(a.get("sid"), str)}
    sid_to_member = {}
    for art in arts:
        sid = art.get("sid")
        if not isinstance(sid, str):
            continue
        slot = art.get("slotOe") or "item_slot"
        sid_to_member[sid] = SLOT_TO_ITEM_FILE.get(slot, SLOT_TO_ITEM_FILE["item_slot"])
    for member in SLOT_TO_ITEM_FILE.values():
        doc = load_member(member)
        arr = doc.get("array")
        if not isinstance(arr, list):
            continue
        kept: list[Any] = []
        removed = 0
        for item in arr:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            rid = item.get("id")
            if (
                isinstance(rid, str)
                and rid in catalog_sids
                and sid_to_member.get(rid) != member
            ):
                removed += 1
                continue
            kept.append(item)
        if removed:
            doc["array"] = kept
            output[member] = write_json(doc)
            notes.append(f"remove {removed} relocated HoMM3 artifacts from {member}")

    for member, rows in [
        ("DB/map/objects/6_artifacts.json", map_rows),
        ("DB/objects_logic/items/artifacts.json", logic_rows),
        ("DB/market_items/market_items.json", market_rows),
        ("DB/items/item_sets/item_sets.json", set_rows),
    ]:
        doc = load_member(member)
        upsert_array_by_id(doc, rows)
        output[member] = write_json(doc)
        notes.append(f"merge {len(rows)} HoMM3 rows into {member}")

    lang_member = "Lang/english/texts/artifacts.json"
    lang_doc = load_member(lang_member)
    upsert_lang(lang_doc, lang_rows)
    output[lang_member] = write_json(lang_doc)
    notes.append(f"merge {len(lang_rows)} HoMM3 artifact Lang rows into {lang_member}")

    # Persist generated members for inspection / standalone install.
    GENERATED_OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    touched = {
        *items_by_file.keys(),
        "DB/map/objects/6_artifacts.json",
        "DB/objects_logic/items/artifacts.json",
        "DB/market_items/market_items.json",
        "DB/items/item_sets/item_sets.json",
        lang_member,
    }
    for name, data in output.items():
        if name not in touched:
            continue
        target = GENERATED_OVERLAY_DIR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    notes.append(
        f"HoMM3 artifact overlay: {len(arts)} artifacts, {len(set_rows)} item sets, "
        f"{len(membership)} set members"
    )
    return output


def generate_standalone(core_path: Path) -> int:
    with zipfile.ZipFile(core_path) as zf:
        output: dict[str, bytes] = {}
        notes: list[str] = []
        merge_homm3_artifacts_into_overlay(zf, output, notes)
    for note in notes:
        print(note)
    print(f"wrote inspection members under {GENERATED_OVERLAY_DIR}")
    return 0


def main() -> int:
    core = Path(
        r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
        r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
    )
    if len(sys.argv) > 1:
        core = Path(sys.argv[1])
    if not core.is_file():
        print(f"missing Core.zip: {core}", file=sys.stderr)
        return 1
    return generate_standalone(core)


if __name__ == "__main__":
    raise SystemExit(main())
