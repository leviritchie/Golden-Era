using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Screen-reader focus / utterance layer on Component 2.
/// Speech consumers (NVDA companion, later AI pilot) read utterance + context only —
/// never raw screen_dump catalogs.
/// </summary>
internal static partial class Homm3AiDriverBridge
{
	internal const string FocusSnapshotSchemaVersion = "ai-driver.v1.focus-snapshot";
	private const string FocusGrepKey = "HOMM3_AI_FOCUS";
	/// <summary>
	/// Opt-in BepInEx flag beside OfflineUnlockMod.dll. Absent by default so map-hover
	/// focus ticks do not flood LogWarning with HOMM3_AI_FOCUS utterance lines.
	/// </summary>
	internal const string FocusUtteranceLogFlag = "homm3_ai_focus_utterance_log.flag";

	private static string _lastContextFingerprint = "";
	private static string _lastSpokenContextUtterance = "";
	private static string _lastContextMode = "";
	private static int _lastContextScanFrame = int.MinValue;
	private const int ContextScanMinFrameGap = 30;
	private static string _cachedContextJson = "{}";
	private static string _cachedContextUtterance = "";
	private static string _cachedContextFp = "";
	private static string _lastKeyboardFocusFingerprint = "";
	private static string _lastFocusEmitFingerprint = "";

	/// <summary>
	/// Builds the speech-facing focus snapshot. Includes hover lane plus human utterance and context.
	/// Also writes focus_latest.json alongside hover_latest.json.
	/// </summary>
	internal static string BuildFocusSnapshotResponse(string id)
	{
		return OkResponse(id, "\"focus\":" + BuildFocusSnapshotJson(writeEventFile: false));
	}

	internal static string BuildFocusSnapshotJson(bool writeEventFile)
	{
		var hoverJson = BuildHoverSnapshotJson(writeEventFile: false);
		// Parse is intentional: hover builder owns pointer/hover/gaps; we enrich for speech.
		var utterance = "";
		var speechSafe = false;
		var contextJson = "{}";
		var gaps = new List<string>();

		try
		{
			EnrichHoverIntoFocus(hoverJson, out utterance, out speechSafe, out contextJson, out var enrichGaps);
			if (enrichGaps != null)
			{
				for (var i = 0; i < enrichGaps.Count; i++)
					gaps.Add(enrichGaps[i]);
			}
		}
		catch (Exception ex)
		{
			gaps.Add(GapJson("focus_enrich_failed", "Focus utterance enrich failed: " + ex.GetType().Name + ": " + ex.Message, false));
			utterance = "";
			speechSafe = false;
			var mode = InferModeFromLoadedScenes(SceneManager.GetActiveScene().name ?? "");
			contextJson = "{\"mode\":\"" + EscapeJson(mode) + "\"}";
		}

		if (string.IsNullOrWhiteSpace(contextJson) || contextJson == "{}")
		{
			var mode = InferModeFromLoadedScenes(SceneManager.GetActiveScene().name ?? "");
			contextJson = "{\"mode\":\"" + EscapeJson(mode) + "\"}";
		}

		var focus = "{"
			+ "\"schemaVersion\":\"" + FocusSnapshotSchemaVersion + "\","
			+ "\"speechSafe\":" + BoolJson(speechSafe) + ","
			+ "\"utterance\":\"" + EscapeJson(utterance) + "\","
			+ "\"context\":" + contextJson + ","
			+ "\"hover\":" + hoverJson
			+ (gaps.Count > 0 ? ",\"gaps\":[" + string.Join(",", gaps) + "]" : ",\"gaps\":[]")
			+ "}";

		if (writeEventFile)
			WriteFocusEventFile(focus, utterance, speechSafe);

		return focus;
	}

	/// <summary>
	/// Called from TickHoverMonitor after hover write — emit focus file when utterance/context changes.
	/// </summary>
	internal static void TickFocusFromHover()
	{
		try
		{
			BuildFocusSnapshotJson(writeEventFile: true);
		}
		catch (Exception ex)
		{
			_log?.LogWarning(FocusGrepKey + " tick failed: " + ex.Message);
		}
	}

