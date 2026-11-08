#!/usr/bin/env python3
"""
Build a broad, falsifiable semantic map between the old Mono demo Hex.dll and
current Golden Era Cpp2IL DiffableCs shells.

This is a static evidence tool. It does not load game runtime objects, patch
methods, or claim runtime proof. It compares metadata shape, names that survived
between builds, and focused mod-relevant surfaces.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

import dnfile

DEFAULT_MONO_HEX = Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data\Managed\Hex.dll")
DEFAULT_EXTRA_MONO_ASSEMBLIES = (
    Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data\Managed\Hex.ResManager.dll"),
    Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data\Managed\Hex.Sound.Runtime.dll"),
    Path(r"V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data\Managed\Hex.Utils.dll"),
)
DEFAULT_DIFFABLE_ROOT = Path("tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs")
DEFAULT_OUT_JSON = Path("experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.json")
DEFAULT_OUT_MD = Path("docs/mono_deobf_semantic_map.md")

PRIORITY_TYPES = (
    "Hex.Session.Battle.BhSelectedUnitHud",
    "Hex.Session.Battle.BhUnitControlsView",
    "Hex.Session.Battle.BhUnitAbilityView",
    "Hex.Session.Battle.BhBattleQueueView",
    "Hex.Session.Battle.BhTurnView",
    "Hex.Session.Battle.BhSelectedUnitView",
    "Hex.Session.Battle.BattleEventArgs",
    "Hex.Session.Battle.HotkeyAbilityArgs",
    "Hex.Session.World.Minimap",
    "Hex.Session.World.SoMinimapConfig",
    "Hex.Render.SoTerrainMaterial",
    "Hex.Configs.BiomesInfo",
    "Hex.Configs.EHeroSoundType",
    "Hex.Configs.EAmbientSoundType",
    "Hex.UI.BhIcon",
    "Hex.Storage.IconData",
    "Hex.Configs.SpriteConfig",
    "Hex.Configs.AbilityViewConfig",
    "Hex.Configs.HeroAbilityConfig",
    "Hex.Configs.HeroAbilityLevelConfig",
    "Hex.Session.City.BhHireUnitAbilityItemView",
    "Hex.Session.City.BhHireUnitAbilityView",
    "Hex.Session.UI.HeroProfile.BhHeroPortraitView",
    "Hex.Session.UI.HeroProfile.BhHeroSpecializationView",
    "Hex.Session.UI.HeroProfile.BhHeroSkillView",
    "Hex.Session.UI.HeroProfile.BhHeroSubSkillView",
    "Hex.Configs.BattleCommonSoundsConfig",
    "Hex.Configs.CitySoundConfig",
    "Hex.Configs.CityCommonSoundsConfig",
    "Hex.Configs.MusicSoundConfig",
    "Hex.Configs.MusicSoundsConfig",
    "Hex.Configs.MapHeroSoundConfig",
    "Hex.Configs.MapHeroSoundsConfig",
    "Hex.Configs.MapAmbientSoundConfig",
    "Hex.Configs.MapAmbientSoundsConfig",
    "Hex.Configs.ProjectileConfig",
    "Hex.Session.Battle.BhProjectileController",
    "Hex.Session.Battle.BhProjectileDrawerEmulator",
    "Hex.Session.Battle.ProjectileEventArgs",
    "Hex.Session.City.BhCitySoundObject",
    "Hex.Map.BhSoundMapObject",
    "Hex.Sound.TrackedSoundInfo",
    "Hex.Configs.ESpatialSoundType",
    "Hex.ResManager",
    "Hex.Sound.SoundsManager",
    "Hex.Sound.SoundSource",
    "Hex.Sound.SoundSourcesPool",
    "Hex.Sound.SoundSetConfig",
    "Hex.Sound.SoundGroupConfig",
    "Hex.Sound.SoundClipConfig",
    "Hex.Sound.SoundSettings",
    "Hex.Sound.SoSoundSettings",
    "Hex.Sound.SoundMixersManager",
    "Hex.Sound.MixerConfig",
    "Hex.Sound.MixerGroupConfig",
    "Hex.Sound.MixersConfig",
)

FOCUS_TERMS = (
    "BhSelectedUnitHud",
    "BhUnitControlsView",
    "BhUnitAbilityView",
    "BhBattleQueueView",
    "BhTurnView",
    "BhSelectedUnitView",
    "BhUnitCommandsView",
    "BhUnitBasicCommands",
    "Unit",
    "AbilitiesSet",
    "BattleEventArgs",
    "HotkeyAbilityArgs",
    "Buff",
    "Damage",
    "Morale",
    "Magic",
    "Reward",
    "Resource",
    "Construction",
    "City",
    "Town",
    "Terrain",
    "Minimap",
    "Biome",
    "Ambient",
    "Sound",
    "Icon",
    "Portrait",
    "Sprite",
    "Audio",
    "Music",
    "Clip",
    "Projectile",
    "AbilityView",
    "Hero",
    "Spell",
)


MANUAL_TYPE_ALIASES = [
    {
        "mono": "Hex.Sound.SoundsClientBase",
        "current": "fwr",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["same protected fields: enabled/player/container", "same Init/Release/Enable/Disable/PlaySingleSound shape", "current fwr derives no namespace but matches Mono abstract client base"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.SoundConstantParameters",
        "current": "fws",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["same seven audio constants: min/max volume, pitch, random pitch, min fade"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.SoundClipData",
        "current": "fwt",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["constructor AudioClip + SoundClipConfig + SoundSetConfig", "same clip/config/released backing fields", "same volume/pitch/active accessors"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.SoundGroupData",
        "current": "fwv",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["SoundGroupConfig field plus list of sound sets", "Init(groupName, SoundGroupConfig, List)", "GetSoundSet(string) shape"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.ISoundGroupsDataListener",
        "current": "fww",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["single update callback method", "implemented by current fxf matching SoundSetsContainer"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.SoundGroupsData",
        "current": "fwx",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["inherits current fxi matching IResManagerListener", "dictionary + listener list fields", "GetSoundGroup/GetSoundSet/listen/unlisten/load/unload callback shape"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.SoundGroupsDataLoader",
        "current": "fwy",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["static loader-only class", "loads SoundGroupConfig out param", "loads List of SoundSetConfig out param", "returns fwv/SoundGroupData"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.SoundSetData",
        "current": "fwz",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["fields SoundGroupConfig + SoundSetConfig", "constructor SoundSetConfig + SoundGroupConfig", "random clip and named clip getters returning fwt/SoundClipData", "release and active/canPlay/count accessors"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.AudioListenerController",
        "current": "fxa",
        "confidence": "probable-static",
        "domain": "sound-runtime",
        "evidence": ["MonoBehaviour with enable/disable lifecycle", "paired with singleton-style current fxb matching AudioListenerControllers"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.AudioListenerControllers",
        "current": "fxb",
        "confidence": "probable-static",
        "domain": "sound-runtime",
        "evidence": ["singleton/list of fxa controllers", "push/pop/register/unregister controller shape"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.MixerGroupVolumeController",
        "current": "fxd",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["status/transition enums", "mixer group name + return/mute curves + AudioMixer fields", "transition and set-volume method shape"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.PlaybackReceiver",
        "current": "fxe",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["single Action field", "playback-complete callback methods taking int"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.Sound.SoundSetsContainer",
        "current": "fxf",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["implements fww/ISoundGroupsDataListener", "fields SoundGroupsData + dictionary + list + string[] group names", "Init(string[]), Release, GetSoundSet(string,bool), update callback shape"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
    {
        "mono": "Hex.IResManagerListener",
        "current": "fxi",
        "confidence": "strong-static",
        "domain": "resmanager",
        "evidence": ["two callback interface methods", "both callbacks take fxj/ResBundle", "implemented by sound-runtime fwx/SoundGroupsData"],
        "doc": "docs/mono_resmanager_static_evidence.md",
    },
    {
        "mono": "Hex.ResBundle",
        "current": "fxj",
        "confidence": "strong-static",
        "domain": "resmanager",
        "evidence": ["string bundle name field", "AssetBundle data field", "release-like method"],
        "doc": "docs/mono_resmanager_static_evidence.md",
    },
    {
        "mono": "Hex.FileInfo",
        "current": "fxk",
        "confidence": "strong-static",
        "domain": "resmanager",
        "evidence": ["path/bundleName/Type fields", "Equals override", "GetHashCode plus hash-combine helpers"],
        "doc": "docs/mono_resmanager_static_evidence.md",
    },
    {
        "mono": "Hex.ResFile",
        "current": "fxl",
        "confidence": "strong-static",
        "domain": "resmanager",
        "evidence": ["FileInfo/fxk info field", "UnityEngine.Object data field", "used by ResManager file enumeration methods"],
        "doc": "docs/mono_resmanager_static_evidence.md",
    },    {
        "mono": "Hex.DirectoryHelper",
        "current": "fwo",
        "confidence": "strong-static",
        "domain": "utils",
        "evidence": ["static utility class", "same resource-path helper signatures", "used by Mono ResManager for bundle path normalization and matching"],
        "doc": "docs/mono_hex_utils_static_evidence.md",
    },    {
        "mono": "Hex.Sound.SoundSetsPlayer",
        "current": "fxg",
        "confidence": "strong-static",
        "domain": "sound-runtime",
        "evidence": ["PlaybackInfo/SoundSetInfo nested structs", "dictionaries and playback id field", "Play overloads returning int", "Stop/Pause/Unpause/volume/pan/source lookup methods"],
        "doc": "docs/mono_sound_runtime_static_evidence.md",
    },
]
METHOD_LINE_RE = re.compile(
    r"^\s*(?P<access>public|private|protected|internal)?\s*"
    r"(?:(?:override|virtual|static|sealed|async|extern|unsafe)\s+)*"
    r"(?P<ret>[\w.`<>\[\],]+)\s+"
    r"(?P<name>[A-Za-z_][\w`<>]*)\s*\((?P<params>[^)]*)\)\s*\{"
)
CTOR_LINE_RE = re.compile(r"^\s*public\s+Type:\s+(?P<name>[\w.]+)\s*\((?P<params>[^)]*)\)\s*\{")
FIELD_LINE_RE = re.compile(r"^\s*(?:\[[^]]+\]\s*)*(?P<access>public|private|protected|internal)?\s*(?:(?:readonly|static|const|volatile)\s+)*(?P<type>[\w.`<>\[\],]+)\s+(?P<name>[A-Za-z_][\w`<>]*)\s*(?:=|;).*//Field offset:")
CLASS_RE = re.compile(r"^\s*public\s+(?:abstract\s+|sealed\s+|static\s+)?(?:class|struct|interface|enum)\s+(?P<name>[A-Za-z_][\w`<>]*)")
NAMESPACE_RE = re.compile(r"^\s*namespace\s+(?P<ns>[\w.]+)\s*;")


def token_set(value: str) -> set[str]:
    parts = re.split(r"[^A-Za-z0-9]+", value or "")
    out: set[str] = set()
    for part in parts:
        if not part:
            continue
        # split CamelCase lightly
        split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", part).split()
        out.update(s.lower() for s in split if s)
    return out


def compressed_uint(data: bytes, idx: int) -> tuple[int, int]:
    if idx >= len(data):
        return 0, idx
    b0 = data[idx]
    if b0 & 0x80 == 0:
        return b0, idx + 1
    if b0 & 0xC0 == 0x80 and idx + 1 < len(data):
        return ((b0 & 0x3F) << 8) | data[idx + 1], idx + 2
    if idx + 3 < len(data):
        return ((b0 & 0x1F) << 24) | (data[idx + 1] << 16) | (data[idx + 2] << 8) | data[idx + 3], idx + 4
    return 0, len(data)


def method_param_count(signature_obj) -> int:
    data = bytes(getattr(signature_obj, "value", b"") or b"")
    if not data:
        return 0
    idx = 1
    callconv = data[0]
    if callconv & 0x10:  # generic method
        _generic_count, idx = compressed_uint(data, idx)
    count, _idx = compressed_uint(data, idx)
    return int(count)


@dataclass
class TypeShape:
    full: str
    namespace: str
    name: str
    source: str
    path: str | None
    methods: list[dict]
    fields: list[dict]

    @property
    def method_names(self) -> set[str]:
        return {m["name"] for m in self.methods}

    @property
    def public_method_names(self) -> set[str]:
        return {m["name"] for m in self.methods if m.get("public")}

    @property
    def field_names(self) -> set[str]:
        return {f["name"] for f in self.fields}

    @property
    def param_hist(self) -> Counter:
        return Counter(int(m.get("param_count", 0)) for m in self.methods)

    def compact(self) -> dict:
        return {
            "full": self.full,
            "namespace": self.namespace,
            "name": self.name,
            "source": self.source,
            "path": self.path,
            "methodCount": len(self.methods),
            "fieldCount": len(self.fields),
            "methods": self.methods[:80],
            "fields": self.fields[:80],
        }


def row_index(value) -> int:
    # dnfile MDTableIndex rows are 1-based in metadata terms. Prefer row_index
    # when present; otherwise parse the string fallback defensively.
    for attr in ("row_index", "index", "rid"):
        if hasattr(value, attr):
            try:
                return int(getattr(value, attr))
            except Exception:
                pass
    text = str(value)
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else 1


def mono_types(path: Path) -> list[TypeShape]:
    dn = dnfile.dnPE(str(path))
    typedef_table = getattr(dn.net.mdtables, "TypeDef", None)
    method_table = getattr(dn.net.mdtables, "MethodDef", None)
    field_table = getattr(dn.net.mdtables, "Field", None)
    typedefs = list(getattr(typedef_table, "rows", None) or [])
    methods = list(getattr(method_table, "rows", None) or [])
    fields = list(getattr(field_table, "rows", None) or [])
    result: list[TypeShape] = []
    for i, row in enumerate(typedefs):
        name = str(row.TypeName)
        namespace = str(row.TypeNamespace or "")
        if name == "<Module>":
            continue
        full = f"{namespace}.{name}" if namespace else name
        owned_methods = []
        for method_index in list(row.MethodList or []):
            method = getattr(method_index, "row", None)
            if method is None:
                continue
            mname = str(method.Name)
            owned_methods.append({
                "name": mname,
                "param_count": method_param_count(method.Signature),
                "public": "mdPublic                                    True" in str(method.Flags),
                "private": "mdPrivate                                   True" in str(method.Flags),
                "static": "mdStatic                                    True" in str(method.Flags),
                "virtual": "mdVirtual                                   True" in str(method.Flags),
            })
        owned_fields = []
        for field_index in list(row.FieldList or []):
            field = getattr(field_index, "row", None)
            if field is None:
                continue
            fname = str(field.Name)
            owned_fields.append({
                "name": fname,
                "public": "fdPublic                                    True" in str(field.Flags),
                "private": "fdPrivate                                   True" in str(field.Flags),
                "static": "fdStatic                                    True" in str(field.Flags),
            })
        result.append(TypeShape(full, namespace, name, "mono-demo", str(path), owned_methods, owned_fields))
    return result


def count_params(text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    # Handles simple decomp shells only; generic commas inside params are rare in these shells.
    return len([p for p in text.split(",") if p.strip()])



def top_level_member_line(line: str) -> bool:
    # DiffableCs shells indent direct type members with one tab/one level. Nested
    # compiler helper classes are indented deeper. Keep this conservative so
    # nested helper methods do not shift owner method ordinals.
    if not line.strip():
        return False
    leading = len(line) - len(line.lstrip(" \t"))
    prefix = line[:leading]
    tab_units = prefix.count("\t") + (len(prefix.replace("\t", "")) // 4)
    return tab_units <= 1
def deobf_types(root: Path) -> list[TypeShape]:
    result: list[TypeShape] = []
    for path in root.rglob("*.cs"):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        namespace = ""
        class_name = None
        methods: list[dict] = []
        fields: list[dict] = []
        for line in lines:
            ns = NAMESPACE_RE.match(line)
            if ns:
                namespace = ns.group("ns")
                continue
            cls = CLASS_RE.match(line)
            if cls and class_name is None:
                class_name = cls.group("name")
                continue
            if not top_level_member_line(line):
                continue
            ctor = CTOR_LINE_RE.match(line)
            if ctor:
                methods.append({"name": ".ctor", "param_count": count_params(ctor.group("params")), "public": True, "private": False, "static": False, "virtual": False})
                continue
            meth = METHOD_LINE_RE.match(line)
            if meth:
                access = meth.group("access") or ""
                methods.append({
                    "name": meth.group("name"),
                    "return": meth.group("ret"),
                    "param_count": count_params(meth.group("params")),
                    "params": meth.group("params"),
                    "public": access == "public",
                    "private": access == "private",
                    "static": " static " in f" {line} ",
                    "virtual": " virtual " in f" {line} " or " override " in f" {line} ",
                })
                continue
            field = FIELD_LINE_RE.match(line)
            if field:
                access = field.group("access") or ""
                fields.append({"name": field.group("name"), "type": field.group("type"), "public": access == "public", "private": access == "private", "static": " static " in f" {line} "})
        if class_name is None:
            continue
        full = f"{namespace}.{class_name}" if namespace else class_name
        result.append(TypeShape(full, namespace, class_name, "current-deobf-diffable", str(path), methods, fields))
    return result


def hist_similarity(a: Counter, b: Counter) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 1.0
    common = sum(min(a[k], b[k]) for k in keys)
    total = sum(max(a[k], b[k]) for k in keys)
    return common / total if total else 0.0


def closeness(a: int, b: int) -> float:
    if a == b:
        return 1.0
    denom = max(a, b, 1)
    return max(0.0, 1.0 - abs(a - b) / denom)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)



COMMON_SIMPLE_NAME_COLLISIONS = {
    "Color",
    "Entry",
    "Extensions",
    "Game",
    "Key",
    "Logger",
    "Mode",
    "MouseState",
    "PointerInputModule",
    "PreserveAttribute",
    "Profiler",
    "PropertyContainer",
    "TextElement",
    "Tile",
    "TileData",
    "Toggle",
    "Vertex",
}

FRAMEWORK_NAMESPACE_ROOTS = {
    "System",
    "UnityEngine",
    "Unity",
    "Newtonsoft",
    "Steamworks",
    "MagicOnion",
    "Epic",
    "Mono",
}


def namespace_root(namespace: str) -> str:
    return (namespace or "").split(".", 1)[0] if namespace else ""


def candidate_plausibility(mono: TypeShape, deobf: TypeShape) -> tuple[bool, str | None]:
    """Reject simple-name matches that are more likely framework collisions than semantic carry-over."""
    if mono.full == deobf.full:
        return True, None
    mroot = namespace_root(mono.namespace)
    droot = namespace_root(deobf.namespace)
    if mroot == droot and mroot:
        return True, None
    if mroot == "Hex" and droot and droot != "Hex":
        return False, f"rejected Hex-to-{droot} simple-name collision"
    if droot == "Hex" and mroot and mroot != "Hex":
        return False, f"rejected {mroot}-to-Hex simple-name collision"
    if droot in FRAMEWORK_NAMESPACE_ROOTS and mroot != droot:
        left = mroot or "global"
        return False, f"rejected {left}-to-{droot} framework simple-name collision"
    if mroot in FRAMEWORK_NAMESPACE_ROOTS and droot != mroot:
        right = droot or "global"
        return False, f"rejected {mroot}-to-{right} framework simple-name collision"
    if mono.name in COMMON_SIMPLE_NAME_COLLISIONS and mroot != droot:
        left = mroot or "global"
        right = droot or "global"
        return False, f"rejected common simple-name collision across namespace roots: {left} vs {right}"
    if mroot in FRAMEWORK_NAMESPACE_ROOTS and droot in FRAMEWORK_NAMESPACE_ROOTS and mroot != droot:
        return False, f"rejected framework-to-framework simple-name collision: {mroot} vs {droot}"
    return True, None

def score_pair(mono: TypeShape, deobf: TypeShape) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if mono.full == deobf.full:
        score += 60
        reasons.append("exact full type name")
    elif mono.name == deobf.name:
        score += 42
        reasons.append("exact simple type name")
    elif mono.name.lower() == deobf.name.lower():
        score += 35
        reasons.append("case-insensitive simple type name")
    if mono.name == deobf.name and namespace_root(mono.namespace) == "Hex" and namespace_root(deobf.namespace) == "Hex" and mono.namespace != deobf.namespace:
        score += 4
        reasons.append(f"Hex namespace migration candidate: {mono.namespace} -> {deobf.namespace}")
    name_tokens = jaccard(token_set(mono.full), token_set(deobf.full))
    if name_tokens >= 0.35:
        score += 18 * name_tokens
        reasons.append(f"namespace/name token overlap {name_tokens:.2f}")
    method_name_overlap = jaccard(mono.method_names, deobf.method_names)
    if method_name_overlap >= 0.10:
        score += 22 * method_name_overlap
        reasons.append(f"method-name overlap {method_name_overlap:.2f}")
    public_overlap = jaccard(mono.public_method_names, deobf.public_method_names)
    if public_overlap >= 0.10:
        score += 10 * public_overlap
        reasons.append(f"public-method overlap {public_overlap:.2f}")
    param = hist_similarity(mono.param_hist, deobf.param_hist)
    score += 12 * param
    reasons.append(f"param-count histogram similarity {param:.2f}")
    mc = closeness(len(mono.methods), len(deobf.methods))
    fc = closeness(len(mono.fields), len(deobf.fields))
    score += 8 * mc + 5 * fc
    reasons.append(f"method-count closeness {mc:.2f}")
    reasons.append(f"field-count closeness {fc:.2f}")
    return score, reasons



def align_members(mono: TypeShape, deobf: TypeShape) -> dict:
    method_rows = []
    max_methods = max(len(mono.methods), len(deobf.methods))
    for i in range(max_methods):
        mm = mono.methods[i] if i < len(mono.methods) else None
        dm = deobf.methods[i] if i < len(deobf.methods) else None
        if mm is None or dm is None:
            method_rows.append({
                "ordinal": i,
                "mono": mm,
                "deobf": dm,
                "confidence": "missing-side",
                "reasons": ["method exists on only one side at this ordinal"],
            })
            continue
        reasons = ["same declaration ordinal"]
        score = 35
        if int(mm.get("param_count", -1)) == int(dm.get("param_count", -2)):
            score += 25
            reasons.append("same parameter count")
        else:
            reasons.append("parameter count differs")
        for flag in ("public", "private", "static", "virtual"):
            if bool(mm.get(flag)) == bool(dm.get(flag)):
                score += 5
                reasons.append(f"same {flag} flag")
        if mm.get("name") == dm.get("name"):
            score += 20
            reasons.append("same method name")
        if mm.get("name") == dm.get("name") and score >= 85:
            conf = "strong-static"
        elif mm.get("name") == dm.get("name") and score >= 65:
            conf = "probable-static"
        elif score >= 45:
            conf = "candidate"
        else:
            conf = "weak-candidate"
        method_rows.append({
            "ordinal": i,
            "mono": mm,
            "deobf": dm,
            "score": score,
            "confidence": conf,
            "reasons": reasons,
        })
    field_rows = []
    max_fields = max(len(mono.fields), len(deobf.fields))
    for i in range(max_fields):
        mf = mono.fields[i] if i < len(mono.fields) else None
        df = deobf.fields[i] if i < len(deobf.fields) else None
        if mf is None or df is None:
            field_rows.append({
                "ordinal": i,
                "mono": mf,
                "deobf": df,
                "confidence": "missing-side",
                "reasons": ["field exists on only one side at this ordinal"],
            })
            continue
        reasons = ["same declaration ordinal"]
        score = 40
        for flag in ("public", "private", "static"):
            if bool(mf.get(flag)) == bool(df.get(flag)):
                score += 8
                reasons.append(f"same {flag} flag")
        if mf.get("name") == df.get("name"):
            score += 20
            reasons.append("same field name")
        if score >= 80:
            conf = "strong-static"
        elif score >= 60:
            conf = "probable-static"
        elif score >= 40:
            conf = "candidate"
        else:
            conf = "weak-candidate"
        field_rows.append({
            "ordinal": i,
            "mono": mf,
            "deobf": df,
            "score": score,
            "confidence": conf,
            "reasons": reasons,
        })
    mono_methods_by_name = {m["name"]: m for m in mono.methods}
    deobf_methods_by_name = {m["name"]: m for m in deobf.methods}
    exact_method_rows = [
        {"name": name, "mono": mono_methods_by_name[name], "deobf": deobf_methods_by_name[name], "confidence": "strong-static", "reasons": ["same owner type", "same method name"]}
        for name in sorted(set(mono_methods_by_name) & set(deobf_methods_by_name))
    ]
    mono_fields_by_name = {f["name"]: f for f in mono.fields}
    deobf_fields_by_name = {f["name"]: f for f in deobf.fields}
    exact_field_rows = [
        {"name": name, "mono": mono_fields_by_name[name], "deobf": deobf_fields_by_name[name], "confidence": "strong-static", "reasons": ["same owner type", "same field name"]}
        for name in sorted(set(mono_fields_by_name) & set(deobf_fields_by_name))
    ]
    return {
        "exactMethodNameAlignment": exact_method_rows,
        "exactFieldNameAlignment": exact_field_rows,
        "methodOrdinalAlignment": method_rows,
        "fieldOrdinalAlignment": field_rows,
        "methodAlignmentSummary": dict(Counter(r["confidence"] for r in method_rows)),
        "fieldAlignmentSummary": dict(Counter(r["confidence"] for r in field_rows)),
    }
def confidence(score: float, top: float | None, second: float | None, reasons: list[str]) -> str:
    gap = (top or 0) - (second or 0)
    has_exact_full = "exact full type name" in reasons
    has_exact_simple = "exact simple type name" in reasons or "case-insensitive simple type name" in reasons
    if score >= 75 and gap >= 12 and has_exact_full:
        return "strong-static"
    if score >= 58 and gap >= 8 and (has_exact_full or has_exact_simple):
        return "probable-static"
    if score >= 42:
        return "candidate"
    return "weak-candidate"


def is_focus_type(t: TypeShape) -> bool:
    hay = t.full.lower()
    return any(term.lower() in hay for term in FOCUS_TERMS)


def build_map(mono: list[TypeShape], deobf: list[TypeShape], topn: int) -> dict:
    deobf_by_simple: dict[str, list[TypeShape]] = {}
    for d in deobf:
        deobf_by_simple.setdefault(d.name, []).append(d)
    rows = []
    focus_rows = []
    rejected_simple_name_collisions = []
    for m in mono:
        candidate_pool: list[TypeShape]
        if m.name in deobf_by_simple:
            # Broad map layer: only exact simple-name survivals. This is fast,
            # falsifiable, and high-value for stable UI/gameplay classes. Obfuscated
            # current-only candidates must be generated by focused dossiers instead.
            candidate_pool = deobf_by_simple[m.name]
        else:
            candidate_pool = []
        scored = []
        for d in candidate_pool:
            s, reasons = score_pair(m, d)
            plausible, rejection_reason = candidate_plausibility(m, d)
            if not plausible:
                rejected_simple_name_collisions.append({
                    "mono": m.compact(),
                    "deobf": d.compact(),
                    "score": round(s, 2),
                    "reason": rejection_reason,
                    "scoreReasons": reasons,
                })
                continue
            if s >= 30 or m.name == d.name or is_focus_type(m):
                scored.append((s, d, reasons))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            continue
        second = scored[1][0] if len(scored) > 1 else None
        entry = {
            "mono": m.compact(),
            "candidates": [
                {
                    "score": round(s, 2),
                    "confidence": confidence(s, scored[0][0], second, reasons),
                    "reasons": reasons,
                    "deobf": d.compact(),
                    "sharedMethodNames": sorted(m.method_names & d.method_names)[:50],
                    "sharedFieldNames": sorted(m.field_names & d.field_names)[:50],
                    "memberAlignment": align_members(m, d) if (m.full == d.full or m.name == d.name) else None,
                }
                for s, d, reasons in scored[:topn]
            ],
        }
        rows.append(entry)
        if is_focus_type(m) or any(is_focus_type(c[1]) for c in scored[:topn]):
            focus_rows.append(entry)
    return {
        "schema": "mono-deobf-semantic-map.v1",
        "evidenceBoundary": "Static metadata and DiffableCs shell comparison only. This does not prove runtime invocation order, method body equivalence, or patch safety.",
        "inputs": {
            "monoTypes": len(mono),
            "deobfTypes": len(deobf),
        },
        "summary": {
            "mappedMonoTypes": len(rows),
            "focusMappedMonoTypes": len(focus_rows),
            "strongStatic": sum(1 for r in rows if r["candidates"] and r["candidates"][0]["confidence"] == "strong-static"),
            "probableStatic": sum(1 for r in rows if r["candidates"] and r["candidates"][0]["confidence"] == "probable-static"),
            "candidate": sum(1 for r in rows if r["candidates"] and r["candidates"][0]["confidence"] == "candidate"),
            "weakCandidate": sum(1 for r in rows if r["candidates"] and r["candidates"][0]["confidence"] == "weak-candidate"),
            "rejectedSimpleNameCollisions": len(rejected_simple_name_collisions),
        },
        "rows": rows,
        "focusRows": focus_rows,
        "rejectedSimpleNameCollisions": rejected_simple_name_collisions,
        "manualTypeAliases": MANUAL_TYPE_ALIASES,
    }



def md_member_table(rows: list[dict], limit: int = 40) -> str:
    out = ["| Ordinal | Mono member | Current deobf member | Confidence | Reasons |", "|---:|---|---|---|---|"]
    for row in rows[:limit]:
        mono = row.get("mono") or {}
        deobf = row.get("deobf") or {}
        mono_name = mono.get("name") or "-"
        deobf_name = deobf.get("name") or "-"
        mono_pc = mono.get("param_count")
        deobf_pc = deobf.get("param_count")
        mono_label = f"`{mono_name}`" + (f"/{mono_pc}" if mono_pc is not None else "")
        deobf_label = f"`{deobf_name}`" + (f"/{deobf_pc}" if deobf_pc is not None else "")
        reasons = "; ".join(row.get("reasons", [])[:3])
        out.append(f"| {row.get('ordinal', '-')} | {mono_label} | {deobf_label} | {row.get('confidence', '-')} | {reasons} |")
    return "\n".join(out)


def md_priority_member_sections(priority_rows: list[dict]) -> str:
    sections = []
    for row in priority_rows:
        cand = row["candidates"][0]
        align = cand.get("memberAlignment") or {}
        exact_methods = align.get("exactMethodNameAlignment") or []
        exact_fields = align.get("exactFieldNameAlignment") or []
        exact_method_names = ", ".join(f"`{r['name']}`" for r in exact_methods) or "none"
        exact_field_names = ", ".join(f"`{r['name']}`" for r in exact_fields) or "none"
        sections.append(
            f"### `{row['mono']['full']}` -> `{cand['deobf']['full']}`\n\n"
            f"Exact method-name survivals: {exact_method_names}\n\n"
            f"Exact field-name survivals: {exact_field_names}\n\n"
            "Ordinal method hypotheses. Treat these as candidate evidence only unless backed by exact names or method-body/xref evidence.\n\n"
            f"{md_member_table((align.get('methodOrdinalAlignment') or []), 28)}\n"
        )
    return "\n".join(sections)

def md_manual_alias_table(rows: list[dict]) -> str:
    if not rows:
        return "none"
    out = ["| Mono semantic type | Current deobf type | Confidence | Domain | Evidence |", "|---|---|---|---|---|"]
    for row in rows:
        evidence = "; ".join(row.get("evidence", [])[:3])
        out.append(f"| `{row.get('mono', '-')}` | `{row.get('current', '-')}` | {row.get('confidence', '-')} | {row.get('domain', '-')} | {evidence} |")
    return "\n".join(out)


def md_rejected_table(rows: list[dict], limit: int = 80) -> str:
    if not rows:
        return "none"
    out = ["| Mono type | Rejected current type | Score | Reason |", "|---|---|---:|---|"]
    for row in rows[:limit]:
        mono = (row.get("mono") or {}).get("full", "-")
        deobf = (row.get("deobf") or {}).get("full", "-")
        reason = row.get("reason") or "-"
        out.append(f"| `{mono}` | `{deobf}` | {row.get('score', '-')} | {reason} |")
    if len(rows) > limit:
        out.append(f"| ... | ... | ... | {len(rows) - limit} more omitted from Markdown; see JSON artifact. |")
    return "\n".join(out)

def md_table(rows: list[dict], limit: int) -> str:
    out = ["| Mono type | Best current deobf candidate | Confidence | Score | Key reasons |", "|---|---|---|---:|---|"]
    for row in rows[:limit]:
        cand = row["candidates"][0]
        reasons = "; ".join(cand["reasons"][:3])
        out.append(f"| `{row['mono']['full']}` | `{cand['deobf']['full']}` | {cand['confidence']} | {cand['score']} | {reasons} |")
    return "\n".join(out)


def write_md(data: dict, path: Path, focus_limit: int, general_limit: int) -> None:
    summary = data["summary"]
    strong = [r for r in data["rows"] if r["candidates"] and r["candidates"][0]["confidence"] == "strong-static"]
    probable = [r for r in data["rows"] if r["candidates"] and r["candidates"][0]["confidence"] == "probable-static"]
    focus = data["focusRows"]
    priority = [r for r in data["rows"] if r["mono"]["full"] in PRIORITY_TYPES]
    text = f"""# Mono Demo to Golden Era Semantic Map

