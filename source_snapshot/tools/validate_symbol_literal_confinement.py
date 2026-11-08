#!/usr/bin/env python3
"""Gate: raw obfuscated symbol literals and direct AccessTools calls stay inside the resolver layer.

The port to another game build only works when every build-specific name lives where the build scopes
can rewrite it (GameSymbols.cs + GameSymbolsCurrent.g.cs) and every reflection lookup goes through the
owner-checked resolver (GameMember.cs, DeobfInteropCompat.cs, GameSymbolScope.cs). A literal or an
AccessTools call anywhere else silently binds the Golden Era name on the current build.

Scanned: the compiled top-level *.cs of OfflineUnlockMod (tools/, _decompiled_*/ and tmp_decomp_*.cs are
not compiled). Findings, counted per file:
  accesstools|AccessTools.<Api>     a direct Harmony AccessTools call;
  literal|<value>                   a string literal with an obfuscated shape:
      * Il2CppInterop generated names (Method_/field_/method_<Visibility>_..., *Unique, *_PDM_<n>),
      * NativeFieldInfoPtr_/NativeMethodInfoPtr_ names,
      * compiler backing fields around a short obfuscated core (<abc>k__BackingField, _abc_k__BackingField),
      * the BepInEx deobfuscation shapes ^[a-z]{2,3}$ | ^[a-c][a-z]{3}$ minus ordinary words.

The allowlist (tools/symbol_literal_confinement_allowlist.txt, `file|kind|detail|count`) is SHRINK-ONLY:
  * a finding whose count exceeds its allowed count fails (new raw literal / new direct call);
  * an allowlist line whose count exceeds the actual count fails (stale: lower or delete it);
  * never add or raise a line to make the gate pass; move the name into GameSymbols.cs instead.

Wired into the build through tools/validate_game_symbols_hint_contract.py (ValidateGameSymbolsHintContract).

Usage: python tools/validate_symbol_literal_confinement.py [--root <repo>] [--print-seed]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

PLUGIN = Path("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod")
ALLOWLIST = Path("tools/symbol_literal_confinement_allowlist.txt")
RESOLVER_FILES = {
    "GameSymbols.cs",
    "GameSymbolsCurrent.g.cs",
    "GameSymbolScope.cs",
    "GameMember.cs",
    "DeobfInteropCompat.cs",
}

TOKEN = re.compile(r'''
    (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<vstr>@"(?:[^"]|"")*")
  | (?P<istr>\$@?"(?:[^"\\\n]|\\.)*")
  | (?P<str>"(?:[^"\\\n]|\\.)*")
  | (?P<chr>'(?:[^'\\\n]|\\.)+')
  | (?P<code>[^/"'@$]+|.)
''', re.S | re.X)
ACCESSTOOLS = re.compile(r"\bAccessTools\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)")

GENERATED = re.compile(
    r"^(?:get_|set_)?(?:Method|method|field)_(?:Public|Private|Internal|Protected|Assembly|Family|Static)_[A-Za-z0-9_]+$"
    r"|Unique\b|_PDM_\d+$|^Native(?:Field|Method)InfoPtr_"
)
SHORT_CORE = r"(?:[a-z]{2,3}|[a-c][a-z]{3})"
BACKING = re.compile(rf"^(?:get_|set_)?(?:<{SHORT_CORE}>k__BackingField|_{SHORT_CORE}_k__BackingField)$")
SHORT = re.compile(rf"^{SHORT_CORE}$")
ORDINARY = {
    "a", "act", "add", "age", "aid", "air", "all", "and", "any", "arg", "art", "as", "ask", "atk", "avg",
    "bad", "bag", "bar", "bat", "bed", "big", "bin", "bit", "bow", "box", "btn", "bug", "but", "buy", "by",
    "cam", "can", "cap", "car", "cat", "cfg", "cmd", "cnt", "col", "cos", "cpu", "cry", "cs", "csv", "cur",
    "cut", "day", "dbg", "def", "del", "dev", "did", "die", "dim", "dir", "dll", "doc", "dog", "dot", "dry",
    "due", "ear", "end", "err", "eta", "ex", "exe", "exp", "eye", "fan", "far", "fee", "few", "fit", "fix",
    "fly", "fog", "for", "fps", "fx", "gap", "gas", "get", "gif", "god", "gpu", "gui", "gun", "has", "hat",
    "hex", "hit", "hot", "how", "hp", "hud", "icon", "id", "ids", "if", "img", "in", "ini", "inn", "io", "is",
    "it", "jpg", "json", "key", "kit", "lab", "law", "lay", "led", "leg", "len", "let", "lid", "lie", "lit",
    "log", "lot", "low", "lua", "mac", "mad", "man", "map", "max", "may", "mem", "men", "mid", "min", "mix",
    "mod", "mp", "msg", "mud", "my", "net", "new", "nil", "no", "nor", "not", "now", "null", "num", "obj",
    "odd", "of", "off", "oil", "ok", "old", "on", "one", "or", "our", "out", "own", "pad", "pan", "par", "pay",
    "pct", "pdf", "pen", "per", "pet", "pic", "pin", "pit", "png", "pop", "pos", "pot", "put", "raw", "ray",
    "red", "ref", "rep", "req", "res", "ret", "rgb", "rng", "rot", "row", "run", "sad", "saw", "say", "sea",
    "see", "seq", "set", "she", "sid", "sin", "sit", "six", "sky", "so", "sp", "spd", "sql", "src", "std",
    "str", "sub", "sum", "sun", "svg", "tab", "tag", "tan", "tap", "tax", "tea", "ten", "tex", "the", "tie",
    "tip", "tmp", "to", "toe", "too", "top", "toy", "try", "ttl", "two", "txt", "ui", "up", "url", "us", "use",
    "uv", "val", "var", "vec", "via", "vs", "war", "was", "way", "web", "wet", "who", "why", "win", "won",
    "xml", "xp", "yes", "yet", "you", "zip", "zoo",
    "able", "back", "bake", "ball", "band", "bank", "base", "bash", "beam", "bear", "beat", "bell", "belt",
    "best", "bind", "bird", "bite", "blue", "blur", "boat", "body", "bold", "bolt", "bone", "book", "boot",
    "boss", "both", "bowl", "buff", "bulk", "burn", "busy", "byte", "cage", "cake", "call", "calm", "came",
    "camp", "card", "care", "cart", "case", "cash", "cast", "cell", "char", "chat", "chip", "city", "clan",
    "clip", "club", "coat", "code", "coin", "cold", "cone", "cool", "copy", "core", "cost", "crit", "cube",
    "curl", "cyan", "back", "aura", "area", "army", "arch", "atom", "auto", "axis", "away", "acid", "also",
    "ammo", "apex", "arms",
    # Core unit sids carried by generated catalogs (Homm3TowerArtificingCatalog.g.cs).
    "ent", "jaw",
}


def iter_literals(text: str):
    """(value, line) for every string literal outside comments; interpolated strings are skipped."""
    line = 1
    for m in TOKEN.finditer(text):
        kind, raw = m.lastgroup, m.group(0)
        if kind == "str":
            yield raw[1:-1], line
        elif kind == "vstr":
            yield raw[2:-1].replace('""', '"'), line
        line += raw.count("\n")


def code_only(text: str) -> str:
    return "".join(m.group(0) if m.lastgroup == "code" else " " for m in TOKEN.finditer(text))


def literal_kind(value: str) -> bool:
    if GENERATED.search(value):
        return True
    if BACKING.match(value):
        return re.sub(r"^(?:get_|set_)?[<_]|[>_]k__BackingField$", "", value) not in ORDINARY
    return bool(SHORT.match(value)) and value not in ORDINARY


def scan(root: Path) -> Counter:
    found: Counter = Counter()
    plugin = root / PLUGIN
    for path in sorted(plugin.glob("*.cs")):
        if path.name in RESOLVER_FILES or path.name.startswith("tmp_decomp_"):
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for api in ACCESSTOOLS.findall(code_only(text)):
            found[(path.name, "accesstools", f"AccessTools.{api}")] += 1
        for value, _ in iter_literals(text):
            if literal_kind(value):
                found[(path.name, "literal", value)] += 1
    return found


def load_allowlist(path: Path) -> tuple[Counter, list[str]]:
    allowed: Counter = Counter()
    errors = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) != 4 or not parts[3].isdigit() or int(parts[3]) <= 0:
            errors.append(f"{path}:{n}: malformed line {line!r} (want file|kind|detail|count>0)")
            continue
        key = (parts[0], parts[1], parts[2])
        if key in allowed:
            errors.append(f"{path}:{n}: duplicate entry {line!r}")
        allowed[key] = int(parts[3])
    return allowed, errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--print-seed", action="store_true", help="print current findings in allowlist format and exit 0")
    a = ap.parse_args(argv)
    root = Path(a.root)
    found = scan(root)
    if a.print_seed:
        for (f, k, d), c in sorted(found.items()):
            print(f"{f}|{k}|{d}|{c}")
        return 0
    allowed, errors = load_allowlist(root / ALLOWLIST)
    for key, count in sorted(found.items()):
        if count > allowed.get(key, 0):
            f, k, d = key
            errors.append(f"NEW {k} in {f}: {d!r} x{count} (allowed {allowed.get(key, 0)}); "
                          "route it through GameSymbols.cs / GameMember instead")
    for key, count in sorted(allowed.items()):
        if found.get(key, 0) < count:
            f, k, d = key
            errors.append(f"STALE allowlist {f}|{k}|{d}|{count}: actual {found.get(key, 0)}; "
                          "lower or delete the line (the list only shrinks)")
    total = sum(found.values())
    if errors:
        print(f"validate_symbol_literal_confinement: FAILED ({len(errors)} problems, {total} findings)")
        for e in errors:
            print("  " + e)
        return 1
    acc = sum(c for (f, k, d), c in found.items() if k == "accesstools")
    print(f"validate_symbol_literal_confinement: OK ({acc} allow-listed AccessTools calls, "
          f"{total - acc} allow-listed literals, {len(allowed)} allowlist lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
