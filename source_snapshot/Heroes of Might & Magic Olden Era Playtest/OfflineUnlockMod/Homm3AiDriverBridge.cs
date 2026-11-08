using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using Hex.MainMenu;
using Hex.UI;
using Hex.UI.GeneralKit;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

internal static partial class Homm3AiDriverBridge
{
	internal const string FlagFileName = "homm3_ai_driver.flag";
	internal const string BridgeDirectoryName = "ai_driver_bridge";
	internal const string SchemaVersion = "ai-driver.v0.source-prepared";
	private const string GrepKey = "HOMM3_AI_DRIVER";
	private const int MaxTextBytes = 1024 * 1024;

	private static bool _configured;
	private static bool _bridgeRegistered;
	private static bool _bridgeAttached;
	private static bool _bridgeAttachPatched;
	private static ManualLogSource _log;
	private static int _lastStatusWriteFrame = int.MinValue;
	private static string _lastStatusState;
	private const int StatusWriteMinFrameGap = 30;

	private static string _lastObservationId;
	private static string _lastScreenId;
	private static readonly Dictionary<string, ObservedActionRecord> _lastActions = new Dictionary<string, ObservedActionRecord>(StringComparer.Ordinal);

	private sealed class ObservedActionRecord
	{
		internal string ObservationId;
		internal string ScreenId;
		internal string ActionId;
		internal string Kind;
		internal string Role;
		internal string Label;
		internal string TargetFingerprint;
		internal string Path;
		internal int InstanceId;
	}

	internal static string BridgeDirectory { get; private set; }
	internal static string BridgeToken { get; private set; }