Status: source-generated/static-only. Runtime-unvalidated.

This map compares the old Mono demo `Hex.dll` against the current Golden Era Cpp2IL DiffableCs shells. It is intended to make future mod surface work more native-friendly by preserving semantic evidence from the readable Mono build while keeping proof levels explicit.

Evidence boundary: {data['evidenceBoundary']}

## Summary

| Metric | Count |
|---|---:|
| Mono types parsed | {data['inputs']['monoTypes']} |
| Current deobf types parsed | {data['inputs']['deobfTypes']} |
| Mono types with candidates | {summary['mappedMonoTypes']} |
| Focus types with candidates | {summary['focusMappedMonoTypes']} |
| Strong static matches | {summary['strongStatic']} |
| Probable static matches | {summary['probableStatic']} |
| Candidate matches | {summary['candidate']} |
| Weak candidates | {summary['weakCandidate']} |
| Rejected simple-name collisions | {summary.get('rejectedSimpleNameCollisions', 0)} |

## How to read confidence

- `strong-static`: exact full type-name evidence plus shape agreement and enough separation from the next candidate.
- `probable-static`: exact simple-name or full-name evidence with candidate separation, but not enough to treat as proven runtime behavior.
- `candidate`: useful hypothesis for decomp follow-up.
- `weak-candidate`: shape-only or ambiguous. Do not implement from this without stronger evidence.
- `rejected simple-name collision`: same simple type name, but namespace/domain evidence contradicts a useful semantic match. These are tracked separately so they do not pollute implementation candidates.

