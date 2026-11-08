"""Check native preview startup scope wiring and run its linked headless fixture."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MOD = Path("Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod")
HELPER = MOD / "NativePreviewStartupScope.cs"
SETTINGS_JSON = MOD / "ManagedModSettingsJson.cs"
HOOK = MOD / "Homm3NativePreviewStartupDeferral.cs"
CONFIG = MOD / "LauncherConfig.cs"
PLUGIN = MOD / "Plugin.cs"
TUNER = MOD / "DamageHistogramOverlay.cs"
SYMBOLS = MOD / "GameSymbols.cs"
CURRENT_SYMBOLS = MOD / "GameSymbolsCurrent.g.cs"
CSPROJ = MOD / "OfflineUnlockMod.csproj"
EVIDENCE = Path("tools/port_current/remap/current_scope_overrides_25672315.json")
FIXTURE_DIR = Path("tools/fixtures/native_preview_startup")
FIXTURE_PROJECT = FIXTURE_DIR / "NativePreviewStartupFixture.csproj"
SUCCESS = "NativePreviewStartupScope fixture: OK (12 cases)"


def require(errors: list[str], condition: bool, message: str) -> None:
	if not condition:
		errors.append(message)


def read(root: Path, path: Path, errors: list[str]) -> str:
	try:
		return (root / path).read_text(encoding="utf-8")
	except OSError as ex:
		errors.append(f"cannot read {path.as_posix()}: {ex}")
		return ""


def block(source: str, marker: str) -> str:
	"""Find one C# brace block while ignoring braces in comments and literals."""
	start = source.find(marker)
	if start < 0:
		return ""
	clean = re.sub(
		r'//[^\r\n]*|/\*[\s\S]*?\*/|@?"(?:""|\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
		lambda match: " " * len(match.group()), source, flags=re.S)
	opening = clean.find("{", start + len(marker))
	if opening < 0:
		return ""
	depth = 0
	for index in range(opening, len(clean)):
		if clean[index] == "{":
			depth += 1
		elif clean[index] == "}":
			depth -= 1
			if depth == 0:
				return source[opening:index + 1]
	return ""


def check_scope(root: Path, errors: list[str]) -> None:
	source = read(root, HELPER, errors)
	for marker in ("internal static class NativePreviewStartupScope", "internal sealed class Frame", "[ThreadStatic]",
			"internal static bool IsActive", "EnterWarmup(long ownerKey)", "EnterDemand(long ownerKey)",
			"TryDefer(long ownerKey)", "Exit(Frame frame)", "OwnerKey", "IsDemand", "Previous", "DeferredCount",
			"Thread.CurrentThread.ManagedThreadId", "ReferenceEquals(_current, frame)"):
		require(errors, marker in source, f"scope helper is missing {marker!r}")
	exit_body = block(source, "internal static void Exit(Frame frame)")
	require(errors, re.search(r"if\s*\(\s*frame\s*==\s*null\s*\)\s*return\s*;", exit_body) is not None,
		"scope Exit(null) must be a no-op")
	for token in ("Dictionary<", "List<", "Queue<", "Harmony", "UnityEngine", "Marshal.OffsetOf", "unsafe "):
		require(errors, token not in source, f"scope helper must remain a managed thread-local frame chain (found {token})")


