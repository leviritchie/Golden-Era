#!/usr/bin/env python3
"""Carry scoped current-build symbols across a Steam hotfix by in-order native-name succession.

The game's obfuscator names types, methods and fields sequentially (bijective base 26: a..z, aa..zz, aaa..). A hotfix
that adds a few types or members shifts every later name by a small constant, so within a neighbourhood the old->new
offset is the same for every member: 25509697 -> 25672315 shifted methods by +10..+43 and types by +3/+4. The offset
is measured on *anchors*: obfuscated members whose (masked) signature is unique on a high-confidence mapped owner on
both builds. A member the old build bound by role keeps its role in its successor, including when Il2CppInterop
renamed it (a real method that gained or lost `_PDM_`, or an ordinal that flipped). Random-named obfuscator decoy copies
(`_PDM_` duplicates with out-of-sequence names) do not shift and are never predicted; positions that bound them carry
only when the drift remap maps them.

`carry` takes the declarations that the previous build scoped but the new golden->new remap refuses, and writes an
override entry for each one whose every bound position resolves uniquely:

  * owner: drift type map (old live -> new live) when its native agrees with the shifted native, else the unique
    type whose native is the shifted native and whose field/method counts are within the old shape's tolerance;
  * member: the shifted native on the new owner, same row kind (method token / field) and masked signature, exactly
    one candidate across the neighbouring offsets;
  * real (unobfuscated) names: the same name on the new owner;
  * type literals: the type at the shifted native, cross-checked against the drift type map when it maps.

Anything else is listed for hand review; nothing is guessed. Inputs are read only.

  python tools/port_current/native_name_shift.py carry \\
      --old-idx artifacts/port_current/idx2_live_25509697 --new-idx artifacts/port_current/idx2_live_25672315 \\
      --type-map artifacts/port_current/drift_25509697_to_25672315/type_map_25672315.json \\
      --old-scopes tools/port_current/remap/current_scopes_25509697.json \\
      --new-scopes tools/port_current/remap/current_scopes_25672315.json \\
      --remap tools/port_current/remap/game_symbols_remap_25672315.json \\
      --new-shapes artifacts/port_current/p2/index_cache/shape_index_80c9ae5d78c3de78a99ebf09.tsv \\
      --overrides tools/port_current/remap/current_scope_overrides_25672315.json \\
      --report artifacts/port_current/native_shift_carry_25672315.json

Proof tier of the output: generated artifact (static index evidence), never runtime.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import re
import sys
from pathlib import Path

OBF = re.compile(r"^[a-z]{1,4}$")
MASK = re.compile(r"Object(?:Public|Private|Protected|Internal|N)\w*Unique|Interface\w*Unique|\b[a-z]{2,4}\b")
ANCHOR_CONFIDENCE = 0.95
DECOY = object()


def n2i(s: str) -> int:
    v = 0
    for ch in s:
        v = v * 26 + (ord(ch) - 96)
    return v


def i2n(v: int) -> str:
    s = ""
    while v > 0:
        v, r = divmod(v - 1, 26)
        s = chr(97 + r) + s
    return s


class Member:
    __slots__ = ("kind", "name", "native", "sig")

    def __init__(self, kind, name, native, sig):
        self.kind, self.name, self.native, self.sig = kind, name, native, sig


class Index:
    def __init__(self, idx_dir: Path):
        self.types: dict[str, dict] = {}
        self.by_native: dict[str, list[str]] = collections.defaultdict(list)
        self.members: dict[str, list[Member]] = collections.defaultdict(list)
        with (idx_dir / "port_index.tsv").open(encoding="utf-8") as fh:
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if p[0] == "T":
                    nat = p[4].split("+")[-1] if p[4] else ""
                    self.types[p[2]] = {"name": p[3], "native": nat, "nativePath": p[4], "base": p[7],
                                        "fields": int(p[11]), "methods": int(p[12])}
                    if nat:
                        self.by_native[nat].append(p[2])
                elif p[0] in ("M", "F", "P"):
                    raw = p[4]
                    if raw.startswith("tok:"):
                        parts = raw.split(":")
                        if len(parts) < 3:
                            continue
                        kind, native = "m", parts[2]
                    elif raw.startswith("fld:"):
                        kind, native = "f", raw[4:]
                    else:
                        kind, native = "plain", p[3]
                    if p[0] == "F" and p[3].startswith("NativeMethodInfoPtr_"):
                        continue
                    self.members[p[2]].append(Member(kind, p[3], native, MASK.sub("O", p[7])))

    def find(self, owner: str, literal: str) -> list[Member]:
        return [m for m in self.members.get(owner, []) if m.name == literal or m.native == literal]


def field_core(native: str) -> str:
    m = re.match(r"^<([^>]+)>k__BackingField$", native)
    return m.group(1) if m else native


class Shift:
    """Sorted (old native int, offset) anchors for one name family."""

    def __init__(self, pairs):
        self.anchors = sorted(set(pairs))
        self.keys = [a[0] for a in self.anchors]

    def offsets(self, native: str) -> list[int]:
        x = n2i(native)
        i = bisect.bisect_left(self.keys, x)
        if i < len(self.anchors) and self.anchors[i][0] == x:
            return [self.anchors[i][1]]
        near = set()
        if i > 0:
            near.add(self.anchors[i - 1][1])
        if i < len(self.anchors):
            near.add(self.anchors[i][1])
        # between two anchors with different offsets the insertion point is unknown: every offset in between
        return list(range(min(near), max(near) + 1)) if near and max(near) - min(near) <= 4 else sorted(near)


def build_shifts(O: Index, N: Index, tmap: dict) -> tuple[Shift, Shift, Shift]:
    mpairs, fpairs, tpairs = [], [], []
    for go, v in tmap.items():
        if not v.get("live") or v.get("confidence", 0) < ANCHOR_CONFIDENCE:
            continue
        ot, nt = O.types.get(go), N.types.get(v["live"])
        if ot and nt and OBF.match(ot["native"]) and OBF.match(nt["native"]):
            tpairs.append((n2i(ot["native"]), n2i(nt["native"]) - n2i(ot["native"])))
        for kind, out in (("m", mpairs), ("f", fpairs)):
            om = [m for m in O.members.get(go, []) if m.kind == kind and OBF.match(field_core(m.native))]
            nm = [m for m in N.members.get(v["live"], []) if m.kind == kind and OBF.match(field_core(m.native))]
            key = (lambda m: m.sig) if kind == "m" else (lambda m: (m.sig, m.name.startswith(("get_", "set_"))))
            if kind == "f":
                om = [m for m in om if m.name.startswith("NativeFieldInfoPtr_")] or om
                nm = [m for m in nm if m.name.startswith("NativeFieldInfoPtr_")] or nm
            oc, nc = collections.Counter(map(key, om)), collections.Counter(map(key, nm))
            for m in om:
                if oc[key(m)] == 1 and nc[key(m)] == 1:
                    n = next(x for x in nm if key(x) == key(m))
                    a, b = field_core(m.native), field_core(n.native)
                    out.append((n2i(a), n2i(b) - n2i(a)))
    return Shift(mpairs), Shift(fpairs), Shift(tpairs)


def carry(a) -> int:
    O, N = Index(a.old_idx), Index(a.new_idx)
    tmap = {k: v for k, v in json.loads(a.type_map.read_text(encoding="utf-8")).items()}
    ms, fs, ts = build_shifts(O, N, tmap)
    old_sc = {d["symbol"]: d for d in json.loads(a.old_scopes.read_text(encoding="utf-8"))["declarations"]}
    new_sc = {d["symbol"]: d for d in json.loads(a.new_scopes.read_text(encoding="utf-8"))["declarations"]}
    remap_doc = json.loads(a.remap.read_text(encoding="utf-8"))
    groups = {g["symbol"]: g for g in remap_doc["groups"] if g["file"] == "GameSymbols.cs"}
    remap_literals = remap_doc["literals"]
    shapes = {}
    with a.new_shapes.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("T\t"):
                p = line.rstrip("\n").split("\t")
                shapes[p[3]] = [p[3], p[5], int(p[6]), int(p[7]), p[4]]
    ov = json.loads(a.overrides.read_text(encoding="utf-8"))
    old_build = a.old_scopes.stem.split("_")[-1]

    def map_type(old_full: str):
        """old interop full name ('/' nested) -> (new full, basis) or (None, reason)."""
        ot = O.types.get(old_full)
        if ot is None:
            return None, "owner not in the old index"
        tm = tmap.get(old_full) or {}
        if not OBF.match(ot["native"]):
            nt = tm.get("live") if tm.get("live") in N.types else (old_full if old_full in N.types else None)
            return (nt, "stable/real-named type") if nt else (None, "real-named type missing on the new build")
        preds = []
        for off in ts.offsets(ot["native"]):
            nat = i2n(n2i(ot["native"]) + off)
            for full in N.by_native.get(nat, []):
                # nested types: the parent must map too (same parent chain shape)
                if ("/" in full) != ("/" in old_full):
                    continue
                if "/" in old_full:
                    po, _ = old_full.rsplit("/", 1)
                    pn, _ = full.rsplit("/", 1)
                    pm, _r = map_type(po)
                    if pm != pn:
                        continue
                preds.append(full)
        preds = sorted(set(preds))
        if len(preds) > 1:
            # tie-break 1: the successor that kept the old interop short name
            same = [f for f in preds if N.types[f]["name"] == ot["name"]]
            # tie-break 2: the drift type matcher's best candidate (mapped or ambiguous)
            best = tm.get("live") or ((tm.get("candidates") or [{}])[0].get("live"))
            if len(same) == 1:
                preds = same
            elif best in preds:
                preds = [best]
        if tm.get("live"):
            if tm["live"] in preds:
                return tm["live"], f"type map {tm.get('method')} {tm.get('confidence')} and native {ot['native']} -> {N.types[tm['live']]['native']}"
            off = n2i(N.types[tm["live"]]["native"]) - n2i(ot["native"]) if tm["live"] in N.types and OBF.match(N.types[tm["live"]]["native"]) else None
            near = ts.offsets(ot["native"])
            if off is not None and tm.get("confidence", 0) >= 0.85 and min(near) - 2 <= off <= max(near) + 2:
                return tm["live"], (f"type map {tm.get('method')} {tm.get('confidence')}; native {ot['native']} -> "
                                    f"{N.types[tm['live']]['native']} (+{off}, local type insertion next to offsets {near})")
            return None, f"type map {tm['live']} disagrees with the native succession {preds}"
        if len(preds) == 1:
            nt = N.types[preds[0]]
            if abs(nt["fields"] - ot["fields"]) <= max(3, ot["fields"] // 4) and abs(nt["methods"] - ot["methods"]) <= max(4, ot["methods"] // 3):
                return preds[0], f"native succession {ot['native']} -> {nt['native']} (type map unmapped; shape {ot['fields']}/{ot['methods']} -> {nt['fields']}/{nt['methods']})"
            return None, f"native successor {preds[0]} shape differs ({ot['fields']}/{ot['methods']} -> {nt['fields']}/{nt['methods']})"
        return None, f"native succession not unique: {preds}"

    def map_member(oo: str, no: str, lit: str):
        hits = O.find(oo, lit)
        if not hits:
            return None, f"{lit} not on {oo}"
        m = hits[0]
        core = field_core(m.native)
        if m.kind == "plain" or not OBF.match(core):
            same = [x for x in N.members.get(no, []) if x.name == lit]
            return (lit, "real name kept") if same else (None, f"real-named {lit} missing on {no}")
        shift = ms if m.kind == "m" else fs
        cands = []
        for off in shift.offsets(core):
            ncore = i2n(n2i(core) + off)
            nnat = m.native.replace(core, ncore) if m.kind == "f" else ncore
            if lit == m.native:
                rows = [x for x in N.members.get(no, []) if x.native == nnat and x.kind == m.kind]
                if rows and (m.kind == "f" or any(x.sig == m.sig for x in rows)):
                    cands.append((nnat, off))
            else:
                want = lit.replace(core, ncore) if core in lit else None
                rows = [x for x in N.members.get(no, []) if x.native == nnat and x.kind == m.kind and x.sig == m.sig
                        and (want is None or x.name == want)]
                if m.kind == "m":
                    rows = [x for x in rows if x.name.startswith(lit.split("_")[0])]
                if len(rows) == 1:
                    cands.append((rows[0].name, off))
        cands = sorted(set(cands))
        if len(cands) == 1:
            return cands[0][0], f"{core}+{cands[0][1]}"
        if not cands and m.kind == "m":
            succ = {i2n(n2i(core) + off) for off in shift.offsets(core)}
            if not any(x.native in succ for x in N.members.get(no, [])):
                # No successor name exists on the new owner: the old binding was an out-of-sequence (random-named)
                # obfuscator copy. It has no identity across builds and is left unbound.
                return DECOY, f"{lit} ({core}) is an out-of-sequence copy with no successor on {no}; unbound"
        return None, f"{lit} ({core}): succession candidates {cands} for offsets {shift.offsets(core)}"

    results, review = {}, {}
    for sym, od in old_sc.items():
        nd = new_sc.get(sym)
        if od["status"] != "scoped" or nd is None or nd["status"] == "scoped" or sym in ov["symbols"]:
            continue
        g = groups.get(sym)
        if g is None:
            review[sym] = ["no remap group"]
            continue
        problems, live, notes, checks = [], [], [], []
        decoys = 0
        owners_old = [o.replace("+", "/") for o in od.get("owners") or []]
        owners_new = []
        for o in owners_old:
            nt, why = map_type(o)
            if nt is None:
                problems.append(f"owner {o}: {why}")
            owners_new.append(nt)
            notes.append(f"owner {o} -> {nt}: {why}")
        is_type = od.get("remapKind") == "type"
        for pos, lit in enumerate(od.get("live") or []):
            if lit is None:
                live.append(None)
                checks.append(None)
                continue
            if is_type:
                cand = [f for f, t in O.types.items() if f == lit.replace("+", "/") or t["native"] == lit or t["name"] == lit]
                if len(cand) != 1:
                    problems.append(f"pos {pos} {lit}: {len(cand)} old types")
                    live.append(None); checks.append(None)
                    continue
                nt, why = map_type(cand[0])
                if nt is None:
                    problems.append(f"pos {pos} {lit}: {why}")
                    live.append(None); checks.append(None)
                    continue
                ot = O.types[cand[0]]
                out = N.types[nt]["native"] if lit == ot["native"] else (nt.replace("/", "+") if "/" in lit or "+" in lit or lit == cand[0] else N.types[nt]["name"])
                live.append(out)
                rf = nt.replace("/", "+")
                shp = shapes.get(rf)
                checks.append(None if shp is None else shp[:4] + [out if lit == ot["native"] else ""])
                notes.append(f"pos {pos} {lit} -> {out}: {why}")
                continue
            got = None
            for oo, no in zip(owners_old, owners_new):
                if no is None or not O.find(oo, lit):
                    continue
                got, why = map_member(oo, no, lit)
                if got is DECOY:
                    got = None
                    decoys += 1
                notes.append(f"pos {pos} {lit} -> {got}: {why}")
                if got is None and "unbound" not in why:
                    problems.append(f"pos {pos}: {why}")
                break
            else:
                golden = g["literals"][pos] if pos < len(g["literals"]) else None
                bare = re.sub(r"_k__BackingField$", "", field_core(lit)).lstrip("_")
                if (lit == golden and not re.match(r"^(get_|set_|Method_|field_)", lit) and not OBF.match(bare)
                        and not MASK.search(bare)):
                    got = lit
                    notes.append(f"pos {pos} {lit}: real-named golden literal kept verbatim on {old_build}, kept verbatim")
                elif lit == golden:
                    notes.append(f"pos {pos} {lit}: golden literal that names nothing on the {old_build} owners and is "
                                 "positional/obfuscated (could rebind to another member); unbound")
                elif not any(m.name == lit or m.native == lit for ms_ in O.members.values() for m in ms_):
                    notes.append(f"pos {pos} {lit}: names nothing in the {old_build} index (dead alias); unbound")
                else:
                    problems.append(f"pos {pos} {lit}: not on any old owner {owners_old}")
            live.append(got)
            checks.append(None)
        results[sym] = notes
        if not problems and not any(v is not None for v in live):
            problems.append("no position stays bound")
        if problems:
            review[sym] = problems
            continue
        entry = {"goldenLiterals": g["literals"], "live": live}
        if owners_old:
            entry["owners"] = [o.replace("/", "+") if "/" in o else o for o in owners_new]
        if is_type and any(checks):
            entry["typeChecks"] = checks
        entry["evidence"] = (f"{ov['buildId']} native-succession carry by tools/port_current/native_name_shift.py of the "
                             f"{a.old_scopes.stem.split('_')[-1]} generated scope (remap {od['remapResolution']} there; "
                             f"the golden->{ov['buildId']} remap refuses it: {nd['reason']}). " + "; ".join(notes) + ".")
        ov["symbols"][sym] = entry
    ov["symbols"] = dict(sorted(ov["symbols"].items()))
    if not a.dry_run:
        with a.overrides.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(ov, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    rep = {"anchors": {"methods": len(ms.anchors), "fields": len(fs.anchors), "types": len(ts.anchors)},
           "carried": sorted(set(results) - set(review)), "needsReview": review, "notes": results}
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    print(f"anchors {rep['anchors']}; carried {len(rep['carried'])}; review {len(review)}")
    for s, p in review.items():
        print("  REVIEW", s, "|", " | ".join(p)[:400])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("carry")
    for k in ("old-idx", "new-idx", "type-map", "old-scopes", "new-scopes", "remap", "new-shapes", "overrides", "report"):
        c.add_argument("--" + k, type=Path, required=True)
    c.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    return carry(a)


if __name__ == "__main__":
    sys.exit(main())