## Rejected simple-name collisions

These rows had an exact simple-name match, but namespace/domain evidence contradicted a useful semantic match. They remain in the JSON under `rejectedSimpleNameCollisions` for auditability and are excluded from implementation candidate counts.

{md_rejected_table(data.get("rejectedSimpleNameCollisions", []), 80)}

## Manual obfuscated type aliases

These aliases cannot be discovered by exact simple-name matching because the current build keeps obfuscated global type names. They are authored from focused Mono/current dossiers and remain static-only until runtime-proven.

{md_manual_alias_table(data.get("manualTypeAliases", []))}

## Priority selected-HUD and battle-UI matches

{md_table(priority, 80)}

## Focused mod-relevant matches

{md_table(focus, focus_limit)}

## Priority member-level hypotheses

{md_priority_member_sections(priority)}

## Strong static matches sample

{md_table(strong, general_limit)}

## Probable static matches sample

{md_table(probable, general_limit)}

## Next use

For a concrete surface, start from the JSON row in `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.json`, then collect at least one additional evidence class before changing runtime hooks:

- current DiffableCs/ISIL method body or call-site evidence,
- generated interop metadata from the current Golden Era install,
- targeted live bridge metadata if runtime is available,
- runtime log proof for invocation ordering only after static candidates are narrow.