	internal static void Configure(ManualLogSource log, LauncherConfig cfg, Harmony harmony)
	{
		if (_configured)
			return;

		var enabled = cfg != null && cfg.Homm3AiDriverBridge;
		enabled = enabled || Homm3DiagnosticFlags.IsEnabled(FlagFileName);
		if (!enabled)
			return;

		_configured = true;
		_log = log;

#if !OFFICIAL_DEOBF_BUILD
		log?.LogWarning(GrepKey + " disabled: first AI driver target is Golden Era; rebuild with -p:OfficialDeobfBuild=true.");
		return;
#else
		if (harmony == null)
		{
			log?.LogWarning(GrepKey + " disabled: Harmony instance was not available during plugin load.");
			return;
		}

		log?.LogWarning(GrepKey + " source-prepared: file bridge enabled with status, ai_observe, fresh-observation ai_act, screen_dump, visible_snapshot, hover_snapshot, focus_snapshot (SR utterance), source-prepared pilot_key/pilot_pointer_move/pilot_click, native-proven ai_grant_law_points, native-proven ai_grant_resources, native-canApply ai_buy_law, and configured-path ai_start_match. ai_open_town, ai_start_combat, and pilot_drag remain absent until proven.");
		Homm3AiDriverFogCache.TryRegister(harmony, log);
		Homm3AiDriverLogicHeroRegistry.TryRegister(harmony, log);
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
			CleanupOrphanStatusTemps(BridgeDirectory);
			BridgeToken = Guid.NewGuid().ToString("N");
			WriteAllTextAtomic(Path.Combine(BridgeDirectory, "token.txt"), BridgeToken);
			WriteStatus("starting", force: true);

			if (!_bridgeAttachPatched)
			{
				var start = AccessTools.Method(typeof(ScMainMenu), nameof(ScMainMenu.Start));
				var postfix = AccessTools.Method(typeof(Homm3AiDriverBridge), nameof(AfterMainMenuStartAttachBridge));
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
				ClassInjector.RegisterTypeInIl2Cpp<Homm3AiDriverBridgeBehaviour>();
				_bridgeRegistered = true;
			}

			var go = new GameObject("Homm3AiDriverBridge");
			go.hideFlags = HideFlags.HideAndDontSave;
			go.AddComponent<Homm3AiDriverBridgeBehaviour>();
			UnityObject.DontDestroyOnLoad(go);
			_bridgeAttached = true;
			_log?.LogWarning(GrepKey + " Unity file-bridge host attached after scene load at " + BridgeDirectory + ".");
		}
		catch (Exception ex)
		{
			_log?.LogWarning(GrepKey + " Unity file-bridge host attach failed: " + ex);
		}
	}

	internal static void WriteStatus(string state, bool force = false)
	{
		if (string.IsNullOrWhiteSpace(BridgeDirectory))
			return;
		try
		{
			var frame = Time.frameCount;
			var normalized = state ?? "unknown";
			if (!force
			    && string.Equals(normalized, _lastStatusState, StringComparison.Ordinal)
			    && frame - _lastStatusWriteFrame < StatusWriteMinFrameGap)
				return;

			var json = "{"
				+ "\"ok\":true,"
				+ "\"state\":\"" + EscapeJson(normalized) + "\","
				+ "\"schemaVersion\":\"" + EscapeJson(SchemaVersion) + "\","
				+ "\"build\":\"" + EscapeJson(Plugin.PluginVersion) + "\","
				+ "\"profile\":\"OfficialDeobf\","
				+ "\"frame\":" + frame.ToString(System.Globalization.CultureInfo.InvariantCulture) + ","
				+ "\"scene\":\"" + EscapeJson(SceneManager.GetActiveScene().name ?? "") + "\","
				+ "\"commands\":[\"status\",\"ai_observe\",\"ai_act\",\"screen_dump\",\"visible_snapshot\",\"hover_snapshot\",\"focus_snapshot\",\"pilot_key\",\"pilot_pointer_move\",\"pilot_click\",\"ai_grant_law_points\",\"ai_grant_resources\",\"ai_buy_law\",\"ai_start_match\"],"
				+ "\"absentCommands\":[\"ai_open_town\",\"ai_start_combat\",\"pilot_drag\"],"
				+ "\"note\":\"AI driver bridge is separate from live_probe_bridge. focus_snapshot is the SR utterance surface (speechSafe). screen_dump/visible_snapshot remain AI catalogs (not SR-safe). hover_snapshot is the raw hover lane. pilot_* are human-parity input. ai_observe/ai_act stay the safe observed-UI path. Town/combat setup and pilot_drag remain absent until proven.\""
				+ "}";
			WriteAllTextAtomic(Path.Combine(BridgeDirectory, "status.json"), json);
			_lastStatusWriteFrame = frame;
			_lastStatusState = normalized;
		}
		catch (Exception ex)
		{
			_log?.LogWarning(GrepKey + " status write failed: " + ex.Message);
		}
	}

	private static void CleanupOrphanStatusTemps(string bridgeDirectory)
	{
		try
		{
			foreach (var path in Directory.GetFiles(bridgeDirectory, "status.json.*.tmp"))
			{
				try
				{
					File.Delete(path);
				}
				catch
				{
				}
			}
			var stableTmp = Path.Combine(bridgeDirectory, "status.json.tmp");
			if (File.Exists(stableTmp))
			{
				try
				{
					File.Delete(stableTmp);
				}
				catch
				{
				}
			}
		}
		catch
		{
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
				case "ai_observe":
					var uiLimit = ReadIntBounded(requestJson, "uiLimit", 128, 1, 256);
					return OkResponse(id, "\"observation\":" + BuildAiObserveSourcePreparedJson(uiLimit));
				case "ai_act":
					return BuildAiActResponse(id, requestJson);
				case "screen_dump":
					return BuildScreenDumpResponse(id, requestJson);
				case "visible_snapshot":
					return BuildVisibleSnapshotResponse(id, requestJson);
				case "hover_snapshot":
					return BuildHoverSnapshotResponse(id);
				case "focus_snapshot":
					return BuildFocusSnapshotResponse(id);
				case "pilot_key":
					return BuildPilotKeyResponse(id, requestJson);
				case "pilot_pointer_move":
					return BuildPilotPointerMoveResponse(id, requestJson);
				case "pilot_click":
					return BuildPilotClickResponse(id, requestJson);
				case "ai_grant_law_points":
					return BuildAiGrantLawPointsResponse(id, requestJson);
				case "ai_grant_resources":
					return BuildAiGrantResourcesResponse(id, requestJson);
				case "ai_buy_law":
					return BuildAiBuyLawResponse(id, requestJson);
				case "ai_start_match":
					return BuildAiStartMatchResponse(id);
				default:
					return ErrorResponse(id, "unknown_command", "Unsupported AI driver command '" + command + "'. Unproven commands are intentionally absent from this bridge.");
			}
		}
		catch (Exception ex)
		{
			return ErrorResponse(id, "exception", ex.GetType().Name + ": " + ex.Message);
		}
	}

	// Read-only observation builder. This route emits observations/actions but never executes gameplay or input.
	internal static string BuildAiObserveSourcePreparedJson(int requestedUiLimit)
	{
		var uiLimit = Math.Max(1, Math.Min(requestedUiLimit <= 0 ? 128 : requestedUiLimit, 256));
		var observationId = Guid.NewGuid().ToString("N");
		var activeScene = SceneManager.GetActiveScene();
		var sceneName = activeScene.IsValid() ? activeScene.name ?? "" : "";
		var mode = InferModeFromLoadedScenes(sceneName);
		var gaps = new List<string>();
		var uiElements = new List<string>(uiLimit);
		var actions = new List<string>(uiLimit);
		var actionRecords = new List<ObservedActionRecord>(uiLimit);

		if (mode == "unknown")
			gaps.Add(GapJson("mode_unknown", "Active scene name did not map to a known AI driver mode.", false));

		var selectables = CollectSupportedUiComponents(Math.Max(uiLimit * 4, 256), gaps);
		selectables.Sort(CompareUiComponentForStableObservation);
		for (var i = 0; i < selectables.Count && uiElements.Count < uiLimit; i++)
		{
			var component = selectables[i];
			if (!component || !component.gameObject || !component.gameObject.activeInHierarchy)
				continue;
			var go = component.gameObject;
			var rectTransform = go.GetComponent<RectTransform>();
			if (rectTransform == null)
				continue;
			var path = UnityPath(component.transform);
			var rectJson = ScreenRectJson(rectTransform, go.GetComponentInParent<Canvas>());
			var visible = go.activeInHierarchy && HasPositiveRect(rectTransform);
			var typeName = ComponentTypeName(component);
			var enabled = TryReadSupportedUiState(component, typeName, out var interactableValue);
			var interactable = enabled && interactableValue;
			var role = UiRole(typeName);
			var elementId = StableElementId("ui", go.GetInstanceID(), path);
			var elementSceneName = go.scene.IsValid() ? go.scene.name ?? "" : "";
			var fingerprint = FingerprintJson("screen_path", elementSceneName + "|" + path + "|" + go.GetInstanceID().ToString(CultureInfo.InvariantCulture));
			var text = UiText(go);
			uiElements.Add("{"
				+ "\"id\":\"" + EscapeJson(elementId) + "\","
				+ "\"role\":\"" + EscapeJson(role) + "\","
				+ "\"name\":\"" + EscapeJson(go.name ?? "") + "\","
				+ "\"path\":\"" + EscapeJson(path) + "\","
				+ "\"text\":\"" + EscapeJson(text) + "\","
				+ "\"rect\":" + rectJson + ","
				+ "\"visible\":" + BoolJson(visible) + ","
				+ "\"enabled\":" + BoolJson(enabled) + ","
				+ "\"interactable\":" + BoolJson(interactable) + ","
				+ "\"fingerprint\":" + fingerprint
				+ "}");
			if (visible && interactable)
			{
				var actionKind = IsClickUiType(typeName) ? "click" : "submit";
				var label = text.Length == 0 ? go.name ?? "" : text;
				var actionId = StableElementId("action", go.GetInstanceID(), path + "|" + actionKind);
				actions.Add("{"
					+ "\"actionId\":\"" + EscapeJson(actionId) + "\","
					+ "\"kind\":\"" + actionKind + "\","
					+ "\"role\":\"" + EscapeJson(role) + "\","
					+ "\"targetId\":\"" + EscapeJson(elementId) + "\","
					+ "\"targetFingerprint\":" + fingerprint + ","
					+ "\"screenId\":\"__SCREEN_ID__\","
					+ "\"label\":\"" + EscapeJson(label) + "\""
					+ "}");
				actionRecords.Add(new ObservedActionRecord
				{
					ObservationId = observationId,
					ActionId = actionId,
					Kind = actionKind,
					Role = role,
					Label = label,
					TargetFingerprint = elementSceneName + "|" + path + "|" + go.GetInstanceID().ToString(CultureInfo.InvariantCulture),
					Path = path,
					InstanceId = go.GetInstanceID()
				});
			}
		}
		if (selectables.Count == 0)
			gaps.Add(GapJson("no_selectables", "No active supported Unity UI Selectable instances were present.", false));
		else if (uiElements.Count == 0)
			gaps.Add(GapJson("no_active_ui_elements", "Active supported UI Selectable instances existed, but none passed visible UI element gates.", false));
		else if (uiElements.Count >= uiLimit)
			gaps.Add(GapJson("ui_limit_reached", "UI element output reached the requested bound.", false));

		var screenId = StableScreenId(sceneName, mode, uiElements);
		for (var i = 0; i < actions.Count; i++)
			actions[i] = actions[i].Replace("__SCREEN_ID__", EscapeJson(screenId));
		_lastObservationId = observationId;
		_lastScreenId = screenId;
		_lastActions.Clear();
		for (var i = 0; i < actionRecords.Count; i++)
		{
			actionRecords[i].ScreenId = screenId;
			_lastActions[actionRecords[i].ActionId] = actionRecords[i];
		}

		return "{"
			+ "\"schemaVersion\":\"ai-driver.v1.observation\","
			+ "\"observationId\":\"" + EscapeJson(observationId) + "\","
			+ "\"screenId\":\"" + EscapeJson(screenId) + "\","
			+ "\"scene\":\"" + EscapeJson(sceneName) + "\","
			+ "\"frame\":" + Time.frameCount.ToString(CultureInfo.InvariantCulture) + ","
			+ "\"mode\":\"" + EscapeJson(mode) + "\","
			+ "\"timestamp\":\"" + EscapeJson(DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture)) + "\","
			+ "\"uiElements\":[" + string.Join(",", uiElements) + "],"
			+ "\"gameObjects\":[],"
			+ "\"actions\":[" + string.Join(",", actions) + "],"
			+ "\"gaps\":[" + string.Join(",", gaps) + "]"
			+ "}";
	}

	// Runtime-proven on 2026-06-19: this single route emitted visible/interactable UI actions and drove a fresh Button Hide click through ai_act.
	private static List<Component> CollectSupportedUiComponents(int scanLimit, List<string> gaps)
	{
		var result = new List<Component>(Math.Min(scanLimit, 256));
		var seen = new HashSet<int>();

		// Prefer Hex main-menu / HUD buttons first — Unity Selectable scans can saturate the bound with Settings/lobby leftovers.
		TryAppendTypedUiComponents(result, seen, scanLimit, FindObjectsOfTypeSafe<BhNavigationButton>());
		TryAppendTypedUiComponents(result, seen, scanLimit, FindObjectsOfTypeSafe<BhGenericButton>());

		// Prefer Selectable over FindObjectsOfType<Component>(true) — full Component scans hitch hard.
		Selectable[] selectables;
		try
		{
			selectables = UnityObject.FindObjectsOfType<Selectable>(true) ?? Array.Empty<Selectable>();
		}
		catch (Exception ex)
		{
			gaps.Add(GapJson("component_scan_failed", "Active supported UI selectable scan failed: " + ex.GetType().Name + ": " + ex.Message, true));
			return result;
		}

		for (var i = 0; i < selectables.Length && result.Count < scanLimit; i++)
		{
			var component = selectables[i];
			if (!component || !component.gameObject || !component.gameObject.activeInHierarchy || !component.gameObject.scene.IsValid())
				continue;
			if (!IsSupportedUiType(ComponentTypeName(component)))
				continue;
			var id = component.gameObject.GetInstanceID();
			if (seen.Add(id))
				result.Add(component);
		}

		if (result.Count >= scanLimit)
			gaps.Add(GapJson("selectable_scan_limit_reached", "Active supported UI selectable scan reached the hard observation bound.", false));
		return result;
	}

	private static T[] FindObjectsOfTypeSafe<T>() where T : UnityObject
	{
		try
		{
			return UnityObject.FindObjectsOfType<T>(true) ?? Array.Empty<T>();
		}
		catch
		{
			return Array.Empty<T>();
		}
	}

	private static void TryAppendTypedUiComponents<T>(List<Component> result, HashSet<int> seen, int scanLimit, T[] typed) where T : Component
	{
		if (typed == null)
			return;
		for (var i = 0; i < typed.Length && result.Count < scanLimit; i++)
		{
			var component = typed[i];
			if (!component || !component.gameObject || !component.gameObject.activeInHierarchy || !component.gameObject.scene.IsValid())
				continue;
			var id = component.gameObject.GetInstanceID();
			if (seen.Add(id))
				result.Add(component);
		}
	}

	private static int CompareUiComponentForStableObservation(Component left, Component right)
	{
		var leftPath = left && left.transform ? UnityPath(left.transform) : "";
		var rightPath = right && right.transform ? UnityPath(right.transform) : "";
		return string.Compare(leftPath, rightPath, StringComparison.Ordinal);
	}

	private static bool IsSupportedUiType(string typeName)
	{
		return IsClickUiType(typeName)
		       || string.Equals(typeName, "UnityEngine.UI.Slider", StringComparison.Ordinal)
		       || string.Equals(typeName, "UnityEngine.UI.Dropdown", StringComparison.Ordinal)
		       || string.Equals(typeName, "UnityEngine.UI.InputField", StringComparison.Ordinal)
		       || string.Equals(typeName, "UnityEngine.UI.Scrollbar", StringComparison.Ordinal)
		       || string.Equals(typeName, "Slider", StringComparison.Ordinal)
		       || string.Equals(typeName, "Dropdown", StringComparison.Ordinal)
		       || string.Equals(typeName, "InputField", StringComparison.Ordinal)
		       || string.Equals(typeName, "Scrollbar", StringComparison.Ordinal);
	}

	private static bool IsClickUiType(string typeName)
	{
		return string.Equals(typeName, "UnityEngine.UI.Button", StringComparison.Ordinal)
		       || string.Equals(typeName, "UnityEngine.UI.Toggle", StringComparison.Ordinal)
		       || string.Equals(typeName, "Button", StringComparison.Ordinal)
		       || string.Equals(typeName, "Toggle", StringComparison.Ordinal)
		       || string.Equals(typeName, "Hex.UI.GeneralKit.BhNavigationButton", StringComparison.Ordinal)
		       || string.Equals(typeName, "Hex.UI.BhNavigationButton", StringComparison.Ordinal)
		       || string.Equals(typeName, "BhNavigationButton", StringComparison.Ordinal)
		       || string.Equals(typeName, "Hex.UI.BhGenericButton", StringComparison.Ordinal)
		       || string.Equals(typeName, "BhGenericButton", StringComparison.Ordinal);
	}

	private static bool TryReadSupportedUiState(Component component, string typeName, out bool interactable)
	{
		interactable = false;
		try
		{
			if (string.Equals(typeName, "Hex.UI.GeneralKit.BhNavigationButton", StringComparison.Ordinal)
			    || string.Equals(typeName, "Hex.UI.BhNavigationButton", StringComparison.Ordinal)
			    || string.Equals(typeName, "BhNavigationButton", StringComparison.Ordinal))
			{
				var nav = component.TryCast<BhNavigationButton>();
				if (!nav) return false;
				interactable = nav.enabled && nav.gameObject.activeInHierarchy;
				return nav.enabled;
			}
			if (string.Equals(typeName, "Hex.UI.BhGenericButton", StringComparison.Ordinal)
			    || string.Equals(typeName, "BhGenericButton", StringComparison.Ordinal))
			{
				var generic = component.TryCast<BhGenericButton>();
				if (!generic) return false;
				interactable = generic.enabled && generic.gameObject.activeInHierarchy;
				return generic.enabled;
			}
			if (string.Equals(typeName, "UnityEngine.UI.Button", StringComparison.Ordinal) || string.Equals(typeName, "Button", StringComparison.Ordinal))
			{
				var button = component.TryCast<Button>();
				if (!button) return false;
				interactable = button.interactable;
				return button.enabled;
			}
			if (string.Equals(typeName, "UnityEngine.UI.Toggle", StringComparison.Ordinal) || string.Equals(typeName, "Toggle", StringComparison.Ordinal))
			{
				var toggle = component.TryCast<Toggle>();
				if (!toggle) return false;
				interactable = toggle.interactable;
				return toggle.enabled;
			}
			if (string.Equals(typeName, "UnityEngine.UI.Slider", StringComparison.Ordinal) || string.Equals(typeName, "Slider", StringComparison.Ordinal))
			{
				var slider = component.TryCast<Slider>();
				if (!slider) return false;
				interactable = slider.interactable;
				return slider.enabled;
			}
			if (string.Equals(typeName, "UnityEngine.UI.Dropdown", StringComparison.Ordinal) || string.Equals(typeName, "Dropdown", StringComparison.Ordinal))
			{
				var dropdown = component.TryCast<Dropdown>();
				if (!dropdown) return false;
				interactable = dropdown.interactable;
				return dropdown.enabled;
			}
			if (string.Equals(typeName, "UnityEngine.UI.InputField", StringComparison.Ordinal) || string.Equals(typeName, "InputField", StringComparison.Ordinal))
			{
				var input = component.TryCast<InputField>();
				if (!input) return false;
				interactable = input.interactable;
				return input.enabled;
			}
			if (string.Equals(typeName, "UnityEngine.UI.Scrollbar", StringComparison.Ordinal) || string.Equals(typeName, "Scrollbar", StringComparison.Ordinal))
			{
				var scrollbar = component.TryCast<Scrollbar>();
				if (!scrollbar) return false;
				interactable = scrollbar.interactable;
				return scrollbar.enabled;
			}
		}
		catch { }
		return false;
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
	private static string InferModeFromLoadedScenes(string activeSceneName)
	{
		var active = (activeSceneName ?? "").ToLowerInvariant();
		if (active.Contains("battle")) return "battle";
		if (active.Contains("city") || active.Contains("town")) return "town";
		if (active.Contains("session") || active.Contains("world") || active.Contains("map") || active.Contains("hud")) return "adventure_map";
		if (active.Contains("menu")) return "main_menu";
		if (active.Contains("load")) return "loading";

		var sceneCount = SceneManager.sceneCount;
		var sawMenu = false;
		var sawLoading = false;
		for (var i = 0; i < sceneCount; i++)
		{
			var scene = SceneManager.GetSceneAt(i);
			if (!scene.IsValid() || !scene.isLoaded)
				continue;
			var value = (scene.name ?? "").ToLowerInvariant();
			if (value.Contains("battle")) return "battle";
			if (value.Contains("city") || value.Contains("town")) return "town";
			if (value.Contains("session") || value.Contains("world") || value.Contains("map") || value.Contains("hud")) return "adventure_map";
			if (value.Contains("menu")) sawMenu = true;
			if (value.Contains("load")) sawLoading = true;
		}

		if (sawMenu) return "main_menu";
		if (sawLoading) return "loading";
		return "unknown";
	}
	private static string UiRole(string typeName)
	{
		if (string.Equals(typeName, "UnityEngine.UI.Button", StringComparison.Ordinal) || string.Equals(typeName, "Button", StringComparison.Ordinal)) return "button";
		if (string.Equals(typeName, "Hex.UI.GeneralKit.BhNavigationButton", StringComparison.Ordinal)
		    || string.Equals(typeName, "Hex.UI.BhNavigationButton", StringComparison.Ordinal)
		    || string.Equals(typeName, "BhNavigationButton", StringComparison.Ordinal)) return "button";
		if (string.Equals(typeName, "Hex.UI.BhGenericButton", StringComparison.Ordinal) || string.Equals(typeName, "BhGenericButton", StringComparison.Ordinal)) return "button";
		if (string.Equals(typeName, "UnityEngine.UI.Toggle", StringComparison.Ordinal) || string.Equals(typeName, "Toggle", StringComparison.Ordinal)) return "toggle";
		if (string.Equals(typeName, "UnityEngine.UI.Slider", StringComparison.Ordinal) || string.Equals(typeName, "Slider", StringComparison.Ordinal)) return "slider";
		if (string.Equals(typeName, "UnityEngine.UI.Scrollbar", StringComparison.Ordinal) || string.Equals(typeName, "Scrollbar", StringComparison.Ordinal)) return "scrollbar";
		if (string.Equals(typeName, "UnityEngine.UI.Dropdown", StringComparison.Ordinal) || string.Equals(typeName, "Dropdown", StringComparison.Ordinal)) return "dropdown";
		if (string.Equals(typeName, "UnityEngine.UI.InputField", StringComparison.Ordinal) || string.Equals(typeName, "InputField", StringComparison.Ordinal)) return "input";
		return "selectable";
	}
	private static string UiText(GameObject go)
	{
		try
		{
			var tmp = go.GetComponentInChildren<TMP_Text>(true);
			if (tmp && !string.IsNullOrWhiteSpace(tmp.text))
				return tmp.text.Trim();
			var text = go.GetComponentInChildren<Text>(true);
			if (text && !string.IsNullOrWhiteSpace(text.text))
				return text.text.Trim();
		}
		catch
		{
		}
		return "";
	}

	private static string ScreenRectJson(RectTransform rectTransform, Canvas canvas)
	{
		if (!TryGetScreenRect(rectTransform, canvas, out var minX, out var minY, out var maxX, out var maxY))
			return "{\"x\":0,\"y\":0,\"width\":0,\"height\":0}";
		return "{"
			+ "\"x\":" + minX.ToString("0.###", CultureInfo.InvariantCulture) + ","
			+ "\"y\":" + minY.ToString("0.###", CultureInfo.InvariantCulture) + ","
			+ "\"width\":" + Math.Max(0, maxX - minX).ToString("0.###", CultureInfo.InvariantCulture) + ","
			+ "\"height\":" + Math.Max(0, maxY - minY).ToString("0.###", CultureInfo.InvariantCulture)
			+ "}";
	}

	// IL2CPP: GetWorldCorners requires Il2CppStructArray; a managed Vector3[] silently leaves corners unset.
	private static bool TryGetScreenRect(RectTransform rectTransform, Canvas canvas, out float minX, out float minY, out float maxX, out float maxY)
	{
		minX = minY = maxX = maxY = 0f;
		if (!rectTransform)
			return false;
		try
		{
			var corners = new Il2CppStructArray<Vector3>(4);
			rectTransform.GetWorldCorners(corners);
			var root = canvas ? canvas.rootCanvas : null;
			Camera camera = null;
			if (root && root.renderMode != RenderMode.ScreenSpaceOverlay)
				camera = root.worldCamera ? root.worldCamera : Camera.main;
			minX = float.PositiveInfinity;
			minY = float.PositiveInfinity;
			maxX = float.NegativeInfinity;
			maxY = float.NegativeInfinity;
			for (var i = 0; i < corners.Length; i++)
			{
				var point = RectTransformUtility.WorldToScreenPoint(camera, corners[i]);
				minX = Math.Min(minX, point.x);
				minY = Math.Min(minY, point.y);
				maxX = Math.Max(maxX, point.x);
				maxY = Math.Max(maxY, point.y);
			}
			return !float.IsInfinity(minX) && !float.IsInfinity(minY) && !float.IsInfinity(maxX) && !float.IsInfinity(maxY);
		}
		catch
		{
			return false;
		}
	}

	private static bool HasPositiveRect(RectTransform rectTransform)
	{
		var rect = rectTransform.rect;
		return rect.width > 0.1f && rect.height > 0.1f;
	}

	private static string UnityPath(Transform transform)
	{
		if (!transform) return "";
		var parts = new List<string>();
		var current = transform;
		while (current)
		{
			parts.Add(current.name ?? "");
			current = current.parent;
		}
		parts.Reverse();
		return string.Join("/", parts);
	}

	private static string StableElementId(string prefix, int instanceId, string path)
	{
		return prefix + "-" + StableHash(instanceId.ToString(CultureInfo.InvariantCulture) + "|" + (path ?? ""));
	}

	private static string StableScreenId(string sceneName, string mode, List<string> uiElements)
	{
		var seed = (sceneName ?? "") + "|" + (mode ?? "") + "|" + uiElements.Count.ToString(CultureInfo.InvariantCulture);
		for (var i = 0; i < uiElements.Count && i < 24; i++)
			seed += "|" + uiElements[i];
		return "screen-" + StableHash(seed);
	}

	private static string StableHash(string value)
	{
		unchecked
		{
			var hash = 1469598103934665603UL;
			for (var i = 0; i < (value ?? "").Length; i++)
			{
				hash ^= value[i];
				hash *= 1099511628211UL;
			}
			return hash.ToString("x16", CultureInfo.InvariantCulture);
		}
	}

	private static string FingerprintJson(string kind, string value)
	{
		return "{\"kind\":\"" + EscapeJson(kind) + "\",\"value\":\"" + EscapeJson(value ?? "") + "\"}";
	}

	private static string GapJson(string code, string message, bool blocking)
	{
		return "{\"code\":\"" + EscapeJson(code) + "\",\"message\":\"" + EscapeJson(message) + "\",\"blocking\":" + BoolJson(blocking) + "}";
	}

	private static string BoolJson(bool value)
	{
		return value ? "true" : "false";
	}
	private static string BuildAiActResponse(string id, string requestJson)
	{
		var observationId = ReadString(requestJson, "observationId");
		var screenId = ReadString(requestJson, "screenId");
		var actionId = ReadString(requestJson, "actionId");
		var fingerprintKind = ReadString(requestJson, "kind");
		var fingerprintValue = ReadString(requestJson, "value");
		if (!string.Equals(fingerprintKind, "screen_path", StringComparison.Ordinal))
			return ErrorResponse(id, "unsupported_fingerprint", "ai_act currently accepts only screen_path target fingerprints emitted by ai_observe.");
		if (string.IsNullOrWhiteSpace(observationId) || string.IsNullOrWhiteSpace(screenId) || string.IsNullOrWhiteSpace(actionId) || string.IsNullOrWhiteSpace(fingerprintValue))
			return ErrorResponse(id, "bad_request", "ai_act requires observationId, screenId, actionId, and targetFingerprint.value.");
		if (!string.Equals(observationId, _lastObservationId, StringComparison.Ordinal))
			return ErrorResponse(id, "stale_observation", "Observation id is not the latest ai_observe result.");
		if (!string.Equals(screenId, _lastScreenId, StringComparison.Ordinal))
			return ErrorResponse(id, "stale_screen", "Screen id is not the latest ai_observe result.");
		if (!_lastActions.TryGetValue(actionId, out var record))
			return ErrorResponse(id, "unknown_action", "Action id was not emitted by the latest ai_observe result.");
		if (!string.Equals(record.TargetFingerprint, fingerprintValue, StringComparison.Ordinal))
			return ErrorResponse(id, "fingerprint_mismatch", "Action target fingerprint does not match the latest observed action.");

		var component = FindObservedActionComponent(record, out var errorCode, out var error);
		if (!component)
			return ErrorResponse(id, errorCode ?? "target_missing", error ?? "Observed action target is no longer available.");
		var go = component.gameObject;
		var rectTransform = go.GetComponent<RectTransform>();
		if (rectTransform == null || !HasPositiveRect(rectTransform))
			return ErrorResponse(id, "target_not_visible", "Observed action target no longer has a visible positive RectTransform.");
		var typeName = ComponentTypeName(component);
		if (!TryReadSupportedUiState(component, typeName, out var interactable) || !interactable)
			return ErrorResponse(id, "target_not_interactable", "Observed action target is no longer enabled and interactable.");

		if (!DispatchObservedAction(record, go, rectTransform, out var dispatchError))
			return ErrorResponse(id, "dispatch_failed", dispatchError ?? "Unity EventSystem dispatch failed.");
		var postObservation = BuildAiObserveSourcePreparedJson(64);
		return OkResponse(id, "\"action\":{\"actionId\":\"" + EscapeJson(actionId) + "\",\"kind\":\"" + EscapeJson(record.Kind) + "\",\"label\":\"" + EscapeJson(record.Label) + "\"},\"postObservation\":" + postObservation);
	}

	// Runtime route is the same configured local match startup path used by menu interception and auto-launch.
	private static string BuildAiStartMatchResponse(string id)
	{
		var mode = InferModeFromLoadedScenes(SceneManager.GetActiveScene().name ?? "");
		if (!string.Equals(mode, "main_menu", StringComparison.Ordinal))
			return ErrorResponse(id, "ai_start_match_wrong_mode", "ai_start_match requires main_menu mode; current mode is '" + mode + "'.");
		if (!ModActions.TryStartConfiguredNewGameForAiDriver(out var resultJson, out var failure))
			return ErrorResponse(id, "ai_start_match_failed", failure ?? "Configured local match startup failed closed.");
		return OkResponse(id, "\"command\":\"ai_start_match\"," + resultJson + ",\"postObservation\":" + BuildAiObserveSourcePreparedJson(64));
	}
	// Runtime route is the exact native dtj.LevelUp bridge already proven for custom faction law points.
	private static string BuildAiGrantLawPointsResponse(string id, string requestJson)
	{
		var factionSid = ReadString(requestJson, "factionSid");
		var count = ReadIntBounded(requestJson, "count", 1, 1, 10);
		if (!Homm3CustomFactionLawRuntime.TryNativeLawLevelUpForBridge(factionSid, count, out var resultJson, out var failure))
			return ErrorResponse(id, "ai_grant_law_points_failed", failure ?? "Native law-point grant route failed closed.");
		return OkResponse(id, "\"command\":\"ai_grant_law_points\"," + resultJson + ",\"postObservation\":" + BuildAiObserveSourcePreparedJson(64));
	}
	// Runtime route is exact Data.Side.res -> ResHeap.<resource> -> Resource.addValue(int) with before/after confirmation.
	private static string BuildAiGrantResourcesResponse(string id, string requestJson)
	{
		var factionSid = ReadString(requestJson, "factionSid");
		var resourceName = ReadString(requestJson, "resourceName");
		var amount = ReadIntBounded(requestJson, "amount", 1, 1, 1000000);
		if (!Homm3CustomFactionLawRuntime.TryGrantResourceForBridge(factionSid, resourceName, amount, out var resultJson, out var failure))
			return ErrorResponse(id, "ai_grant_resources_failed", failure ?? "Native resource grant route failed closed.");
		return OkResponse(id, "\"command\":\"ai_grant_resources\"," + resultJson + ",\"postObservation\":" + BuildAiObserveSourcePreparedJson(64));
	}
	// Runtime route is the exact native FractionLaws canApply/xpl bridge already proven for guarded law apply.
	private static string BuildAiBuyLawResponse(string id, string requestJson)
	{
		var lawSid = ReadString(requestJson, "lawSid");
		var rank = ReadIntBounded(requestJson, "rank", 1, 1, 3);
		if (!Homm3CustomFactionLawRuntime.TryDescribeNativeLawStateForBridge(lawSid, rank, true, out var resultJson, out var failure))
			return ErrorResponse(id, "ai_buy_law_failed", failure ?? "Native law apply route failed closed.");
		if (!JsonBool(resultJson, "applyInvoked"))
			return ErrorResponse(id, "ai_buy_law_not_applied", "Native canApply/apply route did not invoke apply. State: {" + resultJson + "}");
		return OkResponse(id, "\"command\":\"ai_buy_law\"," + resultJson + ",\"postObservation\":" + BuildAiObserveSourcePreparedJson(64));
	}
	private static Component FindObservedActionComponent(ObservedActionRecord record, out string errorCode, out string error)
	{
		errorCode = "target_missing";
		error = null;
		Component matched = null;
		var candidates = CollectSupportedUiComponents(256, new List<string>());
		for (var i = 0; i < candidates.Count; i++)
		{
			var component = candidates[i];
			if (!component || !component.gameObject || component.gameObject.GetInstanceID() != record.InstanceId)
				continue;
			var path = component.transform ? UnityPath(component.transform) : "";
			var sceneName = component.gameObject.scene.IsValid() ? component.gameObject.scene.name ?? "" : "";
			var fingerprint = sceneName + "|" + path + "|" + component.gameObject.GetInstanceID().ToString(CultureInfo.InvariantCulture);
			if (!string.Equals(fingerprint, record.TargetFingerprint, StringComparison.Ordinal))
			{
				errorCode = "fingerprint_mismatch";
				error = "Observed action target fingerprint changed.";
				return null;
			}
			if (matched != null)
			{
				errorCode = "target_ambiguous";
				error = "Observed action target matched more than one active supported UI component.";
				return null;
			}
			matched = component;
		}
		if (matched != null)
			return matched;
		error = "Observed action target instance was not found in active supported UI components.";
		return null;
	}

	private static bool DispatchObservedAction(ObservedActionRecord record, GameObject go, RectTransform rectTransform, out string error)
	{
		error = null;
		var eventSystem = EventSystem.current;
		if (!eventSystem)
		{
			error = "EventSystem.current is unavailable.";
			return false;
		}
		if (string.Equals(record.Kind, "click", StringComparison.Ordinal))
		{
			var canvas = go.GetComponentInParent<Canvas>();
			Vector2 center;
			if (TryGetScreenRect(rectTransform, canvas, out var minX, out var minY, out var maxX, out var maxY))
				center = new Vector2((minX + maxX) * 0.5f, (minY + maxY) * 0.5f);
			else
				center = RectTransformUtility.WorldToScreenPoint(null, rectTransform.TransformPoint(rectTransform.rect.center));
			var pointer = new PointerEventData(eventSystem) { button = PointerEventData.InputButton.Left, position = center, pointerCurrentRaycast = new RaycastResult { gameObject = go } };
			ExecuteEvents.Execute(go, pointer, ExecuteEvents.pointerEnterHandler);
			ExecuteEvents.Execute(go, pointer, ExecuteEvents.pointerDownHandler);
			ExecuteEvents.Execute(go, pointer, ExecuteEvents.pointerUpHandler);
			ExecuteEvents.Execute(go, pointer, ExecuteEvents.pointerClickHandler);
			return true;
		}
		if (string.Equals(record.Kind, "submit", StringComparison.Ordinal))
		{
			var data = new BaseEventData(eventSystem);
			ExecuteEvents.Execute(go, data, ExecuteEvents.submitHandler);
			return true;
		}
		error = "Unsupported observed action kind: " + record.Kind;
		return false;
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
		// Stable temp name — Guid temps leaked ~18k files when Move raced/failed every frame.
		var tmp = path + ".tmp";
		File.WriteAllText(tmp, text ?? "");
		if (File.Exists(path))
			File.Delete(path);
		File.Move(tmp, path);
	}

	private static string ReadString(string json, string key)
	{
		if (json != null && json.Length > MaxTextBytes)
			return null;
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return null;
		var match = Regex.Match(json, "\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*\\\"(?<v>(?:\\\\.|[^\\\"])*)\\\"");
		return match.Success ? Regex.Unescape(match.Groups["v"].Value) : null;
	}

	private static int ReadIntBounded(string json, string key, int defaultValue, int min, int max)
	{
		if (json != null && json.Length > MaxTextBytes)
			return defaultValue;
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return defaultValue;
		var match = Regex.Match(json, "\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*(?<v>-?\\d+)");
		if (!match.Success || !int.TryParse(match.Groups["v"].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value))
			return defaultValue;
		return Math.Max(min, Math.Min(max, value));
	}
	private static bool JsonBool(string json, string key)
	{
		if (json != null && json.Length > MaxTextBytes)
			return false;
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return false;
		var match = Regex.Match(json, "\\\"" + Regex.Escape(key) + "\\\"\\s*:\\s*(?<v>true|false)");
		return match.Success && string.Equals(match.Groups["v"].Value, "true", StringComparison.Ordinal);
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
}

public sealed class Homm3AiDriverBridgeBehaviour : MonoBehaviour
{
	private int _lastFrame;

	private void Update()
	{
		if (_lastFrame == Time.frameCount)
			return;
		_lastFrame = Time.frameCount;
		// Status is rate-limited inside WriteStatus; inbox still polled every frame.
		Homm3AiDriverBridge.WriteStatus("ready");
		Homm3AiDriverBridge.TickHoverMonitor();
		Homm3AiDriverBridge.TickPilotInput();
		ProcessInbox();
	}

	private static void ProcessInbox()
	{
		var bridgeDir = Homm3AiDriverBridge.BridgeDirectory;
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
			Plugin.LogSource?.LogWarning("HOMM3_AI_DRIVER inbox processing failed: " + ex.Message);
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
			var response = Homm3AiDriverBridge.HandleBridgeRequest(text);
			Homm3AiDriverBridge.WriteAllTextAtomic(responsePath, response);
			if (File.Exists(processedPath))
				File.Delete(processedPath);
			File.Move(requestPath, processedPath);
		}
		catch (Exception ex)
		{
			Homm3AiDriverBridge.WriteAllTextAtomic(responsePath, "{\"id\":\"" + Homm3AiDriverBridge.EscapeJson(name) + "\",\"ok\":false,\"error\":{\"code\":\"bridge_exception\",\"message\":\"" + Homm3AiDriverBridge.EscapeJson(ex.Message) + "\"}}");
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
