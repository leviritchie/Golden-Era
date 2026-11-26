"""Preview custom faction law descriptions exactly as each level will read in game, and lint their style.

Reads custom_factions/law_overrides/homm3_<faction>.json and the installed Core's laws.script, fills every
{n} placeholder from descriptionArgs against that level's parametersPerLevel (the game's laws.script rules:
modPercent = |v x 100|, modInt = |round(v)|), and prints the tree in rank order.

    python tools/release_port/preview_custom_law_text.py castle rampart
    python tools/release_port/preview_custom_law_text.py --all --flags-only

Exit code 1 when any enabled law has a flag, so it can gate a faction hand-back.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES = ROOT / "custom_factions" / "law_overrides"
DEFAULT_CORE = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)
FACTIONS = (
    "castle", "rampart", "tower", "inferno", "necropolis", "dungeon",
    "stronghold", "fortress", "conflux", "cove", "factory", "bulwark",
)
PLACEHOLDER = re.compile(r"\{(\d+)\}")

# Style rules from the vanilla law texts (docs/faction_law_pass_20261125/STYLE.md).
STYLE_RULES: tuple[tuple[str, str], ...] = (
    (r"\d+\s*%?\s*/\s*[+\-\u2013]?\d", "slash list of per-level numbers (each level shows only its own number)"),
    (r"\bby rank\b|\bat (the )?(second|third|2nd|3rd) level\b|\bat level \d\b", "level-conditional wording"),
    (r"\bDefence\b", "spelling: vanilla uses Defense"),
    (r"\bgain \+(?:\d+|\{\d+\})(?!\d|\s*%)", "flat stat with +: vanilla writes 'gain 2 Attack'"),
    (r"\bgrowth \+\d|\bgrowth in your cities increases by \+", "growth wording: 'X growth in your cities increases by {0}.'"),
    (r"\bYour kingdom gains\b", "income wording: 'Produces {0} Gold daily.'"),
    (r"\b(plugin|runtime|Core|hook|sid|donor|native|TODO|placeholder|anchor)\b", "implementation word"),
    (r"  ", "double space"),
    (r"\bLarge creatures\b", "Olden Era has no large creatures"),
    (r"[A-Za-z]'[A-Za-z]|s' ", "straight apostrophe: vanilla uses ’"),
    (r"(?<![\w‑])-\d|(?<=\s)-\{", "minus sign: vanilla writes – (en dash) before a reduction"),
    (r"\b(Tier|one|non)-", "hyphen: vanilla writes a non-breaking hyphen ‑ here"),
    (r"\bexperience\b", "vanilla says XP"),
)


def load_script_functions(core: Path) -> dict[str, tuple[str, str | None, str | None]]:
    with zipfile.ZipFile(core) as zf:
        text = zf.read("DB/info/info_laws/laws.script").decode("utf-8-sig")
    funcs: dict[str, tuple[str, str | None, str | None]] = {}
    for m in re.finditer(r"(?ms)^\s*(\w+)\s+(\w+)\s*$\s*\{(.*?)^\s*\}", text):
        kind, name, body = m.group(1), m.group(2), m.group(3)
        path = re.search(r'CurrentFractionLawConfig\s*\(\s*lawData\s*,\s*"([^"]+)"', body)
        lit = re.search(r'Text\s*\(\s*return\s*,\s*"([^"]*)"', body)
        funcs[name] = (kind, path.group(1) if path else None, lit.group(1) if lit else None)
    return funcs


def walk(level: dict, path: str):
    cur = level
    for part in re.findall(r"\w+|\[\d+\]", path):
        if part.startswith("["):
            i = int(part[1:-1])
            if not isinstance(cur, list) or i >= len(cur):
                return None
            cur = cur[i]
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
    return cur


def fmt(v: float) -> str:
    return str(int(round(v))) if abs(v - round(v)) < 1e-6 else f"{v:.2f}".rstrip("0").rstrip(".")


def arg_value(funcs, arg: str, level: dict) -> str | None:
    kind, path, lit = funcs.get(arg, (None, None, None))
    if kind is None:
        return None
    raw = walk(level, path) if path else lit
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    if kind == "modPercentNumeric":
        return fmt(abs(v * 100))
    if kind.startswith("modFloatPercent"):
        return f"{abs(v * 100):.1f}".rstrip("0").rstrip(".")
    if kind == "modInt":
        return fmt(abs(round(v)))
    return fmt(v)


def render(funcs, template: str, args: list[str], level: dict) -> tuple[str, list[str]]:
    problems: list[str] = []

    def sub(m: re.Match) -> str:
        i = int(m.group(1))
        if i >= len(args):
            problems.append(f"{{{i}}} has no descriptionArgs entry")
            return m.group(0)
        value = arg_value(funcs, args[i], level)
        if value is None:
            problems.append(f"{{{i}}} = {args[i]} does not resolve on this level")
            return m.group(0)
        return value

    return PLACEHOLDER.sub(sub, template), problems


def lint(text: str) -> list[str]:
    flags = [why for pattern, why in STYLE_RULES if re.search(pattern, text)]
    if text.strip() and text.strip()[-1] not in ".!?":
        flags.append("no final period")
    return flags


def preview(faction: str, funcs, flags_only: bool) -> int:
    path = OVERRIDES / f"homm3_{faction}.json"
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    overrides = doc.get("lawOverrides") or {}
    tree = doc.get("lawTree") or []
    prefix = f"fraction_law_homm3_{faction}_"
    order: list[tuple[str, int]] = []
    for rank, row in enumerate(tree):
        for column in ("kingdom", "army"):
            for index in row.get(column) or []:
                order.append((f"r{rank}{column[0].upper()}", int(index)))
    placed = {index for _tag, index in order}
    for key, entry in overrides.items():
        index = int(str(key).rsplit("_", 1)[-1])
        if isinstance(entry, dict) and entry.get("enabled") is not False and index not in placed and "descriptionText" in entry:
            order.append(("unplaced", index))
    flagged = 0
    print(f"=== {faction}")
    for tag, index in order:
        entry = overrides.get(f"{prefix}{index}")
        if not isinstance(entry, dict) or "descriptionText" not in entry:
            if not flags_only:
                print(f"  {tag} #{index} (generated: Resource Riches / Mining)")
            continue
        template = entry["descriptionText"]
        args = entry.get("descriptionArgs") or []
        levels = entry.get("parametersPerLevel") or []
        lines: list[str] = []
        law_flags: list[str] = []
        used = {int(n) for n in PLACEHOLDER.findall(template)}
        if used != set(range(len(args))):
            law_flags.append(f"placeholders {sorted(used)} vs {len(args)} descriptionArgs")
        for unknown in [a for a in args if a not in funcs]:
            law_flags.append(f"{unknown} is not a laws.script function")
        seen_texts: list[str] = []
        for n, level in enumerate(levels, start=1):
            text, problems = render(funcs, template, args, level)
            law_flags += [f"L{n}: {p}" for p in problems]
            law_flags += [f"L{n}: {f}" for f in lint(text)]
            seen_texts.append(text)
            lines.append(f"      L{n} [{level.get('cost')}] {text}")
        if len(levels) > 1 and len(set(seen_texts)) == 1 and not args:
            law_flags.append("multi-level law whose text never changes (add the level's numbers as {n})")
        law_flags = list(dict.fromkeys(law_flags))
        if law_flags:
            flagged += 1
        if flags_only and not law_flags:
            continue
        print(f"  {tag} #{index} {entry.get('nameText')}")
        if not flags_only or law_flags:
            for line in lines:
                print(line)
        for flag in law_flags:
            print(f"      !! {flag}")
    return flagged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("factions", nargs="*", help="faction short names (castle, rampart, ...)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--flags-only", action="store_true")
    ap.add_argument("--core", type=Path, default=DEFAULT_CORE)
    a = ap.parse_args()
    factions = FACTIONS if a.all or not a.factions else tuple(f.removeprefix("homm3_") for f in a.factions)
    funcs = load_script_functions(a.core)
    flagged = sum(preview(f, funcs, a.flags_only) for f in factions)
    print(f"\n{flagged} flagged law(s)")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