## Recommended next expansion slices

Expand from existing mod pain points, not alphabetically through the whole assembly:

| Slice | Why it matters | Seed types from this map | Proof needed before implementation |
|---|---|---|---|
| Town/city screen load | Town scenes work but load slowly; Mono can identify native lifecycle, city view binding, building tooltip, and resource/cost contracts. | `Hex.BhCityUpgradeStatsView`, `Hex.Cheat.UI.BhCityCheatPanel`, `Hex.Cheat.UI.BhWindowCity`, city/building analytics/config types. | Current deobf dossiers for scene open, building view bind, tooltip open/close, and resource affordability/spend routes. |
| Selected unit HUD/action bar | Custom unit SIDs can hit native UI dictionaries unexpectedly; this slice now has focused evidence. | `Hex.Session.Battle.BhSelectedUnitHud`, `BhUnitControlsView`, `BhUnitAbilityView`, `BattleEventArgs`, `HotkeyAbilityArgs`. | Use `docs/mono_priority_battle_ui_static_evidence.md`; remaining gaps are `bejo` exact role, `belz` clickability drift, and current-build hotkey index base. |
| Unit ability/tooltip panels | Custom abilities need precise data adapters instead of broad UI guards. | `Hex.BhHireUnitAbilities`, `Hex.BhUiBuff`, `Hex.BhUnitPreviews`, `Hex.Tools.BhUnitAnimationListener`. | Current dossiers for ability dictionary lookup, icon binding, buff/debuff panel item creation, tooltip text/image source. |
| Hero/army UI adapters | Existing hero/unit import code likely benefits from native identity and slot binding instead of defensive patches. | `BhSideHeroesViewController`, `BhHeroLoader`, `Hex.Pick.BhUnitSlot`, `Hex.Pick.BhHeroDetails`, story/pick hero types. | Current dossiers for hero slot bind, portrait load, army slot bind, unit stack tooltip, and hero selection refresh. |
| Custom biome/minimap/terrain | Current custom biome code should stay data-driven instead of renderer-rewrite driven; Mono confirms the original config contracts. | `Hex.Session.World.Minimap`, `Hex.Session.World.SoMinimapConfig`, `Hex.Render.SoTerrainMaterial`, `Hex.Configs.BiomesInfo`, sound enums. | Use `docs/mono_custom_biome_minimap_static_evidence.md`; remaining runtime proof is visual correctness and sound selector behavior only. |
| Icon/portrait/sprite binding | Law icons, hero portraits, ability icons, and specialization icons should use native bind contracts instead of broad UI/resource fallbacks. | `Hex.UI.BhIcon`, `IconData`, `SpriteConfig`, `AbilityViewConfig`, hero profile views, city ability views. | Use `docs/mono_icon_portrait_static_evidence.md`; remaining runtime proof is sprite availability and exact UI surface coverage. |
| Audio/music/projectile routing | Existing sidecar audio works but bypasses native sound-set, projectile flight, and city/map spatial sound routes. | `ProjectileConfig`, `BhProjectileController`, `MusicSoundsConfig`, `CityCommonSoundsConfig`, `MapHeroSoundsConfig`, `BhCitySoundObject`, `BhSoundMapObject`. | Use `docs/mono_audio_music_static_evidence.md`; remaining proof is exact current key selection and sound-set asset registration. |
| Sound runtime and mixer routing | Sidecar audio bypasses native sound groups, sound sets, pooled sources, mixer groups, focus fades, and ResManager bundle notifications. | `SoundsManager`, `SoundGroupConfig`, `SoundSetConfig`, `SoundClipConfig`, `SoundSource`, `SoundSourcesPool`, `SoundMixersManager`. | Use `docs/mono_sound_runtime_static_evidence.md`; remaining proof is custom sound bundle registration and exact music key selection. |
| ResManager/native asset loading | Existing prefab/icon/portrait/audio hooks depend on custom bundles resolving safely through native resource lookup. | `Hex.ResManager`, `ProjectileConfig`, `IconData`, sprite/portrait cache consumers. | Use `docs/mono_resmanager_static_evidence.md`; remaining proof is exact current loader body identity and bundle registration timing. |
| Utility path normalization | ResManager bundle lookup depends on normalized resource paths and case-insensitive matching. | `Hex.DirectoryHelper` -> `fwo`. | Use `docs/mono_hex_utils_static_evidence.md`; remaining proof is current method-body identity for individual obfuscated helpers. |
| Cheat/AI driver surfaces | Old Mono names can clarify intended cheat window owner and command surfaces used by automation. | `Hex.Cheat.UI.State*`, `BhWindowHero`, `BhWindowMagic`, `BhWindowWorldHeroPick`, `BhResourcePanel`. | Current dossiers plus live metadata only; no command exposure without runtime freshness and exact owner instance proof. |

