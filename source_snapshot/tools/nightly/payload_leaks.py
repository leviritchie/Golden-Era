#!/usr/bin/env python3
"""Sanitize and leak-scan a staged Golden Era release payload (nightly lane).

  fix  --root STAGE [--report R]   Rewrites JSON and CSV files outside payload/streaming_assets that hold local
                                   build paths. Unlike the old PowerShell pass, it also catches
                                   JSON-escaped paths ("C:\\\\Users\\\\..."), forward-slash paths
                                   ("V:/...") and paths embedded inside longer strings. A string that IS
                                   a local path becomes "<sanitized-local-path>". A path inside a longer
                                   string becomes "<local-path>".
  scan --root STAGE [--report R]   Fails (exit 1) on any absolute local path, local username, email
           [--term WORD ...]       address, secret-shaped token or maintainer folder name, in every text
                                   file and in the first-party DLLs (OfflineUnlockMod.dll, OldenAiSim.dll).
                                   It reads the printable ASCII and UTF-16 strings of each DLL.
                                   Pass the machine's username, user.name and user.email as --term. They
                                   are read at run time, so none of them is stored in this file.

Reported excerpts mask emails, secrets and --term values, so the report is safe to relay.
The scan only reads files. It never runs or imports anything from the payload.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from pathlib import Path

TEXT_EXTS = {
    ".json", ".txt", ".cfg", ".ini", ".xml", ".yml", ".yaml", ".md", ".manifest", ".csv", ".lua",
    ".foldercache", ".html", ".htm", ".js", ".css", ".config", ".props", ".targets", ".bat", ".cmd",
    ".ps1", ".sh", ".toml", ".log", ".tsv", ".shader", ".asmdef",
}
FIRST_PARTY_DLLS = {"offlineunlockmod.dll", "oldenaisim.dll"}
EXTENSIONLESS_TEXT_MAX = 1 << 20

# The BepInEx plugin GUID is the one shipped string that legitimately carries the username.
ALLOW_SUBSTRINGS = ("levir.heroesoe.offlineunlock",)

DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:(?:\\{1,2}|/)(?=[A-Za-z0-9_$~.-])")
USERS_DIR = re.compile(r"(?i)(?:\\{1,2}|/)Users(?:\\{1,2}|/)+(?!Public\b|Default\b|All Users\b|<)[A-Za-z0-9._-]+")
MAINTAINER = re.compile(
    r"(?i)Olden Era Playtest Tweak|golden_era_release_repo|CodexSandbox|olden_port_work|homm3_scratch|"
    r"olden_mirrors|SteamLibrary(?:\\{1,2}|/)|iCloudDrive"
)
EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,24}(?![A-Za-z0-9-])")
SECRETS = [
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("google_oauth", re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}")),
    ("openai_like_key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}")),
    ("secret_field", re.compile(
        r"(?i)\"(?:api[_-]?key|apikey|secret|client[_-]?secret|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
        r"password|passwd|private[_-]?key)\"\s*:\s*\"[^\"\s]{6,}\"")),
]

WHOLE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\)")
EMBEDDED_PATH = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:(?:\\{1,2}|/)(?:[^\"\s,;()<>|]| (?=[^\s\"]*[\\/]))*")
EMBEDDED_USERS = re.compile(r"(?i)(?:\\{1,2}|/)Users(?:\\{1,2}|/)+[^\\/\"\s]+")
FIX_TRIGGER = re.compile(
    r"(?i)(?<![A-Za-z0-9_])[A-Za-z]:(?:\\{1,4}|/)[A-Za-z0-9_$~.-]|(?:\\{1,4}|/)Users(?:\\{1,4}|/)+|"
    r"Olden Era Playtest Tweak|golden_era_release_repo|CodexSandbox"
)
WHOLE_MARKERS = re.compile(r"(?i)Olden Era Playtest Tweak|golden_era_release_repo|CodexSandbox")


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def is_streaming(relpath: str) -> bool:
    return relpath.lower().startswith("payload/streaming_assets/")


# ---- fix ------------------------------------------------------------------------------------------
class Fixer:
    def __init__(self) -> None:
        self.whole = 0
        self.embedded = 0

    def string(self, s: str) -> str:
        if WHOLE_PATH.match(s) or WHOLE_MARKERS.search(s):
            self.whole += 1
            return "<sanitized-local-path>"
        out, n1 = EMBEDDED_PATH.subn("<local-path>", s)
        out, n2 = EMBEDDED_USERS.subn("/Users/<user>", out)
        self.embedded += n1 + n2
        return out

    def value(self, v):
        if isinstance(v, str):
            return self.string(v)
        if isinstance(v, list):
            return [self.value(x) for x in v]
        if isinstance(v, dict):
            return {self.string(k) if isinstance(k, str) else k: self.value(x) for k, x in v.items()}
        return v


def cmd_fix(root: Path, report: Path | None) -> int:
    changed = []
    fixer = Fixer()
    for path in sorted(root.rglob("*.json")):
        r = rel(root, path)
        if is_streaming(r):
            continue  # campaign/map JSON is not rewritten; the scan still blocks local paths there
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig", errors="replace")
        if not FIX_TRIGGER.search(text):
            continue
        try:
            data = json.loads(text)
        except ValueError as exc:
            print(f"FAIL cannot parse {r}: {exc}", file=sys.stderr)
            return 1
        before = (fixer.whole, fixer.embedded)
        clean = fixer.value(data)
        if (fixer.whole, fixer.embedded) == before:
            continue
        path.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        changed.append({"file": r, "whole": fixer.whole - before[0], "embedded": fixer.embedded - before[1]})
    # CSV side tables (for example custom_factions/*_icon_assignments.csv) can carry absolute paths too.
    for path in sorted(root.rglob("*.csv")):
        r = rel(root, path)
        if is_streaming(r):
            continue
        text = path.read_bytes().decode("utf-8-sig", errors="strict")
        if not FIX_TRIGGER.search(text):
            continue
        newline = "\r\n" if "\r\n" in text else "\n"
        before = (fixer.whole, fixer.embedded)
        rows = [[fixer.string(cell) for cell in row] for row in csv.reader(io.StringIO(text, newline=""))]
        if (fixer.whole, fixer.embedded) == before:
            continue
        buf = io.StringIO(newline="")
        csv.writer(buf, lineterminator=newline).writerows(rows)
        path.write_text(buf.getvalue(), encoding="utf-8", newline="")
        changed.append({"file": r, "whole": fixer.whole - before[0], "embedded": fixer.embedded - before[1]})
    result = {
        "schema": "nightly_payload_fix.v1",
        "filesChanged": len(changed),
        "stringsReplacedWhole": fixer.whole,
        "pathsReplacedEmbedded": fixer.embedded,
        "files": changed,
    }
    if report:
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"sanitized {len(changed)} JSON/CSV file(s): {fixer.whole} whole-path string(s), {fixer.embedded} embedded path(s)")
    return 0


# ---- scan -----------------------------------------------------------------------------------------
def mask(s: str) -> str:
    s = s.replace("\n", " ")
    return (s[:3] + "***" + s[-2:]) if len(s) > 6 else "***"


def dll_strings(data: bytes) -> str:
    ascii_runs = re.findall(rb"[\x20-\x7e]{5,}", data)
    utf16_runs = re.findall(rb"(?:[\x20-\x7e]\x00){5,}", data)
    parts = [r.decode("ascii") for r in ascii_runs]
    parts += [r.decode("utf-16-le") for r in utf16_runs]
    return "\n".join(parts)


def scan_text(text: str, terms: list[re.Pattern]) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    probe = text
    for allowed in ALLOW_SUBSTRINGS:
        probe = re.sub(re.escape(allowed), " " * len(allowed), probe, flags=re.I)

    def excerpt(m: re.Match, masked: bool) -> str:
        if masked:
            return mask(m.group(0))
        a, b = max(0, m.start() - 10), min(len(probe), m.end() + 50)
        return probe[a:b].replace("\n", " ")

    for rule, rx, masked in (("absolute_path", DRIVE_PATH, False), ("users_dir", USERS_DIR, False),
                             ("maintainer_path", MAINTAINER, False), ("email", EMAIL, True)):
        m = rx.search(probe)
        if m:
            hits.append((rule, excerpt(m, masked)))
    for rule, rx in SECRETS:
        m = rx.search(probe)
        if m:
            hits.append((rule, excerpt(m, True)))
    for rx in terms:
        m = rx.search(probe)
        if m:
            hits.append(("local_identity", excerpt(m, True)))
    return hits


def cmd_scan(root: Path, report: Path | None, raw_terms: list[str]) -> int:
    terms = []
    for t in raw_terms:
        t = (t or "").strip()
        if len(t) >= 4:
            terms.append(re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])"))
    files = 0
    total = 0
    hits = []
    skipped_binary = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            lower = name.lower()
            ext = path.suffix.lower()
            r = rel(root, path)
            if lower in FIRST_PARTY_DLLS:
                data = path.read_bytes()
                text = dll_strings(data)
            elif ext in TEXT_EXTS or lower == ".foldercache" or (ext == "" and path.stat().st_size <= EXTENSIONLESS_TEXT_MAX):
                data = path.read_bytes()
                text = data.decode("utf-8-sig", errors="replace")
                if "\x00" in text[:4096] and ext == "":
                    skipped_binary += 1
                    continue
            else:
                skipped_binary += 1
                continue
            files += 1
            total += len(data)
            for rule, ex in scan_text(text, terms):
                hits.append({"file": r, "rule": rule, "excerpt": ex})
    result = {
        "schema": "nightly_payload_scan.v1",
        "filesScanned": files,
        "bytesScanned": total,
        "binaryFilesSkipped": skipped_binary,
        "hitCount": len(hits),
        "hits": hits[:500],
    }
    if report:
        report.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"scanned {files} file(s), {total:,} bytes: {len(hits)} hit(s)")
    for h in hits[:20]:
        print(f"  HIT {h['rule']}: {h['file']}: {h['excerpt']}")
    return 1 if hits else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("fix", "scan"))
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--term", action="append", default=[], help="local identity string to forbid (repeatable)")
    args = ap.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        print(f"FAIL no such stage root: {root}", file=sys.stderr)
        return 2
    if args.mode == "fix":
        return cmd_fix(root, args.report)
    return cmd_scan(root, args.report, args.term)


if __name__ == "__main__":
    raise SystemExit(main())
