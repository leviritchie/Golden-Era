#!/usr/bin/env python3
"""Build SoD+HotA artifact catalog and extract icon/map PNGs for Olden Era.

Sources (local):
- HD Edition H3BITMAP.LOD artraits.txt (classic names/slots/class/cost/desc)
- HD Edition H3SPRITE.LOD AVA####.def (classic map art)
- VCMI HotA heroes3DataPatch ArtIm###.png (UI icons, preferred)
- VCMI HotA mods/artifacts (+ supplementary/cannon/horn) for HotA extras
- custom_factions/artifacts/homm3_artifact_mechanics.json (authoritative bonuses + effect text)

Evidence: generated-artifact only. Runtime equip/billboard proof is separate.

Use --apply-mechanics-only to re-apply the curated mechanics table onto an existing
catalog without re-extracting LOD/icons (for environments without HD Edition data).
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HD_DATA = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might & Magic III - HD Edition/data"
)
BITMAP_LOD = HD_DATA / "H3BITMAP.LOD"
SPRITE_LOD = HD_DATA / "H3SPRITE.LOD"
VCMI_HOTA = ROOT / "vcmi" / "Mods" / "hota" / "mods"
DEFEXTRACT = ROOT / "tools" / "defextract_py3.py"

OUT_CATALOG = ROOT / "custom_factions" / "artifacts" / "homm3_artifact_catalog.json"
MECHANICS_PATH = ROOT / "custom_factions" / "artifacts" / "homm3_artifact_mechanics.json"
SLOT_OVERRIDES_PATH = (
    ROOT / "custom_factions" / "artifacts" / "homm3_artifact_slot_overrides.json"
)
OUT_ASSETS = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "artifacts"
)
OUT_ICONS = OUT_ASSETS / "icons"
OUT_MAP = OUT_ASSETS / "map"
OUT_MANIFEST = OUT_ASSETS / "artifact_asset_manifest.json"
OUT_WORK = ROOT / "artifacts" / "homm3_artifact_port" / "work"

SLOT_COLS = [
    "Spell Book",
    "War Machine 4",
    "War Machine 3",
    "War Machine 2",
    "War Machine 1",
    "Misc 4",
    "Misc 3",
    "Misc 2",
    "Misc 1",
    "Feet",
    "Left Ring",
    "Right Ring",
    "Torso",
    "Left Hand",
    "Right Hand",
    "Neck",
    "Shoulders",
    "Head",
]

H3_SLOT_TO_OE = {
    "Head": "head",
    "Shoulders": "back",
    "Neck": "item_slot",
    "Right Hand": "left_hand",
    "Left Hand": "right_hand",
    "Torso": "armor",
    "Right Ring": "ring",
    "Left Ring": "ring",
    "Feet": "boots",
    "Misc 1": "item_slot",
    "Misc 2": "item_slot",
    "Misc 3": "item_slot",
    "Misc 4": "item_slot",
    "Spell Book": "item_slot",
    "War Machine 1": "item_slot",
    "War Machine 2": "item_slot",
    "War Machine 3": "item_slot",
    "War Machine 4": "item_slot",
}

HOTA_SLOT_TO_OE = {
    "HEAD": "head",
    "SHOULDERS": "back",
    "NECK": "item_slot",
    "RIGHT_HAND": "left_hand",
    "LEFT_HAND": "right_hand",
    "TORSO": "armor",
    "RIGHT_RING": "ring",
    "LEFT_RING": "ring",
    "RING": "ring",
    "FEET": "boots",
    "MISC": "item_slot",
    "MISC1": "item_slot",
    "MISC2": "item_slot",
    "MISC3": "item_slot",
    "MISC4": "item_slot",
    "MISC5": "item_slot",
    "MACH1": "item_slot",
    "MACH2": "item_slot",
    "MACH3": "item_slot",
    "MACH4": "item_slot",
}

CLASS_TO_RARITY = {
    "S": "common",
    "T": "common",
    "N": "rare",
    "J": "epic",
    "R": "legendary",
    "TREASURE": "common",
    "MINOR": "rare",
    "MAJOR": "epic",
    "RELIC": "legendary",
    "SPECIAL": "common",
}

# SoD artraits.txt ends at 126; AB campaign pickups occupy 127–141 before HotA.
AB_CAMPAIGN_ARTIFACT_SEEDS: list[dict[str, Any]] = [
    {
        "h3Id": 127,
        "sid": "homm3_artifact_127_vial_of_dragon_blood",
        "slug": "vial_of_dragon_blood",
        "name": "Vial of Dragon Blood",
        "description": (
            "This vial of dragon blood allows its bearer to claim an unclaimed town as their own."
        ),
        "slotOe": "item_slot",
        "h3Slots": ["Misc 1", "Misc 2", "Misc 3", "Misc 4"],
        "rarityOe": "legendary",
        "h3Class": "R",
        "goodsValue": 20000,
        "isSpecialItem": True,
        "bonuses": [],
        "mechanicsStatus": "text_only",
        "source": "ab_campaign_seed",
        "iconKey": "homm3_artifact_127_vial_of_dragon_blood",
        "mapAva": "AVA0127",
    },
    {
        "h3Id": 128,
        "sid": "homm3_artifact_128_armageddons_blade",
        "slug": "armageddons_blade",
        "name": "Armageddon's Blade",
        "description": (
            "This legendary blade grants immense power to its wielder and enables the Armageddon spell."
        ),
        "slotOe": "left_hand",
        "h3Slots": ["RIGHT HAND"],
        "rarityOe": "legendary",
        "h3Class": "R",
        "goodsValue": 50000,
        "isSpecialItem": True,
        "bonuses": [],
        "mechanicsStatus": "text_only",
        "source": "ab_campaign_seed",
        "iconKey": "homm3_artifact_128_armageddons_blade",
        "mapAva": "AVA0129",
    },
]

PRIMARY_SKILL_TO_OE = {
    "attack": "offence",
    "defence": "defence",
    "defense": "defence",
    "power": "spellPower",
    "spellpower": "spellPower",
    "knowledge": "intelligence",
}

SPECIAL_ITEM_NAMES = {
    "spell book",
    "spell scroll",
    "the grail",
    "catapult",
    "ballista",
    "ammo cart",
    "first aid tent",
    "cannon",
}


def slugify(name: str) -> str:
    s = name.lower().replace("'", "").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:48] or "artifact"


def clean_description(raw: str) -> str:
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    # Strip {Name} header block common in H3 descriptions.
    text = re.sub(r"^\{[^}]+\}\s*", "", text)
    return text.strip() or "HoMM3 artifact."


def extract_lod_member(lod_path: Path, member: str) -> bytes:
    data = lod_path.read_bytes()
    if data[:4] != b"LOD\0":
        raise RuntimeError(f"not LOD: {lod_path}")
    total = struct.unpack_from("<I", data, 8)[0]
    off = 92
    want = member.lower().encode("ascii")
    for _ in range(total):
        raw = data[off : off + 16]
        off += 16
        nul = raw.find(b"\0")
        name = raw[:nul] if nul >= 0 else raw
        o, size, _u, csize = struct.unpack_from("<IIII", data, off)
        off += 16
        if name.lower() != want:
            continue
        blob = data[o : o + (csize or size)]
        return zlib.decompress(blob) if csize else blob
    raise FileNotFoundError(f"{member} not in {lod_path}")


def loads_jsonc(text: str) -> Any:
    # Strip // and /* */ comments for VCMI-ish JSON.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out: list[str] = []
    for line in text.splitlines():
        if "//" in line:
            in_str = False
            cleaned = []
            i = 0
            while i < len(line):
                ch = line[i]
                if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                    in_str = not in_str
                if not in_str and line[i : i + 2] == "//":
                    break
                cleaned.append(ch)
                i += 1
            line = "".join(cleaned)
        out.append(line)
    cleaned_text = "\n".join(out)
    # Trailing commas
    cleaned_text = re.sub(r",\s*([}\]])", r"\1", cleaned_text)
    return json.loads(cleaned_text)


def parse_artraits(text: str) -> list[dict[str, Any]]:
    reader = csv.reader(io.StringIO(text), delimiter="\t", quotechar='"')
    rows = list(reader)
    if len(rows) < 3:
        raise RuntimeError("artraits.txt too short")
    header = rows[1]
    name_i = header.index("Name")
    cost_i = header.index("Cost")
    class_i = header.index('Class (S,T,N,J,R)')
    desc_i = header.index("Description")
    slot_indices = {name: header.index(name) for name in SLOT_COLS}
    artifacts: list[dict[str, Any]] = []
    for h3_id, row in enumerate(rows[2:]):
        if not row or not str(row[0]).strip():
            continue
        while len(row) < len(header):
            row.append("")
        name = row[name_i].strip()
        if not name:
            continue
        # Skip blank filler names sometimes present as empty placeholders.
        if name.lower() in {"", "empty", "none"}:
            continue
        slots = [
            sn for sn in SLOT_COLS if str(row[slot_indices[sn]]).strip().lower() == "x"
        ]
        primary_slot = slots[0] if slots else "Misc 1"
        oe_slot = H3_SLOT_TO_OE.get(primary_slot, "item_slot")
        cls = (row[class_i] or "T").strip().upper() or "T"
        try:
            cost = int(float(str(row[cost_i]).strip() or "0"))
        except ValueError:
            cost = 0
        desc = clean_description(row[desc_i])
        special = name.lower() in SPECIAL_ITEM_NAMES or primary_slot.startswith(
            "War Machine"
        ) or primary_slot == "Spell Book"
        bonuses, status = infer_bonuses_from_description(desc, cls)
        slug = slugify(name)
        sid = f"homm3_artifact_{h3_id:03d}_{slug}"
        artifacts.append(
            {
                "h3Id": h3_id,
                "sid": sid,
                "slug": slug,
                "name": name,
                "description": desc,
                "slotOe": oe_slot,
                "h3Slots": slots,
                "rarityOe": CLASS_TO_RARITY.get(cls, "common"),
                "h3Class": cls,
                "goodsValue": max(cost, 500) if cost > 0 else 1500,
                "isSpecialItem": special,
                "bonuses": bonuses,
                "mechanicsStatus": status,
                "source": "sod_artraits",
                "iconKey": sid,
                "mapAva": f"AVA{h3_id:04d}",
            }
        )
    return artifacts


def dedupe_bonuses(bonuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact duplicate bonus rows while preserving order."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in bonuses:
        key = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def load_mechanics_table() -> dict[str, dict[str, Any]]:
    if not MECHANICS_PATH.is_file():
        raise FileNotFoundError(
            f"missing curated mechanics table {MECHANICS_PATH}; "
            "run tools/homm3_import/generate_homm3_artifact_mechanics_table.py"
        )
    doc = json.loads(MECHANICS_PATH.read_text(encoding="utf-8"))
    arts = doc.get("artifacts")
    if not isinstance(arts, dict) or not arts:
        raise RuntimeError(f"{MECHANICS_PATH}: missing artifacts{{}}")
    return arts


def load_slot_overrides() -> dict[str, dict[str, Any]]:
    """Load curated OE slot remaps keyed by catalog sid."""
    if not SLOT_OVERRIDES_PATH.is_file():
        raise FileNotFoundError(
            f"missing slot overrides {SLOT_OVERRIDES_PATH}; "
            "required so combination sets stay wearable under OE slot capacity"
        )
    doc = json.loads(SLOT_OVERRIDES_PATH.read_text(encoding="utf-8"))
    rows = doc.get("overrides")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"{SLOT_OVERRIDES_PATH}: missing overrides[]")
    by_sid: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError(f"{SLOT_OVERRIDES_PATH}: non-object override row")
        sid = row.get("sid")
        slot = row.get("slotOe")
        if not isinstance(sid, str) or not sid.startswith("homm3_artifact_"):
            raise RuntimeError(f"{SLOT_OVERRIDES_PATH}: bad sid {sid!r}")
        if not isinstance(slot, str) or not slot:
            raise RuntimeError(f"{SLOT_OVERRIDES_PATH}: {sid} missing slotOe")
        if sid in by_sid:
            raise RuntimeError(f"{SLOT_OVERRIDES_PATH}: duplicate sid {sid}")
        by_sid[sid] = row
    return by_sid


def apply_slot_overrides_to_catalog(catalog: list[dict[str, Any]]) -> None:
    """Apply curated slotOe remaps. Fail closed on unknown sids."""
    overrides = load_slot_overrides()
    catalog_sids = {r.get("sid") for r in catalog}
    for sid in sorted(set(overrides) - catalog_sids):
        raise RuntimeError(f"slot override for unknown catalog sid {sid}")
    for row in catalog:
        sid = row.get("sid")
        if not isinstance(sid, str):
            continue
        ov = overrides.get(sid)
        if ov is None:
            continue
        want = ov["slotOe"]
        if row.get("slotOe") != want:
            row["slotOe"] = want
        reason = ov.get("reason")
        if isinstance(reason, str) and reason.strip():
            row["slotOverrideReason"] = reason.strip()
        else:
            row.pop("slotOverrideReason", None)


def apply_mechanics_to_catalog(catalog: list[dict[str, Any]]) -> None:
    """Overwrite bonuses/description/status from the curated mechanics table.

    Fail closed if any catalog sid lacks a mechanics row or has empty bonuses.
    """
    mechanics = load_mechanics_table()
    missing: list[str] = []
    for row in catalog:
        sid = row.get("sid")
        if not isinstance(sid, str):
            raise RuntimeError(f"catalog row missing sid: {row!r}")
        mech = mechanics.get(sid)
        if not isinstance(mech, dict):
            missing.append(sid)
            continue
        bonuses = list(mech.get("bonuses") or [])
        bonuses = dedupe_bonuses(bonuses)
        if not bonuses:
            raise RuntimeError(f"{sid}: curated mechanics has empty bonuses")
        status = mech.get("mechanicsStatus")
        if status not in {"native_exact", "native_substitute"}:
            raise RuntimeError(f"{sid}: bad mechanicsStatus {status!r}")
        desc = str(mech.get("description") or "").strip()
        if not desc:
            raise RuntimeError(f"{sid}: curated mechanics has empty description")
        row["bonuses"] = bonuses
        row["description"] = desc
        row["mechanicsStatus"] = status
        if mech.get("notes"):
            row["mechanicsNotes"] = mech["notes"]
        else:
            row.pop("mechanicsNotes", None)
    if missing:
        raise RuntimeError(
            f"mechanics table missing {len(missing)} catalog sids "
            f"(first: {missing[:10]})"
        )
    extra = sorted(set(mechanics) - {r["sid"] for r in catalog})
    if extra:
        raise RuntimeError(
            f"mechanics table has {len(extra)} unknown sids (first: {extra[:10]})"
        )
    apply_slot_overrides_to_catalog(catalog)


def infer_bonuses_from_description(
    desc: str, _cls: str
) -> tuple[list[dict[str, Any]], str]:
    """Legacy seed helper only. Curated mechanics overwrite these before emit.

    Kept so parse_artraits / HotA parse can still produce interim rows when the
    mechanics table is regenerated from a fresh LOD extract. Never ship
    text_only from this path: apply_mechanics_to_catalog must run before write.
    """
    bonuses: list[dict[str, Any]] = []
    text = desc.lower()

    def add_hero(stat: str, value: str) -> None:
        bonuses.append({"type": "heroStat", "parameters": [stat, value]})

    # Prefer non-overlapping patterns to avoid duplicate emission.
    patterns = [
        (r"increases? your attack(?: skill)? by \+(\d+)", "offence"),
        (r"increases? your defen[cs]e(?: skill)? by \+(\d+)", "defence"),
        (r"increases? your (?:spell )?power(?: skill)? by \+(\d+)", "spellPower"),
        (r"increases? your knowledge(?: skill)? by \+(\d+)", "intelligence"),
        (r"(?:attack skill|attack)\s+by\s+\+(\d+)", "offence"),
        (r"(?:defense skill|defence skill|defense|defence)\s+by\s+\+(\d+)", "defence"),
        (r"(?:power skill|spell power|power)\s+by\s+\+(\d+)", "spellPower"),
        (r"(?:knowledge skill|knowledge)\s+by\s+\+(\d+)", "intelligence"),
        (r"\+(\d+)\s+to\s+attack", "offence"),
        (r"\+(\d+)\s+to\s+defense", "defence"),
        (r"\+(\d+)\s+to\s+defence", "defence"),
        (r"\+(\d+)\s+to\s+power", "spellPower"),
        (r"\+(\d+)\s+to\s+knowledge", "intelligence"),
        (r"\+(\d+)\s+morale", "moral"),
        (r"\+(\d+)\s+luck", "luck"),
        (r"morale\s+by\s+\+(\d+)", "moral"),
        (r"luck\s+by\s+\+(\d+)", "luck"),
    ]
    matched_stats: set[str] = set()
    for pat, stat in patterns:
        if stat in matched_stats:
            continue
        m = re.search(pat, text)
        if m:
            add_hero(stat, m.group(1))
            matched_stats.add(stat)

    m = re.search(r"(?:movement|land movement).*?\+(\d+)", text)
    if m and "movementBonus" not in matched_stats:
        add_hero("movementBonus", m.group(1))
        matched_stats.add("movementBonus")
    m = re.search(r"\+(\d+)\s+(?:movement|move points)", text)
    if m and "movementBonus" not in matched_stats:
        add_hero("movementBonus", m.group(1))

    m = re.search(r"(?:\+|produces?\s+)(\d+)\s+gold", text)
    if m:
        bonuses.append({"type": "sideRes", "parameters": ["gold", m.group(1)]})

    m = re.search(r"(?:speed|initiative).*?\+(\d+)", text)
    if m and "all" in text:
        bonuses.append({"type": "unitStat", "parameters": ["speed", m.group(1)]})

    bonuses = dedupe_bonuses(bonuses)
    if not bonuses:
        return [], "text_only"
    return bonuses, "mapped"


def map_hota_bonuses(raw_bonuses: Any) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(raw_bonuses, dict) or not raw_bonuses:
        return [], "text_only"
    out: list[dict[str, Any]] = []
    unknown = 0
    for _key, bonus in raw_bonuses.items():
        if not isinstance(bonus, dict):
            unknown += 1
            continue
        btype = str(bonus.get("type") or "").upper()
        subtype = str(bonus.get("subtype") or "").lower()
        val = bonus.get("val", bonus.get("value", 0))
        try:
            val_s = str(int(val))
        except (TypeError, ValueError):
            val_s = str(val)
        if btype == "PRIMARY_SKILL":
            oe = PRIMARY_SKILL_TO_OE.get(subtype)
            if oe:
                out.append({"type": "heroStat", "parameters": [oe, val_s]})
            else:
                unknown += 1
        elif btype in {"MORALE", "MORALE_BATTLE"}:
            out.append({"type": "heroStat", "parameters": ["moral", val_s]})
        elif btype == "LUCK":
            out.append({"type": "heroStat", "parameters": ["luck", val_s]})
        elif btype in {"MOVEMENT", "LAND_MOVEMENT"}:
            out.append({"type": "heroStat", "parameters": ["movementBonus", val_s]})
        elif btype == "SIGHT_RADIUS":
            out.append({"type": "heroStat", "parameters": ["viewRadius", val_s]})
        elif btype == "GENERATE_RESOURCE" and "gold" in subtype:
            out.append({"type": "sideRes", "parameters": ["gold", val_s]})
        elif btype in {"CREATURE_GROWTH", "CREATURE_GROWTH_PERCENT"}:
            out.append(
                {
                    "type": "cityUnitsIncrementPer",
                    "parameters": ["all", str(float(val) / 100.0 if abs(float(val)) > 1 else val)],
                }
            )
        elif btype in {"STACKS_SPEED", "CREATURE_SPEED"}:
            out.append({"type": "unitStat", "parameters": ["speed", val_s]})
        else:
            unknown += 1
    if out and unknown == 0:
        return out, "mapped"
    if out:
        return out, "partial"
    return [], "text_only"


def parse_hota_artifact_file(path: Path, forced_id: int | None = None) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        data = loads_jsonc(text)
    except json.JSONDecodeError as exc:
        print(f"WARN: skip bad json {path}: {exc}", file=sys.stderr)
        return []
    if not isinstance(data, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        graphics = cfg.get("graphics") or {}
        text_block = cfg.get("text") or {}
        name = str(text_block.get("name") or key)
        desc = clean_description(str(text_block.get("description") or name))
        slot = str(cfg.get("slot") or "MISC").upper()
        oe_slot = HOTA_SLOT_TO_OE.get(slot, "item_slot")
        cls = str(cfg.get("class") or "MAJOR").upper()
        try:
            value = int(cfg.get("value") or 5000)
        except (TypeError, ValueError):
            value = 5000
        map_ref = str(graphics.get("map") or "")
        ava_m = re.search(r"AVA(\d+)", map_ref, re.I)
        if forced_id is not None:
            h3_id = forced_id
        elif ava_m:
            h3_id = int(ava_m.group(1))
        else:
            # Allocate high id namespace for nameless map refs.
            h3_id = 9000 + abs(hash(key)) % 900
        bonuses, status = map_hota_bonuses(cfg.get("bonuses"))
        if status == "text_only":
            # Fall back to description parse.
            bonuses, status = infer_bonuses_from_description(desc, cls)
        special = name.lower() in SPECIAL_ITEM_NAMES or slot.startswith("MACH")
        slug = slugify(name)
        sid = f"homm3_artifact_{h3_id:03d}_{slug}"
        icon_src = str(graphics.get("image") or "")
        rows.append(
            {
                "h3Id": h3_id,
                "sid": sid,
                "slug": slug,
                "name": name,
                "description": desc,
                "slotOe": oe_slot,
                "h3Slots": [slot],
                "rarityOe": CLASS_TO_RARITY.get(cls, "epic"),
                "h3Class": cls,
                "goodsValue": max(value, 500),
                "isSpecialItem": special,
                "bonuses": bonuses,
                "mechanicsStatus": status,
                "source": f"hota:{path.stem}",
                "iconKey": sid,
                "mapAva": f"AVA{h3_id:04d}" if h3_id < 9000 else None,
                "hotaIconRel": icon_src,
                "hotaKey": key,
            }
        )
    return rows


def collect_hota_artifacts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Core HotA artifact pack
    cfg_dir = VCMI_HOTA / "artifacts" / "Content" / "config" / "hotaArtifacts"
    if cfg_dir.is_dir():
        for path in sorted(cfg_dir.glob("*.json")):
            rows.extend(parse_hota_artifact_file(path))
    # Supplementary pack
    supp = VCMI_HOTA / "supplementary" / "content.zip"
    if supp.is_file():
        with zipfile.ZipFile(supp) as zf:
            for name in zf.namelist():
                if "artifacts/" in name and name.endswith(".json"):
                    raw = zf.read(name).decode("utf-8", "replace")
                    tmp = OUT_WORK / "tmp_supp.json"
                    tmp.parent.mkdir(parents=True, exist_ok=True)
                    tmp.write_text(raw, encoding="utf-8")
                    rows.extend(parse_hota_artifact_file(tmp))
    # Cannon
    cannon = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "homm3_runtime_assets"
        / "cannon"
        / "homm3_cove"
        / "config"
        / "hotaCannon"
        / "cannonArtifact.json"
    )
    if cannon.is_file():
        rows.extend(parse_hota_artifact_file(cannon, forced_id=145))
    # Horn of the Abyss
    horn_zip = VCMI_HOTA / "neutralCreatures" / "content.zip"
    if horn_zip.is_file():
        with zipfile.ZipFile(horn_zip) as zf:
            for name in zf.namelist():
                if name.endswith("hornOfTheAbyss.json"):
                    tmp = OUT_WORK / "hornOfTheAbyss.json"
                    tmp.write_bytes(zf.read(name))
                    rows.extend(parse_hota_artifact_file(tmp, forced_id=163))
    # Deduplicate by h3Id (later sources win only if not already present)
    by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        hid = int(row["h3Id"])
        if hid not in by_id:
            by_id[hid] = row
    return [by_id[k] for k in sorted(by_id)]


def ensure_artim_icons(work: Path) -> Path:
    """Extract ArtIm###.png into work/artim/."""
    out = work / "artim"
    out.mkdir(parents=True, exist_ok=True)
    zpath = VCMI_HOTA / "heroes3DataPatch" / "content.zip"
    if not zpath.is_file():
        raise FileNotFoundError(zpath)
    with zipfile.ZipFile(zpath) as zf:
        for name in zf.namelist():
            if not name.lower().startswith("sprites/artifact/artim"):
                continue
            if not name.lower().endswith(".png"):
                continue
            target = out / Path(name).name
            if not target.exists():
                target.write_bytes(zf.read(name))
    return out


