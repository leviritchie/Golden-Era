#!/usr/bin/env python3
"""Write measured attack timings into an installed ``Core.zip`` for a set of h3_* units (coordinator deploy step).

Uses the release overlay's ``assign_homm3_attack_timings`` (the single owner of attackTimeBefore/After) on only the
``DB/units/units_views/**/<sid>_v.json`` entries of the given units, so the next release overlay produces the same
values. Every other ZIP entry keeps its name, order and uncompressed bytes; the result is verified entry by entry
before it replaces the original, and the original is backed up beside ``--backup-dir``.

Usage:
  python tools/homm3_def_retarget_delivery/sync_core_attack_timing.py --core <Core.zip> --units h3_a,h3_b \
    --backup-dir V:/olden_port_work/<dir> [--dry-run]
Then: python tools/validate_homm3_attack_timing.py --core <Core.zip>
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "release_port"))
from homm3_attack_timing_overlay import assign_homm3_attack_timings  # noqa: E402


def write_json(value) -> bytes:  # same bytes as apply_release_core_overlay.write_json
    import json
    return (json.dumps(value, ensure_ascii=False, indent="\t") + "\n").encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--core", required=True, type=Path)
    ap.add_argument("--units", required=True)
    ap.add_argument("--backup-dir", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sids = {s for s in a.units.split(",") if s}

    with zipfile.ZipFile(a.core) as z:
        infos = z.infolist()
        targets = {i.filename: z.read(i) for i in infos
                   if i.filename.startswith("DB/units/units_views/") and Path(i.filename).name[:-7] in sids
                   and i.filename.endswith("_v.json")}
    missing = sids - {Path(n).name[:-7] for n in targets}
    if missing:
        print("no view entry for:", ", ".join(sorted(missing)))
        return 2
    output = dict(targets)
    notes: list[str] = []
    assign_homm3_attack_timings(output, notes, write_json)
    changed = {n: b for n, b in output.items() if b != targets[n]}
    print(notes[-1] if notes else "")
    for n in sorted(changed):
        print("CHANGED", n)
    if a.dry_run or not changed:
        print("dry run" if a.dry_run else "nothing to change")
        return 0

    a.backup_dir.mkdir(parents=True, exist_ok=True)
    backup = a.backup_dir / f"Core.before_timing_{hashlib.sha256(a.core.read_bytes()).hexdigest()[:8]}.zip"
    shutil.copy2(a.core, backup)
    tmp = a.core.with_suffix(".timing_tmp.zip")
    with zipfile.ZipFile(backup) as src, zipfile.ZipFile(tmp, "w") as dst:
        for info in src.infolist():
            if info.filename in changed:
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.compress_type, zi.external_attr = info.compress_type, info.external_attr
                dst.writestr(zi, changed[info.filename])
            else:
                with src.open(info) as fh:  # recompress-free copy is not exposed; copy decompressed bytes
                    dst.writestr(info, fh.read())
    with zipfile.ZipFile(backup) as old, zipfile.ZipFile(tmp) as new:
        on, nn = [i.filename for i in old.infolist()], [i.filename for i in new.infolist()]
        assert on == nn, "entry order/name mismatch"
        for n in on:
            want = changed.get(n)
            got = new.read(n)
            assert got == (want if want is not None else old.read(n)), f"verify failed: {n}"
    tmp.replace(a.core)
    print(f"wrote {a.core} ({len(changed)} entr{'y' if len(changed) == 1 else 'ies'} changed); backup {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
