"""Re-extract every lab recipe plus new sources in ONE vanilla_ps_recipe.py call, under the shared Unity lock.

    python tools/homm3_vfx/vanilla_recipes_all.py ["<resPath>:<childPath>" ...]

vanilla_ps_recipe.py rewrites artifacts/vanilla_vfx_style/recipes/materials.json from the sources of the call it is
given, so a call with only a new source drops every other unit's materials. This wrapper rebuilds the source list from
each existing recipe's own "source" field, appends the arguments, and runs the extraction through
tools/homm3_vfx/unitylock.py. The lab stages materials.json into the Unity project, so the Unity lock keeps a rebuild
out of another agent's lab run. Use a full childPath when the root's children are inactive (the walk skips them).

Every call first renames any recipe whose file name is not recipe_key(its source) (the pre-hash naming of long
childPaths, which Unity cannot open) to its current key; `--migrate-only` does just that, under the same lock.
Proof tier: static read of the installed assets.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REC = ROOT / "artifacts/vanilla_vfx_style/recipes"
sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
from vanilla_ps_recipe import recipe_key  # noqa: E402


def migrate() -> int:
    """Rename recipes to recipe_key(source); refuse when the target holds a different source."""
    moved = 0
    for p in sorted(REC.glob("*.json")):
        if p.name == "materials.json":
            continue
        src = json.loads(p.read_text(encoding="utf-8"))["source"]
        dst = REC / (recipe_key(src) + ".json")
        if dst == p:
            continue
        if dst.exists():
            other = json.loads(dst.read_text(encoding="utf-8"))["source"]
            if other != src:
                raise SystemExit(f"FAIL: {dst.name} holds {other}, not {src}")
            p.unlink()   # same source already under its current key: the legacy copy is a duplicate
        else:
            p.rename(dst)
        moved += 1
        print(f"migrated {p.name} -> {dst.name}")
    return moved


def main() -> int:
    if sys.argv[1:] == ["--migrate-only"]:
        cmd = [sys.executable, str(ROOT / "tools/homm3_vfx/unitylock.py"), "run", "--wait", "60", "--",
               sys.executable, __file__, "--migrate-locked"]
        return subprocess.run(cmd, cwd=ROOT).returncode
    if sys.argv[1:] == ["--migrate-locked"]:
        print(f"vanilla_recipes_all: {migrate()} recipe(s) renamed")
        return 0
    migrate()
    known = [json.loads(p.read_text(encoding="utf-8"))["source"]
             for p in sorted(REC.glob("*.json")) if p.name != "materials.json"]
    sources = list(dict.fromkeys(known + sys.argv[1:]))
    print(f"vanilla_recipes_all: {len(known)} existing + {len(sources) - len(known)} new source(s)")
    cmd = [sys.executable, str(ROOT / "tools/homm3_vfx/unitylock.py"), "run", "--wait", "60", "--",
           sys.executable, str(ROOT / "tools/homm3_vfx/vanilla_ps_recipe.py"), str(REC)] + sources
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