def extract_map_frame(ava_name: str, work: Path, dest_png: Path) -> bool:
    """Extract AVA####.def from HD LOD or HotA pack; copy preferred frame to dest."""
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    def_name = ava_name if ava_name.lower().endswith(".def") else f"{ava_name}.def"
    def_path = work / "defs" / def_name.lower()
    def_path.parent.mkdir(parents=True, exist_ok=True)

    got = False
    # Prefer HotA map DEFs when present.
    hota_map = (
        VCMI_HOTA
        / "artifacts"
        / "Content"
        / "sprites"
        / "hota"
        / "artifactsMap"
        / def_name.upper().replace(".DEF", ".def")
    )
    # Case variants
    for candidate in [
        VCMI_HOTA / "artifacts" / "Content" / "sprites" / "hota" / "artifactsMap" / def_name,
        VCMI_HOTA / "artifacts" / "Content" / "sprites" / "hota" / "artifactsMap" / def_name.upper(),
        VCMI_HOTA / "artifacts" / "Content" / "sprites" / "hota" / "artifactsMap" / def_name.lower(),
    ]:
        if candidate.is_file():
            shutil.copy2(candidate, def_path)
            got = True
            break
    if not got:
        # Supplementary zip DEFs
        supp = VCMI_HOTA / "supplementary" / "content.zip"
        if supp.is_file():
            with zipfile.ZipFile(supp) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(def_name.lower()):
                        def_path.write_bytes(zf.read(name))
                        got = True
                        break
    if not got and SPRITE_LOD.is_file():
        try:
            def_path.write_bytes(extract_lod_member(SPRITE_LOD, def_name))
            got = True
        except FileNotFoundError:
            got = False
    if not got:
        return False

    # defextract into work/extracted/<ava>/
    extract_root = work / "extracted"
    extract_root.mkdir(parents=True, exist_ok=True)
    # Import extract_def
    sys.path.insert(0, str(ROOT / "tools"))
    from defextract_py3 import extract_def  # type: ignore

    if not extract_def(str(def_path), str(extract_root)):
        return False
    bn = Path(def_name).stem.lower()
    frame_dir = extract_root / f"{bn}.dir"
    if not frame_dir.is_dir():
        return False
    preferred = [
        frame_dir / "00_00.png",
        frame_dir / "00_01.png",
        frame_dir / "00_04.png",
    ]
    chosen = next((p for p in preferred if p.is_file()), None)
    if chosen is None:
        pngs = sorted(frame_dir.glob("*.png"))
        if not pngs:
            return False
        chosen = pngs[0]
    shutil.copy2(chosen, dest_png)
    # AVA frames keep DEF soft-shadow pixels that inflate aspect and off-center billboards.
    _sys_dir = str(Path(__file__).resolve().parent)
    if _sys_dir not in sys.path:
        sys.path.insert(0, _sys_dir)
    from artifact_map_shadow_crop import postpass_artifact_map_png

    postpass_artifact_map_png(dest_png)
    return True


