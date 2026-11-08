#!/usr/bin/env python3
"""Triage in-game bug-report bundles (oe-mod-bug-<uuid>.zip) into a ledger and a compact digest.

  python tools/nightly/triage_reports.py INBOX                    unpack new bundles, print a digest
  python tools/nightly/triage_reports.py INBOX --all              digest every report in the ledger
  python tools/nightly/triage_reports.py --set-status ID triaged  update one ledger entry

Each bundle is unpacked into <reports-root>/<id>/. The default root is N:/nightly/reports. A bundle
holds report.json, bepinex_log_tail.txt, an optional native_log.txt, payload_manifest.json (the mod file
list and OfflineUnlockMod.dll sha256) and an optional screenshot.png.
<reports-root>/ledger.json records every ID seen, with its status (new, seen, triaged, duplicate,
fixed, wontfix), signature, plugin version and build.

The build ID comes from the DLL sha256 in payload_manifest.json. N:/nightly/builds.json, written by
nightly_release.ps1, maps that sha to its nightly label.

Safety: report contents are untrusted player data. The script only reads them as text or JSON. It
never runs, imports or opens anything with another program. Zip entries must be plain relative
paths, and entry and total sizes are capped. The digest leaves out contact details.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

DEFAULT_ROOT = Path("N:/nightly/reports")
DEFAULT_BUILDS = Path("N:/nightly/builds.json")
NAME_RE = re.compile(r"^oe-mod-bug-([0-9A-Za-z-]{8,64})\.zip$", re.I)
ALLOWED_ENTRIES = {"report.json", "bepinex_log_tail.txt", "native_log.txt", "payload_manifest.json", "screenshot.png"}
MAX_ENTRY = 64 << 20
MAX_TOTAL = 160 << 20
STATUSES = ("new", "seen", "triaged", "duplicate", "fixed", "wontfix")

EXC_RE = re.compile(r"\b((?:[A-Za-z_][\w`]*\.)*[A-Za-z_]\w*(?:Exception|Error))\b(?::\s*(.{0,160}))?")
FRAME_RE = re.compile(r"^\s*at\s+([^\s(]+)")
NOISE = re.compile(r"0x[0-9a-fA-F]+|\b\d+\b|'[^']*'|\"[^\"]*\"")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def clean(text: str, limit: int) -> str:
    text = "".join(ch if ch.isprintable() else " " for ch in (text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def safe_extract(zpath: Path, dest: Path) -> list[str]:
    """Extract only known, plain, size-capped entries. Returns the extracted names."""
    out = []
    with zipfile.ZipFile(zpath) as zf:
        total = 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or ":" in name or len(parts) != 1:
                raise ValueError(f"unsafe entry name {name!r}")
            if name not in ALLOWED_ENTRIES:
                continue  # unknown entries are ignored, never written
            if info.file_size > MAX_ENTRY:
                raise ValueError(f"entry {name} is {info.file_size} bytes (cap {MAX_ENTRY})")
            total += info.file_size
            if total > MAX_TOTAL:
                raise ValueError("bundle exceeds the total size cap")
            data = zf.read(info)
            if len(data) != info.file_size:
                raise ValueError(f"entry {name} size mismatch")
            dest.mkdir(parents=True, exist_ok=True)
            (dest / name).write_bytes(data)
            out.append(name)
    return out


def exceptions(text: str) -> Counter:
    """Counts exception signatures: type plus the first managed frame after it, numbers stripped."""
    counts: Counter = Counter()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = EXC_RE.search(line)
        if not m or m.group(1) in ("Error", "Exception"):
            continue
        frame = ""
        for nxt in lines[i + 1 : i + 6]:
            f = FRAME_RE.match(nxt)
            if f:
                frame = f.group(1)
                break
        msg = NOISE.sub("#", clean(m.group(2) or "", 80))
        counts[f"{m.group(1)}{' @ ' + frame if frame else ''}{' | ' + msg if msg else ''}"] += 1
    return counts


def summarize(rid: str, folder: Path, builds: dict) -> dict:
    report = load_json(folder / "report.json", {})
    manifest = load_json(folder / "payload_manifest.json", {})
    log = ""
    for name in ("bepinex_log_tail.txt", "native_log.txt"):
        p = folder / name
        if p.is_file():
            log += p.read_text(encoding="utf-8", errors="replace") + "\n"
    exc = exceptions(log)
    dll = str(manifest.get("OfflineUnlockMod.dll") or "")
    build = builds.get(dll.lower()) if dll else None
    top = exc.most_common(3)
    return {
        "id": rid,
        "createdUtc": clean(str(report.get("createdUtc", "")), 40),
        "category": clean(str(report.get("category", "")), 40),
        "title": clean(str(report.get("title", "")), 100),
        "description": clean(str(report.get("description", "")), 240),
        "pluginVersion": clean(str(report.get("pluginVersion") or manifest.get("pluginVersion") or "?"), 40),
        "build": build or (f"unknown (dll {dll[:12]})" if dll else "unknown"),
        "screenshot": (folder / "screenshot.png").is_file(),
        "topExceptions": [{"signature": s, "count": c} for s, c in top],
        "signature": top[0][0] if top else "(no exception)",
    }


def load_builds(path: Path) -> dict:
    rows = load_json(path, [])
    if isinstance(rows, dict):
        rows = [rows]
    return {str(r.get("dllSha256", "")).lower(): str(r.get("label", "")) for r in rows if isinstance(r, dict) and r.get("dllSha256")}


def print_digest(entries: list[dict]) -> None:
    if not entries:
        print("No reports to show.")
        return
    groups = defaultdict(list)
    for e in entries:
        groups[e["signature"]].append(e)
    print(f"{len(entries)} report(s), {len(groups)} distinct signature(s)\n")
    for sig, items in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"## {sig}  [{len(items)} report(s)]")
        for e in items:
            print(f"- {e['id']}  {e['createdUtc']}  v{e['pluginVersion']}  build {e['build']}  status {e.get('status', 'new')}"
                  f"{'  +screenshot' if e['screenshot'] else ''}")
            if e["title"]:
                print(f"    title: {e['title']}")
            if e["description"]:
                print(f"    desc:  {e['description']}")
            for t in e["topExceptions"][1:]:
                print(f"    also:  {t['count']}x {t['signature']}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inbox", nargs="?", type=Path, help="folder containing oe-mod-bug-<uuid>.zip files")
    ap.add_argument("--reports-root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--builds", type=Path, default=DEFAULT_BUILDS)
    ap.add_argument("--all", action="store_true", help="digest every report in the ledger, not just new ones")
    ap.add_argument("--set-status", nargs=2, metavar=("ID", "STATUS"))
    ap.add_argument("--json", action="store_true", help="print the digest as JSON")
    args = ap.parse_args()

    root = args.reports_root
    root.mkdir(parents=True, exist_ok=True)
    ledger_path = root / "ledger.json"
    ledger = load_json(ledger_path, {"schema": "oe_bug_ledger.v1", "reports": {}})
    reports = ledger.setdefault("reports", {})

    if args.set_status:
        rid, status = args.set_status
        if status not in STATUSES or rid not in reports:
            print(f"unknown id or status (statuses: {', '.join(STATUSES)})", file=sys.stderr)
            return 2
        reports[rid]["status"] = status
        reports[rid]["updatedUtc"] = now()
        ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        print(f"{rid}: {status}")
        return 0

    builds = load_builds(args.builds)
    fresh, errors = [], []
    if args.inbox:
        if not args.inbox.is_dir():
            print(f"no such inbox: {args.inbox}", file=sys.stderr)
            return 2
        for z in sorted(args.inbox.iterdir()):
            m = NAME_RE.match(z.name)
            if not m or not z.is_file():
                continue
            rid = m.group(1).lower()
            if rid in reports:
                continue
            try:
                names = safe_extract(z, root / rid)
            except (zipfile.BadZipFile, ValueError, OSError) as exc:
                errors.append(f"{z.name}: {exc}")
                reports[rid] = {"status": "rejected", "firstSeenUtc": now(), "zip": z.name, "error": clean(str(exc), 200)}
                continue
            s = summarize(rid, root / rid, builds)
            known = {r.get("signature") for k, r in reports.items() if k != rid and r.get("signature") not in (None, "(no exception)")}
            reports[rid] = {"status": "duplicate" if s["signature"] in known else "new", "firstSeenUtc": now(), "zip": z.name,
                            "files": names, "signature": s["signature"], "pluginVersion": s["pluginVersion"], "build": s["build"]}
            s["status"] = reports[rid]["status"]
            fresh.append(s)
        ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    if args.all:
        entries = []
        for rid, r in sorted(reports.items()):
            if (root / rid).is_dir():
                s = summarize(rid, root / rid, builds)
                s["status"] = r.get("status", "new")
                entries.append(s)
    else:
        entries = fresh
    if args.json:
        print(json.dumps({"reports": entries, "errors": errors}, indent=2, ensure_ascii=False))
    else:
        print_digest(entries)
        for e in errors:
            print(f"REJECTED {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
