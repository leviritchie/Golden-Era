#!/usr/bin/env python3
"""Symbol-literal tier gate for OfflineUnlockMod GameSymbols hint groups.

Contract (docs/port_to_current_game_version.md, "Phase 2/3 status"):

* Every *type* hint group in ``GameSymbols.cs`` (``string[] <Name>TypeHints`` / ``const string
  <Name>TypeHint``) must resolve, on the target build's interop, to exactly one type. A group that
  resolves to nothing, or whose hints reach more than one distinct type, is a finding. On the current
  build a flat group is checked as ``GameSymbolsCurrent.g.cs`` rewrites it at runtime: a scoped group by
  its generated live literals, a group the generator refused as ``refused`` (fail-closed, not a finding).
* Every build-scoped group in ``GameSymbols.TypeGroups`` (``TypeHintGroup``) must, for the target
  build's scope, resolve to exactly one type **of the pinned expected shape** (base type, declared
  field count, declared non-constructor method count). On Golden Era the accepted type must also be
  the type the pre-migration first-hint-wins resolver picked, so the migration is behaviour-preserving.
  An empty scope is reported as ``refused`` - that is the fail-closed runtime result, not a finding.
  ``current: TypeHintScope.Generated`` takes its hint and shape from the generated current-build scope
  report (``tools/port_current/remap/current_scopes_<build>.json``, ``typeGroups``); a group that report
  refused is an empty scope.
* The generated current-build scopes (``GameSymbolsCurrent.g.cs`` + the scope report, produced by
  ``tools/port_current/generate_current_symbol_scopes.py``) must be fresh against GameSymbols.cs, the
  P1 remap and the tracked evidence (``--check``). Every class in GameSymbols.cs must be ``partial``
  (the generated static constructors attach to it) and every generated static constructor must begin
  with the ``GameSymbolScope.RewriteForCurrentBuild`` guard, so Golden Era resolution is untouched.
* Raw obfuscated literals and direct ``AccessTools`` calls outside the resolver layer are gated by
  ``tools/validate_symbol_literal_confinement.py`` (shrink-only ``symbol_literal_confinement_allowlist.txt``),
  which this validator runs so it is build-wired through ``ValidateGameSymbolsHintContract``.
* ``TypeGroups`` must be the only runtime consumers of the migrated groups: no per-file
  ``ResolveFirstType`` resolver copy may remain in the plugin source.

Pre-existing findings live in ``tools/game_symbols_hint_allowlist.txt`` (``<build>|<group>|<status>``).
That list may only shrink: a finding not on it fails the gate, and an allow-list line that no longer
matches a finding also fails (prune it).

Member hint groups (MethodSymbol / field-name arrays) carry no owner type in GameSymbols.cs itself; on the
current build their live owner is pinned by the generated scope (``GameSymbolScope.Members(..., owners)``
checked by GameMember at lookup). The reviewed UnitViewConfig map-mesh loader also has a narrow explicit
owner/evidence/hook check; ``memberGroupsUnchecked`` still counts groups not indexed by the generic type gate.

The interop index is produced by ``tools/port_current/interop_shape_index`` (Mono.Cecil, counting the
same way the plugin's runtime ``TypeShape.Of`` does). ``--interop`` runs it (cached by Hex.dll hash);
``--index`` reads an existing TSV.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
GAME_SYMBOLS = PLUGIN_DIR / "GameSymbols.cs"
DEFAULT_ALLOWLIST = REPO / "tools" / "game_symbols_hint_allowlist.txt"
INDEXER = REPO / "tools" / "port_current" / "interop_shape_index" / "InteropShapeIndex.csproj"
DEFAULT_CACHE = REPO / "artifacts" / "port_current" / "p2" / "index_cache"
SCOPE_GENERATOR = REPO / "tools" / "port_current" / "generate_current_symbol_scopes.py"
SCOPE_CS = PLUGIN_DIR / "GameSymbolsCurrent.g.cs"


def _current_build_id() -> str:
    """The build the scope generator targets (its BUILD_ID), so this gate never checks a retired report."""
    m = re.search(r'^BUILD_ID = "(\d+)"$', SCOPE_GENERATOR.read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit(f"cannot read BUILD_ID from {SCOPE_GENERATOR}")
    return m.group(1)


SCOPE_REPORT = REPO / "tools" / "port_current" / "remap" / f"current_scopes_{_current_build_id()}.json"
SCOPE_OVERRIDES = REPO / "tools" / "port_current" / "remap" / f"current_scope_overrides_{_current_build_id()}.json"
SCOPE_REMAP = REPO / "tools" / "port_current" / "remap" / f"game_symbols_remap_{_current_build_id()}.json"
SCOPE_GUARD = "if (!GameSymbolScope.RewriteForCurrentBuild)"
BUILDS = ("golden", "current")
MAP_MESH_LOADER_ALIAS = "Method_Public_GameObject_0"
MAP_MESH_LOADER_OWNER = "Hex.Configs.UnitViewConfig"

# Per-file resolver copies that the central resolver replaced. Their reappearance fails the gate.
FORBIDDEN_RESOLVER_COPY = re.compile(r"\bstatic\s+Type\s+ResolveFirstType\s*\(")


# --------------------------------------------------------------------------------------------
# Interop index
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TypeRow:
    asm: str
    full: str
    name: str
    obf: str
    base: str
    fields: int
    methods: int

    @property
    def shape(self) -> tuple[str, int, int]:
        return (self.base, self.fields, self.methods)


class InteropIndex:
    def __init__(self, path: Path):
        self.path = path
        self.by_full: dict[str, list[TypeRow]] = defaultdict(list)
        self.by_obf: dict[str, list[TypeRow]] = defaultdict(list)
        self.by_name: dict[str, list[TypeRow]] = defaultdict(list)
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.startswith("T\t"):
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 8:
                    raise SystemExit(f"malformed index row in {path}: {line!r}")
                row = TypeRow(parts[1], parts[2], parts[3], parts[4], parts[5], int(parts[6]), int(parts[7]))
                self.by_full[row.full].append(row)
                self.by_name[row.name].append(row)
                # GameMember resolves obfuscated names inside the Hex assembly only.
                if row.obf and row.asm == "Hex":
                    self.by_obf[row.obf].append(row)
        if not self.by_full:
            raise SystemExit(f"index {path} has no type rows")


def build_index(interop: Path, cache_dir: Path) -> Path:
    hex_dll = interop / "Hex.dll"
    if not hex_dll.is_file():
        raise SystemExit(f"interop dir has no Hex.dll: {interop}")
    digest = hashlib.sha256()
    for dll in sorted(interop.glob("*.dll")):
        digest.update(dll.name.encode("utf-8"))
        digest.update(hashlib.sha256(dll.read_bytes()).digest())
    digest.update(INDEXER.with_name("Program.cs").read_bytes())
    key = digest.hexdigest()[:24]
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"shape_index_{key}.tsv"
    if out.is_file() and out.stat().st_size > 0:
        return out
    tmp = out.with_suffix(".tmp")
    cmd = ["dotnet", "run", "--project", str(INDEXER), "-c", "Release", "--", str(interop), str(tmp)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0 or not tmp.is_file():
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"interop shape indexer failed for {interop}")
    tmp.replace(out)
    return out


# --------------------------------------------------------------------------------------------
# GameSymbols.cs parsing
# --------------------------------------------------------------------------------------------
STRING_LIT = re.compile(r'@?"((?:[^"\\]|\\.)*)"')
DECL = re.compile(
    r"internal\s+(?:const\s+string|static\s+readonly\s+string(?:\[\])?)\s+(\w+)\s*=\s*(.*?);",
    re.S,
)
CLASS_OPEN = re.compile(r"\b(?:static\s+)?(?:partial\s+)?class\s+(\w+)")
TYPE_GROUP_DECL = re.compile(
    r"internal\s+static\s+readonly\s+TypeHintGroup\s+(\w+)\s*=\s*new\s*\((.*?)\);\s*$",
    re.S | re.M,
)
SCOPE_EXPR = re.compile(
    r"(golden|current)\s*:\s*(TypeHintScope\.None|TypeHintScope\.Generated|new\s*\(\s*([\w.]+)\s*,\s*"
    r"new\s+TypeShape\s*\(\s*\"([^\"]*)\"\s*,\s*(\d+)\s*,\s*(\d+)\s*\)\s*\))",
    re.S,
)


def strip_comments(text: str) -> str:
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


@dataclass
class Decl:
    qualified: str  # e.g. "AdventureVisionLaws.DataFogOfWarTypeHints"
    kind: str  # "array" | "const"
    raw: str
    line: int
    values: list[str] | None = None


@dataclass
class ScopeSpec:
    hints_ref: str | None
    hints: list[str]
    shape: tuple[str, int, int] | None


@dataclass
class GroupSpec:
    symbol: str
    group_id: str
    line: int
    scopes: dict[str, ScopeSpec] = field(default_factory=dict)


def class_path_at(text: str) -> list[tuple[int, str]]:
    """Return (offset, dotted class path) boundaries by brace tracking."""
    stack: list[tuple[str, int]] = []
    depth = 0
    pending: str | None = None
    marks: list[tuple[int, str]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        m = CLASS_OPEN.match(text, i) if ch == "c" or ch == "s" or ch == "p" else None
        if m and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
            pending = m.group(1)
            i = m.end()
            continue
        if ch == "{":
            depth += 1
            if pending is not None:
                stack.append((pending, depth))
                pending = None
                marks.append((i, ".".join(s for s, _ in stack[1:])))
        elif ch == "}":
            if stack and stack[-1][1] == depth:
                stack.pop()
                marks.append((i, ".".join(s for s, _ in stack[1:])))
            depth -= 1
        elif ch == ";":
            pending = None
        i += 1
    return marks


def owner_at(marks: list[tuple[int, str]], offset: int) -> str:
    owner = ""
    for pos, path in marks:
        if pos > offset:
            break
        owner = path
    return owner


def parse_game_symbols(path: Path) -> tuple[dict[str, Decl], list[GroupSpec]]:
    raw = path.read_text(encoding="utf-8-sig")
    text = strip_comments(raw)
    marks = class_path_at(text)
    decls: dict[str, Decl] = {}
    for m in DECL.finditer(text):
        owner = owner_at(marks, m.start())
        qualified = f"{owner}.{m.group(1)}" if owner else m.group(1)
        head = m.group(0).split("=")[0]
        # a single `static readonly string` (a former const, so the current-build scope can rewrite it) is
        # gated exactly like the const it replaced
        kind = "array" if "[]" in head else "const"
        decls[qualified] = Decl(qualified, kind, m.group(2).strip(), text.count("\n", 0, m.start()) + 1)

    def resolve(qualified: str, seen: set[str]) -> list[str] | None:
        d = decls.get(qualified)
        if d is None:
            return None
        if d.values is not None:
            return d.values
        if qualified in seen:
            return None
        seen.add(qualified)
        rawv = d.raw
        if rawv.startswith("{") or rawv.startswith("new") or rawv.startswith('"') or rawv.startswith("@\""):
            vals = [bytes(s, "utf-8").decode("unicode_escape") for s in STRING_LIT.findall(rawv)]
        elif "Array.Empty" in rawv:
            vals = []
        else:
            ref = rawv.strip()
            if ref.startswith("GameSymbols."):
                ref = ref[len("GameSymbols.") :]
            target = ref if ref in decls else f"{qualified.rsplit('.', 1)[0]}.{ref}"
            vals = resolve(target, seen)
        d.values = vals
        return vals

    for q in list(decls):
        resolve(q, set())

    groups: list[GroupSpec] = []
    for m in TYPE_GROUP_DECL.finditer(text):
        owner = owner_at(marks, m.start())
        symbol = f"{owner}.{m.group(1)}" if owner else m.group(1)
        body = m.group(2)
        id_ref = body.split(",", 1)[0].strip()
        id_ref = id_ref[len("GameSymbols.") :] if id_ref.startswith("GameSymbols.") else id_ref
        if id_ref.startswith('"'):
            gid = STRING_LIT.findall(id_ref)[0]
        else:
            iv = decls.get(id_ref)
            if iv is None or not iv.values:
                raise SystemExit(f"TypeHintGroup {symbol}: cannot resolve id {id_ref}")
            gid = iv.values[0]
        spec = GroupSpec(symbol, gid, text.count("\n", 0, m.start()) + 1)
        for sm in SCOPE_EXPR.finditer(body):
            build = sm.group(1)
            if sm.group(2).startswith("TypeHintScope.None"):
                spec.scopes[build] = ScopeSpec(None, [], None)
                continue
            if sm.group(2).startswith("TypeHintScope.Generated"):
                if build != "current":
                    raise SystemExit(f"TypeHintGroup {symbol}: TypeHintScope.Generated is only valid for 'current:'")
                gen = generated_type_groups().get(symbol)
                if gen is None:
                    raise SystemExit(f"TypeHintGroup {symbol}: current scope is Generated but {SCOPE_REPORT.name} "
                                     "has no typeGroups entry (regenerate the current scopes)")
                if gen.get("status") == "scoped" and gen.get("liveHint") and gen.get("shape"):
                    b, f, mth = gen["shape"]
                    spec.scopes[build] = ScopeSpec(None, [gen["liveHint"]], (b, int(f), int(mth)))
                else:
                    spec.scopes[build] = ScopeSpec(None, [], None)
                continue
            ref = sm.group(3)
            ref = ref[len("GameSymbols.") :] if ref.startswith("GameSymbols.") else ref
            vals = decls.get(ref)
            if vals is None or vals.values is None:
                raise SystemExit(f"TypeHintGroup {symbol}: cannot resolve {build} hints {ref}")
            spec.scopes[build] = ScopeSpec(ref, list(vals.values), (sm.group(4), int(sm.group(5)), int(sm.group(6))))
        for b in BUILDS:
            if b not in spec.scopes:
                raise SystemExit(f"TypeHintGroup {symbol}: missing '{b}:' scope (use TypeHintScope.None)")
        groups.append(spec)
    return decls, groups


_GENERATED_TYPE_GROUPS: dict | None = None


def generated_type_groups() -> dict:
    global _GENERATED_TYPE_GROUPS
    if _GENERATED_TYPE_GROUPS is None:
        if not SCOPE_REPORT.is_file():
            raise SystemExit(f"missing generated current-scope report {SCOPE_REPORT}")
        doc = json.loads(SCOPE_REPORT.read_text(encoding="utf-8"))
        _GENERATED_TYPE_GROUPS = {g["symbol"]: g for g in doc.get("typeGroups", [])}
    return _GENERATED_TYPE_GROUPS


def check_map_mesh_loader_contract() -> list[str]:
    """Pin the native-body-reviewed UnitViewConfig map-mesh loader through the owning symbol gate."""
    problems: list[str] = []
    symbols = GAME_SYMBOLS.read_text(encoding="utf-8")
    unit_view = re.search(
        r"internal\s+static\s+partial\s+class\s+UnitViewConfig\s*\{(?P<body>.*?)\n\s*\}",
        symbols,
        re.S,
    )
    declaration = re.compile(
        rf'MethodSymbol\s+MapMeshLoader\s*=\s*new\(\s*"unitViewConfig\.mapMesh\.loader"\s*,\s*"{MAP_MESH_LOADER_ALIAS}"\s*\)\s*;'
    )
    if not unit_view or not declaration.search(unit_view.group("body")):
        problems.append(f"GameSymbols.cs: UnitViewConfig.MapMeshLoader must pin only {MAP_MESH_LOADER_ALIAS}")

    try:
        override_doc = json.loads(SCOPE_OVERRIDES.read_text(encoding="utf-8"))
        if override_doc.get("schema") != "game_symbols_current_scope_overrides.v1":
            problems.append(f"{SCOPE_OVERRIDES.name}: unexpected override schema")
        if str(override_doc.get("buildId")) != _current_build_id():
            problems.append(f"{SCOPE_OVERRIDES.name}: override buildId differs from the current scope target")
        override_symbols = override_doc.get("symbols")
        override = (override_symbols.get("UnitViewConfig.MapMeshLoader")
                    if isinstance(override_symbols, dict) else None)
    except (OSError, json.JSONDecodeError) as exc:
        override = None
        problems.append(f"{SCOPE_OVERRIDES.name}: cannot read map-mesh loader pin: {exc}")
    if override is not None:
        if override.get("goldenLiterals") != [MAP_MESH_LOADER_ALIAS]:
            problems.append(f"{SCOPE_OVERRIDES.name}: map-mesh Golden alias changed")
        if override.get("live") != [MAP_MESH_LOADER_ALIAS]:
            problems.append(f"{SCOPE_OVERRIDES.name}: map-mesh live alias changed")
        if override.get("owners") != [MAP_MESH_LOADER_OWNER]:
            problems.append(f"{SCOPE_OVERRIDES.name}: map-mesh live owner changed")
        evidence = override.get("evidence", "")
        for pin in (
            "D47706EB0FFEDBDA0EC07EDE47ABC778E6022ED820AE1A1FD23522D3ACDB8416",
            "D9972B0E7F7DD1C17758808E2F1B80E0A728946416D9A41DEAA99BAD744DE53A",
            "100685816:seo",
            "100686425:szi",
            "layout-derived",
            "Static evidence only",
        ):
            if pin not in evidence:
                problems.append(f"{SCOPE_OVERRIDES.name}: map-mesh evidence is missing {pin!r}")
    else:
        if not any(f"{SCOPE_OVERRIDES.name}: cannot read" in p for p in problems):
            problems.append(f"{SCOPE_OVERRIDES.name}: missing UnitViewConfig.MapMeshLoader pin")

    try:
        remap_doc = json.loads(SCOPE_REMAP.read_text(encoding="utf-8"))
        remap_group = next((g for g in remap_doc.get("groups", [])
                            if g.get("symbol") == "UnitViewConfig.MapMeshLoader"), None)
    except (OSError, json.JSONDecodeError) as exc:
        remap_group = None
        problems.append(f"{SCOPE_REMAP.name}: cannot read map-mesh source row: {exc}")
    if remap_group is not None:
        if remap_group.get("literals") != [MAP_MESH_LOADER_ALIAS]:
            problems.append(f"{SCOPE_REMAP.name}: map-mesh remap row does not match the Golden hint")
        if remap_group.get("resolution") != "unmapped":
            problems.append(f"{SCOPE_REMAP.name}: manual map-mesh pin must not be represented as an algorithm mapping")
        entries = remap_group.get("entries", [])
        if (len(entries) != 1 or entries[0].get("golden") != MAP_MESH_LOADER_ALIAS
                or entries[0].get("status") != "UNMAPPED"
                or entries[0].get("confidence") != 0.0
                or entries[0].get("goldenOwner") != MAP_MESH_LOADER_OWNER
                or entries[0].get("liveOwner") != MAP_MESH_LOADER_OWNER
                or entries[0].get("candidates") != []):
            problems.append(f"{SCOPE_REMAP.name}: manual map-mesh row must retain exact owners without fabricated candidates/scores")
    elif not any(f"{SCOPE_REMAP.name}: cannot read" in p for p in problems):
        problems.append(f"{SCOPE_REMAP.name}: missing UnitViewConfig.MapMeshLoader source row")

    try:
        scope_report = json.loads(SCOPE_REPORT.read_text(encoding="utf-8"))
        scope_row = next((row for row in scope_report.get("declarations", [])
                          if row.get("symbol") == "UnitViewConfig.MapMeshLoader"), None)
    except (OSError, json.JSONDecodeError) as exc:
        scope_row = None
        problems.append(f"{SCOPE_REPORT.name}: cannot read map-mesh generated scope: {exc}")
    if scope_row is not None:
        if (scope_row.get("status") != "scoped"
                or scope_row.get("live") != [MAP_MESH_LOADER_ALIAS]
                or scope_row.get("owners") != [MAP_MESH_LOADER_OWNER]
                or scope_row.get("remapResolution") != "unmapped"):
            problems.append(f"{SCOPE_REPORT.name}: map-mesh override is not the expected owner-scoped manual pin")
        if scope_row.get("minConfidence") is not None:
            problems.append(f"{SCOPE_REPORT.name}: manual map-mesh pin must not report an algorithm confidence score")
    elif not any(f"{SCOPE_REPORT.name}: cannot read" in p for p in problems):
        problems.append(f"{SCOPE_REPORT.name}: missing UnitViewConfig.MapMeshLoader scope row")

    hook_path = PLUGIN_DIR / "CustomUnitViewRouting.cs"
    try:
        hook_source = hook_path.read_text(encoding="utf-8")
        marker = "internal static class UnitViewConfigGetMapPrefabPatch"
        start = hook_source.index(marker)
        end = hook_source.index("\n}\n", start)
        hook = re.sub(r"\s+", "", hook_source[start:end])
    except (OSError, ValueError) as exc:
        hook = ""
        problems.append(f"{hook_path.name}: cannot read map-mesh patch: {exc}")
    if hook:
        required_hook_fragments = (
            "GameMember.FindMethods(typeof(UnitViewConfig),typeof(GameObject),Type.EmptyTypes,GameSymbols.UnitViewConfig.MapMeshLoader)",
            "privatestaticboolPrepare()",
            "ResolveTargetMethod();return_targetMethod!=null;",
            "candidates.Length==1&&candidates[0].DeclaringType==typeof(UnitViewConfig)&&!candidates[0].IsStatic&&!candidates[0].IsGenericMethod",
            "Plugin.LogSource?.LogWarning(",
            "return_targetMethod??thrownewMissingMethodException(",
        )
        for fragment in required_hook_fragments:
            if fragment not in hook:
                problems.append(f"{hook_path.name}: map-mesh target contract is missing {fragment}")
        if "AccessTools.Method(" in hook:
            problems.append(f"{hook_path.name}: map-mesh patch must not resolve a raw method name")
    return problems


def check_unit_preview_wrapper_contract() -> list[str]:
    """Keep the preview wrapper read tied to exact current interop metadata and owner."""
    problems: list[str] = []
    pointer_name = "NativeFieldInfoPtr_field_Private_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_0"
    field_name = "field_Private_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_0"
    owner_name = "Hex.Session.Battle.BhUnitWindowPreview"
    wrapper_name = "MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique"
    expected_literals = [pointer_name, field_name]

    try:
        symbols = GAME_SYMBOLS.read_text(encoding="utf-8")
        unit_preview = re.search(
            r"internal\s+static\s+partial\s+class\s+UnitPreview\s*\{(?P<body>.*?)\n\s*\}",
            symbols,
            re.S,
        )
        declaration = re.compile(
            rf'FieldSymbol\s+WindowPreviewWrapperField\s*=\s*new\(\s*"unitPreview\.window\.wrapper"\s*,\s*"{re.escape(pointer_name)}"\s*,\s*"{re.escape(field_name)}"\s*\)\s*;'
        )
        if not unit_preview or not declaration.search(unit_preview.group("body")):
            problems.append("GameSymbols.cs: UnitPreview.WindowPreviewWrapperField must centralize the exact native pointer/member pair")
        if "WindowWrapperFields" in symbols:
            problems.append("GameSymbols.cs: obsolete broad preview-wrapper name list must not remain")
    except OSError as exc:
        symbols = ""
        problems.append(f"GameSymbols.cs: cannot read preview-wrapper symbol declaration: {exc}")

    try:
        override_doc = json.loads(SCOPE_OVERRIDES.read_text(encoding="utf-8"))
        override_symbols = override_doc.get("symbols", {})
        override = override_symbols.get("UnitPreview.WindowPreviewWrapperField") if isinstance(override_symbols, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        override = None
        problems.append(f"{SCOPE_OVERRIDES.name}: cannot read preview-wrapper current pin: {exc}")
    if override is not None:
        if override.get("goldenLiterals") != expected_literals or override.get("live") != expected_literals:
            problems.append(f"{SCOPE_OVERRIDES.name}: preview-wrapper pointer/member pair changed")
        if override.get("owners") != [owner_name]:
            problems.append(f"{SCOPE_OVERRIDES.name}: preview-wrapper owner changed")
        evidence = override.get("evidence", "")
        for pin in (
            "D47706EB0FFEDBDA0EC07EDE47ABC778E6022ED820AE1A1FD23522D3ACDB8416",
            "EDE61A05C38006AD853AB716F21CA882A4E0480EAAD46C86FDFB135D01EFFD04",
            "D9972B0E7F7DD1C17758808E2F1B80E0A728946416D9A41DEAA99BAD744DE53A",
            "A535D47EF5E8C929CA7C4794D9EC596C8D40DDAAD7FBDB1AE7A2B0C2C296D4D7",
            owner_name,
            wrapper_name,
            "Model (UnityEngine.GameObject)",
            "Rotatable (UnityEngine.GameObject)",
            "Background (UnityEngine.MeshRenderer)",
            "runtime field read and preview behavior remain unproven",
        ):
            if pin not in evidence:
                problems.append(f"{SCOPE_OVERRIDES.name}: preview-wrapper evidence is missing {pin!r}")
    elif not any(f"{SCOPE_OVERRIDES.name}: cannot read" in p for p in problems):
        problems.append(f"{SCOPE_OVERRIDES.name}: missing UnitPreview.WindowPreviewWrapperField pin")

    try:
        scope_doc = json.loads(SCOPE_REPORT.read_text(encoding="utf-8"))
        scope = next((row for row in scope_doc.get("declarations", [])
                      if row.get("symbol") == "UnitPreview.WindowPreviewWrapperField"), None)
    except (OSError, json.JSONDecodeError) as exc:
        scope = None
        problems.append(f"{SCOPE_REPORT.name}: cannot read preview-wrapper generated scope: {exc}")
    if scope is not None:
        if (scope.get("declType") != "FieldSymbol" or scope.get("status") != "scoped"
                or scope.get("live") != expected_literals or scope.get("owners") != [owner_name]
                or scope.get("remapResolution") != "not-in-remap"
                or scope.get("minConfidence") is not None):
            problems.append(f"{SCOPE_REPORT.name}: preview-wrapper pin must be a confidence-free, exact-owner manual scope")
    elif not any(f"{SCOPE_REPORT.name}: cannot read" in p for p in problems):
        problems.append(f"{SCOPE_REPORT.name}: missing UnitPreview.WindowPreviewWrapperField scope row")

    generated = SCOPE_CS.read_text(encoding="utf-8") if SCOPE_CS.is_file() else ""
    if "WindowPreviewWrapperField = GameSymbolScope.Field(" not in generated or owner_name not in generated:
        problems.append(f"{SCOPE_CS.name}: preview-wrapper symbol must generate an owner-scoped Field binding")
    if 'RefuseField("UnitPreview.WindowPreviewWrapperField"' in generated:
        problems.append(f"{SCOPE_CS.name}: preview-wrapper field is still refused")

    hook_path = PLUGIN_DIR / "Homm3ImportUnitPreviewModelHook.cs"
    try:
        hook_source = hook_path.read_text(encoding="utf-8")
        marker = "private static object TryGetPreviewWrapper(BhUnitWindowPreview instance)"
        start = hook_source.index(marker)
        end = hook_source.index("\n\tprivate static bool HasNativePreviewWrapperSurface", start)
        hook = re.sub(r"\s+", "", hook_source[start:end])
    except (OSError, ValueError) as exc:
        hook = ""
        problems.append(f"{hook_path.name}: cannot read exact preview-wrapper hook: {exc}")
    if hook:
        required = (
            "varownerType=typeof(BhUnitWindowPreview)",
            "varpin=GameSymbols.UnitPreview.WindowPreviewWrapperField",
            "BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Instance|BindingFlags.DeclaredOnly",
            "HasNativePreviewWrapperSurface(wrapperType)",
            "DeobfInteropCompat.TryReadNativeObjectFieldDeclared(instance,ownerType,wrapperType,pin,outvarwrapper,outvarfailure)",
        )
        for fragment in required:
            if fragment not in hook:
                problems.append(f"{hook_path.name}: exact preview-wrapper contract is missing {fragment}")
        if "GetMemberValue(" in hook or "WindowWrapperFields" in hook:
            problems.append(f"{hook_path.name}: preview wrapper must not fall back to guessed property aliases")

    compat_path = PLUGIN_DIR / "DeobfInteropCompat.cs"
    try:
        compat_source = compat_path.read_text(encoding="utf-8")
        marker = "internal static bool TryReadNativeObjectFieldDeclared("
        start = compat_source.index(marker)
        end = compat_source.index("\n\tpublic static string TryReadNativeStringMember", start)
        reader = re.sub(r"\s+", "", compat_source[start:end])
    except (OSError, ValueError) as exc:
        reader = ""
        problems.append(f"{compat_path.name}: cannot read declared native object-field reader: {exc}")
    if reader:
        required = (
            "declaringType.IsInstanceOfType(owner)",
            "ownerisnotIl2CppObjectBaseil2Cpp||il2Cpp.Pointer==IntPtr.Zero",
            '!string.Equals(member.NativeFieldInfoName,"NativeFieldInfoPtr_"+member.FieldName,StringComparison.Ordinal)',
            "metadataType!=expectedType",
            "declaringType.GetField(member.NativeFieldInfoName,declaredStatic)",
            "pointerField.FieldType!=typeof(IntPtr)",
            "NativeFieldClassAssignableToExpectedType(fieldPointer,expectedType,outfailure)",
            "IL2CPP.il2cpp_field_get_offset(fieldPointer)",
            "CreateIl2CppObjectWrapper(valuePointer,expectedType)",
        )
        for fragment in required:
            if fragment not in reader:
                problems.append(f"{compat_path.name}: declared native object-field reader lacks {fragment}")

        marker = "private static bool NativeFieldClassAssignableToExpectedType("
        try:
            start = compat_source.index(marker)
            end = compat_source.index("\n\tprivate static bool NativeFieldTypeAssignableTo(", start)
            native_type_check = re.sub(r"\s+", "", compat_source[start:end])
        except ValueError as exc:
            native_type_check = ""
            problems.append(f"{compat_path.name}: cannot read native class identity check: {exc}")
        if native_type_check:
            native_required = (
                "IL2CPP.il2cpp_field_get_type(fieldPtr)",
                "IL2CPP.il2cpp_class_from_il2cpp_type(nativeFieldType)",
                "TryGetNativeClassPointer(expectedType,outvarexpectedClass,outfailure)",
                "IL2CPP.il2cpp_class_is_assignable_from(expectedClass,nativeFieldClass)",
                "RuntimeHelpers.RunClassConstructor(classPointerStore.TypeHandle)",
                'classPointerStore.GetField("NativeClassPtr",BindingFlags.Public|BindingFlags.Static)',
            )
            for fragment in native_required:
                if fragment not in native_type_check:
                    problems.append(f"{compat_path.name}: native class identity check lacks {fragment}")
            if any(fragment in native_type_check for fragment in (
                "ResolveNativeFieldTypeName(",
                "GameInteropTypes.GetNativeTypeAliases(",
                "NativeTypeNameMatchesExpectedAlias(",
            )):
                problems.append(f"{compat_path.name}: exact declared wrapper field must use native class identity, not generated type-name aliases")
    return problems


def check_current_scope_contract() -> list[str]:
    """Structural + freshness checks for the generated current-build scopes. Returns failure lines."""
    problems: list[str] = []
    problems.extend(check_map_mesh_loader_contract())
    problems.extend(check_unit_preview_wrapper_contract())
    text = strip_comments(GAME_SYMBOLS.read_text(encoding="utf-8"))
    for m in re.finditer(r"\b((?:(?:internal|public|private|static|partial|sealed)\s+)*)class\s+(\w+)", text):
        mods = m.group(1).split()
        if "static" in mods and "partial" not in mods:
            problems.append(f"GameSymbols.cs: static class {m.group(2)} is not partial (generated scopes attach to it)")
    if not SCOPE_CS.is_file():
        problems.append(f"missing {SCOPE_CS.name}")
    else:
        gen = SCOPE_CS.read_text(encoding="utf-8").replace("\r\n", "\n")
        ctors = list(re.finditer(r"static\s+(\w+)\s*\(\s*\)\s*\{\s*([^\n]*)", gen))
        if not ctors:
            problems.append(f"{SCOPE_CS.name}: no generated static constructors")
        for c in ctors:
            if not c.group(2).startswith(SCOPE_GUARD):
                problems.append(f"{SCOPE_CS.name}: static {c.group(1)}() does not start with the current-build guard")
    proc = subprocess.run([sys.executable, str(SCOPE_GENERATOR), "--check"], cwd=str(REPO),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        problems.append("current-build scopes are STALE or failed to generate "
                        "(run tools/port_current/generate_current_symbol_scopes.py):\n    " + out.replace("\n", "\n    "))
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "validate_symbol_literal_confinement.py")],
                          cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        problems.append("symbol literal confinement gate failed:\n    " + out.replace("\n", "\n    "))
    return problems


def flat_type_groups(decls: dict[str, Decl]) -> list[Decl]:
    out = []
    for d in decls.values():
        leaf = d.qualified.rsplit(".", 1)[-1]
        if d.qualified.startswith("TypeGroups."):
            continue
        if d.kind == "array" and re.search(r"TypeHints$", leaf):
            out.append(d)
        elif d.kind == "const" and re.search(r"TypeHint$", leaf):
            out.append(d)
    return sorted(out, key=lambda d: d.qualified)


def type_group_owned_flat_refs_to_exclude(groups: list[GroupSpec], build: str) -> set[str]:
    """Return type-hint arrays covered by a TypeGroup scope instead of a flat build check.

    Preserve the legacy handling of current-only arrays on both builds. Golden-only arrays are now
    also excluded on Current because their current TypeGroup scope supplies the generated replacement.
    Shared arrays and standalone flat arrays remain in the selected-build flat check.
    """
    if build not in BUILDS:
        raise ValueError(f"unsupported GameSymbols build {build!r}; expected one of {BUILDS}")

    golden_refs = {group.scopes["golden"].hints_ref for group in groups if group.scopes["golden"].hints_ref}
    current_refs = {group.scopes["current"].hints_ref for group in groups if group.scopes["current"].hints_ref}
    if build == "golden":
        return current_refs - golden_refs
    return golden_refs ^ current_refs


# --------------------------------------------------------------------------------------------
# Resolution models
# --------------------------------------------------------------------------------------------
def candidates_for_hint(index: InteropIndex, hint: str) -> list[TypeRow]:
    """Every type a hint can reach through the central resolver's routes (full name, obfuscated name)."""
    found: dict[tuple[str, str], TypeRow] = {}
    for row in index.by_full.get(hint, []):
        found[(row.asm, row.full)] = row
    for row in index.by_obf.get(hint, []):
        found[(row.asm, row.full)] = row
    return list(found.values())