def check_config(root: Path, errors: list[str]) -> None:
	config = read(root, CONFIG, errors)
	plugin = read(root, PLUGIN, errors)
	settings = read(root, SETTINGS_JSON, errors)
	setting = "Homm3NativePreviewStartupDeferral"
	require(errors, f"public bool {setting};" in config
		and f'{setting} = ReadBool(json, NativePreviewStartupDeferralSettingName, false)' in config,
		"pilot config field must default false")
	require(errors, 'NativePreviewStartupDeferralSettingName = "homm3NativePreviewStartupDeferral"' in config,
		"pilot config key must remain explicit")
	reader = block(config, "private static void TryReadHomm3NativePreviewStartupDeferral(")
	require(errors, "ManagedModSettingsJson.TryReadTopLevelBoolean(" in reader and "valid = ManagedModSettingsJson" in reader,
		"launcher must use the strict managed selector and retain its failure result")
	require(errors, "System.Text.Json" not in config and "using System.Text.Json;" in settings
		and "System.Runtime.Serialization.Json" not in settings and "JsonReaderWriterFactory" not in settings,
		"production settings helper must use the strongly typed System.Text.Json API")
	require(errors, "IndexOf" not in reader and "IndexOf" not in settings,
		"pilot selector must parse decoded JSON names rather than raw substring presence")
	selector = block(settings, "internal static bool TryReadTopLevelBoolean(")
	for token in ("TryParseObject(json", "RootElement.EnumerateObject()", "property.Name", "StringComparison.OrdinalIgnoreCase",
			"if (setting.HasValue)", "ContainsNestedProperty(property.Value", "JsonValueKind.True", "JsonValueKind.False", "GetBoolean()"):
		require(errors, token in selector, f"managed selector is missing strict rule {token!r}")
	nested = block(settings, "private static bool ContainsNestedProperty(JsonElement value, string propertyName)")
	require(errors, all(token in nested for token in ("ValueKind == JsonValueKind.Object", "EnumerateObject()",
			"ValueKind == JsonValueKind.Array", "EnumerateArray()", "StringComparison.OrdinalIgnoreCase")),
		"nested selector rejection must cover decoded names through object and array containers")
	parse = block(settings, "private static bool TryParseObject(")
	for token in ("JsonDocument.Parse(json, DocumentOptions)", "document.RootElement.ValueKind == JsonValueKind.Object",
			"Encoding.UTF8.GetByteCount(json) > MaxDocumentBytes", "MaxDocumentBytes"):
		require(errors, token in parse, f"managed JSON reader is missing {token!r}")
	require(errors, "MaxDepth = MaxDepth" in settings and "AllowTrailingCommas = true" in settings
		and "CommentHandling = JsonCommentHandling.Skip" in settings,
		"settings JSON options must match the accepted native config syntax")
	require(errors, "HasCompleteObjectFrame" not in settings and "XElement" not in settings and "JsonReaderWriterFactory" not in settings,
		"JSON structure must be validated by the shared typed parser, without XML or hand-written framing")
	merge = block(settings, "internal static bool TryMergeObjects(")
	for token in ("existingJson ?? \"{}\"", "TryParseObject(existingJson", "TryParseObject(updateJson",
			"mergedJson = null", "return false", "new Utf8JsonWriter(stream", "property.WriteTo(writer)", "writer.WriteStartObject()", "writer.WriteEndObject()"):
		require(errors, token in merge, f"object merge is missing fail-closed rule {token!r}")
	output_limit = merge.find("if (stream.Length > MaxDocumentBytes)")
	materialize_output = merge.find("mergedJson = Encoding.UTF8.GetString(stream.ToArray())")
	require(errors, "private const int MaxDocumentBytes = 1_048_576;" in settings
		and output_limit >= 0 and materialize_output > output_limit,
		"merged output must obey the existing 1 MiB settings cap before allocating its result string")
	require(errors, "Update JSON contains duplicate property" in merge and "new HashSet<string>(StringComparer.OrdinalIgnoreCase)" in merge,
		"object merge must reject duplicate update keys and preserve case-insensitive replacement semantics")
	getter = block(config, "internal static bool TryGetHomm3NativePreviewStartupDeferral(")
	require(errors, "return _nativePreviewStartupDeferralSettingValid;" in getter,
		"invalid strict config must prevent hook registration")
	load = block(config, "internal static LauncherConfig TryLoad()")
	for token in ("TryReadHomm3NativePreviewStartupDeferral(", "if (modSettingPresent || !modSettingValid)",
			"nativePreviewSettingEnabled = modSettingEnabled", "if (!nativePreviewSettingPresent && nativePreviewSettingValid)",
			"nativePreviewSettingValid && nativePreviewSettingEnabled",
			f"merged.{setting} = _nativePreviewStartupDeferralEnabled"):
		require(errors, token in load, f"config precedence/defaulting is missing {token!r}")
	plugin_load = block(plugin, "public override void Load()")
	require(errors, "var cfg = LauncherConfigReader.TryLoad();" in plugin_load
		and "else if (deferNativePreviewStartup)" in plugin_load
		and "Homm3NativePreviewStartupDeferral.TryRegister(_harmony, Log);" in plugin_load,
		"Plugin.Load must register only after a valid explicit opt-in")
	require(errors, "no hooks installed" in plugin_load and "TryGetHomm3NativePreviewStartupDeferral" in plugin_load,
		"invalid config must log and leave the native methods unpatched")
	tuner = read(root, TUNER, errors)
	save = block(tuner, "private static void SaveTunerConfig()")
	require(errors, "GetCanonicalModSettingsPath()" in save and "LastResolvedModSettingsPath" in save
		and "File.ReadAllText(activePath)" in save and "ManagedModSettingsJson.TryMergeObjects(existingJson, json"
		in save and "File.WriteAllText(path, mergedJson)" in save,
		"tuner writes must merge the active legacy/canonical settings into the canonical path before writing")
	require(errors, r'damageHistograms\":' not in save
		and r'damageHistogramPanelUgui\":' not in save
		and "existing?.DamageHistograms" not in save
		and "existing?.DamageHistogramPanelUgui" not in save,
		"tuner saves must not promote launcher enable/mode booleans into its numeric settings update")
	merge_call = save.find("ManagedModSettingsJson.TryMergeObjects(")
	merge_abort = save.find("throw new System.IO.InvalidDataException(", merge_call)
	write_call = save.find("File.WriteAllText(path, mergedJson)")
	require(errors, merge_call >= 0 and merge_abort > merge_call and write_call > merge_abort,
		"malformed settings merge must abort before the canonical file is written")


