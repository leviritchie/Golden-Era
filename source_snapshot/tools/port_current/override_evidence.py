#!/usr/bin/env python3
"""Native evidence for re-verifying hand-curated current-scope overrides on a newer build.

`current_scope_overrides_<build>.json` entries were chosen by role (caller, call position, in-order native
name), not by body score alone, because Il2CppInterop `_PDM_` copies are obfuscator decoys with the same body
at their own VA (docs/port_to_current_game_version.md, "PDM copies are obfuscator decoys"). When Steam ships a
new build, every entry has to be re-derived on the new binary. This tool does not decide anything: for each
entry it prints, on the old and the new build, every same-signature candidate on the (type-mapped) owner with
its interop name, token, native name, VA, instruction count, identical-code folding, direct callers (rel32
call/jmp xrefs resolved to the calling function), and the body similarity to the method the old entry bound.
The reviewer records the decision and its evidence in the new overrides file.

  python tools/port_current/override_evidence.py \
      --overrides tools/port_current/remap/current_scope_overrides_25061458.json \
      --old-idx artifacts/port_current/idx2_live --old-ga "<old mirror>/GameAssembly.dll" \
      --new-idx artifacts/port_current/idx2_live_25509697 --new-ga "<new mirror>/GameAssembly.dll" \
      --type-map artifacts/port_current/drift_25061458_to_25509697/type_map_25509697.json \
      --out artifacts/port_current/override_evidence_25509697.json

Both indexes are `build_index.py generate` outputs with `gen/native_addresses.tsv`. Inputs are read only.
Proof tier of the output: generated artifact (static native evidence), never runtime.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from symbol_remap import model, native_body  # noqa: E402

OBF_IDENT = re.compile(r"Object(?:Public|Private|Protected|Internal|N)\w*Unique|\b[a-z]{2,4}\b")


def mask_sig(sig: str) -> str:
    """Signature with build-renamed generated/obfuscated type spellings masked."""
    return OBF_IDENT.sub("O", sig)


class Side:
    def __init__(self, idx_dir: Path, ga: Path):
        inp = json.loads((idx_dir / "inputs.json").read_text(encoding="utf-8"))
        self.label = inp["label"]
        self.build = inp.get("steamBuildId")
        self.index = model.load(str(idx_dir / "port_index.tsv"))
        self.nat = native_body.NativeSide(idx_dir / "gen" / "native_addresses.tsv", ga, inp["gameAssemblySha256"],
                                          inp["metadataSha256"])
        self.va_methods: dict[int, list[str]] = defaultdict(list)
        for (asm, tok), va in self.nat.by_tok.items():
            self.va_methods[va].append(f"{asm}:{tok}")
        self._xrefs: dict[int, list[int]] | None = None
        self._wanted: set[int] = set()

    # -------------------------------------------------------------------------------------------- methods
    def methods(self, owner: str) -> list[dict]:
        t = self.index.types.get(owner)
        if t is None:
            return []
        out = []
        for c in t.cores:
            if c.cat != "method" or c.key[0] != "m":
                continue
            row = c.rows.get("method")
            if row is None:
                continue
            va = self.nat.by_tok.get((t.asm, c.key[1]))
            out.append({"interop": row.name, "token": c.key[1], "native": c.native_name, "sig": row.sig,
                        "static": row.static, "va": va, "asm": t.asm})
        return out

    def insns(self, va: int | None) -> int | None:
        return None if va is None else self.nat.features(va)["_n"]

    # -------------------------------------------------------------------------------------------- xrefs
    def want(self, vas) -> None:
        self._wanted.update(v for v in vas if v)
        self._xrefs = None

    def xrefs(self) -> dict[int, list[int]]:
        if self._xrefs is not None:
            return self._xrefs
        wanted = np.array(sorted(self._wanted), dtype=np.int64)
        found: dict[int, list[int]] = defaultdict(list)
        data = np.frombuffer(self.nat.data, dtype=np.uint8)
        for (rva, end, raw, rawsize, name, ch) in self.nat.sections:
            if not ch & 0x20000000:        # IMAGE_SCN_MEM_EXECUTE
                continue
            sec = data[raw:raw + rawsize]
            pos = np.nonzero((sec[:-5] == 0xE8) | (sec[:-5] == 0xE9))[0]
            rel = (sec[pos + 1].astype(np.int64) | (sec[pos + 2].astype(np.int64) << 8)
                   | (sec[pos + 3].astype(np.int64) << 16) | (sec[pos + 4].astype(np.int64) << 24))
            rel = np.where(rel >= 1 << 31, rel - (1 << 32), rel)
            src = self.nat.base + rva + pos
            tgt = src + 5 + rel
            hit = np.isin(tgt, wanted)
            for s, t in zip(src[hit].tolist(), tgt[hit].tolist()):
                found[t].append(s)
        self._xrefs = found
        return found

    def callers(self, va: int | None) -> list[str]:
        if not va:
            return []
        out = []
        for s in self.xrefs().get(va, []):
            b, _e = self.nat._bounds(s - self.nat.base)
            fva = self.nat.base + b
            if b == s - self.nat.base:
                continue            # no unwind entry: cannot place the source
            who = self.nat.at.get(fva)
            name = f"{who[1]}::{who[2]}" if who else "?"
            out.append(f"{name}@{hex(fva)}+{hex(s - fva)}")
        return sorted(set(out))


def describe(side: Side, owner: str, sig_mask: str, ref_feats: dict | None) -> list[dict]:
    rows = []
    for m in side.methods(owner):
        if mask_sig(m["sig"]) != sig_mask:
            continue
        va = m["va"]
        feats = side.nat.features(va) if va else None
        rows.append({
            "interop": m["interop"], "token": m["token"], "native": m["native"],
            "va": hex(va) if va else None, "insns": feats["_n"] if feats else None,
            "foldedWith": len(side.va_methods.get(va, [])) if va else 0,
            "callers": side.callers(va),
            "simToOldBinding": round(native_body.similarity(ref_feats, feats), 4) if (ref_feats and feats) else None,
        })
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overrides", type=Path, required=True)
    ap.add_argument("--old-idx", type=Path, required=True)
    ap.add_argument("--old-ga", type=Path, required=True)
    ap.add_argument("--new-idx", type=Path, required=True)
    ap.add_argument("--new-ga", type=Path, required=True)
    ap.add_argument("--type-map", type=Path, required=True, help="type_map_<new>.json of an old->new remap run")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)

    ov = json.loads(a.overrides.read_text(encoding="utf-8"))
    tmap = json.loads(a.type_map.read_text(encoding="utf-8"))
    old, new = Side(a.old_idx, a.old_ga), Side(a.new_idx, a.new_ga)
    if str(ov.get("buildId")) != str(old.build):
        sys.exit(f"override_evidence: REFUSED: overrides are for build {ov.get('buildId')}, old index is {old.build}")

    # collect every candidate VA first, so each side scans its code once
    plan = []
    for sym, e in ov["symbols"].items():
        owners = e.get("owners") or []
        for owner in owners:
            new_owner = tmap.get(owner, {}).get("live") or (owner if owner in new.index.types else None)
            for lit in [x for x in e["live"] if x]:
                ref = next((m for m in old.methods(owner) if m["interop"] == lit), None)
                plan.append((sym, owner, new_owner, lit, ref))
                if ref:
                    sm = mask_sig(ref["sig"])
                    old.want(m["va"] for m in old.methods(owner) if mask_sig(m["sig"]) == sm)
                    if new_owner:
                        new.want(m["va"] for m in new.methods(new_owner) if mask_sig(m["sig"]) == sm)

    report = {"schema": "scope_override_evidence.v1", "oldBuild": old.build, "newBuild": new.build,
              "overrides": str(a.overrides).replace("\\", "/"), "entries": []}
    for sym, owner, new_owner, lit, ref in plan:
        ent = {"symbol": sym, "oldOwner": owner, "newOwner": new_owner,
               "newOwnerMatch": tmap.get(owner, {}).get("method"), "oldLiteral": lit}
        if ref is None:
            ent["error"] = f"{lit} not found on {owner} in the old index"
        else:
            ref_feats = old.nat.features(ref["va"]) if ref["va"] else None
            sm = mask_sig(ref["sig"])
            ent["oldBinding"] = {"native": ref["native"], "token": ref["token"],
                                 "va": hex(ref["va"]) if ref["va"] else None, "sig": ref["sig"]}
            ent["oldCandidates"] = describe(old, owner, sm, ref_feats)
            ent["newCandidates"] = describe(new, new_owner, sm, ref_feats) if new_owner else []
        report["entries"].append(ent)
        print(f"== {sym} [{owner} -> {new_owner} ({ent['newOwnerMatch']})] old {lit}")
        for tag in ("oldCandidates", "newCandidates"):
            for r in ent.get(tag, []):
                print(f"   {tag[:3]} {r['interop']} {r['native']} tok={r['token']} {r['va']} n={r['insns']} "
                      f"fold={r['foldedWith']} sim={r['simToOldBinding']} callers={r['callers'][:4]}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
