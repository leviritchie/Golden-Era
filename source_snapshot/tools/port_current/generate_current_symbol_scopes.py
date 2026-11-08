#!/usr/bin/env python3
"""Generate the build-scoped `current` hint scopes of GameSymbols from the P1 remap.

Output: `OfflineUnlockMod/GameSymbolsCurrent.g.cs` plus the tracked report
`tools/port_current/remap/current_scopes_<buildid>.json`. Nothing here edits GameSymbols.cs.

How the plugin consumes it (docs/port_to_current_game_version.md, "Phase 2/3 current scopes"):
every nested class of GameSymbols is `partial`, and the generated file gives each class that owns
remapped hint declarations a static constructor. On the current build (GameBuild.Kind == Current)
the constructor replaces each declaration's Golden Era literals with the live ones, position for
position, so every consumer (GameMember or a direct `foreach` over the array) sees live names. On
Golden Era and on an unknown build the constructor returns before touching anything, so Golden
Era resolution is unchanged by construction.

Per declaration (a `string`, `string[]`, `MethodSymbol`, `FieldSymbol`, `MethodSymbol[]`, `FieldSymbol[]`
or `(string Name, int ParameterCount)[]` whose initializer is literal-only):

* `scoped`: the remap group is `all_mapped` and every mapped literal was verified against the live
  index (a type literal reaches exactly one live type, whose shape is pinned; a member literal
  exists on its live owner). Positions whose literal named nothing on Golden Era (dead aliases)
  are kept verbatim unless the literal names something on the live build, where it would bind a
  reused name; those become the refusal sentinel.
* `refused`: anything else (partially mapped, unmapped, owner unmapped, unverified, literals
  changed since the remap, non-literal initializer). Every position becomes the refusal sentinel
  `!unresolved-on-current-build:<symbol>`, which cannot name any type or member, keeps array
  lengths (indexing consumers do not throw) and makes GameMember refuse with a clear log.
* `identity`: remap kind `none` (the literals are not symbol hints, e.g. building ids) - untouched.

`const string` hints cannot be rewritten and are listed as `const` (the GameMember build gate
still refuses obfuscated/generated names through them off Golden Era). Literals inside method
bodies are listed as `inline`.

Modes:
  --evidence   rebuild the evidence file from the port and shape indexes (needs artifacts/)
  (default)    regenerate the .g.cs and report from remap + evidence + GameSymbols.cs
  --check      regenerate in memory and fail (exit 1) when the checked-in outputs differ (STALE)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from symbol_remap import literals as harvest  # noqa: E402

PLUGIN_DIR = REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
GAME_SYMBOLS = PLUGIN_DIR / "GameSymbols.cs"
GENERATED_CS = PLUGIN_DIR / "GameSymbolsCurrent.g.cs"
REMAP_DIR = HERE / "remap"
# The one live build the plugin treats as GameBuildKind.Current. Retired builds keep their tracked
# remap/evidence/overrides/report files; only this build is generated into GameSymbolsCurrent.g.cs.
BUILD_ID = "25672315"
REMAP = REMAP_DIR / f"game_symbols_remap_{BUILD_ID}.json"
EVIDENCE = REMAP_DIR / f"current_scope_evidence_{BUILD_ID}.json"
OVERRIDES = REMAP_DIR / f"current_scope_overrides_{BUILD_ID}.json"
REPORT = REMAP_DIR / f"current_scopes_{BUILD_ID}.json"
SCHEMA = "game_symbols_current_scopes.v1"
EVIDENCE_SCHEMA = "game_symbols_current_scope_evidence.v1"
OVERRIDES_SCHEMA = "game_symbols_current_scope_overrides.v1"

REAL_TYPE_NAME = re.compile(r"^(?![a-z]{1,4}$)[A-Za-z_][A-Za-z0-9_.+`]*$")
GENERATED = re.compile(r"^(Method|field|prop|NativeFieldInfoPtr|NativeMethodInfoPtr)_|Unique$|^Object(Public|Private|N)")
PTR_PREFIXES = ("NativeFieldInfoPtr_", "NativeMethodInfoPtr_")
SCOPABLE_TYPES = ("string", "string[]", "MethodSymbol", "FieldSymbol", "MethodSymbol[]", "FieldSymbol[]", "tuple[]")
OK = ("MAPPED", "UNCHANGED")


def fnv1a32(values: list[str]) -> int:
    """Must match GameSymbolScope.Hash in the plugin: FNV-1a 32 over UTF-8, values joined by U+001F."""
    h = 0x811C9DC5
    for b in "\x1f".join(values).encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def text_sha256(path: Path) -> str:
    """sha256 of a tracked text file with CRLF normalised to LF, so autocrlf checkouts stay FRESH."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest().upper()


# ------------------------------------------------------------------------------------------------
# GameSymbols.cs declaration parser
# ------------------------------------------------------------------------------------------------
@dataclass
class Element:
    """One symbol inside a declaration: its hint literals (ids excluded) in order."""
    hints: list[str]


@dataclass
class Decl:
    cls: str
    name: str
    decl_type: str          # string | string[] | MethodSymbol | FieldSymbol | MethodSymbol[] | FieldSymbol[] | tuple[] | const | other
    line: int
    elements: list[Element] = field(default_factory=list)
    literal_only: bool = True
    alias_of: str | None = None
    group_current: str | None = None   # TypeHintGroup: the `current:` expression kind
    group_golden_ref: str | None = None
    group_golden_shape: tuple | None = None
    group_current_ref: str | None = None

    @property
    def symbol(self) -> str:
        return f"{self.cls}.{self.name}"

    @property
    def hints(self) -> list[str]:
        return [h for e in self.elements for h in e.hints]


