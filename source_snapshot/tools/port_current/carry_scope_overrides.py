#!/usr/bin/env python3
"""Carry hand-curated current-scope overrides from one live build to the next.

`current_scope_overrides_<old>.json` binds Golden Era hint literals to names on the *old* live build. Each entry
was decided by role (caller, call position, in-order native name) with native evidence. When Steam ships a
hotfix, this tool maps every bound old-live name to the new build with the same matcher the P1 remap uses
(`symbol_remap` TypeMatcher + member matcher, native-body evidence on), treating the old live index as the
"golden" side. It decides nothing by guessing:

* a type literal (a position with a typeCheck) must map through its typeCheck's own type;
* a member literal on an entry with owners must bind on one of those owners;
* every bound name must aggregate to exactly one new name (remap status MAPPED or UNCHANGED);
* a method's new body is compared with the old binding (`native_body.similarity`); below --min-sim the
  entry is held for review.

Entries that pass are written to --out-overrides with new owners, recomputed typeChecks (from the new interop
shape index) and an evidence line naming the carry. Every other entry is listed in --report under
`needsReview` and is NOT written: re-derive it with override_evidence.py and add it by hand.

  python tools/port_current/carry_scope_overrides.py \
      --overrides tools/port_current/remap/current_scope_overrides_25509697.json \
      --old-idx artifacts/port_current/idx2_live_25509697 --old-ga "<old mirror>/GameAssembly.dll" \
      --new-idx artifacts/port_current/idx2_live_25672315 --new-ga "<new mirror>/GameAssembly.dll" \
      --new-shapes artifacts/port_current/p2/index_cache/shape_index_<key>.tsv \
      --out-overrides tools/port_current/remap/current_scope_overrides_25672315.json \
      --report artifacts/port_current/carry_overrides_25672315.json

Inputs are read only. Proof tier of the output: generated artifact (static native evidence), never runtime.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from symbol_remap import match, model, native_body, remap  # noqa: E402

OVERRIDES_SCHEMA = "game_symbols_current_scope_overrides.v1"


def load_shapes(tsv: Path) -> dict[str, list]:
    """runtime full name -> [runtimeFull, base, fields, methods, obf] from an interop_shape_index TSV."""
    out: dict[str, list] = {}
    with tsv.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("T\t"):
                continue
            p = line.rstrip("\n").split("\t")
            # T asm full runtimeFull obf base fields methods
            out[p[3]] = [p[3], p[5], int(p[6]), int(p[7]), p[4]]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overrides", type=Path, required=True)
    ap.add_argument("--old-idx", type=Path, required=True)
    ap.add_argument("--old-ga", type=Path, required=True)
    ap.add_argument("--new-idx", type=Path, required=True)
    ap.add_argument("--new-ga", type=Path, required=True)
    ap.add_argument("--new-shapes", type=Path, required=True, help="interop_shape_index TSV of the new interop")
    ap.add_argument("--out-overrides", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--min-sim", type=float, default=0.90)
    a = ap.parse_args(argv)

    ov = json.loads(a.overrides.read_text(encoding="utf-8"))
    if ov.get("schema") != OVERRIDES_SCHEMA:
        sys.exit(f"carry_scope_overrides: REFUSED: {a.overrides} schema {ov.get('schema')!r}")
    sides = []
    for d, ga in ((a.old_idx, a.old_ga), (a.new_idx, a.new_ga)):
        inp = json.loads((d / "inputs.json").read_text(encoding="utf-8"))
        idx = model.load(str(d / "port_index.tsv"))
        nat = native_body.NativeSide(d / "gen" / "native_addresses.tsv", ga, inp["gameAssemblySha256"],
                                     inp["metadataSha256"])
        sides.append((inp, idx, nat))
    (oinp, G, gnat), (ninp, L, lnat) = sides
    if str(ov.get("buildId")) != str(oinp.get("steamBuildId")):
        sys.exit(f"carry_scope_overrides: REFUSED: overrides are for build {ov.get('buildId')}, old index is "
                 f"{oinp.get('steamBuildId')}")
    new_build = ninp.get("steamBuildId")
    if not new_build or new_build == oinp.get("steamBuildId"):
        sys.exit("carry_scope_overrides: REFUSED: new index carries no (or the same) Steam build id")
    shapes = load_shapes(a.new_shapes)

    tm = match.TypeMatcher(G, L)
    tm.run()
    rm = remap.Remapper(G, L, tm, native_body.BodyEvidence(gnat, lnat))

    carried: dict[str, dict] = {}
    review: dict[str, list[str]] = {}
    details: dict[str, list[dict]] = {}
    for sym, e in ov["symbols"].items():
        problems: list[str] = []
        rows: list[dict] = []
        if not isinstance(e.get("live"), list):
            review[sym] = ["live must be an array"]
            details[sym] = rows
            continue
        if "typeChecks" in e:
            checks = e["typeChecks"]
            if not isinstance(checks, list):
                review[sym] = ["typeChecks must be an array"]
                details[sym] = rows
                continue
            if len(checks) != len(e["live"]):
                review[sym] = [f"typeChecks length must equal live length ({len(e['live'])})"]
                details[sym] = rows
                continue
        else:
            checks = [None] * len(e["live"])
        owners = e.get("owners") or []
        new_owners = []
        for o in owners:
            ts = rm.type_status(o) if o in G.types else {"status": "UNMAPPED", "reason": "owner not in old index"}
            if ts["status"] != "MAPPED":
                problems.append(f"owner {o}: {ts.get('reason')}")
            else:
                new_owners.append(ts["live"])
        new_live, new_checks = [], []
        for pos, lit in enumerate(e["live"]):
            chk = checks[pos]
            if lit is None:
                new_live.append(None)
                new_checks.append(None)
                continue
            bs = rm.bindings(lit)
            if chk:
                want = chk[0].replace("+", "/")
                bs = [b for b in bs if b["kind"] == "type" and b["goldenOwner"] == want]
            elif owners:
                bs = [b for b in bs if b["kind"] == "member" and b["goldenOwner"] in owners]
            agg = remap.Remapper.aggregate(lit, bs)
            row = {"pos": pos, "old": lit, "status": agg["status"], "new": agg.get("live"),
                   "confidence": agg.get("confidence"), "bindings": len(bs)}
            if agg["status"] not in ("MAPPED", "UNCHANGED"):
                problems.append(f"pos {pos} {lit}: {agg.get('reason')}")
            if chk and agg.get("live"):
                lt = next((b for b in bs if b.get("live") == agg["live"]), None)
                shape = shapes.get(L.types[lt["liveOwner"]].runtime_full) if lt else None
                if shape is None:
                    problems.append(f"pos {pos} {lit}: no shape for the new type in {a.new_shapes.name}")
                else:
                    if chk[4]:
                        shape = shape[:4] + [agg["live"] if chk[4] == lit else shape[4]]
                    else:
                        shape = shape[:4] + [""]
                    row["typeCheck"] = shape
                new_checks.append(shape)
            else:
                new_checks.append(None)
            if not chk and agg.get("live"):
                method_bindings = [b for b in bs if b.get("kind") == "member" and
                                   b.get("memberCategory") == "method"]
                sims = []
                for b in method_bindings:
                    gt = G.types.get(b.get("goldenOwner") or "")
                    if gt is None:
                        problems.append(f"pos {pos} {lit}->{agg['live']}: method owner missing from old index")
                        continue
                    core_key = b.get("goldenCoreKey")
                    if (not isinstance(core_key, (list, tuple)) or len(core_key) != 2 or
                            core_key[0] != "m" or not isinstance(core_key[1], int) or
                            isinstance(core_key[1], bool)):
                        problems.append(f"pos {pos} {lit}->{agg['live']}: method binding lacks a valid core key")
                        continue
                    c = next((candidate for candidate in gt.cores if candidate.key == tuple(core_key)), None)
                    if c is None or c.cat != "method":
                        problems.append(f"pos {pos} {lit}->{agg['live']}: method core key {core_key} missing on {gt.full}")
                        continue
                    mm = rm.members_of(gt.full).get(c.key)
                    lt = L.types.get(b.get("liveOwner") or "")
                    if mm is None or mm.live is None or lt is None:
                        problems.append(f"pos {pos} {lit}->{agg['live']}: mapped method unavailable for body comparison")
                        continue
                    va_o, va_n = gnat.va_of(gt.asm, c), lnat.va_of(lt.asm, mm.live)
                    if not va_o or not va_n:
                        problems.append(f"pos {pos} {lit}->{agg['live']}: native body address unavailable on "
                                        f"{oinp.get('steamBuildId')} or {new_build}")
                        continue
                    sims.append(round(native_body.similarity(gnat.features(va_o), lnat.features(va_n)), 4))
                if method_bindings and len(sims) == len(method_bindings):
                    row["bodySim"] = min(sims)
                    if min(sims) < a.min_sim:
                        problems.append(f"pos {pos} {lit}->{agg['live']}: body similarity {min(sims)} < {a.min_sim}")
            new_live.append(agg.get("live"))
            rows.append(row)
        details[sym] = rows
        if problems:
            review[sym] = problems
            continue
        out = {"goldenLiterals": e["goldenLiterals"], "live": new_live}
        if e.get("split"):
            out["split"] = True
        if owners:
            out["owners"] = new_owners
        if e.get("typeChecks"):
            out["typeChecks"] = new_checks
        summary = "; ".join(f"{r['old']}->{r['new']} ({r['status']}, conf {r['confidence']}"
                            + (f", body {r['bodySim']}" if "bodySim" in r else "") + ")" for r in rows)
        out["evidence"] = (f"{new_build} carry from the {ov['buildId']} override by tools/port_current/"
                           f"carry_scope_overrides.py (old-live -> new-live matcher, native body on): {summary}. "
                           f"{ov['buildId']} basis: {e['evidence']}")
        carried[sym] = out

    doc = {"schema": OVERRIDES_SCHEMA, "buildId": new_build,
           "note": (f"Hand-curated current-build scopes carried from {ov['buildId']} to {new_build} by "
                    "tools/port_current/carry_scope_overrides.py (old live index "
                    f"{oinp['gameAssemblySha256'][:8]}..., new live index {ninp['gameAssemblySha256'][:8]}...). "
                    "Entries with mapping problems were omitted and remain pending manual re-derivation; see the "
                    "companion report's needsReview field. "
                    "Proof tier: generated artifact (static native evidence); runtime unproven."),
           "symbols": carried}
    a.out_overrides.parent.mkdir(parents=True, exist_ok=True)
    a.out_overrides.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps({"carried": sorted(carried), "needsReview": review, "details": details},
                                   indent=1) + "\n", encoding="utf-8")
    print(f"carried {len(carried)} / {len(ov['symbols'])}; needs review {len(review)}")
    for s, p in review.items():
        print(f"  REVIEW {s}: {' | '.join(p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