def legacy_first_pick(index: InteropIndex, hints: list[str]) -> tuple[TypeRow | None, str]:
    """Pre-migration ResolveFirstType: per hint, GameMember.FindType (full name, then Hex obfuscated
    name), then AccessTools.TypeByName (full name, then simple name). First hit wins."""
    for hint in hints:
        if not hint:
            continue
        full = index.by_full.get(hint, [])
        if full:
            return full[0], ("ambiguous-full" if len(full) > 1 else f"full:{hint}")
        obf = index.by_obf.get(hint, [])
        if obf:
            return obf[0], ("ambiguous-obf" if len(obf) > 1 else f"obf:{hint}")
        simple = index.by_name.get(hint, [])
        if simple:
            return simple[0], ("ambiguous-simple" if len(simple) > 1 else f"simple:{hint}")
    return None, "none"


def generated_flat_scopes() -> dict[str, dict]:
    """Generated current-build scope rows (``declarations``) by symbol, aliases resolved to their target."""
    doc = json.loads(SCOPE_REPORT.read_text(encoding="utf-8"))
    rows = {r["symbol"]: r for r in doc.get("declarations", [])}
    out = {}
    for sym, row in rows.items():
        if row.get("status") == "alias":
            m = re.match(r"aliases (\S+);", row.get("reason") or "")
            row = rows.get(m.group(1), row) if m else row
        out[sym] = row
    return out


