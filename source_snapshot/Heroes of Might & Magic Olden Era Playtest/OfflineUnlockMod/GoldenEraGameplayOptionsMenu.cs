using System;
using Hex.MainMenu;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;
using UnityEngine.UI;
using UnityImage = UnityEngine.UI.Image;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Main-menu "Gameplay Options" button (bottom-left) and window for <see cref="GoldenEraGameplayOptions"/>.
///
/// Shown only while the main-menu navigation view is active, like <see cref="ModBugReportMenuBanner"/>. IMGUI on
/// a 720-line virtual screen scaled by screen height. A transparent uGUI raycast target sits under the button
/// (or the whole screen while the window is open) so clicks never reach the menu underneath.
/// Every choice saves immediately; Escape or Done closes the window.
/// </summary>
internal static class GoldenEraGameplayOptionsMenu
{
	private const string HostObjectName = "OFFLINE_UNLOCK_MOD_GAMEPLAY_OPTIONS_MENU";
	private const float ReferenceScreenHeight = 720f;
	private const float Margin = 18f;
	private const float ButtonWidth = 176f;
	private const float ButtonHeight = 40f;
	private const float WindowWidth = 600f;
	private const float WindowHeight = 470f;
	private const float RowHeight = 62f;
	private const int MenuFrameGrace = 3;

	private static readonly Color PanelColor = new(0.06f, 0.05f, 0.04f, 0.96f);
	private static readonly Color DimColor = new(0f, 0f, 0f, 0.55f);
	private static readonly Color GoldColor = new(0.86f, 0.68f, 0.30f, 1f);
	private static readonly Color GoldDimColor = new(0.55f, 0.42f, 0.18f, 1f);
	private static readonly Color ChoiceColor = new(0.16f, 0.13f, 0.09f, 1f);
	private static readonly Color ChoiceHoverColor = new(0.26f, 0.21f, 0.13f, 1f);
	private static readonly Color TitleColor = new(1f, 0.92f, 0.70f, 1f);
	private static readonly Color BodyColor = new(0.90f, 0.88f, 0.84f, 1f);
	private static readonly Color NoteColor = new(0.70f, 0.67f, 0.60f, 1f);
	private static readonly Color SelectedTextColor = new(0.10f, 0.08f, 0.05f, 1f);

	private static bool _failed;
	private static bool _open;
	private static GoldenEraGameplayOptionsMenuHost _host;
	private static MainMenuNavigationView _navigation;
	private static int _lastMenuFrame = -1000;
	private static GUIStyle _titleStyle;
	private static GUIStyle _labelStyle;
	private static GUIStyle _hintStyle;
	private static GUIStyle _choiceStyle;
	private static GUIStyle _noteStyle;
	private static Canvas _shieldCanvas;
	private static UnityImage _shieldImage;