def _tokens(text: str):
    return list(harvest.tokenize(text))


def _string_value(kind: str, val: str) -> str:
    if kind == "vstr":
        return val[2:-1].replace('""', '"')
    return harvest._unescape(val[1:-1])


def _split_top(toks, open_ch, close_ch):
    """toks start at open_ch; return (list of element token-lists at depth 1, index after close)."""
    assert toks[0][1] == open_ch
    depth = 0
    elems, cur = [], []
    for i, t in enumerate(toks):
        v = t[1]
        if t[0] == "punct" and v in "({[":
            depth += 1
            if depth == 1:
                continue
        elif t[0] == "punct" and v in ")}]":
            depth -= 1
            if depth == 0:
                if cur:
                    elems.append(cur)
                return elems, i + 1
        elif t[0] == "punct" and v == "," and depth == 1:
            elems.append(cur)
            cur = []
            continue
        cur.append(t)
    raise ValueError("unbalanced initializer")


def _only_strings(elem) -> list[str] | None:
    if len(elem) == 1 and elem[0][0] in ("str", "vstr"):
        return [_string_value(elem[0][0], elem[0][1])]
    return None


def _parse_ctor(elem, arity: int | None):
    """`new ( "id", "a", ... )` or `new MethodSymbol(...)` -> list of string args, else None."""
    toks = list(elem)
    if not toks or toks[0][1] != "new":
        return None
    toks = toks[1:]
    if toks and toks[0][0] == "ident":
        toks = toks[1:]
    if not toks or toks[0][1] != "(":
        return None
    args, end = _split_top(toks, "(", ")")
    if end != len(toks):
        return None
    out = []
    for a in args:
        s = _only_strings(a)
        if s is None:
            return None
        out.extend(s)
    if arity is not None and len(out) != arity:
        return None
    return out


def _array_body(init):
    """Initializer of an array: `{...}`, `new[] {...}`, `new T[] {...}` -> element token lists."""
    toks = list(init)
    while toks and toks[0][1] != "{":
        if toks[0][1] not in ("new", "[", "]") and toks[0][0] != "ident":
            return None
        toks = toks[1:]
    if not toks:
        return None
    elems, end = _split_top(toks, "{", "}")
    return elems if end == len(toks) else None


def parse_game_symbols(text: str) -> list[Decl]:
    toks = _tokens(text)
    decls: list[Decl] = []
    i, n = 0, len(toks)
    stack: list[str] = []          # brace kinds: 'class:<name>' | 'block'
    pending: list = []
    while i < n:
        kind, val, line = toks[i]
        if kind == "punct" and val == "{" and not any(t[1] == "=" for t in pending):
            idents = [t[1] for t in pending if t[0] == "ident"]
            if "class" in idents or "struct" in idents:
                kw = "class" if "class" in idents else "struct"
                stack.append("class:" + idents[idents.index(kw) + 1])
            else:
                stack.append("block")
            pending = []
            i += 1
            continue
        if kind == "punct" and val == "}" and not pending:
            if stack:
                stack.pop()
            i += 1
            continue
        pending.append(toks[i])
        # statement end: ';' at bracket depth 0 of the pending statement
        if kind == "punct" and val == ";":
            depth = 0
            for t in pending[:-1]:
                if t[0] == "punct" and t[1] in "({[":
                    depth += 1
                elif t[0] == "punct" and t[1] in ")}]":
                    depth -= 1
            if depth == 0:
                in_member_class = (len(stack) == 2 and stack[0] == "class:GameSymbols"
                                   and stack[1].startswith("class:"))
                if in_member_class:
                    d = _declaration(stack[1][6:], pending[:-1])
                    if d is not None:
                        decls.append(d)
                pending = []
        i += 1
    return decls


def _declaration(cls: str, stmt) -> Decl | None:
    idents = [t[1] for t in stmt if t[0] == "ident"]
    if not idents or idents[0] != "internal":
        return None
    try:
        eq = next(j for j, t in enumerate(stmt) if t[0] == "punct" and t[1] == "=")
    except StopIteration:
        return None
    head, init = stmt[:eq], stmt[eq + 1:]
    head_ids = [t[1] for t in head if t[0] == "ident"]
    if len(head_ids) < 2:
        return None
    name = head_ids[-1]
    line = stmt[0][2]
    head_text = [t[1] for t in head]
    if "const" in head_ids:
        d = Decl(cls, name, "const", line)
        s = _only_strings(init) if len(init) == 1 else None
        d.elements = [Element(s)] if s else []
        d.literal_only = s is not None
        return d
    if "static" not in head_ids or "readonly" not in head_ids:
        return None
    # declared type
    mods = {"internal", "static", "readonly"}
    type_toks = [t for t in head if t[1] not in mods][:-1]
    type_text = "".join(t[1] for t in type_toks)
    if type_text.startswith("(") or (type_toks and type_toks[0][1] == "("):
        dtype = "tuple[]"
    else:
        dtype = type_text
    d = Decl(cls, name, dtype, line)
    if dtype == "TypeHintGroup":
        _parse_type_group(d, init)
        return d
    if all(t[0] == "ident" for t in init) and init:
        d.alias_of = ".".join(t[1] for t in init)
        d.literal_only = False
        return d
    try:
        if dtype == "string[]":
            body = _array_body(init)
            if body is None:
                d.literal_only = False
            else:
                for e in body:
                    s = _only_strings(e)
                    if s is None:
                        d.literal_only = False
                        break
                    d.elements.append(Element(s))
        elif dtype == "string":
            v = _only_strings(init) if len(init) == 1 else None
            if v is None:
                d.literal_only = False
            else:
                d.elements = [Element(v)]
        elif dtype == "MethodSymbol":
            args = _parse_ctor(init, None)
            if args is None or not args:
                d.literal_only = False
            else:
                d.elements = [Element(args[1:])]
        elif dtype == "FieldSymbol":
            args = _parse_ctor(init, 3)
            if args is None:
                d.literal_only = False
            else:
                d.elements = [Element(args[1:])]
        elif dtype in ("MethodSymbol[]", "FieldSymbol[]"):
            body = _array_body(init)
            if body is None:
                d.literal_only = False
            else:
                for e in body:
                    args = _parse_ctor(e, 3 if dtype == "FieldSymbol[]" else None)
                    if args is None or not args:
                        d.literal_only = False
                        break
                    d.elements.append(Element(args[1:]))
        elif dtype == "tuple[]":
            body = _array_body(init)
            if body is None:
                d.literal_only = False
            else:
                for e in body:
                    if not e or e[0][1] != "(":
                        d.literal_only = False
                        break
                    parts, _ = _split_top(e, "(", ")")
                    s = _only_strings(parts[0]) if parts else None
                    if s is None:
                        d.literal_only = False
                        break
                    d.elements.append(Element(s))
        else:
            d.decl_type = "other"
            d.literal_only = False
    except ValueError:
        d.literal_only = False
    return d


