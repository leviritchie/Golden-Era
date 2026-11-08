"""Check the bounded native ConfigElementBase<string>.id reader contract."""
from __future__ import annotations

import argparse
import sys
import time
import tracemalloc
from pathlib import Path


STRING_NATIVE_TYPES = {"System.String", "String", "Il2CppSystem.String"}
OBJECT_CONFIG_TAGS = {
	"Artifact", "Interact", "Environment", "Animals", "FX", "TEST",
	"Resource", "meta", "Block",
}
ID_NATIVE_ALIASES = {"id", "field_Public_IDType_0"}


def policy_fixture(case: dict[str, str | None]) -> str | None:
	"""Model static policy examples; this does not execute production C# or IL2CPP."""
	if case["owner"] != "ConfigElementBase" or case["generic_arg"] != "System.String":
		return None
	if case["alias"] not in ID_NATIVE_ALIASES or case["native_type"] not in STRING_NATIVE_TYPES:
		return None

	candidate = (case["native_value"] or "").strip()
	if not candidate or candidate == case["tag"] or candidate in OBJECT_CONFIG_TAGS:
		return None
	return candidate


def main() -> int:
	started = time.perf_counter()
	tracemalloc.start()
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", default=Path(__file__).resolve().parent.parent)
	args = parser.parse_args()
	root = Path(args.repo_root).resolve()
	plugin = root / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
	paths = {
		"compat": plugin / "DeobfInteropCompat.cs",
		"symbols": plugin / "GameSymbols.cs",
		"routing": plugin / "CustomUnitViewRouting.cs",
		"billboard": plugin / "TempleSwordsmanBillboardPrototype.cs",
		"project": plugin / "OfflineUnlockMod.csproj",
	}
	errors: list[str] = []
	for label, path in paths.items():
		if not path.is_file():
			errors.append(f"missing {label} source: {path.relative_to(root)}")
	if errors:
		for error in errors:
			print("ERROR " + error)
		return 1

	compat = paths["compat"].read_text(encoding="utf-8")
	symbols = paths["symbols"].read_text(encoding="utf-8")
	routing = paths["routing"].read_text(encoding="utf-8")
	billboard = paths["billboard"].read_text(encoding="utf-8")
	project = paths["project"].read_text(encoding="utf-8")

	if ("UnitViewConfig.ConfigElementBaseStringIdNativeFieldAliases" not in compat
			or "ConfigElementBaseStringIdNativeFieldAliases" not in symbols
			or '"field_Public_IDType_0"' not in symbols
			or '"Hex.Configs.ConfigElementBase`1"' not in symbols):
		errors.append("GameSymbols must own the current typed ConfigElementBase<string> ID alias")
	if '"field_Public_IDType_0"' in compat or '"field_Public_IDType_0"' in routing or '"field_Public_IDType_0"' in billboard:
		errors.append("the generated ID alias must not be duplicated outside GameSymbols")

	get_id_start = compat.find("public static bool TryGetConfigElementId(object config, out string id)")
	get_id_end = compat.find("public static bool TrySetConfigElementId", get_id_start)
	try_api = compat[get_id_start:get_id_end] if get_id_start >= 0 and get_id_end > get_id_start else ""
	if "TryReadNativeConfigElementBaseId(config, out id, out _)" not in try_api:
		errors.append("TryGetConfigElementId must call the strict native-only reader directly")
	if any(marker in try_api for marker in ("TryReadConfigElementId(", "TryReadDeclaredStringField(", "TryReadNativeStringMember(target, \"id\")")):
		errors.append("TryGetConfigElementId must not reach legacy CLR or broad-name ID fallbacks")
	legacy_get_start = compat.find("public static string GetConfigElementId(object config)")
	legacy_get_end = get_id_start
	legacy_get = compat[legacy_get_start:legacy_get_end] if legacy_get_start >= 0 and legacy_get_end > legacy_get_start else ""
	if "TryReadConfigElementId(config, out var id)" not in legacy_get:
		errors.append("GetConfigElementId must retain the broad legacy reader for mixed callers")

	native_id_start = compat.find("private static bool TryReadNativeConfigElementBaseId(object target, out string id, out string tag)")
	native_id_end = compat.find("private static bool TryReadConfigElementId(object target, out string id)", native_id_start)
	native_id_reader = compat[native_id_start:native_id_end] if native_id_start >= 0 and native_id_end > native_id_start else ""
	if "target is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero" not in native_id_reader:
		errors.append("strict native ID reader must require a live Il2CppObjectBase")
	if "IsStringConfigElementBaseType(cur)" not in native_id_reader or "TryReadNativeStringMember(target, cur, aliases[i])" not in native_id_reader:
		errors.append("native ID reads must be scoped to the closed ConfigElementBase<string> owner")
	if "TryAcceptConfigElementId(candidate, tag, out id)" not in native_id_reader:
		errors.append("native candidate acceptance must retain the derived-tag/category guard")
	if any(marker in native_id_reader for marker in ("TryReadConfigElementId(", "TryReadDeclaredStringField(", "TryReadObjectConfigTag(", "GetProperty(", "GetMethod(", ".Invoke(")):
		errors.append("strict native reader must not invoke getters or enter legacy field fallback")

	legacy_start = native_id_end
	legacy_end = compat.find("private static string TryReadObjectConfigTag", legacy_start)
	legacy_reader = compat[legacy_start:legacy_end] if legacy_start >= 0 and legacy_end > legacy_start else ""
	if not ("TryReadNativeConfigElementBaseId(target, out id, out var tag)" in legacy_reader
			and legacy_reader.find("TryReadNativeConfigElementBaseId(target, out id, out var tag)") < legacy_reader.find("TryReadNativeStringMember(target, \"id\")")
			and "TryReadDeclaredStringField" in legacy_reader):
		errors.append("legacy GetConfigElementId must retain its existing fallbacks after the shared typed native read")

	string_owner_start = compat.find("private static bool IsStringConfigElementBaseType(Type type)")
	string_owner_end = compat.find("private static bool TryReadDeclaredStringField", string_owner_start)
	string_owner = compat[string_owner_start:string_owner_end] if string_owner_start >= 0 and string_owner_end > string_owner_start else ""
	if ("arguments[0] == typeof(string)" not in string_owner
			or "GetGenericTypeDefinition()" not in string_owner
			or "GameSymbols.UnitViewConfig.ConfigElementBaseGenericTypeFullName" not in string_owner):
		errors.append("ConfigElementBase ID owner check must require the exact string specialization")

	native_reader_start = compat.find("private static string TryReadNativeStringMember(object owner, Type declaringType, string name)")
	native_reader_end = compat.find("private static IntPtr ResolveNativeFieldPointer(Type ownerType, string logicalName)", native_reader_start)
	native_reader = compat[native_reader_start:native_reader_end] if native_reader_start >= 0 and native_reader_end > native_reader_start else ""
	if "ResolveNativeFieldPointerDeclared(declaringType, name)" not in native_reader:
		errors.append("typed alias lookup must resolve the native field on the pinned declaring type only")
	if not ("NativeFieldTypeIsString(fieldPtr)" in native_reader
			and native_reader.find("NativeFieldTypeIsString(fieldPtr)") < native_reader.find("il2cpp_field_get_offset(fieldPtr)")
			and native_reader.find("NativeFieldTypeIsString(fieldPtr)") < native_reader.find("Il2CppStringToManaged(valuePtr)")):
		errors.append("native field type must be proven String before reading/converting its value")

	accept_start = compat.find("private static bool TryAcceptConfigElementId(")
	accept_end = compat.find("private static bool IsKnownObjectConfigCategoryTag", accept_start)
	accept = compat[accept_start:accept_end] if accept_start >= 0 and accept_end > accept_start else ""
	if "string.Equals(trimmed, tag, StringComparison.Ordinal)" not in accept or "IsKnownObjectConfigCategoryTag(trimmed)" not in accept:
		errors.append("ConfigElementBase ID must reject an ID candidate equal to a derived category tag")

	route_start = routing.find("internal static bool TryResolvePrototypeExportFolder(UnitViewConfig cfg, out string configId, out string exportFolderName)")
	route_end = routing.find("internal static bool TryGetBattlePrefabRequest", route_start)
	route = routing[route_start:route_end] if route_start >= 0 and route_end > route_start else ""
	if not ("TryGetConfigElementId(cfg, out configId)" in route
			and route.find("TryGetConfigElementId(cfg, out configId)") < route.find("TryGetPrototypeExportFolder(configId")
			and route.find("TryGetConfigElementId(cfg, out configId)") < route.find("foreach (var route in Routes)")):
		errors.append("routing must fail with a diagnostic before ID/mesh route selection when ID reading fails")
	if "cfg.id" in routing or "viewConfig.id" in billboard:
		errors.append("custom map-view path must reuse one resolved ID instead of calling the stale id accessor")
	for marker in ("MapPrefabsByUnitSid.TryGetValue(configId", "MapPrefabsByUnitSid[configId]",
				   "BuildMapPrefab(configId, assets, viewConfig.modelHeight)"):
		if marker not in billboard:
			errors.append(f"map prefab path must reuse the resolved config ID for {marker}")
	if ("BuildMapPrefab(string configId, PrototypeAssetBundle assets, float modelHeight)" not in billboard
			or "var height = modelHeight > 0f" not in billboard):
		errors.append("map prefab sizing must consume the resolved UnitViewConfig modelHeight argument")

	project_target_start = project.find('<Target Name="ValidateConfigElementNativeIdContract"')
	project_target_end = project.find("</Target>", project_target_start)
	project_target = project[project_target_start:project_target_end] if project_target_start >= 0 and project_target_end > project_target_start else ""
	if ("'$(FullValidationNormalized)' == 'true'" not in project_target
			or "BeforeTargets=\"BeforeBuild\"" not in project_target
			or "validate_config_element_native_id_contract.py" not in project_target):
		errors.append("native ID contract must run in the full-validation build tier")

	fixtures = (
		{
			"name": "typed base ID is distinct from ObjectConfig tag",
			"owner": "ConfigElementBase", "generic_arg": "System.String",
			"alias": "field_Public_IDType_0", "native_type": "System.String",
			"native_value": "creature.temple_swordsman", "tag": "Artifact",
			"expected": "creature.temple_swordsman",
		},
		{
			"name": "wrong native field type rejected",
			"owner": "ConfigElementBase", "generic_arg": "System.String",
			"alias": "field_Public_IDType_0", "native_type": "System.Int32",
			"native_value": "not-a-string", "tag": "Artifact",
			"expected": None,
		},
		{
			"name": "wrong generic specialization fails closed",
			"owner": "ConfigElementBase", "generic_arg": "System.Int32",
			"alias": "field_Public_IDType_0", "native_type": "System.String",
			"native_value": "not-a-config-id", "tag": "Artifact",
			"expected": None,
		},
		{
			"name": "missing native alias fails closed",
			"owner": "ConfigElementBase", "generic_arg": "System.String",
			"alias": "missing", "native_type": "System.String",
			"native_value": None, "tag": "Artifact",
			"expected": None,
		},
		{
			"name": "native value equal to category tag rejected",
			"owner": "ConfigElementBase", "generic_arg": "System.String",
			"alias": "field_Public_IDType_0", "native_type": "System.String",
			"native_value": "Artifact", "tag": "Artifact",
			"expected": None,
		},
	)
	for fixture in fixtures:
		actual = policy_fixture(fixture)
		if actual != fixture["expected"]:
			errors.append(f"fixture failed: {fixture['name']}: expected {fixture['expected']!r}, got {actual!r}")

	current, peak = tracemalloc.get_traced_memory()
	tracemalloc.stop()
	elapsed_ms = (time.perf_counter() - started) * 1000.0
	for error in errors:
		print("ERROR " + error)
	print(
		"config element native ID contract: "
		+ ("OK" if not errors else f"{len(errors)} errors")
		+ f"; static-policy cases={len(fixtures)}; elapsed_ms={elapsed_ms:.1f}; python_heap_peak_kib={peak / 1024:.1f}; native runtime unproven"
	)
	return 1 if errors else 0


if __name__ == "__main__":
	sys.exit(main())