def check_hook(root: Path, errors: list[str]) -> None:
	hook = read(root, HOOK, errors)
	symbols = read(root, SYMBOLS, errors)
	unit = block(symbols, "internal static partial class UnitPreview\n")
	for marker in ("SharedPreviewWarmup", "SharedPreviewCreate", "SharedPreviewFactory",
			"unitPreview.shared.warmup", "Method_Private_Void_0", "htu", "unitPreview.shared.create",
			"Method_Private_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_UnitViewConfig_0", "htz",
			"unitPreview.shared.factory"):
		require(errors, marker in unit, f"GameSymbols.UnitPreview must own pin {marker!r}")

	register = block(hook, "internal static bool TryRegister(Harmony harmony, ManualLogSource log)")
	locked = block(hook, "private static bool TryRegisterLocked(Harmony harmony, ManualLogSource log)")
	require(errors, "RegistrationLock" in hook and "RegistrationInactive" in hook
		and "RegistrationInProgress" in hook and "RegistrationActive" in hook and "IsRegistered" in hook
		and "if (IsRegistered)" in register and "lock (RegistrationLock)" in register,
		"registration must be serialized and idempotent")
	for token in ("GameBuild.Kind != GameBuildKind.Current", "TryResolveTargets(out var warmup, out var create, out var factory, out var error)",
			"GetPatchMethod(nameof(WarmupPrefix))", "GetPatchMethod(nameof(WarmupFinalizer))",
			"GetPatchMethod(nameof(SharedPreviewCreatePrefix))", "GetPatchMethod(nameof(SharedPreviewFactoryPrefix))",
			"GetPatchMethod(nameof(SharedPreviewFactoryFinalizer))", "harmony.Patch(", "catch (Exception ex)",
			"TryUnpatchExact(harmony, registration.Target", "No alternate hook path was attempted"):
		require(errors, token in locked, f"hook registration must include {token!r}")
	registrations = (
		"new PatchRegistration { Target = warmup, Prefix = warmupPrefix, Finalizer = warmupFinalizer }",
		"new PatchRegistration { Target = create, Prefix = createPrefix }",
		"new PatchRegistration { Target = factory, Prefix = factoryPrefix, Finalizer = factoryFinalizer }")
	require(errors, all(item in locked for item in registrations) and locked.count("new PatchRegistration { Target = ") == 3,
		"registration must patch exactly the three central native methods with their intended prefix/finalizer pairs")
	patch_loop = locked.find("foreach (var registration in registrations)")
	catch_start = locked.find("catch (Exception ex)")
	active = locked.find("Volatile.Write(ref _registrationState, RegistrationActive)")
	require(errors, patch_loop >= 0 and active > patch_loop and active > catch_start,
		"active registration must be published only after all patches succeed")
	require(errors, "Volatile.Write(ref _registrationState, RegistrationInactive)" in locked
		and re.search(r"if\s*\(rollbackFailures\s*!=\s*0\)\s*throw\s+new\s+InvalidOperationException", locked) is not None,
		"failed or incomplete exact rollback must not expose an active/partial hook")
	require(errors, "UnpatchAll" not in locked, "registration rollback must not unpatch unrelated Harmony owners")
	unpatch = block(hook, "private static int TryUnpatchExact(")
	require(errors, "harmony.Unpatch(target, patch);" in unpatch and "UnpatchAll" not in unpatch,
		"registration rollback must remove only this feature's exact patches")

	resolve = block(hook, "private static bool TryResolveTargets(")
	for token in ("GameSymbols.UnitPreview.SharedPreviewWarmup", "GameSymbols.UnitPreview.SharedPreviewCreate",
			"GameSymbols.UnitPreview.SharedPreviewFactory", 'GetType("Hex.BhUnitPreviews", throwOnError: false)',
			"warmups.Length != 1", "create == null", "factory == null", "typeof(UnitViewConfig)"):
		require(errors, token in resolve, f"target resolver must include {token!r}")
	require(errors, re.search(r"typeof\s*\(\s*(?:UnityEngine\.)?MonoBehaviour\s*\)\.IsAssignableFrom\(candidate\.ReturnType\)", resolve) is not None,
		"SharedPreviewCreate result must be UnityEngine.MonoBehaviour-derived")

	warmup = block(hook, "private static void WarmupPrefix(")
	require(errors, "NativePreviewStartupScope.EnterWarmup(ownerKey)" in warmup
		and "return false" not in warmup and "__runOriginal" not in warmup
		and 'LogMissingOwnerOnce("SharedPreviewWarmup")' in warmup,
		"warmup prefix must scope by native owner and preserve the original method")
	require(errors, "return ExitScope(__exception, __state, logWarmup: true);" in block(hook, "private static Exception WarmupFinalizer("),
		"warmup finalizer must restore its scope and retain the original exception")

	create = block(hook, "private static bool SharedPreviewCreatePrefix(")
	require(errors, re.search(r"if\s*\(!NativePreviewStartupScope\.TryDefer\(ownerKey\)\)\s*return\s+true\s*;\s*__result\s*=\s*null\s*;\s*return\s+false\s*;", create, re.S) is not None
		and "!IsRegistered || !NativePreviewStartupScope.IsActive" in create
		and 'LogMissingOwnerOnce("SharedPreviewCreate")' in create,
		"create prefix may return the null sentinel only for a matched active owner scope")
	factory = block(hook, "private static void SharedPreviewFactoryPrefix(")
	require(errors, "NativePreviewStartupScope.EnterDemand(ownerKey)" in factory
		and "__state = new ScopeState { Frame = frame };" in factory
		and "!IsRegistered || !NativePreviewStartupScope.IsActive" in factory,
		"factory demand scope must be owner-matched and active through the original/postfix")
	require(errors, "return ExitScope(__exception, __state, logWarmup: false);" in block(hook, "private static Exception SharedPreviewFactoryFinalizer("),
		"factory finalizer must restore demand scope and retain the original exception")
	exit_scope = block(hook, "private static Exception ExitScope(")
	require(errors, "NativePreviewStartupScope.Exit(state.Frame);" in exit_scope
		and "return originalException;" in exit_scope,
		"finalizer cleanup must exit state and return the original exception")
	owner = block(hook, "private static bool TryGetOwnerKey(")
	require(errors, "owner.Pointer == IntPtr.Zero" in owner and "owner.Pointer.ToInt64()" in owner and "ownerKey != 0" in owner,
		"scope owner identity must use a nonzero native pointer")
	require(errors, "Interlocked.Exchange" in block(hook, "private static void LogMissingOwnerOnce(")
		and "LogError" in block(hook, "private static void LogMissingOwnerOnce("),
		"missing-owner diagnostics must be explicit and rate-limited")
	for token in ("Dictionary<", "List<", "Queue<", "Marshal.OffsetOf", "IntPtr.Add(", "NativeMemory.",
			"unsafe ", "Resources.Load(", "AssetBundle.LoadAsset(", "Instantiate(", "UnpatchAll",
			'"Method_Private_Void_0"', '"htu"', '"Method_Private_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_UnitViewConfig_0', '"htz"'):
		require(errors, token not in hook, f"feature must not add local native state/fallback or raw pin {token}")
	for token in ("Runtime behavior, native detour coverage, and first-demand resource behavior remain unproven.",
			"this invocation does not prove the pilot changed startup work", "Source registration is not runtime proof."):
		require(errors, token in hook, f"feature must preserve the proof boundary: {token}")


