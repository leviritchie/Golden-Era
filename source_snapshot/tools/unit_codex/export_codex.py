#!/usr/bin/env python3
"""Build the Golden Era Codex: a static, searchable site of the mod's custom units,
their upgrade branches, and every custom town's building tree.

Everything on the page is derived from data the game itself reads, so the site
cannot drift from the mod:

- unit stats, costs, upgrades     DB/units/units_logics/<faction>/*.json
- ability cards and icons         DB/units/units_views/<faction>/*.json
- card/building text              Lang/english/texts/*.json (+ Lang/args, DB/info/*.script)
- building trees and growth       DB/objects_logic/cities/<city>.json (nodePos, prevBuildings)
- unit lines, faction identity    custom_factions/homm3_*.json
- portraits / ability icons       OfflineUnlockMod/homm3_portraits, homm3_skill_icons

Usage (reads the installed Golden Era Core.zip by default; pass --core to read a
staged release Core.zip instead):

    python tools/unit_codex/export_codex.py --out V:/olden_port_work/unit_codex/site

The output folder is a complete static site (index.html + data + images) that
GitHub Pages can serve as-is. No network access, no game launch.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
SITE_SRC = Path(__file__).resolve().parent / "site"
DEFAULT_CORE = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)

STAT_KEYS = ["hp", "offence", "defence", "damageMin", "damageMax", "initiative", "speed", "luck", "moral", "numCounters", "shots"]
CARD_GROUPS = [("abilities", "active"), ("alternativeAttacks", "alternate"), ("passives", "passive")]
RESOURCE_ORDER = ["gold", "wood", "ore", "mercury", "crystals", "gemstones", "dust"]

PORTRAIT_PX = 256
ICON_PX = 72
CREST_PX = 128


# ---------------------------------------------------------------- core reading

class Core:
    def __init__(self, path: Path):
        self.path = path
        self.zf = zipfile.ZipFile(path)
        self.names = self.zf.namelist()
        self.tokens: dict[str, str] = {}
        self.args: dict[str, list[str]] = {}
        for name in self.names:
            if name.startswith("Lang/english/texts/") and name.endswith(".json"):
                for row in self.json(name).get("tokens", []):
                    self.tokens[row["sid"]] = row.get("text", "")
            elif name.startswith("Lang/args/") and name.endswith(".json"):
                for row in self.json(name).get("tokensArgs", []):
                    self.args[row["sid"]] = row.get("args", [])
        self.info = InfoScripts(self)

    def json(self, name: str) -> Any:
        return json.loads(self.zf.read(name).decode("utf-8-sig"))

    def rows(self, prefix: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name in sorted(self.names):
            if name.startswith(prefix) and name.endswith(".json"):
                out.extend(self.json(name).get("array", []))
        return out


class InfoScripts:
    """Resolves the {0}/{1} arguments in card text the way the game's DB/info scripts do.

    Only two shapes are used by custom cards: a literal `Text( return, "50" )`, and
    `CurrentUnitConfig( var, "path" )` followed by `Text( return, var )`. Anything
    else is reported as unresolved instead of guessed.
    """

    BLOCK = re.compile(r"^(\w+)\s+(\w+)\s*\{(.*?)^\}", re.S | re.M)

    def __init__(self, core: Core):
        self.defs: dict[str, tuple[str, str]] = {}
        for name in core.names:
            if name.startswith("DB/info/") and name.endswith(".script"):
                src = core.zf.read(name).decode("utf-8-sig", "replace")
                for m in self.BLOCK.finditer(src):
                    self.defs.setdefault(m.group(2), (m.group(1), m.group(3)))
        self.unresolved: set[str] = set()

    def resolve(self, key: str, unit: dict[str, Any] | None) -> str | None:
        key = key.split("|", 1)[0]
        found = self.defs.get(key)
        if not found:
            return None
        kind, body = found
        lit = re.search(r'Text\(\s*return\s*,\s*"([^"]*)"\s*\)', body)
        if lit:
            return lit.group(1)
        cfg = re.search(r'CurrentUnitConfig\s*\(\s*(\w+)\s*,\s*"([^"]+)"\s*\)', body)
        if cfg and unit is not None:
            value = walk_path(unit, cfg.group(2))
            if isinstance(value, (int, float)):
                if kind.lower().startswith("modpercent"):
                    value = value * 100
                return f"{value:g}" if isinstance(value, float) else str(value)
        return None


def walk_path(obj: Any, path: str) -> Any:
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            idx = int(part[1:-1])
            if not isinstance(obj, list) or idx >= len(obj):
                return None
            obj = obj[idx]
        else:
            if not isinstance(obj, dict):
                return None
            obj = obj.get(part)
    return obj


def clean_text(text: str) -> str:
    """Escape game text for the page, keeping the game's own bold/italic/colour markup."""
    text = text.replace("\r\n", "\n").strip()
    text = html.escape(text, quote=False)
    text = re.sub(r"&lt;(/?)(b|i)&gt;", r"<\1\2>", text)
    text = re.sub(r"&lt;color=(#[0-9a-fA-F]{3,8}|\w+)&gt;", r'<span class="tc" style="color:\1">', text)
    text = text.replace("&lt;/color&gt;", "</span>")
    text = re.sub(r"&lt;/?(size|sprite|style|link)[^&]*&gt;", "", text)
    return text.replace("\n", "<br>")