def _parse_type_group(d: Decl, init) -> None:
    toks = list(init)
    joined = " ".join(t[1] for t in toks)
    m = re.search(r"current\s*:\s*TypeHintScope\s+(\w+)", joined)
    d.group_current = m.group(1) if m else "explicit"
    if d.group_current == "explicit":
        m = re.search(r"current\s*:\s*new\s*\(\s*((?:\w+\s+)*\w+)\s*,", joined)
        d.group_current_ref = ".".join(m.group(1).split()) if m else None
    for j, t in enumerate(toks):
        if t[1] == "golden" and j + 2 < len(toks) and toks[j + 1][1] == ":":
            # golden : new ( <ref idents> , new TypeShape ( "base" , ...
            k = j + 2
            while k < len(toks) and toks[k][1] != "(":
                k += 1
            ref = []
            k += 1
            while k < len(toks) and toks[k][0] == "ident":
                ref.append(toks[k][1])
                k += 1
            d.group_golden_ref = ".".join(ref)
            base = next((toks[x] for x in range(k, len(toks)) if toks[x][0] in ("str", "vstr")), None)
            d.group_golden_shape = (_string_value(base[0], base[1]),) if base else None
            break


# ------------------------------------------------------------------------------------------------
# Evidence (built from the indexes, tracked so --check needs no artifacts)
# ------------------------------------------------------------------------------------------------
def build_evidence(remap_doc: dict, remap_sha: str, live_index: Path, golden_index: Path, live_shapes: Path,
                   golden_shapes: Path) -> dict:
    from symbol_remap import model

    L = model.load(str(live_index))
    G = model.load(str(golden_index))
    shapes_live = _load_shapes(live_shapes)
    shapes_golden = _load_shapes(golden_shapes)

    # every name a hint could bind on the live build (types: full/runtime/name/obf; members: interop row
    # names, native names, ObfuscatedName attributes)
    live_names: set[str] = set()
    members_by_type: dict[str, set[str]] = defaultdict(set)
    obf_count: Counter = Counter()
    for t in L.types.values():
        live_names.update(x for x in (t.full, t.runtime_full, t.name, t.obf) if x)
        if t.obf and t.asm == "Hex":
            obf_count[t.obf] += 1
        names = members_by_type[t.full]
        for r in t.rows:
            names.add(r.name)
            if r.obf:
                names.add(r.obf)
            if r.native.startswith("fld:"):
                names.add(r.native[4:])
            elif r.native.startswith("tok:") and r.native.count(":") >= 2:
                names.add(r.native.split(":", 2)[2])
        live_names.update(names)

    def chain_names(full: str) -> set[str]:
        out, cur, seen = set(), L.types.get(full), set()
        while cur is not None and cur.full not in seen:
            seen.add(cur.full)
            out |= members_by_type.get(cur.full, set())
            cur = L.types.get(cur.base)
        return out

    type_shapes, golden_type_shapes, obf_unique, member_ok, hazards, golden_route = {}, {}, {}, {}, {}, {}
    for g in remap_doc["groups"]:
        for e in g["entries"]:
            lit = e["golden"]
            if e["status"] == "NOT_IN_GOLDEN":
                hazards[lit] = lit in live_names
                # consumers derive the native name by stripping the interop pointer prefix
                for pfx in PTR_PREFIXES:
                    if lit.startswith(pfx):
                        hazards[lit[len(pfx):]] = lit[len(pfx):] in live_names
                continue
            if e["status"] not in OK:
                continue
            if e["kind"] == "type":
                rt = e.get("liveRuntimeFullName")
                if rt:
                    rows = shapes_live.get(rt, [])
                    type_shapes[rt] = list(rows[0]) if len(rows) == 1 else None
                go = e.get("goldenOwner")
                if go and go in G.types:
                    # does the plugin's type resolution (full name / exact ObfuscatedName in Hex / simple name)
                    # reach the Golden Era type this entry was matched through?
                    gt = G.types[go]
                    golden_route[lit + "	" + go] = lit in (gt.runtime_full, gt.name) or (gt.asm == "Hex" and lit == gt.obf)
                if go:
                    grt = go.replace("/", "+")
                    rows = shapes_golden.get(grt, [])
                    golden_type_shapes[grt] = list(rows[0]) if len(rows) == 1 else None
                if e["live"] and e["live"] != rt and "." not in e["live"]:
                    obf_unique[e["live"]] = obf_count.get(e["live"], 0)
            elif e["kind"] == "member":
                owners = _entry_live_owners(e)
                for o in owners:
                    member_ok[o + "\t" + e["live"]] = e["live"] in chain_names(o)
    return {
        "schema": EVIDENCE_SCHEMA,
        "remapSha256": remap_sha,
        "liveIndexSha256": sha256(live_index),
        "goldenIndexSha256": sha256(golden_index),
        "liveShapeIndexSha256": sha256(live_shapes),
        "goldenShapeIndexSha256": sha256(golden_shapes),
        "liveTypeShapes": dict(sorted(type_shapes.items())),
        "goldenTypeShapes": dict(sorted(golden_type_shapes.items())),
        "liveObfuscatedNameCounts": dict(sorted(obf_unique.items())),
        "memberOnLiveOwner": dict(sorted(member_ok.items())),
        "typeLiteralReachesGoldenType": dict(sorted(golden_route.items())),
        "deadAliasNamesLiveSymbol": dict(sorted(hazards.items())),
    }


