using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.MainMenu;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes;
using Il2CppInterop.Runtime.Runtime;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

internal static class Homm3LiveProbeWorkbench
{
	internal const string FlagFileName = "homm3_live_probe_workbench.flag";
	internal const string RecipeFileName = "homm3_live_probe_recipes.json";
	internal const string ExactGetterAllowlistFileName = "volatile_exact_getter_allowlist.json";
	internal const string VolatileOperationAllowlistFileName = "volatile_operation_allowlist.json";
	internal const string BridgeDirectoryName = "live_probe_bridge";
	private const string ProbeAssemblyDirectoryName = "probes";
	private const string GrepKey = "HOMM3_LIVE_PROBE";
	private const int MaxTextBytes = 1024 * 1024;
	private const int MaxProbeResultChars = 256 * 1024;

	private static readonly HashSet<string> KnownTriggers = new(StringComparer.OrdinalIgnoreCase)
	{
		"manual",
		"configReload",
		"sceneLoaded",
		"mapPrepare",
		"mapBuildPostfix",
		"townSessionBind",
		"townBuildingViewBind",
		"townNavigationBind",
		"heroHudBind",
		"selectedUnitHudBind",
		"dwellingInit",
		"hireInit",
		"mapSquadVisualInit",
		"terrainPrepare",
		"terrainBuild"
	};

	private static readonly HashSet<string> KnownActions = new(StringComparer.OrdinalIgnoreCase)
	{
		"snapshotFields",
		"diffFields",
		"searchTypes",
		"searchLiveUnityObjects",
		"dumpMethodSignatures",
		"dumpUnityHierarchy",
		"invokeKnownSafeMethod",
		"setPrimitiveField",
		"volatileSetCanvasProperty",
		"volatileSetUiSibling"
	};

	private static bool _configured;
	private static bool _bridgeRegistered;
	private static bool _bridgeAttached;
	private static bool _bridgeAttachPatched;
	private static ManualLogSource _log;
	private static string _recipePath;
	private static RecipeManifestSummary _recipes;
	private static string _exactGetterAllowlistPath;
	private static DateTime _exactGetterAllowlistMtimeUtc;
	private static List<ExactGetterAllowlistEntry> _exactGetterAllowlist = new();
	private static string _volatileOperationAllowlistPath;
	private static DateTime _volatileOperationAllowlistMtimeUtc;
	private static List<VolatileOperationAllowlistEntry> _volatileOperationAllowlist = new();

	internal static string BridgeDirectory { get; private set; }
	internal static string BridgeToken { get; private set; }

	internal static void Configure(ManualLogSource log, LauncherConfig cfg, Harmony harmony)
	{
		if (_configured)
			return;

		var enabled = cfg != null && cfg.Homm3LiveProbeWorkbench;
		enabled = enabled || Homm3DiagnosticFlags.IsEnabled(FlagFileName);
		if (!enabled)
			return;

		_configured = true;
		_log = log;
		_exactGetterAllowlistPath = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", BridgeDirectoryName, ExactGetterAllowlistFileName);
		_volatileOperationAllowlistPath = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", BridgeDirectoryName, VolatileOperationAllowlistFileName);

#if !OFFICIAL_DEOBF_BUILD
		log?.LogWarning(GrepKey + " disabled: initial live workbench target is Golden Era; rebuild with -p:OfficialDeobfBuild=true.");
		return;
#else
		if (harmony == null)
		{
			log?.LogWarning(GrepKey + " disabled: Harmony instance was not available during plugin load.");
			return;
		}

		_recipePath = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", RecipeFileName);
		_recipes = LoadRecipeManifest(log, _recipePath);
		log?.LogWarning(
			GrepKey
			+ " ready: recipe validation loaded "
			+ _recipes.EnabledCount
			+ " enabled recipe(s), "
			+ _recipes.DisabledCount
			+ " disabled recipe(s), "
			+ _recipes.ErrorCount
			+ " error(s). File bridge is enabled for MCP adapter commands, including explicit volatile hot-loaded probe assemblies.");
		EnsureFileBridge(log, harmony);
#endif
	}

	private static void EnsureFileBridge(ManualLogSource log, Harmony harmony)
	{
		if (_bridgeAttached)
			return;
		try
		{
			BridgeDirectory = Path.Combine(Paths.BepInExRootPath, "plugins", "OfflineUnlockMod", BridgeDirectoryName);
			Directory.CreateDirectory(BridgeDirectory);
			Directory.CreateDirectory(Path.Combine(BridgeDirectory, "inbox"));
			Directory.CreateDirectory(Path.Combine(BridgeDirectory, "outbox"));
			Directory.CreateDirectory(Path.Combine(BridgeDirectory, "processed"));
			Directory.CreateDirectory(Path.Combine(BridgeDirectory, ProbeAssemblyDirectoryName));
			BridgeToken = Guid.NewGuid().ToString("N");
			WriteAllTextAtomic(Path.Combine(BridgeDirectory, "token.txt"), BridgeToken);
			WriteStatus("starting");

			if (!_bridgeAttachPatched)
			{
				var start = AccessTools.Method(typeof(ScMainMenu), nameof(ScMainMenu.Start));
				var postfix = AccessTools.Method(typeof(Homm3LiveProbeWorkbench), nameof(AfterMainMenuStartAttachBridge));
				var bridgeReason = "";
				if (start != null && postfix != null && GameMember.IsHarmonyPatchCompatible(start, postfix, out bridgeReason))
				{
					harmony.Patch(start, postfix: new HarmonyMethod(postfix));
					_bridgeAttachPatched = true;
					log?.LogWarning(GrepKey + " Unity host attach deferred to ScMainMenu.Start.");
				}
				else
				{
					log?.LogWarning(GrepKey + " Unity host attach not patched: " + (bridgeReason ?? "surface missing") + ".");
				}
			}
			log?.LogWarning(GrepKey + " file bridge prepared at " + BridgeDirectory + ".");
		}
		catch (Exception ex)
		{
			log?.LogWarning(GrepKey + " file bridge setup failed: " + ex);
		}
	}

	private static void AfterMainMenuStartAttachBridge()
	{
		AttachBridgeHost();
	}

	private static void AttachBridgeHost()
	{
		if (_bridgeAttached)
			return;
		try
		{
			if (!_bridgeRegistered)
			{
				ClassInjector.RegisterTypeInIl2Cpp<Homm3LiveProbeWorkbenchBridgeBehaviour>();
				_bridgeRegistered = true;
			}

			var go = new GameObject("Homm3LiveProbeWorkbenchBridge");
			go.hideFlags = HideFlags.HideAndDontSave;
			go.AddComponent<Homm3LiveProbeWorkbenchBridgeBehaviour>();
			UnityObject.DontDestroyOnLoad(go);
			_bridgeAttached = true;
			_log?.LogWarning(GrepKey + " Unity file-bridge host attached after scene load at " + BridgeDirectory + ".");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(GrepKey + " Unity file-bridge host attach failed: " + ex);
		}
	}

	internal static void WriteStatus(string state)
	{
		if (string.IsNullOrWhiteSpace(BridgeDirectory))
			return;
		try
		{
			var json = "{"
				+ "\"ok\":true,"
				+ "\"state\":\"" + EscapeJson(state ?? "unknown") + "\","
				+ "\"build\":\"" + EscapeJson(Plugin.PluginVersion) + "\","
				+ "\"profile\":\"OfficialDeobf\","
				+ "\"frame\":" + Time.frameCount.ToString(System.Globalization.CultureInfo.InvariantCulture) + ","
				+ "\"scene\":\"" + EscapeJson(SceneManager.GetActiveScene().name ?? "") + "\","
				+ "\"recipes\":{\"enabled\":" + _recipes.EnabledCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ ",\"disabled\":" + _recipes.DisabledCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ ",\"errors\":" + _recipes.ErrorCount.ToString(System.Globalization.CultureInfo.InvariantCulture) + "},"
				+ "\"commands\":[\"status\",\"reload_recipes\",\"list_recipes\",\"list_triggers\",\"mutation_capabilities\",\"custom_law_candidate_surface_status\",\"source_prepared_law_profiles\",\"native_law_state\",\"native_law_level_up\",\"battle_unit_status_probe\",\"battle_unit_apply_status_probe\",\"direct_state_m3_bfdi_shove\",\"direct_state_m6_bfdi_teleport\",\"direct_state_ingress_evidence\",\"query_types\",\"method_signatures\",\"field_signatures\",\"construct_instance_snapshot\",\"resolve_decomp_method\",\"unity_renderers\",\"unity_ui_surfaces\",\"unity_objects_exact\",\"unity_object_components\",\"unity_components_by_type\",\"component_member_path\",\"town_ui_state\",\"set_unity_ui_property\",\"set_nearest_canvas_property\",\"set_canvas_by_name\",\"diagnostic_set_ui_property_by_path\",\"volatile_set_canvas_property\",\"volatile_set_ui_sibling\",\"volatile_invoke_exact_noarg_getter\",\"volatile_invoke_exact_getter_chain\",\"volatile_invoke_allowlisted_method\",\"volatile_set_allowlisted_member\",\"volatile_refresh_town_layers_from_cached_wrapper\",\"volatile_load_probe_assembly\",\"set_primitive_component_field\",\"invoke_allowlisted_method\",\"dispatch_ui_click\",\"create_ui_diagnostic_overlay\",\"remove_ui_diagnostic_overlays\",\"enable_precompiled_patch\",\"volatile_reflection_invoke\",\"volatile_generated_getter_sweep\",\"volatile_write_object_reference\",\"volatile_autopatch_same_shape_methods\",\"volatile_global_ui_setter_patch\"],"
				+ "\"note\":\"bridge includes read-only inspection, construct_instance_snapshot for bar-C EventArgs factories, UI-scoped guarded live-writing commands, volatile UI mutation commands, live-reloadable exact volatile operation allowlists, and explicit volatile hot-loaded probe assemblies\""
				+ "}";
			WriteAllTextAtomic(Path.Combine(BridgeDirectory, "status.json"), json);
		}
		catch (Exception ex)
		{
			_log?.LogWarning(GrepKey + " status write failed: " + ex.Message);
		}
	}