def current_flat_hints(decl: Decl, scopes: dict[str, dict]) -> tuple[list[str], str | None, str]:
    """The hints the runtime actually resolves for a flat group on the current build.

    GameSymbolsCurrent.g.cs rewrites every scoped declaration to its generated live literals (a null
    position becomes a refusal sentinel) and replaces a refused declaration with sentinels, so the
    selected-build check evaluates those, not the Golden Era literals in GameSymbols.cs. Rows the
    generator leaves untouched (identity, const, not generated) keep the declared literals.
    Returns (hints, refusal reason or None, source label).
    """
    row = scopes.get(decl.qualified)
    if row is None:
        return [h for h in (decl.values or []) if h], None, "declared"
    status = row.get("status")
    if status == "refused":
        return [], row.get("reason") or "refused by the generated current scope", "generated-refused"
    if status == "scoped":
        live = [h for h in (row.get("live") or []) if h]
        if not live:
            return [], "generated current scope kept no live literal", "generated-refused"
        return live, None, "generated"
    return [h for h in (decl.values or []) if h], None, "declared"


def evaluate_flat(index: InteropIndex, decl: Decl, scopes: dict[str, dict] | None = None) -> dict:
    source, refused = "declared", None
    if scopes is None:
        hints = [h for h in (decl.values or []) if h]
    else:
        hints, refused, source = current_flat_hints(decl, scopes)
    if refused is not None:
        return {
            "group": decl.qualified,
            "line": decl.line,
            "status": "refused",
            "binding": "none",
            "source": source,
            "detail": refused,
            "resolved": [],
            "perHint": {},
        }
    reached: dict[tuple[str, str], TypeRow] = {}
    per_hint = {}
    for h in hints:
        c = candidates_for_hint(index, h)
        per_hint[h] = [r.full for r in c]
        for r in c:
            reached[(r.asm, r.full)] = r
    if not hints:
        status = "empty"
    elif not reached:
        status = "miss"
    elif len(reached) > 1:
        status = "ambiguous"
    else:
        status = "ok"
    # Off Golden Era the runtime build gate refuses any flat hint that binds an obfuscated/generated
    # type (the type carries ObfuscatedNameAttribute); only real-name bindings survive there.
    binding = "none"
    if reached:
        binding = "obfuscated" if any(r.obf for r in reached.values()) else "real-name"
    return {
        "group": decl.qualified,
        "line": decl.line,
        "status": status,
        "binding": binding,
        "source": source,
        "resolved": sorted(r.full for r in reached.values()),
        "perHint": per_hint,
    }