	private static void EnrichHoverIntoFocus(
		string hoverSnapshotJson,
		out string utterance,
		out bool speechSafe,
		out string contextJson,
		out List<string> gaps)
	{
		utterance = "";
		speechSafe = false;
		gaps = new List<string>();
		contextJson = BuildSpeechContextJson(gaps, out var contextUtterance, out var contextFp);

		var lane = ExtractJsonString(hoverSnapshotJson, "lane") ?? "none";
		// hover object is nested; crude extract from full snapshot is enough for utterance.
		var label = ExtractNestedHoverString(hoverSnapshotJson, "label");
		var name = ExtractNestedHoverString(hoverSnapshotJson, "name");
		var path = ExtractNestedHoverString(hoverSnapshotJson, "path");
		var nodeStr = ExtractNestedHoverNumber(hoverSnapshotJson, "node");
		int? node = null;
		if (!string.IsNullOrEmpty(nodeStr) && int.TryParse(nodeStr, NumberStyles.Integer, CultureInfo.InvariantCulture, out var n) && n >= 0)
			node = n;

		var mode = ExtractJsonString(hoverSnapshotJson, "mode") ?? InferModeFromLoadedScenes(SceneManager.GetActiveScene().name ?? "");

		if (string.Equals(mode, "loading", StringComparison.Ordinal))
		{
			_lastContextMode = mode;
			utterance = "";
			speechSafe = false;
			gaps.Add(GapJson(
				"focus_loading_suppressed",
				"Speech suppressed while mode=loading; wait for adventure_map before announcing context.",
				false));
			return;
		}

		var exitedLoading = string.Equals(_lastContextMode, "loading", StringComparison.Ordinal)
		                    && string.Equals(mode, "adventure_map", StringComparison.Ordinal);
		_lastContextMode = mode;

		var cleaned = SanitizeSpeechLabel(label);
		if (string.IsNullOrEmpty(cleaned))
			cleaned = SanitizeSpeechLabel(name);

		string mapName = null;
		bool? fogVisible = null;
		if (node.HasValue && string.Equals(mode, "adventure_map", StringComparison.Ordinal))
		{
			if (TryResolveMapObjectSpeechForNode(node.Value, out mapName, out fogVisible, out var mapGap))
			{
				if (!string.IsNullOrEmpty(mapName))
					cleaned = mapName;
			}
			else if (!string.IsNullOrEmpty(mapGap))
			{
				gaps.Add(GapJson("map_focus_name_unresolved", mapGap, false));
			}
		}

		if (!string.IsNullOrEmpty(contextUtterance)
		    && (!string.Equals(contextFp, _lastContextFingerprint, StringComparison.Ordinal) || exitedLoading))
		{
			_lastContextFingerprint = contextFp;
			_lastSpokenContextUtterance = contextUtterance;
			utterance = contextUtterance;
			speechSafe = true;
			return;
		}

		if (string.Equals(lane, "ui", StringComparison.Ordinal))
		{
			if (string.IsNullOrEmpty(cleaned) || IsPlaceholderSpeechLabel(cleaned))
			{
				gaps.Add(GapJson("ui_focus_label_unusable", "UI hover label is missing or placeholder; not spoken.", false));
				utterance = "";
				speechSafe = false;
				return;
			}
			utterance = cleaned;
			speechSafe = true;
			return;
		}

		if (TryReadKeyboardFocusSpeech(out var keyboardLabel, out var keyboardPath, out var keyboardFp)
		    && !string.IsNullOrEmpty(keyboardLabel)
		    && !IsPlaceholderSpeechLabel(keyboardLabel))
		{
			if (!string.Equals(keyboardFp, _lastKeyboardFocusFingerprint, StringComparison.Ordinal))
			{
				_lastKeyboardFocusFingerprint = keyboardFp;
				utterance = keyboardLabel;
				speechSafe = true;
				gaps.Add(GapJson(
					"focus_keyboard_selected",
					"Keyboard EventSystem selection drove utterance (path=" + (keyboardPath ?? "?") + ").",
					false));
				return;
			}
		}

		if (string.Equals(lane, "map", StringComparison.Ordinal) || node.HasValue)
		{
			var parts = new List<string>(4);
			if (!string.IsNullOrEmpty(cleaned) && !IsPlaceholderSpeechLabel(cleaned))
				parts.Add(cleaned);
			else if (node.HasValue)
				parts.Add("map tile " + node.Value.ToString(CultureInfo.InvariantCulture));
			if (fogVisible == false)
				parts.Add("shrouded");
			else if (fogVisible == true)
				parts.Add("revealed");
			utterance = string.Join(", ", parts);
			speechSafe = !string.IsNullOrEmpty(utterance) && (fogVisible != false || parts.Count > 0);
			if (fogVisible == false)
				speechSafe = true; // speaking "shrouded" is honest
			return;
		}

		if (!string.IsNullOrEmpty(contextUtterance))
		{
			utterance = contextUtterance;
			speechSafe = true;
			return;
		}

		utterance = "";
		speechSafe = false;
		gaps.Add(GapJson("focus_none", "No speech-safe focus under pointer and no pending context announcement.", false));
	}

