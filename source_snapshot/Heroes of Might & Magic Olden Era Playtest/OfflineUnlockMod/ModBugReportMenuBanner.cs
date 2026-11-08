using System;
using Hex.MainMenu;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Main-menu notice in the bottom-right corner: bug reports go to the Golden Era mod team, and F1 opens the form.
///
/// Shown only while the main-menu navigation view is active and <see cref="ModBugReportRedirect"/> holds the
/// native report sink (so the text is true), and hidden while the report status window is up. Drawn with IMGUI on
/// a 720-line virtual screen scaled by screen height, like the report windows. Labels and textures only, so it
/// never takes clicks from the menu underneath.
/// </summary>
internal static class ModBugReportMenuBanner
{
	private const string HostObjectName = "OFFLINE_UNLOCK_MOD_BUG_REPORT_MENU_BANNER";
	private const float ReferenceScreenHeight = 720f;
	private const float Width = 400f;
	private const float Height = 112f;
	private const float Margin = 18f;
	private const float FadeSeconds = 0.6f;
	// Shown for this long per visit to the main menu, then it fades out so it stops covering menu UI.
	private const float VisibleSeconds = 10f;
	private const int MenuFrameGrace = 3;

	private static readonly Color PanelColor = new(0.06f, 0.05f, 0.04f, 0.88f);
	private static readonly Color GoldColor = new(0.86f, 0.68f, 0.30f, 1f);
	private static readonly Color GoldDimColor = new(0.55f, 0.42f, 0.18f, 1f);
	private static readonly Color KeyFaceColor = new(0.16f, 0.13f, 0.09f, 1f);
	private static readonly Color TitleColor = new(1f, 0.92f, 0.70f, 1f);
	private static readonly Color BodyColor = new(0.90f, 0.88f, 0.84f, 1f);

	private static bool _failed;
	private static ModBugReportMenuBannerHost _host;
	private static MainMenuNavigationView _navigation;
	private static int _lastMenuFrame = -1000;
	private static float _shownSince = -1f;
	private static GUIStyle _keyStyle;
	private static GUIStyle _titleStyle;
	private static GUIStyle _bodyStyle;