Do not use this map as a direct replacement for `GameSymbols.cs`. It is a candidate/evidence source that should feed centralized symbols after review.

## Focused evidence documents

- Town screen load and city UI lifecycle: `docs/mono_town_screen_static_evidence.md`
- Battle visual drawer and spawn surfaces: `docs/mono_battle_visual_static_evidence.md`
- Unit visual presentation and UnitViewConfig: `docs/mono_unit_visual_presentation_static_evidence.md`
- Unit tooltip, preview, hire ability, and selected-unit UI: `docs/mono_unit_tooltip_preview_static_evidence.md`
- Hero and army UI adapter surfaces: `docs/mono_hero_army_ui_static_evidence.md`
- Battle damage forecast and kill mapping: `docs/mono_damage_forecast_static_evidence.md`
- Map squad visuals and fog adapter: `docs/mono_map_squad_visual_static_evidence.md`
- Custom biome, minimap, terrain material, and terrain sound: `docs/mono_custom_biome_minimap_static_evidence.md`
- Icon, portrait, sprite, and ability image binding: `docs/mono_icon_portrait_static_evidence.md`
- Audio, music, projectile, city/map spatial sound routing: `docs/mono_audio_music_static_evidence.md`
- Sound runtime, sound-set, pooled-source, and mixer routing: `docs/mono_sound_runtime_static_evidence.md`
- ResManager and native asset loading: `docs/mono_resmanager_static_evidence.md`
- Hex utility path normalization: `docs/mono_hex_utils_static_evidence.md`
- Static boundary audit for exhausted/missing body evidence: `docs/mono_deobf_static_boundary_audit.md`