def evaluate_scoped(index: InteropIndex, spec: GroupSpec, build: str) -> dict:
    scope = spec.scopes[build]
    result = {"group": spec.symbol, "id": spec.group_id, "line": spec.line, "build": build}
    if not scope.hints:
        result["status"] = "refused"
        result["detail"] = f"{build} scope is empty; the runtime resolver refuses this group on this build"
        return result
    shaped: dict[tuple[str, str], TypeRow] = {}
    rejected = []
    for h in scope.hints:
        for r in candidates_for_hint(index, h):
            if r.shape == scope.shape:
                shaped[(r.asm, r.full)] = r
            else:
                rejected.append({"hint": h, "type": r.full, "shape": list(r.shape)})
    result["expectedShape"] = list(scope.shape) if scope.shape else None
    result["rejected"] = rejected
    result["accepted"] = sorted(r.full for r in shaped.values())
    if len(shaped) == 1:
        accepted = next(iter(shaped.values()))
        result["status"] = "ok"
        if build == "golden":
            legacy, how = legacy_first_pick(index, scope.hints)
            result["legacyPick"] = legacy.full if legacy else None
            result["legacyRoute"] = how
            if legacy is None or legacy.full != accepted.full or how.startswith("ambiguous"):
                result["status"] = "behaviour-change"
    elif not shaped:
        result["status"] = "miss"
    else:
        result["status"] = "ambiguous"
    return result