def check_hash_evidence(root: Path, errors: list[str]) -> None:
	current = read(root, CURRENT_SYMBOLS, errors)
	hash_match = re.search(r'\bGameAssemblySha256\s*=\s*"([0-9A-Fa-f]{64})"', current)
	require(errors, hash_match is not None, "canonical GameAssembly SHA256 must be a full 64-hex source constant")
	if hash_match is None:
		return
	try:
		symbols = json.loads((root / EVIDENCE).read_text(encoding="utf-8")).get("symbols", {})
	except (OSError, json.JSONDecodeError) as ex:
		errors.append(f"cannot parse central override evidence: {ex}")
		return
	for key in ("UnitPreview.SharedPreviewWarmup", "UnitPreview.SharedPreviewCreate"):
		row = symbols.get(key, {}) if isinstance(symbols, dict) else {}
		evidence = row.get("evidence", "") if isinstance(row, dict) else ""
		cited = re.findall(r"GameAssembly SHA256\s+([0-9A-Fa-f]{64})", evidence)
		require(errors, len(cited) == 1 and cited[0].upper() == hash_match.group(1).upper(),
			f"{key} evidence must cite the full canonical GameAssembly SHA256")


def check_build_gate(root: Path, errors: list[str]) -> None:
	try:
		project = ET.parse(root / CSPROJ).getroot()
	except (OSError, ET.ParseError) as ex:
		errors.append(f"cannot parse {CSPROJ.as_posix()}: {ex}")
		return
	targets = [item for item in project.findall(".//Target") if item.get("Name") == "ValidateNativePreviewStartupContract"]
	require(errors, len(targets) == 1, "focused validator must be wired exactly once")
	if len(targets) != 1:
		return
	target = targets[0]
	require(errors, target.get("BeforeTargets") == "BeforeBuild" and "FullValidationNormalized" in (target.get("Condition") or "")
		and target.get("DependsOnTargets") == "ValidateManagedModSettingsJsonRuntime",
		"validator must run only in the full-validation build tier")
	execs = target.findall(".//Exec")
	require(errors, len(execS := execs) == 1 and "$(NativePreviewStartupContractValidator)" in execS[0].get("Command", "")
		and "--repo-root" in execS[0].get("Command", "") and execS[0].get("Timeout") == "60000",
		"build target must invoke the focused gate with an explicit 60-second timeout")
	require(errors, len(target.findall(".//Error")) == 1 and "Missing native preview startup contract validator"
		in target.find(".//Error").get("Text", ""), "build target must fail clearly if its validator is missing")
	packages = [item for item in project.findall(".//PackageReference") if item.get("Include") == "System.Text.Json"]
	require(errors, len(packages) == 1 and packages[0].get("Version") == "6.0.11"
		and packages[0].get("PrivateAssets") == "all" and packages[0].get("ExcludeAssets") == "runtime",
		"plugin must compile against pinned System.Text.Json 6.0.11 API metadata without shipping the package runtime")
	runtime_targets = [item for item in project.findall(".//Target") if item.get("Name") == "ValidateManagedModSettingsJsonRuntime"]
	require(errors, len(runtime_targets) == 1, "shared game System.Text.Json check must be wired once")
	if runtime_targets:
		runtime = runtime_targets[0]
		runtime_xml = ET.tostring(runtime, encoding="unicode")
		require(errors, "BeforeBuild" in (runtime.get("BeforeTargets") or "")
			and "DeployPluginToGame" in (runtime.get("BeforeTargets") or "")
			and "FullValidationNormalized" in (runtime.get("Condition") or "")
			and "DeployPluginToGame" in (runtime.get("Condition") or ""),
			"shared parser check must run for full validation and plugin deployment")
		require(errors, "$(GameRootDir)dotnet\\System.Text.Json.dll" in runtime_xml
			and runtime.find(".//GetAssemblyIdentity") is not None
			and "System.Version" in runtime_xml and "&lt; 6" in runtime_xml,
			"shared parser check must inspect installed assembly identity and require major version 6 or newer")
	deploy_targets = [item for item in project.findall(".//Target") if item.get("Name") == "DeployPluginToGame"]
	deploy_files = [item.get("Include", "") for target_item in deploy_targets for item in target_item.findall(".//DeployFile")]
	require(errors, len(deploy_targets) == 1 and not any("System.Text.Json.dll" in item for item in deploy_files),
		"deployment must not copy a private System.Text.Json parser assembly")