def _load_shapes(path: Path) -> dict[str, list[tuple]]:
    out: dict[str, list[tuple]] = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("T\t"):
                continue
            p = line.rstrip("\n").split("\t")
            out[p[2]].append((p[5], int(p[6]), int(p[7])))
    return out


def _entry_live_owners(e: dict) -> list[str]:
    """Live owners (Cecil full names) a member entry was matched on; empty when owner-independent."""
    if e.get("ownerBasis") == "agreeing_owners":
        return sorted({c["live"] for c in e.get("ownerCandidates", []) if c.get("live")})
    return [e["liveOwner"]] if e.get("liveOwner") else []


# ------------------------------------------------------------------------------------------------
# Scope computation
# ------------------------------------------------------------------------------------------------
SENTINEL = None  # a refused position in the emitted live arrays (the runtime substitutes the sentinel)


@dataclass
class Position:
    live: str | None                    # None = refused position
    type_check: tuple | None = None     # (runtimeFullName, base, fields, methods, obfLiteral or "")
    note: str = ""


@dataclass
class Scope:
    decl: Decl
    status: str                         # scoped | refused | identity | const | alias | unscopable
    reason: str = ""
    positions: list[Position] = field(default_factory=list)
    owners: list[str] = field(default_factory=list)   # runtime full names; empty = no owner check
    kind: str = ""
    resolution: str = ""
    dead_alias_refused: int = 0
    dead_alias_kept: int = 0
    min_confidence: float | None = 1.0
    override: str = ""
    split: bool = False                 # override: one golden method became several live methods


