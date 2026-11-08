"""Promote vanilla-style drafts into shipped specs (the draft -> units/ step of the effects rollout).

    python tools/homm3_vfx/promote_vanilla_style.py <labSid>[:<source unit>] ...            # dry run (default)
    python tools/homm3_vfx/promote_vanilla_style.py <labSid>... --apply stage                # move draft -> units/
    python tools/homm3_vfx/promote_vanilla_style.py <labSid>... --apply compile              # after the freeze

A promotion is three steps. No step does another's job:

  1. stage   (this tool): move tools/homm3_vfx/vanilla_style/drafts/<lab>.json to units/<lab>.json.
  2. freeze  (fleet: tools/homm3_def_retarget_delivery/freeze_slice.py): finds units/<lab>.json and writes the row as
             vfxAuthority vanilla_style + albedo basecolor + vanillaStyleSpec (freeze_slice.vanilla_style_row).
  3. compile (this tool): refuses unless the frozen row carries exactly that authority/albedo/spec, then runs
             vanilla_style_fx compile for the unit and the full `check`.

`vanilla_style_fx.py check` is red from step 1 until step 3: a spec in units/ must be compiled and its row flipped.
Run all three in one sitting.

The dry run writes nothing. Per unit it fails closed on the first mismatch and runs:
  - the draft exists, no shipped spec shadows it, and it names this labSid;
  - freeze_slice.vanilla_style_row(lab, draft, layers), the SAME function the freeze calls, where layers is the look
    manifest the next freeze copies (artifacts/homm3_unit_look/<source unit>/vfx/vfx_manifest.json);
  - the currently frozen manifest (<selection out>/<lab>/inputs/vfx/vfx_manifest.json) gets the same check when the
    unit already has a row, so a draft that only fits a newer look is reported rather than discovered at freeze;
  - vanilla_style_fx plan: the delivery row's gameSid is in gameUnitSids (the runtime matches by game sid), every
    bone is a delivered joint, and every window resolves to a stock animator state.

Proof tier: source/static + generated artifact. Nothing here builds, freezes, deploys or launches anything.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/homm3_vfx"))
sys.path.insert(0, str(ROOT / "tools/homm3_def_retarget_delivery"))
import vanilla_style_fx as vs  # noqa: E402

LOOK = ROOT / "artifacts/homm3_unit_look"


class PromoteError(Exception):
    pass


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def manifest_layers(p: Path) -> dict:
    if not p.is_file():
        raise PromoteError(f"no look manifest {vs.rel(p)}")
    return {k: v["type"] for k, v in load(p).get("layers", {}).items()}


def freeze_accepts(lab: str, spec_path: Path, layers: dict, what: str) -> dict:
    import freeze_slice  # noqa: E402  (fleet-owned; imported, never edited)
    try:
        return freeze_slice.vanilla_style_row(lab, spec_path, layers)
    except SystemExit as e:
        raise PromoteError(f"freeze would refuse against the {what}: {e}") from None


def selection_row(spec: dict, lab: str) -> tuple[dict, dict | None]:
    sel = load(ROOT / spec["delivery"]["selection"])
    return sel, next((r for r in sel["units"] if r["labSid"] == lab), None)


def dry_run(lab: str, source: str) -> None:
    draft = vs.DRAFT_DIR / f"{lab}.json"
    shipped = vs.SPEC_DIR / f"{lab}.json"
    if not draft.is_file():
        raise PromoteError(f"no draft {vs.rel(draft)}")
    if shipped.exists():
        raise PromoteError(f"{vs.rel(shipped)} already exists")
    spec = load(draft)
    if spec.get("unit") != lab:
        raise PromoteError(f"draft names unit {spec.get('unit')!r}")
    pending = vs.pending_lanes(spec)
    if pending:
        raise PromoteError(f"layer type(s) {pending} have no end-to-end runtime lane yet; the draft is lab-only")
    live = manifest_layers(LOOK / source / "vfx/vfx_manifest.json")
    facts = freeze_accepts(lab, draft, live, f"live look manifest ({source})")
    print(f"  freeze check (live look {source}): ok, supersedes {len(facts['superseded'])} layer(s)")
    sel, row = selection_row(spec, lab)
    if row is None:
        print(f"  no row in {spec['delivery']['selection']} yet: the freeze adds it; plan skipped")
        return
    frozen = ROOT / sel["out"] / lab / "inputs/vfx/vfx_manifest.json"
    if frozen.is_file():
        if manifest_layers(frozen) != live:
            print("  NOTE: the frozen look manifest's layer set differs from the live look; the next freeze uses live")
        freeze_accepts(lab, draft, manifest_layers(frozen), "currently frozen manifest")
        print("  freeze check (currently frozen manifest): ok")
    # plan against the frozen row: game sid, joints, stock states (vanilla_style_fx.delivery_facts/build_rows)
    df = vs.delivery_facts(lab, spec)
    emission = {l["id"]: (f"{lab}__{l['id']}.png", "<not built>") for l in spec["layers"] if l["type"] == "emissionMap"}
    # the COLOR_0 bake is made by compile from the frozen GLB; the plan only needs its row shape
    bakes = {l["id"]: {"outGlbSha256": "<not built>"} for l in spec["layers"] if l["type"] == "bodyDisplacement"}
    rows = vs.build_rows(lab, spec, df, emission, bakes)
    print(f"  plan: {len(rows)} catalog row(s) for gameSid {row['gameSid']}; row today: "
          f"{row.get('vfxAuthority', 'unit_look')}/{row.get('albedo')}")


def stage(lab: str) -> None:
    draft, shipped = vs.DRAFT_DIR / f"{lab}.json", vs.SPEC_DIR / f"{lab}.json"
    shutil.move(str(draft), str(shipped))
    print(f"  staged {vs.rel(shipped)}; next: freeze_slice.py (fleet), then --apply compile")


def compile_unit(lab: str) -> None:
    shipped = vs.SPEC_DIR / f"{lab}.json"
    if not shipped.is_file():
        raise PromoteError(f"not staged: {vs.rel(shipped)} missing")
    spec = load(shipped)
    _, row = selection_row(spec, lab)
    want = {"vfxAuthority": "vanilla_style", "albedo": "basecolor", "vanillaStyleSpec": vs.rel(shipped)}
    got = {k: (row or {}).get(k) for k in want}
    if got != want:
        raise PromoteError(f"the frozen row is {got}, not {want}: run the freeze first")
    vs.cmd_compile(lab)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("units", nargs="+", help="<labSid> or <labSid>:<source unit> when the look lives under another id")
    ap.add_argument("--apply", choices=("stage", "compile"))
    a = ap.parse_args()
    failed = []
    for arg in a.units:
        lab, _, source = arg.partition(":")
        print(f"{lab}:")
        try:
            if a.apply == "compile":
                compile_unit(lab)
            else:
                dry_run(lab, source or lab)       # stage always re-runs the dry run first
                if a.apply == "stage":
                    stage(lab)
        except (PromoteError, vs.VsError) as e:
            print(f"  FAIL: {e}")
            failed.append(lab)
    if a.apply == "compile" and not failed:
        print("check: ok " + ",".join(vs.check()))
    print(f"promote ({a.apply or 'dry run'}): {len(a.units) - len(failed)} ok, {len(failed)} failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