	/// <summary>Called from the main-menu Update postfix; the banner hides a few frames after the menu stops updating.</summary>
	internal static void MarkMainMenuFrame(ScMainMenu menu)
	{
		if (_failed)
			return;
		_lastMenuFrame = Time.frameCount;
		try
		{
			_navigation = menu != null ? menu.mainMenuNavigationView : null;
		}
		catch
		{
			_navigation = null;
		}
		if (_host != null)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<ModBugReportMenuBannerHost>();
			var go = new GameObject(HostObjectName) { hideFlags = HideFlags.HideAndDontSave };
			_host = go.AddComponent<ModBugReportMenuBannerHost>();
			if (_host == null)
			{
				UnityObject.Destroy(go);
				throw new InvalidOperationException("AddComponent returned null");
			}
			UnityObject.DontDestroyOnLoad(go);
		}
		catch (Exception ex)
		{
			_failed = true;
			Plugin.LogSource?.LogWarning("Bug report menu banner disabled: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static bool ShouldShow()
	{
		if (Time.frameCount - _lastMenuFrame > MenuFrameGrace)
			return false;
		if (ModBugReportRedirect.State != ModBugReportRedirect.GuardState.Redirecting)
			return false;
		if (ModBugReportSubmission.IsOverlayVisible)
			return false;
		// Sub-screens (skirmish setup, options...) replace the navigation view; keep their corner buttons clear.
		try
		{
			if (_navigation == null || !_navigation.gameObject.activeInHierarchy)
				return false;
		}
		catch
		{
			_navigation = null;
			return false;
		}
		return true;
	}

	internal static void OnHostGui()
	{
		if (_failed || Event.current == null || Event.current.type != EventType.Repaint)
			return;
		// The timer restarts only when the main menu is entered again (after a game), not when a sub-screen
		// such as skirmish setup hides the navigation view for a moment.
		if (Time.frameCount - _lastMenuFrame > MenuFrameGrace)
			_shownSince = -1f;
		if (!ShouldShow())
			return;
		if (_shownSince < 0f)
			_shownSince = Time.unscaledTime;
		var shownFor = Time.unscaledTime - _shownSince;
		if (shownFor >= VisibleSeconds + FadeSeconds)
			return;

		var previousMatrix = GUI.matrix;
		var previousColor = GUI.color;
		var previousDepth = GUI.depth;
		try
		{
			var alpha = Mathf.Min(
				Mathf.Clamp01(shownFor / FadeSeconds),
				Mathf.Clamp01((VisibleSeconds + FadeSeconds - shownFor) / FadeSeconds));
			EnsureStyles();

			// 720-line virtual screen, scaled with the screen height so it keeps its share at any resolution.
			var scale = Mathf.Max(0.5f, Screen.height / ReferenceScreenHeight);
			var screenWidth = Screen.width / scale;
			var screenHeight = Screen.height / scale;
			var width = Mathf.Min(Width, screenWidth - Margin * 2f);
			var panel = new Rect(screenWidth - width - Margin, screenHeight - Height - Margin, width, Height);

			GUI.depth = -2000;
			GUI.matrix = Matrix4x4.TRS(Vector3.zero, Quaternion.identity, new Vector3(scale, scale, 1f));

			// Panel: gold frame, dark fill, gold accent bar on the left.
			Fill(panel, GoldColor, alpha);
			Fill(Inset(panel, 2f), PanelColor, alpha);
			Fill(new Rect(panel.x + 2f, panel.y + 2f, 5f, panel.height - 4f), GoldColor, alpha);

			// Keycap.
			var key = new Rect(panel.x + 22f, panel.y + (panel.height - 68f) * 0.5f, 76f, 68f);
			Fill(new Rect(key.x, key.y + 4f, key.width, key.height), GoldDimColor, alpha);
			Fill(key, GoldColor, alpha);
			Fill(Inset(key, 3f), KeyFaceColor, alpha);
			Text(key, "F1", _keyStyle, GoldColor, alpha);

			// Text.
			var textX = key.xMax + 18f;
			var textWidth = panel.xMax - textX - 14f;
			Text(new Rect(textX, panel.y + 14f, textWidth, 32f), "Found a bug? Press F1", _titleStyle, TitleColor, alpha);
			Text(
				new Rect(textX, panel.y + 48f, textWidth, panel.height - 56f),
				"Bug reports go to the Golden Era mod team, not the Olden Era developers.",
				_bodyStyle,
				BodyColor,
				alpha);
		}
		catch (Exception ex)
		{
			_failed = true;
			Plugin.LogSource?.LogWarning("Bug report menu banner disabled after a draw error: " + ex.GetType().Name);
		}
		finally
		{
			GUI.matrix = previousMatrix;
			GUI.color = previousColor;
			GUI.depth = previousDepth;
		}
	}

	private static void EnsureStyles()
	{
		if (_keyStyle != null)
			return;
		_keyStyle = new GUIStyle(GUI.skin.label) { fontSize = 34, fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleCenter };
		_titleStyle = new GUIStyle(GUI.skin.label) { fontSize = 22, fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleLeft };
		_bodyStyle = new GUIStyle(GUI.skin.label) { fontSize = 14, wordWrap = true, alignment = TextAnchor.UpperLeft };
	}

	private static Rect Inset(Rect rect, float by)
	{
		return new Rect(rect.x + by, rect.y + by, rect.width - by * 2f, rect.height - by * 2f);
	}

	private static void Fill(Rect rect, Color color, float alpha)
	{
		GUI.color = new Color(color.r, color.g, color.b, color.a * alpha);
		GUI.DrawTexture(rect, Texture2D.whiteTexture);
	}

	private static void Text(Rect rect, string text, GUIStyle style, Color color, float alpha)
	{
		GUI.color = Color.white;
		style.normal.textColor = new Color(color.r, color.g, color.b, color.a * alpha);
		GUI.Label(rect, text, style);
	}
}

public sealed class ModBugReportMenuBannerHost : MonoBehaviour
{
	public ModBugReportMenuBannerHost(IntPtr ptr) : base(ptr) { }

	private void OnGUI() => ModBugReportMenuBanner.OnHostGui();
}