def resolve_text(core: Core, sid: str | None, unit: dict[str, Any] | None = None) -> str:
    if not sid:
        return ""
    raw = core.tokens.get(sid, "")
    if not raw:
        return ""
    args = core.args.get(sid, [])

    def sub(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        if idx < len(args):
            val = core.info.resolve(args[idx], unit)
            if val is not None:
                return val
            core.info.unresolved.add(f"{sid}:{args[idx]}")
        return "?"

    return clean_text(re.sub(r"\{(\d+)\}", sub, raw))


# ---------------------------------------------------------------- images

class Images:
    def __init__(self, out: Path, enabled: bool):
        self.out = out
        self.enabled = enabled
        self.written: dict[str, str] = {}
        self.reused = 0
        if enabled:
            from PIL import Image  # noqa: F401  (fail early if Pillow is missing)

    def put(self, src: Path | None, rel: str, px: int, square: bool = True) -> str | None:
        if not self.enabled or src is None or not src.is_file():
            return None
        if rel in self.written:
            return self.written[rel]
        dest = self.out / rel
        self.written[rel] = rel
        # Incremental: an image is re-encoded only when its source is newer than the output.
        if dest.is_file() and dest.stat().st_mtime >= src.stat().st_mtime:
            self.reused += 1
            return rel
        from PIL import Image

        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = im.convert("RGBA")
            bbox = im.getchannel("A").getbbox()
            if bbox and square:
                # trim transparent margins, then re-centre on a square canvas
                im = im.crop(bbox)
                side = max(im.size)
                canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
                canvas.paste(im, ((side - im.width) // 2, side - im.height))
                im = canvas
            im.thumbnail((px, px), Image.LANCZOS)
            im.save(dest, "WEBP", quality=82, method=4)
        return rel

    def prune(self) -> int:
        """Delete images from earlier builds that nothing references any more."""
        removed = 0
        img = self.out / "img"
        if self.enabled and img.is_dir():
            for f in img.rglob("*.webp"):
                if f.relative_to(self.out).as_posix() not in self.written:
                    f.unlink()
                    removed += 1
        return removed


# ---------------------------------------------------------------- units

def unit_cards(core: Core, view: dict[str, Any], logic: dict[str, Any], images: Images, icon_dirs: list[Path]) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
    cards: list[dict[str, Any]] = []
    for key, kind in CARD_GROUPS:
        for card in view.get(key) or []:
            name = resolve_text(core, card.get("name"), logic)
            desc = resolve_text(core, card.get("description"), logic)
            if not name and not desc:
                continue
            icon_sid = card.get("icon") or ""
            icon = None
            for d in icon_dirs:
                icon = images.put(d / f"{icon_sid}.png", f"img/a/{icon_sid}.webp", ICON_PX, square=False)
                if icon:
                    break
            cards.append({
                "kind": kind,
                "type": (card.get("abilityType") or "").replace("Ability_type_", ""),
                "name": name,
                "desc": desc,
                "icon": icon,
                "glyph": glyph_for(icon_sid, name, kind),
            })
    base = view.get("baseClass") or {}
    unit_class = None
    if base.get("name"):
        unit_class = {"name": resolve_text(core, base.get("name"), logic), "desc": resolve_text(core, base.get("description"), logic)}
    return cards, unit_class


def glyph_for(icon_sid: str, name: str, kind: str) -> str:
    s = f"{icon_sid} {name}".lower()
    for needle, glyph in [
        ("ranged", "bow"), ("shoot", "bow"), ("shot", "bow"), ("arrow", "bow"),
        ("fly", "wing"), ("flight", "wing"), ("flying", "wing"),
        ("immun", "ward"), ("resist", "ward"), ("armor", "ward"), ("shield", "ward"),
        ("heal", "heart"), ("regen", "heart"), ("drain", "heart"), ("life", "heart"),
        ("fire", "flame"), ("burn", "flame"), ("breath", "flame"),
        ("magic", "star"), ("spell", "star"), ("mana", "star"), ("cast", "star"),
        ("retaliat", "swords"), ("counter", "swords"), ("strike", "swords"), ("melee", "swords"), ("attack", "swords"),
    ]:
        if needle in s:
            return glyph
    return "star" if kind == "active" else "rune"


def unit_record(core: Core, logic: dict[str, Any], view: dict[str, Any], faction: str, kind: str, line_base: str | None,
                images: Images, portrait_dir: Path, icon_dirs: list[Path]) -> dict[str, Any]:
    uid = logic["id"]
    stats = logic.get("stats", {})
    cards, unit_class = unit_cards(core, view, logic, images, icon_dirs)
    ranged = any(a.get("attackType_") == "shoot" for a in logic.get("defaultAttacks") or [])
    cost = sorted(((c["name"], c["cost"]) for c in (logic.get("unitCost") or {}).get("costResArray") or [] if c.get("cost")),
                  key=lambda rc: RESOURCE_ORDER.index(rc[0]) if rc[0] in RESOURCE_ORDER else 99)
    return {
        "id": uid,
        "name": resolve_text(core, f"{uid}_name") or uid,
        "faction": faction,
        "tier": logic.get("tier"),
        "kind": kind,
        "line": line_base,
        "upgrades": [],
        "cost": [{"res": r, "n": n} for r, n in cost],
        "value": logic.get("squadValue"),
        "stats": {k: stats[k] for k in STAT_KEYS if isinstance(stats.get(k), (int, float))},
        "move": stats.get("moveType") or "ground",
        "ranged": ranged,
        "class": unit_class,
        "cards": cards,
        "portrait": images.put(portrait_dir / f"{uid}.png", f"img/u/{uid}.webp", PORTRAIT_PX),
    }


# ---------------------------------------------------------------- buildings

def building_nodes(core: Core, city: dict[str, Any], unit_ids: set[str]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for section, rows in city.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or "parametersPerLevel" not in row or not row.get("sid"):
                continue
            hires = row.get("unitsHire") or {}
            if isinstance(hires, dict):
                hires = hires.get("units", [])
            recruits: list[str] = []
            growth = None
            for h in hires or []:
                if isinstance(h, dict):
                    recruits += [s for s in h.get("sids") or [] if s in unit_ids]
                    growth = h.get("weeklyIncrement", growth)
            names, descs = row.get("names") or [], row.get("descriptions") or []
            start_level = row.get("levelOnStart", 1) if row.get("isConstructedOnStart") else 0
            for idx, level in enumerate(row["parametersPerLevel"]):
                pos = level.get("nodePos") or {}
                nodes.append({
                    "id": f"{row['sid']}@{idx + 1}",
                    "sid": row["sid"],
                    "level": idx + 1,
                    "levels": len(row["parametersPerLevel"]),
                    "section": section,
                    "name": resolve_text(core, names[idx] if idx < len(names) else (names[-1] if names else None)) or row["sid"],
                    "desc": resolve_text(core, descs[idx] if idx < len(descs) else None),
                    "cost": [{"res": c["name"], "n": c["cost"]} for c in level.get("costs") or [] if c.get("cost")],
                    "req": [f"{p['sid']}@{p.get('level', 1)}" for p in level.get("prevBuildings") or [] if p.get("sid")],
                    "x": pos.get("xPos"),
                    "y": pos.get("yPos"),
                    "start": idx < start_level,
                    "recruits": recruits,
                    "growth": growth,
                })
    return nodes


# ---------------------------------------------------------------- build

def plugin_asset(plugin: Path, rel: str | None) -> Path | None:
    """A manifest asset path. Paths under the plugin folder resolve against --plugin-dir, so a git export
    of the manifests plus a staged plugin folder (the nightly) finds the same files as the checkout.
    Bare sprite names (stock Olden Era crests) have no file and return None."""
    if not rel or "/" not in rel.replace("\\", "/"):
        return None
    rel = rel.replace("\\", "/")
    prefix = PLUGIN.relative_to(ROOT).as_posix() + "/"
    return plugin / rel[len(prefix):] if rel.startswith(prefix) else ROOT / rel


def build(core_path: Path, out: Path, with_images: bool, label: str | None, plugin: Path = PLUGIN) -> dict[str, Any]:
    t0 = time.perf_counter()
    core = Core(core_path)
    shutil.rmtree(out / "data", ignore_errors=True)
    if not with_images:
        shutil.rmtree(out / "img", ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    images = Images(out, with_images)
    portrait_dir = plugin / "homm3_portraits"
    icon_dirs = [plugin / "homm3_skill_icons"]

    logic_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    view_by_id: dict[str, dict[str, Any]] = {}
    for name in core.names:
        m = re.match(r"DB/units/units_(logics|views)/([^/]+)/[^/]+\.json$", name)
        if not m:
            continue
        folder = m.group(2)
        custom = folder.startswith("homm3_") or (folder == "neutral" and "/h3_" in name)
        if not custom:
            continue
        for row in core.json(name).get("array", []):
            if m.group(1) == "logics":
                logic_by_id[row["id"]] = (folder, row)
            else:
                view_by_id[row["id"]] = row

    units: dict[str, dict[str, Any]] = {}
    factions: list[dict[str, Any]] = []
    orphans: list[str] = []
    fusion_src = ROOT / "custom_factions" / "conflux_fusion" / "fusion_units.json"
    fusion_pairs = json.loads(fusion_src.read_text(encoding="utf-8-sig")).get("units", {}) if fusion_src.is_file() else {}
    for manifest_path in sorted((ROOT / "custom_factions").glob("homm3_*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        ident = manifest["identity"]
        fsid = ident["factionSid"]
        city_path = manifest.get("coreOverlay", {}).get("cityLogic")
        if not city_path or city_path not in core.names:
            raise SystemExit(f"CODEX: FAIL {fsid}: city logic {city_path!r} missing from {core_path}")
        own_ids = {uid for uid, (folder, _) in logic_by_id.items() if folder == fsid}
        buildings = building_nodes(core, core.json(city_path)["array"][0], own_ids)

        # A line is exactly what one dwelling recruits, in the game's order: base, upgrade, alternate upgrade.
        # (Manifest unitLines predate several renames, so they are not used to pick units.)
        lines = []
        for node in buildings:
            if node["level"] != 1 or not node["recruits"]:
                continue
            ids = node["recruits"]
            for pos, uid in enumerate(ids):
                kind = ["base", "upg", "alt"][min(pos, 2)]
                units[uid] = unit_record(core, logic_by_id[uid][1], view_by_id.get(uid, {}), fsid, kind, ids[0], images, portrait_dir, icon_dirs)
                units[uid]["dwelling"] = node["sid"]
                units[uid]["growth"] = node["growth"]
            units[ids[0]]["upgrades"] = ids[1:]
            lines.append({"tier": units[ids[0]]["tier"], "dwelling": node["sid"], "units": ids})
        lines.sort(key=lambda l: (l["tier"] or 99, l["dwelling"]))

        # Units no dwelling recruits: Conflux fusion forms are real (made in battle); anything else is a stale row.
        extras = []
        for uid in sorted(own_ids - set(units), key=lambda u: (logic_by_id[u][1].get("tier", 99), u)):
            if uid.startswith("h3_fusion_"):
                units[uid] = unit_record(core, logic_by_id[uid][1], view_by_id.get(uid, {}), fsid, "fusion", None, images, portrait_dir, icon_dirs)
                pair = fusion_pairs.get(uid) or {}
                if pair.get("host") in units and pair.get("guest") in units:
                    units[uid]["parents"] = [pair["host"], pair["guest"]]
                extras.append(uid)
            else:
                orphans.append(uid)

        crest_src = plugin_asset(plugin, manifest.get("assets", {}).get("factionIcon"))
        factions.append({
            "sid": fsid,
            "key": fsid.removeprefix("homm3_"),
            "name": resolve_text(core, ident.get("displayNameToken")) or fsid.removeprefix("homm3_").title(),
            "desc": resolve_text(core, ident.get("descriptionToken")),
            "skill": manifest.get("skillsAndLaws", {}).get("factionSkillName", ""),
            "biome": ident.get("nativeBiome", ""),
            "crest": images.put(crest_src, f"img/f/{fsid}.webp", CREST_PX),
            "lines": lines,
            "extras": extras,
            "buildings": buildings,
        })

    neutral_ids = []
    for uid, (folder, logic) in sorted(logic_by_id.items(), key=lambda kv: (kv[1][1].get("tier", 99), kv[0])):
        if folder == "neutral" and uid not in units:
            units[uid] = unit_record(core, logic, view_by_id.get(uid, {}), "neutral", "neutral", None, images, portrait_dir, icon_dirs)
            neutral_ids.append(uid)
    if neutral_ids:
        factions.append({"sid": "neutral", "key": "neutral", "name": "Neutrals", "desc": "Custom neutral creatures found on the adventure map.",
                         "skill": "", "biome": "", "crest": None, "lines": [], "extras": neutral_ids, "buildings": []})

    core_sha = hashlib.sha256(core_path.read_bytes()).hexdigest()
    data = {
        "schema": 1,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "label": label or git_label(),
        "core": core_sha[:12],
        "factions": factions,
        "units": units,
    }
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "data" / "codex.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for src in SITE_SRC.iterdir():
        if src.is_file():
            shutil.copy2(src, out / src.name)

    stats = {
        "factions": len(factions),
        "units": len(units),
        "buildingNodes": sum(len(f["buildings"]) for f in factions),
        "portraitsMissing": sorted(u["id"] for u in units.values() if not u["portrait"] and u["kind"] != "fusion") if with_images else "skipped",
        "unrecruitableRowsSkipped": sorted(orphans),
        "unitsWithoutCards": sorted(u["id"] for u in units.values() if not u["cards"]),
        "unresolvedArgs": sorted(core.info.unresolved),
        "images": len(images.written),
        "imagesReused": images.reused,
        "imagesPruned": images.prune(),
        "seconds": round(time.perf_counter() - t0, 1),
    }
    return stats


def git_label() -> str:
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short=10", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        return f"dev-{sha}"
    except (OSError, subprocess.CalledProcessError):
        return "dev"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--core", type=Path, default=DEFAULT_CORE, help="Core.zip to read (default: installed Golden Era)")
    ap.add_argument("--out", type=Path, required=True, help="site output folder")
    ap.add_argument("--label", help="version label shown on the page (e.g. v0.1.328 or nightly-20261118-abcdef12)")
    ap.add_argument("--plugin-dir", type=Path, default=PLUGIN, help="OfflineUnlockMod folder holding homm3_portraits/ and homm3_skill_icons/")
    ap.add_argument("--no-images", action="store_true", help="skip portraits/icons (fast data-only rebuild)")
    args = ap.parse_args()
    if not args.core.is_file():
        print(f"CODEX: FAIL Core.zip not found: {args.core}", file=sys.stderr)
        return 2
    stats = build(args.core, args.out, not args.no_images, args.label, args.plugin_dir)
    print(json.dumps(stats, indent=1))
    print(f"CODEX: OK {stats['units']} units, {stats['buildingNodes']} building nodes, {stats['images']} images in {stats['seconds']}s -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
