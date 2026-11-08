"""Copy the live install's data files (read-only) into a scratch dir with provenance.

Copies StreamingAssets/Core.zip plus the maps/, map_templates/ and map_schemas/ trees,
records sha256 per file and the appmanifest buildid/manifest before and after the copy.
Fails closed if the buildid is not the expected one, or if it changes during the copy.

    python tools/port_current/snapshot_live_data.py --expect-buildid 25509697 \
        --out artifacts/port_current/live_25509697
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

DEFAULT_LIBRARY = Path(r"V:\SteamLibrary\steamapps")
APP_ID = "3105440"
INSTALL_DIR = "Heroes of Might and Magic Olden Era"
TREES = ("maps", "map_templates", "map_schemas")


def read_manifest(library: Path) -> dict:
    text = (library / f"appmanifest_{APP_ID}.acf").read_text(encoding="utf-8")
    build = re.search(r'"buildid"\s+"(\d+)"', text)
    depot_manifest = re.search(r'"manifest"\s+"(\d+)"', text)
    updated = re.search(r'"LastUpdated"\s+"(\d+)"', text)
    if not build or not depot_manifest:
        raise SystemExit("appmanifest has no buildid/manifest")
    return {"buildid": build.group(1), "manifest": depot_manifest.group(1),
            "lastUpdated": updated.group(1) if updated else None}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-buildid", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    args = ap.parse_args()

    out = args.out.resolve()
    if "steamapps" in [p.lower() for p in out.parts]:
        raise SystemExit(f"refusing to write under steamapps: {out}")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"--out must be new or empty: {out}")

    before = read_manifest(args.library)
    if before["buildid"] != args.expect_buildid:
        raise SystemExit(f"buildid {before['buildid']} != expected {args.expect_buildid}; refusing")

    sa = args.library / "common" / INSTALL_DIR / "HeroesOldenEra_Data" / "StreamingAssets"
    sources = [sa / "Core.zip"]
    for tree in TREES:
        sources.extend(sorted(p for p in (sa / tree).rglob("*") if p.is_file()))

    files = {}
    for src in sources:
        rel = src.relative_to(sa).as_posix()
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        digest = sha256(dst)
        if digest != sha256(src):
            raise SystemExit(f"copy mismatch for {rel}")
        files[rel] = {"sha256": digest, "size": dst.stat().st_size}

    after = read_manifest(args.library)
    if after != before:
        raise SystemExit(f"appmanifest changed during copy: {before} -> {after}")

    report = {"schema": "live_data_snapshot.v1", "copiedAtUnix": int(time.time()),
              "source": str(sa), "appmanifest": before, "fileCount": len(files), "files": files}
    (out / "snapshot.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(out), "appmanifest": before, "fileCount": len(files),
                      "coreSha256": files["Core.zip"]["sha256"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
