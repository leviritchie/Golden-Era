#!/usr/bin/env python3
"""Unit test for town_full3d_fork (candidate-init's seed inheritance): pins arrive byte-identical, the catalog arrives
without its bundle keys, a seed without them forks cleanly, a failed copy refuses the fork, and carry_catalog never
carries bundle keys or overwrites a produced block. python test_town_full3d_fork.py"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_fork as FK  # noqa: E402


def _seed(root: Path, with_pins: bool = True) -> Path:
    s = root / "seed"
    (s / "work" / "props").mkdir(parents=True)
    (s / "bundle").mkdir(parents=True)
    if with_pins:
        (s / "work" / "building_depth.json").write_text('{"mode": "contact_v1"}', encoding="utf-8")
        (s / "work" / "props" / "placement.json").write_text('{"instances": []}', encoding="utf-8")
        (s / "work" / "closing_walls.npz").write_bytes(b"\x00\x01npz")
        (s / "bundle" / "catalog.json").write_text(json.dumps(
            {"layers": [], "props": {"schema": "town_t2_props.v1"}, "bundleBytes": 7, "bundleSha256": "ab"}),
            encoding="utf-8")
    return s


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        s = _seed(root)
        work, out = root / "fork" / "work", root / "fork" / "bundle"
        r = FK.fork_seed_state(s, work, out)
        assert r["pins"] == list(FK.SEED_PINS), r
        for rel in FK.SEED_PINS:
            assert (work / rel).read_bytes() == (s / "work" / rel).read_bytes(), rel
        cat = json.loads((out / "catalog.json").read_text(encoding="utf-8"))
        assert "props" in cat and not (set(cat) & FK.BUNDLE_KEYS), cat
        assert r["droppedCatalogKeys"] == ["bundleBytes", "bundleSha256"], r

        bare = _seed(root / "b", with_pins=False)
        r = FK.fork_seed_state(bare, root / "b" / "fork" / "work", root / "b" / "fork" / "bundle")
        assert r == {"pins": [], "catalog": False, "droppedCatalogKeys": []}, r
        assert not (root / "b" / "fork" / "bundle" / "catalog.json").exists()

        orig = shutil.copy2
        shutil.copy2 = lambda a, b: Path(b).write_bytes(b"truncated")     # a copy that does not arrive intact
        try:
            FK.fork_seed_state(s, root / "c" / "work", root / "c" / "bundle")
            raise AssertionError("a corrupted pin copy must refuse the fork")
        except SystemExit as e:
            assert "byte-identical" in str(e), e
        finally:
            shutil.copy2 = orig

        def boom(a, b):
            raise PermissionError("denied")
        shutil.copy2 = boom
        try:
            FK.fork_seed_state(s, root / "d" / "work", root / "d" / "bundle")
            raise AssertionError("a failed pin copy must refuse the fork")
        except SystemExit as e:
            assert "could not be copied" in str(e), e
        finally:
            shutil.copy2 = orig

        new = {"layers": [1], "skyLook": {}}
        carried = FK.carry_catalog(new, {"layers": [0], "props": {"p": 1}, "bundleSha256": "x"})
        assert carried == ["props"] and new["layers"] == [1] and "bundleSha256" not in new, (carried, new)
        # catalog_carry: the rule write_catalog(sc, carry=...) applies
        prev = {"layers": [0], "props": {"p": 1}, "houses": {"h": 1}, "buildingDepth": {"stale": 1},
                "bundleSha256": "x"}
        new = {"layers": [1]}
        try:
            FK.catalog_carry(dict(new), prev, "previous", owned={"buildingDepth"})
            raise AssertionError("an owned block the write no longer produces must refuse")
        except SystemExit as e:
            assert "no longer produces" in str(e), e
        got = FK.catalog_carry(new, prev, "previous", owned={"buildingDepth"}, drop=("houses", "buildingDepth"))
        assert got == ["props"] and new == {"layers": [1], "props": {"p": 1}}, (got, new)
        for mode, prv, msg in (("previous", None, "no previous catalog"), ("fresh", prev, "would drop"),
                               ("carry", prev, "must be one of")):
            try:
                FK.catalog_carry({"layers": [], "buildingDepth": {}}, prv, mode, owned={"buildingDepth"})
                raise AssertionError(f"{mode} must refuse")
            except SystemExit as e:
                assert msg in str(e), e
        assert FK.catalog_carry({"layers": []}, None, "fresh") == []
        assert FK.catalog_carry({"layers": [], "buildingDepth": 3}, {"buildingDepth": 1, "bundleBytes": 2}, "fresh",
                                owned={"buildingDepth"}) == []

    # write_catalog takes a required keyword carry, and every call site in this folder passes it, so no step can
    # rewrite a catalog without declaring how it meets the previous one (redepth used to drop the props block)
    import ast
    here = Path(__file__).resolve().parent
    tree = ast.parse((here / "stronghold_full3d_scene.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "write_catalog")
    kw = [a.arg for a in fn.args.kwonlyargs]
    assert "carry" in kw and fn.args.kw_defaults[kw.index("carry")] is None, "write_catalog: carry must be required"
    calls = 0
    for f in sorted(here.glob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8-sig"))):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) == "write_catalog":
                calls += 1
                assert any(k.arg == "carry" for k in n.keywords), f"{f.name}:{n.lineno} write_catalog without carry"
    assert calls >= 20, calls
    print("town_full3d_fork: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