	/// <summary>Called from the main-menu Update postfix; everything hides a few frames after the menu stops updating.</summary>
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
			ClassInjector.RegisterTypeInIl2Cpp<GoldenEraGameplayOptionsMenuHost>();
			var go = new GameObject(HostObjectName) { hideFlags = HideFlags.HideAndDontSave };
			_host = go.AddComponent<GoldenEraGameplayOptionsMenuHost>();
			if (_host == null)
			{
				UnityObject.Destroy(go);
				throw new InvalidOperationException("AddComponent returned null");
			}
			UnityObject.DontDestroyOnLoad(go);
			AttachPointerShield();
		}
		catch (Exception ex)
		{
			_failed = true;
			Plugin.LogSource?.LogWarning("Gameplay options menu disabled: " + ex.GetType().Name + ": " + ex.Message);
		}
	}

	private static bool MenuVisible()
	{
		if (Time.frameCount - _lastMenuFrame > MenuFrameGrace)
			return false;
		if (ModBugReportSubmission.IsOverlayVisible)
			return false;
		try
		{
			return _navigation != null && _navigation.gameObject.activeInHierarchy;
		}
		catch
		{
			_navigation = null;
			return false;
		}
	}

	internal static void OnHostGui()
	{
		if (_failed || Event.current == null)
			return;
		if (!MenuVisible())
		{
			_open = false;
			HideShield();
			return;
		}

		var previousMatrix = GUI.matrix;
		var previousColor = GUI.color;
		var previousDepth = GUI.depth;
		try
		{
			EnsureStyles();
			var scale = Mathf.Max(0.5f, Screen.height / ReferenceScreenHeight);
			var screenWidth = Screen.width / scale;
			var screenHeight = Screen.height / scale;
			GUI.depth = -2000;
			GUI.matrix = Matrix4x4.TRS(Vector3.zero, Quaternion.identity, new Vector3(scale, scale, 1f));

			if (_open)
			{
				if (Event.current.type == EventType.KeyDown && Event.current.keyCode == KeyCode.Escape)
				{
					_open = false;
					Event.current.Use();
				}
				else
				{
					UpdateShield(new Rect(0f, 0f, Screen.width, Screen.height));
					DrawWindow(screenWidth, screenHeight);
					return;
				}
			}

			var button = new Rect(Margin, screenHeight - ButtonHeight - Margin, ButtonWidth, ButtonHeight);
			UpdateShield(new Rect(button.x * scale, button.y * scale, button.width * scale, button.height * scale));
			var hover = button.Contains(Event.current.mousePosition);
			Fill(button, GoldColor);
			Fill(Inset(button, 2f), hover ? ChoiceHoverColor : PanelColor);
			Label(button, "Gameplay Options", _choiceStyle, TitleColor);
			if (GUI.Button(button, GUIContent.none, GUIStyle.none))
				_open = true;
		}
		catch (Exception ex)
		{
			_failed = true;
			HideShield();
			Plugin.LogSource?.LogWarning("Gameplay options menu disabled after a draw error: " + ex.GetType().Name + ": " + ex.Message);
		}
		finally
		{
			GUI.matrix = previousMatrix;
			GUI.color = previousColor;
			GUI.depth = previousDepth;
		}
	}

	private static void DrawWindow(float screenWidth, float screenHeight)
	{
		Fill(new Rect(0f, 0f, screenWidth, screenHeight), DimColor);
		var width = Mathf.Min(WindowWidth, screenWidth - Margin * 2f);
		var height = Mathf.Min(WindowHeight, screenHeight - Margin * 2f);
		var panel = new Rect((screenWidth - width) * 0.5f, (screenHeight - height) * 0.5f, width, height);
		Fill(panel, GoldColor);
		Fill(Inset(panel, 2f), PanelColor);
		Fill(new Rect(panel.x + 2f, panel.y + 2f, panel.width - 4f, 5f), GoldColor);

		Label(new Rect(panel.x + 24f, panel.y + 16f, panel.width - 48f, 32f), "Gameplay Options", _titleStyle, TitleColor);

		var settings = GoldenEraGameplayOptions.Current.Clone();
		var changed = false;
		var y = panel.y + 58f;
		var x = panel.x + 24f;
		var rowWidth = panel.width - 48f;

		changed |= ChoiceRow(new Rect(x, y, rowWidth, RowHeight), "Hero movement", "Adventure-map movement points for every hero (stacks with Logistics).",
			GoldenEraGameplayOptions.MovementChoices, ref settings.MovementMultiplier, v => "x" + v);
		y += RowHeight;
		changed |= ChoiceRow(new Rect(x, y, rowWidth, RowHeight), "Experience gain", "Heroes need less experience per level.",
			GoldenEraGameplayOptions.ExperienceChoices, ref settings.ExperienceMultiplier, v => "x" + v);
		y += RowHeight;
		changed |= ChoiceRow(new Rect(x, y, rowWidth, RowHeight), "Neutral monster strength", "Size of wandering monsters and guards on generated maps.",
			GoldenEraGameplayOptions.NeutralStrengthChoices, ref settings.NeutralStrength, v => Mathf.RoundToInt(v * 100f) + "%");
		y += RowHeight;
		var reset = (int)settings.SiteReset;
		changed |= ChoiceRow(new Rect(x, y, rowWidth, RowHeight), "One-time sites reset", "Sites you can only visit once (Tree of Knowledge, Learning Stone...) restock.",
			new[] { 0, 1, 2 }, ref reset, v => ((GoldenEraGameplayOptions.SiteResetMode)v).ToString());
		settings.SiteReset = (GoldenEraGameplayOptions.SiteResetMode)reset;
		y += RowHeight;
		changed |= ChoiceRow(new Rect(x, y, rowWidth, RowHeight), "Monsters leave gold", "Beating neutral monsters pays a share of their recruit cost.",
			GoldenEraGameplayOptions.MonsterGoldChoices, ref settings.MonsterGoldPercent, v => v == 0 ? "Off" : v + "%");
		y += RowHeight;

		if (changed)
			GoldenEraGameplayOptions.Save(settings);

		Label(new Rect(x, y + 4f, rowWidth, 40f),
			"Saved automatically. Movement and monster strength apply to new games; the rest also to loaded games. Every side uses them, AI included. Single player only.",
			_noteStyle, NoteColor);

		var buttonY = panel.yMax - 48f;
		if (FrameButton(new Rect(x, buttonY, 130f, 32f), "Defaults", !GoldenEraGameplayOptions.Current.IsDefault))
			GoldenEraGameplayOptions.Save(new GoldenEraGameplayOptions.Settings());
		if (FrameButton(new Rect(panel.xMax - 24f - 130f, buttonY, 130f, 32f), "Done", true))
			_open = false;
	}

	private static bool ChoiceRow<T>(Rect row, string title, string hint, T[] choices, ref T value, Func<T, string> text)
	{
		Label(new Rect(row.x, row.y, row.width * 0.46f, 24f), title, _labelStyle, BodyColor);
		Label(new Rect(row.x, row.y + 22f, row.width * 0.46f, 36f), hint, _hintStyle, NoteColor);
		var areaX = row.x + row.width * 0.48f;
		var areaWidth = row.width - row.width * 0.48f;
		var gap = 6f;
		var width = (areaWidth - gap * (choices.Length - 1)) / choices.Length;
		var changed = false;
		for (var i = 0; i < choices.Length; i++)
		{
			var rect = new Rect(areaX + i * (width + gap), row.y + 8f, width, 34f);
			var selected = Equals(choices[i], value);
			if (selected)
			{
				Fill(rect, GoldColor);
				Label(rect, text(choices[i]), _choiceStyle, SelectedTextColor);
			}
			else
			{
				var hover = rect.Contains(Event.current.mousePosition);
				Fill(rect, GoldDimColor);
				Fill(Inset(rect, 1f), hover ? ChoiceHoverColor : ChoiceColor);
				Label(rect, text(choices[i]), _choiceStyle, BodyColor);
			}
			if (GUI.Button(rect, GUIContent.none, GUIStyle.none) && !selected)
			{
				value = choices[i];
				changed = true;
			}
		}
		return changed;
	}

	private static bool FrameButton(Rect rect, string text, bool enabled)
	{
		var hover = enabled && rect.Contains(Event.current.mousePosition);
		Fill(rect, enabled ? GoldColor : GoldDimColor);
		Fill(Inset(rect, 2f), hover ? ChoiceHoverColor : ChoiceColor);
		Label(rect, text, _choiceStyle, enabled ? TitleColor : NoteColor);
		return enabled && GUI.Button(rect, GUIContent.none, GUIStyle.none);
	}

	private static void EnsureStyles()
	{
		if (_titleStyle != null)
			return;
		_titleStyle = new GUIStyle(GUI.skin.label) { fontSize = 22, fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleLeft };
		_labelStyle = new GUIStyle(GUI.skin.label) { fontSize = 15, fontStyle = FontStyle.Bold, alignment = TextAnchor.UpperLeft };
		_hintStyle = new GUIStyle(GUI.skin.label) { fontSize = 11, wordWrap = true, alignment = TextAnchor.UpperLeft };
		_choiceStyle = new GUIStyle(GUI.skin.label) { fontSize = 14, fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleCenter };
		_noteStyle = new GUIStyle(GUI.skin.label) { fontSize = 11, wordWrap = true, fontStyle = FontStyle.Italic, alignment = TextAnchor.UpperLeft };
	}

	private static Rect Inset(Rect rect, float by) => new(rect.x + by, rect.y + by, rect.width - by * 2f, rect.height - by * 2f);

	private static void Fill(Rect rect, Color color)
	{
		GUI.color = color;
		GUI.DrawTexture(rect, Texture2D.whiteTexture);
		GUI.color = Color.white;
	}

	private static void Label(Rect rect, string text, GUIStyle style, Color color)
	{
		style.normal.textColor = color;
		GUI.Label(rect, text, style);
	}

	// ---------------------------------------------------------------- pointer shield

	private static void AttachPointerShield()
	{
		var canvasObject = new GameObject("OFFLINE_UNLOCK_MOD_GAMEPLAY_OPTIONS_POINTER_SHIELD", new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<Canvas>(),
			Il2CppType.Of<GraphicRaycaster>(),
		})
		{
			hideFlags = HideFlags.HideAndDontSave,
		};
		var canvas = canvasObject.GetComponent<Canvas>();
		if (canvas == null || canvasObject.GetComponent<GraphicRaycaster>() == null)
		{
			UnityObject.Destroy(canvasObject);
			throw new InvalidOperationException("pointer shield canvas/raycaster could not be created");
		}
		canvas.renderMode = RenderMode.ScreenSpaceOverlay;
		canvas.overrideSorting = true;
		canvas.sortingOrder = 32766;
		var imageObject = new GameObject("GameplayOptionsRaycastTarget", new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<CanvasRenderer>(),
			Il2CppType.Of<UnityImage>(),
		});
		imageObject.transform.SetParent(canvasObject.transform, false);
		var image = imageObject.GetComponent<UnityImage>();
		if (image == null)
		{
			UnityObject.Destroy(canvasObject);
			throw new InvalidOperationException("pointer shield image could not be created");
		}
		image.color = new Color(0f, 0f, 0f, 0f);
		image.raycastTarget = true;
		image.maskable = false;
		image.canvasRenderer.cullTransparentMesh = false;
		image.enabled = false;
		_shieldCanvas = canvas;
		_shieldImage = image;
		UnityObject.DontDestroyOnLoad(canvasObject);
	}

	/// <summary>Moves the raycast target over <paramref name="screenRect"/> (screen pixels, top-left origin).</summary>
	private static void UpdateShield(Rect screenRect)
	{
		if (_shieldImage == null || _shieldCanvas == null)
			return;
		var rect = _shieldImage.rectTransform;
		rect.anchorMin = new Vector2(0f, 1f);
		rect.anchorMax = new Vector2(0f, 1f);
		rect.pivot = new Vector2(0f, 1f);
		rect.anchoredPosition = new Vector2(screenRect.x, -screenRect.y);
		rect.sizeDelta = new Vector2(screenRect.width, screenRect.height);
		_shieldImage.enabled = true;
	}

	private static void HideShield()
	{
		try
		{
			if (_shieldImage != null)
				_shieldImage.enabled = false;
		}
		catch
		{
		}
	}
}

public sealed class GoldenEraGameplayOptionsMenuHost : MonoBehaviour
{
	public GoldenEraGameplayOptionsMenuHost(IntPtr ptr) : base(ptr) { }

	private void OnGUI() => GoldenEraGameplayOptionsMenu.OnHostGui();
}