def check_fixture(root: Path, errors: list[str]) -> Path:
	directory = root / FIXTURE_DIR
	project = root / FIXTURE_PROJECT
	program = directory / "Program.cs"
	props = directory / "Directory.Build.props"
	for path in (project, program, props):
		require(errors, path.is_file(), f"missing fixture file {path.relative_to(root).as_posix()}")
	if project.is_file():
		try:
			xml = ET.parse(project).getroot()
		except ET.ParseError as ex:
			errors.append(f"invalid fixture project XML: {ex}")
			xml = None
		if xml is not None:
			includes = [item.get("Include", "") for item in xml.findall(".//Compile")]
			for path in (HELPER, SETTINGS_JSON):
				links = [item for item in includes if item.replace("/", "\\").endswith(path.name)]
				require(errors, len(links) == 1 and (directory / links[0]).resolve() == (root / path).resolve(),
					f"fixture must compile the actual {path.name} source once")
			require(errors, xml.find(".//PackageReference") is None and xml.findtext(".//TargetFramework") == "net9.0",
				"headless fixture must use the installed .NET 9 framework without adding another package dependency")
	if props.is_file():
		try:
			xml = ET.parse(props).getroot()
		except ET.ParseError as ex:
			errors.append(f"invalid fixture output props XML: {ex}")
			xml = None
		if xml is not None:
			for name, folder in (("BaseOutputPath", "bin"), ("BaseIntermediateOutputPath", "obj"), ("RestorePackagesPath", "packages")):
				require(errors, f"artifacts\\port_current\\native_preview_fixture\\{folder}" in (xml.findtext(f".//{name}") or ""),
					f"fixture {name} must remain under the repo artifact directory")
	if program.is_file():
		source = program.read_text(encoding="utf-8")
		for marker in ("outside scope is untouched", "matching demand protects reentry", "foreign demand does not enter",
				"nested owners restore correctly", "same-owner nesting targets nearest warmup", "normal and exception cleanup",
				"thread isolation and wrong-thread exit", "invalid keys and out-of-order exit", "NativePreviewStartupScope.Exit(null)",
				"settings parser decodes names and enforces boolean types", "settings parser rejects ambiguous and malformed JSON",
				"settings merge preserves unrelated values", "settings merge fails closed", "JsonDocument.Parse(merged)"):
			require(errors, marker in source, f"scope fixture is missing case {marker!r}")
		require(errors, "TryReadHomm3NativePreviewStartupDeferral" not in source,
			"fixture must not duplicate the launcher-config parser")
	return project