	private static string BuildSpeechContextJson(List<string> gaps, out string contextUtterance, out string fingerprint)
	{
		var frame = Time.frameCount;
		if (frame - _lastContextScanFrame < ContextScanMinFrameGap && !string.IsNullOrEmpty(_cachedContextJson) && _cachedContextJson != "{}")
		{
			contextUtterance = _cachedContextUtterance;
			fingerprint = _cachedContextFp;
			return _cachedContextJson;
		}
		_lastContextScanFrame = frame;

		contextUtterance = "";
		fingerprint = "";
		var mode = InferModeFromLoadedScenes(SceneManager.GetActiveScene().name ?? "");
		string dialogTitle = null;
		string dialogBody = null;
		string questText = null;
		string heroTitle = null;

		try
		{
			TryReadOnScreenDialogSpeech(out dialogTitle, out dialogBody);
			TryReadOnScreenQuestSpeech(out questText);
			TryReadOnScreenHeroTitle(out heroTitle);
		}
		catch (Exception ex)
		{
			gaps?.Add(GapJson("focus_context_scan_failed", "Context TMP scan failed: " + ex.GetType().Name + ": " + ex.Message, false));
		}

		var sb = new StringBuilder(256);
		sb.Append('{');
		sb.Append("\"mode\":\"").Append(EscapeJson(mode)).Append('"');
		if (!string.IsNullOrEmpty(heroTitle))
			sb.Append(",\"hero\":\"").Append(EscapeJson(heroTitle)).Append('"');
		if (!string.IsNullOrEmpty(questText))
			sb.Append(",\"quest\":\"").Append(EscapeJson(questText)).Append('"');
		if (!string.IsNullOrEmpty(dialogTitle))
			sb.Append(",\"dialogTitle\":\"").Append(EscapeJson(dialogTitle)).Append('"');
		if (!string.IsNullOrEmpty(dialogBody))
			sb.Append(",\"dialogBody\":\"").Append(EscapeJson(TruncateSpeech(dialogBody, 400))).Append('"');
		sb.Append('}');

		fingerprint = mode + "|" + (dialogTitle ?? "") + "|" + TruncateSpeech(dialogBody ?? "", 80) + "|" + (questText ?? "") + "|" + (heroTitle ?? "");

		if (!string.IsNullOrEmpty(dialogBody))
		{
			contextUtterance = string.IsNullOrEmpty(dialogTitle)
				? dialogBody
				: dialogTitle + ". " + dialogBody;
		}
		else if (!string.IsNullOrEmpty(questText))
		{
			contextUtterance = "Quest: " + questText;
		}

		_cachedContextJson = sb.ToString();
		_cachedContextUtterance = contextUtterance;
		_cachedContextFp = fingerprint;
		return _cachedContextJson;
	}

	private static void TryReadOnScreenDialogSpeech(out string title, out string body)
	{
		title = null;
		body = null;
		TMP_Text[] texts;
		try { texts = Resources.FindObjectsOfTypeAll<TMP_Text>(); }
		catch { return; }
		if (texts == null)
			return;

		for (var i = 0; i < texts.Length; i++)
		{
			var tmp = texts[i];
			if (!tmp || !tmp.gameObject || !tmp.gameObject.activeInHierarchy)
				continue;
			var path = UnityPath(tmp.transform);
			if (path.IndexOf("ScDialogSlide", StringComparison.Ordinal) < 0
			    && path.IndexOf("ScGuide", StringComparison.Ordinal) < 0)
				continue;
			if (!TryGetSpeechOnScreen(tmp.rectTransform, out _))
				continue;
			var text = (tmp.text ?? "").Trim();
			if (string.IsNullOrEmpty(text) || IsPlaceholderSpeechLabel(text))
				continue;
			if (path.IndexOf("DialogText", StringComparison.Ordinal) >= 0
			    || path.IndexOf("MainText", StringComparison.Ordinal) >= 0)
			{
				if (string.IsNullOrEmpty(body) || text.Length > body.Length)
					body = text;
			}
			else if (path.IndexOf("Title", StringComparison.Ordinal) >= 0 || path.IndexOf("Header", StringComparison.Ordinal) >= 0)
			{
				if (string.IsNullOrEmpty(title))
					title = text;
			}
		}
	}