def copy_hota_icon(row: dict[str, Any], dest: Path) -> bool:
    """Copy HotA-specific icon PNG when ArtIm is missing."""
    key = row.get("hotaKey")
    if not key:
        return False
    # Known HotA icon folders
    candidates = [
        VCMI_HOTA / "artifacts" / "Content" / "data" / "hota" / "artifactsIcons" / f"{key}.png",
        VCMI_HOTA
        / "artifacts"
        / "Content"
        / "data"
        / "hota"
        / "artifactsIcons"
        / f"{row.get('slug')}.png",
    ]
    # camelCase file names from configs
    icon_dir = VCMI_HOTA / "artifacts" / "Content" / "data" / "hota" / "artifactsIcons"
    if icon_dir.is_dir():
        for p in icon_dir.glob("*.png"):
            if p.stem.lower() == str(key).lower() or slugify(p.stem) == row["slug"]:
                candidates.append(p)
    # Horn
    horn_zip = VCMI_HOTA / "neutralCreatures" / "content.zip"
    if horn_zip.is_file() and "horn" in row["slug"]:
        with zipfile.ZipFile(horn_zip) as zf:
            for name in zf.namelist():
                if name.endswith("artifactsIcons/hornOfTheAbyss.png"):
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(name))
                    return True
    # Cannon
    cannon_icon = (
        ROOT
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "homm3_runtime_assets"
        / "cannon"
        / "homm3_cove"
        / "sprites"
        / "hota"
        / "iconsSmall"
        / "cannonArtifact.png"
    )
    candidates.append(cannon_icon)
    # Supplementary zip icons
    supp = VCMI_HOTA / "supplementary" / "content.zip"
    if supp.is_file():
        with zipfile.ZipFile(supp) as zf:
            for name in zf.namelist():
                base = Path(name).stem.lower()
                if base in {str(key).lower(), row["slug"]} and name.endswith(".png"):
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(name))
                    return True
    for c in candidates:
        if c and Path(c).is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(c, dest)
            return True
    return False