def run_fixture(project: Path, root: Path, errors: list[str]) -> tuple[float, int | None, int | None, str | None]:
	dotnet = shutil.which("dotnet")
	if dotnet is None:
		errors.append("linked helper fixture requires the .NET 9 SDK")
		return 0.0, None, None, None
	try:
		import psutil  # type: ignore[import-not-found]
	except ImportError:
		psutil = None
	command = [dotnet, "run", "--project", str(project), "--configuration", "Release", "--no-launch-profile", "--verbosity", "quiet"]
	started = time.perf_counter()
	try:
		process = subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
	except OSError as ex:
		errors.append(f"could not start fixture: {ex}")
		return time.perf_counter() - started, None, None, None
	peak = {"rss": 0, "private": 0, "field": None}
	stop = threading.Event()
	def sample() -> None:
		if psutil is None:
			return
		while not stop.is_set():
			try:
				parent = psutil.Process(process.pid)
				infos = [item.memory_info() for item in [parent, *parent.children(recursive=True)]]
				peak["rss"] = max(peak["rss"], sum(item.rss for item in infos))
				field = next((name for name in ("private", "uss", "pagefile") if all(hasattr(item, name) for item in infos)), None)
				if field:
					peak["private"] = max(peak["private"], sum(getattr(item, field) for item in infos))
					peak["field"] = field
			except Exception:
				pass
			stop.wait(0.05)

	thread = threading.Thread(target=sample, name="native-preview-fixture-memory", daemon=True)
	thread.start()
	try:
		stdout, stderr = process.communicate(timeout=55)
	except subprocess.TimeoutExpired:
		if psutil is not None:
			try:
				for child in psutil.Process(process.pid).children(recursive=True):
					child.kill()
			except psutil.Error:
				pass
		process.kill()
		stdout, stderr = process.communicate()
		errors.append("linked helper fixture exceeded its 55-second timeout")
	finally:
		stop.set()
		thread.join(timeout=2)
	elapsed = time.perf_counter() - started
	if process.returncode != 0:
		errors.append("linked helper fixture failed: " + (stderr or stdout).strip()[-3000:])
	elif SUCCESS not in stdout:
		errors.append("linked helper fixture exited without its success marker")
	return elapsed, peak["rss"] or None, peak["private"] or None, peak["field"]


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", type=Path, default=ROOT)
	root = parser.parse_args().repo_root.resolve()
	started = time.perf_counter()
	errors: list[str] = []
	check_scope(root, errors)
	check_config(root, errors)
	check_hook(root, errors)
	check_hash_evidence(root, errors)
	check_build_gate(root, errors)
	project = check_fixture(root, errors)
	seconds = 0.0
	rss = private = None
	field = None
	if not errors:
		seconds, rss, private, field = run_fixture(project, root, errors)
	for error in errors:
		print("ERROR " + error)
	resources = f"peak-process-tree-rss={rss / 1048576:.1f} MiB" if rss else "peak-process-tree-memory=unavailable"
	if private:
		resources += f", peak-private-estimate({field})={private / 1048576:.1f} MiB"
	print(f"native preview startup contract: {'OK' if not errors else f'{len(errors)} errors'}; elapsed={time.perf_counter() - started:.2f}s; fixture={seconds:.2f}s; {resources}")
	return 1 if errors else 0


if __name__ == "__main__":
	sys.exit(main())