	internal static string HandleBridgeRequest(string requestJson)
	{
		var id = ReadString(requestJson, "id") ?? Guid.NewGuid().ToString("N");
		var token = ReadString(requestJson, "token");
		var command = ReadString(requestJson, "command");
		try
		{
			if (!string.Equals(token, BridgeToken, StringComparison.Ordinal))
				return ErrorResponse(id, "unauthorized", "Bridge token mismatch.");
			if (string.IsNullOrWhiteSpace(command))
				return ErrorResponse(id, "bad_request", "Missing command.");

			switch (command)
			{
				case "status":
					WriteStatus("ready");
					return OkResponse(id, "\"status\":" + ReadStatusJson());
				case "reload_recipes":
					_recipes = LoadRecipeManifest(_log, _recipePath);
					WriteStatus("ready");
					return OkResponse(id, "\"recipes\":" + RecipeSummaryJson());
				case "list_recipes":
					return OkResponse(id, "\"recipes\":" + RecipeSummaryJson() + ",\"recipePath\":\"" + EscapeJson(_recipePath ?? "") + "\"");
				case "list_triggers":
					return OkResponse(id, "\"triggers\":" + StringArrayJson(KnownTriggers) + ",\"actions\":" + StringArrayJson(KnownActions));
				case "mutation_capabilities":
					return MutationCapabilities(id);
				case "custom_law_candidate_surface_status":
					return CustomLawCandidateSurfaceStatus(id);
				case "source_prepared_law_profiles":
					return SourcePreparedLawProfiles(id, requestJson);
				case "native_law_state":
					return NativeLawState(id, requestJson);
				case "native_law_level_up":
					return NativeLawLevelUp(id, requestJson);
				case "battle_unit_status_probe":
					return BattleUnitStatusProbe(id, requestJson);
                case "battle_unit_apply_status_probe":
                    return BattleUnitApplyStatusProbe(id, requestJson);
				case "direct_state_m3_bfdi_shove":
					return DirectStateM3BfdiShove(id, requestJson);
				case "direct_state_m6_bfdi_teleport":
					return DirectStateM6BfdiTeleport(id, requestJson);
				case "direct_state_ingress_evidence":
					return DirectStateIngressEvidence(id);
				case "query_types":
					return QueryTypes(id, ReadString(requestJson, "query"), ReadInt(requestJson, "limit", 40));
				case "method_signatures":
					return MethodSignatures(id, ReadString(requestJson, "typeName"), ReadInt(requestJson, "limit", 80));
				case "field_signatures":
					return FieldSignatures(id, ReadString(requestJson, "typeName"), ReadInt(requestJson, "limit", 120));
				case "construct_instance_snapshot":
					return ConstructInstanceSnapshot(id, requestJson);
				case "resolve_decomp_method":
					return ResolveDecompMethod(id, requestJson);
				case "unity_renderers":
					return UnityRenderers(id, ReadString(requestJson, "nameContains"), ReadInt(requestJson, "limit", 40));
				case "unity_ui_surfaces":
					return UnityUiSurfaces(id, ReadString(requestJson, "nameContains"), ReadInt(requestJson, "limit", 40));
				case "unity_objects_exact":
					return UnityObjectsExact(id, requestJson);
				case "unity_object_components":
					return UnityObjectComponents(id, requestJson);
				case "unity_components_by_type":
					return UnityComponentsByType(id, requestJson);
				case "component_member_path":
					return ComponentMemberPath(id, requestJson);
				case "town_ui_state":
					return TownUiState(id);
				case "set_unity_ui_property":
					return SetUnityUiProperty(id, requestJson);
				case "set_nearest_canvas_property":
					return SetNearestCanvasProperty(id, requestJson);
				case "set_canvas_by_name":
					return SetCanvasByName(id, requestJson);
				case "diagnostic_set_ui_property_by_path":
					return DiagnosticSetUiPropertyByPath(id, requestJson);
				case "volatile_set_canvas_property":
					return VolatileSetCanvasProperty(id, requestJson);
				case "volatile_set_ui_sibling":
					return VolatileSetUiSibling(id, requestJson);
				case "volatile_invoke_exact_noarg_getter":
					return VolatileInvokeExactNoArgGetter(id, requestJson);
				case "volatile_invoke_exact_getter_chain":
					return VolatileInvokeExactGetterChain(id, requestJson);
				case "volatile_invoke_allowlisted_method":
					return VolatileInvokeAllowlistedMethod(id, requestJson);
				case "volatile_set_allowlisted_member":
					return VolatileSetAllowlistedMember(id, requestJson);
				case "volatile_refresh_town_layers_from_cached_wrapper":
					return VolatileRefreshTownLayersFromCachedWrapper(id, requestJson);
				case "volatile_load_probe_assembly":
					return VolatileLoadProbeAssembly(id, requestJson);
				case "set_primitive_component_field":
					return SetPrimitiveComponentField(id, requestJson);
				case "invoke_allowlisted_method":
					return InvokeAllowlistedMethod(id, requestJson);
				case "dispatch_ui_click":
					return DispatchUiClick(id, requestJson);
				case "create_ui_diagnostic_overlay":
					return CreateUiDiagnosticOverlay(id, requestJson);
				case "remove_ui_diagnostic_overlays":
					return RemoveUiDiagnosticOverlays(id, requestJson);
				case "enable_precompiled_patch":
					return EnablePrecompiledPatch(id, requestJson);
				case "volatile_reflection_invoke":
				case "volatile_generated_getter_sweep":
				case "volatile_write_object_reference":
				case "volatile_autopatch_same_shape_methods":
				case "volatile_global_ui_setter_patch":
					return VolatileUnavailable(id, command);
				default:
					return ErrorResponse(id, "unknown_command", "Unsupported command '" + command + "'.");
			}
		}
		catch (Exception ex)
		{
			return ErrorResponse(id, "exception", ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static string QueryTypes(string id, string query, int limit)
	{
		if (string.IsNullOrWhiteSpace(query))
			return ErrorResponse(id, "bad_request", "query_types requires query.");
		limit = Math.Max(1, Math.Min(limit, 200));
		var count = 0;
		var values = new List<string>();
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try
			{
				types = assembly.GetTypes();
			}
			catch (ReflectionTypeLoadException ex)
			{
				types = ex.Types;
			}
			catch
			{
				continue;
			}
			if (types == null)
				continue;
			for (var i = 0; i < types.Length; i++)
			{
				var type = types[i];
				if (type == null)
					continue;
				var name = type.FullName ?? type.Name ?? "";
				if (name.IndexOf(query, StringComparison.OrdinalIgnoreCase) < 0)
					continue;
				values.Add("{\"fullName\":\"" + EscapeJson(name) + "\",\"assembly\":\"" + EscapeJson(assembly.GetName().Name ?? "") + "\"}");
				count++;
				if (count >= limit)
					return OkResponse(id, "\"types\":[" + string.Join(",", values) + "],\"truncated\":true");
			}
		}
		return OkResponse(id, "\"types\":[" + string.Join(",", values) + "],\"truncated\":false");
	}

	private static string NativeLawState(string id, string requestJson)
	{
		var lawSid = ReadString(requestJson, "lawSid");
		var rank = ReadInt(requestJson, "rank", 1);
		var applyIfCan = ReadBool(requestJson, "applyIfCan", false);
		if (!Homm3CustomFactionLawRuntime.TryDescribeNativeLawStateForBridge(lawSid, rank, applyIfCan, out var body, out var failure))
			return ErrorResponse(id, "native_law_state_failed", failure ?? "native law state failed closed");
		return OkResponse(id, "\"command\":\"native_law_state\"," + body);
	}

	private static string NativeLawLevelUp(string id, string requestJson)
	{
		var factionSid = ReadString(requestJson, "factionSid");
		var count = ReadInt(requestJson, "count", 1);
		if (!Homm3CustomFactionLawRuntime.TryNativeLawLevelUpForBridge(factionSid, count, out var body, out var failure))
			return ErrorResponse(id, "native_law_level_up_failed", failure ?? "native law level-up failed closed");
		return OkResponse(id, "\"command\":\"native_law_level_up\"," + body);
	}

	private static string DirectStateIngressEvidence(string id)
	{
		// Read-only: never mutates combat. Writes a diagnostic evidence envelope and returns JSON.
		if (!Homm3DirectStateIngressMining.TryWriteEvidenceEnvelope(out var path, out var writeFailure)
		    && !string.IsNullOrWhiteSpace(writeFailure))
		{
			return ErrorResponse(
				id,
				"direct_state_ingress_evidence_failed",
				writeFailure);
		}
		var envelope = Homm3DirectStateIngressMining.BuildEvidenceEnvelopeJson();
		return OkResponse(
			id,
			"\"command\":\"direct_state_ingress_evidence\","
			+ "\"envelopePath\":\"" + EscapeJson(path ?? Homm3DirectStateIngressMining.LastEnvelopePath) + "\","
			+ "\"envelope\":" + envelope);
	}

	private static string BattleUnitStatusProbe(string id, string requestJson)
	{
		var limit = ReadInt(requestJson, "limit", 32);
		if (!Homm3StatusTaxonomyRegistry.TryGetSidsForAnyTag(new[] { "negative" }, out var negativeStatusSids))
			return ErrorResponse(id, "battle_unit_status_probe_failed", "status taxonomy has no exact negative-status SID set");

		var units = Homm3BattleUnitLawOwnerRegistry.SnapshotUnits(limit);
		var values = new List<string>(units.Count);
		for (var i = 0; i < units.Count; i++)
		{
			var unit = units[i];
			var statusKnown = Homm3BuffDebuffNativeAdapter.TryQueryAnyBuffSidFromReceiver(
				unit.Unit,
				negativeStatusSids,
				out var statusInfo,
				out var statusFailure);
			values.Add("{"
			           + "\"unitKey\":" + unit.UnitKey.ToString(System.Globalization.CultureInfo.InvariantCulture)
			           + ",\"unitType\":\"" + EscapeJson(TypeDisplayName(unit.Unit?.GetType())) + "\""
			           + ",\"transferSideType\":\"" + EscapeJson(TypeDisplayName(unit.TransferSide?.GetType())) + "\""
			           + ",\"sideIndexKnown\":" + (unit.SideIndexKnown ? "true" : "false")
			           + (unit.SideIndexKnown ? ",\"sideIndex\":" + unit.SideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture) : "")
			           + ",\"dataSideKnown\":" + (unit.DataSideKnown ? "true" : "false")
			           + ",\"dataSideType\":\"" + EscapeJson(TypeDisplayName(unit.DataSide?.GetType())) + "\""
			           + ",\"trainingLawKnown\":" + (unit.TrainingLawKnown ? "true" : "false")
			           + (unit.TrainingLawKnown ? ",\"trainingLaw\":\"" + EscapeJson(unit.TrainingLaw.ToString()) + "\"" : "")
			           + ",\"negativeStatusQueryKnown\":" + (statusKnown ? "true" : "false")
			           + ",\"negativeStatusPresent\":" + (statusKnown && statusInfo.HasSid ? "true" : "false")
			           + (statusKnown ? ",\"negativeStatusInfo\":\"" + EscapeJson(statusInfo.ToString()) + "\"" : "")
			           + (!string.IsNullOrWhiteSpace(statusFailure) ? ",\"negativeStatusFailure\":\"" + EscapeJson(statusFailure) + "\"" : "")
			           + "}");
		}

		return OkResponse(id,
			"\"command\":\"battle_unit_status_probe\""
			+ ",\"unitCount\":" + units.Count.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"registryUnitCount\":" + Homm3BattleUnitLawOwnerRegistry.RegisteredUnitCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"lastRegistration\":\"" + EscapeJson(Homm3BattleUnitLawOwnerRegistry.LastRegistrationSummary) + "\""
			+ ",\"lastClear\":\"" + EscapeJson(Homm3BattleUnitLawOwnerRegistry.LastClearReason) + "\""
			+ ",\"negativeStatusSidCount\":" + negativeStatusSids.Length.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"mutation\":\"disabled\""
			+ ",\"units\":[" + string.Join(",", values) + "]");
	}

	private static string DirectStateM3BfdiShove(string id, string requestJson)
	{
		_ = requestJson;
		if (!Homm3DirectStateM3BfdiShoveDiagnostic.IsMovementPushAllowed())
		{
			return ErrorResponse(id, "direct_state_m3_bfdi_shove_gated",
				"MovementPush gated; place "
				+ Homm3DirectStateM3BfdiShoveDiagnostic.DiagnosticFlag
				+ " beside OfflineUnlockMod.dll (or set MovementPushLivePositiveProven after CapLog agree). gate="
				+ Homm3DirectStateM3BfdiShoveDiagnostic.DescribeGateState());
		}

		if (!Homm3DirectStateM3BfdiShoveDiagnostic.TryRunAdjacentUnitShove(out var resultJson, out var failReason))
		{
			return ErrorResponse(id, "direct_state_m3_bfdi_shove_failed",
				EscapeJson(failReason ?? "unknown")
				+ "; gate=" + Homm3DirectStateM3BfdiShoveDiagnostic.DescribeGateState()
				+ "; registryUnitCount="
				+ Homm3BattleUnitLawOwnerRegistry.RegisteredUnitCount.ToString(
					System.Globalization.CultureInfo.InvariantCulture)
				+ (string.IsNullOrWhiteSpace(resultJson) ? "" : "; partial=" + resultJson));
		}

		return OkResponse(id,
			"\"command\":\"direct_state_m3_bfdi_shove\""
			+ ",\"gate\":\"" + EscapeJson(Homm3DirectStateM3BfdiShoveDiagnostic.DescribeGateState()) + "\""
			+ ",\"result\":" + (string.IsNullOrWhiteSpace(resultJson) ? "null" : resultJson));
	}

	private static string DirectStateM6BfdiTeleport(string id, string requestJson)
	{
		_ = requestJson;
		if (!Homm3DirectStateM6BfdiTeleportDiagnostic.IsMovementTeleportAllowed())
		{
			return ErrorResponse(id, "direct_state_m6_bfdi_teleport_gated",
				"MovementTeleport gated; place "
				+ Homm3DirectStateM6BfdiTeleportDiagnostic.DiagnosticFlag
				+ " beside OfflineUnlockMod.dll (or set MovementTeleportLivePositiveProven after CapLog agree). gate="
				+ Homm3DirectStateM6BfdiTeleportDiagnostic.DescribeGateState());
		}

		if (!Homm3DirectStateM6BfdiTeleportDiagnostic.TryRunNonAdjacentTeleportRelocate(
			    out var resultJson,
			    out var failReason))
		{
			return ErrorResponse(id, "direct_state_m6_bfdi_teleport_failed",
				EscapeJson(failReason ?? "unknown")
				+ "; gate=" + Homm3DirectStateM6BfdiTeleportDiagnostic.DescribeGateState()
				+ "; registryUnitCount="
				+ Homm3BattleUnitLawOwnerRegistry.RegisteredUnitCount.ToString(
					System.Globalization.CultureInfo.InvariantCulture)
				+ (string.IsNullOrWhiteSpace(resultJson) ? "" : "; partial=" + resultJson));
		}

		return OkResponse(id,
			"\"command\":\"direct_state_m6_bfdi_teleport\""
			+ ",\"gate\":\"" + EscapeJson(Homm3DirectStateM6BfdiTeleportDiagnostic.DescribeGateState()) + "\""
			+ ",\"result\":" + (string.IsNullOrWhiteSpace(resultJson) ? "null" : resultJson));
	}

	private static string BattleUnitApplyStatusProbe(string id, string requestJson)
	{
		var unitKey = ReadLong(requestJson, "unitKey", -1);
		if (unitKey < 0)
			return ErrorResponse(id, "battle_unit_apply_status_probe_failed", "unitKey is required and must be non-negative");
		var sid = ReadString(requestJson, "sid") ?? "blade_dancer_debuff";
		if (!Homm3StatusTaxonomyRegistry.TryGet(sid, out var statusEntry) || !Homm3StatusTaxonomyRegistry.HasTag(sid, "negative"))
			return ErrorResponse(id, "battle_unit_apply_status_probe_failed", "status SID is not an exact taxonomy negative status: " + EscapeJson(sid ?? "null"));
		var level = ReadInt(requestJson, "level", 1);
		var duration = ReadInt(requestJson, "duration", 1);
		var value = ReadInt(requestJson, "value", 0);
		var refresh = ReadBool(requestJson, "refresh", true);
		if (level < 0 || duration < 0)
			return ErrorResponse(id, "battle_unit_apply_status_probe_failed", "level and duration must be non-negative");

		var units = Homm3BattleUnitLawOwnerRegistry.SnapshotUnits(64);
		Homm3BattleUnitLawOwnerRegistry.BattleUnitSnapshot target = default;
		var found = false;
		for (var i = 0; i < units.Count; i++)
		{
			if (units[i].UnitKey != unitKey)
				continue;
			target = units[i];
			found = true;
			break;
		}
		if (!found || target.Unit == null)
			return ErrorResponse(id, "battle_unit_apply_status_probe_failed", "registered battle unit key was not found: " + unitKey.ToString(System.Globalization.CultureInfo.InvariantCulture));

		Homm3BuffDebuffNativeAdapter.TryQueryAnyBuffSidFromReceiver(target.Unit, new[] { sid }, out var beforeInfo, out var beforeFailure);
		var statusSource = target.Unit;
		if (statusSource == null)
			return ErrorResponse(id, "battle_unit_apply_status_probe_failed", "registered battle unit has no exact native unit/source object");

		if (!Homm3BuffDebuffNativeAdapter.TryDiagnosticAddBuffSidFromReceiver(
			    target.Unit,
			    sid,
			    statusSource,
			    level,
			    duration,
			    value,
			    refresh,
			    out var afterInfo,
			    out var applyFailure))
		{
			return ErrorResponse(id, "battle_unit_apply_status_probe_failed",
				"exact native status add failed closed: " + EscapeJson(applyFailure ?? "unknown")
				+ "; sourceType=" + EscapeJson(TypeDisplayName(statusSource.GetType()))
				+ "; before=" + EscapeJson(beforeInfo.ToString())
				+ (!string.IsNullOrWhiteSpace(beforeFailure) ? "; beforeFailure=" + EscapeJson(beforeFailure) : ""));
		}

		return OkResponse(id,
			"\"command\":\"battle_unit_apply_status_probe\""
			+ ",\"unitKey\":" + unitKey.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"sid\":\"" + EscapeJson(sid) + "\""
			+ ",\"statusTags\":" + StringArrayJson(statusEntry.Tags)
			+ ",\"level\":" + level.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"duration\":" + duration.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"value\":" + value.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"refresh\":" + (refresh ? "true" : "false")
			+ ",\"unitType\":\"" + EscapeJson(TypeDisplayName(target.Unit.GetType())) + "\""
			+ ",\"sourceType\":\"" + EscapeJson(TypeDisplayName(statusSource.GetType())) + "\""
			+ ",\"sideIndexKnown\":" + (target.SideIndexKnown ? "true" : "false")
			+ (target.SideIndexKnown ? ",\"sideIndex\":" + target.SideIndex.ToString(System.Globalization.CultureInfo.InvariantCulture) : "")
			+ ",\"trainingLawKnown\":" + (target.TrainingLawKnown ? "true" : "false")
			+ (target.TrainingLawKnown ? ",\"trainingLaw\":\"" + EscapeJson(target.TrainingLaw.ToString()) + "\"" : "")
			+ ",\"beforeKnown\":" + (beforeInfo.Manager != null ? "true" : "false")
			+ ",\"beforePresent\":" + (beforeInfo.HasSid ? "true" : "false")
			+ (beforeInfo.Manager != null ? ",\"beforeInfo\":\"" + EscapeJson(beforeInfo.ToString()) + "\"" : "")
			+ (!string.IsNullOrWhiteSpace(beforeFailure) ? ",\"beforeFailure\":\"" + EscapeJson(beforeFailure) + "\"" : "")
			+ ",\"afterPresent\":" + (afterInfo.HasSid ? "true" : "false")
			+ ",\"afterInfo\":\"" + EscapeJson(afterInfo.ToString()) + "\""
			+ ",\"mutation\":\"diagnostic-native-status-add\"");
	}
		private static string CustomLawCandidateSurfaceStatus(string id)
	{
		return OkResponse(id,
			"\"command\":\"custom_law_candidate_surface_status\""
			+ ",\"battleAction\":" + Homm3BattleActionLawRuntime.SnapshotJson()
			+ ",\"morale\":" + Homm3MoraleTriggerLawRuntime.SnapshotJson()
			+ ",\"committedDamageRegistration\":\"" + EscapeJson(Homm3TrainingDamageLawRuntime.RegistrationAuditStatus) + "\""
			+ ",\"counterattackRegistration\":\"" + EscapeJson(Homm3CounterattackDoctrineMutationRuntime.RegistrationAuditStatus) + "\""
			+ ",\"spellCooldownRegistration\":\"" + EscapeJson(Homm3CustomSpellCooldownLawRuntime.RegistrationAuditStatus) + "\""
			+ ",\"rewardResultRegistration\":\"" + EscapeJson(Homm3SquadValueEconomyLawRuntime.RegistrationAuditStatus) + "\""
			+ ",\"rampartAvengerRegistration\":\"" + EscapeJson(Homm3RampartAvengerMarkerRuntime.RegistrationAuditStatus) + "\""
			+ ",\"candidateCounters\":" + Homm3CandidateSurfaceRuntimeCounters.SnapshotJson());
	}
private static string SourcePreparedLawProfiles(string id, string requestJson)
	{
		var factionSid = ReadString(requestJson, "factionSid");
		var rank = ReadInt(requestJson, "rank", 0);
		if (string.IsNullOrWhiteSpace(factionSid))
		{
			if (rank != 0)
				return ErrorResponse(id, "bad_request", "source_prepared_law_profiles rank filter requires factionSid.");
			return OkResponse(id,
				"\"command\":\"source_prepared_law_profiles\""
				+ ",\"scope\":\"all\""
				+ ",\"syntheticBoundary\":\"counterattack and morale-trigger catalog observations are design metadata only, not runtime event proof\""
				+ ",\"profiles\":" + StringArrayJson(Homm3CustomLawImplementationCatalog.DescribeSourcePreparedProfileCatalogLines()));
		}

		if (rank < 0 || rank > 3)
			return ErrorResponse(id, "bad_request", "source_prepared_law_profiles rank must be 0, 1, 2, or 3.");
		if (rank > 0)
		{
			return OkResponse(id,
				"\"command\":\"source_prepared_law_profiles\""
				+ ",\"scope\":\"faction-rank\""
				+ ",\"factionSid\":\"" + EscapeJson(factionSid) + "\""
				+ ",\"rank\":" + rank.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ ",\"syntheticBoundary\":\"counterattack and morale-trigger catalog observations are design metadata only, not runtime event proof\""
				+ ",\"profiles\":" + StringArrayJson(new[] { Homm3CustomLawImplementationCatalog.DescribeSourcePreparedProfiles(factionSid, rank) }));
		}

		var lines = new List<string>(3);
		for (var i = 1; i <= 3; i++)
			lines.Add(Homm3CustomLawImplementationCatalog.DescribeSourcePreparedProfiles(factionSid, i));
		return OkResponse(id,
			"\"command\":\"source_prepared_law_profiles\""
			+ ",\"scope\":\"faction\""
			+ ",\"factionSid\":\"" + EscapeJson(factionSid) + "\""
			+ ",\"syntheticBoundary\":\"counterattack and morale-trigger catalog observations are design metadata only, not runtime event proof\""
			+ ",\"profiles\":" + StringArrayJson(lines));
	}

	private static string MethodSignatures(string id, string typeName, int limit)
	{
		if (string.IsNullOrWhiteSpace(typeName))
			return ErrorResponse(id, "bad_request", "method_signatures requires typeName.");
		limit = Math.Max(1, Math.Min(limit, 200));
		var type = FindType(typeName);
		if (type == null)
			return ErrorResponse(id, "not_found", "Type not found: " + typeName);

		var methods = type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
		var values = new List<string>();
		var max = Math.Min(methods.Length, limit);
		for (var i = 0; i < max; i++)
		{
			var method = methods[i];
			values.Add("{\"name\":\"" + EscapeJson(method.Name) + "\""
				+ ",\"runtimeCallableOrdinal\":" + NullableIntJson(RuntimeCallableOrdinal(method))
				+ ",\"signature\":\"" + EscapeJson(FormatSignature(method)) + "\"}");
		}

		return OkResponse(id,
			"\"typeName\":\"" + EscapeJson(type.FullName ?? type.Name ?? "") + "\","
			+ "\"methods\":[" + string.Join(",", values) + "],"
			+ "\"truncated\":" + (methods.Length > limit ? "true" : "false"));
	}

	private static string FieldSignatures(string id, string typeName, int limit)
	{
		if (string.IsNullOrWhiteSpace(typeName))
			return ErrorResponse(id, "bad_request", "field_signatures requires typeName.");
		limit = Math.Max(1, Math.Min(limit, 200));
		var type = FindType(typeName);
		if (type == null)
			return ErrorResponse(id, "not_found", "Type not found: " + typeName);

		var fields = type.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
		var values = new List<string>();
		var max = Math.Min(fields.Length, limit);
		for (var i = 0; i < max; i++)
		{
			var field = fields[i];
			values.Add("{\"name\":\"" + EscapeJson(field.Name) + "\",\"fieldType\":\"" + EscapeJson(TypeDisplayName(field.FieldType)) + "\",\"isStatic\":" + (field.IsStatic ? "true" : "false") + "}");
		}

		return OkResponse(id,
			"\"typeName\":\"" + EscapeJson(type.FullName ?? type.Name ?? "") + "\","
			+ "\"fields\":[" + string.Join(",", values) + "],"
			+ "\"truncated\":" + (fields.Length > limit ? "true" : "false"));
	}

	private static string ConstructInstanceSnapshot(string id, string requestJson)
	{
		var typeName = ReadString(requestJson, "typeName");
		if (string.IsNullOrWhiteSpace(typeName))
			return ErrorResponse(id, "bad_request", "construct_instance_snapshot requires typeName.");

		var parameterArity = ReadInt(requestJson, "parameterArity", 0);
		if (parameterArity < 0 || parameterArity > 8)
			return ErrorResponse(id, "bad_request", "construct_instance_snapshot parameterArity must be 0..8.");

		var parameterTypesCsv = ReadString(requestJson, "parameterTypes") ?? ReadString(requestJson, "parameterTypeFullNames") ?? "";
		var expectedParameterTypes = SplitTypeList(parameterTypesCsv);
		if (parameterArity == 0 && expectedParameterTypes.Length > 0)
			return ErrorResponse(id, "bad_request", "parameterArity=0 forbids parameterTypes.");
		if (parameterArity > 0 && expectedParameterTypes.Length != parameterArity)
			return ErrorResponse(id, "bad_request", "parameterTypes count must equal parameterArity when arity > 0.");

		var argsJson = ReadString(requestJson, "argsJson") ?? "[]";
		if (!TryParsePrimitiveArgArray(argsJson, out var rawArgs, out var argsError))
			return ErrorResponse(id, "bad_request", argsError);
		if (rawArgs.Length != parameterArity)
			return ErrorResponse(id, "bad_request", "argsJson length must equal parameterArity.");

		var includeInherited = ReadBool(requestJson, "includeInheritedFields", true);
		var fieldLimit = Math.Max(1, Math.Min(ReadInt(requestJson, "fieldLimit", 64), 128));
		var reason = ReadString(requestJson, "reason");
		if (string.IsNullOrWhiteSpace(reason))
			return ErrorResponse(id, "bad_request", "construct_instance_snapshot requires reason.");

		var type = FindType(typeName);
		if (type == null)
			return ErrorResponse(id, "not_found", "Type not found: " + typeName);

		TryInitializeIl2CppType(type);

		if (!TryResolveExactConstructor(type, parameterArity, expectedParameterTypes, out var ctor, out var ctorError))
			return ErrorResponse(id, "constructor_unresolved", ctorError);

		object[] invokeArgs;
		try
		{
			invokeArgs = CoerceConstructorArgs(ctor, rawArgs);
		}
		catch (Exception ex)
		{
			return ErrorResponse(id, "args_coerce_failed", ex.GetBaseException().Message);
		}

		object instance;
		try
		{
			instance = ctor.Invoke(invokeArgs);
		}
		catch (TargetInvocationException ex)
		{
			var inner = ex.InnerException ?? ex;
			return ErrorResponse(id, "constructor_invoke_failed", inner.GetType().Name + ": " + inner.Message);
		}
		catch (Exception ex)
		{
			return ErrorResponse(id, "constructor_invoke_failed", ex.GetType().Name + ": " + ex.Message);
		}

		if (instance == null)
			return ErrorResponse(id, "constructor_invoke_failed", "constructor returned null");

		var snapshot = InstanceFieldSnapshotJson(instance, includeInherited, fieldLimit);
		var ctorParams = ctor.GetParameters();
		var ctorParamTypes = new string[ctorParams.Length];
		for (var i = 0; i < ctorParams.Length; i++)
			ctorParamTypes[i] = TypeDisplayName(ctorParams[i].ParameterType);

		return OkResponse(id,
			"\"command\":\"construct_instance_snapshot\""
			+ ",\"typeName\":\"" + EscapeJson(type.FullName ?? type.Name ?? "") + "\""
			+ ",\"constructorParameterTypes\":" + StringArrayJson(ctorParamTypes)
			+ ",\"parameterArity\":" + parameterArity.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"reason\":\"" + EscapeJson(reason) + "\""
			+ ",\"instance\":" + snapshot);
	}

	private static bool TryResolveExactConstructor(
		Type type,
		int parameterArity,
		string[] expectedParameterTypes,
		out ConstructorInfo ctor,
		out string error)
	{
		ctor = null;
		error = null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		ConstructorInfo[] constructors;
		try
		{
			constructors = type.GetConstructors(flags);
		}
		catch (Exception ex)
		{
			error = "GetConstructors failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}

		var matches = new List<ConstructorInfo>();
		for (var i = 0; i < constructors.Length; i++)
		{
			var candidate = constructors[i];
			var parameters = candidate.GetParameters();
			if (parameters.Length != parameterArity)
				continue;
			// Skip Il2CppInterop IntPtr wrapper constructors for parameterless captures.
			if (parameterArity == 1
			    && parameters[0].ParameterType == typeof(IntPtr)
			    && expectedParameterTypes.Length == 0)
				continue;
			if (parameterArity == 1
			    && expectedParameterTypes.Length == 1
			    && parameters[0].ParameterType == typeof(IntPtr)
			    && !TypeTokenMatches(parameters[0].ParameterType, expectedParameterTypes[0]))
				continue;
			if (parameterArity > 0)
			{
				var allMatch = true;
				for (var p = 0; p < parameters.Length; p++)
				{
					if (!TypeTokenMatches(parameters[p].ParameterType, expectedParameterTypes[p]))
					{
						allMatch = false;
						break;
					}
				}
				if (!allMatch)
					continue;
			}
			matches.Add(candidate);
		}

		if (matches.Count == 0)
		{
			error = "no constructor matched arity=" + parameterArity.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ " on " + (type.FullName ?? type.Name);
			return false;
		}
		if (matches.Count > 1)
		{
			error = "ambiguous constructors (" + matches.Count.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ ") for arity=" + parameterArity.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ "; refine parameterTypes";
			return false;
		}
		ctor = matches[0];
		return true;
	}

	private static bool TypeTokenMatches(Type runtimeType, string expectedToken)
	{
		if (runtimeType == null || string.IsNullOrWhiteSpace(expectedToken))
			return false;
		var token = expectedToken.Trim();
		var full = runtimeType.FullName ?? "";
		var name = runtimeType.Name ?? "";
		if (string.Equals(full, token, StringComparison.OrdinalIgnoreCase)
		    || string.Equals(name, token, StringComparison.OrdinalIgnoreCase))
			return true;
		if (runtimeType.IsEnum
		    && (string.Equals(token, "enum", StringComparison.OrdinalIgnoreCase)
		        || string.Equals(token, full, StringComparison.OrdinalIgnoreCase)))
			return true;
		// Allow short DiffableCs tokens (e.g. int, bool, string).
		if (runtimeType == typeof(int) && (token == "int" || token == "Int32" || token == "System.Int32"))
			return true;
		if (runtimeType == typeof(bool) && (token == "bool" || token == "Boolean" || token == "System.Boolean"))
			return true;
		if (runtimeType == typeof(float) && (token == "float" || token == "Single" || token == "System.Single"))
			return true;
		if (runtimeType == typeof(double) && (token == "double" || token == "Double" || token == "System.Double"))
			return true;
		if (runtimeType == typeof(long) && (token == "long" || token == "Int64" || token == "System.Int64"))
			return true;
		if (runtimeType == typeof(string) && (token == "string" || token == "String" || token == "System.String"))
			return true;
		return name.IndexOf(token, StringComparison.OrdinalIgnoreCase) >= 0
		       || full.IndexOf(token, StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static bool TryParsePrimitiveArgArray(string argsJson, out string[] values, out string error)
	{
		values = Array.Empty<string>();
		error = null;
		if (string.IsNullOrWhiteSpace(argsJson))
		{
			values = Array.Empty<string>();
			return true;
		}
		var trimmed = argsJson.Trim();
		if (trimmed == "[]")
		{
			values = Array.Empty<string>();
			return true;
		}
		if (trimmed.Length < 2 || trimmed[0] != '[' || trimmed[trimmed.Length - 1] != ']')
		{
			error = "argsJson must be a JSON array of primitive/string values";
			return false;
		}
		var inner = trimmed.Substring(1, trimmed.Length - 2).Trim();
		if (inner.Length == 0)
		{
			values = Array.Empty<string>();
			return true;
		}
		var parts = SplitTopLevelList(inner, ',');
		var parsed = new string[parts.Length];
		for (var i = 0; i < parts.Length; i++)
		{
			var part = (parts[i] ?? "").Trim();
			if (part.Length >= 2 && part[0] == '"' && part[part.Length - 1] == '"')
				parsed[i] = Regex.Unescape(part.Substring(1, part.Length - 2));
			else
				parsed[i] = part;
		}
		values = parsed;
		return true;
	}

	private static object[] CoerceConstructorArgs(ConstructorInfo ctor, string[] rawArgs)
	{
		var parameters = ctor.GetParameters();
		var args = new object[parameters.Length];
		for (var i = 0; i < parameters.Length; i++)
		{
			var parameterType = parameters[i].ParameterType;
			var raw = rawArgs[i];
			if (parameterType == typeof(string))
			{
				args[i] = raw;
				continue;
			}
			if (parameterType == typeof(bool))
			{
				if (!bool.TryParse(raw, out var b))
					throw new InvalidOperationException("bool coerce failed at arg " + i);
				args[i] = b;
				continue;
			}
			if (parameterType == typeof(int) || parameterType == typeof(short) || parameterType == typeof(byte)
			    || parameterType == typeof(long) || parameterType == typeof(uint))
			{
				if (!long.TryParse(raw, System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var n))
					throw new InvalidOperationException("integer coerce failed at arg " + i);
				args[i] = Convert.ChangeType(n, parameterType, System.Globalization.CultureInfo.InvariantCulture);
				continue;
			}
			if (parameterType == typeof(float) || parameterType == typeof(double) || parameterType == typeof(decimal))
			{
				if (!double.TryParse(raw, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var f))
					throw new InvalidOperationException("float coerce failed at arg " + i);
				args[i] = Convert.ChangeType(f, parameterType, System.Globalization.CultureInfo.InvariantCulture);
				continue;
			}
			if (parameterType.IsEnum)
			{
				try
				{
					args[i] = Enum.Parse(parameterType, raw, ignoreCase: true);
				}
				catch
				{
					if (!long.TryParse(raw, System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var enumNum))
						throw new InvalidOperationException("enum coerce failed at arg " + i + " for " + parameterType.FullName);
					args[i] = Enum.ToObject(parameterType, enumNum);
				}
				continue;
			}
			throw new InvalidOperationException(
				"unsupported constructor parameter type " + TypeDisplayName(parameterType)
				+ " at arg " + i.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ "; only primitive/enum/string args are allowed");
		}
		return args;
	}

	private static string InstanceFieldSnapshotJson(object instance, bool includeInherited, int fieldLimit)
	{
		if (instance == null)
			return "{\"isNull\":true,\"fields\":{}}";

		var runtimeValue = UnwrapNativeTypedObject(instance, out var reflectedType);
		var type = reflectedType ?? runtimeValue.GetType();
		var fields = new List<string>();
		var seen = new HashSet<string>(StringComparer.Ordinal);

		// Prefer NativeFieldInfoPtr_* logical fields (IL2CPP truth) over interop wrapper managed fields.
		for (var current = type; current != null && current != typeof(object); current = includeInherited ? current.BaseType : null)
		{
			if (string.Equals(current.FullName, "System.EventArgs", StringComparison.Ordinal)
			    || current == typeof(EventArgs))
				break;
			FieldInfo[] declared;
			try
			{
				declared = current.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly);
			}
			catch
			{
				break;
			}
			for (var i = 0; i < declared.Length; i++)
			{
				if (fields.Count >= fieldLimit)
					break;
				var field = declared[i];
				if (field == null || string.IsNullOrEmpty(field.Name))
					continue;
				if (!field.IsStatic || field.FieldType != typeof(IntPtr))
					continue;
				if (!field.Name.StartsWith("NativeFieldInfoPtr_", StringComparison.Ordinal))
					continue;
				var logicalName = field.Name.Substring("NativeFieldInfoPtr_".Length);
				if (string.IsNullOrEmpty(logicalName) || !seen.Add(logicalName))
					continue;
				if (TryReadNativeField(runtimeValue, type, logicalName, out var nativeValue, out _))
					fields.Add("\"" + EscapeJson(logicalName) + "\":" + SnapshotValueJson(nativeValue));
				else
					fields.Add("\"" + EscapeJson(logicalName) + "\":{\"readError\":\"native_field_unreadable\"}");
			}
			if (!includeInherited)
				break;
		}

		// Fall back to managed instance fields only when no native logical fields were found.
		if (fields.Count == 0)
		{
			for (var current = type; current != null && current != typeof(object); current = includeInherited ? current.BaseType : null)
			{
				FieldInfo[] declared;
				try
				{
					declared = current.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				}
				catch
				{
					break;
				}
				for (var i = 0; i < declared.Length; i++)
				{
					if (fields.Count >= fieldLimit)
						break;
					var field = declared[i];
					if (field == null || string.IsNullOrEmpty(field.Name))
						continue;
					if (field.Name.StartsWith("NativeFieldInfoPtr_", StringComparison.Ordinal)
					    || field.Name.StartsWith("NativeMethodInfoPtr_", StringComparison.Ordinal))
						continue;
					if (!seen.Add(field.Name))
						continue;
					fields.Add("\"" + EscapeJson(field.Name) + "\":" + FieldValueJson(runtimeValue, field));
				}
				if (!includeInherited)
					break;
			}
		}

		return "{"
			+ "\"isNull\":false"
			+ ",\"type\":\"" + EscapeJson(type.FullName ?? type.Name ?? "") + "\""
			+ ",\"fields\":{" + string.Join(",", fields) + "}"
			+ "}";
	}

	private static string SnapshotValueJson(object raw)
	{
		if (raw == null)
			return "null";
		if (raw is NativeTypedObject nativeTyped)
		{
			var inner = nativeTyped.Instance;
			if (inner == null)
				return "null";
			return "{\"isNull\":false,\"type\":\"" + EscapeJson(TypeDisplayName(nativeTyped.ReflectionType ?? inner.GetType())) + "\"}";
		}
		if (raw is string s)
			return "\"" + EscapeJson(s) + "\"";
		if (raw is bool b)
			return b ? "true" : "false";
		var rawType = raw.GetType();
		if (rawType.IsEnum)
		{
			var numeric = Convert.ToInt64(raw, System.Globalization.CultureInfo.InvariantCulture);
			return "{\"enumType\":\"" + EscapeJson(TypeDisplayName(rawType)) + "\",\"name\":\""
				+ EscapeJson(raw.ToString() ?? "") + "\",\"value\":"
				+ numeric.ToString(System.Globalization.CultureInfo.InvariantCulture) + "}";
		}
		if (rawType.IsPrimitive || rawType == typeof(decimal))
			return Convert.ToString(raw, System.Globalization.CultureInfo.InvariantCulture) ?? "null";
		if (raw is Array arr)
		{
			return "{\"isArray\":true,\"length\":"
				+ arr.Length.ToString(System.Globalization.CultureInfo.InvariantCulture)
				+ ",\"elementType\":\"" + EscapeJson(TypeDisplayName(rawType.GetElementType())) + "\"}";
		}
		if (raw is Il2CppObjectBase)
			return "{\"isNull\":false,\"type\":\"" + EscapeJson(TypeDisplayName(rawType)) + "\"}";
		return "{\"isNull\":false,\"type\":\"" + EscapeJson(TypeDisplayName(rawType)) + "\"}";
	}

	private static string FieldValueJson(object owner, FieldInfo field)
	{
		object raw;
		try
		{
			raw = field.GetValue(owner);
		}
		catch (Exception ex)
		{
			return "{\"readError\":\"" + EscapeJson(ex.GetType().Name + ": " + ex.Message) + "\"}";
		}
		return SnapshotValueJson(raw);
	}

	private static string ResolveDecompMethod(string id, string requestJson)
	{
		var typeName = ReadString(requestJson, "typeName") ?? ReadString(requestJson, "decompTypeName");
		var signature = ReadString(requestJson, "signature") ?? ReadString(requestJson, "decompSignature");
		var methodName = ReadString(requestJson, "methodName") ?? ReadString(requestJson, "decompMethodName");
		var returnType = ReadString(requestJson, "returnType");
		var parameterTypes = ReadString(requestJson, "parameterTypes") ?? ReadString(requestJson, "parameterTypeFullNames");
		var methodOrdinal = ReadOptionalInt(requestJson, "methodOrdinal") ?? ReadOptionalInt(requestJson, "decompMethodOrdinal");
		var limit = Math.Max(1, Math.Min(ReadInt(requestJson, "limit", 12), 50));
		var includeInherited = ReadBool(requestJson, "includeInherited", false);

		if (string.IsNullOrWhiteSpace(typeName))
			return ErrorResponse(id, "bad_request", "resolve_decomp_method requires typeName.");
		ParseDecompSignature(signature, ref methodName, ref returnType, ref parameterTypes);
		if (string.IsNullOrWhiteSpace(methodName) && string.IsNullOrWhiteSpace(returnType) && string.IsNullOrWhiteSpace(parameterTypes) && !methodOrdinal.HasValue)
			return ErrorResponse(id, "bad_request", "resolve_decomp_method requires signature, methodName, returnType, parameterTypes, or methodOrdinal.");

		var type = FindType(typeName);
		if (type == null)
			return ErrorResponse(id, "not_found", "Type not found by runtime or obfuscated name: " + typeName);

		var expectedParameters = SplitTypeList(parameterTypes);
		var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		if (!includeInherited)
			flags |= BindingFlags.DeclaredOnly;
		var methods = type.GetMethods(flags);
		var candidates = new List<MethodCandidateScore>();
		for (var i = 0; i < methods.Length; i++)
		{
			var method = methods[i];
			var runtimeCallableOrdinal = RuntimeCallableOrdinal(method);
			var score = ScoreMethodCandidate(method, methodName, returnType, expectedParameters, methodOrdinal, runtimeCallableOrdinal, out var reasons);
			if (score <= 0)
				continue;
			candidates.Add(new MethodCandidateScore(method, runtimeCallableOrdinal, score, reasons));
		}
		candidates.Sort((a, b) =>
		{
			var scoreCompare = b.Score.CompareTo(a.Score);
			return scoreCompare != 0 ? scoreCompare : string.CompareOrdinal(a.Method.Name, b.Method.Name);
		});

		var values = new List<string>();
		var max = Math.Min(candidates.Count, limit);
		for (var i = 0; i < max; i++)
			values.Add(MethodCandidateJson(candidates[i]));

		return OkResponse(id,
			"\"decompTypeName\":\"" + EscapeJson(typeName) + "\""
			+ ",\"resolvedTypeName\":\"" + EscapeJson(type.FullName ?? type.Name ?? "") + "\""
			+ ",\"typeObfuscatedName\":\"" + EscapeJson(GameMember.ReadObfuscatedName(type) ?? "") + "\""
			+ ",\"decompMethodName\":\"" + EscapeJson(methodName ?? "") + "\""
			+ ",\"decompMethodOrdinal\":" + NullableIntJson(methodOrdinal)
			+ ",\"returnType\":\"" + EscapeJson(returnType ?? "") + "\""
			+ ",\"parameterTypes\":" + StringArrayJson(expectedParameters)
			+ ",\"candidates\":[" + string.Join(",", values) + "]"
			+ ",\"candidateCount\":" + candidates.Count.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"truncated\":" + (candidates.Count > limit ? "true" : "false")
			+ ",\"evidenceBoundary\":["
			+ "\"runtimeName and obfuscatedName are reflection metadata evidence\","
			+ "\"runtimeCallableOrdinal is runtime reflection ordering and should be paired with static Cpp2IL evidence\","
			+ "\"signature-shape matches are candidates until reviewed against decomp/static evidence\","
			+ "\"this command is read-only and does not invoke or patch methods\""
			+ "]");
	}

	private static string UnityRenderers(string id, string nameContains, int limit)
	{
		if (string.IsNullOrWhiteSpace(nameContains))
			return ErrorResponse(id, "bad_request", "unity_renderers requires nameContains.");
		limit = Math.Max(1, Math.Min(limit, 120));
		var values = new List<string>();
		var count = 0;
		var filter = nameContains.Trim();
		GameObject[] objects;
		try
		{
			objects = UnityObject.FindObjectsOfType<GameObject>(true);
		}
		catch (Exception ex)
		{
			return ErrorResponse(id, "unity_error", ex.GetType().Name + ": " + ex.Message);
		}

		for (var i = 0; i < objects.Length; i++)
		{
			var go = objects[i];
			if (!go)
				continue;
			var path = UnityPath(go.transform);
			if ((go.name ?? "").IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0
			    && path.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			values.Add(UnityGameObjectJson(go, path, 16));
			count++;
			if (count >= limit)
				return OkResponse(id, "\"filter\":\"" + EscapeJson(filter) + "\",\"objects\":[" + string.Join(",", values) + "],\"truncated\":true");
		}
		return OkResponse(id, "\"filter\":\"" + EscapeJson(filter) + "\",\"objects\":[" + string.Join(",", values) + "],\"truncated\":false");
	}

	private static string UnityUiSurfaces(string id, string nameContains, int limit)
	{
		if (string.IsNullOrWhiteSpace(nameContains))
			return ErrorResponse(id, "bad_request", "unity_ui_surfaces requires nameContains.");
		limit = Math.Max(1, Math.Min(limit, 120));
		var values = new List<string>();
		var count = 0;
		var filter = nameContains.Trim();
		GameObject[] objects;
		try
		{
			objects = UnityObject.FindObjectsOfType<GameObject>(true);
		}
		catch (Exception ex)
		{
			return ErrorResponse(id, "unity_error", ex.GetType().Name + ": " + ex.Message);
		}

		for (var i = 0; i < objects.Length; i++)
		{
			var go = objects[i];
			if (!go)
				continue;
			var path = UnityPath(go.transform);
			if ((go.name ?? "").IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0
			    && path.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			values.Add(UnityUiSurfaceJson(go, path));
			count++;
			if (count >= limit)
				return OkResponse(id, "\"filter\":\"" + EscapeJson(filter) + "\",\"objects\":[" + string.Join(",", values) + "],\"truncated\":true");
		}
		return OkResponse(id, "\"filter\":\"" + EscapeJson(filter) + "\",\"objects\":[" + string.Join(",", values) + "],\"truncated\":false");
	}

	private static string UnityObjectsExact(string id, string requestJson)
	{
		var exactName = ReadString(requestJson, "name") ?? ReadString(requestJson, "exactName");
		var exactPath = ReadString(requestJson, "path") ?? ReadString(requestJson, "exactPath");
		if (string.IsNullOrWhiteSpace(exactName) && string.IsNullOrWhiteSpace(exactPath))
			return ErrorResponse(id, "bad_request", "unity_objects_exact requires exact name or path.");
		var requireActiveHierarchy = ReadBool(requestJson, "requireActiveHierarchy", false);
		var limit = Math.Max(1, Math.Min(ReadInt(requestJson, "limit", 40), 120));
		var values = new List<string>();
		GameObject[] objects;
		try
		{
			objects = UnityObject.FindObjectsOfType<GameObject>(true);
		}
		catch (Exception ex)
		{
			return ErrorResponse(id, "unity_error", ex.GetType().Name + ": " + ex.Message);
		}
		for (var i = 0; i < objects.Length; i++)
		{
			var go = objects[i];
			if (!go)
				continue;
			if (requireActiveHierarchy && !go.activeInHierarchy)
				continue;
			var path = UnityPath(go.transform);
			if (!string.IsNullOrWhiteSpace(exactName) && !string.Equals(go.name ?? "", exactName, StringComparison.Ordinal))
				continue;
			if (!string.IsNullOrWhiteSpace(exactPath) && !string.Equals(path, exactPath, StringComparison.Ordinal))
				continue;
			values.Add(UnityGameObjectJson(go, path, 8));
			if (values.Count >= limit)
				return OkResponse(id, "\"objects\":[" + string.Join(",", values) + "],\"truncated\":true");
		}
		return OkResponse(id, "\"objects\":[" + string.Join(",", values) + "],\"truncated\":false");
	}

	private static string ComponentMemberPath(string id, string requestJson)
	{
		if (!TryResolveGetterTarget(requestJson, out var target, out var targetLabel, out var targetError))
			return ErrorResponse(id, "target_not_found", targetError);
		if (target == null)
			return ErrorResponse(id, "target_not_found", "Resolved member path target is null.");

		var memberPath = ReadString(requestJson, "memberPath") ?? ReadString(requestJson, "pathMembers");
		if (string.IsNullOrWhiteSpace(memberPath))
			return ErrorResponse(id, "bad_request", "component_member_path requires memberPath.");

		var allowProperties = ReadBool(requestJson, "allowProperties", false);
		var fieldLimit = Math.Max(0, Math.Min(ReadInt(requestJson, "fieldLimit", 24), 80));
		var maxSegments = Math.Max(1, Math.Min(ReadInt(requestJson, "maxSegments", 16), 32));
		var segments = memberPath.Split(new[] { '.' }, StringSplitOptions.RemoveEmptyEntries);
		if (segments.Length > maxSegments)
			return ErrorResponse(id, "path_too_long", "memberPath exceeds maxSegments.");

		var current = target;
		var steps = new List<string>();
		steps.Add(MemberPathStepJson("target", targetLabel, current, fieldLimit, null));
		for (var i = 0; i < segments.Length; i++)
		{
			var segment = segments[i].Trim();
			if (segment.Length == 0)
				continue;
			if (!TryReadExactMemberSegment(current, segment, allowProperties, out var next, out var note))
			{
				return ErrorResponse(id, "member_not_found", "Failed at segment '" + segment + "': " + note);
			}
			current = next;
			steps.Add(MemberPathStepJson("segment", segment, current, fieldLimit, note));
			if (current == null)
				break;
		}

		return OkResponse(id,
			"\"command\":\"component_member_path\""
			+ ",\"target\":\"" + EscapeJson(targetLabel ?? "") + "\""
			+ ",\"memberPath\":\"" + EscapeJson(memberPath) + "\""
			+ ",\"allowProperties\":" + (allowProperties ? "true" : "false")
			+ ",\"steps\":[" + string.Join(",", steps) + "]"
			+ ",\"result\":" + ObjectSummaryJson(current, fieldLimit));
	}

		private static string UnityObjectComponents(string id, string requestJson)
	{
		if (!TryResolveGameObjectTarget(requestJson, out var go, out var error))
			return ErrorResponse(id, "not_found", error ?? "unity_object_components requires objectId, exact path, or exact name.");
		var includeMembers = ReadBool(requestJson, "includeMembers", true);
		var memberLimit = Math.Max(0, Math.Min(ReadInt(requestJson, "memberLimit", 40), 120));
		var components = go.GetComponents<Component>();
		var values = new List<string>();
		for (var i = 0; i < components.Length; i++)
		{
			var component = components[i];
			if (!component)
			{
				values.Add("{\"index\":" + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + ",\"missing\":true}");
				continue;
			}
			var type = component.GetType();
			values.Add("{"
			           + "\"index\":" + i.ToString(System.Globalization.CultureInfo.InvariantCulture)
			           + ",\"type\":\"" + EscapeJson(TypeDisplayName(type)) + "\""
			           + ",\"fullName\":\"" + EscapeJson(type.FullName ?? "") + "\""
			           + ",\"members\":" + (includeMembers ? ComponentSafeMemberJson(component, type, memberLimit) : "[]")
			           + "}");
		}
		return OkResponse(id,
			"\"command\":\"unity_object_components\""
			+ ",\"objectId\":" + go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"name\":\"" + EscapeJson(go.name ?? "") + "\""
			+ ",\"path\":\"" + EscapeJson(UnityPath(go.transform)) + "\""
			+ ",\"scene\":\"" + EscapeJson(go.scene.name ?? "") + "\""
			+ ",\"activeSelf\":" + (go.activeSelf ? "true" : "false")
			+ ",\"activeInHierarchy\":" + (go.activeInHierarchy ? "true" : "false")
			+ ",\"componentCount\":" + components.Length.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"components\":[" + string.Join(",", values) + "]");
	}

	private static string ComponentSafeMemberJson(Component component, Type type, int memberLimit)
	{
		if (!component || type == null || memberLimit <= 0)
			return "[]";
		var values = new List<string>();
		foreach (var method in type.GetMethods(BindingFlags.Instance | BindingFlags.Public))
		{
			if (values.Count >= memberLimit)
				break;
			if (method == null || method.GetParameters().Length != 0 || method.ReturnType == typeof(void))
				continue;
			if (!method.Name.StartsWith("get_", StringComparison.Ordinal) && !method.Name.StartsWith("Method_Public_get_", StringComparison.Ordinal))
				continue;
			values.Add(ComponentMemberProbeJson(component, method.Name, method.ReturnType, () => method.Invoke(component, null)));
		}
		foreach (var field in type.GetFields(BindingFlags.Instance | BindingFlags.Public))
		{
			if (values.Count >= memberLimit)
				break;
			if (field == null)
				continue;
			values.Add(ComponentMemberProbeJson(component, field.Name, field.FieldType, () => field.GetValue(component)));
		}
		return "[" + string.Join(",", values) + "]";
	}

	private static string ComponentMemberProbeJson(object target, string memberName, Type valueType, Func<object> read)
	{
		try
		{
			var value = read != null ? read() : null;
			return "{"
			       + "\"name\":\"" + EscapeJson(memberName ?? "") + "\""
			       + ",\"type\":\"" + EscapeJson(TypeDisplayName(valueType)) + "\""
			       + ",\"value\":" + SafeInspectableValueJson(value)
			       + "}";
		}
		catch (Exception ex)
		{
			return "{\"name\":\"" + EscapeJson(memberName ?? "") + "\",\"type\":\"" + EscapeJson(TypeDisplayName(valueType)) + "\",\"error\":\"" + EscapeJson(ex.GetType().Name + ": " + ex.Message) + "\"}";
		}
	}

	private static string SafeInspectableValueJson(object value)
	{
		if (value == null)
			return "null";
		if (value is string s)
			return "\"" + EscapeJson(s) + "\"";
		if (value is bool b)
			return b ? "true" : "false";
		if (value is int or long or short or byte or uint or ulong or ushort or sbyte)
			return Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture);
		if (value is float f)
			return FloatJson(f);
		if (value is double d)
			return d.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture);
		if (value is Transform transform)
			return "{\"kind\":\"Transform\",\"objectId\":" + (transform.gameObject ? transform.gameObject.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ",\"path\":\"" + EscapeJson(UnityPath(transform)) + "\"}";
		if (value is GameObject go)
			return "{\"kind\":\"GameObject\",\"objectId\":" + go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) + ",\"path\":\"" + EscapeJson(UnityPath(go.transform)) + "\"}";
		if (value is Component component)
			return "{\"kind\":\"Component\",\"objectId\":" + (component.gameObject ? component.gameObject.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ",\"componentType\":\"" + EscapeJson(TypeDisplayName(component.GetType())) + "\",\"path\":\"" + EscapeJson(component.transform ? UnityPath(component.transform) : "") + "\"}";
		return "{\"kind\":\"Object\",\"type\":\"" + EscapeJson(TypeDisplayName(value.GetType())) + "\",\"text\":\"" + EscapeJson(value.ToString() ?? "") + "\"}";
	}
private static string UnityComponentsByType(string id, string requestJson)
	{
		var typeName = ReadString(requestJson, "componentType") ?? ReadString(requestJson, "typeName");
		if (string.IsNullOrWhiteSpace(typeName))
			return ErrorResponse(id, "bad_request", "unity_components_by_type requires componentType.");
		var type = FindLoadedTypeByName(typeName);
		if (type == null)
			return ErrorResponse(id, "not_found", "Component type not found: " + typeName);
		if (!typeof(Component).IsAssignableFrom(type))
			return ErrorResponse(id, "not_component", "Resolved type is not a UnityEngine.Component: " + TypeDisplayName(type));

		var limit = Math.Max(1, Math.Min(ReadInt(requestJson, "limit", 40), 120));
		var fieldLimit = Math.Max(0, Math.Min(ReadInt(requestJson, "fieldLimit", 12), 40));
		var requireActiveHierarchy = ReadBool(requestJson, "requireActiveHierarchy", false);
		var sceneName = ReadString(requestJson, "scene");
		var nameContains = ReadString(requestJson, "nameContains");
		var pathContains = ReadString(requestJson, "pathContains");
		var values = new List<string>();
		var total = 0;
		var components = UnityObject.FindObjectsOfType<Component>(true);
		for (var i = 0; i < components.Length; i++)
		{
			var component = components[i];
			if (!component || !component.gameObject)
				continue;
			if (!ComponentMatchesType(component, type, typeName))
				continue;
			if (requireActiveHierarchy && !component.gameObject.activeInHierarchy)
				continue;
			if (!string.IsNullOrWhiteSpace(sceneName)
			    && (!component.gameObject.scene.IsValid() || !string.Equals(component.gameObject.scene.name ?? "", sceneName, StringComparison.Ordinal)))
				continue;
			var path = UnityPath(component.transform);
			if (!string.IsNullOrWhiteSpace(nameContains)
			    && (component.gameObject.name ?? "").IndexOf(nameContains, StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			if (!string.IsNullOrWhiteSpace(pathContains)
			    && (path ?? "").IndexOf(pathContains, StringComparison.OrdinalIgnoreCase) < 0)
				continue;

			total++;
			if (values.Count >= limit)
				continue;
			values.Add(UnityComponentInstanceJson(component, path, fieldLimit));
		}

		return OkResponse(id,
			"\"command\":\"unity_components_by_type\""
			+ ",\"componentType\":\"" + EscapeJson(type.FullName ?? type.Name ?? "") + "\""
			+ ",\"total\":" + total.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"objects\":[" + string.Join(",", values) + "]"
			+ ",\"truncated\":" + (total > values.Count ? "true" : "false"));
	}

	private static bool ComponentMatchesType(Component component, Type type, string requestedTypeName)
	{
		if (!component || type == null)
			return false;
		try
		{
			if (type.IsInstanceOfType(component))
				return true;
		}
		catch { }
		var componentType = component.GetType();
		try
		{
			if (componentType == type || componentType.IsSubclassOf(type))
				return true;
		}
		catch { }
		var componentTypeName = ComponentTypeName(component);
		if (string.Equals(componentTypeName, type.FullName ?? type.Name ?? "", StringComparison.Ordinal)
		    || string.Equals(componentTypeName, type.Name ?? "", StringComparison.Ordinal)
		    || string.Equals(componentTypeName, requestedTypeName ?? "", StringComparison.Ordinal)
		    || string.Equals(componentTypeName, requestedTypeName ?? "", StringComparison.OrdinalIgnoreCase))
			return true;
		var managedName = componentType.FullName ?? componentType.Name ?? "";
		return string.Equals(managedName, requestedTypeName ?? "", StringComparison.Ordinal)
		       || string.Equals(managedName, type.FullName ?? type.Name ?? "", StringComparison.Ordinal);
	}

	private static bool TryReadExactMemberSegment(object owner, string segment, bool allowProperties, out object value, out string note)
	{
		value = null;
		note = null;
		if (owner == null)
		{
			note = "owner is null";
			return false;
		}
		if (string.IsNullOrWhiteSpace(segment))
		{
			note = "empty segment";
			return false;
		}

		var memberName = segment;
		int? index = null;
		var bracket = segment.IndexOf('[', StringComparison.Ordinal);
		if (bracket >= 0 && segment.EndsWith("]", StringComparison.Ordinal))
		{
			memberName = segment.Substring(0, bracket);
			var text = segment.Substring(bracket + 1, segment.Length - bracket - 2);
			if (!int.TryParse(text, System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var parsed) || parsed < 0)
			{
				note = "invalid index";
				return false;
			}
			index = parsed;
		}

		object next = owner;
		if (!string.IsNullOrWhiteSpace(memberName))
		{
			if (!TryReadExactMember(owner, memberName, allowProperties, out next, out note))
				return false;
		}

		if (index.HasValue)
		{
			if (!TryReadIndexedValue(next, index.Value, out next, out note))
				return false;
			note = string.IsNullOrWhiteSpace(note) ? "index " + index.Value.ToString(System.Globalization.CultureInfo.InvariantCulture) : note;
		}
		else if (string.IsNullOrWhiteSpace(note))
		{
			note = "member";
		}

		value = next;
		return true;
	}

	private static bool TryReadExactMember(object owner, string memberName, bool allowProperties, out object value, out string note)
	{
		value = null;
		note = null;
		if (owner == null)
		{
			note = "owner is null";
			return false;
		}
		var runtimeOwner = UnwrapNativeTypedObject(owner, out var reflectionType);
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		for (var type = reflectionType ?? runtimeOwner.GetType(); type != null; type = type.BaseType)
		{
			try
			{
				var field = type.GetField(memberName, flags);
				if (field != null)
				{
					value = field.GetValue(runtimeOwner);
					note = "field " + TypeDisplayName(field.FieldType);
					return true;
				}
			}
			catch (Exception ex)
			{
				note = "field read failed: " + ex.GetType().Name + ": " + ex.Message;
				return false;
			}

			if (!allowProperties)
				continue;
			try
			{
				var property = type.GetProperty(memberName, flags);
				if (property == null)
					continue;
				if (!property.CanRead || property.GetIndexParameters().Length != 0)
				{
					note = "property is not a readable scalar";
					return false;
				}
				value = property.GetValue(runtimeOwner);
				note = "property " + TypeDisplayName(property.PropertyType);
				return true;
			}
			catch (TargetInvocationException ex)
			{
				var inner = ex.InnerException ?? ex;
				note = "property getter failed: " + inner.GetType().Name + ": " + inner.Message;
				return false;
			}
			catch (Exception ex)
			{
				note = "property read failed: " + ex.GetType().Name + ": " + ex.Message;
				return false;
			}
		}
		if (TryReadNativeField(runtimeOwner, reflectionType, memberName, out value, out note))
			return true;
		note = "exact member not found";
		return false;
	}

	private static object UnwrapNativeTypedObject(object owner, out Type reflectionType)
	{
		if (owner is NativeTypedObject typed)
		{
			reflectionType = typed.ReflectionType;
			if (typed.Instance is Il2CppObjectBase nativeInstance
			    && reflectionType != null
			    && typeof(Il2CppObjectBase).IsAssignableFrom(reflectionType)
			    && !reflectionType.IsInstanceOfType(nativeInstance)
			    && nativeInstance.Pointer != IntPtr.Zero)
			{
				try
				{
					var wrapped = CreateExactIl2CppObjectWrapper(nativeInstance, reflectionType);
					if (wrapped != null)
						return wrapped;
				}
				catch
				{
				}
			}
			return typed.Instance;
		}
		reflectionType = null;
		return owner;
	}

	private static object CreateExactIl2CppObjectWrapper(Il2CppObjectBase nativeInstance, Type reflectionType)
	{
		if (nativeInstance == null || nativeInstance.Pointer == IntPtr.Zero || reflectionType == null || !typeof(Il2CppObjectBase).IsAssignableFrom(reflectionType))
			return null;
		if (reflectionType.IsInstanceOfType(nativeInstance))
			return nativeInstance;
		try
		{
			foreach (var method in typeof(Il2CppObjectBase).GetMethods(BindingFlags.Public | BindingFlags.Instance))
			{
				if (!string.Equals(method.Name, "TryCast", StringComparison.Ordinal) || !method.IsGenericMethodDefinition)
					continue;
				if (method.GetParameters().Length != 0)
					continue;
				var cast = method.MakeGenericMethod(reflectionType).Invoke(nativeInstance, Array.Empty<object>());
				if (cast != null && reflectionType.IsInstanceOfType(cast))
					return cast;
			}
		}
		catch
		{
		}
		return CreateExactIl2CppObjectWrapper(nativeInstance.Pointer, reflectionType);
	}

	private static object CreateExactIl2CppObjectWrapper(IntPtr pointer, Type reflectionType)
	{
		if (pointer == IntPtr.Zero || reflectionType == null || !typeof(Il2CppObjectBase).IsAssignableFrom(reflectionType))
			return null;
		try
		{
			var pooled = CreateIl2CppObjectWrapper(pointer, reflectionType);
			if (pooled != null && reflectionType.IsInstanceOfType(pooled))
				return pooled;
		}
		catch
		{
		}
		try
		{
			var ctor = reflectionType.GetConstructor(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance, null, new[] { typeof(IntPtr) }, null);
			if (ctor != null)
			{
				var constructed = ctor.Invoke(new object[] { pointer });
				if (constructed != null && reflectionType.IsInstanceOfType(constructed))
					return constructed;
			}
		}
		catch
		{
		}
		return null;
	}

	private static bool TryReadNativeField(object owner, Type reflectionType, string memberName, out object value, out string note)
	{
		value = null;
		note = null;
		if (!TryResolveNativeField(owner, reflectionType, memberName, out var il2Cpp, out var fieldPtr, out var ownerType, out note))
			return false;
		var fieldType = ResolveNativeFieldManagedType(fieldPtr);
		if (fieldType != null && IsSupportedPrimitiveFieldType(fieldType))
			return TryReadNativeField(owner, ownerType, memberName, fieldType, out value, out note);
		try
		{
			var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
			var valuePtr = Marshal.ReadIntPtr(IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr)));
			if (valuePtr == IntPtr.Zero)
			{
				value = null;
				note = "native field null";
				return true;
			}
			if (fieldType == typeof(string))
			{
				value = IL2CPP.Il2CppStringToManaged(valuePtr);
				note = "native field System.String";
				return true;
			}
			var wrapped = CreateIl2CppObjectWrapper(valuePtr, fieldType);
			value = fieldType != null && wrapped != null ? new NativeTypedObject(wrapped, fieldType) : wrapped;
			note = "native field " + TypeDisplayName(fieldType ?? wrapped?.GetType());
			return true;
		}
		catch (Exception ex)
		{
			note = "native field read failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static bool TryReadNativeField(object owner, Type reflectionType, string memberName, Type fieldType, out object value, out string note)
	{
		value = null;
		note = null;
		if (!TryResolveNativeField(owner, reflectionType, memberName, out var il2Cpp, out var fieldPtr, out _, out note))
			return false;
		if (fieldType == null)
		{
			note = "native field type unavailable";
			return false;
		}
		try
		{
			var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
			var address = IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr));
			value = ReadNativePrimitiveOrString(address, fieldType);
			note = "native field " + TypeDisplayName(fieldType);
			return true;
		}
		catch (Exception ex)
		{
			note = "native field read failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static bool TryWriteNativeField(object owner, Type reflectionType, string memberName, Type fieldType, object value, out string note)
	{
		note = null;
		if (!TryResolveNativeField(owner, reflectionType, memberName, out var il2Cpp, out var fieldPtr, out _, out note))
			return false;
		if (fieldType == null || !IsSupportedPrimitiveFieldType(fieldType))
		{
			note = "native field type is not a supported primitive/string/enum";
			return false;
		}
		try
		{
			var objectPtr = IL2CPP.Il2CppObjectBaseToPtrNotNull(il2Cpp);
			var address = IntPtr.Add(objectPtr, (int)IL2CPP.il2cpp_field_get_offset(fieldPtr));
			WriteNativePrimitiveOrString(objectPtr, address, fieldType, value);
			note = "native field write";
			return true;
		}
		catch (Exception ex)
		{
			note = "native field write failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static bool TryResolveNativeField(object owner, Type reflectionType, string memberName, out Il2CppObjectBase il2Cpp, out IntPtr fieldPtr, out Type ownerType, out string note)
	{
		il2Cpp = null;
		fieldPtr = IntPtr.Zero;
		ownerType = reflectionType;
		note = null;
		if (owner is not Il2CppObjectBase nativeOwner || nativeOwner.Pointer == IntPtr.Zero)
		{
			note = "owner is not an IL2CPP object";
			return false;
		}
		il2Cpp = nativeOwner;
		ownerType ??= owner.GetType();
		for (var current = ownerType; current != null; current = current.BaseType)
		{
			fieldPtr = ResolveNativeFieldPointer(current, memberName);
			if (fieldPtr != IntPtr.Zero)
			{
				ownerType = current;
				return true;
			}
		}
		note = "native field pointer not found";
		return false;
	}

	private static IntPtr ResolveNativeFieldPointer(Type ownerType, string logicalName)
	{
		if (ownerType == null || string.IsNullOrWhiteSpace(logicalName))
			return IntPtr.Zero;
		TryInitializeIl2CppType(ownerType);
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var current = ownerType; current != null; current = current.BaseType)
		{
			foreach (var nativeInfoName in ExpandNativeFieldInfoNames(logicalName))
			{
				try
				{
					var field = current.GetField(nativeInfoName, flags);
					if (field != null && field.FieldType == typeof(IntPtr) && field.IsStatic)
					{
						var ptr = (IntPtr)field.GetValue(null);
						if (ptr != IntPtr.Zero)
							return ptr;
					}
				}
				catch
				{
				}
			}
		}
		return IntPtr.Zero;
	}

	private static IEnumerable<string> ExpandNativeFieldInfoNames(string logicalName)
	{
		if (string.IsNullOrWhiteSpace(logicalName))
			yield break;
		yield return "NativeFieldInfoPtr_" + logicalName;
		if (logicalName.StartsWith("<", StringComparison.Ordinal) && logicalName.EndsWith(">k__BackingField", StringComparison.Ordinal))
		{
			var end = logicalName.IndexOf('>', StringComparison.Ordinal);
			if (end > 1)
			{
				var inner = logicalName.Substring(1, end - 1);
				yield return "NativeFieldInfoPtr__" + inner + "_k__BackingField";
				yield return "NativeFieldInfoPtr_" + inner;
			}
		}
		if (logicalName.StartsWith("_", StringComparison.Ordinal) && logicalName.EndsWith("_k__BackingField", StringComparison.Ordinal))
		{
			var inner = logicalName.Substring(1, logicalName.Length - "_k__BackingField".Length - 1);
			if (!string.IsNullOrWhiteSpace(inner))
			{
				yield return "NativeFieldInfoPtr__" + inner + "_k__BackingField";
				yield return "NativeFieldInfoPtr_" + inner;
			}
		}
	}

	private static Type ResolveNativeFieldManagedType(IntPtr fieldPtr)
	{
		if (fieldPtr == IntPtr.Zero)
			return null;
		try
		{
			var getType = typeof(IL2CPP).GetMethod("il2cpp_field_get_type", BindingFlags.Public | BindingFlags.Static);
			var getName = typeof(IL2CPP).GetMethod("il2cpp_type_get_name", BindingFlags.Public | BindingFlags.Static);
			if (getType == null || getName == null)
				return null;
			var typePtr = getType.Invoke(null, new object[] { fieldPtr });
			if (typePtr is not IntPtr nativeType || nativeType == IntPtr.Zero)
				return null;
			var nameResult = getName.Invoke(null, new object[] { nativeType });
			var name = nameResult switch
			{
				string text => text,
				IntPtr ptr when ptr != IntPtr.Zero => Marshal.PtrToStringAnsi(ptr),
				_ => null
			};
			return FindLoadedTypeByName(CleanIl2CppTypeName(name));
		}
		catch
		{
			return null;
		}
	}

	private static string CleanIl2CppTypeName(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return "";
		var value = name.Trim();
		if (value.StartsWith("class ", StringComparison.Ordinal))
			value = value.Substring("class ".Length);
		else if (value.StartsWith("struct ", StringComparison.Ordinal))
			value = value.Substring("struct ".Length);
		return value.TrimEnd('*', '&').Trim();
	}

	private static object CreateIl2CppObjectWrapper(IntPtr valuePtr, Type fieldType)
	{
		if (valuePtr == IntPtr.Zero)
			return null;
		try
		{
			if (fieldType != null && typeof(Il2CppObjectBase).IsAssignableFrom(fieldType))
			{
				foreach (var method in typeof(Il2CppObjectPool).GetMethods(BindingFlags.Public | BindingFlags.Static))
				{
					if (!string.Equals(method.Name, "Get", StringComparison.Ordinal) || !method.IsGenericMethodDefinition)
						continue;
					var parameters = method.GetParameters();
					if (parameters.Length == 1 && parameters[0].ParameterType == typeof(IntPtr))
						return method.MakeGenericMethod(fieldType).Invoke(null, new object[] { valuePtr });
				}
			}
		}
		catch
		{
		}
		try
		{
			return Il2CppObjectPool.Get<Il2CppObjectBase>(valuePtr);
		}
		catch
		{
			return null;
		}
	}

	private static bool TryInvokeNoArgMethod(object runtimeTarget, Type targetType, MethodInfo method, out object result, out string error)
	{
		result = null;
		error = null;
		if (runtimeTarget is Il2CppObjectBase nativeTarget
		    && nativeTarget.Pointer != IntPtr.Zero
		    && targetType != null
		    && typeof(Il2CppObjectBase).IsAssignableFrom(targetType)
		    && TryInvokeNativeNoArgMethod(nativeTarget, targetType, method.Name, method.ReturnType, out result, out error))
			return true;

		try
		{
			result = method.Invoke(runtimeTarget, null);
			error = null;
			return true;
		}
		catch (TargetInvocationException ex)
		{
			var inner = ex.InnerException ?? ex;
			error = inner.GetType().Name + ": " + inner.Message;
			return false;
		}
		catch (Exception ex)
		{
			error = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static unsafe bool TryInvokeNativeNoArgMethod(Il2CppObjectBase nativeTarget, Type targetType, string methodName, Type returnType, out object result, out string error)
	{
		result = null;
		error = null;
		var methodPtr = ResolveNativeMethodPointer(targetType, methodName);
		if (methodPtr == IntPtr.Zero)
		{
			error = "native method pointer not found";
			return false;
		}
		try
		{
			var exception = IntPtr.Zero;
			var resultPtr = IL2CPP.il2cpp_runtime_invoke(methodPtr, IL2CPP.Il2CppObjectBaseToPtrNotNull(nativeTarget), null, ref exception);
			if (exception != IntPtr.Zero)
			{
				error = "native exception pointer 0x" + exception.ToString("x");
				return false;
			}
			if (returnType == typeof(void))
			{
				result = null;
				return true;
			}
			if (resultPtr == IntPtr.Zero)
			{
				result = null;
				return true;
			}
			if (returnType == typeof(string))
			{
				result = IL2CPP.Il2CppStringToManaged(resultPtr);
				return true;
			}
			var wrapped = CreateIl2CppObjectWrapper(resultPtr, returnType);
			result = returnType != null && typeof(Il2CppObjectBase).IsAssignableFrom(returnType) && wrapped != null
				? new NativeTypedObject(wrapped, returnType)
				: wrapped;
			return true;
		}
		catch (Exception ex)
		{
			error = "native invoke failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static IntPtr ResolveNativeMethodPointer(Type ownerType, string logicalName)
	{
		if (ownerType == null || string.IsNullOrWhiteSpace(logicalName))
			return IntPtr.Zero;
		TryInitializeIl2CppType(ownerType);
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		for (var current = ownerType; current != null; current = current.BaseType)
		{
			foreach (var nativeInfoName in ExpandNativeMethodInfoNames(logicalName))
			{
				try
				{
					var field = current.GetField(nativeInfoName, flags);
					if (field != null && field.FieldType == typeof(IntPtr) && field.IsStatic)
					{
						var ptr = (IntPtr)field.GetValue(null);
						if (ptr != IntPtr.Zero)
							return ptr;
					}
				}
				catch
				{
				}
			}
		}
		return IntPtr.Zero;
	}

	private static IEnumerable<string> ExpandNativeMethodInfoNames(string logicalName)
	{
		if (string.IsNullOrWhiteSpace(logicalName))
			yield break;
		if (logicalName.StartsWith("NativeMethodInfoPtr_", StringComparison.Ordinal))
			yield return logicalName;
		else
			yield return "NativeMethodInfoPtr_" + logicalName;
	}

	private static object ReadNativePrimitiveOrString(IntPtr address, Type type)
	{
		var effectiveType = type.IsEnum ? Enum.GetUnderlyingType(type) : type;
		if (effectiveType == typeof(string))
		{
			var valuePtr = Marshal.ReadIntPtr(address);
			return valuePtr == IntPtr.Zero ? "" : IL2CPP.Il2CppStringToManaged(valuePtr);
		}
		if (effectiveType == typeof(bool))
			return Marshal.ReadByte(address) != 0;
		if (effectiveType == typeof(byte))
			return Marshal.ReadByte(address);
		if (effectiveType == typeof(sbyte))
			return unchecked((sbyte)Marshal.ReadByte(address));
		if (effectiveType == typeof(short))
			return Marshal.ReadInt16(address);
		if (effectiveType == typeof(ushort))
			return unchecked((ushort)Marshal.ReadInt16(address));
		if (effectiveType == typeof(int))
			return Marshal.ReadInt32(address);
		if (effectiveType == typeof(uint))
			return unchecked((uint)Marshal.ReadInt32(address));
		if (effectiveType == typeof(long))
			return Marshal.ReadInt64(address);
		if (effectiveType == typeof(ulong))
			return unchecked((ulong)Marshal.ReadInt64(address));
		if (effectiveType == typeof(float))
		{
			var bytes = BitConverter.GetBytes(Marshal.ReadInt32(address));
			return BitConverter.ToSingle(bytes, 0);
		}
		if (effectiveType == typeof(double))
		{
			var bytes = BitConverter.GetBytes(Marshal.ReadInt64(address));
			return BitConverter.ToDouble(bytes, 0);
		}
		return null;
	}

	private static void WriteNativePrimitiveOrString(IntPtr objectPtr, IntPtr address, Type type, object value)
	{
		var effectiveType = type.IsEnum ? Enum.GetUnderlyingType(type) : type;
		if (effectiveType == typeof(string))
		{
			IL2CPP.il2cpp_gc_wbarrier_set_field(objectPtr, address, IL2CPP.ManagedStringToIl2Cpp((string)value));
			return;
		}
		if (effectiveType == typeof(bool))
		{
			Marshal.WriteByte(address, (bool)value ? (byte)1 : (byte)0);
			return;
		}
		if (effectiveType == typeof(byte))
		{
			Marshal.WriteByte(address, (byte)value);
			return;
		}
		if (effectiveType == typeof(sbyte))
		{
			Marshal.WriteByte(address, unchecked((byte)(sbyte)value));
			return;
		}
		if (effectiveType == typeof(short))
		{
			Marshal.WriteInt16(address, (short)value);
			return;
		}
		if (effectiveType == typeof(ushort))
		{
			Marshal.WriteInt16(address, unchecked((short)(ushort)value));
			return;
		}
		if (effectiveType == typeof(int))
		{
			Marshal.WriteInt32(address, (int)value);
			return;
		}
		if (effectiveType == typeof(uint))
		{
			Marshal.WriteInt32(address, unchecked((int)(uint)value));
			return;
		}
		if (effectiveType == typeof(long))
		{
			Marshal.WriteInt64(address, (long)value);
			return;
		}
		if (effectiveType == typeof(ulong))
		{
			Marshal.WriteInt64(address, unchecked((long)(ulong)value));
			return;
		}
		if (effectiveType == typeof(float))
		{
			Marshal.WriteInt32(address, BitConverter.ToInt32(BitConverter.GetBytes((float)value), 0));
			return;
		}
		if (effectiveType == typeof(double))
		{
			Marshal.WriteInt64(address, BitConverter.ToInt64(BitConverter.GetBytes((double)value), 0));
			return;
		}
		throw new NotSupportedException("Unsupported native field type: " + TypeDisplayName(type));
	}

	private static bool TryReadIndexedValue(object owner, int index, out object value, out string note)
	{
		value = null;
		note = null;
		if (owner == null)
		{
			note = "indexed owner is null";
			return false;
		}
		owner = UnwrapNativeTypedObject(owner, out var reflectedType);
		try
		{
			if (owner is Array array)
			{
				if (index >= array.Length)
				{
					note = "array index out of range length=" + array.Length.ToString(System.Globalization.CultureInfo.InvariantCulture);
					return false;
				}
				value = array.GetValue(index);
				note = "array index " + index.ToString(System.Globalization.CultureInfo.InvariantCulture);
				return true;
			}
			if (owner is IList list)
			{
				if (index >= list.Count)
				{
					note = "list index out of range count=" + list.Count.ToString(System.Globalization.CultureInfo.InvariantCulture);
					return false;
				}
				value = list[index];
				note = "list index " + index.ToString(System.Globalization.CultureInfo.InvariantCulture);
				return true;
			}

			var type = reflectedType ?? owner.GetType();
			var length = GetCollectionLength(owner, type);
			if (length >= 0 && index >= length)
			{
				note = "index out of range length=" + length.ToString(System.Globalization.CultureInfo.InvariantCulture);
				return false;
			}
			var getItem = type.GetMethod("get_Item", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance, null, new[] { typeof(int) }, null);
			if (getItem == null)
			{
				note = "no supported indexer";
				return false;
			}
			value = getItem.Invoke(owner, new object[] { index });
			note = "indexer " + index.ToString(System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		catch (TargetInvocationException ex)
		{
			var inner = ex.InnerException ?? ex;
			note = "indexer failed: " + inner.GetType().Name + ": " + inner.Message;
			return false;
		}
		catch (Exception ex)
		{
			note = "index read failed: " + ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static int GetCollectionLength(object owner, Type type)
	{
		if (owner == null || type == null)
			return -1;
		try
		{
			var length = type.GetProperty("Length", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (length != null && length.PropertyType == typeof(int) && length.GetIndexParameters().Length == 0)
				return (int)length.GetValue(owner);
		}
		catch { }
		try
		{
			var count = type.GetProperty("Count", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (count != null && count.PropertyType == typeof(int) && count.GetIndexParameters().Length == 0)
				return (int)count.GetValue(owner);
		}
		catch { }
		return -1;
	}

	private static string MemberPathStepJson(string kind, string segment, object value, int fieldLimit, string note)
	{
		var type = value?.GetType();
		var length = value != null ? GetCollectionLength(value, type) : -1;
		return "{"
		       + "\"kind\":\"" + EscapeJson(kind ?? "") + "\""
		       + ",\"segment\":\"" + EscapeJson(segment ?? "") + "\""
		       + ",\"note\":\"" + EscapeJson(note ?? "") + "\""
		       + ",\"isNull\":" + (value == null ? "true" : "false")
		       + ",\"type\":\"" + EscapeJson(type != null ? type.FullName ?? type.Name ?? "" : "") + "\""
		       + ",\"collectionLength\":" + length.ToString(System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"summary\":" + ObjectSummaryJson(value, fieldLimit)
		       + "}";
	}

	private static string TownUiState(string id)
	{
		return OkResponse(id, "\"townUi\":" + TownUiStateJson(ModActions.GetLiveProbeTownUiState()));
	}

	private static string UnityGameObjectJson(GameObject go, string path, int rendererLimit)
	{
		var renderers = new List<string>();
		if (go)
		{
			var all = go.GetComponentsInChildren<Renderer>(true);
			var max = Math.Min(all.Length, Math.Max(0, rendererLimit));
			for (var i = 0; i < max; i++)
				renderers.Add(UnityRendererJson(all[i]));
		}
		return "{"
			+ "\"name\":\"" + EscapeJson(go ? (go.name ?? "") : "") + "\","
			+ "\"objectId\":" + (go ? go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
			+ "\"path\":\"" + EscapeJson(path ?? "") + "\","
			+ "\"scene\":\"" + EscapeJson(go && go.scene.IsValid() ? go.scene.name : "") + "\","
			+ "\"activeSelf\":" + (go && go.activeSelf ? "true" : "false") + ","
			+ "\"activeInHierarchy\":" + (go && go.activeInHierarchy ? "true" : "false") + ","
			+ "\"layer\":" + (go ? go.layer.ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
			+ "\"localPosition\":" + Vector3Json(go && go.transform ? go.transform.localPosition : Vector3.zero) + ","
			+ "\"worldPosition\":" + Vector3Json(go && go.transform ? go.transform.position : Vector3.zero) + ","
			+ "\"components\":" + ComponentNamesJson(go) + ","
			+ "\"rendererCount\":" + (go ? go.GetComponentsInChildren<Renderer>(true).Length.ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
			+ "\"renderers\":[" + string.Join(",", renderers) + "]"
			+ "}";
	}

	private static string ComponentNamesJson(GameObject go)
	{
		if (!go)
			return "[]";
		var values = new List<string>();
		try
		{
			var components = go.GetComponents<Component>();
			for (var i = 0; i < components.Length && values.Count < 32; i++)
			{
				var component = components[i];
				if (!component)
					continue;
				values.Add("\"" + EscapeJson(ComponentTypeName(component)) + "\"");
			}
		}
		catch (Exception ex)
		{
			values.Add("\"<" + EscapeJson(ex.GetType().Name) + ">\"");
		}
		return "[" + string.Join(",", values) + "]";
	}

	private static string ComponentTypeName(Component component)
	{
		if (!component)
			return "";
		try
		{
			var il2CppType = component.GetIl2CppType();
			if (il2CppType != null)
				return il2CppType.FullName ?? il2CppType.Name ?? "";
		}
		catch { }
		var type = component.GetType();
		return type.FullName ?? type.Name ?? "";
	}

	private static string UnityComponentInstanceJson(Component component, string path, int fieldLimit)
	{
		if (!component || !component.gameObject)
			return "{}";
		var behaviour = component as Behaviour;
		var typeName = ComponentTypeName(component);
		return "{"
			+ "\"name\":\"" + EscapeJson(component.gameObject.name ?? "") + "\","
			+ "\"objectId\":" + component.gameObject.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) + ","
			+ "\"path\":\"" + EscapeJson(path ?? "") + "\","
			+ "\"scene\":\"" + EscapeJson(component.gameObject.scene.IsValid() ? component.gameObject.scene.name : "") + "\","
			+ "\"activeSelf\":" + (component.gameObject.activeSelf ? "true" : "false") + ","
			+ "\"activeInHierarchy\":" + (component.gameObject.activeInHierarchy ? "true" : "false") + ","
			+ "\"componentType\":\"" + EscapeJson(typeName) + "\","
			+ "\"componentEnabled\":" + (behaviour != null ? (behaviour.enabled ? "true" : "false") : "null") + ","
			+ "\"summary\":" + ObjectSummaryJson(component, fieldLimit)
			+ "}";
	}

	private static string UnityUiSurfaceJson(GameObject go, string path)
	{
		var transform = go ? go.transform : null;
		var rect = go ? go.GetComponent<RectTransform>() : null;
		var canvas = go ? go.GetComponentInParent<Canvas>(true) : null;
		return "{"
			+ "\"name\":\"" + EscapeJson(go ? (go.name ?? "") : "") + "\","
			+ "\"objectId\":" + (go ? go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
			+ "\"path\":\"" + EscapeJson(path ?? "") + "\","
			+ "\"scene\":\"" + EscapeJson(go && go.scene.IsValid() ? go.scene.name : "") + "\","
			+ "\"activeSelf\":" + (go && go.activeSelf ? "true" : "false") + ","
			+ "\"activeInHierarchy\":" + (go && go.activeInHierarchy ? "true" : "false") + ","
			+ "\"layer\":" + (go ? go.layer.ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
			+ "\"tag\":\"" + EscapeJson(SafeTag(go)) + "\","
			+ "\"transform\":" + TransformJson(transform, path) + ","
			+ "\"rectTransform\":" + RectTransformJson(rect) + ","
			+ "\"canvas\":" + CanvasJson(canvas) + ","
			+ "\"canvasGroups\":" + CanvasGroupsJson(transform) + ","
			+ "\"graphics\":" + GraphicsJson(go, 32) + ","
			+ "\"layoutClues\":" + LayoutCluesJson(go, 32)
			+ "}";
	}

	private static string TransformJson(Transform transform, string path)
	{
		if (!transform)
			return "{}";
		return "{"
			+ "\"localPosition\":" + Vector3Json(transform.localPosition) + ","
			+ "\"worldPosition\":" + Vector3Json(transform.position) + ","
			+ "\"localScale\":" + Vector3Json(transform.localScale) + ","
			+ "\"siblingIndex\":" + transform.GetSiblingIndex().ToString(System.Globalization.CultureInfo.InvariantCulture) + ","
			+ "\"parentPath\":\"" + EscapeJson(transform.parent ? UnityPath(transform.parent) : "") + "\""
			+ "}";
	}

	private static string RectTransformJson(RectTransform rect)
	{
		if (!rect)
			return "null";
		var r = rect.rect;
		return "{"
			+ "\"anchoredPosition\":" + Vector2Json(rect.anchoredPosition) + ","
			+ "\"sizeDelta\":" + Vector2Json(rect.sizeDelta) + ","
			+ "\"rect\":{\"width\":" + FloatJson(r.width) + ",\"height\":" + FloatJson(r.height) + "},"
			+ "\"anchorMin\":" + Vector2Json(rect.anchorMin) + ","
			+ "\"anchorMax\":" + Vector2Json(rect.anchorMax) + ","
			+ "\"pivot\":" + Vector2Json(rect.pivot) + ","
			+ "\"offsetMin\":" + Vector2Json(rect.offsetMin) + ","
			+ "\"offsetMax\":" + Vector2Json(rect.offsetMax)
			+ "}";
	}

	private static string CanvasJson(Canvas canvas)
	{
		if (!canvas)
			return "null";
		var camera = canvas.worldCamera;
		return "{"
			+ "\"objectId\":" + (canvas.gameObject ? canvas.gameObject.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
			+ "\"path\":\"" + EscapeJson(UnityPath(canvas.transform)) + "\","
			+ "\"enabled\":" + (canvas.enabled ? "true" : "false") + ","
			+ "\"overrideSorting\":" + (canvas.overrideSorting ? "true" : "false") + ","
			+ "\"sortingOrder\":" + canvas.sortingOrder.ToString(System.Globalization.CultureInfo.InvariantCulture) + ","
			+ "\"sortingLayerID\":" + canvas.sortingLayerID.ToString(System.Globalization.CultureInfo.InvariantCulture) + ","
			+ "\"sortingLayerName\":\"" + EscapeJson(SafeSortingLayerName(canvas)) + "\","
			+ "\"renderMode\":\"" + EscapeJson(canvas.renderMode.ToString()) + "\","
			+ "\"worldCamera\":\"" + EscapeJson(camera ? (camera.name ?? "") : "") + "\","
			+ "\"planeDistance\":" + FloatJson(canvas.planeDistance)
			+ "}";
	}

	private static string CanvasGroupsJson(Transform transform)
	{
		var values = new List<string>();
		var effectiveAlpha = 1f;
		var cursor = transform;
		var depth = 0;
		while (cursor && depth < 32)
		{
			var group = cursor.GetComponent<CanvasGroup>();
			if (group)
			{
				effectiveAlpha *= group.alpha;
				values.Add("{"
					+ "\"path\":\"" + EscapeJson(UnityPath(cursor)) + "\","
					+ "\"enabled\":" + (group.enabled ? "true" : "false") + ","
					+ "\"alpha\":" + FloatJson(group.alpha) + ","
					+ "\"interactable\":" + (group.interactable ? "true" : "false") + ","
					+ "\"blocksRaycasts\":" + (group.blocksRaycasts ? "true" : "false") + ","
					+ "\"ignoreParentGroups\":" + (group.ignoreParentGroups ? "true" : "false")
					+ "}");
				if (group.ignoreParentGroups)
					break;
			}
			cursor = cursor.parent;
			depth++;
		}
		return "{\"effectiveAlpha\":" + FloatJson(effectiveAlpha) + ",\"chain\":[" + string.Join(",", values) + "]}";
	}

	private static string GraphicsJson(GameObject go, int limit)
	{
		var values = new List<string>();
		var total = 0;
		if (go)
		{
			var graphics = go.GetComponentsInChildren<Graphic>(true);
			total = graphics.Length;
			var max = Math.Min(graphics.Length, Math.Max(0, limit));
			for (var i = 0; i < max; i++)
				values.Add(GraphicJson(graphics[i]));
		}
		return "{\"total\":" + total.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"truncated\":" + (total > limit ? "true" : "false")
			+ ",\"items\":[" + string.Join(",", values) + "]}";
	}

	private static string GraphicJson(Graphic graphic)
	{
		if (!graphic)
			return "{}";
		var material = SafeGraphicMaterial(graphic);
		var shader = material && material.shader ? material.shader.name : "";
		return "{"
			+ "\"path\":\"" + EscapeJson(UnityPath(graphic.transform)) + "\","
			+ "\"objectId\":" + (graphic.gameObject ? graphic.gameObject.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
			+ "\"type\":\"" + EscapeJson(graphic.GetType().FullName ?? graphic.GetType().Name ?? "") + "\","
			+ "\"enabled\":" + (graphic.enabled ? "true" : "false") + ","
			+ "\"activeSelf\":" + (graphic.gameObject && graphic.gameObject.activeSelf ? "true" : "false") + ","
			+ "\"activeInHierarchy\":" + (graphic.gameObject && graphic.gameObject.activeInHierarchy ? "true" : "false") + ","
			+ "\"raycastTarget\":" + (graphic.raycastTarget ? "true" : "false") + ","
			+ "\"colorAlpha\":" + FloatJson(graphic.color.a) + ","
			+ "\"material\":\"" + EscapeJson(material ? (material.name ?? "") : "") + "\","
			+ "\"shader\":\"" + EscapeJson(shader ?? "") + "\","
			+ "\"asset\":" + GraphicAssetJson(graphic)
			+ "}";
	}

	private static string GraphicAssetJson(Graphic graphic)
	{
		var image = graphic as Image;
		if (image)
		{
			var sprite = image.sprite;
			var texture = sprite ? sprite.texture : null;
			return "{"
				+ "\"kind\":\"sprite\","
				+ "\"name\":\"" + EscapeJson(sprite ? (sprite.name ?? "") : "") + "\","
				+ "\"texture\":\"" + EscapeJson(texture ? (texture.name ?? "") : "") + "\","
				+ "\"width\":" + (texture ? texture.width.ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
				+ "\"height\":" + (texture ? texture.height.ToString(System.Globalization.CultureInfo.InvariantCulture) : "0")
				+ "}";
		}
		var raw = graphic as RawImage;
		if (raw)
		{
			var texture = raw.texture;
			return "{"
				+ "\"kind\":\"texture\","
				+ "\"name\":\"" + EscapeJson(texture ? (texture.name ?? "") : "") + "\","
				+ "\"width\":" + (texture ? texture.width.ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
				+ "\"height\":" + (texture ? texture.height.ToString(System.Globalization.CultureInfo.InvariantCulture) : "0")
				+ "}";
		}
		var text = graphic as TMP_Text;
		if (text)
		{
			return "{"
				+ "\"kind\":\"text\","
				+ "\"font\":\"" + EscapeJson(text.font ? (text.font.name ?? "") : "") + "\","
				+ "\"fontSize\":" + FloatJson(text.fontSize)
				+ "}";
		}
		return "null";
	}

	private static string LayoutCluesJson(GameObject go, int limit)
	{
		var values = new List<string>();
		var total = 0;
		if (go)
		{
			total += AddComponentClues(go.GetComponentsInChildren<CanvasScaler>(true), "CanvasScaler", values, limit);
			total += AddComponentClues(go.GetComponentsInChildren<Mask>(true), "Mask", values, limit);
			total += AddComponentClues(go.GetComponentsInChildren<RectMask2D>(true), "RectMask2D", values, limit);
			total += AddComponentClues(go.GetComponentsInChildren<ScrollRect>(true), "ScrollRect", values, limit);
			total += AddComponentClues(go.GetComponentsInChildren<LayoutGroup>(true), "LayoutGroup", values, limit);
			total += AddComponentClues(go.GetComponentsInChildren<ContentSizeFitter>(true), "ContentSizeFitter", values, limit);
		}
		return "{\"total\":" + total.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"truncated\":" + (total > limit ? "true" : "false")
			+ ",\"items\":[" + string.Join(",", values) + "]}";
	}

	private static int AddComponentClues<T>(IList<T> components, string typeName, List<string> values, int limit) where T : Behaviour
	{
		var total = components == null ? 0 : components.Count;
		if (components == null)
			return 0;
		for (var i = 0; i < components.Count && values.Count < limit; i++)
		{
			var component = components[i];
			if (!component)
				continue;
			values.Add("{\"type\":\"" + EscapeJson(typeName) + "\",\"path\":\"" + EscapeJson(UnityPath(component.transform)) + "\",\"enabled\":" + (component.enabled ? "true" : "false") + "}");
		}
		return total;
	}

	private static string MutationCapabilities(string id)
	{
		return OkResponse(id,
			"\"capabilities\":["
			+ CapabilityJson("set_unity_ui_property", "guarded", "Per-object Unity UI writes for captured objectId handles. Supports GameObject activeSelf, Behaviour enabled, CanvasGroup alpha/interactable/blocksRaycasts/ignoreParentGroups, Graphic raycastTarget/colorAlpha, RectTransform scalar geometry fields, and Canvas sorting/plane fields. Use expectedOldValue when practical.")
			+ "," + CapabilityJson("set_nearest_canvas_property", "guarded", "Canvas-only write from a captured descendant objectId to its nearest parent Canvas in the active scene or additive CityUI while active scene is a native city interior scene. Supports enabled, overrideSorting, sortingOrder, sortingLayerID, sortingLayerName, and planeDistance with optional expectedOldValue.")
			+ "," + CapabilityJson("set_canvas_by_name", "guarded", "Canvas-only write by exact Canvas GameObject name, scoped to active scene or additive CityUI while active scene is a native city interior scene and active hierarchy. Fails on missing or ambiguous matches. Supports enabled, overrideSorting, sortingOrder, sortingLayerID, sortingLayerName, and planeDistance with optional expectedOldValue.")
			+ "," + CapabilityJson("diagnostic_set_ui_property_by_path", "diagnostic", "Exact diagnostic UI write by scene name and transform path. Scene must be the active scene, additive CityUI during a town scene, or an explicitly allowed diagnostic additive scene such as sessionFade. Supports the same UI property set as set_unity_ui_property and should include expectedOldValue.")
			+ "," + CapabilityJson("volatile_set_canvas_property", "volatile", "Last-resort UI Canvas mutation by captured objectId, exact canvasName, or exact transform path. It is still bounded to active scene/additive CityUI town scope, active hierarchy by default, and Canvas properties only: enabled, overrideSorting, sortingOrder, sortingLayerID, sortingLayerName, planeDistance.")
			+ "," + CapabilityJson("volatile_set_ui_sibling", "volatile", "Last-resort UI Transform sibling ordering by captured objectId, exact name, or exact path. Supports setFirst, setLast, and setIndex with optional expectedOldSiblingIndex, scoped to active scene/additive CityUI town scope and active hierarchy by default.")
			+ "," + CapabilityJson("unity_objects_exact", "read_only", "Lightweight exact GameObject lookup by name or transform path. Returns bounded non-UI-heavy GameObject summaries for handles and root existence checks.")
			+ "," + CapabilityJson("component_member_path", "read_only", "Exact read-only field path inspection on a captured GameObject or named component. Supports explicit memberPath segments and optional [index] collection access; properties are disabled unless allowProperties=true.")
			+ "," + CapabilityJson("town_ui_state", "read_only", "Reports cached town UI wrapper/faction/city state and current OfflineUnlockStrongholdTownLayers root counters.")
			+ "," + CapabilityJson("volatile_invoke_exact_noarg_getter", "volatile", "Invokes an exact no-arg getter only when its exact method and expected return type are in the built-in semantic allowlist or live-reloadable volatile_exact_getter_allowlist.json.")
			+ "," + CapabilityJson("volatile_invoke_allowlisted_method", "volatile", "Invokes an exact method only when target type, method name, return type, and primitive argument types match live-reloadable volatile_operation_allowlist.json. Arguments are primitive/string/enum only.")
			+ "," + CapabilityJson("volatile_set_allowlisted_member", "volatile", "Writes an exact field or property only when target type, member name, member kind, and primitive/string/enum member type match live-reloadable volatile_operation_allowlist.json. Supports expectedOldValue and post-write retention checks.")
			+ "," + CapabilityJson("volatile_refresh_town_layers_from_cached_wrapper", "volatile", "One-shot semantic town-layer refresh from the cached wrapper using exact allowlisted ObjCity/ObjCityConfig getters and existing production backdrop/layer sync.")
			+ "," + CapabilityJson("volatile_load_probe_assembly", "volatile", "Loads a compiled probe DLL from live_probe_bridge/probes and invokes an exact static zero-argument or single-string method on Unity's main thread. This is intentionally unsafe and may crash or mutate live state.")
			+ "," + CapabilityJson("source_prepared_law_profiles", "read_only", "Returns the source-prepared custom law profile catalog for all factions, one faction, or one faction/rank. Uses synthetic counterattack/morale observations as design metadata only; no gameplay state is read or mutated.")
			+ "," + CapabilityJson("native_law_state", "guarded", "Reports exact native FractionLaws state for a known custom law and optionally invokes native apply only when native canApply returns true. Does not force raw DataFractionLaw state.")
			+ "," + CapabilityJson("native_law_level_up", "guarded", "Invokes exact native dtj.LevelUp for a custom faction side to grant law points through the same native level/point path used by the law UI. Test-only; does not write raw law rows or law-point fields.")
			+ "," + CapabilityJson("custom_law_candidate_surface_status", "read_only", "Reports startup registration and live counters for candidate custom law mutation surfaces in one bridge call.")
			+ "," + CapabilityJson("battle_unit_status_probe", "read_only", "Reports registered live battle units, exact side/data-side law-owner resolution, active training law state, and exact negative-status query results. Mutation disabled.")
			+ "," + CapabilityJson("direct_state_m3_bfdi_shove", "volatile", "M3 focused live-positive shove: requires homm3_direct_state_m3_bfdi_shove.flag (or MovementPushLivePositiveProven). Finds adjacent registered battle units and runs Homm3DirectStateAdapters.TryMove(MovementPush) through journaled UnitData.bfdi with CapLog dual-readback (helper hex + fieldObjects).")
			+ "," + CapabilityJson("direct_state_m6_bfdi_teleport", "volatile", "M6 focused live-positive teleport relocate: requires homm3_direct_state_m6_bfdi_teleport.flag (or MovementTeleportLivePositiveProven). Finds a registered battle unit and runs Homm3DirectStateAdapters.TryMove(MovementTeleport) onto an empty non-adjacent hex through the same journaled UnitData.bfdi / TryCommitUnitHexMove path with CapLog dual-readback (helper hex + fieldObjects).")
			+ "," + CapabilityJson("battle_unit_apply_status_probe", "guarded", "Diagnostic-only exact native status add against one registered battle unit key, followed by exact status query confirmation. Requires an exact negative status SID; not used by gameplay laws.")
			+ "," + CapabilityJson("construct_instance_snapshot", "guarded", "Constructs one instance via an exact arity-matched constructor (parameterless first; primitive/enum/string args only) and snapshots instance fields. Fail-closed on ambiguous ctors, unsupported args, or invoke failure. Used for Olden C# recovery live_execution oracles.")
			+ "," + CapabilityJson("set_primitive_component_field", "guarded", "Primitive/string/enum field write on a named component attached to a captured objectId. Requires componentType, fieldName, value, and should include expectedOldValue.")
			+ "," + CapabilityJson("invoke_allowlisted_method", "guarded", "Only exact built-in allowlisted calls are available: GameObject.SetActive(bool), Transform.SetAsFirstSibling(), and Transform.SetAsLastSibling().")
			+ "," + CapabilityJson("dispatch_ui_click", "guarded", "Dispatches one Unity pointer click to an exact scoped active UI GameObject by objectId, exact path, or exact name. Intended for diagnostic navigation only; no broad raycast search or fallback target is used.")
			+ "," + CapabilityJson("create_ui_diagnostic_overlay", "guarded", "Creates a non-raycast diagnostic Image child on a RectTransform target to prove bounds/draw order. Remove with remove_ui_diagnostic_overlays.")
			+ "," + CapabilityJson("remove_ui_diagnostic_overlays", "guarded", "Destroys diagnostic overlay children created by this workbench under one captured objectId or all live UI roots when no objectId is supplied.")
			+ "," + CapabilityJson("enable_precompiled_patch", "guarded_unavailable", "Reserved for toggling dormant precompiled patches by id. No patches are registered in this build.")
			+ "," + CapabilityJson("volatile_reflection_invoke", "volatile_unavailable", "Last-resort arbitrary reflection invocation. Intentionally unavailable because IL2CPP methods/getters can crash or mutate native state.")
			+ "," + CapabilityJson("volatile_generated_getter_sweep", "volatile_unavailable", "Last-resort generated getter exploration. Intentionally unavailable because generated getters are not safe diagnostics in this project.")
			+ "," + CapabilityJson("volatile_write_object_reference", "volatile_unavailable", "Last-resort object reference writes. Intentionally unavailable because type-compatible references may violate native lifetime/ownership invariants.")
			+ "," + CapabilityJson("volatile_autopatch_same_shape_methods", "volatile_unavailable", "Last-resort same-shape Harmony patching. Intentionally unavailable because signature shape is not semantic identity.")
			+ "," + CapabilityJson("volatile_global_ui_setter_patch", "volatile_unavailable", "Last-resort global UI setter patching. Intentionally unavailable because global Image/RawImage/material setter hooks have high blast radius.")
			+ "],\"volatilePolicy\":\"Volatile UI commands, exact JSON-allowlisted primitive operations, and explicit hot-loaded probe assemblies are implemented for diagnostic probes. Probe assemblies are arbitrary code and are expected to be crash-risky; use them only when a rebuild/restart would otherwise be the next step.\"");
	}

	private static string SetUnityUiProperty(string id, string requestJson)
	{
		var go = FindGameObjectById(ReadInt(requestJson, "objectId", 0));
		if (!go)
			return ErrorResponse(id, "not_found", "set_unity_ui_property requires a live objectId from a prior Unity query.");
		if (!IsWritableUiSceneObject(go, ReadBool(requestJson, "requireActiveHierarchy", true), out var scopeError))
			return ErrorResponse(id, "out_of_scope", scopeError);
		var componentType = ReadString(requestJson, "componentType") ?? "GameObject";
		var property = ReadString(requestJson, "property");
		var value = ReadString(requestJson, "value");
		var expected = ReadString(requestJson, "expectedOldValue");
		if (string.IsNullOrWhiteSpace(property))
			return ErrorResponse(id, "bad_request", "set_unity_ui_property requires property.");

		if (!TryGetUnityUiProperty(go, componentType, property, out var oldValue))
			return ErrorResponse(id, "unsupported_property", "Unsupported UI property " + componentType + "." + property + ".");
		if (!string.IsNullOrEmpty(expected) && !string.Equals(oldValue, expected, StringComparison.Ordinal))
			return ErrorResponse(id, "expected_old_value_mismatch", "Expected old value '" + expected + "' but found '" + oldValue + "'.");
		if (!TrySetUnityUiProperty(go, componentType, property, value, out var error))
			return ErrorResponse(id, "write_failed", error);
		TryGetUnityUiProperty(go, componentType, property, out var newValue);
		return OkResponse(id,
			"\"objectId\":" + go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"path\":\"" + EscapeJson(UnityPath(go.transform)) + "\""
			+ ",\"componentType\":\"" + EscapeJson(componentType) + "\""
			+ ",\"property\":\"" + EscapeJson(property) + "\""
			+ ",\"oldValue\":\"" + EscapeJson(oldValue) + "\""
			+ ",\"newValue\":\"" + EscapeJson(newValue) + "\"");
	}

	private static string DiagnosticSetUiPropertyByPath(string id, string requestJson)
	{
		var sceneName = ReadString(requestJson, "sceneName") ?? ReadString(requestJson, "scene");
		var path = ReadString(requestJson, "path") ?? ReadString(requestJson, "transformPath");
		if (string.IsNullOrWhiteSpace(sceneName) || string.IsNullOrWhiteSpace(path))
			return ErrorResponse(id, "bad_request", "diagnostic_set_ui_property_by_path requires sceneName and exact path.");
		if (!IsWritableDiagnosticUiScene(sceneName))
			return ErrorResponse(id, "out_of_scope", "Scene '" + sceneName + "' is not in diagnostic UI write scope.");
		if (!TryFindGameObjectBySceneAndPath(sceneName, path, ReadBool(requestJson, "requireActiveHierarchy", true), out var go, out var findError))
			return ErrorResponse(id, "not_found", findError);

		var componentType = ReadString(requestJson, "componentType") ?? "GameObject";
		var property = ReadString(requestJson, "property");
		var value = ReadString(requestJson, "value");
		var expected = ReadString(requestJson, "expectedOldValue");
		if (string.IsNullOrWhiteSpace(property))
			return ErrorResponse(id, "bad_request", "diagnostic_set_ui_property_by_path requires property.");
		if (!TryGetUnityUiProperty(go, componentType, property, out var oldValue))
			return ErrorResponse(id, "unsupported_property", "Unsupported UI property " + componentType + "." + property + ".");
		if (!string.IsNullOrEmpty(expected) && !string.Equals(oldValue, expected, StringComparison.Ordinal))
			return ErrorResponse(id, "expected_old_value_mismatch", "Expected old value '" + expected + "' but found '" + oldValue + "'.");
		if (!TrySetUnityUiProperty(go, componentType, property, value, out var error))
			return ErrorResponse(id, "write_failed", error);
		TryGetUnityUiProperty(go, componentType, property, out var newValue);
		return OkResponse(id,
			"\"objectId\":" + go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"scene\":\"" + EscapeJson(go.scene.IsValid() ? go.scene.name : "") + "\""
			+ ",\"path\":\"" + EscapeJson(UnityPath(go.transform)) + "\""
			+ ",\"componentType\":\"" + EscapeJson(componentType) + "\""
			+ ",\"property\":\"" + EscapeJson(property) + "\""
			+ ",\"oldValue\":\"" + EscapeJson(oldValue) + "\""
			+ ",\"newValue\":\"" + EscapeJson(newValue) + "\"");
	}

	private static string SetNearestCanvasProperty(string id, string requestJson)
	{
		var go = FindGameObjectById(ReadInt(requestJson, "objectId", 0));
		if (!go)
			return ErrorResponse(id, "not_found", "set_nearest_canvas_property requires a live descendant objectId from a prior Unity query.");
		var canvas = go.GetComponentInParent<Canvas>(true);
		if (!canvas)
			return ErrorResponse(id, "not_found", "No parent Canvas found for objectId " + go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) + ".");
		if (!IsWritableActiveSceneCanvas(canvas, out var scopeError))
			return ErrorResponse(id, "out_of_scope", scopeError);
		return SetCanvasPropertyCore(id, canvas, ReadString(requestJson, "property"), ReadString(requestJson, "value"), ReadString(requestJson, "expectedOldValue"), "set_nearest_canvas_property", false);
	}

	private static string SetCanvasByName(string id, string requestJson)
	{
		var canvasName = ReadString(requestJson, "canvasName") ?? ReadString(requestJson, "name");
		if (string.IsNullOrWhiteSpace(canvasName))
			return ErrorResponse(id, "bad_request", "set_canvas_by_name requires canvasName.");
		var matches = new List<Canvas>();
		var activeScene = SceneManager.GetActiveScene();
		var canvases = UnityObject.FindObjectsOfType<Canvas>(true);
		for (var i = 0; i < canvases.Length; i++)
		{
			var canvas = canvases[i];
			if (!canvas || !canvas.gameObject)
				continue;
			if (!string.Equals(canvas.gameObject.name ?? "", canvasName, StringComparison.Ordinal))
				continue;
			if (!IsWritableCanvasScene(canvas.gameObject.scene, activeScene) || !canvas.gameObject.activeInHierarchy)
				continue;
			matches.Add(canvas);
		}
		if (matches.Count == 0)
			return ErrorResponse(id, "not_found", "No active-scene, active-hierarchy Canvas with exact name '" + canvasName + "'.");
		if (matches.Count > 1)
			return ErrorResponse(id, "ambiguous", "Multiple active-scene, active-hierarchy Canvases have exact name '" + canvasName + "'. Use unity_ui_surfaces and set_nearest_canvas_property instead.");
		return SetCanvasPropertyCore(id, matches[0], ReadString(requestJson, "property"), ReadString(requestJson, "value"), ReadString(requestJson, "expectedOldValue"), "set_canvas_by_name", false);
	}

	private static string VolatileSetCanvasProperty(string id, string requestJson)
	{
		var reason = ReadString(requestJson, "reason");
		if (string.IsNullOrWhiteSpace(reason))
			return ErrorResponse(id, "bad_request", "volatile_set_canvas_property requires reason.");
		if (!TryResolveCanvasTarget(requestJson, out var canvas, out var error))
			return ErrorResponse(id, "target_not_found", error);
		if (!IsWritableActiveSceneCanvas(canvas, out var scopeError))
			return ErrorResponse(id, "out_of_scope", scopeError);
		return SetCanvasPropertyCore(id, canvas, ReadString(requestJson, "property"), ReadString(requestJson, "value"), ReadString(requestJson, "expectedOldValue"), "volatile_set_canvas_property", true, reason);
	}

	private static string VolatileSetUiSibling(string id, string requestJson)
	{
		var reason = ReadString(requestJson, "reason");
		if (string.IsNullOrWhiteSpace(reason))
			return ErrorResponse(id, "bad_request", "volatile_set_ui_sibling requires reason.");
		if (!TryResolveGameObjectTarget(requestJson, out var go, out var error))
			return ErrorResponse(id, "target_not_found", error);
		if (!go.transform)
			return ErrorResponse(id, "not_transform", "Target has no Transform.");
		if (!IsWritableUiSceneObject(go, ReadBool(requestJson, "requireActiveHierarchy", true), out var scopeError))
			return ErrorResponse(id, "out_of_scope", scopeError);

		var operation = ReadString(requestJson, "operation") ?? ReadString(requestJson, "methodName");
		var oldIndex = go.transform.GetSiblingIndex();
		var expected = ReadString(requestJson, "expectedOldSiblingIndex") ?? ReadString(requestJson, "expectedOldValue");
		if (!string.IsNullOrEmpty(expected) && !string.Equals(oldIndex.ToString(System.Globalization.CultureInfo.InvariantCulture), expected, StringComparison.Ordinal))
			return ErrorResponse(id, "expected_old_value_mismatch", "Expected old sibling index '" + expected + "' but found '" + oldIndex.ToString(System.Globalization.CultureInfo.InvariantCulture) + "'.");

		if (string.Equals(operation, "setFirst", StringComparison.OrdinalIgnoreCase)
		    || string.Equals(operation, "Transform.SetAsFirstSibling", StringComparison.OrdinalIgnoreCase))
		{
			go.transform.SetAsFirstSibling();
		}
		else if (string.Equals(operation, "setLast", StringComparison.OrdinalIgnoreCase)
		         || string.Equals(operation, "Transform.SetAsLastSibling", StringComparison.OrdinalIgnoreCase))
		{
			go.transform.SetAsLastSibling();
		}
		else if (string.Equals(operation, "setIndex", StringComparison.OrdinalIgnoreCase))
		{
			var parent = go.transform.parent;
			if (!parent)
				return ErrorResponse(id, "no_parent", "setIndex requires a parent Transform.");
			var index = ReadInt(requestJson, "index", oldIndex);
			index = Math.Max(0, Math.Min(index, parent.childCount - 1));
			go.transform.SetSiblingIndex(index);
		}
		else
		{
			return ErrorResponse(id, "unsupported_operation", "volatile_set_ui_sibling supports only setFirst, setLast, and setIndex.");
		}

		var newIndex = go.transform.GetSiblingIndex();
		return OkResponse(id,
			"\"command\":\"volatile_set_ui_sibling\""
			+ ",\"volatile\":true"
			+ ",\"objectId\":" + go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"name\":\"" + EscapeJson(go.name ?? "") + "\""
			+ ",\"path\":\"" + EscapeJson(UnityPath(go.transform)) + "\""
			+ ",\"scene\":\"" + EscapeJson(go.scene.IsValid() ? go.scene.name : "") + "\""
			+ ",\"activeScene\":\"" + EscapeJson(SceneManager.GetActiveScene().name ?? "") + "\""
			+ ",\"reason\":\"" + EscapeJson(reason) + "\""
			+ ",\"operation\":\"" + EscapeJson(operation ?? "") + "\""
			+ ",\"oldValue\":\"" + oldIndex.ToString(System.Globalization.CultureInfo.InvariantCulture) + "\""
			+ ",\"newValue\":\"" + newIndex.ToString(System.Globalization.CultureInfo.InvariantCulture) + "\"");
	}

	private static string VolatileInvokeExactNoArgGetter(string id, string requestJson)
	{
		var reason = ReadString(requestJson, "reason");
		if (string.IsNullOrWhiteSpace(reason))
			return ErrorResponse(id, "bad_request", "volatile_invoke_exact_noarg_getter requires reason.");
		var methodName = ReadString(requestJson, "methodName");
		var expectedReturnType = ReadString(requestJson, "expectedReturnTypeFullName");
		if (string.IsNullOrWhiteSpace(methodName) || string.IsNullOrWhiteSpace(expectedReturnType))
			return ErrorResponse(id, "bad_request", "volatile_invoke_exact_noarg_getter requires methodName and expectedReturnTypeFullName.");
		if (!TryResolveGetterTarget(requestJson, out var target, out var targetLabel, out var targetError))
			return ErrorResponse(id, "target_not_found", targetError);
		if (target == null)
			return ErrorResponse(id, "target_not_found", "Resolved getter target is null.");
		var runtimeTarget = UnwrapNativeTypedObject(target, out var reflectedTargetType);
		var targetType = reflectedTargetType ?? runtimeTarget.GetType();
		if (!IsAllowlistedExactNoArgGetter(targetType, methodName, expectedReturnType))
			return ErrorResponse(id, "not_allowlisted", "Getter is not in the built-in or reloadable exact getter allowlist: " + methodName + " -> " + expectedReturnType + ".");

		var method = targetType.GetMethod(methodName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance, null, Type.EmptyTypes, null);
		if (method == null)
			return ErrorResponse(id, "method_not_found", "Target type does not declare exact no-arg method " + methodName + ".");
		var actualReturnType = method.ReturnType.FullName ?? method.ReturnType.Name ?? "";
		if (!string.Equals(actualReturnType, expectedReturnType, StringComparison.Ordinal))
			return ErrorResponse(id, "return_type_mismatch", "Getter return type was " + actualReturnType + ".");

		if (!TryInvokeNoArgMethod(runtimeTarget, targetType, method, out var result, out var invokeError))
			return ErrorResponse(id, "invoke_failed", invokeError);

		return OkResponse(id,
			"\"command\":\"volatile_invoke_exact_noarg_getter\""
			+ ",\"volatile\":true"
			+ ",\"reason\":\"" + EscapeJson(reason) + "\""
			+ ",\"target\":\"" + EscapeJson(targetLabel) + "\""
			+ ",\"targetType\":\"" + EscapeJson(targetType.FullName ?? targetType.Name ?? "") + "\""
			+ ",\"methodName\":\"" + EscapeJson(methodName) + "\""
			+ ",\"returnType\":\"" + EscapeJson(actualReturnType) + "\""
			+ ",\"isNull\":" + (result == null ? "true" : "false")
			+ ",\"summary\":" + ObjectSummaryJson(result, 24));
	}

	private static string VolatileInvokeExactGetterChain(string id, string requestJson)
	{
		var reason = ReadString(requestJson, "reason");
		if (string.IsNullOrWhiteSpace(reason))
			return ErrorResponse(id, "bad_request", "volatile_invoke_exact_getter_chain requires reason.");
		var methodNames = SplitGetterChain(ReadString(requestJson, "methodNames") ?? ReadString(requestJson, "getterChain"));
		var expectedReturnTypes = SplitGetterChain(ReadString(requestJson, "expectedReturnTypeFullNames") ?? ReadString(requestJson, "returnTypes"));
		if (methodNames.Length == 0 || expectedReturnTypes.Length == 0)
			return ErrorResponse(id, "bad_request", "volatile_invoke_exact_getter_chain requires methodNames and expectedReturnTypeFullNames separated by '|'.");
		if (methodNames.Length != expectedReturnTypes.Length)
			return ErrorResponse(id, "bad_request", "methodNames and expectedReturnTypeFullNames must have the same number of entries.");
		if (methodNames.Length > 16)
			return ErrorResponse(id, "chain_too_long", "Getter chains are limited to 16 hop(s).");
		if (!TryResolveGetterTarget(requestJson, out var current, out var targetLabel, out var targetError))
			return ErrorResponse(id, "target_not_found", targetError);
		if (current == null)
			return ErrorResponse(id, "target_not_found", "Resolved getter-chain target is null.");

		var steps = new List<string>();
		for (var i = 0; i < methodNames.Length; i++)
		{
			var methodName = methodNames[i];
			var expectedReturnType = expectedReturnTypes[i];
			if (string.IsNullOrWhiteSpace(methodName) || string.IsNullOrWhiteSpace(expectedReturnType))
				return ErrorResponse(id, "bad_request", "Getter chain contains an empty method or expected return type at index " + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + ".");
			var runtimeCurrent = UnwrapNativeTypedObject(current, out var reflectedCurrentType);
			var targetType = reflectedCurrentType ?? runtimeCurrent.GetType();
			if (!IsAllowlistedExactNoArgGetter(targetType, methodName, expectedReturnType))
				return ErrorResponse(id, "not_allowlisted", "Getter chain hop " + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + " is not in the built-in or reloadable exact getter allowlist: " + (targetType.FullName ?? targetType.Name ?? "") + "." + methodName + " -> " + expectedReturnType + ".");

			var method = targetType.GetMethod(methodName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance, null, Type.EmptyTypes, null);
			if (method == null)
				return ErrorResponse(id, "method_not_found", "Getter chain hop " + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + " target type does not declare exact no-arg method " + methodName + ".");
			var actualReturnType = method.ReturnType.FullName ?? method.ReturnType.Name ?? "";
			if (!string.Equals(actualReturnType, expectedReturnType, StringComparison.Ordinal))
				return ErrorResponse(id, "return_type_mismatch", "Getter chain hop " + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + " return type was " + actualReturnType + ".");

			if (!TryInvokeNoArgMethod(runtimeCurrent, targetType, method, out var result, out var invokeError))
				return ErrorResponse(id, "invoke_failed", "Getter chain hop " + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + " failed: " + invokeError);

			steps.Add("{\"index\":" + i.ToString(System.Globalization.CultureInfo.InvariantCulture)
			          + ",\"targetType\":\"" + EscapeJson(targetType.FullName ?? targetType.Name ?? "") + "\""
			          + ",\"methodName\":\"" + EscapeJson(methodName) + "\""
			          + ",\"returnType\":\"" + EscapeJson(actualReturnType) + "\""
			          + ",\"isNull\":" + (result == null ? "true" : "false")
			          + ",\"summary\":" + ObjectSummaryJson(result, 8)
			          + "}");
			current = result;
			targetLabel += "." + methodName + "()";
			if (current == null && i < methodNames.Length - 1)
				return ErrorResponse(id, "null_hop", "Getter chain hop " + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + " returned null before the chain ended.");
		}

		var finalFieldLimit = Math.Max(0, Math.Min(ReadInt(requestJson, "fieldLimit", 48), 96));
		return OkResponse(id,
			"\"command\":\"volatile_invoke_exact_getter_chain\""
			+ ",\"volatile\":true"
			+ ",\"reason\":\"" + EscapeJson(reason) + "\""
			+ ",\"target\":\"" + EscapeJson(targetLabel) + "\""
			+ ",\"hopCount\":" + methodNames.Length.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"steps\":[" + string.Join(",", steps) + "]"
			+ ",\"isNull\":" + (current == null ? "true" : "false")
			+ ",\"summary\":" + ObjectSummaryJson(current, finalFieldLimit));
	}

	private static string VolatileInvokeAllowlistedMethod(string id, string requestJson)
	{
		var reason = ReadString(requestJson, "reason");
		if (string.IsNullOrWhiteSpace(reason))
			return ErrorResponse(id, "bad_request", "volatile_invoke_allowlisted_method requires reason.");
		var methodName = ReadString(requestJson, "methodName");
		var expectedReturnType = ReadString(requestJson, "expectedReturnTypeFullName") ?? "System.Void";
		if (string.IsNullOrWhiteSpace(methodName))
			return ErrorResponse(id, "bad_request", "volatile_invoke_allowlisted_method requires methodName.");
		if (!TryResolveGetterTarget(requestJson, out var target, out var targetLabel, out var targetError))
			return ErrorResponse(id, "target_not_found", targetError);
		if (target == null)
			return ErrorResponse(id, "target_not_found", "Resolved method target is null.");

		var argCount = Math.Max(0, Math.Min(ReadInt(requestJson, "argCount", 0), 4));
		var parameterTypes = new Type[argCount];
		var parameterTypeNames = new string[argCount];
		var args = new object[argCount];
		for (var i = 0; i < argCount; i++)
		{
			var typeName = ReadString(requestJson, "arg" + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + "TypeFullName");
			if (string.IsNullOrWhiteSpace(typeName))
				return ErrorResponse(id, "bad_request", "arg" + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + "TypeFullName is required when argCount includes that argument.");
			var type = ResolveSimpleType(typeName);
			if (type == null)
				return ErrorResponse(id, "bad_arg_type", "Unsupported or unresolved primitive argument type: " + typeName + ".");
			if (!IsSupportedPrimitiveFieldType(type))
				return ErrorResponse(id, "unsupported_arg_type", "Only bool, numeric, string, and enum arguments are supported.");
			if (!TryConvertPrimitive(ReadString(requestJson, "arg" + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + "Value"), type, out var converted, out var convertError))
				return ErrorResponse(id, "bad_arg_value", convertError);
			parameterTypes[i] = type;
			parameterTypeNames[i] = type.FullName ?? type.Name ?? "";
			args[i] = converted;
		}

		var runtimeTarget = UnwrapNativeTypedObject(target, out var reflectedTargetType);
		var targetType = reflectedTargetType ?? runtimeTarget.GetType();
		if (!IsAllowlistedVolatileMethod(targetType, methodName, expectedReturnType, parameterTypeNames))
			return ErrorResponse(id, "not_allowlisted", "Method is not in volatile_operation_allowlist.json with the requested target/return/parameter signature.");
		var method = targetType.GetMethod(methodName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance, null, parameterTypes, null);
		if (method == null)
			return ErrorResponse(id, "method_not_found", "Target type does not declare exact method " + methodName + " with requested primitive parameter types.");
		var actualReturnType = method.ReturnType.FullName ?? method.ReturnType.Name ?? "";
		if (!string.Equals(actualReturnType, expectedReturnType, StringComparison.Ordinal))
			return ErrorResponse(id, "return_type_mismatch", "Method return type was " + actualReturnType + ".");

		object result;
		if (argCount == 0)
		{
			if (!TryInvokeNoArgMethod(runtimeTarget, targetType, method, out result, out var invokeError))
				return ErrorResponse(id, "invoke_failed", invokeError);
		}
		else
		{
			try
			{
				result = method.Invoke(runtimeTarget, args);
			}
			catch (TargetInvocationException ex)
			{
				var inner = ex.InnerException ?? ex;
				return ErrorResponse(id, "invoke_failed", inner.GetType().Name + ": " + inner.Message);
			}
			catch (Exception ex)
			{
				return ErrorResponse(id, "invoke_failed", ex.GetType().Name + ": " + ex.Message);
			}
		}

		return OkResponse(id,
			"\"command\":\"volatile_invoke_allowlisted_method\""
			+ ",\"volatile\":true"
			+ ",\"reason\":\"" + EscapeJson(reason) + "\""
			+ ",\"target\":\"" + EscapeJson(targetLabel) + "\""
			+ ",\"targetType\":\"" + EscapeJson(targetType.FullName ?? targetType.Name ?? "") + "\""
			+ ",\"methodName\":\"" + EscapeJson(methodName) + "\""
			+ ",\"returnType\":\"" + EscapeJson(actualReturnType) + "\""
			+ ",\"parameterTypeFullNames\":" + StringArrayJson(parameterTypeNames)
			+ ",\"isNull\":" + (result == null ? "true" : "false")
			+ ",\"summary\":" + ObjectSummaryJson(result, 16));
	}

	private static string VolatileSetAllowlistedMember(string id, string requestJson)
	{
		var reason = ReadString(requestJson, "reason");
		if (string.IsNullOrWhiteSpace(reason))
			return ErrorResponse(id, "bad_request", "volatile_set_allowlisted_member requires reason.");
		var memberPath = ReadString(requestJson, "memberPath") ?? ReadString(requestJson, "pathMembers");
		var memberName = ReadString(requestJson, "memberName") ?? ReadString(requestJson, "fieldName") ?? ReadString(requestJson, "propertyName");
		if (string.IsNullOrWhiteSpace(memberName) && !string.IsNullOrWhiteSpace(memberPath))
		{
			var parts = memberPath.Split(new[] { '.' }, StringSplitOptions.RemoveEmptyEntries);
			if (parts.Length > 0)
				memberName = parts[parts.Length - 1].Trim();
		}
		var memberKind = ReadString(requestJson, "memberKind") ?? (string.IsNullOrWhiteSpace(ReadString(requestJson, "propertyName")) ? "field" : "property");
		var expectedTypeName = ReadString(requestJson, "expectedMemberTypeFullName");
		if (string.IsNullOrWhiteSpace(memberName))
			return ErrorResponse(id, "bad_request", "volatile_set_allowlisted_member requires memberName or memberPath.");
		if (!string.Equals(memberKind, "field", StringComparison.OrdinalIgnoreCase)
		    && !string.Equals(memberKind, "property", StringComparison.OrdinalIgnoreCase))
			return ErrorResponse(id, "bad_request", "memberKind must be field or property.");
		if (!TryResolveGetterTarget(requestJson, out var target, out var targetLabel, out var targetError))
			return ErrorResponse(id, "target_not_found", targetError);
		if (target == null)
			return ErrorResponse(id, "target_not_found", "Resolved member target is null.");
		if (!string.IsNullOrWhiteSpace(memberPath))
		{
			var segments = memberPath.Split(new[] { '.' }, StringSplitOptions.RemoveEmptyEntries);
			if (segments.Length > 1)
			{
				var maxSegments = Math.Max(1, Math.Min(ReadInt(requestJson, "maxSegments", 16), 32));
				if (segments.Length > maxSegments)
					return ErrorResponse(id, "path_too_long", "memberPath exceeds maxSegments.");
				var allowPropertiesForPath = ReadBool(requestJson, "allowProperties", false);
				var current = target;
				for (var i = 0; i < segments.Length - 1; i++)
				{
					var segment = segments[i].Trim();
					if (!TryReadExactMemberSegment(current, segment, allowPropertiesForPath, out var next, out var note))
						return ErrorResponse(id, "member_not_found", "Failed at parent segment '" + segment + "': " + note);
					if (next == null)
						return ErrorResponse(id, "target_not_found", "Parent segment '" + segment + "' resolved to null.");
					current = next;
				}
				target = current;
				targetLabel += "." + string.Join(".", segments, 0, segments.Length - 1);
				memberName = segments[segments.Length - 1].Trim();
			}
		}

		var runtimeTarget = UnwrapNativeTypedObject(target, out var reflectedTargetType);
		var targetType = reflectedTargetType ?? runtimeTarget.GetType();
		Type memberType;
		object oldRaw;
		Action<object> setter;
		if (string.Equals(memberKind, "field", StringComparison.OrdinalIgnoreCase))
		{
			var field = targetType.GetField(memberName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (field != null)
			{
				memberType = field.FieldType;
				oldRaw = field.GetValue(runtimeTarget);
				setter = value => field.SetValue(runtimeTarget, value);
			}
			else
			{
				memberType = ResolveNativeWriteMemberType(targetType, memberKind, memberName, expectedTypeName);
				if (memberType == null)
					return ErrorResponse(id, "member_not_found", "Field not found on target and no allowlisted native member type was available: " + memberName + ".");
				if (!TryReadNativeField(runtimeTarget, targetType, memberName, memberType, out oldRaw, out var readNote))
					return ErrorResponse(id, "member_not_found", "Native field not found/readable on target: " + memberName + " (" + readNote + ").");
				setter = value =>
				{
					if (!TryWriteNativeField(runtimeTarget, targetType, memberName, memberType, value, out var writeNote))
						throw new InvalidOperationException(writeNote);
				};
			}
		}
		else
		{
			var property = targetType.GetProperty(memberName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (property == null)
				return ErrorResponse(id, "member_not_found", "Property not found on target: " + memberName + ".");
			if (!property.CanRead || !property.CanWrite)
				return ErrorResponse(id, "unsupported_member", "Property must be readable and writable for compare-and-swap and retention checks.");
			memberType = property.PropertyType;
			oldRaw = property.GetValue(runtimeTarget, null);
			setter = value => property.SetValue(runtimeTarget, value, null);
		}

		var actualTypeName = memberType.FullName ?? memberType.Name ?? "";
		if (!string.IsNullOrWhiteSpace(expectedTypeName) && !string.Equals(actualTypeName, expectedTypeName, StringComparison.Ordinal))
			return ErrorResponse(id, "member_type_mismatch", "Member type was " + actualTypeName + ".");
		if (!IsSupportedPrimitiveFieldType(memberType))
			return ErrorResponse(id, "unsupported_member_type", "Only bool, numeric, string, and enum members are supported.");
		if (!IsAllowlistedVolatileMember(targetType, memberKind, memberName, actualTypeName))
			return ErrorResponse(id, "not_allowlisted", "Member is not in volatile_operation_allowlist.json with the requested target/member signature.");

		var oldValue = PrimitiveValueString(oldRaw);
		var expected = ReadString(requestJson, "expectedOldValue");
		if (!string.IsNullOrEmpty(expected) && !string.Equals(oldValue, expected, StringComparison.Ordinal))
			return ErrorResponse(id, "expected_old_value_mismatch", "Expected old value '" + expected + "' but found '" + oldValue + "'.");
		if (!TryConvertPrimitive(ReadString(requestJson, "value"), memberType, out var converted, out var error))
			return ErrorResponse(id, "bad_value", error);
		var requestedValue = PrimitiveValueString(converted);
		try
		{
			setter(converted);
		}
		catch (TargetInvocationException ex)
		{
			var inner = ex.InnerException ?? ex;
			return ErrorResponse(id, "write_failed", inner.GetType().Name + ": " + inner.Message);
		}
		catch (Exception ex)
		{
			return ErrorResponse(id, "write_failed", ex.GetType().Name + ": " + ex.Message);
		}

		object newRaw;
		if (string.Equals(memberKind, "field", StringComparison.OrdinalIgnoreCase))
		{
			var field = targetType.GetField(memberName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
			if (field != null)
				newRaw = field.GetValue(runtimeTarget);
			else if (!TryReadNativeField(runtimeTarget, targetType, memberName, memberType, out newRaw, out var readNote))
				return ErrorResponse(id, "readback_failed", "Native field readback failed: " + readNote);
		}
		else
			newRaw = targetType.GetProperty(memberName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance)?.GetValue(runtimeTarget, null);
		var newValue = PrimitiveValueString(newRaw);
		if (!string.Equals(newValue, requestedValue, StringComparison.Ordinal))
			return ErrorResponse(id, "write_not_retained", "Member write did not retain requested value '" + requestedValue + "'; current value is '" + newValue + "'.");

		return OkResponse(id,
			"\"command\":\"volatile_set_allowlisted_member\""
			+ ",\"volatile\":true"
			+ ",\"reason\":\"" + EscapeJson(reason) + "\""
			+ ",\"target\":\"" + EscapeJson(targetLabel) + "\""
			+ ",\"targetType\":\"" + EscapeJson(targetType.FullName ?? targetType.Name ?? "") + "\""
			+ ",\"memberKind\":\"" + EscapeJson(memberKind) + "\""
			+ ",\"memberName\":\"" + EscapeJson(memberName) + "\""
			+ ",\"memberType\":\"" + EscapeJson(actualTypeName) + "\""
			+ ",\"oldValue\":\"" + EscapeJson(oldValue) + "\""
			+ ",\"newValue\":\"" + EscapeJson(newValue) + "\"");
	}

	private static string VolatileRefreshTownLayersFromCachedWrapper(string id, string requestJson)
	{
		var reason = ReadString(requestJson, "reason");
		if (string.IsNullOrWhiteSpace(reason))
			return ErrorResponse(id, "bad_request", "volatile_refresh_town_layers_from_cached_wrapper requires reason.");
		var result = ModActions.LiveProbeRefreshTownLayersFromCachedWrapper();
		return OkResponse(id,
			"\"command\":\"volatile_refresh_town_layers_from_cached_wrapper\""
			+ ",\"volatile\":true"
			+ ",\"reason\":\"" + EscapeJson(reason) + "\""
			+ ",\"result\":" + TownLayerRefreshResultJson(result));
	}

	private static string VolatileLoadProbeAssembly(string id, string requestJson)
	{
		var reason = ReadString(requestJson, "reason");
		if (string.IsNullOrWhiteSpace(reason))
			return ErrorResponse(id, "bad_request", "volatile_load_probe_assembly requires reason.");
		var assemblyPath = ReadString(requestJson, "assemblyPath");
		var typeName = ReadString(requestJson, "typeName");
		var methodName = ReadString(requestJson, "methodName") ?? "Run";
		if (string.IsNullOrWhiteSpace(assemblyPath) || string.IsNullOrWhiteSpace(typeName))
			return ErrorResponse(id, "bad_request", "volatile_load_probe_assembly requires assemblyPath and typeName.");
		if (!TryNormalizeProbeAssemblyPath(assemblyPath, out var normalizedPath, out var pathError))
			return ErrorResponse(id, "out_of_scope", pathError);
		if (!File.Exists(normalizedPath))
			return ErrorResponse(id, "not_found", "Probe assembly not found: " + normalizedPath);

		try
		{
			var bytes = File.ReadAllBytes(normalizedPath);
			var assembly = Assembly.Load(bytes);
			var type = assembly.GetType(typeName, throwOnError: false);
			if (type == null)
				return ErrorResponse(id, "type_not_found", "Probe type not found: " + typeName);
			var method = FindVolatileProbeMethod(type, methodName);
			if (method == null)
				return ErrorResponse(id, "method_not_found", "Probe method must be static and accept either no arguments or one string argument: " + methodName);
			_log?.LogWarning(GrepKey + " volatile probe assembly invoking " + type.FullName + "." + method.Name + " reason='" + reason + "'.");
			var ps = method.GetParameters();
			var result = method.Invoke(null, ps.Length == 0 ? null : new object[] { requestJson });
			return OkResponse(id,
				"\"command\":\"volatile_load_probe_assembly\""
				+ ",\"volatile\":true"
				+ ",\"assemblyPath\":\"" + EscapeJson(normalizedPath) + "\""
				+ ",\"typeName\":\"" + EscapeJson(type.FullName ?? type.Name ?? "") + "\""
				+ ",\"methodName\":\"" + EscapeJson(method.Name) + "\""
				+ "," + ProbeResultJson(result));
		}
		catch (TargetInvocationException ex)
		{
			var inner = ex.InnerException ?? ex;
			return ErrorResponse(id, "probe_exception", inner.GetType().Name + ": " + inner.Message + "\n" + inner.StackTrace);
		}
		catch (Exception ex)
		{
			return ErrorResponse(id, "probe_load_failed", ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static bool TryNormalizeProbeAssemblyPath(string assemblyPath, out string normalizedPath, out string error)
	{
		normalizedPath = null;
		error = null;
		try
		{
			var probeRoot = Path.GetFullPath(Path.Combine(BridgeDirectory ?? "", ProbeAssemblyDirectoryName));
			var candidate = Path.IsPathRooted(assemblyPath)
				? Path.GetFullPath(assemblyPath)
				: Path.GetFullPath(Path.Combine(probeRoot, assemblyPath));
			var rootWithSeparator = probeRoot.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
			if (!candidate.StartsWith(rootWithSeparator, StringComparison.OrdinalIgnoreCase)
			    && !string.Equals(candidate, probeRoot, StringComparison.OrdinalIgnoreCase))
			{
				error = "Probe assembly must live under " + probeRoot + ".";
				return false;
			}
			if (!string.Equals(Path.GetExtension(candidate), ".dll", StringComparison.OrdinalIgnoreCase))
			{
				error = "Probe assembly must be a .dll.";
				return false;
			}
			normalizedPath = candidate;
			return true;
		}
		catch (Exception ex)
		{
			error = ex.Message;
			return false;
		}
	}

	private static MethodInfo FindVolatileProbeMethod(Type type, string methodName)
	{
		if (type == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		foreach (var method in type.GetMethods(flags))
		{
			if (!string.Equals(method.Name, methodName, StringComparison.Ordinal))
				continue;
			var ps = method.GetParameters();
			if (ps.Length == 0 || (ps.Length == 1 && ps[0].ParameterType == typeof(string)))
				return method;
		}
		return null;
	}

	private static string ProbeResultJson(object result)
	{
		if (result is string text)
		{
			var truncated = false;
			if (text.Length > MaxProbeResultChars)
			{
				text = text.Substring(0, MaxProbeResultChars);
				truncated = true;
			}
			return "\"resultText\":\"" + EscapeJson(text) + "\""
			       + ",\"resultTruncated\":" + (truncated ? "true" : "false")
			       + ",\"result\":" + ObjectSummaryJson(result, 0);
		}
		return "\"result\":" + ObjectSummaryJson(result, 32);
	}

	private static string SetCanvasPropertyCore(string id, Canvas canvas, string property, string value, string expected, string commandName, bool isVolatile, string reason = null)
	{
		if (!canvas)
			return ErrorResponse(id, "not_found", "Canvas not found.");
		if (!IsWritableCanvasProperty(property))
			return ErrorResponse(id, "unsupported_property", commandName + " supports only enabled, overrideSorting, sortingOrder, sortingLayerID, sortingLayerName, and planeDistance.");
		if (!TryGetCanvasProperty(canvas, property, out var oldValue))
			return ErrorResponse(id, "unsupported_property", "Unsupported Canvas property: " + (property ?? ""));
		if (!string.IsNullOrEmpty(expected) && !string.Equals(oldValue, expected, StringComparison.Ordinal))
			return ErrorResponse(id, "expected_old_value_mismatch", "Expected old value '" + expected + "' but found '" + oldValue + "'.");
		if (!TryNormalizeCanvasRequestedValue(canvas, property, value, out var requestedValue, out var valueError))
			return ErrorResponse(id, "bad_value", valueError);
		if (!TrySetCanvasProperty(canvas, property, value))
			return ErrorResponse(id, "write_failed", "Failed to write Canvas property: " + (property ?? ""));
		TryGetCanvasProperty(canvas, property, out var newValue);
		if (!string.Equals(newValue, requestedValue, StringComparison.Ordinal))
			return ErrorResponse(id, "write_not_retained", "Canvas property write did not retain requested value '" + requestedValue + "'; current value is '" + newValue + "'.");
		return OkResponse(id,
			"\"command\":\"" + EscapeJson(commandName) + "\""
			+ ",\"volatile\":" + (isVolatile ? "true" : "false")
			+ ",\"canvasObjectId\":" + (canvas.gameObject ? canvas.gameObject.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) : "0")
			+ ",\"canvasName\":\"" + EscapeJson(canvas.gameObject ? (canvas.gameObject.name ?? "") : "") + "\""
			+ ",\"canvasPath\":\"" + EscapeJson(UnityPath(canvas.transform)) + "\""
			+ ",\"targetScene\":\"" + EscapeJson(canvas.gameObject && canvas.gameObject.scene.IsValid() ? canvas.gameObject.scene.name : "") + "\""
			+ ",\"activeScene\":\"" + EscapeJson(SceneManager.GetActiveScene().name ?? "") + "\""
			+ ",\"reason\":\"" + EscapeJson(reason ?? "") + "\""
			+ ",\"property\":\"" + EscapeJson(property ?? "") + "\""
			+ ",\"oldValue\":\"" + EscapeJson(oldValue) + "\""
			+ ",\"newValue\":\"" + EscapeJson(newValue) + "\"");
	}

	private static string SetPrimitiveComponentField(string id, string requestJson)
	{
		var go = FindGameObjectById(ReadInt(requestJson, "objectId", 0));
		if (!go)
			return ErrorResponse(id, "not_found", "set_primitive_component_field requires a live objectId from a prior Unity query.");
		if (!IsWritableUiSceneObject(go, ReadBool(requestJson, "requireActiveHierarchy", true), out var scopeError))
			return ErrorResponse(id, "out_of_scope", scopeError);
		var componentType = ReadString(requestJson, "componentType");
		var fieldName = ReadString(requestJson, "fieldName");
		var value = ReadString(requestJson, "value");
		var expected = ReadString(requestJson, "expectedOldValue");
		if (string.IsNullOrWhiteSpace(componentType) || string.IsNullOrWhiteSpace(fieldName))
			return ErrorResponse(id, "bad_request", "set_primitive_component_field requires componentType and fieldName.");
		var component = FindComponentByName(go, componentType);
		if (!component)
			return ErrorResponse(id, "not_found", "Component not found on target: " + componentType);
		var field = component.GetType().GetField(fieldName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
		if (field == null)
			return ErrorResponse(id, "not_found", "Field not found on component: " + fieldName);
		if (!IsSupportedPrimitiveFieldType(field.FieldType))
			return ErrorResponse(id, "unsupported_field_type", "Only bool, integral, float, double, string, and enum fields are supported.");
		var oldRaw = field.GetValue(component);
		var oldValue = oldRaw == null ? "" : Convert.ToString(oldRaw, System.Globalization.CultureInfo.InvariantCulture);
		if (!string.IsNullOrEmpty(expected) && !string.Equals(oldValue, expected, StringComparison.Ordinal))
			return ErrorResponse(id, "expected_old_value_mismatch", "Expected old value '" + expected + "' but found '" + oldValue + "'.");
		if (!TryConvertPrimitive(value, field.FieldType, out var converted, out var error))
			return ErrorResponse(id, "bad_value", error);
		field.SetValue(component, converted);
		var newRaw = field.GetValue(component);
		var newValue = newRaw == null ? "" : Convert.ToString(newRaw, System.Globalization.CultureInfo.InvariantCulture);
		return OkResponse(id,
			"\"objectId\":" + go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"path\":\"" + EscapeJson(UnityPath(go.transform)) + "\""
			+ ",\"componentType\":\"" + EscapeJson(component.GetType().FullName ?? component.GetType().Name ?? "") + "\""
			+ ",\"fieldName\":\"" + EscapeJson(fieldName) + "\""
			+ ",\"oldValue\":\"" + EscapeJson(oldValue) + "\""
			+ ",\"newValue\":\"" + EscapeJson(newValue) + "\"");
	}

	private static string InvokeAllowlistedMethod(string id, string requestJson)
	{
		var go = FindGameObjectById(ReadInt(requestJson, "objectId", 0));
		if (!go)
			return ErrorResponse(id, "not_found", "invoke_allowlisted_method requires a live objectId from a prior Unity query.");
		if (!IsWritableUiSceneObject(go, ReadBool(requestJson, "requireActiveHierarchy", true), out var scopeError))
			return ErrorResponse(id, "out_of_scope", scopeError);
		var method = ReadString(requestJson, "methodName");
		if (string.Equals(method, "GameObject.SetActive", StringComparison.OrdinalIgnoreCase))
		{
			var value = ReadBool(requestJson, "value", go.activeSelf);
			var oldValue = go.activeSelf;
			go.SetActive(value);
			return OkResponse(id, "\"method\":\"GameObject.SetActive\",\"oldValue\":" + (oldValue ? "true" : "false") + ",\"newValue\":" + (go.activeSelf ? "true" : "false") + ",\"path\":\"" + EscapeJson(UnityPath(go.transform)) + "\"");
		}
		if (string.Equals(method, "Transform.SetAsLastSibling", StringComparison.OrdinalIgnoreCase))
		{
			var oldValue = go.transform ? go.transform.GetSiblingIndex() : -1;
			if (go.transform)
				go.transform.SetAsLastSibling();
			return OkResponse(id, "\"method\":\"Transform.SetAsLastSibling\",\"oldSiblingIndex\":" + oldValue.ToString(System.Globalization.CultureInfo.InvariantCulture) + ",\"newSiblingIndex\":" + (go.transform ? go.transform.GetSiblingIndex().ToString(System.Globalization.CultureInfo.InvariantCulture) : "-1") + ",\"path\":\"" + EscapeJson(UnityPath(go.transform)) + "\"");
		}
		if (string.Equals(method, "Transform.SetAsFirstSibling", StringComparison.OrdinalIgnoreCase))
		{
			var oldValue = go.transform ? go.transform.GetSiblingIndex() : -1;
			if (go.transform)
				go.transform.SetAsFirstSibling();
			return OkResponse(id, "\"method\":\"Transform.SetAsFirstSibling\",\"oldSiblingIndex\":" + oldValue.ToString(System.Globalization.CultureInfo.InvariantCulture) + ",\"newSiblingIndex\":" + (go.transform ? go.transform.GetSiblingIndex().ToString(System.Globalization.CultureInfo.InvariantCulture) : "-1") + ",\"path\":\"" + EscapeJson(UnityPath(go.transform)) + "\"");
		}
		return ErrorResponse(id, "not_allowlisted", "Method is not in the live workbench allowlist.");
	}

	private static string DispatchUiClick(string id, string requestJson)
	{
		if (!TryResolveUiClickTarget(requestJson, out var go, out var error))
			return ErrorResponse(id, "not_found", error);
		if (!IsDispatchableUiClickObject(go, ReadBool(requestJson, "requireActiveHierarchy", true), out var scopeError))
			return ErrorResponse(id, "out_of_scope", scopeError);
		var rectTransform = go.GetComponent<RectTransform>();
		if (!rectTransform)
			return ErrorResponse(id, "not_ui_target", "dispatch_ui_click requires a RectTransform target.");
		if (EventSystem.current == null)
			return ErrorResponse(id, "no_event_system", "Unity EventSystem.current is null.");
		var canvas = go.GetComponentInParent<Canvas>(true);
		var eventCamera = canvas && canvas.renderMode != RenderMode.ScreenSpaceOverlay ? canvas.worldCamera : null;
		var screenPosition = RectTransformUtility.WorldToScreenPoint(eventCamera, rectTransform.TransformPoint(rectTransform.rect.center));

		var pointer = new PointerEventData(EventSystem.current)
		{
			button = PointerEventData.InputButton.Left,
			clickCount = 1,
			eligibleForClick = true,
			position = screenPosition,
			pressPosition = screenPosition,
			pointerId = -1,
			pointerPress = go,
			rawPointerPress = go,
			useDragThreshold = true,
		};

		ExecuteEvents.Execute(go, pointer, ExecuteEvents.pointerDownHandler);
		ExecuteEvents.Execute(go, pointer, ExecuteEvents.pointerUpHandler);
		ExecuteEvents.Execute(go, pointer, ExecuteEvents.pointerClickHandler);
		return OkResponse(id,
			"\"method\":\"dispatch_ui_click\""
			+ ",\"objectId\":" + go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"path\":\"" + EscapeJson(UnityPath(go.transform)) + "\""
			+ ",\"screenX\":" + screenPosition.x.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"screenY\":" + screenPosition.y.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture));
	}

	private static bool TryResolveUiClickTarget(string json, out GameObject go, out string error)
	{
		go = null;
		error = null;
		var objectId = ReadInt(json, "objectId", 0);
		if (objectId != 0)
		{
			go = FindGameObjectById(objectId);
			if (go)
				return true;
			error = "No live GameObject with objectId " + objectId.ToString(System.Globalization.CultureInfo.InvariantCulture) + ".";
			return false;
		}

		var path = ReadString(json, "path");
		if (!string.IsNullOrWhiteSpace(path))
		{
			var matches = new List<GameObject>();
			var objects = UnityObject.FindObjectsOfType<GameObject>(true);
			for (var i = 0; i < objects.Length; i++)
			{
				var candidate = objects[i];
				if (!candidate || !candidate.transform)
					continue;
				if (!string.Equals(UnityPath(candidate.transform), path, StringComparison.Ordinal))
					continue;
				if (!IsDispatchableUiClickObject(candidate, true, out _))
					continue;
				matches.Add(candidate);
			}
			if (matches.Count == 1)
			{
				go = matches[0];
				return true;
			}
			error = matches.Count == 0
				? "No active dispatchable UI GameObject with exact path '" + path + "'."
				: "Multiple active dispatchable UI GameObjects have exact path '" + path + "'.";
			return false;
		}

		var name = ReadString(json, "name") ?? ReadString(json, "targetName");
		if (!string.IsNullOrWhiteSpace(name))
		{
			var matches = new List<GameObject>();
			var objects = UnityObject.FindObjectsOfType<GameObject>(true);
			for (var i = 0; i < objects.Length; i++)
			{
				var candidate = objects[i];
				if (!candidate || !string.Equals(candidate.name ?? "", name, StringComparison.Ordinal))
					continue;
				if (!IsDispatchableUiClickObject(candidate, true, out _))
					continue;
				matches.Add(candidate);
			}
			if (matches.Count == 1)
			{
				go = matches[0];
				return true;
			}
			error = matches.Count == 0
				? "No active dispatchable UI GameObject with exact name '" + name + "'."
				: "Multiple active dispatchable UI GameObjects have exact name '" + name + "'. Use objectId or exact path.";
			return false;
		}

		error = "dispatch_ui_click requires objectId, exact path, or exact name.";
		return false;
	}

	private static string CreateUiDiagnosticOverlay(string id, string requestJson)
	{
		var go = FindGameObjectById(ReadInt(requestJson, "objectId", 0));
		if (!go)
			return ErrorResponse(id, "not_found", "create_ui_diagnostic_overlay requires a live objectId from a prior Unity query.");
		if (!IsWritableUiSceneObject(go, ReadBool(requestJson, "requireActiveHierarchy", true), out var scopeError))
			return ErrorResponse(id, "out_of_scope", scopeError);
		var targetRect = go.GetComponent<RectTransform>();
		if (!targetRect)
			return ErrorResponse(id, "not_rect_transform", "Target GameObject has no RectTransform.");
		var overlay = new GameObject("Homm3LiveProbeDiagnosticOverlay");
		overlay.layer = go.layer;
		overlay.transform.SetParent(targetRect, false);
		var rect = overlay.AddComponent<RectTransform>();
		rect.anchorMin = Vector2.zero;
		rect.anchorMax = Vector2.one;
		rect.offsetMin = Vector2.zero;
		rect.offsetMax = Vector2.zero;
		var image = overlay.AddComponent<Image>();
		image.raycastTarget = false;
		image.color = DiagnosticColor(ReadString(requestJson, "color"), ReadFloat(requestJson, "alpha", 0.18f));
		overlay.transform.SetAsLastSibling();
		return OkResponse(id,
			"\"overlayObjectId\":" + overlay.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"targetObjectId\":" + go.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"path\":\"" + EscapeJson(UnityPath(overlay.transform)) + "\"");
	}

	private static string RemoveUiDiagnosticOverlays(string id, string requestJson)
	{
		var objectId = ReadInt(requestJson, "objectId", 0);
		var roots = new List<GameObject>();
		if (objectId != 0)
		{
			var go = FindGameObjectById(objectId);
			if (!go)
				return ErrorResponse(id, "not_found", "ObjectId not found.");
			roots.Add(go);
		}
		else
		{
			roots.AddRange(UnityObject.FindObjectsOfType<GameObject>(true));
		}
		var removed = 0;
		foreach (var root in roots)
		{
			if (!root)
				continue;
			var transforms = root.GetComponentsInChildren<Transform>(true);
			for (var i = 0; i < transforms.Length; i++)
			{
				var t = transforms[i];
				if (t && t.gameObject && string.Equals(t.name, "Homm3LiveProbeDiagnosticOverlay", StringComparison.Ordinal))
				{
					UnityObject.Destroy(t.gameObject);
					removed++;
				}
			}
		}
		return OkResponse(id, "\"removed\":" + removed.ToString(System.Globalization.CultureInfo.InvariantCulture));
	}

	private static string EnablePrecompiledPatch(string id, string requestJson)
	{
		return ErrorResponse(id, "no_patches_registered", "No dormant precompiled live patches are registered in this build. This command exists for the guarded capability contract only.");
	}

	private static string VolatileUnavailable(string id, string command)
	{
		return ErrorResponse(id, "volatile_unavailable", command + " remains unavailable because it would require arbitrary C#, broad reflection, generated getter sweeps, object-reference writes, same-shape autopatching, or global UI hooks.");
	}

	private static string UnityRendererJson(Renderer renderer)
	{
		if (!renderer)
			return "{}";
		var material = renderer.sharedMaterial;
		var shader = material && material.shader ? material.shader.name : "";
		return "{"
			+ "\"name\":\"" + EscapeJson(renderer.name ?? "") + "\","
			+ "\"objectId\":" + (renderer.gameObject ? renderer.gameObject.GetInstanceID().ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
			+ "\"path\":\"" + EscapeJson(UnityPath(renderer.transform)) + "\","
			+ "\"type\":\"" + EscapeJson(renderer.GetType().FullName ?? renderer.GetType().Name ?? "") + "\","
			+ "\"enabled\":" + (renderer.enabled ? "true" : "false") + ","
			+ "\"forceRenderingOff\":" + (renderer.forceRenderingOff ? "true" : "false") + ","
			+ "\"activeSelf\":" + (renderer.gameObject && renderer.gameObject.activeSelf ? "true" : "false") + ","
			+ "\"activeInHierarchy\":" + (renderer.gameObject && renderer.gameObject.activeInHierarchy ? "true" : "false") + ","
			+ "\"layer\":" + (renderer.gameObject ? renderer.gameObject.layer.ToString(System.Globalization.CultureInfo.InvariantCulture) : "0") + ","
			+ "\"localPosition\":" + Vector3Json(renderer.transform ? renderer.transform.localPosition : Vector3.zero) + ","
			+ "\"worldPosition\":" + Vector3Json(renderer.transform ? renderer.transform.position : Vector3.zero) + ","
			+ "\"material\":\"" + EscapeJson(material ? (material.name ?? "") : "") + "\","
			+ "\"shader\":\"" + EscapeJson(shader ?? "") + "\""
			+ "}";
	}

	private static string Vector3Json(Vector3 value)
	{
		return "{\"x\":"
		       + value.x.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"y\":"
		       + value.y.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"z\":"
		       + value.z.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
		       + "}";
	}

	private static string Vector2Json(Vector2 value)
	{
		return "{\"x\":"
		       + value.x.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
		       + ",\"y\":"
		       + value.y.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
		       + "}";
	}

	private static string FloatJson(float value)
	{
		if (float.IsNaN(value) || float.IsInfinity(value))
			return "0";
		return value.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture);
	}

	private static string SafeTag(GameObject go)
	{
		if (!go)
			return "";
		try
		{
			return go.tag ?? "";
		}
		catch
		{
			return "";
		}
	}

	private static string SafeSortingLayerName(Canvas canvas)
	{
		if (!canvas)
			return "";
		try
		{
			return SortingLayer.IDToName(canvas.sortingLayerID) ?? "";
		}
		catch
		{
			return "";
		}
	}

	private static Material SafeGraphicMaterial(Graphic graphic)
	{
		if (!graphic)
			return null;
		try
		{
			return graphic.material;
		}
		catch
		{
			return null;
		}
	}

	private static string CapabilityJson(string name, string risk, string description)
	{
		return "{\"name\":\"" + EscapeJson(name) + "\",\"risk\":\"" + EscapeJson(risk) + "\",\"description\":\"" + EscapeJson(description) + "\"}";
	}

	private static GameObject FindGameObjectById(int objectId)
	{
		if (objectId == 0)
			return null;
		var objects = UnityObject.FindObjectsOfType<GameObject>(true);
		for (var i = 0; i < objects.Length; i++)
		{
			var go = objects[i];
			if (go && go.GetInstanceID() == objectId)
				return go;
		}
		return null;
	}

	private static bool TryResolveGetterTarget(string json, out object target, out string label, out string error)
	{
		target = null;
		label = null;
		error = null;
		var targetKind = ReadString(json, "target") ?? ReadString(json, "targetKind");
		if (string.Equals(targetKind, "cachedTownWrapper", StringComparison.OrdinalIgnoreCase)
		    || ReadBool(json, "cachedTownWrapper", false))
		{
			target = ModActions.GetLiveProbeTownWrapper();
			label = "cachedTownWrapper";
			if (target != null)
				return true;
			error = "Cached town wrapper is null.";
			return false;
		}

		if (!TryResolveGameObjectTarget(json, out var go, out error))
			return false;
		var componentType = ReadString(json, "componentType");
		if (string.IsNullOrWhiteSpace(componentType) || string.Equals(componentType, "GameObject", StringComparison.OrdinalIgnoreCase))
		{
			target = go;
			label = "GameObject:" + UnityPath(go.transform);
			return true;
		}
		var component = FindComponentByName(go, componentType);
		if (!component)
		{
			error = "Component not found on target: " + componentType;
			return false;
		}
		var exactType = FindLoadedTypeByName(componentType);
		target = exactType != null && typeof(Component).IsAssignableFrom(exactType)
			? new NativeTypedObject(component, exactType)
			: component;
		label = (exactType?.FullName ?? component.GetType().FullName ?? componentType) + ":" + UnityPath(go.transform);
		return true;
	}

	private static bool IsAllowlistedExactNoArgGetter(Type targetType, string methodName, string expectedReturnType)
	{
		if (targetType == null || string.IsNullOrWhiteSpace(methodName) || string.IsNullOrWhiteSpace(expectedReturnType))
			return false;
		if (IsBuiltInExactNoArgGetter(methodName, expectedReturnType))
			return true;
		foreach (var entry in LoadExactGetterAllowlist())
		{
			if (!string.Equals(entry.MethodName, methodName, StringComparison.Ordinal)
			    || !string.Equals(entry.ExpectedReturnTypeFullName, expectedReturnType, StringComparison.Ordinal))
				continue;
			if (string.IsNullOrWhiteSpace(entry.TargetTypeFullName)
			    || string.Equals(entry.TargetTypeFullName, targetType.FullName, StringComparison.Ordinal)
			    || string.Equals(entry.TargetTypeFullName, targetType.Name, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool IsBuiltInExactNoArgGetter(string methodName, string expectedReturnType)
	{
		if (string.Equals(expectedReturnType, "Hex.Session.Data.ObjCity", StringComparison.Ordinal)
		    && ContainsExact(GameSymbols.ReleaseTownUi.SessionCityDataMethods, methodName))
			return true;
		if (string.Equals(expectedReturnType, "Hex.Session.Data.ObjCityConfig", StringComparison.Ordinal)
		    && ContainsExact(GameSymbols.ReleaseTownUi.SessionCityConfigMethods, methodName))
			return true;
		if (string.Equals(expectedReturnType, "Hex.Session.Data.BuildingData", StringComparison.Ordinal)
		    && ContainsExact(GameSymbols.ReleaseTownUi.BuildingModelDataMethods, methodName))
			return true;
		if (string.Equals(expectedReturnType, "Hex.Session.Data.BuildingConfigBase", StringComparison.Ordinal)
		    && ContainsExact(GameSymbols.ReleaseTownUi.DataObjectConfigMethods, methodName))
			return true;
		if (string.Equals(expectedReturnType, "System.String", StringComparison.Ordinal)
		    && ContainsExact(GameSymbols.ReleaseTownUi.BuildingModelSidMethods, methodName))
			return true;
		return false;
	}

	private static bool IsAllowlistedVolatileMethod(Type targetType, string methodName, string expectedReturnType, string[] parameterTypeNames)
	{
		if (targetType == null || string.IsNullOrWhiteSpace(methodName) || string.IsNullOrWhiteSpace(expectedReturnType))
			return false;
		var parameterKey = JoinTypeNames(parameterTypeNames);
		foreach (var entry in LoadVolatileOperationAllowlist())
		{
			if (!string.Equals(entry.Kind, "method", StringComparison.OrdinalIgnoreCase))
				continue;
			if (!string.Equals(entry.MethodName, methodName, StringComparison.Ordinal))
				continue;
			if (!string.Equals(entry.ExpectedReturnTypeFullName ?? "System.Void", expectedReturnType, StringComparison.Ordinal))
				continue;
			if (!string.Equals(entry.ParameterTypeFullNames ?? "", parameterKey, StringComparison.Ordinal))
				continue;
			if (MatchesTargetType(entry.TargetTypeFullName, targetType))
				return true;
		}
		return false;
	}

	private static bool IsAllowlistedVolatileMember(Type targetType, string memberKind, string memberName, string memberTypeFullName)
	{
		if (targetType == null || string.IsNullOrWhiteSpace(memberKind) || string.IsNullOrWhiteSpace(memberName) || string.IsNullOrWhiteSpace(memberTypeFullName))
			return false;
		foreach (var entry in LoadVolatileOperationAllowlist())
		{
			if (!string.Equals(entry.Kind, "member", StringComparison.OrdinalIgnoreCase)
			    && !string.Equals(entry.Kind, "writeMember", StringComparison.OrdinalIgnoreCase))
				continue;
			if (!string.Equals(entry.MemberKind ?? "field", memberKind, StringComparison.OrdinalIgnoreCase))
				continue;
			if (!string.Equals(entry.MemberName, memberName, StringComparison.Ordinal))
				continue;
			if (!string.Equals(entry.MemberTypeFullName, memberTypeFullName, StringComparison.Ordinal))
				continue;
			if (MatchesTargetType(entry.TargetTypeFullName, targetType))
				return true;
		}
		return false;
	}

	private static bool MatchesTargetType(string configuredTargetType, Type targetType)
	{
		return targetType != null
		       && (string.IsNullOrWhiteSpace(configuredTargetType)
		           || string.Equals(configuredTargetType, targetType.FullName, StringComparison.Ordinal)
		           || string.Equals(configuredTargetType, targetType.Name, StringComparison.Ordinal));
	}

	private static string JoinTypeNames(string[] parameterTypeNames)
	{
		if (parameterTypeNames == null || parameterTypeNames.Length == 0)
			return "";
		return string.Join("|", parameterTypeNames);
	}

	private static bool ContainsExact(string[] values, string value)
	{
		if (values == null || value == null)
			return false;
		for (var i = 0; i < values.Length; i++)
		{
			if (string.Equals(values[i], value, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static List<ExactGetterAllowlistEntry> LoadExactGetterAllowlist()
	{
		try
		{
			if (string.IsNullOrWhiteSpace(_exactGetterAllowlistPath) || !File.Exists(_exactGetterAllowlistPath))
			{
				_exactGetterAllowlist = new List<ExactGetterAllowlistEntry>();
				_exactGetterAllowlistMtimeUtc = DateTime.MinValue;
				return _exactGetterAllowlist;
			}
			var mtime = File.GetLastWriteTimeUtc(_exactGetterAllowlistPath);
			if (mtime == _exactGetterAllowlistMtimeUtc)
				return _exactGetterAllowlist;
			var text = File.ReadAllText(_exactGetterAllowlistPath);
			var entries = new List<ExactGetterAllowlistEntry>();
			foreach (Match match in Regex.Matches(text, "\\{[^{}]*\"methodName\"\\s*:[^{}]*\\}", RegexOptions.IgnoreCase))
			{
				var item = match.Value;
				var methodName = ReadString(item, "methodName");
				var returnType = ReadString(item, "expectedReturnTypeFullName");
				if (string.IsNullOrWhiteSpace(methodName) || string.IsNullOrWhiteSpace(returnType))
					continue;
				entries.Add(new ExactGetterAllowlistEntry
				{
					MethodName = methodName,
					ExpectedReturnTypeFullName = returnType,
					TargetTypeFullName = ReadString(item, "targetTypeFullName"),
					Reason = ReadString(item, "reason")
				});
			}
			_exactGetterAllowlist = entries;
			_exactGetterAllowlistMtimeUtc = mtime;
		}
		catch (Exception ex)
		{
			_log?.LogWarning(GrepKey + " exact getter allowlist reload failed: " + ex.Message);
			_exactGetterAllowlist = new List<ExactGetterAllowlistEntry>();
			_exactGetterAllowlistMtimeUtc = DateTime.MinValue;
		}
		return _exactGetterAllowlist;
	}

	private static List<VolatileOperationAllowlistEntry> LoadVolatileOperationAllowlist()
	{
		try
		{
			if (string.IsNullOrWhiteSpace(_volatileOperationAllowlistPath) || !File.Exists(_volatileOperationAllowlistPath))
			{
				_volatileOperationAllowlist = new List<VolatileOperationAllowlistEntry>();
				_volatileOperationAllowlistMtimeUtc = DateTime.MinValue;
				return _volatileOperationAllowlist;
			}
			var mtime = File.GetLastWriteTimeUtc(_volatileOperationAllowlistPath);
			if (mtime == _volatileOperationAllowlistMtimeUtc)
				return _volatileOperationAllowlist;
			var text = File.ReadAllText(_volatileOperationAllowlistPath);
			var entries = new List<VolatileOperationAllowlistEntry>();
			foreach (Match match in Regex.Matches(text, "\\{[^{}]*\"kind\"\\s*:[^{}]*\\}", RegexOptions.IgnoreCase))
			{
				var item = match.Value;
				var kind = ReadString(item, "kind");
				if (string.IsNullOrWhiteSpace(kind))
					continue;
				var methodName = ReadString(item, "methodName");
				var memberName = ReadString(item, "memberName");
				var entry = new VolatileOperationAllowlistEntry
				{
					Kind = kind,
					TargetTypeFullName = ReadString(item, "targetTypeFullName"),
					MethodName = methodName,
					ExpectedReturnTypeFullName = ReadString(item, "expectedReturnTypeFullName") ?? "System.Void",
					ParameterTypeFullNames = NormalizeTypeNameList(ReadString(item, "parameterTypeFullNames")),
					MemberKind = ReadString(item, "memberKind") ?? "field",
					MemberName = memberName,
					MemberTypeFullName = ReadString(item, "memberTypeFullName") ?? ReadString(item, "expectedMemberTypeFullName"),
					Reason = ReadString(item, "reason")
				};
				if (string.Equals(kind, "method", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(methodName))
					entries.Add(entry);
				else if ((string.Equals(kind, "member", StringComparison.OrdinalIgnoreCase) || string.Equals(kind, "writeMember", StringComparison.OrdinalIgnoreCase))
				         && !string.IsNullOrWhiteSpace(memberName)
				         && !string.IsNullOrWhiteSpace(entry.MemberTypeFullName))
					entries.Add(entry);
			}
			_volatileOperationAllowlist = entries;
			_volatileOperationAllowlistMtimeUtc = mtime;
		}
		catch (Exception ex)
		{
			_log?.LogWarning(GrepKey + " volatile operation allowlist reload failed: " + ex.Message);
			_volatileOperationAllowlist = new List<VolatileOperationAllowlistEntry>();
			_volatileOperationAllowlistMtimeUtc = DateTime.MinValue;
		}
		return _volatileOperationAllowlist;
	}

	private static string NormalizeTypeNameList(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return "";
		var parts = value.Split(new[] { '|', ',' }, StringSplitOptions.RemoveEmptyEntries);
		for (var i = 0; i < parts.Length; i++)
			parts[i] = parts[i].Trim();
		return string.Join("|", parts);
	}

	private static string[] SplitGetterChain(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return Array.Empty<string>();
		var parts = value.Split(new[] { '|' }, StringSplitOptions.RemoveEmptyEntries);
		var values = new List<string>();
		for (var i = 0; i < parts.Length; i++)
		{
			var part = parts[i].Trim();
			if (part.Length > 0)
				values.Add(part);
		}
		return values.ToArray();
	}

	private static Type ResolveSimpleType(string typeName)
	{
		if (string.IsNullOrWhiteSpace(typeName))
			return null;
		switch (typeName)
		{
			case "bool":
			case "Boolean":
			case "System.Boolean":
				return typeof(bool);
			case "byte":
			case "Byte":
			case "System.Byte":
				return typeof(byte);
			case "sbyte":
			case "SByte":
			case "System.SByte":
				return typeof(sbyte);
			case "short":
			case "Int16":
			case "System.Int16":
				return typeof(short);
			case "ushort":
			case "UInt16":
			case "System.UInt16":
				return typeof(ushort);
			case "int":
			case "Int32":
			case "System.Int32":
				return typeof(int);
			case "uint":
			case "UInt32":
			case "System.UInt32":
				return typeof(uint);
			case "long":
			case "Int64":
			case "System.Int64":
				return typeof(long);
			case "ulong":
			case "UInt64":
			case "System.UInt64":
				return typeof(ulong);
			case "float":
			case "Single":
			case "System.Single":
				return typeof(float);
			case "double":
			case "Double":
			case "System.Double":
				return typeof(double);
			case "string":
			case "String":
			case "System.String":
				return typeof(string);
			default:
				return FindType(typeName);
		}
	}

	private static Type ResolveNativeWriteMemberType(Type targetType, string memberKind, string memberName, string expectedTypeName)
	{
		var explicitType = ResolveSimpleType(expectedTypeName);
		if (explicitType != null)
			return explicitType;
		foreach (var entry in LoadVolatileOperationAllowlist())
		{
			if (!string.Equals(entry.Kind, "member", StringComparison.OrdinalIgnoreCase)
			    && !string.Equals(entry.Kind, "writeMember", StringComparison.OrdinalIgnoreCase))
				continue;
			if (!string.Equals(entry.MemberName, memberName, StringComparison.Ordinal))
				continue;
			if (!string.Equals(entry.MemberKind ?? "field", memberKind ?? "field", StringComparison.OrdinalIgnoreCase))
				continue;
			if (!string.IsNullOrWhiteSpace(entry.TargetTypeFullName)
			    && targetType != null
			    && !string.Equals(entry.TargetTypeFullName, targetType.FullName, StringComparison.Ordinal)
			    && !string.Equals(entry.TargetTypeFullName, targetType.Name, StringComparison.Ordinal))
				continue;
			var type = ResolveSimpleType(entry.MemberTypeFullName);
			if (type != null)
				return type;
		}
		return null;
	}

	private static bool TryResolveCanvasTarget(string json, out Canvas canvas, out string error)
	{
		canvas = null;
		error = null;
		if (TryResolveGameObjectTarget(json, out var go, out error))
		{
			canvas = go.GetComponent<Canvas>() ?? go.GetComponentInParent<Canvas>(true);
			if (canvas)
				return true;
			error = "Resolved target has no Canvas on self or parent.";
			return false;
		}
		return false;
	}

	private static bool TryResolveGameObjectTarget(string json, out GameObject go, out string error)
	{
		go = null;
		error = null;
		var objectId = ReadInt(json, "objectId", 0);
		if (objectId != 0)
		{
			go = FindGameObjectById(objectId);
			if (go)
				return true;
			error = "No live GameObject with objectId " + objectId.ToString(System.Globalization.CultureInfo.InvariantCulture) + ".";
			return false;
		}

		var path = ReadString(json, "path") ?? ReadString(json, "transformPath");
		if (!string.IsNullOrWhiteSpace(path))
			return TryFindScopedGameObjectByPath(path, out go, out error);

		var name = ReadString(json, "canvasName") ?? ReadString(json, "name") ?? ReadString(json, "gameObjectName");
		if (!string.IsNullOrWhiteSpace(name))
			return TryFindScopedGameObjectByExactName(name, out go, out error);

		error = "Target requires objectId, exact path, or exact name/canvasName.";
		return false;
	}

	private static bool TryFindScopedGameObjectByPath(string path, out GameObject go, out string error)
	{
		go = null;
		error = null;
		var matches = new List<GameObject>();
		var objects = UnityObject.FindObjectsOfType<GameObject>(true);
		for (var i = 0; i < objects.Length; i++)
		{
			var candidate = objects[i];
			if (!candidate || !candidate.transform)
				continue;
			if (!string.Equals(UnityPath(candidate.transform), path, StringComparison.Ordinal))
				continue;
			if (!IsWritableUiSceneObject(candidate, true, out _))
				continue;
			matches.Add(candidate);
		}
		if (matches.Count == 1)
		{
			go = matches[0];
			return true;
		}
		error = matches.Count == 0
			? "No active scoped GameObject with exact path '" + path + "'."
			: "Multiple active scoped GameObjects have exact path '" + path + "'.";
		return false;
	}

	private static bool TryFindGameObjectBySceneAndPath(string sceneName, string path, bool requireActiveHierarchy, out GameObject go, out string error)
	{
		go = null;
		error = null;
		var matches = new List<GameObject>();
		var objects = UnityObject.FindObjectsOfType<GameObject>(true);
		for (var i = 0; i < objects.Length; i++)
		{
			var candidate = objects[i];
			if (!candidate || !candidate.transform)
				continue;
			var scene = candidate.scene;
			if (!scene.IsValid() || !string.Equals(scene.name ?? "", sceneName, StringComparison.Ordinal))
				continue;
			if (!string.Equals(UnityPath(candidate.transform), path, StringComparison.Ordinal))
				continue;
			if (requireActiveHierarchy && !candidate.activeInHierarchy)
				continue;
			matches.Add(candidate);
		}
		if (matches.Count == 1)
		{
			go = matches[0];
			return true;
		}
		error = matches.Count == 0
			? "No GameObject in scene '" + sceneName + "' with exact path '" + path + "'."
			: "Multiple GameObjects in scene '" + sceneName + "' have exact path '" + path + "'.";
		return false;
	}

	private static bool IsWritableDiagnosticUiScene(string sceneName)
	{
		if (string.IsNullOrWhiteSpace(sceneName))
			return false;
		var activeScene = SceneManager.GetActiveScene();
		if (!activeScene.IsValid())
			return false;
		if (string.Equals(sceneName, activeScene.name, StringComparison.Ordinal))
			return true;
		if (string.Equals(sceneName, "CityUI", StringComparison.Ordinal) && IsCityInteriorSceneName(activeScene.name))
			return true;
		if (IsAllowedAdditiveDiagnosticUiScene(sceneName) && IsTownOrMapSceneName(activeScene.name))
			return true;
		return false;
	}

	private static bool IsAllowedAdditiveDiagnosticUiScene(string sceneName)
	{
		return string.Equals(sceneName, "sessionFade", StringComparison.Ordinal);
	}

	private static bool IsTownOrMapSceneName(string sceneName)
	{
		return IsCityInteriorSceneName(sceneName)
		       || string.Equals(sceneName, "worldLight", StringComparison.OrdinalIgnoreCase);
	}

	private static bool TryFindScopedGameObjectByExactName(string name, out GameObject go, out string error)
	{
		go = null;
		error = null;
		var matches = new List<GameObject>();
		var objects = UnityObject.FindObjectsOfType<GameObject>(true);
		for (var i = 0; i < objects.Length; i++)
		{
			var candidate = objects[i];
			if (!candidate || !string.Equals(candidate.name ?? "", name, StringComparison.Ordinal))
				continue;
			if (!IsWritableUiSceneObject(candidate, true, out _))
				continue;
			matches.Add(candidate);
		}
		if (matches.Count == 1)
		{
			go = matches[0];
			return true;
		}
		error = matches.Count == 0
			? "No active scoped GameObject with exact name '" + name + "'."
			: "Multiple active scoped GameObjects have exact name '" + name + "'. Use objectId or exact path.";
		return false;
	}

	private static Component FindComponentByName(GameObject go, string componentType)
	{
		if (!go || string.IsNullOrWhiteSpace(componentType))
			return null;
		if (string.Equals(componentType, "Graphic", StringComparison.OrdinalIgnoreCase))
			return go.GetComponent<Graphic>();
		if (string.Equals(componentType, "Behaviour", StringComparison.OrdinalIgnoreCase))
			return go.GetComponent<Behaviour>();
		if (string.Equals(componentType, "LayoutGroup", StringComparison.OrdinalIgnoreCase))
			return go.GetComponent<LayoutGroup>();
		var exactType = FindLoadedTypeByName(componentType);
		if (exactType != null)
		{
			try
			{
				var typedComponent = go.GetComponent(Il2CppType.From(exactType))?.TryCast<Component>();
				if (typedComponent)
					return typedComponent;
			}
			catch { }
		}
		var components = go.GetComponents<Component>();
		for (var i = 0; i < components.Length; i++)
		{
			var component = components[i];
			if (!component)
				continue;
			var fullName = ComponentTypeName(component);
			var name = ShortTypeName(fullName);
			if (string.Equals(fullName, componentType, StringComparison.OrdinalIgnoreCase)
			    || string.Equals(name, componentType, StringComparison.OrdinalIgnoreCase))
				return component;
		}
		return null;
	}

	private static Type FindLoadedTypeByName(string typeName)
	{
		if (string.IsNullOrWhiteSpace(typeName))
			return null;
		try
		{
			var direct = Type.GetType(typeName, false);
			if (direct != null)
				return direct;
		}
		catch { }
		try
		{
			var assemblies = AppDomain.CurrentDomain.GetAssemblies();
			for (var i = 0; i < assemblies.Length; i++)
			{
				Type[] types;
				try { types = assemblies[i].GetTypes(); }
				catch (ReflectionTypeLoadException ex) { types = ex.Types; }
				catch { continue; }
				if (types == null)
					continue;
				for (var j = 0; j < types.Length; j++)
				{
					var type = types[j];
					if (type == null)
						continue;
					if (string.Equals(type.FullName ?? "", typeName, StringComparison.OrdinalIgnoreCase)
					    || string.Equals(type.Name ?? "", typeName, StringComparison.OrdinalIgnoreCase))
						return type;
				}
			}
		}
		catch { }
		return null;
	}

	private static void TryInitializeIl2CppType(Type managedType)
	{
		if (managedType == null)
			return;
		try
		{
			var storeType = typeof(Il2CppClassPointerStore<>).MakeGenericType(managedType);
			storeType.TypeInitializer?.Invoke(null, null);
		}
		catch
		{
		}
	}

	private static string ShortTypeName(string fullName)
	{
		if (string.IsNullOrWhiteSpace(fullName))
			return "";
		var index = fullName.LastIndexOf('.');
		return index >= 0 && index + 1 < fullName.Length ? fullName.Substring(index + 1) : fullName;
	}

	private static bool TryGetUnityUiProperty(GameObject go, string componentType, string property, out string value)
	{
		value = "";
		componentType = componentType ?? "";
		property = property ?? "";
		if (string.Equals(componentType, "GameObject", StringComparison.OrdinalIgnoreCase)
		    && string.Equals(property, "activeSelf", StringComparison.OrdinalIgnoreCase))
		{
			value = go.activeSelf ? "true" : "false";
			return true;
		}
		if (string.Equals(property, "enabled", StringComparison.OrdinalIgnoreCase))
		{
			var behaviour = FindComponentByName(go, componentType) as Behaviour;
			if (!behaviour)
				return false;
			value = behaviour.enabled ? "true" : "false";
			return true;
		}
		var canvasGroup = FindComponentByName(go, componentType) as CanvasGroup;
		if (canvasGroup && TryGetCanvasGroupProperty(canvasGroup, property, out value))
			return true;
		var graphic = FindComponentByName(go, componentType) as Graphic;
		if (graphic && TryGetGraphicProperty(graphic, property, out value))
			return true;
		var rect = FindComponentByName(go, componentType) as RectTransform;
		if (rect && TryGetRectTransformProperty(rect, property, out value))
			return true;
		var canvas = FindComponentByName(go, componentType) as Canvas;
		if (canvas && TryGetCanvasProperty(canvas, property, out value))
			return true;
		return false;
	}

	private static bool TrySetUnityUiProperty(GameObject go, string componentType, string property, string value, out string error)
	{
		error = null;
		componentType = componentType ?? "";
		property = property ?? "";
		if (string.Equals(componentType, "GameObject", StringComparison.OrdinalIgnoreCase)
		    && string.Equals(property, "activeSelf", StringComparison.OrdinalIgnoreCase))
		{
			go.SetActive(ParseBoolString(value, go.activeSelf));
			return true;
		}
		if (string.Equals(property, "enabled", StringComparison.OrdinalIgnoreCase))
		{
			var behaviour = FindComponentByName(go, componentType) as Behaviour;
			if (!behaviour)
			{
				error = "Component is not a Behaviour: " + componentType;
				return false;
			}
			behaviour.enabled = ParseBoolString(value, behaviour.enabled);
			return true;
		}
		var canvasGroup = FindComponentByName(go, componentType) as CanvasGroup;
		if (canvasGroup && TrySetCanvasGroupProperty(canvasGroup, property, value))
			return true;
		var graphic = FindComponentByName(go, componentType) as Graphic;
		if (graphic && TrySetGraphicProperty(graphic, property, value))
			return true;
		var rect = FindComponentByName(go, componentType) as RectTransform;
		if (rect && TrySetRectTransformProperty(rect, property, value))
			return true;
		var canvas = FindComponentByName(go, componentType) as Canvas;
		if (canvas && TrySetCanvasProperty(canvas, property, value))
			return true;
		error = "Unsupported UI property " + componentType + "." + property + ".";
		return false;
	}

	private static bool TryGetCanvasGroupProperty(CanvasGroup group, string property, out string value)
	{
		value = "";
		if (string.Equals(property, "alpha", StringComparison.OrdinalIgnoreCase)) value = FloatJson(group.alpha);
		else if (string.Equals(property, "interactable", StringComparison.OrdinalIgnoreCase)) value = group.interactable ? "true" : "false";
		else if (string.Equals(property, "blocksRaycasts", StringComparison.OrdinalIgnoreCase)) value = group.blocksRaycasts ? "true" : "false";
		else if (string.Equals(property, "ignoreParentGroups", StringComparison.OrdinalIgnoreCase)) value = group.ignoreParentGroups ? "true" : "false";
		else return false;
		return true;
	}

	private static bool TrySetCanvasGroupProperty(CanvasGroup group, string property, string value)
	{
		if (string.Equals(property, "alpha", StringComparison.OrdinalIgnoreCase)) group.alpha = ParseFloatString(value, group.alpha);
		else if (string.Equals(property, "interactable", StringComparison.OrdinalIgnoreCase)) group.interactable = ParseBoolString(value, group.interactable);
		else if (string.Equals(property, "blocksRaycasts", StringComparison.OrdinalIgnoreCase)) group.blocksRaycasts = ParseBoolString(value, group.blocksRaycasts);
		else if (string.Equals(property, "ignoreParentGroups", StringComparison.OrdinalIgnoreCase)) group.ignoreParentGroups = ParseBoolString(value, group.ignoreParentGroups);
		else return false;
		return true;
	}

	private static bool TryGetGraphicProperty(Graphic graphic, string property, out string value)
	{
		value = "";
		if (string.Equals(property, "raycastTarget", StringComparison.OrdinalIgnoreCase)) value = graphic.raycastTarget ? "true" : "false";
		else if (string.Equals(property, "colorAlpha", StringComparison.OrdinalIgnoreCase)) value = FloatJson(graphic.color.a);
		else return false;
		return true;
	}

	private static bool TrySetGraphicProperty(Graphic graphic, string property, string value)
	{
		if (string.Equals(property, "raycastTarget", StringComparison.OrdinalIgnoreCase)) graphic.raycastTarget = ParseBoolString(value, graphic.raycastTarget);
		else if (string.Equals(property, "colorAlpha", StringComparison.OrdinalIgnoreCase))
		{
			var color = graphic.color;
			color.a = ParseFloatString(value, color.a);
			graphic.color = color;
		}
		else return false;
		return true;
	}

	private static bool TryGetRectTransformProperty(RectTransform rect, string property, out string value)
	{
		value = "";
		if (string.Equals(property, "anchoredPositionX", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.anchoredPosition.x);
		else if (string.Equals(property, "anchoredPositionY", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.anchoredPosition.y);
		else if (string.Equals(property, "sizeDeltaX", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.sizeDelta.x);
		else if (string.Equals(property, "sizeDeltaY", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.sizeDelta.y);
		else if (string.Equals(property, "anchorMinX", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.anchorMin.x);
		else if (string.Equals(property, "anchorMinY", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.anchorMin.y);
		else if (string.Equals(property, "anchorMaxX", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.anchorMax.x);
		else if (string.Equals(property, "anchorMaxY", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.anchorMax.y);
		else if (string.Equals(property, "pivotX", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.pivot.x);
		else if (string.Equals(property, "pivotY", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.pivot.y);
		else if (string.Equals(property, "offsetMinX", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.offsetMin.x);
		else if (string.Equals(property, "offsetMinY", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.offsetMin.y);
		else if (string.Equals(property, "offsetMaxX", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.offsetMax.x);
		else if (string.Equals(property, "offsetMaxY", StringComparison.OrdinalIgnoreCase)) value = FloatJson(rect.offsetMax.y);
		else return false;
		return true;
	}

	private static bool TrySetRectTransformProperty(RectTransform rect, string property, string value)
	{
		var f = ParseFloatString(value, 0f);
		if (string.Equals(property, "anchoredPositionX", StringComparison.OrdinalIgnoreCase)) rect.anchoredPosition = new Vector2(f, rect.anchoredPosition.y);
		else if (string.Equals(property, "anchoredPositionY", StringComparison.OrdinalIgnoreCase)) rect.anchoredPosition = new Vector2(rect.anchoredPosition.x, f);
		else if (string.Equals(property, "sizeDeltaX", StringComparison.OrdinalIgnoreCase)) rect.sizeDelta = new Vector2(f, rect.sizeDelta.y);
		else if (string.Equals(property, "sizeDeltaY", StringComparison.OrdinalIgnoreCase)) rect.sizeDelta = new Vector2(rect.sizeDelta.x, f);
		else if (string.Equals(property, "anchorMinX", StringComparison.OrdinalIgnoreCase)) rect.anchorMin = new Vector2(f, rect.anchorMin.y);
		else if (string.Equals(property, "anchorMinY", StringComparison.OrdinalIgnoreCase)) rect.anchorMin = new Vector2(rect.anchorMin.x, f);
		else if (string.Equals(property, "anchorMaxX", StringComparison.OrdinalIgnoreCase)) rect.anchorMax = new Vector2(f, rect.anchorMax.y);
		else if (string.Equals(property, "anchorMaxY", StringComparison.OrdinalIgnoreCase)) rect.anchorMax = new Vector2(rect.anchorMax.x, f);
		else if (string.Equals(property, "pivotX", StringComparison.OrdinalIgnoreCase)) rect.pivot = new Vector2(f, rect.pivot.y);
		else if (string.Equals(property, "pivotY", StringComparison.OrdinalIgnoreCase)) rect.pivot = new Vector2(rect.pivot.x, f);
		else if (string.Equals(property, "offsetMinX", StringComparison.OrdinalIgnoreCase)) rect.offsetMin = new Vector2(f, rect.offsetMin.y);
		else if (string.Equals(property, "offsetMinY", StringComparison.OrdinalIgnoreCase)) rect.offsetMin = new Vector2(rect.offsetMin.x, f);
		else if (string.Equals(property, "offsetMaxX", StringComparison.OrdinalIgnoreCase)) rect.offsetMax = new Vector2(f, rect.offsetMax.y);
		else if (string.Equals(property, "offsetMaxY", StringComparison.OrdinalIgnoreCase)) rect.offsetMax = new Vector2(rect.offsetMax.x, f);
		else return false;
		return true;
	}

	private static bool TryGetCanvasProperty(Canvas canvas, string property, out string value)
	{
		value = "";
		if (string.Equals(property, "enabled", StringComparison.OrdinalIgnoreCase)) value = canvas.enabled ? "true" : "false";
		else if (string.Equals(property, "overrideSorting", StringComparison.OrdinalIgnoreCase)) value = canvas.overrideSorting ? "true" : "false";
		else if (string.Equals(property, "sortingOrder", StringComparison.OrdinalIgnoreCase)) value = canvas.sortingOrder.ToString(System.Globalization.CultureInfo.InvariantCulture);
		else if (string.Equals(property, "sortingLayerID", StringComparison.OrdinalIgnoreCase)) value = canvas.sortingLayerID.ToString(System.Globalization.CultureInfo.InvariantCulture);
		else if (string.Equals(property, "sortingLayerName", StringComparison.OrdinalIgnoreCase)) value = SafeSortingLayerName(canvas);
		else if (string.Equals(property, "planeDistance", StringComparison.OrdinalIgnoreCase)) value = FloatJson(canvas.planeDistance);
		else return false;
		return true;
	}

	private static bool TrySetCanvasProperty(Canvas canvas, string property, string value)
	{
		if (string.Equals(property, "enabled", StringComparison.OrdinalIgnoreCase)) canvas.enabled = ParseBoolString(value, canvas.enabled);
		else if (string.Equals(property, "overrideSorting", StringComparison.OrdinalIgnoreCase)) canvas.overrideSorting = ParseBoolString(value, canvas.overrideSorting);
		else if (string.Equals(property, "sortingOrder", StringComparison.OrdinalIgnoreCase)) canvas.sortingOrder = int.TryParse(value, out var parsed) ? parsed : canvas.sortingOrder;
		else if (string.Equals(property, "sortingLayerID", StringComparison.OrdinalIgnoreCase)) canvas.sortingLayerID = int.TryParse(value, out var parsedLayer) ? parsedLayer : canvas.sortingLayerID;
		else if (string.Equals(property, "sortingLayerName", StringComparison.OrdinalIgnoreCase))
		{
			var id = SortingLayer.NameToID(value ?? "");
			if (id == 0 && !string.Equals(value, "Default", StringComparison.Ordinal))
				return false;
			canvas.sortingLayerID = id;
		}
		else if (string.Equals(property, "planeDistance", StringComparison.OrdinalIgnoreCase)) canvas.planeDistance = ParseFloatString(value, canvas.planeDistance);
		else return false;
		return true;
	}

	private static bool TryNormalizeCanvasRequestedValue(Canvas canvas, string property, string value, out string normalized, out string error)
	{
		normalized = "";
		error = null;
		if (string.Equals(property, "enabled", StringComparison.OrdinalIgnoreCase))
		{
			normalized = ParseBoolString(value, canvas.enabled) ? "true" : "false";
			return true;
		}
		if (string.Equals(property, "overrideSorting", StringComparison.OrdinalIgnoreCase))
		{
			normalized = ParseBoolString(value, canvas.overrideSorting) ? "true" : "false";
			return true;
		}
		if (string.Equals(property, "sortingOrder", StringComparison.OrdinalIgnoreCase))
		{
			if (!int.TryParse(value, out var parsed))
			{
				error = "sortingOrder requires an integer value.";
				return false;
			}
			normalized = parsed.ToString(System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		if (string.Equals(property, "sortingLayerID", StringComparison.OrdinalIgnoreCase))
		{
			if (!int.TryParse(value, out var parsed))
			{
				error = "sortingLayerID requires an integer value.";
				return false;
			}
			normalized = parsed.ToString(System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		if (string.Equals(property, "sortingLayerName", StringComparison.OrdinalIgnoreCase))
		{
			var requested = value ?? "";
			var id = SortingLayer.NameToID(requested);
			if (id == 0 && !string.Equals(requested, "Default", StringComparison.Ordinal))
			{
				error = "sortingLayerName is not a known SortingLayer: " + requested;
				return false;
			}
			normalized = requested;
			return true;
		}
		if (string.Equals(property, "planeDistance", StringComparison.OrdinalIgnoreCase))
		{
			normalized = FloatJson(ParseFloatString(value, canvas.planeDistance));
			return true;
		}
		error = "Unsupported Canvas property: " + (property ?? "");
		return false;
	}

	private static bool IsWritableCanvasProperty(string property)
	{
		return string.Equals(property, "enabled", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(property, "overrideSorting", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(property, "sortingOrder", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(property, "sortingLayerID", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(property, "sortingLayerName", StringComparison.OrdinalIgnoreCase)
		       || string.Equals(property, "planeDistance", StringComparison.OrdinalIgnoreCase);
	}

	private static bool IsWritableActiveSceneCanvas(Canvas canvas, out string error)
	{
		error = null;
		if (!canvas || !canvas.gameObject)
		{
			error = "Canvas is missing or destroyed.";
			return false;
		}
		var activeScene = SceneManager.GetActiveScene();
		if (!IsWritableCanvasScene(canvas.gameObject.scene, activeScene))
		{
			error = "Canvas is not in the active town UI scene scope. canvasScene='" + (canvas.gameObject.scene.IsValid() ? canvas.gameObject.scene.name : "") + "' activeScene='" + (activeScene.IsValid() ? activeScene.name : "") + "'.";
			return false;
		}
		if (!canvas.gameObject.activeInHierarchy)
		{
			error = "Canvas GameObject is not activeInHierarchy.";
			return false;
		}
		return true;
	}

	private static bool IsWritableUiSceneObject(GameObject go, bool requireActiveHierarchy, out string error)
	{
		error = null;
		if (!go)
		{
			error = "GameObject is missing or destroyed.";
			return false;
		}
		var activeScene = SceneManager.GetActiveScene();
		if (!IsWritableCanvasScene(go.scene, activeScene))
		{
			error = "GameObject is not in the active town UI scene scope. targetScene='" + (go.scene.IsValid() ? go.scene.name : "") + "' activeScene='" + (activeScene.IsValid() ? activeScene.name : "") + "'.";
			return false;
		}
		if (requireActiveHierarchy && !go.activeInHierarchy)
		{
			error = "GameObject is not activeInHierarchy.";
			return false;
		}
		return true;
	}

	private static bool IsDispatchableUiClickObject(GameObject go, bool requireActiveHierarchy, out string error)
	{
		error = null;
		if (!go)
		{
			error = "GameObject is missing or destroyed.";
			return false;
		}
		var scene = go.scene;
		if (!scene.IsValid() || !scene.isLoaded)
		{
			error = "GameObject is not in a loaded scene. targetScene='" + (scene.IsValid() ? scene.name : "") + "'.";
			return false;
		}
		if (requireActiveHierarchy && !go.activeInHierarchy)
		{
			error = "GameObject is not activeInHierarchy.";
			return false;
		}
		if (!go.GetComponent<RectTransform>())
		{
			error = "GameObject has no RectTransform.";
			return false;
		}
		var canvas = go.GetComponentInParent<Canvas>(true);
		if (!canvas || !canvas.gameObject)
		{
			error = "GameObject has no parent Canvas.";
			return false;
		}
		if (!canvas.enabled || !canvas.gameObject.activeInHierarchy)
		{
			error = "Parent Canvas is not active and enabled.";
			return false;
		}
		return true;
	}

	private static bool IsWritableCanvasScene(Scene canvasScene, Scene activeScene)
	{
		if (!canvasScene.IsValid() || !activeScene.IsValid())
			return false;
		if (canvasScene.handle == activeScene.handle)
			return true;
		return string.Equals(canvasScene.name, "CityUI", StringComparison.Ordinal)
		       && IsCityInteriorSceneName(activeScene.name);
	}

	private static bool IsCityInteriorSceneName(string sceneName)
	{
		return !string.IsNullOrEmpty(sceneName)
		       && sceneName.StartsWith("city", StringComparison.OrdinalIgnoreCase);
	}

	private static Color DiagnosticColor(string name, float alpha)
	{
		alpha = Mathf.Clamp01(alpha);
		if (string.Equals(name, "red", StringComparison.OrdinalIgnoreCase)) return new Color(1f, 0f, 0f, alpha);
		if (string.Equals(name, "green", StringComparison.OrdinalIgnoreCase)) return new Color(0f, 1f, 0f, alpha);
		if (string.Equals(name, "blue", StringComparison.OrdinalIgnoreCase)) return new Color(0f, 0.35f, 1f, alpha);
		if (string.Equals(name, "yellow", StringComparison.OrdinalIgnoreCase)) return new Color(1f, 0.9f, 0f, alpha);
		return new Color(1f, 0f, 1f, alpha);
	}

	private static bool IsSupportedPrimitiveFieldType(Type type)
	{
		if (type == null)
			return false;
		return type == typeof(bool)
		       || type == typeof(byte)
		       || type == typeof(sbyte)
		       || type == typeof(short)
		       || type == typeof(ushort)
		       || type == typeof(int)
		       || type == typeof(uint)
		       || type == typeof(long)
		       || type == typeof(ulong)
		       || type == typeof(float)
		       || type == typeof(double)
		       || type == typeof(string)
		       || type.IsEnum;
	}

	private static bool TryConvertPrimitive(string value, Type type, out object converted, out string error)
	{
		converted = null;
		error = null;
		try
		{
			if (type == typeof(string))
				converted = value ?? "";
			else if (type == typeof(bool))
				converted = ParseBoolString(value, false);
			else if (type.IsEnum)
				converted = Enum.Parse(type, value ?? "", ignoreCase: true);
			else
				converted = Convert.ChangeType(value, type, System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		catch (Exception ex)
		{
			error = ex.GetType().Name + ": " + ex.Message;
			return false;
		}
	}

	private static string PrimitiveValueString(object value)
	{
		if (value == null)
			return "";
		if (value is bool b)
			return b ? "true" : "false";
		if (value is float f)
			return FloatJson(f);
		if (value is double d)
			return d.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
		return Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture) ?? "";
	}

	private static bool ParseBoolString(string value, bool fallback)
	{
		return bool.TryParse(value, out var parsed) ? parsed : fallback;
	}

	private static float ParseFloatString(string value, float fallback)
	{
		return float.TryParse(value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var parsed) ? parsed : fallback;
	}

	private static string UnityPath(Transform transform)
	{
		if (!transform)
			return "";
		var parts = new List<string>();
		var cursor = transform;
		var depth = 0;
		while (cursor && depth < 32)
		{
			parts.Add(cursor.name ?? "");
			cursor = cursor.parent;
			depth++;
		}
		parts.Reverse();
		return string.Join("/", parts);
	}

	private static Type FindType(string fullName)
	{
		if (string.IsNullOrWhiteSpace(fullName))
			return null;
		var requested = fullName.Trim();
		var requestedSimple = SimpleTypeName(requested);
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type type = null;
			try
			{
				type = assembly.GetType(requested, throwOnError: false, ignoreCase: false)
					?? assembly.GetType(requested, throwOnError: false, ignoreCase: true);
			}
			catch
			{
			}
			if (type != null)
				return type;
		}
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try
			{
				types = assembly.GetTypes();
			}
			catch (ReflectionTypeLoadException ex)
			{
				types = ex.Types;
			}
			catch
			{
				continue;
			}
			for (var i = 0; i < types.Length; i++)
			{
				var type = types[i];
				if (type == null)
					continue;
				if (string.Equals(type.FullName, requested, StringComparison.Ordinal)
				    || string.Equals(type.FullName, requested, StringComparison.OrdinalIgnoreCase)
				    || string.Equals(type.Name, requested, StringComparison.Ordinal)
				    || string.Equals(type.Name, requested, StringComparison.OrdinalIgnoreCase)
				    || string.Equals(GameMember.ReadObfuscatedName(type), requested, StringComparison.Ordinal)
				    || string.Equals(GameMember.ReadObfuscatedName(type), requestedSimple, StringComparison.Ordinal))
					return type;
			}
		}
		return null;
	}

	private static string FormatSignature(MethodInfo method)
	{
		var parameters = method.GetParameters();
		var parts = new string[parameters.Length];
		for (var i = 0; i < parameters.Length; i++)
		{
			var parameter = parameters[i];
			parts[i] = TypeDisplayName(parameter.ParameterType) + " " + parameter.Name;
		}
		return TypeDisplayName(method.ReturnType) + " " + method.Name + "(" + string.Join(", ", parts) + ")";
	}

	private static string TypeDisplayName(Type type)
	{
		return type == null ? "?" : (type.FullName ?? type.Name ?? "?");
	}

	private static void ParseDecompSignature(string signature, ref string methodName, ref string returnType, ref string parameterTypes)
	{
		if (string.IsNullOrWhiteSpace(signature))
			return;
		var trimmed = signature.Trim();
		var openParen = trimmed.IndexOf('(');
		var closeParen = trimmed.LastIndexOf(')');
		if (openParen > 0)
		{
			var before = trimmed.Substring(0, openParen).Trim();
			var lastSpace = before.LastIndexOf(' ');
			if (lastSpace > 0)
			{
				if (string.IsNullOrWhiteSpace(returnType))
					returnType = before.Substring(0, lastSpace).Trim();
				if (string.IsNullOrWhiteSpace(methodName))
					methodName = before.Substring(lastSpace + 1).Trim();
			}
			else if (string.IsNullOrWhiteSpace(methodName))
			{
				methodName = before;
			}
			if (closeParen > openParen && string.IsNullOrWhiteSpace(parameterTypes))
			{
				var rawParameters = SplitTopLevelList(trimmed.Substring(openParen + 1, closeParen - openParen - 1), ',');
				var parsedParameters = new List<string>();
				for (var i = 0; i < rawParameters.Length; i++)
				{
					var parameter = ExtractParameterType(rawParameters[i]);
					if (!string.IsNullOrWhiteSpace(parameter))
						parsedParameters.Add(parameter);
				}
				parameterTypes = string.Join(",", parsedParameters);
			}
			return;
		}
		if (string.IsNullOrWhiteSpace(methodName))
			methodName = trimmed;
	}

	private static string[] SplitTypeList(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return Array.Empty<string>();
		var raw = SplitTopLevelList(value, value.IndexOf(';') >= 0 ? ';' : ',');
		var result = new List<string>();
		for (var i = 0; i < raw.Length; i++)
		{
			var item = NormalizeTypeName(raw[i]);
			if (!string.IsNullOrWhiteSpace(item))
				result.Add(item);
		}
		return result.ToArray();
	}

	private static string[] SplitTopLevelList(string value, char separator)
	{
		if (string.IsNullOrEmpty(value))
			return Array.Empty<string>();
		var result = new List<string>();
		var start = 0;
		var depth = 0;
		for (var i = 0; i < value.Length; i++)
		{
			var ch = value[i];
			if (ch == '<' || ch == '(' || ch == '[')
				depth++;
			else if ((ch == '>' || ch == ')' || ch == ']') && depth > 0)
				depth--;
			else if (ch == separator && depth == 0)
			{
				result.Add(value.Substring(start, i - start).Trim());
				start = i + 1;
			}
		}
		result.Add(value.Substring(start).Trim());
		return result.ToArray();
	}

	private static string ExtractParameterType(string parameter)
	{
		if (string.IsNullOrWhiteSpace(parameter))
			return "";
		var value = parameter.Trim();
		var equals = value.IndexOf('=');
		if (equals >= 0)
			value = value.Substring(0, equals).Trim();
		var tokens = SplitTopLevelList(value, ' ');
		if (tokens.Length <= 1)
			return NormalizeTypeName(value);
		var last = tokens[tokens.Length - 1];
		if (last.IndexOf('.') < 0 && last.IndexOf('+') < 0 && last.IndexOf('<') < 0 && last.IndexOf('[') < 0)
		{
			value = value.Substring(0, Math.Max(0, value.Length - last.Length)).Trim();
		}
		return NormalizeTypeName(value);
	}

	private static int ScoreMethodCandidate(MethodInfo method, string expectedName, string expectedReturnType, string[] expectedParameters, int? expectedCallableOrdinal, int? runtimeCallableOrdinal, out List<string> reasons)
	{
		reasons = new List<string>();
		var score = 0;
		var obfuscatedName = GameMember.ReadObfuscatedName(method);
		if (!string.IsNullOrWhiteSpace(expectedName))
		{
			if (string.Equals(method.Name, expectedName, StringComparison.Ordinal))
			{
				score += 100;
				reasons.Add("runtime_name_exact");
			}
			if (string.Equals(obfuscatedName, expectedName, StringComparison.Ordinal))
			{
				score += 120;
				reasons.Add("obfuscated_name_exact");
			}
		}

		if (!string.IsNullOrWhiteSpace(expectedReturnType))
		{
			if (TypeNameMatches(expectedReturnType, method.ReturnType))
			{
				score += 30;
				reasons.Add("return_type_match");
			}
			else if (score > 0)
			{
				reasons.Add("return_type_mismatch");
				score -= 30;
			}
		}

		if (expectedParameters != null && expectedParameters.Length > 0)
		{
			var parameters = method.GetParameters();
			if (parameters.Length == expectedParameters.Length)
			{
				score += 40;
				reasons.Add("parameter_count_match");
				for (var i = 0; i < parameters.Length; i++)
				{
					if (TypeNameMatches(expectedParameters[i], parameters[i].ParameterType))
					{
						score += 10;
						reasons.Add("parameter_" + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + "_type_match");
					}
					else
					{
						score -= 8;
						reasons.Add("parameter_" + i.ToString(System.Globalization.CultureInfo.InvariantCulture) + "_type_mismatch");
					}
				}
			}
			else if (score > 0 || !string.IsNullOrWhiteSpace(expectedReturnType))
			{
				score -= 40;
				reasons.Add("parameter_count_mismatch");
			}
		}

		if (expectedCallableOrdinal.HasValue)
		{
			if (runtimeCallableOrdinal.HasValue && runtimeCallableOrdinal.Value == expectedCallableOrdinal.Value)
			{
				score += 65;
				reasons.Add("runtime_callable_ordinal_match");
			}
			else if (runtimeCallableOrdinal.HasValue && (score > 0 || !string.IsNullOrWhiteSpace(expectedReturnType) || (expectedParameters != null && expectedParameters.Length > 0)))
			{
				score -= 25;
				reasons.Add("runtime_callable_ordinal_mismatch");
			}
			else if (score > 0)
			{
				reasons.Add("runtime_callable_ordinal_unavailable");
			}
		}

		return reasons.Count == 0 ? 0 : score;
	}

	private static bool TypeNameMatches(string expected, Type actual)
	{
		if (actual == null || string.IsNullOrWhiteSpace(expected))
			return false;
		var normalizedExpected = NormalizeTypeName(expected);
		var actualType = actual.IsByRef ? actual.GetElementType() : actual;
		if (actualType == null)
			return false;
		var normalizedActualFull = NormalizeTypeName(actualType.FullName ?? actualType.Name ?? "");
		var normalizedActualName = NormalizeTypeName(actualType.Name ?? "");
		var normalizedActualSimple = SimpleTypeName(normalizedActualFull);
		var normalizedExpectedSimple = SimpleTypeName(normalizedExpected);
		var obfuscatedName = NormalizeTypeName(GameMember.ReadObfuscatedName(actualType) ?? "");
		return string.Equals(normalizedExpected, normalizedActualFull, StringComparison.OrdinalIgnoreCase)
			|| string.Equals(normalizedExpected, normalizedActualName, StringComparison.OrdinalIgnoreCase)
			|| string.Equals(normalizedExpectedSimple, normalizedActualSimple, StringComparison.OrdinalIgnoreCase)
			|| (!string.IsNullOrWhiteSpace(obfuscatedName) && string.Equals(normalizedExpected, obfuscatedName, StringComparison.Ordinal));
	}

	private static string MethodCandidateJson(MethodCandidateScore candidate)
	{
		var method = candidate.Method;
		var parameters = method.GetParameters();
		var parameterTypes = new string[parameters.Length];
		for (var i = 0; i < parameters.Length; i++)
			parameterTypes[i] = TypeDisplayName(parameters[i].ParameterType);
		return "{\"runtimeName\":\"" + EscapeJson(method.Name) + "\""
			+ ",\"obfuscatedName\":\"" + EscapeJson(GameMember.ReadObfuscatedName(method) ?? "") + "\""
			+ ",\"declaringType\":\"" + EscapeJson(TypeDisplayName(method.DeclaringType)) + "\""
			+ ",\"signature\":\"" + EscapeJson(FormatSignature(method)) + "\""
			+ ",\"runtimeCallableOrdinal\":" + NullableIntJson(candidate.RuntimeCallableOrdinal)
			+ ",\"returnType\":\"" + EscapeJson(TypeDisplayName(method.ReturnType)) + "\""
			+ ",\"parameterTypes\":" + StringArrayJson(parameterTypes)
			+ ",\"isStatic\":" + (method.IsStatic ? "true" : "false")
			+ ",\"score\":" + candidate.Score.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"reasons\":" + StringArrayJson(candidate.Reasons)
			+ "}";
	}

	private static int? RuntimeCallableOrdinal(MethodInfo target)
	{
		if (target == null || target.DeclaringType == null || !IsCallableRuntimeMethod(target))
			return null;
		MethodInfo[] methods;
		try
		{
			methods = target.DeclaringType.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
		}
		catch
		{
			return null;
		}

		var ordinal = 0;
		for (var i = 0; i < methods.Length; i++)
		{
			var method = methods[i];
			if (!IsCallableRuntimeMethod(method))
				continue;
			if (SameRuntimeMethod(method, target))
				return ordinal;
			ordinal++;
		}
		return null;
	}

	private static bool IsCallableRuntimeMethod(MethodInfo method)
	{
		if (method == null)
			return false;
		var name = method.Name ?? "";
		if (string.Equals(name, ".cctor", StringComparison.Ordinal) || string.Equals(name, ".ctor", StringComparison.Ordinal))
			return false;
		return !name.StartsWith("get_", StringComparison.Ordinal)
			&& !name.StartsWith("set_", StringComparison.Ordinal)
			&& !name.StartsWith("add_", StringComparison.Ordinal)
			&& !name.StartsWith("remove_", StringComparison.Ordinal);
	}

	private static bool SameRuntimeMethod(MethodInfo left, MethodInfo right)
	{
		if (ReferenceEquals(left, right))
			return true;
		try
		{
			return left != null
				&& right != null
				&& left.MetadataToken == right.MetadataToken
				&& Equals(left.Module, right.Module);
		}
		catch
		{
			return false;
		}
	}

	private static string NormalizeTypeName(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return "";
		var normalized = value.Trim();
		if (normalized.StartsWith("global::", StringComparison.Ordinal))
			normalized = normalized.Substring("global::".Length);
		var prefixes = new[] { "ref ", "out ", "in ", "params " };
		for (var i = 0; i < prefixes.Length; i++)
		{
			if (normalized.StartsWith(prefixes[i], StringComparison.Ordinal))
				normalized = normalized.Substring(prefixes[i].Length).TrimStart();
		}
		while (normalized.EndsWith("&", StringComparison.Ordinal))
			normalized = normalized.Substring(0, normalized.Length - 1).TrimEnd();
		return normalized;
	}

	private static string SimpleTypeName(string value)
	{
		if (string.IsNullOrWhiteSpace(value))
			return "";
		var normalized = NormalizeTypeName(value);
		var arraySuffix = normalized.EndsWith("[]", StringComparison.Ordinal) ? "[]" : "";
		if (arraySuffix.Length > 0)
			normalized = normalized.Substring(0, normalized.Length - arraySuffix.Length);
		var genericTick = normalized.IndexOf('`');
		if (genericTick >= 0)
			normalized = normalized.Substring(0, genericTick);
		var lastDot = normalized.LastIndexOf('.');
		var lastPlus = normalized.LastIndexOf('+');
		var last = Math.Max(lastDot, lastPlus);
		if (last >= 0 && last + 1 < normalized.Length)
			normalized = normalized.Substring(last + 1);
		return normalized + arraySuffix;
	}

	private static string ReadStatusJson()
	{
		try
		{
			var path = Path.Combine(BridgeDirectory, "status.json");
			return File.Exists(path) ? File.ReadAllText(path) : "{}";
		}
		catch
		{
			return "{}";
		}
	}

	private static string RecipeSummaryJson()
	{
		return "{\"enabled\":" + _recipes.EnabledCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"disabled\":" + _recipes.DisabledCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"errors\":" + _recipes.ErrorCount.ToString(System.Globalization.CultureInfo.InvariantCulture) + "}";
	}

	private static string TownUiStateJson(LiveProbeTownUiState state)
	{
		if (state == null)
			return "{}";
		return "{"
			+ "\"activeScene\":\"" + EscapeJson(state.ActiveScene ?? "") + "\""
			+ ",\"cachedFraction\":\"" + EscapeJson(state.CachedFraction ?? "") + "\""
			+ ",\"currentFraction\":\"" + EscapeJson(state.CurrentFraction ?? "") + "\""
			+ ",\"cachedWrapperPresent\":" + (state.CachedWrapperPresent ? "true" : "false")
			+ ",\"cachedWrapperKnownType\":" + (state.CachedWrapperKnownType ? "true" : "false")
			+ ",\"cachedWrapperType\":\"" + EscapeJson(state.CachedWrapperType ?? "") + "\""
			+ ",\"currentCityDataNonNull\":" + (state.CurrentCityDataNonNull ? "true" : "false")
			+ ",\"currentCityDataType\":\"" + EscapeJson(state.CurrentCityDataType ?? "") + "\""
			+ ",\"currentCityConfigNonNull\":" + (state.CurrentCityConfigNonNull ? "true" : "false")
			+ ",\"currentCityConfigType\":\"" + EscapeJson(state.CurrentCityConfigType ?? "") + "\""
			+ ",\"layers\":" + TownLayerStateJson(state.Layers)
			+ "}";
	}

	private static string TownLayerRefreshResultJson(LiveProbeTownLayerRefreshResult result)
	{
		if (result == null)
			return "{}";
		return "{"
			+ "\"ok\":" + (result.Ok ? "true" : "false")
			+ ",\"errorCode\":\"" + EscapeJson(result.ErrorCode ?? "") + "\""
			+ ",\"errorMessage\":\"" + EscapeJson(result.ErrorMessage ?? "") + "\""
			+ ",\"oldFraction\":\"" + EscapeJson(result.OldFraction ?? "") + "\""
			+ ",\"oldCityDataNonNull\":" + (result.OldCityDataNonNull ? "true" : "false")
			+ ",\"oldCityConfigNonNull\":" + (result.OldCityConfigNonNull ? "true" : "false")
			+ ",\"wrapperType\":\"" + EscapeJson(result.WrapperType ?? "") + "\""
			+ ",\"newFraction\":\"" + EscapeJson(result.NewFraction ?? "") + "\""
			+ ",\"newCityDataNonNull\":" + (result.NewCityDataNonNull ? "true" : "false")
			+ ",\"newCityConfigNonNull\":" + (result.NewCityConfigNonNull ? "true" : "false")
			+ ",\"layersBefore\":" + TownLayerStateJson(result.LayersBefore)
			+ ",\"layersAfter\":" + TownLayerStateJson(result.LayersAfter)
			+ "}";
	}

	private static string TownLayerStateJson(LiveProbeTownLayerState state)
	{
		if (state == null)
			return "{}";
		return "{"
			+ "\"rootExists\":" + (state.RootExists ? "true" : "false")
			+ ",\"rootActive\":" + (state.RootActive ? "true" : "false")
			+ ",\"rootObjectId\":" + state.RootObjectId.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"rootPath\":\"" + EscapeJson(state.RootPath ?? "") + "\""
			+ ",\"rootScene\":\"" + EscapeJson(state.RootScene ?? "") + "\""
			+ ",\"activeLayerCount\":" + state.ActiveLayerCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"graphicCount\":" + state.GraphicCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ ",\"rawImageCount\":" + state.RawImageCount.ToString(System.Globalization.CultureInfo.InvariantCulture)
			+ "}";
	}

	private static string ObjectSummaryJson(object value, int fieldLimit)
	{
		if (value == null)
			return "{\"isNull\":true}";
		var runtimeValue = UnwrapNativeTypedObject(value, out var reflectedType);
		var type = reflectedType ?? runtimeValue.GetType();
		var scalarValue = TryFormatSummaryScalar(runtimeValue, type, out var scalarText)
			? ",\"value\":\"" + EscapeJson(scalarText ?? "") + "\""
			: "";
		var fields = new List<string>();
		try
		{
			var all = type.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
			for (var i = 0; i < all.Length && fields.Count < Math.Max(0, fieldLimit); i++)
			{
				var field = all[i];
				if (!IsSupportedSummaryFieldType(field.FieldType))
					continue;
				string text;
				try
				{
					var raw = field.GetValue(runtimeValue);
					text = raw == null ? "" : Convert.ToString(raw, System.Globalization.CultureInfo.InvariantCulture);
				}
				catch (Exception ex)
				{
					text = "<" + ex.GetType().Name + ">";
				}
				if (text != null && text.Length > 160)
					text = text.Substring(0, 160);
				fields.Add("{\"name\":\"" + EscapeJson(field.Name) + "\",\"fieldType\":\"" + EscapeJson(TypeDisplayName(field.FieldType)) + "\",\"value\":\"" + EscapeJson(text ?? "") + "\"}");
			}
		}
		catch
		{
		}
		return "{"
			+ "\"isNull\":false"
			+ ",\"type\":\"" + EscapeJson(type.FullName ?? type.Name ?? "") + "\""
			+ scalarValue
			+ ",\"fields\":[" + string.Join(",", fields) + "]"
			+ "}";
	}

	private static bool TryFormatSummaryScalar(object value, Type type, out string text)
	{
		text = null;
		if (value == null || type == null || !IsSupportedSummaryFieldType(type))
			return false;
		try
		{
			text = Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture) ?? "";
			if (text.Length > 240)
				text = text.Substring(0, 240);
			return true;
		}
		catch (Exception ex)
		{
			text = "<" + ex.GetType().Name + ">";
			return true;
		}
	}

	private static bool IsSupportedSummaryFieldType(Type type)
	{
		return type != null
		       && (type.IsPrimitive
		           || type.IsEnum
		           || type == typeof(string)
		           || type == typeof(decimal));
	}

	private static string OkResponse(string id, string body)
	{
		return "{\"id\":\"" + EscapeJson(id) + "\",\"ok\":true," + body + "}";
	}

	private static string ErrorResponse(string id, string code, string message)
	{
		return "{\"id\":\"" + EscapeJson(id) + "\",\"ok\":false,\"error\":{\"code\":\""
			+ EscapeJson(code) + "\",\"message\":\"" + EscapeJson(message) + "\"}}";
	}

	internal static void WriteAllTextAtomic(string path, string text)
	{
		var dir = Path.GetDirectoryName(path);
		if (!string.IsNullOrEmpty(dir))
			Directory.CreateDirectory(dir);
		// Stable temp name — avoid Guid.tmp pile-up when delete/move fails under load.
		var tmp = path + ".tmp";
		File.WriteAllText(tmp, text ?? "");
		if (File.Exists(path))
			File.Delete(path);
		File.Move(tmp, path);
	}

	private static RecipeManifestSummary LoadRecipeManifest(ManualLogSource log, string path)
	{
		var summary = new RecipeManifestSummary();
		if (!File.Exists(path))
		{
			log?.LogWarning(GrepKey + " no recipe manifest at " + path + "; workbench has no live recipes.");
			return summary;
		}

		try
		{
			var text = File.ReadAllText(path);
			if (!Regex.IsMatch(text, "\"recipes\"\\s*:", RegexOptions.IgnoreCase))
			{
				summary.ErrorCount++;
				log?.LogWarning(GrepKey + " manifest ignored: missing top-level recipes array.");
				return summary;
			}

			var recipeMatches = Regex.Matches(text, "\\{[^{}]*\"id\"\\s*:[^{}]*\\}", RegexOptions.IgnoreCase);
			if (recipeMatches.Count == 0)
			{
				log?.LogWarning(GrepKey + " manifest contains no flat recipe objects with ids.");
				return summary;
			}

			foreach (Match match in recipeMatches)
			{
				if (!ValidateRecipe(log, match.Value, out var enabled))
				{
					summary.ErrorCount++;
					continue;
				}

				if (enabled)
					summary.EnabledCount++;
				else
					summary.DisabledCount++;
			}
		}
		catch (Exception ex)
		{
			summary.ErrorCount++;
			log?.LogWarning(GrepKey + " manifest parse failed: " + ex.Message);
		}

		return summary;
	}

	private static bool ValidateRecipe(ManualLogSource log, string recipe, out bool enabled)
	{
		enabled = ReadBool(recipe, "enabled", false);
		var id = ReadString(recipe, "id");
		var trigger = ReadString(recipe, "trigger");
		var action = ReadString(recipe, "action");

		if (string.IsNullOrWhiteSpace(id))
		{
			log?.LogWarning(GrepKey + " recipe ignored: missing id.");
			return false;
		}

		if (string.IsNullOrWhiteSpace(trigger) || !KnownTriggers.Contains(trigger))
		{
			log?.LogWarning(GrepKey + " recipe '" + id + "' ignored: unknown trigger '" + (trigger ?? "") + "'.");
			return false;
		}

		if (string.IsNullOrWhiteSpace(action) || !KnownActions.Contains(action))
		{
			log?.LogWarning(GrepKey + " recipe '" + id + "' ignored: unknown action '" + (action ?? "") + "'.");
			return false;
		}

		if (string.Equals(action, "setPrimitiveField", StringComparison.OrdinalIgnoreCase)
		    && !ReadBool(recipe, "allowMutation", false))
		{
			log?.LogWarning(GrepKey + " recipe '" + id + "' ignored: setPrimitiveField requires allowMutation=true.");
			return false;
		}

		if (string.Equals(action, "invokeKnownSafeMethod", StringComparison.OrdinalIgnoreCase)
		    && (!ReadBool(recipe, "allowlistedMethod", false)
		        || string.IsNullOrWhiteSpace(ReadString(recipe, "declaringType"))
		        || string.IsNullOrWhiteSpace(ReadString(recipe, "methodName"))
		        || string.IsNullOrWhiteSpace(ReadString(recipe, "parameterShape"))))
		{
			log?.LogWarning(GrepKey + " recipe '" + id + "' ignored: invokeKnownSafeMethod requires allowlistedMethod=true, declaringType, methodName, and parameterShape.");
			return false;
		}

		return true;
	}

	private static string ReadString(string json, string key)
	{
		if (json != null && json.Length > MaxTextBytes)
			return null;
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return null;
		var match = Regex.Match(
			json,
			"\"" + Regex.Escape(key) + "\"\\s*:\\s*\"(?<value>(?:\\\\.|[^\"])*)\"",
			RegexOptions.IgnoreCase);
		return match.Success
			? Regex.Unescape(match.Groups["value"].Value)
			: null;
	}

	private static bool ReadBool(string json, string key, bool fallback)
	{
		if (json != null && json.Length > MaxTextBytes)
			return fallback;
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return fallback;
		var match = Regex.Match(
			json,
			"\"" + Regex.Escape(key) + "\"\\s*:\\s*(?<value>true|false|\"true\"|\"false\")",
			RegexOptions.IgnoreCase);
		if (!match.Success)
			return fallback;
		var value = match.Groups["value"].Value.Trim('"');
		return bool.TryParse(value, out var parsed) ? parsed : fallback;
	}

	private static long ReadLong(string json, string key, long fallback)
	{
		if (json != null && json.Length > MaxTextBytes)
			return fallback;
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return fallback;
		var match = Regex.Match(
			json,
			"\"" + Regex.Escape(key) + "\"\\s*:\\s*(?<value>-?[0-9]+)",
			RegexOptions.IgnoreCase);
		return match.Success && long.TryParse(match.Groups["value"].Value, out var parsed) ? parsed : fallback;
	}

	private static int ReadInt(string json, string key, int fallback)
	{
		if (json != null && json.Length > MaxTextBytes)
			return fallback;
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return fallback;
		var match = Regex.Match(
			json,
			"\"" + Regex.Escape(key) + "\"\\s*:\\s*(?<value>-?[0-9]+)",
			RegexOptions.IgnoreCase);
		return match.Success && int.TryParse(match.Groups["value"].Value, out var parsed) ? parsed : fallback;
	}

	private static int? ReadOptionalInt(string json, string key)
	{
		if (json != null && json.Length > MaxTextBytes)
			return null;
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return null;
		var match = Regex.Match(
			json,
			"\"" + Regex.Escape(key) + "\"\\s*:\\s*(?<value>-?[0-9]+)",
			RegexOptions.IgnoreCase);
		return match.Success && int.TryParse(match.Groups["value"].Value, out var parsed) ? parsed : (int?) null;
	}

	private static float ReadFloat(string json, string key, float fallback)
	{
		if (json != null && json.Length > MaxTextBytes)
			return fallback;
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return fallback;
		var match = Regex.Match(
			json,
			"\"" + Regex.Escape(key) + "\"\\s*:\\s*(?<value>-?[0-9]+(?:\\.[0-9]+)?)",
			RegexOptions.IgnoreCase);
		return match.Success && float.TryParse(match.Groups["value"].Value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var parsed) ? parsed : fallback;
	}

	private static string StringArrayJson(IEnumerable<string> values)
	{
		var items = new List<string>();
		foreach (var value in values)
			items.Add("\"" + EscapeJson(value) + "\"");
		return "[" + string.Join(",", items) + "]";
	}

	private static string NullableIntJson(int? value)
	{
		return value.HasValue ? value.Value.ToString(System.Globalization.CultureInfo.InvariantCulture) : "null";
	}

	internal static string EscapeJson(string value)
	{
		if (string.IsNullOrEmpty(value))
			return "";
		return value
			.Replace("\\", "\\\\")
			.Replace("\"", "\\\"")
			.Replace("\r", "\\r")
			.Replace("\n", "\\n")
			.Replace("\t", "\\t");
	}

	private struct RecipeManifestSummary
	{
		internal int EnabledCount;
		internal int DisabledCount;
		internal int ErrorCount;
	}

	private sealed class ExactGetterAllowlistEntry
	{
		internal string TargetTypeFullName;
		internal string MethodName;
		internal string ExpectedReturnTypeFullName;
		internal string Reason;
	}

	private sealed class VolatileOperationAllowlistEntry
	{
		internal string Kind;
		internal string TargetTypeFullName;
		internal string MethodName;
		internal string ExpectedReturnTypeFullName;
		internal string ParameterTypeFullNames;
		internal string MemberKind;
		internal string MemberName;
		internal string MemberTypeFullName;
		internal string Reason;
	}

	private sealed class MethodCandidateScore
	{
		internal MethodCandidateScore(MethodInfo method, int? runtimeCallableOrdinal, int score, List<string> reasons)
		{
			Method = method;
			RuntimeCallableOrdinal = runtimeCallableOrdinal;
			Score = score;
			Reasons = reasons;
		}

		internal MethodInfo Method { get; }
		internal int? RuntimeCallableOrdinal { get; }
		internal int Score { get; }
		internal List<string> Reasons { get; }
	}

	private sealed class NativeTypedObject
	{
		internal NativeTypedObject(object instance, Type reflectionType)
		{
			Instance = instance;
			ReflectionType = reflectionType;
		}

		internal object Instance { get; }
		internal Type ReflectionType { get; }
	}
}

public sealed class Homm3LiveProbeWorkbenchBridgeBehaviour : MonoBehaviour
{
	private int _lastFrame;

	private void Update()
	{
		if (Time.frameCount - _lastFrame < 15)
			return;
		_lastFrame = Time.frameCount;
		Homm3LiveProbeWorkbench.WriteStatus("ready");
		ProcessInbox();
	}

	private static void ProcessInbox()
	{
		var bridgeDir = Homm3LiveProbeWorkbench.BridgeDirectory;
		if (string.IsNullOrWhiteSpace(bridgeDir))
			return;
		var inbox = Path.Combine(bridgeDir, "inbox");
		var outbox = Path.Combine(bridgeDir, "outbox");
		var processed = Path.Combine(bridgeDir, "processed");
		try
		{
			if (!Directory.Exists(inbox))
				return;
			var files = Directory.GetFiles(inbox, "*.json");
			Array.Sort(files, StringComparer.OrdinalIgnoreCase);
			var max = Math.Min(files.Length, 4);
			for (var i = 0; i < max; i++)
				ProcessOne(files[i], outbox, processed);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("HOMM3_LIVE_PROBE inbox processing failed: " + ex.Message);
		}
	}

	private static void ProcessOne(string requestPath, string outbox, string processed)
	{
		var name = Path.GetFileNameWithoutExtension(requestPath);
		var responsePath = Path.Combine(outbox, name + ".json");
		var processedPath = Path.Combine(processed, name + ".json");
		try
		{
			var text = File.ReadAllText(requestPath);
			var response = Homm3LiveProbeWorkbench.HandleBridgeRequest(text);
			Homm3LiveProbeWorkbench.WriteAllTextAtomic(responsePath, response);
			if (File.Exists(processedPath))
				File.Delete(processedPath);
			File.Move(requestPath, processedPath);
		}
		catch (Exception ex)
		{
			Homm3LiveProbeWorkbench.WriteAllTextAtomic(responsePath, "{\"id\":\"" + Homm3LiveProbeWorkbench.EscapeJson(name) + "\",\"ok\":false,\"error\":{\"code\":\"bridge_exception\",\"message\":\"" + Homm3LiveProbeWorkbench.EscapeJson(ex.Message) + "\"}}");
			try
			{
				if (File.Exists(requestPath))
					File.Delete(requestPath);
			}
			catch
			{
			}
		}
	}
}