	private static void TryReadOnScreenQuestSpeech(out string quest)
	{
		quest = null;
		TMP_Text[] texts;
		try { texts = Resources.FindObjectsOfTypeAll<TMP_Text>(); }
		catch { return; }
		if (texts == null)
			return;
		for (var i = 0; i < texts.Length; i++)
		{
			var tmp = texts[i];
			if (!tmp || !tmp.gameObject || !tmp.gameObject.activeInHierarchy)
				continue;
			var path = UnityPath(tmp.transform);
			if (path.IndexOf("ScQuestLog", StringComparison.Ordinal) < 0)
				continue;
			if (!TryGetSpeechOnScreen(tmp.rectTransform, out _))
				continue;
			var text = (tmp.text ?? "").Trim();
			if (string.IsNullOrEmpty(text) || IsPlaceholderSpeechLabel(text) || text.Length < 4)
				continue;
			// Prefer subquest lines over "Tutorial" header.
			if (path.IndexOf("sub quest", StringComparison.OrdinalIgnoreCase) >= 0
			    || path.IndexOf("subquest", StringComparison.OrdinalIgnoreCase) >= 0
			    || text.IndexOf("Move", StringComparison.OrdinalIgnoreCase) >= 0)
			{
				quest = text;
				return;
			}
			if (quest == null && !string.Equals(text, "Tutorial", StringComparison.OrdinalIgnoreCase))
				quest = text;
		}
	}

	private static void TryReadOnScreenHeroTitle(out string heroTitle)
	{
		heroTitle = null;
		TMP_Text[] texts;
		try { texts = Resources.FindObjectsOfTypeAll<TMP_Text>(); }
		catch { return; }
		if (texts == null)
			return;
		for (var i = 0; i < texts.Length; i++)
		{
			var tmp = texts[i];
			if (!tmp || !tmp.gameObject || !tmp.gameObject.activeInHierarchy)
				continue;
			var path = UnityPath(tmp.transform);
			if (path.IndexOf("HeroTitle", StringComparison.Ordinal) < 0)
				continue;
			if (!TryGetSpeechOnScreen(tmp.rectTransform, out _))
				continue;
			var text = SanitizeSpeechLabel(tmp.text);
			if (!string.IsNullOrEmpty(text))
			{
				heroTitle = text;
				return;
			}
		}
	}

	private static bool TryGetSpeechOnScreen(RectTransform rect, out Rect screen)
	{
		screen = default;
		if (!rect)
			return false;
		var canvas = rect.GetComponentInParent<Canvas>();
		if (!TryGetScreenRect(rect, canvas, out var minX, out var minY, out var maxX, out var maxY))
			return false;
		var w = maxX - minX;
		var h = maxY - minY;
		if (w < 2f || h < 2f)
			return false;
		if (minX >= Screen.width || minY >= Screen.height || maxX <= 0 || maxY <= 0)
			return false;
		// Reject absurd off-layout pooled rects (MessageBox placeholders).
		if (minX > Screen.width * 2f || minY > Screen.height * 2f)
			return false;
		screen = Rect.MinMaxRect(minX, minY, maxX, maxY);
		return true;
	}

