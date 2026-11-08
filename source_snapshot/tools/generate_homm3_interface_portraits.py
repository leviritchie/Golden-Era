#!/usr/bin/env python3
"""Generate HoMM3 static UI portraits from real interface portrait sources.

This intentionally updates only OfflineUnlockMod/homm3_portraits. Recruitment and
detail idle animation is bundle-backed and outside this static portrait tool.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

from PIL import Image

from defextract_py3 import extract_def
from lod_extract_entry_py3 import extract_entry


ROOT = Path(__file__).resolve().parents[1]
MAIN_ROOT = ROOT.parent.parent if ROOT.parent.name.lower() == "worktrees" else ROOT
OFFLINE = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
PORTRAITS = OFFLINE / "homm3_portraits"
CUSTOM_FACTIONS = ROOT / "custom_factions"
TEMP_ROOT = ROOT / "tools" / "build_temp_homm3_interface_portraits"
# Painted 1254 px masters (artifacts/static_asset_painted_upscale/README.md). Where a unit has
# one, the runtime portrait is that master at the runtime size contract, never the raw frame.
PAINTED_MASTERS = MAIN_ROOT / "artifacts" / "static_asset_painted_upscale" / "final"
RUNTIME_SIZE_CONTRACT = MAIN_ROOT / "artifacts" / "static_asset_painted_upscale" / "RUNTIME_SIZE_CONTRACT.json"

# TwCrPort.def has two non-creature frames before the HoMM3 creature table:
# frame 0 is a red dummy texture and frame 1 is a mostly blank outline. Pikeman
# is creature id 0, but sheet frame 2.
TWCRPORT_CREATURE_ID_OFFSET = 2

HOMM3_NAME_TO_CREATURE_ID = {
    # Castle
    "Pikeman": 0,
    "Halberdier": 1,
    "Archer": 2,
    "Marksman": 3,
    "Griffin": 4,
    "Royal Griffin": 5,
    "Swordsman": 6,
    "Crusader": 7,
    "Monk": 8,
    "Zealot": 9,
    "Cavalier": 10,
    "Champion": 11,
    "Angel": 12,
    "Archangel": 13,
    # Rampart
    "Centaur": 14,
    "Centaur Captain": 15,
    "Dwarf": 16,
    "Battle Dwarf": 17,
    "Wood Elf": 18,
    "Grand Elf": 19,
    "Pegasus": 20,
    "Silver Pegasus": 21,
    "Dendroid Guard": 22,
    "Dendroid Soldier": 23,
    "Unicorn": 24,
    "War Unicorn": 25,
    "Green Dragon": 26,
    "Gold Dragon": 27,
    # Tower
    "Gremlin": 28,
    "Master Gremlin": 29,
    "Stone Gargoyle": 30,
    "Obsidian Gargoyle": 31,
    "Stone Golem": 32,
    "Iron Golem": 33,
    "Mage": 34,
    "Arch Mage": 35,
    "Genie": 36,
    "Master Genie": 37,
    "Naga": 38,
    "Naga Queen": 39,
    "Giant": 40,
    "Titan": 41,
    # Inferno
    "Imp": 42,
    "Familiar": 43,
    "Gog": 44,
    "Magog": 45,
    "Hell Hound": 46,
    "Cerberus": 47,
    "Demon": 48,
    "Horned Demon": 49,
    "Pit Fiend": 50,
    "Pit Lord": 51,
    "Efreeti": 52,
    "Efreet Sultan": 53,
    "Devil": 54,
    "Arch Devil": 55,
    # Necropolis
    "Skeleton": 56,
    "Skeleton Warrior": 57,
    "Walking Dead": 58,
    "Zombie": 59,
    "Wight": 60,
    "Wraith": 61,
    "Vampire": 62,
    "Vampire Lord": 63,
    "Lich": 64,
    "Power Lich": 65,
    "Black Knight": 66,
    "Dread Knight": 67,
    "Bone Dragon": 68,
    "Ghost Dragon": 69,
    # Dungeon
    "Troglodyte": 70,
    "Infernal Troglodyte": 71,
    "Harpy": 72,
    "Harpy Hag": 73,
    "Beholder": 74,
    "Evil Eye": 75,
    "Medusa": 76,
    "Medusa Queen": 77,
    "Minotaur": 78,
    "Minotaur King": 79,
    "Manticore": 80,
    "Scorpicore": 81,
    "Red Dragon": 82,
    "Black Dragon": 83,
    # Stronghold
    "Goblin": 84,
    "Hobgoblin": 85,
    "Wolf Rider": 86,
    "Wolf Raider": 87,
    "Orc": 88,
    "Orc Chieftain": 89,
    "Ogre": 90,
    "Ogre Mage": 91,
    "Roc": 92,
    "Thunderbird": 93,
    "Cyclops": 94,
    "Cyclops King": 95,
    "Behemoth": 96,
    "Ancient Behemoth": 97,
    # Fortress
    "Gnoll": 98,
    "Gnoll Marauder": 99,
    "Lizardman": 100,
    "Lizard Warrior": 101,
    "Gorgon": 102,
    "Mighty Gorgon": 103,
    "Serpent Fly": 104,
    "Dragon Fly": 105,
    "Basilisk": 106,
    "Greater Basilisk": 107,
    "Wyvern": 108,
    "Wyvern Monarch": 109,
    "Hydra": 110,
    "Chaos Hydra": 111,
    # Conflux. Ids 122/124/126/128 are the unused creature slots (TwCrPort shows a
    # crossed-out placeholder there); the upgraded elementals sit between them.
    "Air Elemental": 112,
    "Earth Elemental": 113,
    "Fire Elemental": 114,
    "Water Elemental": 115,
    "Gold Golem": 116,
    "Diamond Golem": 117,
    "Pixie": 118,
    "Sprite": 119,
    "Psychic Elemental": 120,
    "Magic Elemental": 121,
    "Ice Elemental": 123,
    "Magma Elemental": 125,
    "Storm Elemental": 127,
    "Energy Elemental": 129,
    "Firebird": 130,
    "Phoenix": 131,
    # SoD neutrals (tools/homm3_import/faction_concepts/homm3_neutral.json displayName).
    "Azure Dragon": 132,
    "Crystal Dragon": 133,
    "Faerie Dragon": 134,
    "Rust Dragon": 135,
    "Enchanter": 136,
    "Sharpshooter": 137,
    "Halfling": 138,
    "Peasant": 139,
    "Boar": 140,
    "Mummy": 141,
    "Nomad": 142,
    "Rogue": 143,
    "Troll": 144,
}

# HotA neutrals are not in the SoD TwCrPort sheet; their large icon is named by the
# creature config's graphics.iconLarge inside the HotA neutralCreatures mod.
HOTA_NEUTRAL_CONFIG_BY_SID = {
    "h3_fangarm": "fangarm",
    "h3_satyr": "satyr",
    "h3_leprechaun": "leprechaun",
    "h3_steel_golem": "steelGolem",
}
NEUTRAL_CATALOG = ROOT / "tools" / "homm3_import" / "faction_concepts" / "homm3_neutral.json"

MISSING_NAME_VARIANTS_BY_BASE_SID = {
    "h3_goblin": ("Goblin", "Hobgoblin"),
    "h3_wolf_rider": ("Wolf Rider", "Wolf Raider"),
    "h3_orc": ("Orc", "Orc Chieftain"),
    "h3_ogre": ("Ogre", "Ogre Mage"),
    "h3_roc": ("Roc", "Thunderbird"),
    "h3_cyclops": ("Cyclops", "Cyclops King"),
    "h3_behemoth": ("Behemoth", "Ancient Behemoth"),
    "h3_gremlin": ("Gremlin", "Master Gremlin"),
    "h3_gargoyle": ("Stone Gargoyle", "Obsidian Gargoyle"),
    "h3_golem": ("Stone Golem", "Iron Golem"),
    "h3_mage": ("Mage", "Arch Mage"),
    "h3_genie": ("Genie", "Master Genie"),
    "h3_naga": ("Naga", "Naga Queen"),
    "h3_giant": ("Giant", "Titan"),
}


def find_required_file(relative: str) -> Path:
    for root in (ROOT, MAIN_ROOT):
        candidate = root / relative
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(relative)


def ensure_twcrport_frames() -> Path:
    out_dir = TEMP_ROOT / "twcrport"
    frame_dir = out_dir / "twcrport.dir"
    if (frame_dir / "00_00.png").is_file() and (frame_dir / "00_146.png").is_file():
        return frame_dir

    out_dir.mkdir(parents=True, exist_ok=True)
    lod = find_required_file("HoMM 3 Complete/Data/H3sprite.lod")
    def_path = out_dir / "TwCrPort.def"
    if not extract_entry(lod, "TwCrPort.def", def_path):
        raise RuntimeError(f"failed to extract TwCrPort.def from {lod}")
    if not extract_def(str(def_path), str(out_dir)):
        raise RuntimeError(f"failed to decode {def_path}")
    return frame_dir


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_image_if_changed(path: Path, image: Image.Image) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    image.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    if path.exists() and path.read_bytes() == data:
        return False
    path.write_bytes(data)
    return True


def copy_image_to_portrait(image: Image.Image, sid: str) -> bool:
    return write_image_if_changed(PORTRAITS / f"{sid}.png", image.convert("RGBA"))


def sid_for_variant(line: dict[str, object], suffix: str) -> str:
    variant_sids = line.get("variantSids")
    if isinstance(variant_sids, dict):
        value = variant_sids.get(suffix)
        if isinstance(value, str) and value:
            return value
    return str(line["baseSid"]) + suffix


def names_for_line(line: dict[str, object]) -> list[str]:
    names = line.get("names")
    if isinstance(names, list) and len(names) >= 2:
        return [str(value) for value in names]
    return list(MISSING_NAME_VARIANTS_BY_BASE_SID.get(str(line["baseSid"]), ()))


def load_twcrport_portrait(frame_dir: Path, name: str) -> tuple[Image.Image, str]:
    try:
        creature_id = HOMM3_NAME_TO_CREATURE_ID[name]
    except KeyError as ex:
        raise KeyError(f"no TwCrPort frame mapping for {name!r}") from ex
    frame = creature_id + TWCRPORT_CREATURE_ID_OFFSET
    path = frame_dir / f"00_{frame:02d}.png"
    if not path.is_file():
        raise FileNotFoundError(path)
    return Image.open(path).convert("RGBA"), f"H3sprite.lod:TwCrPort.def:creatureId={creature_id}:frame={frame}"


def toa_content_zip() -> Path:
    return find_required_file("vcmi/Mods/tears-of-ashan/content.zip")


def load_toa_icon(faction_short: str, tier: int) -> tuple[Image.Image, str]:
    member = f"sprites/creatures/{faction_short}/iconsbig/lvl{tier}Alt.png"
    zip_path = toa_content_zip()
    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            data = zf.read(member)
        except KeyError as ex:
            raise FileNotFoundError(f"{zip_path}: {member}") from ex
    return Image.open(io.BytesIO(data)).convert("RGBA"), f"{zip_path}:{member}"


def load_cove_icon(source_key: str) -> tuple[Image.Image, str]:
    relative = f"vcmi/Mods/hota/mods/cove/Content/sprites/hota/cove/creatures/iconsLarge/{source_key}.png"
    path = find_required_file(relative)
    return Image.open(path).convert("RGBA"), str(path)


def load_hota_neutral_icon(config_key: str) -> tuple[Image.Image, str]:
    zip_path = find_required_file("vcmi/Mods/hota/mods/neutralCreatures/content.zip")
    config_member = f"config/hotaNeutralCreatures/{config_key}.json"
    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            raw = zf.read(config_member).decode("utf-8", "replace")
        except KeyError as ex:
            raise FileNotFoundError(f"{zip_path}: {config_member}") from ex
        match = re.search(r'"iconLarge"\s*:\s*"([^"]+)"', raw)
        if not match:
            raise KeyError(f"{config_member}: missing graphics.iconLarge")
        relative = match.group(1).replace("\\", "/")
        if not relative.lower().endswith(".png"):
            relative += ".png"
        wanted = ("sprites/" + relative).lower()
        # The mod's member names are not case-consistent (TwCrP170.png vs twcrp170.png).
        members = [m for m in zf.namelist() if m.lower() == wanted]
        if len(members) != 1:
            raise FileNotFoundError(f"{zip_path}: {wanted} ({len(members)} case-insensitive match(es))")
        data = zf.read(members[0])
    return Image.open(io.BytesIO(data)).convert("RGBA"), f"{zip_path}:{members[0]}"


def generate_neutral_portraits(frame_dir: Path, source_by_sid: dict[str, str]) -> int:
    """Static portraits for every homm3_neutral catalog unit; fails on any unmapped unit."""
    catalog = load_json(NEUTRAL_CATALOG)
    units = catalog.get("units") if isinstance(catalog, dict) else None
    if not isinstance(units, list) or not units:
        raise RuntimeError(f"{NEUTRAL_CATALOG}: units must be a non-empty array")
    changed = 0
    for unit in units:
        sid = str(unit["sid"])
        config_key = HOTA_NEUTRAL_CONFIG_BY_SID.get(sid)
        if config_key is not None:
            image, source = load_hota_neutral_icon(config_key)
        else:
            image, source = load_twcrport_portrait(frame_dir, str(unit["displayName"]))
        changed += int(copy_image_to_portrait(image, sid))
        source_by_sid[sid] = source
    return changed


def hota_faction_content_zip(faction_short: str) -> Path:
    return find_required_file(f"vcmi/Mods/hota/mods/{faction_short}/content.zip")


def load_bulwark_icon(source_key: str) -> tuple[Image.Image, str]:
    member = f"sprites/hota/bulwark/creatures/iconsLarge/{source_key}.png"
    zip_path = hota_faction_content_zip("bulwark")
    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            data = zf.read(member)
        except KeyError as ex:
            raise FileNotFoundError(f"{zip_path}: {member}") from ex
    return Image.open(io.BytesIO(data)).convert("RGBA"), f"{zip_path}:{member}"


def factory_icon_large_member(source_key: str) -> str:
    """Resolve HotA Factory iconsLarge member from the creature config iconLarge field."""
    zip_path = hota_faction_content_zip("factory")
    config_member = f"config/hota/factory/creatures/{source_key}.json"
    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            raw = zf.read(config_member).decode("utf-8", "replace")
        except KeyError as ex:
            raise FileNotFoundError(f"{zip_path}: {config_member}") from ex
    match = re.search(r'"iconLarge"\s*:\s*"([^"]+)"', raw)
    if not match:
        raise KeyError(f"{config_member}: missing graphics.iconLarge")
    relative = match.group(1).replace("\\", "/")
    if not relative.startswith("hota/factory/creatures/iconsLarge/"):
        raise KeyError(f"{config_member}: unexpected iconLarge path {relative!r}")
    return "sprites/" + relative


def load_factory_icon(source_key: str) -> tuple[Image.Image, str]:
    member = factory_icon_large_member(source_key)
    zip_path = hota_faction_content_zip("factory")
    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            data = zf.read(member)
        except KeyError as ex:
            raise FileNotFoundError(f"{zip_path}: {member}") from ex
    return Image.open(io.BytesIO(data)).convert("RGBA"), f"{zip_path}:{member}"


def load_hota_source_config_icon(
    faction_short: str,
    line: dict[str, object],
    suffix: str,
    variant_index: int,
) -> tuple[Image.Image, str]:
    source_config = line.get("sourceConfig")
    if not isinstance(source_config, list) or not source_config:
        raise KeyError(f"{line.get('baseSid')}: HotA {faction_short} lines require sourceConfig")
    # Material-class alts have no dedicated HotA large icon; reuse the upgraded source art.
    if suffix == "_upg_alt":
        key_index = min(1, len(source_config) - 1)
    else:
        key_index = min(variant_index, len(source_config) - 1)
    source_key = str(source_config[key_index])
    if faction_short == "factory":
        return load_factory_icon(source_key)
    if faction_short == "bulwark":
        return load_bulwark_icon(source_key)
    raise KeyError(f"unsupported HotA portrait faction {faction_short!r}")


def load_portrait_for_variant(
    frame_dir: Path,
    faction_short: str,
    line: dict[str, object],
    suffix: str,
    variant_index: int,
) -> tuple[Image.Image, str]:
    tier = int(line["tier"])
    if faction_short == "cove":
        source_config = line.get("sourceConfig")
        if isinstance(source_config, list) and variant_index < len(source_config):
            return load_cove_icon(str(source_config[variant_index]))
        return load_toa_icon(faction_short, tier)

    if faction_short in ("factory", "bulwark"):
        return load_hota_source_config_icon(faction_short, line, suffix, variant_index)

    if faction_short == "conflux" and line.get("baseSid") == "h3_air_elemental" and suffix == "_upg_alt":
        # Hurricane is a sprite edit of Storm, not a separate Energy-like design.
        return load_twcrport_portrait(frame_dir, "Storm Elemental")

    if suffix == "_upg_alt":
        return load_toa_icon(faction_short, tier)

    names = names_for_line(line)
    if variant_index >= len(names):
        raise KeyError(f"{line['baseSid']}: missing interface name for variant {suffix}")
    return load_twcrport_portrait(frame_dir, names[variant_index])


def iter_manifest_unit_lines(manifest: dict[str, object]) -> list[dict[str, object]]:
    lines: list[dict[str, object]] = []
    for key in ("unitLines", "additionalRecruitmentLines"):
        rows = manifest.get(key) or []
        if not isinstance(rows, list):
            raise RuntimeError(f"manifest {key} must be a list")
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError(f"manifest {key} entries must be objects")
            lines.append(row)
    return lines


def generate_factory_sandworm_larva_portrait(source_by_sid: dict[str, str]) -> int:
    """Factory sandworm larva is import-owned but not a recruit-line variant."""
    image, source = load_factory_icon("sandwormLarva")
    sid = "h3_sandworm_larva"
    source_by_sid[sid] = source
    return int(copy_image_to_portrait(image, sid))


def apply_material_class_hs_alt_portraits(
    source_by_sid: dict[str, str],
    faction: str,
) -> tuple[int, dict]:
    """Subject-only material_class_hs recolor for faction *_upg_alt portraits.

    HotA iconsLarge share one backdrop per faction; a full remap would tint it.
    Uses tools/homm3_import/bake_factory_alt_portraits_material_class_hs.py.
    """
    import sys

    bake_dir = ROOT / "tools" / "homm3_import"
    if str(bake_dir) not in sys.path:
        sys.path.insert(0, str(bake_dir))
    from bake_factory_alt_portraits_material_class_hs import bake_faction_alt_portraits  # noqa: WPS433

    report = bake_faction_alt_portraits(faction, portraits_dir=PORTRAITS, write_spotcheck=True)
    faction_label = faction.title()
    for row in report.get("altPortraits") or []:
        sid = str(row["gameAltSid"])
        upgrade = str(row["upgradeSid"])
        option = str(row["optionId"])
        prev = source_by_sid.get(sid) or f"homm3_portraits/{upgrade}.png"
        source_by_sid[sid] = (
            f"{prev} | material_class_hs subject-only recolor "
            f"(optionId={option}; shared {faction_label} background mask)"
        )
    return int(report.get("changedCount") or 0), report


def apply_factory_material_class_hs_alt_portraits(source_by_sid: dict[str, str]) -> tuple[int, dict]:
    """Backward-compatible Factory wrapper."""
    return apply_material_class_hs_alt_portraits(source_by_sid, "factory")


def _alt_portrait_recolor_manifest_block(report: dict) -> dict:
    mask = report.get("mask") or {}
    return {
        "strategy": "material_class_hs",
        "maskMethod": mask.get("method"),
        "sharedBackgroundCoverage": mask.get("sharedBackgroundCoverage"),
        "lineCount": mask.get("lineCount"),
        "reportPath": report.get("reportPath"),
        "generatedBy": "tools/homm3_import/bake_factory_alt_portraits_material_class_hs.py",
    }


def write_manifest(
    source_by_sid: dict[str, str],
    *,
    factory_alt_report: dict | None = None,
    bulwark_alt_report: dict | None = None,
    painted_masters: dict[str, str] | None = None,
) -> bool:
    PORTRAITS.mkdir(parents=True, exist_ok=True)
    manifest_path = PORTRAITS / "manifest.json"
    try:
        manifest = load_json(manifest_path)
        if not isinstance(manifest, dict):
            manifest = {}
    except (OSError, json.JSONDecodeError):
        manifest = {}

    for stale_key in (
        "towerSource",
        "towerSidToManifest",
        "towerAnimationFrameCounts",
        "fortressSource",
        "fortressToaSource",
        "fortressSidToManifest",
        "fortressAnimationFrameCounts",
        "remainingFactionSidToManifest",
        "remainingFactionAnimationFrameCounts",
        "animationSource",
        "animationFrameCounts",
    ):
        manifest.pop(stale_key, None)

    manifest["staticPortraitPolicy"] = "interface-art-first"
    manifest["interfacePortraitGeneratedBy"] = "tools/generate_homm3_interface_portraits.py"
    manifest["interfacePortraitSources"] = source_by_sid
    # interfacePortraitSources names the frame each unit is identified by (and was painted
    # from); paintedPortraitMasters names the master that actually ships for that unit.
    manifest["paintedPortraitMasters"] = dict(sorted((painted_masters or {}).items()))
    if isinstance(factory_alt_report, dict):
        manifest["factoryAltPortraitRecolor"] = _alt_portrait_recolor_manifest_block(factory_alt_report)
    if isinstance(bulwark_alt_report, dict):
        manifest["bulwarkAltPortraitRecolor"] = _alt_portrait_recolor_manifest_block(bulwark_alt_report)
    text = json.dumps(manifest, indent=4) + "\n"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") == text:
        return False
    manifest_path.write_text(text, encoding="utf-8")
    return True


def apply_painted_masters(source_by_sid: dict[str, str]) -> tuple[int, dict[str, str]]:
    """Last step: every unit with a painted master ships that master, downsampled.

    Runs after the raw-frame and material_class_hs passes (which sample the raw interface
    icons), so the painted art is never overwritten by a 58x64 frame. Output bytes match
    tools/downsample_homm3_runtime_static_assets.py (square Lanczos to the contract side,
    PNG optimize), so the two tools agree. Frames stay the painting reference; the master's
    identity against its frame is recorded in the painting pipeline, not re-checked here.
    """
    contract = load_json(RUNTIME_SIZE_CONTRACT)
    max_side = int(contract["runtime"]["unitPortraits"]["maxSidePx"])
    changed = 0
    painted: dict[str, str] = {}
    for sid in sorted(source_by_sid):
        master = PAINTED_MASTERS / f"{sid}.png"
        if not master.is_file():
            continue
        with Image.open(master) as im:
            im = im.convert("RGBA")
            if im.width != im.height:
                raise RuntimeError(f"painted portrait master must be square: {master} {im.size}")
            side = min(max_side, im.width)
            if im.size != (side, side):
                im = im.resize((side, side), Image.Resampling.LANCZOS)
            changed += int(write_image_if_changed(PORTRAITS / f"{sid}.png", im))
        painted[sid] = str(master.relative_to(MAIN_ROOT)).replace("\\", "/")
    return changed, painted


def main() -> int:
    frame_dir = ensure_twcrport_frames()
    changed = 0
    source_by_sid: dict[str, str] = {}
    for manifest_path in sorted(CUSTOM_FACTIONS.glob("homm3_*.json")):
        manifest = load_json(manifest_path)
        if not isinstance(manifest, dict):
            raise RuntimeError(f"invalid manifest {manifest_path}")
        faction_sid = str(manifest["identity"]["factionSid"])
        faction_short = faction_sid.removeprefix("homm3_")
        variants = manifest.get("unitVariants") or ["", "_upg", "_upg_alt"]
        for line in iter_manifest_unit_lines(manifest):
            for variant_index, suffix in enumerate(variants):
                sid = sid_for_variant(line, str(suffix))
                image, source = load_portrait_for_variant(frame_dir, faction_short, line, str(suffix), variant_index)
                changed += int(copy_image_to_portrait(image, sid))
                source_by_sid[sid] = source
        if faction_short == "factory":
            changed += generate_factory_sandworm_larva_portrait(source_by_sid)
    changed += generate_neutral_portraits(frame_dir, source_by_sid)

    # Overwrite Factory/Bulwark alt portraits after base HotA icons are on disk so
    # the shared-background mask can sample upgrade portraits across lines.
    factory_changed, factory_alt_report = apply_material_class_hs_alt_portraits(source_by_sid, "factory")
    changed += factory_changed
    bulwark_changed, bulwark_alt_report = apply_material_class_hs_alt_portraits(source_by_sid, "bulwark")
    changed += bulwark_changed

    painted_changed, painted = apply_painted_masters(source_by_sid)
    changed += painted_changed

    changed += int(
        write_manifest(
            dict(sorted(source_by_sid.items())),
            factory_alt_report=factory_alt_report,
            bulwark_alt_report=bulwark_alt_report,
            painted_masters=painted,
        )
    )
    print(
        f"Generated interface portraits for {len(source_by_sid)} unit SID(s); "
        f"painted masters={len(painted)}; raw frames={len(source_by_sid) - len(painted)}; changed={changed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