def compute_scopes(decls: list[Decl], remap_doc: dict, evidence: dict, overrides: dict) -> list[Scope]:
    groups = {g["symbol"]: g for g in remap_doc["groups"] if g["file"] == "GameSymbols.cs"}
    shapes = evidence["liveTypeShapes"]
    obf_counts = evidence["liveObfuscatedNameCounts"]
    member_ok = evidence["memberOnLiveOwner"]
    hazards = evidence["deadAliasNamesLiveSymbol"]
    golden_route = evidence["typeLiteralReachesGoldenType"]
    ov = overrides.get("symbols", {})
    # arrays that are the explicit `current:` scope of a TypeHintGroup already hold live names
    current_refs = {(d.group_current_ref or "").split(".")[-1] for d in decls
                    if d.decl_type == "TypeHintGroup" and d.group_current_ref}
    out: list[Scope] = []
    for d in decls:
        if d.decl_type == "TypeHintGroup":
            continue
        if d.name in current_refs:
            continue
        if re.search(r"Ids?$", d.name) and d.decl_type in ("string[]", "const"):
            continue  # symbol ids, not hints (the harvester skips them too)
        if d.decl_type == "const":
            if d.elements:
                g = groups.get(d.symbol)
                s = Scope(d, "const", "const string: a compile-time constant cannot be rewritten per build",
                          kind=g["kind"] if g else "", resolution=g["resolution"] if g else "not-in-remap")
                out.append(s)
            continue
        if d.alias_of:
            out.append(Scope(d, "alias", f"aliases {d.alias_of}; shares that declaration's array/scope"))
            continue
        if d.decl_type not in SCOPABLE_TYPES:
            continue
        g = groups.get(d.symbol)
        if not d.literal_only:
            if g is not None:
                out.append(Scope(d, "refused", "initializer is not literal-only; positions cannot be rewritten",
                                 kind=g["kind"], resolution=g["resolution"]))
            continue
        hints = d.hints
        if not hints:
            continue
        if g is None:
            ident_like = [h for h in hints if harvest.IDENT.match(h) and not h.isdigit()]
            if ident_like and d.symbol in ov:
                # Declared after the remap was generated (e.g. a hard-coded name routed through GameSymbols):
                # the remap has no opinion, so only a reviewed override with its own evidence can scope it.
                s = Scope(d, "", resolution="not-in-remap")
                _apply_override(s, ov[d.symbol], hints)
                out.append(s)
                continue
            if ident_like:
                out.append(Scope(d, "refused", "declaration is not in the remap (added or renamed after it was "
                                              "generated); regenerate the remap", resolution="not-in-remap"))
            continue
        s = Scope(d, "", kind=g["kind"], resolution=g["resolution"])
        if g["literals"] != [h for h in hints if harvest.IDENT.match(h) and not h.isdigit()]:
            s.status, s.reason = "refused", "hint literals changed since the remap was generated; regenerate the remap"
            out.append(s)
            continue
        if d.symbol in ov:
            _apply_override(s, ov[d.symbol], hints)
            out.append(s)
            continue
        if g["kind"] == "none":
            s.status, s.reason = "identity", "remap kind 'none': the literals are not symbol hints"
            out.append(s)
            continue
        if g["resolution"] in ("partially_mapped", "unmapped"):
            reasons = sorted({u["reason"] for u in g.get("unmapped", [])})
            s.status = "refused"
            s.reason = f"remap {g['resolution']}: " + "; ".join(reasons)
            out.append(s)
            continue
        entries = {e["golden"]: e for e in g["entries"]}
        mapped = {k: v["live"] for k, v in entries.items() if v["status"] in OK}
        problems = []
        owners: set[str] = set()
        for h in hints:
            e = entries.get(h)
            if e is None:           # skipped literal (not identifier-like): keep verbatim
                s.positions.append(Position(h, note="non-hint literal kept"))
                continue
            st = e["status"]
            pfx = next((x for x in PTR_PREFIXES if h.startswith(x)), None)
            if st == "NOT_IN_GOLDEN" and pfx and h[len(pfx):] in mapped:
                # NativeFieldInfoPtr_<native>: the pointer spelling of a native name mapped in this group
                s.positions.append(Position(pfx + mapped[h[len(pfx):]], note="pointer spelling of a mapped native name"))
                continue
            if st == "NOT_IN_GOLDEN":
                if hazards.get(h, True) or (pfx and hazards.get(h[len(pfx):], True)):
                    s.positions.append(Position(SENTINEL, note="dead alias names a live symbol"))
                    s.dead_alias_refused += 1
                else:
                    s.positions.append(Position(h, note="dead alias kept (names nothing on either build)"))
                    s.dead_alias_kept += 1
                continue
            if st not in OK:
                problems.append(f"{h}: {st} {e.get('reason', '')}".strip())
                continue
            s.min_confidence = min(s.min_confidence, float(e.get("confidence", 0.0)))
            if e["kind"] == "type":
                rt = e.get("liveRuntimeFullName")
                go = e.get("goldenOwner")
                if go and not golden_route.get(h + "	" + go, False):
                    # the remap matched it through a spelling the plugin never resolves (e.g. a nested type's
                    # bare native name): it binds nothing on Golden Era, so it must bind nothing here either
                    s.positions.append(Position(SENTINEL, note="type literal unreachable on Golden Era"))
                    s.dead_alias_refused += 1
                    continue
                if not rt and st == "UNCHANGED" and REAL_TYPE_NAME.match(h) and not GENERATED.search(h):
                    s.positions.append(Position(h, note="unchanged real type name (several same-named types)"))
                    continue
                shp = shapes.get(rt) if rt else None
                if not rt or not shp:
                    problems.append(f"{h}: live type {rt!r} has no unique shape in the live interop")
                    continue
                obf = ""
                simple = re.split(r"[.+]", rt)[-1]
                if e["live"] not in (rt, simple):
                    obf = e["live"]   # ObfuscatedName form: must name exactly one live Hex type
                    if obf_counts.get(obf, 0) != 1:
                        problems.append(f"{h}: live obfuscated name {obf!r} names {obf_counts.get(obf, 0)} Hex types")
                        continue
                s.positions.append(Position(e["live"], type_check=(rt, shp[0], shp[1], shp[2], obf)))
            else:
                los = _entry_live_owners(e)
                if not los:
                    problems.append(f"{h}: member entry carries no live owner")
                    continue
                bad = [o for o in los if not member_ok.get(o + "\t" + e["live"], False)]
                if bad:
                    problems.append(f"{h}: live name {e['live']!r} not found on live owner {bad[0]}")
                    continue
                if e.get("ownerBasis") != "agreeing_owners":
                    owners.update(o.replace("/", "+") for o in los)
                s.positions.append(Position(e["live"]))
        if problems:
            s.status, s.reason, s.positions = "refused", "unverified: " + "; ".join(problems), []
        elif all(p.live is None for p in s.positions):
            s.status, s.reason = "refused", "every literal is a dead alias that names a live symbol"
        elif all(p.note in ("dead alias kept (names nothing on either build)", "non-hint literal kept")
                 for p in s.positions):
            s.status, s.reason = "identity", "no literal binds on Golden Era and none names a live symbol"
        else:
            s.status = "scoped"
            s.owners = sorted(owners) if g["kind"] != "type" else []
        out.append(s)
    return out


def _apply_override(s: Scope, spec: dict, hints: list[str]) -> None:
    s.override = spec.get("evidence", "")
    # Manual semantic pins bypass the matcher; do not report its default score as evidence.
    s.min_confidence = None
    if spec.get("status") == "refused":
        s.status, s.reason = "refused", "override: " + spec.get("reason", "")
        return
    live = spec.get("live")
    if spec.get("split"):
        # Signature changed and the method was split: each live name is one method (never an alias), so the count
        # may differ. Only a MethodSymbol can carry that, it needs its owners and its evidence, and the runtime
        # (GameSymbolScope.MethodSplit) still hash-pins the golden literals.
        if s.decl.decl_type != "MethodSymbol":
            s.status, s.reason = "refused", "override malformed: 'split' is only valid on a MethodSymbol"
            return
        if (not isinstance(live, list) or not live or len(set(live)) != len(live)
                or not all(isinstance(v, str) and v for v in live)):
            s.status, s.reason = "refused", "override malformed: a split 'live' must list distinct method names"
            return
        if not spec.get("owners") or not spec.get("evidence"):
            s.status, s.reason = "refused", "override malformed: a split needs 'owners' and 'evidence'"
            return
    elif not isinstance(live, list) or len(live) != len(hints):
        s.status, s.reason = "refused", "override malformed: 'live' must list one value per hint literal"
        return
    if spec.get("goldenLiterals") != hints:
        s.status, s.reason = "refused", "override stale: its goldenLiterals differ from the declaration"
        return
    if spec.get("split"):
        s.split = True
        s.positions = [Position(v, note="override split") for v in live]
        s.owners = sorted(spec["owners"])
        s.status = "scoped"
        return
    checks = spec.get("typeChecks") or [None] * len(live)
    s.positions = [Position(v, type_check=tuple(c) if c else None, note="override") for v, c in zip(live, checks)]
    s.owners = sorted(spec.get("owners", []))
    s.status = "scoped"