def apply_mechanics_only() -> int:
    """Re-apply curated mechanics onto the existing catalog without LOD extract."""
    if not OUT_CATALOG.is_file():
        print(f"missing catalog {OUT_CATALOG}", file=sys.stderr)
        return 1
    doc = json.loads(OUT_CATALOG.read_text(encoding="utf-8"))
    catalog = doc.get("artifacts")
    if not isinstance(catalog, list) or not catalog:
        print("catalog has no artifacts[]", file=sys.stderr)
        return 1
    apply_mechanics_to_catalog(catalog)
    doc["artifacts"] = catalog
    doc["policy"] = "homm3_artifact_port_sod_hota_v1"
    doc["proofBoundary"] = "generated_artifact_validated_runtime_unvalidated"
    counts = doc.setdefault("counts", {})
    counts["total"] = len(catalog)
    counts["native_exact"] = sum(
        1 for r in catalog if r.get("mechanicsStatus") == "native_exact"
    )
    counts["native_substitute"] = sum(
        1 for r in catalog if r.get("mechanicsStatus") == "native_substitute"
    )
    counts["text_only"] = sum(
        1 for r in catalog if r.get("mechanicsStatus") == "text_only"
    )
    counts["mapped"] = sum(1 for r in catalog if r.get("mechanicsStatus") == "mapped")
    counts["partial"] = sum(1 for r in catalog if r.get("mechanicsStatus") == "partial")
    OUT_CATALOG.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: counts[k] for k in (
        "total", "native_exact", "native_substitute", "text_only", "mapped", "partial"
    ) if k in counts}, indent=2))
    print(f"wrote {OUT_CATALOG} (mechanics-only)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--apply-mechanics-only" in args:
        return apply_mechanics_only()

    if not BITMAP_LOD.is_file():
        print(f"missing {BITMAP_LOD}", file=sys.stderr)
        print(
            "hint: use --apply-mechanics-only to patch an existing catalog",
            file=sys.stderr,
        )
        return 1
    OUT_WORK.mkdir(parents=True, exist_ok=True)
    OUT_ICONS.mkdir(parents=True, exist_ok=True)
    OUT_MAP.mkdir(parents=True, exist_ok=True)
    OUT_CATALOG.parent.mkdir(parents=True, exist_ok=True)

    artraits = extract_lod_member(BITMAP_LOD, "artraits.txt").decode("latin-1")
    classic = parse_artraits(artraits)
    hota = collect_hota_artifacts()

    by_id: dict[int, dict[str, Any]] = {int(r["h3Id"]): r for r in classic}
    for row in hota:
        hid = int(row["h3Id"])
        if hid in by_id and by_id[hid]["source"] == "sod_artraits" and hid < 141:
            # Do not overwrite classic SoD ids with HotA unless classic missing.
            continue
        by_id[hid] = row
    # SoD artraits.txt ends at 126; AB campaign pickups (Vial / Armageddon's Blade)
    # sit in the 127–141 gap before HotA ids. Seed text_only rows so map emit can
    # resolve templateSubtype without mission special-cases.
    for row in AB_CAMPAIGN_ARTIFACT_SEEDS:
        hid = int(row["h3Id"])
        if hid not in by_id:
            by_id[hid] = dict(row)
    catalog = [by_id[k] for k in sorted(by_id)]
    apply_mechanics_to_catalog(catalog)

    artim = ensure_artim_icons(OUT_WORK)
    manifest: dict[str, Any] = {"artifacts": {}, "proofBoundary": "generated_artifact"}
    missing_icons: list[str] = []
    missing_maps: list[str] = []

    for row in catalog:
        sid = row["sid"]
        h3_id = int(row["h3Id"])
        icon_dest = OUT_ICONS / f"{sid}.png"
        map_dest = OUT_MAP / sid / "00_00.png"

        # Icon: prefer ArtIm###
        artim_png = artim / f"ArtIm{h3_id:03d}.png"
        icon_ok = False
        if artim_png.is_file():
            shutil.copy2(artim_png, icon_dest)
            icon_ok = True
        elif copy_hota_icon(row, icon_dest):
            icon_ok = True
        if not icon_ok:
            missing_icons.append(sid)

        # Map frame
        ava = row.get("mapAva")
        map_ok = False
        if ava:
            map_ok = extract_map_frame(str(ava), OUT_WORK, map_dest)
        if not map_ok:
            # Fallback: reuse a generic classic artifact map frame (AVA0007 Centaur axe-ish)
            fallback = OUT_WORK / "fallback_map.png"
            if not fallback.is_file():
                extract_map_frame("AVA0007", OUT_WORK, fallback)
            if fallback.is_file():
                map_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fallback, map_dest)
                _sys_dir = str(Path(__file__).resolve().parent)
                if _sys_dir not in sys.path:
                    sys.path.insert(0, _sys_dir)
                from artifact_map_shadow_crop import postpass_artifact_map_png

                postpass_artifact_map_png(map_dest)
                map_ok = True
                row["mapFallback"] = "AVA0007"
        if not map_ok:
            missing_maps.append(sid)

        row["iconPath"] = f"homm3_runtime_assets/artifacts/icons/{sid}.png"
        row["mapPath"] = f"homm3_runtime_assets/artifacts/map/{sid}/00_00.png"
        manifest["artifacts"][sid] = {
            "h3Id": h3_id,
            "icon": row["iconPath"] if icon_ok else None,
            "map": row["mapPath"] if map_ok else None,
            "mechanicsStatus": row["mechanicsStatus"],
        }

    payload = {
        "version": 1,
        "policy": "homm3_artifact_port_sod_hota_v1",
        "proofBoundary": "generated_artifact_validated_runtime_unvalidated",
        "counts": {
            "total": len(catalog),
            "classic": sum(1 for r in catalog if r["source"] == "sod_artraits"),
            "hota": sum(1 for r in catalog if str(r["source"]).startswith("hota")),
            "native_exact": sum(
                1 for r in catalog if r["mechanicsStatus"] == "native_exact"
            ),
            "native_substitute": sum(
                1 for r in catalog if r["mechanicsStatus"] == "native_substitute"
            ),
            "mapped": sum(1 for r in catalog if r["mechanicsStatus"] == "mapped"),
            "partial": sum(1 for r in catalog if r["mechanicsStatus"] == "partial"),
            "text_only": sum(1 for r in catalog if r["mechanicsStatus"] == "text_only"),
            "missingIcons": len(missing_icons),
            "missingMaps": len(missing_maps),
        },
        "missingIcons": missing_icons,
        "missingMaps": missing_maps,
        "artifacts": catalog,
    }
    if payload["counts"]["text_only"] or payload["counts"]["mapped"] or payload["counts"]["partial"]:
        print(
            "ERROR: curated mechanics must leave zero text_only/mapped/partial rows; "
            f"got {payload['counts']}",
            file=sys.stderr,
        )
        return 1
    OUT_CATALOG.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload["counts"], indent=2))
    print(f"wrote {OUT_CATALOG}")
    print(f"wrote {OUT_MANIFEST}")
    if missing_icons:
        print(f"WARN missing icons: {len(missing_icons)}", file=sys.stderr)
    if missing_maps:
        print(f"WARN missing maps: {len(missing_maps)}", file=sys.stderr)
    # Fail closed only if classic core icons missing heavily.
    classic_missing = [s for s in missing_icons if s.startswith("homm3_artifact_0")]
    if len(classic_missing) > 20:
        print("too many classic icon gaps", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
