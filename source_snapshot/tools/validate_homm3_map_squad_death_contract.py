#!/usr/bin/env python3
"""HoMM3 owned skinned map squads must die the way vanilla map squads die.

Vanilla contract (docs/homm3_map_squad_death_contract.md; live Golden Era ISIL + mono demo SquadDrawer):
the map-squad drawer (live ezp, mono SquadDrawer) caches GetComponentInChildren<Animator>() of the instantiated
UnitViewConfig.mapMesh prefab once in Init. When the world squad is released as Killed (live fdh.bjiv ->
ezp.bigh, mono WorldSquad.Release -> SquadDrawer.Die) it sets trigger "die" and bool "isDead" on that Animator,
disables the squad BoxCollider and destroys the squad object after UnitViewConfig.deathTimeOffset + 2 s
(live fdl, mono WorldSquadToDestroy). Every vanilla map prefab (148/148) carries an Animator whose controller has
die (Trigger) + isDead (Bool) and an AnyState -> DYING.die 0 transition on die.

Our side: each owned skinned map prefab is a donor-map clone (hidden donor renderers stay as fog probes) with the
owned visual as its last child. Homm3ImportVisuals.BindOwnedSkinnedMapDeathAnimator removes every Animator outside
the owned visual so the drawer binds the owned one (DestroyImmediate, because the template is instantiated in the
same frame).

Source mode (always): the bind exists, uses DestroyImmediate, keeps the marker, and runs from
FinishOwnedSkinnedAdventureMapPresentation (both the create and the refresh path go through it).
Bundle mode (--bundle-dir D --name-prefix P [...], needs UnityPy): every owned skinned map bundle bound in
homm3_import.json (--import) has exactly one Animator, an owned_skinned AnimatorOverrideController over
_Battle_Unit_Anim_ctrl_v2 with die/isDead and an AnyState die transition into DYING, 21.Death overridden by a
*_Death clip, and that clip fits the vanilla destroy window (length <= deathTimeOffset + 2 from the installed
Core.zip views, --core) so the squad is not destroyed mid-fall.
Proof: source/static and generated/installed bundle readback; runtime playback on the map is not claimed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GE = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
DEFAULT_CORE = GE / "HeroesOldenEra_Data/StreamingAssets/Core.zip"
DEFAULT_IMPORT = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json"
VISUALS = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportVisuals.cs"
MARKER = "homm3.mapSquadDeath.ownedAnimatorBind.v1"
STOCK_BASE = "_Battle_Unit_Anim_ctrl_v2"
OWNED_PREFAB_SUFFIX = "/OwnedSkinned/owned_skinned.prefab"
# Vanilla SquadDrawer.GetDieDuration: deathTimeOffset + 2f (live ezp.bigp adds a constant to UnitViewConfig+0xC4).
DESTROY_PAD_SECONDS = 2.0
TRIGGER, BOOL = 9, 4


def method_body(source: str, signature: str) -> str | None:
    start = source.find(signature)
    if start < 0:
        return None
    brace = source.find("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[brace:i + 1]
    return None


def check_source(errors: list[str]) -> None:
    text = VISUALS.read_text(encoding="utf-8-sig")
    if f'"{MARKER}"' not in text:
        errors.append(f"{VISUALS.name}: marker {MARKER} is missing")
    bind = method_body(text, "static bool BindOwnedSkinnedMapDeathAnimator(")
    if bind is None:
        errors.append(f"{VISUALS.name}: BindOwnedSkinnedMapDeathAnimator is missing")
    else:
        if "UnityEngine.Object.DestroyImmediate(animator)" not in bind:
            errors.append("BindOwnedSkinnedMapDeathAnimator must DestroyImmediate donor Animators "
                          "(the template is instantiated in the same frame; a deferred Destroy leaves the donor bound)")
        if "IsUnderTransform(animator.transform, visualRoot)" not in bind:
            errors.append("BindOwnedSkinnedMapDeathAnimator must keep the Animators under the owned visual")
        if "LogError" not in bind:
            errors.append("BindOwnedSkinnedMapDeathAnimator must fail loud when the first Animator is not owned")
    finish = method_body(text, "static void FinishOwnedSkinnedAdventureMapPresentation(")
    if finish is None:
        errors.append(f"{VISUALS.name}: FinishOwnedSkinnedAdventureMapPresentation is missing")
    elif not re.search(r"\bBindOwnedSkinnedMapDeathAnimator\(shell, visual, log\);", finish):
        errors.append("FinishOwnedSkinnedAdventureMapPresentation must call BindOwnedSkinnedMapDeathAnimator(shell, visual, log)")


def load_views(core: Path) -> dict[str, dict]:
    views: dict[str, dict] = {}
    with zipfile.ZipFile(core) as z:
        for name in z.namelist():
            if "/units_views/" not in name or not name.endswith(".json"):
                continue
            doc = json.loads(z.read(name).decode("utf-8-sig"))
            for row in doc.get("array", []) if isinstance(doc, dict) else []:
                if isinstance(row, dict) and row.get("id"):
                    views[row["id"]] = row
    return views


def read_bundle(path: Path) -> dict:
    import UnityPy  # noqa: PLC0415 - optional dependency, only bundle mode needs it

    env = UnityPy.load(str(path))
    animators = 0
    overrides = []
    controllers: dict[int, object] = {}
    clips: dict[int, object] = {}
    for obj in env.objects:
        kind = obj.type.name
        if kind == "Animator":
            animators += 1
        elif kind == "AnimatorOverrideController":
            overrides.append(obj)
        elif kind == "AnimatorController":
            controllers[obj.path_id] = obj
        elif kind == "AnimationClip":
            clips[obj.path_id] = obj
    owned = [o for o in overrides if o.read().m_Name == "owned_skinned"]
    if len(owned) != 1:
        raise ValueError(f"expected one owned_skinned AnimatorOverrideController, found {len(owned)}")
    data = owned[0].read_typetree()
    base_pid = data["m_Controller"]["m_PathID"]
    base = controllers.get(base_pid)
    if base is None:
        raise ValueError("owned_skinned override base controller is not in the bundle")
    bt = base.read_typetree()
    if bt.get("m_Name") != STOCK_BASE:
        raise ValueError(f"owned_skinned override is based on {bt.get('m_Name')!r}, not {STOCK_BASE}")
    tos = {int(k): v for k, v in bt["m_TOS"]}
    ctl = bt["m_Controller"]
    params = {tos.get(v["m_ID"]): v["m_Type"] for v in ctl["m_Values"]["data"]["m_ValueArray"]}
    states: dict[int, str] = {}
    die_targets: list[int] = []
    for sm in ctl["m_StateMachineArray"]:
        smd = sm["data"]
        for st in smd["m_StateConstantArray"]:
            states[len(states)] = tos.get(st["data"]["m_FullPathID"], "")
        for tr in smd.get("m_AnyStateTransitionConstantArray", []):
            td = tr["data"]
            events = [tos.get((c.get("data") or c)["m_EventID"]) for c in td["m_ConditionConstantArray"]]
            if events == ["die"]:
                die_targets.append(td["m_DestinationState"])
    mapping: dict[str, tuple[str | None, float | None]] = {}
    for pair in data["m_Clips"]:
        orig = clips.get(pair["m_OriginalClip"]["m_PathID"])
        over = clips.get(pair["m_OverrideClip"]["m_PathID"])
        if orig is None:
            continue
        oname = orig.read().m_Name
        if over is None:
            mapping[oname] = (None, None)
            continue
        oc = over.read()
        mc = oc.m_MuscleClip
        mapping[oname] = (oc.m_Name, float(mc.m_StopTime - mc.m_StartTime))
    return {
        "animators": animators,
        "params": params,
        "dyingStates": sorted(s for s in states.values() if ".DYING." in s),
        "dieTransitions": die_targets,
        "death": mapping.get("21.Death"),
    }


def check_bundles(args, errors: list[str]) -> int:
    views = load_views(args.core)
    entries = json.loads(args.import_table.read_text(encoding="utf-8-sig"))["entries"]

    def selected(name: str) -> bool:
        return any(name == p or (p.endswith("_") and name.startswith(p)) for p in args.name_prefix)

    bundles = sorted(p for p in args.bundle_dir.iterdir() if p.is_file() and p.suffix == "" and selected(p.name))
    if not bundles:
        errors.append(f"no bundle in {args.bundle_dir} matches {args.name_prefix}")
        return 0
    checked = 0
    for path in bundles:
        rows = [e for e in entries if e.get("bundleName") == path.name
                and str(e.get("mapPrefabAssetPath", "")).endswith(OWNED_PREFAB_SUFFIX)]
        sids = sorted({sid for e in rows for sid in e.get("gameUnitSids", [])})
        if not sids:
            continue  # not an owned skinned map bundle
        try:
            info = read_bundle(path)
        except Exception as ex:  # noqa: BLE001 - reported, never swallowed
            errors.append(f"{path.name}: {ex}")
            continue
        where = path.name
        if info["animators"] != 1:
            errors.append(f"{where}: map prefab must carry exactly one Animator (the one the squad drawer binds), "
                          f"found {info['animators']}")
        if info["params"].get("die") != TRIGGER:
            errors.append(f"{where}: controller lacks Trigger 'die' (has {info['params'].get('die')!r})")
        if info["params"].get("isDead") != BOOL:
            errors.append(f"{where}: controller lacks Bool 'isDead' (has {info['params'].get('isDead')!r})")
        if not info["dyingStates"]:
            errors.append(f"{where}: controller has no DYING state")
        if not info["dieTransitions"]:
            errors.append(f"{where}: controller has no AnyState transition conditioned on 'die'")
        death = info["death"]
        if not death or not death[0]:
            errors.append(f"{where}: 21.Death is not overridden")
            continue
        clip, length = death
        if not clip.endswith("_Death"):
            errors.append(f"{where}: 21.Death plays {clip!r}, not an owned *_Death clip")
        if not length or length <= 0:
            errors.append(f"{where}: death clip {clip} has no length")
        for sid in sids:
            view = views.get(sid)
            if view is None:
                errors.append(f"{where}: unit {sid} has no units_views row in {args.core.name}")
                continue
            offset = view.get("deathTimeOffset")
            if not isinstance(offset, (int, float)):
                errors.append(f"{where}: unit {sid} view has no numeric deathTimeOffset")
                continue
            window = float(offset) + DESTROY_PAD_SECONDS
            if length and length > window + 1e-3:
                errors.append(f"{where}: unit {sid} death clip {clip} is {length:.3f}s but the map squad is destroyed "
                              f"after deathTimeOffset+{DESTROY_PAD_SECONDS:g} = {window:.3f}s")
            checked += 1
    return checked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bundle-dir", type=Path)
    ap.add_argument("--name-prefix", action="append", default=[],
                    help="exact bundle name, or a family prefix ending in '_'")
    ap.add_argument("--core", type=Path, default=DEFAULT_CORE)
    ap.add_argument("--import", dest="import_table", type=Path, default=DEFAULT_IMPORT)
    args = ap.parse_args()

    errors: list[str] = []
    check_source(errors)
    checked = 0
    if args.bundle_dir is not None:
        if not args.name_prefix:
            errors.append("--bundle-dir needs at least one --name-prefix")
        else:
            checked = check_bundles(args, errors)
    if errors:
        print(f"FAIL: HoMM3 map squad death contract ({len(errors)} error(s))")
        for e in errors:
            print("  - " + e)
        return 1
    scope = f"source + {checked} map unit(s)" if args.bundle_dir is not None else "source"
    print(f"OK: HoMM3 map squad death contract ({scope})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
