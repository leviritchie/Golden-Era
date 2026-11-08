#!/usr/bin/env python3
"""Validate that the unit detail preview shows the owned skinned bundle prefab, not the donor.

The unit detail window (``BhUnitWindow`` -> ``BhUnitWindowPreview.Show(UnitViewConfig)``) is the
one 3D preview surface every detail entry point shares (battle, army/hero screen, town garrison,
adventure-map stack, hire-window info). Native ``Show`` calls the factory
``bewc(UnitViewConfig.id, Transform)``; the plugin aliases a custom ``h3_*`` id to its donor so the
native factory builds a real preview rig, then swaps the rig's ``Model`` for the owned skinned
battle prefab. Two things must hold for that swap to happen:

1. Source contract: the Show postfix keys the swap on the id the native factory received
   (recorded on the Show frame). The managed ``GetConfigElementId(UnitViewConfig)`` read returns
   null on live Golden Era, and keying on it alone made every custom unit fall through to the
   native-donor branch (LogOutput 2026-09-25: donor alias for h3_sea_witch_upg_alt followed by
   "restored ... native renderer(s) for native key='Humans/1Prefabs/lightweaver_upg_alt'").
2. Data coverage: every owned skinned ``homm3_import.json`` unit SID has a donor in the custom
   faction registry; without one the native factory cannot build a rig and the preview is empty.
   An owned unit outside every faction (a neutral) instead names a preview-only native donor on
   its import row, ``previewDonorSid``, which must equal the leaf of its
   ``battlePresentationResPath`` (the native prefab already used as its presentation fallback),
   must be a native id (no ``h3_`` prefix) and must not be set on a unit that has a registry donor.

Proof tier: source/static and generated-data only. Runtime display is proven only by an in-game
detail-window check.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
PREVIEW_HOOK = PLUGIN / "Homm3ImportUnitPreviewModelHook.cs"
GAME_SYMBOLS = PLUGIN / "GameSymbols.cs"
REGISTRY = PLUGIN / "Homm3CustomFactionRegistry.cs"
SOURCE_IMPORT = PLUGIN / "homm3_import.json"
SOURCE_FACTIONS = ROOT / "custom_factions"
UNIT_SUFFIXES = ("", "_upg", "_upg_alt")

# Owned skinned units with no faction donor. The native preview factory has no donor rig for
# them, so their detail preview stays empty and the plugin logs an error at runtime. Pinned so a
# new gap (or a fixed one) fails this gate and gets looked at instead of drifting.
KNOWN_NO_DONOR_SIDS = frozenset(
    {
        "h3_fangarm",
        "h3_leprechaun",
        "h3_satyr",
        "h3_steel_golem",
    }
)

REQUIRED_SOURCE = (
    ("RecordShowFactoryCustomKey(customKey);", "factory prefix must record the native id on the Show frame"),
    ("PushShowFrame(__state);", "Show prefix must open a Show frame"),
    ("PopShowFrame(__state);", "Show finalizer (last consumer) must close the Show frame"),
    ("var key = ResolveShowPreviewKey(__state, viewConfig);", "Show postfix/finalizer must key on ResolveShowPreviewKey"),
    ("return state.FactoryCustomKey;", "the factory-recorded key must win over the managed view-config read"),
    ("TryPrepareOwnedSkinnedPreview(key, instance, vanilla);", "the owned skinned preview must take the native preview model as its Hex/Lit donor"),
    ("PrepareOwnedSkinnedIdleInstance(instance, bySid, Plugin.LogSource, hexLitDonor);", "owned skinned preview prepare must forward the Hex/Lit donor"),
    ("LogOwnedSkinnedPreviewRefused(", "an owned skinned preview that cannot swap must log an error"),
    ("Homm3OwnedSkinnedPreviewFraming.TryFrame(instance, entry, vanilla, keepPose, 0f, source, Plugin.LogSource);", "owned skinned preview must be framed by its own battle size at the native mesh pose"),
    ("&& !Homm3ImportVisuals.TryGetPreviewDonorSidForUnitSid(customKey, Plugin.LogSource, out donorSid))",
     "a unit without a registry donor must alias the preview factory to its import row's previewDonorSid"),
    # Town hire screen (large 3D recruit panel): BhHireUnitItemView.tvn builds its wrappers from the
    # BhUnitPreviews per-sid pool; the per-item tvp is inlined natively, so only tvn is a live surface.
    ("() => TryPatchHireItemModelList(h, log));", "the hire-screen model list postfix must be a required registration"),
    ("GameSymbols.UnitPreview.HireItemModelList;", "hire model list method must resolve through GameSymbols"),
    ("GameSymbols.UnitPreview.HireItemModelListFields", "hire wrapper list field must resolve through GameSymbols"),
    ("nameof(PostfixBhHireUnitItemViewModelList)", "hire model list must be patched with the owned skinned swap postfix"),
    ("if (ApplyOwnedSkinnedHireModel(wrapper, key, source))", "each hire wrapper carrying an owned skinned sid must be swapped"),
    ("ExecuteReplaceReflectedPreview(wrapper, key, source, template);", "hire swap must run synchronously (before native UpdateView frames/animates the Model)"),
    ("TryIsSharedPreviewPrefabByNativePointer(wrapper, out var isSharedPrefab, out var sharedCheckFailure)",
     "hire swap must refuse the BhUnitPreviews shared prefab (native pointer identity), failing closed when unreadable"),
    ("GetStaticMemberValue(typeof(BhUnitPreviews), GameSymbols.UnitPreview.SharedPreviewsInstanceMembers)",
     "the BhUnitPreviews singleton must be read by reflection over live interop names"),
    ("no hire preview wrapper carried this sid after the native list build", "an owned sid the hire list did not swap must log an error"),
    ("Register(h, log, includeRecruitmentPreviewFactories: false, required: true);",
     "release registration must not patch the shared BhUnitPreviews.htv cache factory (broke the adventure HUD)"),
)

REQUIRED_GAME_SYMBOLS = (
    ('"unitPreview.hireItem.modelList"', "hire model list symbol id"),
    ('"Method_Public_Void_IReadOnlyList_1_String_0", "tvn"', "hire model list live interop name + decomp name"),
    ('"field_Private_List_1_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_0", "bzii"', "hire wrapper list field names"),
    ('"field_Public_Static_BhUnitPreviews_0", "me"', "BhUnitPreviews singleton live interop name first"),
)

FORBIDDEN_SOURCE = (
    ("var key = __state?.CustomKey ?? PreviewKeyFromViewConfig(viewConfig);",
     "keying the detail preview on the managed view-config id regresses every custom unit to its donor"),
    ("BhUnitPreviews.me",
     "the deobf 'me' accessor does not exist on live Golden Era interop (MissingMethodException 2026-09-26)"),
    ("QueueOrRun(log, () => ExecuteReplaceReflectedPreview(wrapper",
     "deferring the hire swap lets native UpdateView frame and animate the donor model"),
)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001 - surfaced as a gate failure
        raise SystemExit(f"FAIL: cannot parse {path}: {exc}")


def registry_donor_map(factions_dir: Path) -> dict[str, str]:
    """Mirror Homm3CustomFactionRegistry.BuildCustomToDonor for manifests + extra mappings."""
    donors: dict[str, str] = {}
    manifests = sorted(factions_dir.glob("homm3_*.json"))
    if not manifests:
        raise SystemExit(f"FAIL: no homm3_*.json faction manifests under {factions_dir}")
    for manifest_path in manifests:
        manifest = load_json(manifest_path)
        if not isinstance(manifest, dict) or "unitLines" not in manifest:
            continue
        for key in ("unitLines", "additionalRecruitmentLines"):
            for line in manifest.get(key) or []:
                base = line["baseSid"]
                donor = line["donorBaseSid"]
                variants = line.get("variantSids") or {}
                for suffix in UNIT_SUFFIXES:
                    sid = base if suffix == "" else (variants.get(suffix) or base + suffix)
                    donors[sid] = donor + suffix
    registry = REGISTRY.read_text(encoding="utf-8", errors="replace")
    block = re.search(r"ExtraUnitDonorMappings\s*=\s*\{(.*?)\};", registry, re.S)
    if not block:
        raise SystemExit(f"FAIL: {REGISTRY}: ExtraUnitDonorMappings initializer not found")
    for custom, donor in re.findall(r'new\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)', block.group(1)):
        donors[custom] = donor
    return donors


def presentation_leaf(res_path: str) -> str:
    leaf = res_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if leaf.endswith(".prefab"):
        leaf = leaf[: -len(".prefab")]
    return leaf


def owned_skinned_sids(
    import_path: Path, bundle_dir: Path | None, preview_donors: dict[str, str] | None = None, errors: list[str] | None = None
) -> tuple[set[str], list[str]]:
    data = load_json(import_path)
    sids: set[str] = set()
    missing_bundles: list[str] = []
    for entry in data.get("entries") or []:
        donor = entry.get("previewDonorSid")
        if donor is None or preview_donors is None:
            continue
        unit_sids = [s for s in entry.get("gameUnitSids") or [] if s]
        leaf = presentation_leaf(entry.get("battlePresentationResPath") or "")
        if not isinstance(donor, str) or not donor.strip() or donor.startswith("h3_") or donor != leaf:
            if errors is not None:
                errors.append(
                    f"{', '.join(unit_sids) or '?'}: previewDonorSid {donor!r} must be the native id at the leaf of "
                    f"battlePresentationResPath ({leaf!r})"
                )
            continue
        for sid in unit_sids:
            preview_donors[sid] = donor
    for entry in data.get("entries") or []:
        paths = (entry.get("battlePrefabAssetPath") or "", entry.get("mapPrefabAssetPath") or "")
        if not any("/ownedskinned/" in p.replace("\\", "/").lower() for p in paths):
            continue
        if bundle_dir is not None:
            bundle = entry.get("bundleName") or ""
            if not bundle or not (bundle_dir / bundle).is_file():
                missing_bundles.append(f"{bundle or '?'} ({', '.join(entry.get('gameUnitSids') or [])})")
                continue
        sids.update(s for s in entry.get("gameUnitSids") or [] if s)
    return sids, missing_bundles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--installed-plugin-dir",
        type=Path,
        help="Read-only: check the installed plugin's homm3_import.json/custom_factions and count only "
        "units whose skinned bundle is present under homm3_bundles/.",
    )
    args = parser.parse_args()

    errors: list[str] = []
    source = PREVIEW_HOOK.read_text(encoding="utf-8", errors="replace")
    for text, why in REQUIRED_SOURCE:
        if text not in source:
            errors.append(f"{PREVIEW_HOOK.name}: missing {text!r} ({why})")
    for text, why in FORBIDDEN_SOURCE:
        if text in source:
            errors.append(f"{PREVIEW_HOOK.name}: forbidden {text!r} ({why})")
    symbols = GAME_SYMBOLS.read_text(encoding="utf-8", errors="replace")
    for text, why in REQUIRED_GAME_SYMBOLS:
        if text not in symbols:
            errors.append(f"{GAME_SYMBOLS.name}: missing {text!r} ({why})")

    if args.installed_plugin_dir:
        plugin_dir = args.installed_plugin_dir
        import_path = plugin_dir / "homm3_import.json"
        factions_dir = plugin_dir / "custom_factions"
        bundle_dir = plugin_dir / "homm3_bundles"
        label = f"installed {plugin_dir}"
    else:
        import_path, factions_dir, bundle_dir = SOURCE_IMPORT, SOURCE_FACTIONS, None
        label = "source"

    donors = registry_donor_map(factions_dir)
    preview_donors: dict[str, str] = {}
    sids, missing_bundles = owned_skinned_sids(import_path, bundle_dir, preview_donors, errors)
    doubled = sorted(sid for sid in preview_donors if sid in donors)
    if doubled:
        errors.append("previewDonorSid set on unit(s) that already have a registry donor (one donor source only): " + ", ".join(doubled))
    donors = {**preview_donors, **donors}
    no_donor = {sid for sid in sids if sid not in donors}
    new_gaps = sorted(no_donor - KNOWN_NO_DONOR_SIDS)
    closed_gaps = sorted((KNOWN_NO_DONOR_SIDS - no_donor) & sids) if bundle_dir is None else []
    if new_gaps:
        errors.append(
            "owned skinned unit(s) without a registry donor or import-row previewDonorSid (native preview factory cannot build a rig): "
            + ", ".join(new_gaps)
        )
    if closed_gaps:
        errors.append("KNOWN_NO_DONOR_SIDS pins units that now have a donor; remove them: " + ", ".join(closed_gaps))

    if errors:
        for error in errors:
            print("FAIL:", error)
        return 1
    print(
        f"OK: owned skinned detail preview contract ({label}): {len(sids)} owned skinned unit SID(s), "
        f"{len(sids) - len(no_donor)} with a preview donor ({len(set(preview_donors) & sids)} via previewDonorSid), known no-donor gap(s)={sorted(no_donor)}"
        + (f", entries without an installed bundle={len(missing_bundles)}" if bundle_dir is not None else "")
        + "."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