## Generated interop metadata artifacts

- Main Hex interop map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map.json`
- ResManager interop map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map_resmanager.json`
- Sound runtime interop map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map_sound_runtime.json`
- Hex utils interop map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map_hex_utils.json`
- Full method-pointer import from attribute-injected dummy DLLs: `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_from_dummydll_with_attrs.csv`
- ResManager method-pointer subset/address map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_hex_resmanager.csv`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_resmanager.json`
- Sound runtime method-pointer subset/address map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_hex_sound_runtime.csv`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_sound_runtime.json`
- Hex utils method-pointer subset/address map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_hex_utils.csv`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_hex_utils.json`
- Native disassembly packs: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_resmanager.json/md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_hex_utils.json/md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_sound_runtime.json/md`
- Full imported method address map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_all_dummydll_methods.json`
- External-domain native call graph: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_call_graph_external_domains.json/md`
- Core gameplay/UI method-pointer subsets: `method_pointers_hex_session_battle.csv`, `method_pointers_hex_session_city.csv`, `method_pointers_hex_cheat_ui.csv`, `method_pointers_hex_ui.csv`
- Core gameplay/UI native disassembly packs: `native_disasm_hex_session_battle.json/md`, `native_disasm_hex_session_city.json/md`, `native_disasm_hex_cheat_ui.json/md`, `native_disasm_hex_ui.json/md`
- Core gameplay/UI native call graph: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_call_graph_core_gameplay_ui.json/md`
- Additional mod-relevant method-pointer subsets/disassembly packs: `Hex.Session.Data`, `Hex.Map`, `Hex.Configs`, `Hex.Render`, `Hex.Storage`, `Hex.Session.UI`, `Hex.Session.Hud`, `Hex.Session.Logic`, and `Hex.Session.World`
- Broad mod-relevant native call graph: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_call_graph_mod_relevant_domains.json/md`
- Remaining Hex game-code pack: `method_pointers_hex_remaining_game.csv`, `native_disasm_hex_remaining_game.json/md`
- All-Hex game-domain native call graph: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_call_graph_all_hex_game_domains.json/md`
- Reusable all-Hex anchor/path query report: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_call_graph_anchor_report.json/md`
- All-Hex gameplay/UI anchor matrix: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_anchor_matrix_all_hex_game_domains.json/md`
- All-Hex positive anchor path dossiers with native instruction context: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_anchor_path_dossiers_all_hex_game_domains.json/md`
- Heuristic all-Hex anchor path triage: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_anchor_path_triage_all_hex_game_domains.json/md`
- All-Hex native call graph annotated with Mono semantic type aliases: `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_call_graph_with_mono_aliases_all_hex_game_domains.json/md`
- Focused high-priority anchor path review pack: `experiments/cpp2il_readable_csharp/samples/latest_refresh/focused_anchor_path_review_pack_high_priority.json/md`
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    last_error = None
    for attempt in range(12):
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.25 * (attempt + 1))
    raise last_error
