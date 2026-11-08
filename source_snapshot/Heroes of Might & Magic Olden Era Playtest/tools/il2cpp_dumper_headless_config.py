"""Set Il2CppDumper config.json RequireAnyKey=false for headless/CI runs."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: il2cpp_dumper_headless_config.py <playtest_root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    p = root / "tools" / "il2cpp_dumper" / "config.json"
    if not p.is_file():
        return 0
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    if data.get("RequireAnyKey") is False:
        return 0
    data["RequireAnyKey"] = False
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {p}: RequireAnyKey=false (non-interactive exit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