# ------------------------------------------------------------------------------------------------
# TypeGroups `current: TypeHintScope.Generated`
# ------------------------------------------------------------------------------------------------
@dataclass
class GroupScope:
    decl: Decl
    status: str
    reason: str = ""
    live_hint: str = ""
    shape: tuple | None = None


def compute_type_groups(decls: list[Decl], scopes: list[Scope], remap_doc: dict, evidence: dict,
                        golden_shapes_by_decl: dict) -> list[GroupScope]:
    by_symbol = {s.decl.symbol: s for s in scopes}
    groups = {g["symbol"]: g for g in remap_doc["groups"] if g["file"] == "GameSymbols.cs"}
    out = []
    for d in decls:
        if d.decl_type != "TypeHintGroup" or d.group_current != "Generated":
            continue
        ref = d.group_golden_ref or ""
        ref = ref[len("GameSymbols."):] if ref.startswith("GameSymbols.") else ref
        s = by_symbol.get(ref)
        if s is None or s.status != "scoped":
            out.append(GroupScope(d, "refused", f"golden hints {ref} are not scoped for the current build"
                                  + (f" ({s.status}: {s.reason})" if s else "")))
            continue
        pick = golden_shapes_by_decl.get(d.symbol)
        g = groups.get(ref)
        if pick is None or g is None:
            out.append(GroupScope(d, "refused", "no golden pick recorded for this group"))
            continue
        # the golden literal whose Golden Era type has the group's pinned golden shape
        cands = []
        for pos, h in zip(s.positions, [h for h in s.decl.hints]):
            e = next((x for x in g["entries"] if x["golden"] == h), None)
            if e is None or pos.type_check is None:
                continue
            go = (e.get("goldenOwner") or "").replace("/", "+")
            gs = evidence["goldenTypeShapes"].get(go)
            if gs and tuple(gs) == tuple(pick):
                cands.append(pos)
        live_types = {c.type_check[0] for c in cands}
        if len(live_types) != 1:
            out.append(GroupScope(d, "refused", f"golden shape {pick} is reached by {len(live_types)} live type(s)"))
            continue
        c = cands[0]
        out.append(GroupScope(d, "scoped", live_hint=c.type_check[0], shape=c.type_check[1:4]))
    return out


# ------------------------------------------------------------------------------------------------
# Emission
# ------------------------------------------------------------------------------------------------
def cs_str(v: str | None) -> str:
    if v is None:
        return "null"
    v = v.replace(chr(10), " ").replace(chr(13), " ")
    return '"' + v.replace(chr(92), chr(92) * 2).replace('"', chr(92) + '"') + '"'


def cs_arr(vals) -> str:
    return "new string[] { " + ", ".join(cs_str(v) for v in vals) + " }"


def emit(scopes: list[Scope], gscopes: list[GroupScope], remap_sha: str, evidence_sha: str, ga_sha: str) -> str:
    by_cls: dict[str, list] = defaultdict(list)
    for s in scopes:
        if s.status in ("scoped", "refused"):
            by_cls[s.decl.cls].append(s)
    groups_scoped = [g for g in gscopes if g.status == "scoped"]
    lines = [
        "// <auto-generated>",
        "// Generated by tools/port_current/generate_current_symbol_scopes.py. Do not edit by hand:",
        "// regenerate; tools/validate_game_symbols_hint_contract.py (build-wired) fails when this file is stale.",
        f"// Source remap: tools/port_current/remap/game_symbols_remap_{BUILD_ID}.json sha256 {remap_sha}",
        f"// Evidence:     tools/port_current/remap/current_scope_evidence_{BUILD_ID}.json sha256 {evidence_sha}",
        "// On Golden Era and unknown builds every constructor below returns before touching a field.",
        "// </auto-generated>",
        "#nullable disable",
        "namespace OfflineUnlockMod;",
        "",
        "internal static partial class GameSymbols",
        "{",
        "\tinternal static class CurrentScopes",
        "\t{",
        f"\t\tinternal const string BuildId = \"{BUILD_ID}\";",
        f"\t\tinternal const string RemapSha256 = \"{remap_sha}\";",
        "\t\t// GameBuild selects GameBuildKind.Current by this hash (the remap target), so the build the plugin",
        "\t\t// rewrites for can never differ from the build these scopes were generated for.",
        f"\t\tinternal const string GameAssemblySha256 = \"{ga_sha}\";",
        f"\t\tinternal const int Scoped = {sum(1 for s in scopes if s.status == 'scoped')};",
        f"\t\tinternal const int Refused = {sum(1 for s in scopes if s.status == 'refused')};",
        f"\t\tinternal const int TypeGroupsScoped = {len(groups_scoped)};",
        "\t}",
    ]
    for cls in sorted(by_cls):
        lines += ["", f"\tinternal static partial class {cls}", "\t{", f"\t\tstatic {cls}()", "\t\t{",
                  "\t\t\tif (!GameSymbolScope.RewriteForCurrentBuild)", "\t\t\t\treturn;"]
        for s in sorted(by_cls[cls], key=lambda x: x.decl.line):
            lines.append(_emit_one(s))
        lines += ["\t\t}", "\t}"]
    if groups_scoped:
        lines += ["", "\tinternal static partial class TypeGroups", "\t{", "\t\tstatic TypeGroups()", "\t\t{",
                  "\t\t\tif (!GameSymbolScope.RewriteForCurrentBuild)", "\t\t\t\treturn;"]
        for g in sorted(groups_scoped, key=lambda x: x.decl.line):
            b, f, m = g.shape
            lines.append(f"\t\t\t{g.decl.name} = GameSymbolScope.WithCurrent({g.decl.name}, "
                         f"new TypeHintScope(new string[] {{ {cs_str(g.live_hint)} }}, new TypeShape({cs_str(b)}, {f}, {m})));")
        lines += ["\t\t}", "\t}"]
    lines += ["}", ""]
    return "\n".join(lines)