def main() -> int:

    ap = argparse.ArgumentParser()
    ap.add_argument("--mono-hex", type=Path, default=DEFAULT_MONO_HEX)
    ap.add_argument("--mono-assembly", type=Path, action="append", default=None, help="Additional Mono assembly to parse; defaults include Hex.ResManager.dll when present.")
    ap.add_argument("--diffable-root", type=Path, default=DEFAULT_DIFFABLE_ROOT)
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--topn", type=int, default=5)
    ap.add_argument("--focus-limit", type=int, default=80)
    ap.add_argument("--general-limit", type=int, default=80)
    args = ap.parse_args()

    mono_paths = [args.mono_hex]
    extra_paths = args.mono_assembly if args.mono_assembly is not None else [p for p in DEFAULT_EXTRA_MONO_ASSEMBLIES if p.exists()]
    mono_paths.extend(extra_paths)
    mono = []
    for mono_path in mono_paths:
        mono.extend(mono_types(mono_path))
    deobf = deobf_types(args.diffable_root)
    data = build_map(mono, deobf, args.topn)
    write_text_atomic(args.out_json, json.dumps(data, indent=2, ensure_ascii=False))
    write_md(data, args.out_md, args.focus_limit, args.general_limit)
    print(json.dumps({"outJson": str(args.out_json), "outMd": str(args.out_md), "summary": data["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




