	private static bool TryResolveMapObjectSpeechForNode(int node, out string name, out bool? fogVisible, out string gap)
	{
		name = null;
		fogVisible = null;
		gap = null;
		if (!TryResolveAdventureMapContext(out var mapInstance, out var mapData, out var reason))
		{
			gap = "Map context unresolved: " + (reason ?? "unknown");
			return false;
		}

		var objects = ReadFirstMemberValue(mapData, GameSymbols.CampaignSpawnParity.MapDataObjectsListMemberHints);
		if (objects == null)
		{
			gap = "MapData.objects unresolved for focus name lookup.";
			return false;
		}

		foreach (var row in EnumerateIl2CppListForDump(objects))
		{
			if (row == null)
				continue;
			var nodeList = ReadMapDataObjectNodes(row);
			var hit = false;
			for (var i = 0; i < nodeList.Count; i++)
			{
				if (nodeList[i] == node)
				{
					hit = true;
					break;
				}
			}
			if (!hit)
				continue;

			var sid = ReadFirstStringMember(row, GameSymbols.CampaignSpawnParity.MapDataObjectsSidFields);
			name = HumanizeMapSid(sid);
			if (TryResolveAdventureMapFogOfWar(mapInstance, mapData, out var fog, out _))
			{
				if (Homm3AdventureVisionNativeAdapter.TryReadFogVisibility(fog, node, out var vis, out _))
					fogVisible = vis;
				else if (TryReadFogVisibilityMap(fog, node, out vis))
					fogVisible = vis;
			}
			return !string.IsNullOrEmpty(name);
		}

		gap = "No MapData object at node " + node.ToString(CultureInfo.InvariantCulture) + ".";
		return false;
	}

	private static string HumanizeMapSid(string sid)
	{
		if (string.IsNullOrWhiteSpace(sid))
			return null;
		var s = sid.Trim();
		if (s.StartsWith("fx_quest_mark", StringComparison.OrdinalIgnoreCase))
			return "quest marker";
		if (s.StartsWith("resource_gold", StringComparison.OrdinalIgnoreCase))
			return "gold";
		if (s.StartsWith("watchtower", StringComparison.OrdinalIgnoreCase))
			return "watchtower";
		if (s.StartsWith("human_city", StringComparison.OrdinalIgnoreCase))
			return "town";
		if (s.StartsWith("bridge_", StringComparison.OrdinalIgnoreCase))
			return "bridge";
		if (s.StartsWith("pool_", StringComparison.OrdinalIgnoreCase))
			return "pool";
		if (s.StartsWith("pinetree", StringComparison.OrdinalIgnoreCase) || s.StartsWith("tree_", StringComparison.OrdinalIgnoreCase))
			return "tree";
		if (s.StartsWith("mountain_", StringComparison.OrdinalIgnoreCase))
			return "mountain";
		if (s.StartsWith("barracks_", StringComparison.OrdinalIgnoreCase))
			return "barracks";
		if (s.StartsWith("chicken_", StringComparison.OrdinalIgnoreCase))
			return "chicken";
		// Fallback: replace underscores with spaces.
		return s.Replace('_', ' ');
	}

	internal static string SanitizeSpeechLabel(string raw)
	{
		if (string.IsNullOrWhiteSpace(raw))
			return "";
		var text = raw.Trim();
		if (IsPlaceholderSpeechLabel(text))
			return "";
		return text;
	}

	internal static bool IsPlaceholderSpeechLabel(string text)
	{
		if (string.IsNullOrWhiteSpace(text))
			return true;
		var t = text.Trim();
		if (string.Equals(t, "New Text", StringComparison.OrdinalIgnoreCase))
			return true;
		if (string.Equals(t, "Text", StringComparison.OrdinalIgnoreCase))
			return true;
		if (string.Equals(t, "label-button", StringComparison.OrdinalIgnoreCase))
			return true;
		if (string.Equals(t, "Particle System", StringComparison.OrdinalIgnoreCase))
			return true;
		if (string.Equals(t, "MAIN BACK", StringComparison.OrdinalIgnoreCase))
			return true;
		if (t.StartsWith("GENERIC ", StringComparison.OrdinalIgnoreCase))
			return true;
		if (t.StartsWith("GameObject", StringComparison.OrdinalIgnoreCase))
			return true;
		// Raw Unity control names with no player meaning.
		if (t.IndexOf("BUTTON", StringComparison.OrdinalIgnoreCase) >= 0
		    && t.IndexOf(' ') < 0
		    && t.Length > 6)
			return true;
		return false;
	}

	private static string TruncateSpeech(string text, int max)
	{
		if (string.IsNullOrEmpty(text) || text.Length <= max)
			return text ?? "";
		return text.Substring(0, max).TrimEnd() + "…";
	}