def _emit_one(s: Scope) -> str:
    d = s.decl
    sym = cs_str(d.symbol)
    h = f"0x{fnv1a32(d.hints):08X}u"
    n = d.name
    if s.status == "refused":
        reason = cs_str(s.reason[:400])
        fn = {"string": "RefuseOne", "string[]": "Refuse", "MethodSymbol": "RefuseMethod", "FieldSymbol": "RefuseField",
              "MethodSymbol[]": "RefuseMethods", "FieldSymbol[]": "RefuseFields", "tuple[]": "RefuseNamedCounts"}[d.decl_type]
        return f"\t\t\t{n} = GameSymbolScope.{fn}({sym}, {n}, {h}, {reason});"
    live = [p.live for p in s.positions]
    owners = cs_str(";".join(s.owners)) if s.owners else "null"
    if d.decl_type == "string":
        if s.positions[0].type_check:
            check = cs_str("|".join(str(x) for x in s.positions[0].type_check))
            return f"\t\t\t{n} = GameSymbolScope.Type({sym}, {n}, {h}, {cs_str(live[0])}, {check});"
        return f"\t\t\t{n} = GameSymbolScope.Member({sym}, {n}, {h}, {cs_str(live[0])}, {owners});"
    if d.decl_type == "string[]":
        if any(p.type_check for p in s.positions):
            checks = "new string[] { " + ", ".join(
                cs_str("|".join(str(x) for x in p.type_check)) if p.type_check else "null" for p in s.positions) + " }"
            return f"\t\t\t{n} = GameSymbolScope.Types({sym}, {n}, {h}, {cs_arr(live)}, {checks});"
        return f"\t\t\t{n} = GameSymbolScope.Members({sym}, {n}, {h}, {cs_arr(live)}, {owners});"
    if d.decl_type == "MethodSymbol":
        fn = "MethodSplit" if s.split else "Method"
        return f"\t\t\t{n} = GameSymbolScope.{fn}({sym}, {n}, {h}, {cs_arr(live)}, {owners});"
    if d.decl_type == "FieldSymbol":
        return f"\t\t\t{n} = GameSymbolScope.Field({sym}, {n}, {h}, {cs_arr(live)}, {owners});"
    # arrays of symbols: split the flat positions back into elements
    parts, k = [], 0
    for e in d.elements:
        parts.append(cs_arr(live[k:k + len(e.hints)]))
        k += len(e.hints)
    nested = "new string[][] { " + ", ".join(parts) + " }"
    fn = {"MethodSymbol[]": "Methods", "FieldSymbol[]": "Fields", "tuple[]": "NamedCounts"}[d.decl_type]
    if d.decl_type == "tuple[]":
        return f"\t\t\t{n} = GameSymbolScope.{fn}({sym}, {n}, {h}, {cs_arr(live)}, {owners});"
    return f"\t\t\t{n} = GameSymbolScope.{fn}({sym}, {n}, {h}, {nested}, {owners});"


def report_doc(scopes: list[Scope], gscopes: list[GroupScope], remap_doc: dict, remap_sha: str,
               evidence_sha: str) -> dict:
    counts = Counter(s.status for s in scopes)
    by_res = Counter((s.resolution, s.status) for s in scopes)
    inline = [g for g in remap_doc["groups"] if "@" in g["symbol"] or g["file"] != "GameSymbols.cs"]
    return {
        "schema": SCHEMA,
        "buildId": BUILD_ID,
        "remapSha256": remap_sha,
        "evidenceSha256": evidence_sha,
        "summary": {
            "declarations": dict(sorted(counts.items())),
            "byRemapResolution": {f"{r}:{st}": c for (r, st), c in sorted(by_res.items())},
            "typeGroupsGenerated": dict(sorted(Counter(g.status for g in gscopes).items())),
            "deadAliasPositionsRefused": sum(s.dead_alias_refused for s in scopes),
            "deadAliasPositionsKept": sum(s.dead_alias_kept for s in scopes),
            "scopedWithOwnerCheck": sum(1 for s in scopes if s.status == "scoped" and s.owners),
            "inlineGroupsNotScopable": len(inline),
        },
        "declarations": [
            {"symbol": s.decl.symbol, "line": s.decl.line, "declType": s.decl.decl_type, "status": s.status,
             "remapKind": s.kind, "remapResolution": s.resolution, "reason": s.reason,
             "minConfidence": round(s.min_confidence, 4)
                 if s.status == "scoped" and s.min_confidence is not None else None,
             "owners": s.owners, "live": [p.live for p in s.positions] if s.status == "scoped" else None,
             "override": s.override or None, **({"split": True} if s.split else {})}
            for s in sorted(scopes, key=lambda x: x.decl.line)
        ],
        "typeGroups": [
            {"symbol": g.decl.symbol, "status": g.status, "reason": g.reason, "liveHint": g.live_hint or None,
             "shape": list(g.shape) if g.shape else None}
            for g in sorted(gscopes, key=lambda x: x.decl.line)
        ],
        "inlineGroups": [
            {"file": g["file"], "symbol": g["symbol"], "kind": g["kind"], "resolution": g["resolution"]}
            for g in inline
        ],
    }


