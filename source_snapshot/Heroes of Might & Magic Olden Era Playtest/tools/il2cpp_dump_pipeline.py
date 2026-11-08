"""
Il2CppDumper pipeline for HeroesOE (IL2CPP): download tool, dump GameAssembly + metadata, grep hints.

Usage (from repo / playtest folder):
  python tools/il2cpp_dump_pipeline.py download
  python tools/il2cpp_dump_pipeline.py run
  python tools/il2cpp_dump_pipeline.py search --patterns BhCityUISession ObjCityConfig fraction

Notes:
  - Il2CppDumper may exit non-zero after "Done!" (Console.ReadKey in non-TTY). Output is still valid if dump.cs exists.
  - dump.cs is pseudocode; faction ids often come from Core.zip JSON at runtime, not string literals in dump.cs.
  - tools/il2cpp_dumper/ and tools/il2cpp_out/ are gitignored (large binaries / generated dumps).
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

PLAYTEST_ROOT = Path(__file__).resolve().parents[1]

ZIP_URL = "https://github.com/Perfare/Il2CppDumper/releases/download/v6.7.46/Il2CppDumper-win-v6.7.46.zip"
ZIP_NAME = "Il2CppDumper-win-v6.7.46.zip"

GAME_ASM = PLAYTEST_ROOT / "GameAssembly.dll"
METADATA = PLAYTEST_ROOT / "HeroesOE_Data" / "il2cpp_data" / "Metadata" / "global-metadata.dat"

TOOLS = PLAYTEST_ROOT / "tools"
# Zip extracts flat (Il2CppDumper.exe at archive root).
DUMPER_HOME = TOOLS / "il2cpp_dumper"
OUT_DIR = TOOLS / "il2cpp_out"
DEFAULT_DUMP_CS = OUT_DIR / "dump.cs"
DEFAULT_STRINGLITERAL = OUT_DIR / "stringliteral.json"


def download() -> None:
    TOOLS.mkdir(parents=True, exist_ok=True)
    dest_zip = TOOLS / "il2cpp_dumper" / ZIP_NAME
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    if DUMPER_HOME.is_dir() and (DUMPER_HOME / "Il2CppDumper.exe").is_file():
        print(f"Already present: {DUMPER_HOME / 'Il2CppDumper.exe'}")
        return

    print(f"Downloading {ZIP_URL} …")
    urllib.request.urlretrieve(ZIP_URL, dest_zip)
    print(f"Extracting into {DUMPER_HOME} …")
    DUMPER_HOME.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "r") as zf:
        zf.extractall(DUMPER_HOME)
    exe = DUMPER_HOME / "Il2CppDumper.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"Expected {exe} after extract")
    print(f"OK: {exe}")


def run_dump(out_dir: Path | None = None) -> None:
    out = (out_dir or OUT_DIR).resolve()

    exe = DUMPER_HOME / "Il2CppDumper.exe"
    if not exe.is_file():
        print("Run: python tools/il2cpp_dump_pipeline.py download", file=sys.stderr)
        sys.exit(1)
    if not GAME_ASM.is_file():
        print(f"Missing {GAME_ASM}", file=sys.stderr)
        sys.exit(1)
    if not METADATA.is_file():
        print(f"Missing {METADATA}", file=sys.stderr)
        sys.exit(1)

    out.mkdir(parents=True, exist_ok=True)
    # stdin newline sometimes avoids ReadKey hang; crash after Done may still occur - ignore if dump.cs exists.
    proc = subprocess.run(
        [str(exe), str(GAME_ASM), str(METADATA), str(out)],
        cwd=str(DUMPER_HOME),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    dump_cs = out / "dump.cs"
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if dump_cs.is_file():
        print(f"\nOK: {dump_cs} ({dump_cs.stat().st_size / 1024 / 1024:.1f} MB)")
    else:
        print(f"\nFAILED: no {dump_cs} (exit {proc.returncode})", file=sys.stderr)
        sys.exit(proc.returncode or 1)


def search(patterns: list[str], dump_path: Path | None) -> None:
    dump = dump_path or DEFAULT_DUMP_CS
    if not dump.is_file():
        print(f"Missing {dump}; run: python tools/il2cpp_dump_pipeline.py run", file=sys.stderr)
        sys.exit(1)

    text = dump.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    for pat in patterns:
        rx = re.compile(re.escape(pat), re.IGNORECASE)
        hits = [i for i, ln in enumerate(lines, 1) if rx.search(ln)]
        print(f"\n=== {pat!r} - {len(hits)} line(s) ===")
        for i in hits[:80]:
            snippet = lines[i - 1][:200]
            print(f"  L{i}: {snippet}")
        if len(hits) > 80:
            print(f"  … {len(hits) - 80} more")


def search_literals(path: Path | None) -> None:
    p = path or DEFAULT_STRINGLITERAL
    if not p.is_file():
        print(f"Missing {p}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(p.read_text(encoding="utf-8"))
    keys = ("dungeon", "cityDungeon", "human", "undead", "homm3", "fraction")
    print(f"{p.name}: {len(data)} entries")
    for k in keys:
        rows = [x["value"] for x in data if k.lower() in x["value"].lower()]
        print(f"\n--- substring {k!r} ({len(rows)}) ---")
        for v in rows[:25]:
            print(" ", repr(v)[:160])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("download", help="Fetch Il2CppDumper Windows zip into tools/il2cpp_dumper/")

    p_run = sub.add_parser("run", help="Run Il2CppDumper → tools/il2cpp_out/")
    p_run.add_argument("--out", type=Path, help="Override output dir (default: tools/il2cpp_out)")

    p_se = sub.add_parser("search", help="Grep line numbers in dump.cs for each pattern")
    p_se.add_argument("--dump", type=Path, help="Path to dump.cs")
    p_se.add_argument(
        "patterns",
        nargs="+",
        help="Substrings to search (e.g. BhCityUISession ObjCityConfig)",
    )

    p_sl = sub.add_parser(
        "search-literals",
        help="Search stringliteral.json for substring hints (game strings often not present)",
    )
    p_sl.add_argument("--literal-json", type=Path, dest="literal_json", help="Path to stringliteral.json")

    args = ap.parse_args()
    if args.cmd == "download":
        download()
    elif args.cmd == "run":
        o = getattr(args, "out", None)
        run_dump(o.resolve() if o else None)
    elif args.cmd == "search":
        search(args.patterns, args.dump)
    elif args.cmd == "search-literals":
        search_literals(args.literal_json)


if __name__ == "__main__":
    main()