def scan_resolver_copies(plugin_dir: Path) -> list[str]:
    hits = []
    for cs in sorted(plugin_dir.glob("*.cs")):
        text = cs.read_text(encoding="utf-8-sig", errors="replace")
        for m in FORBIDDEN_RESOLVER_COPY.finditer(strip_comments(text)):
            hits.append(f"{cs.name}:{text.count(chr(10), 0, m.start()) + 1}")
    return hits


def load_allowlist(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line)
    return out


def emit_shapes(index: InteropIndex, decls: dict[str, Decl], names: list[str]) -> None:
    for q in names:
        d = decls.get(q)
        if d is None:
            print(f"{q}: not found")
            continue
        legacy, how = legacy_first_pick(index, d.values or [])
        if legacy is None:
            print(f"{q}: no legacy pick")
            continue
        print(f'{q}: {legacy.full} via {how} -> new TypeShape("{legacy.base}", {legacy.fields}, {legacy.methods})')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", choices=BUILDS, action="append", required=True,
                    help="build scope to check; repeat with a matching --interop/--index for each")
    ap.add_argument("--interop", action="append", default=[], help="interop dir per --build (runs the indexer)")
    ap.add_argument("--index", action="append", default=[], help="prebuilt shape index TSV per --build")
    ap.add_argument("--gate", choices=BUILDS, action="append", default=[],
                    help="builds whose findings fail the run (others are report-only)")
    ap.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--report", type=Path, help="write the full JSON report here")
    ap.add_argument("--emit-shapes", nargs="*", help="print legacy pick + TypeShape literal for these groups")
    ap.add_argument("--print-allowlist", action="store_true", help="print the current findings as allow-list lines")
    args = ap.parse_args()

    sources = args.interop or args.index
    if len(sources) != len(args.build) or (args.interop and args.index):
        ap.error("pass exactly one --interop or --index per --build, in the same order")

    decls, groups = parse_game_symbols(GAME_SYMBOLS)
    # Arrays owned by a TypeGroup are checked through the selected build's scope, not as a flat
    # declaration from the other build. Keep the all-type-array set for the unchecked member count.
    non_golden_refs = {g.scopes[b].hints_ref for g in groups for b in BUILDS if b != "golden" and g.scopes[b].hints_ref}
    golden_refs = {g.scopes["golden"].hints_ref for g in groups}
    all_flat_type_groups = flat_type_groups(decls)
    type_arrays = {d.qualified for d in flat_type_groups(decls) if d.kind == "array"} | non_golden_refs
    member_groups = sum(1 for d in decls.values() if d.kind == "array" and d.qualified not in type_arrays)
    allow = load_allowlist(args.allowlist)
    report = {"schema": "game_symbols_hint_contract.v1", "builds": {}, "resolverCopies": scan_resolver_copies(PLUGIN_DIR)}
    findings_by_build: dict[str, set[str]] = {}
    all_lines: list[str] = []

    for build, src in zip(args.build, sources):
        index_path = build_index(Path(src), args.cache_dir) if args.interop else Path(src)
        index = InteropIndex(index_path)
        if args.emit_shapes is not None:
            emit_shapes(index, decls, args.emit_shapes)
            return 0
        excluded_refs = type_group_owned_flat_refs_to_exclude(groups, build)
        flats = [d for d in all_flat_type_groups if d.qualified not in excluded_refs]
        # On the current build the flat groups are checked as GameSymbolsCurrent.g.cs rewrites them.
        flat_scopes = generated_flat_scopes() if build == "current" else None
        flat_results = [evaluate_flat(index, d, flat_scopes) for d in flats]
        scoped_results = [evaluate_scoped(index, g, build) for g in groups]
        findings = set()
        for r in flat_results:
            if r["status"] in ("miss", "ambiguous"):
                findings.add(f"{build}|flat|{r['group']}|{r['status']}")
        for r in scoped_results:
            if r["status"] not in ("ok", "refused"):
                findings.add(f"{build}|scoped|{r['group']}|{r['status']}")
        findings_by_build[build] = findings
        all_lines.extend(sorted(findings))
        counts = defaultdict(int)
        for r in flat_results:
            counts["flat_" + r["status"]] += 1
            counts["binding_" + r["binding"]] += 1
        for r in scoped_results:
            counts["scoped_" + r["status"]] += 1
        report["builds"][build] = {
            "source": str(src),
            "index": str(index_path),
            "flatTypeGroups": len(flat_results),
            "scopedTypeGroups": len(scoped_results),
            "memberGroupsUnchecked": member_groups,
            "counts": dict(sorted(counts.items())),
            "flat": flat_results,
            "scoped": scoped_results,
        }
        print(f"[{build}] {src}")
        print(f"  flat type groups: {len(flat_results)}  " + ", ".join(
            f"{k[5:]}={v}" for k, v in sorted(counts.items()) if k.startswith("flat_")))
        print("  flat bindings: " + ", ".join(
            f"{k[8:]}={v}" for k, v in sorted(counts.items()) if k.startswith("binding_"))
            + ("" if build == "golden" else "  (obfuscated ones are refused at runtime off Golden Era)"))
        print(f"  scoped TypeGroups: {len(scoped_results)}  " + ", ".join(
            f"{k[7:]}={v}" for k, v in sorted(counts.items()) if k.startswith("scoped_")))
        print(f"  member groups not checked by this tier (no owner in GameSymbols): {member_groups}")
        for r in scoped_results:
            if r["status"] not in ("ok", "refused"):
                print(f"  SCOPED {r['status']}: {r['group']} accepted={r.get('accepted')} legacy={r.get('legacyPick')} "
                      f"route={r.get('legacyRoute')} expected={r.get('expectedShape')}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"report: {args.report}")
    if args.print_allowlist:
        print("\n".join(all_lines))
        return 0

    failed = False
    scope_problems = check_current_scope_contract()
    report["currentScopeContract"] = scope_problems
    if scope_problems:
        failed = True
        print("FAIL: generated current-build scope contract:")
        for line in scope_problems:
            print("  " + line)
    else:
        print("current-build scope contract: OK (map-mesh manual pin, fresh scopes, partial classes, guarded constructors, literal confinement)")
    if report["resolverCopies"]:
        failed = True
        print("FAIL: per-file ResolveFirstType resolver copies remain (use GameMember.ResolveTypeGroup):")
        for h in report["resolverCopies"]:
            print("  " + h)
    for build in args.gate:
        if build not in findings_by_build:
            ap.error(f"--gate {build} requires --build {build}")
        findings = findings_by_build[build]
        allowed = {a for a in allow if a.startswith(build + "|")}
        new = sorted(findings - allowed)
        stale = sorted(allowed - findings)
        # Scoped groups are new-contract surfaces: they are never allow-listable.
        scoped_allowed = sorted(a for a in allowed if a.split("|")[1] == "scoped")
        print(f"[{build}] gate: findings={len(findings)} allowlisted={len(findings & allowed)} new={len(new)} stale-allowlist={len(stale)}")
        for line in new:
            print("  NEW " + line)
        for line in stale:
            print("  STALE (remove from allowlist) " + line)
        for line in scoped_allowed:
            print("  FORBIDDEN allowlist entry for a scoped group " + line)
        if new or stale or scoped_allowed:
            failed = True
    print("game symbols hint contract: " + ("FAIL" if failed else "OK"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