# ------------------------------------------------------------------------------------------------
# Golden pick shapes for TypeGroups (from GameSymbols.cs itself)
# ------------------------------------------------------------------------------------------------
TG_SHAPE = re.compile(
    r"internal\s+static\s+readonly\s+TypeHintGroup\s+(\w+)\s*=\s*new\s*\(.*?golden\s*:\s*new\s*\(\s*[\w.]+\s*,\s*"
    r"new\s+TypeShape\s*\(\s*\"([^\"]*)\"\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", re.S)


def golden_group_shapes(text: str) -> dict[str, tuple]:
    return {f"TypeGroups.{m.group(1)}": (m.group(2), int(m.group(3)), int(m.group(4))) for m in TG_SHAPE.finditer(text)}


# ------------------------------------------------------------------------------------------------
def generate(remap_path: Path, evidence_path: Path, overrides_path: Path, symbols_path: Path):
    remap_doc = json.loads(remap_path.read_text(encoding="utf-8"))
    remap_sha = text_sha256(remap_path)
    if remap_doc.get("target", {}).get("steamBuildId") not in (BUILD_ID, int(BUILD_ID)):
        sys.exit(f"generate_current_symbol_scopes: REFUSED: remap target build is not {BUILD_ID}")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("remapSha256") != remap_sha:
        sys.exit("generate_current_symbol_scopes: STALE evidence: it was built for another remap; "
                 "rerun with --evidence (needs artifacts/port_current indexes)")
    overrides = {"symbols": {}}
    if overrides_path.is_file():
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
        if overrides.get("schema") != OVERRIDES_SCHEMA:
            sys.exit(f"generate_current_symbol_scopes: REFUSED: {overrides_path} has schema {overrides.get('schema')!r}")
    text = symbols_path.read_text(encoding="utf-8-sig")
    decls = parse_game_symbols(text)
    scopes = compute_scopes(decls, remap_doc, evidence, overrides)
    gscopes = compute_type_groups(decls, scopes, remap_doc, evidence, golden_group_shapes(text))
    evidence_sha = text_sha256(evidence_path)
    ga_sha = str(remap_doc.get("target", {}).get("gameAssemblySha256", "")).upper()
    if not re.fullmatch(r"[0-9A-F]{64}", ga_sha):
        sys.exit("generate_current_symbol_scopes: REFUSED: remap target carries no GameAssembly sha256")
    cs = emit(scopes, gscopes, remap_sha, evidence_sha, ga_sha)
    rep = report_doc(scopes, gscopes, remap_doc, remap_sha, evidence_sha)
    return cs, json.dumps(rep, indent=1, ensure_ascii=False) + "\n", rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remap", type=Path, default=REMAP)
    ap.add_argument("--evidence-file", type=Path, default=EVIDENCE)
    ap.add_argument("--overrides", type=Path, default=OVERRIDES)
    ap.add_argument("--game-symbols", type=Path, default=GAME_SYMBOLS)
    ap.add_argument("--out-cs", type=Path, default=GENERATED_CS)
    ap.add_argument("--out-report", type=Path, default=REPORT)
    ap.add_argument("--check", action="store_true", help="fail when the checked-in outputs are stale")
    ap.add_argument("--evidence", action="store_true", help="rebuild the evidence file from the indexes first")
    ap.add_argument("--live-index", type=Path, default=REPO / f"artifacts/port_current/idx2_live_{BUILD_ID}/port_index.tsv")
    ap.add_argument("--golden-index", type=Path, default=REPO / "artifacts/port_current/idx2_golden/port_index.tsv")
    ap.add_argument("--live-shapes", type=Path)
    ap.add_argument("--golden-shapes", type=Path)
    a = ap.parse_args(argv)

    if a.evidence:
        if not (a.live_shapes and a.golden_shapes):
            ap.error("--evidence needs --live-shapes and --golden-shapes (tools/port_current/interop_shape_index TSVs)")
        doc = json.loads(a.remap.read_text(encoding="utf-8"))
        ev = build_evidence(doc, text_sha256(a.remap), a.live_index, a.golden_index, a.live_shapes, a.golden_shapes)
        a.evidence_file.write_text(json.dumps(ev, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {a.evidence_file}")

    cs, rep_text, rep = generate(a.remap, a.evidence_file, a.overrides, a.game_symbols)
    if a.check:
        stale = []
        for path, want in ((a.out_cs, cs), (a.out_report, rep_text)):
            have = path.read_text(encoding="utf-8") if path.is_file() else None
            if have != want:
                stale.append(str(path))
        if stale:
            print("STALE current symbol scopes: " + ", ".join(stale))
            print("  regenerate: python tools/port_current/generate_current_symbol_scopes.py")
            return 1
        print(f"FRESH current symbol scopes: {json.dumps(rep['summary']['declarations'])}")
        return 0
    a.out_cs.write_text(cs, encoding="utf-8", newline="\n")
    a.out_report.write_text(rep_text, encoding="utf-8", newline="\n")
    print(f"wrote {a.out_cs}")
    print(f"wrote {a.out_report}")
    print(json.dumps(rep["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
