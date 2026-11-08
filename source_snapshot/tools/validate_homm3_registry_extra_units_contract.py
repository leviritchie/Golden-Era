"""Every extra unit sid in Homm3CustomFactionRegistry must have a bundled battle import row.

ExtraUnitDonorMappings feeds EnumerateCustomUnitSids, and the main-menu preloader requires a
recruitment-portrait idle clip, resolved through a homm3_import.json row with a bundleName, for
every sid it returns. It fails closed and terminates the game. On 2026-09-29 a retired h3_cannon
left in this list crashed Golden Era on launch after its bundle and import row were removed.
This gate moves that failure to build time.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PLUGIN_DIR = Path("Heroes of Might & Magic Olden Era Playtest") / "OfflineUnlockMod"
BLOCK_RE = re.compile(r"ExtraUnitDonorMappings\s*=\s*(.*?);", re.S)
SID_RE = re.compile(r'new\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()
    plugin = Path(args.repo_root) / PLUGIN_DIR
    source = (plugin / "Homm3CustomFactionRegistry.cs").read_text(encoding="utf-8")
    block = BLOCK_RE.search(source)
    if block is None:
        print("error: ExtraUnitDonorMappings declaration not found in Homm3CustomFactionRegistry.cs")
        return 1
    sids = [m.group(1) for m in SID_RE.finditer(block.group(1))]
    entries = json.loads((plugin / "homm3_import.json").read_text(encoding="utf-8"))["entries"]
    bundled = {sid for e in entries if e.get("bundleName") for sid in (e.get("gameUnitSids") or [])}
    errors = [f"extra registry unit '{sid}' has no bundled homm3_import.json row; startup would fail closed"
              for sid in sids if sid not in bundled]
    for e in errors:
        print("error: " + e)
    print(f"homm3 registry extra units contract: {len(sids)} extra sid(s), {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
