#!/usr/bin/env python3
"""Build or verify the hash manifest of a frozen Olden Era install mirror.

The mirror is a plain file copy of the live Steam install, taken while the live
appmanifest reported StateFlags == 4 (fully installed, not updating). It is the
stable target for porting OfflineUnlockMod to that build. See
docs/port_to_current_game_version.md, "Phase 0/5 status".

  build   Hash every file under --mirror. With --source, also prove the source is
          byte-identical to the mirror. Reads the appmanifest to pin the build and
          refuses if it changes while hashing. Never writes to --source or the
          appmanifest.
  verify  Recheck --mirror against a manifest. Missing, changed or extra files
          fail. Extra files are allowed only under an explicit --allow-extra-prefix
          (for example BepInEx/ once the loader is installed into the mirror).

Usage:
  python tools/port_current/mirror_manifest.py build \
      --source "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era" \
      --appmanifest "V:/SteamLibrary/steamapps/appmanifest_3105440.acf" \
      --mirror "F:/olden_mirrors/Heroes of Might and Magic Olden Era - Current Era" \
      --expect-buildid 25061458 \
      --out tools/port_current/mirror_manifest_25061458.json
  python tools/port_current/mirror_manifest.py verify \
      --manifest tools/port_current/mirror_manifest_25061458.json [--mirror ...] [--size-only]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

SCHEMA = "olden_mirror_manifest.v1"
CHUNK = 4 * 1024 * 1024


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def list_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def listing_sha256(entries: list[dict]) -> str:
    text = "".join(f"{e['path']}\t{e['size']}\t{e['sha256']}\n" for e in entries)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_appmanifest(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")

    def field(name: str) -> str:
        m = re.search(r'"' + re.escape(name) + r'"\s+"([^"]*)"', text)
        if not m:
            raise SystemExit(f"FAIL appmanifest field {name!r} missing in {path}")
        return m.group(1)

    block = re.search(r'"InstalledDepots"\s*\{(.*?)\n\t\}', text, re.S)
    if not block:
        raise SystemExit(f"FAIL InstalledDepots missing in {path}")
    depots = re.findall(r'"(\d+)"\s*\{\s*"manifest"\s+"(\d+)"', block.group(1))
    if len(depots) != 1:
        raise SystemExit(f"FAIL expected exactly one installed depot, found {depots}")
    return {
        "appid": field("appid"),
        "buildid": field("buildid"),
        "stateFlags": int(field("StateFlags")),
        "targetBuildId": field("TargetBuildID"),
        "lastUpdated": int(field("LastUpdated")),
        "depot": depots[0][0],
        "depotManifest": depots[0][1],
        "appmanifestSha256": sha256_file(path),
    }


def check_quiescent(app: dict) -> None:
    if app["stateFlags"] != 4:
        raise SystemExit(f"FAIL live install is not quiescent: StateFlags={app['stateFlags']} (want 4)")
    if app["buildid"] != app["targetBuildId"]:
        raise SystemExit(
            f"FAIL buildid {app['buildid']} != TargetBuildID {app['targetBuildId']}: update pending"
        )


def cmd_build(args: argparse.Namespace) -> int:
    mirror = args.mirror.resolve()
    before = parse_appmanifest(args.appmanifest)
    check_quiescent(before)
    if args.expect_buildid and before["buildid"] != args.expect_buildid:
        raise SystemExit(f"FAIL buildid {before['buildid']} != expected {args.expect_buildid}")
    if not mirror.is_dir():
        raise SystemExit(f"FAIL mirror missing: {mirror}")

    rels = list_files(mirror)
    entries = []
    total = 0
    for i, rel in enumerate(rels, 1):
        p = mirror / rel
        size = p.stat().st_size
        entries.append({"path": rel, "size": size, "sha256": sha256_file(p)})
        total += size
        if i % 50 == 0:
            print(f"  hashed mirror {i}/{len(rels)}", flush=True)

    source_check = None
    if args.source:
        source = args.source.resolve()
        src_rels = list_files(source)
        if src_rels != rels:
            only_src = sorted(set(src_rels) - set(rels))[:10]
            only_mir = sorted(set(rels) - set(src_rels))[:10]
            raise SystemExit(f"FAIL file set differs: only source {only_src}, only mirror {only_mir}")
        mismatches = []
        for i, e in enumerate(entries, 1):
            p = source / e["path"]
            if p.stat().st_size != e["size"] or sha256_file(p) != e["sha256"]:
                mismatches.append(e["path"])
            if i % 50 == 0:
                print(f"  hashed source {i}/{len(entries)}", flush=True)
        if mismatches:
            raise SystemExit(f"FAIL mirror differs from source: {mismatches[:10]}")
        source_check = {"source": str(source), "identical": True, "files": len(rels)}

    after = parse_appmanifest(args.appmanifest)
    if after != before:
        raise SystemExit("FAIL appmanifest changed while hashing; the live install moved. Rebuild the mirror.")

    doc = {
        "schema": SCHEMA,
        "createdUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "build": before,
        "mirrorRoot": str(mirror),
        "sourceCheck": source_check,
        "fileCount": len(entries),
        "totalBytes": total,
        "listingSha256": listing_sha256(entries),
        "files": entries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    print(f"OK wrote {args.out}: {len(entries)} files, {total} bytes, listing {doc['listingSha256'][:16]}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    doc = json.loads(args.manifest.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise SystemExit(f"FAIL unexpected manifest schema {doc.get('schema')!r}")
    if listing_sha256(doc["files"]) != doc["listingSha256"]:
        raise SystemExit("FAIL manifest file list does not match its own listingSha256")
    mirror = (args.mirror or Path(doc["mirrorRoot"])).resolve()
    if not mirror.is_dir():
        raise SystemExit(f"FAIL mirror missing: {mirror}")

    expected = {e["path"]: e for e in doc["files"]}
    actual = set(list_files(mirror))
    prefixes = tuple(p.replace("\\", "/").rstrip("/") + "/" for p in args.allow_extra_prefix)
    missing = sorted(set(expected) - actual)
    extra = sorted(p for p in actual - set(expected) if not (prefixes and p.startswith(prefixes)))
    changed = []
    for i, (rel, e) in enumerate(sorted(expected.items()), 1):
        if rel not in actual:
            continue
        p = mirror / rel
        if p.stat().st_size != e["size"]:
            changed.append(f"{rel} (size)")
        elif not args.size_only and sha256_file(p) != e["sha256"]:
            changed.append(f"{rel} (sha256)")
        if i % 100 == 0:
            print(f"  checked {i}/{len(expected)}", flush=True)
    for label, rows in (("missing", missing), ("extra", extra), ("changed", changed)):
        if rows:
            print(f"FAIL {label} {len(rows)}: {rows[:20]}")
    if missing or extra or changed:
        return 1
    mode = "size-only" if args.size_only else "sha256"
    print(f"OK mirror {mirror} matches build {doc['build']['buildid']} ({len(expected)} files, {mode})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--mirror", type=Path, required=True)
    b.add_argument("--appmanifest", type=Path, required=True)
    b.add_argument("--source", type=Path, help="Live install to prove byte-identical (read only)")
    b.add_argument("--expect-buildid")
    b.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("verify")
    v.add_argument("--manifest", type=Path, required=True)
    v.add_argument("--mirror", type=Path)
    v.add_argument("--allow-extra-prefix", action="append", default=[])
    v.add_argument("--size-only", action="store_true", help="Quick check; skips sha256")
    args = ap.parse_args()
    return cmd_build(args) if args.cmd == "build" else cmd_verify(args)


if __name__ == "__main__":
    sys.exit(main())