	private static bool TryReadKeyboardFocusSpeech(out string label, out string path, out string fingerprint)
	{
		label = "";
		path = "";
		fingerprint = "";
		var eventSystem = EventSystem.current;
		if (!eventSystem)
			return false;

		var selected = eventSystem.currentSelectedGameObject;
		if (!selected || !selected.activeInHierarchy)
			return false;

		path = UnityPath(selected.transform);
		label = UiText(selected);
		if (string.IsNullOrEmpty(label))
		{
			var selectable = selected.GetComponentInParent<Selectable>();
			if (selectable)
				label = UiText(selectable.gameObject);
		}
		if (string.IsNullOrEmpty(label) || IsPlaceholderSpeechLabel(label))
			label = SanitizeSpeechLabel(selected.name);
		if (IsPlaceholderSpeechLabel(label))
			label = "";

		var sceneName = selected.scene.IsValid() ? selected.scene.name ?? "" : "";
		fingerprint = "keyboard|" + sceneName + "|" + path + "|" + selected.GetInstanceID().ToString(CultureInfo.InvariantCulture);
		return !string.IsNullOrEmpty(label);
	}

	private static void WriteFocusEventFile(string json, string utterance, bool speechSafe)
	{
		if (string.IsNullOrWhiteSpace(BridgeDirectory))
			return;
		try
		{
			// Always refresh the latest snapshot for MCP / NVDA consumers.
			WriteAllTextAtomic(System.IO.Path.Combine(BridgeDirectory, "focus_latest.json"), json);

			var emitFp = (speechSafe ? "1|" : "0|") + (utterance ?? "");
			var changed = !string.Equals(emitFp, _lastFocusEmitFingerprint, StringComparison.Ordinal);
			if (!changed)
				return;

			_lastFocusEmitFingerprint = emitFp;
			var eventsDir = System.IO.Path.Combine(BridgeDirectory, "events");
			System.IO.Directory.CreateDirectory(eventsDir);
			var fileName = "focus_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff", CultureInfo.InvariantCulture)
				+ "_" + Time.frameCount.ToString(CultureInfo.InvariantCulture) + ".json";
			WriteAllTextAtomic(System.IO.Path.Combine(eventsDir, fileName), json);

			// Quiet by default: map-tile hover would otherwise LogWarning every node change.
			if (Homm3DiagnosticFlags.IsEnabled(FocusUtteranceLogFlag))
				_log?.LogWarning(FocusGrepKey + " utterance speechSafe=" + speechSafe + " text=" + TruncateSpeech(utterance ?? "", 120));
		}
		catch (Exception ex)
		{
			_log?.LogWarning(FocusGrepKey + " event write failed: " + ex.Message);
		}
	}

	private static string ExtractJsonString(string json, string key)
	{
		if (string.IsNullOrEmpty(json) || string.IsNullOrEmpty(key))
			return null;
		var match = System.Text.RegularExpressions.Regex.Match(
			json,
			"\\\"" + System.Text.RegularExpressions.Regex.Escape(key) + "\\\"\\s*:\\s*\\\"(?<v>(?:\\\\.|[^\\\"])*)\\\"");
		return match.Success ? System.Text.RegularExpressions.Regex.Unescape(match.Groups["v"].Value) : null;
	}

	private static string ExtractNestedHoverString(string hoverSnapshotJson, string key)
	{
		// Prefer values inside the "hover":{...} object.
		var hoverIdx = hoverSnapshotJson.IndexOf("\"hover\"", StringComparison.Ordinal);
		if (hoverIdx < 0)
			return ExtractJsonString(hoverSnapshotJson, key);
		var slice = hoverSnapshotJson.Substring(hoverIdx);
		var end = slice.IndexOf("\"gaps\"", StringComparison.Ordinal);
		if (end > 0)
			slice = slice.Substring(0, end);
		return ExtractJsonString(slice, key);
	}

	private static string ExtractNestedHoverNumber(string hoverSnapshotJson, string key)
	{
		var hoverIdx = hoverSnapshotJson.IndexOf("\"hover\"", StringComparison.Ordinal);
		var slice = hoverIdx >= 0 ? hoverSnapshotJson.Substring(hoverIdx) : hoverSnapshotJson;
		var match = System.Text.RegularExpressions.Regex.Match(
			slice,
			"\\\"" + System.Text.RegularExpressions.Regex.Escape(key) + "\\\"\\s*:\\s*(?<v>-?\\d+)");
		return match.Success ? match.Groups["v"].Value : null;
	}
}
