using System;
using System.Collections.Generic;
using System.IO;
using BepInEx.Logging;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using A = OfflineUnlockMod.Homm3TowerArtificingPicker;
using P = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using UnityObject = UnityEngine.Object;

namespace OfflineUnlockMod;

/// <summary>
/// Geometry, heat and timing of the Warcry chain counter, in units of a 1920x1080 canvas (top-left origin, y down).
/// tools/stronghold_warcry/build_counter_mockup.py mirrors these values; change both together.
/// Art cells come from tools/stronghold_warcry/build_counter_art.py (homm3_ui/stronghold_warcry).
/// </summary>
internal static class Homm3StrongholdWarcryCounterLayout
{
	internal const string ArtFolder = "stronghold_warcry";
	internal const int CellWidth = 160;
	internal const int CellHeight = 224;
	internal const int DigitBaseline = 204;
	internal const int DigitAdvance = 92;
	internal const int FlameFrames = 24;
	internal const int FlameDownscale = 2;
	internal const int HeatStages = 5;
	internal const int LabelWidth = 320;
	internal const int LabelHeight = 72;
	internal const int MaxDigits = 3;

	/// <summary>Right edge of the number and the baseline of the digits on the 1920x1080 canvas.</summary>
	internal const float AnchorRightX = 1836f;
	internal const float BaselineY = 356f;
	/// <summary>Cell pixels to canvas units.</summary>
	internal const float DigitScale = 0.86f;
	internal const float LabelScale = 0.62f;
	internal const float LabelGap = 12f;
	internal const float SubTextSize = 21f;
	internal const float SubTextGap = 0f;
	internal const int SortingOrder = 40;

	/// <summary>Lowest chain value of each heat stage (stage 0 starts at 1).</summary>
	internal static readonly int[] StageFrom = { 1, 3, 6, 10, 15 };
	/// <summary>Per stage: flame opacity, flame size (around the digit's foot), flame frames per second, shake in canvas units.</summary>
	internal static readonly float[] FlameAlpha = { 0.50f, 0.72f, 0.88f, 1.00f, 1.00f };
	internal static readonly float[] FlameSize = { 0.90f, 1.00f, 1.10f, 1.22f, 1.36f };
	internal static readonly float[] FlameFps = { 13f, 16f, 19f, 23f, 27f };
	internal static readonly float[] Shake = { 0f, 0f, 0.6f, 1.4f, 2.4f };

	/// <summary>Hit: the number punches in oversized and settles; a white flash fades with it.</summary>
	internal const float PopSeconds = 0.26f;
	internal const float PopScale = 1.55f;
	internal const float PopScalePerStage = 0.08f;
	/// <summary>Break: the dead number greys out, drops and fades.</summary>
	internal const float BreakSeconds = 0.55f;
	internal const float BreakDrop = 46f;
	internal const float BreakTilt = -9f;

	internal static int StageFor(int value)
	{
		var stage = 0;
		for (var i = 0; i < StageFrom.Length; i++)
		{
			if (value >= StageFrom[i])
				stage = i;
		}
		return stage;
	}
}

/// <summary>
/// The Warcry chain counter: a fighting-game combo number in savage numerals that gets hotter (face colour, flame
/// size, flame speed, shake) as the Stronghold chain bonus grows, punches in on every hit and drops off when the chain
/// breaks. Pure display: it reads <see cref="Homm3StrongholdWarcryRuntime.TryGetCounter"/> every frame and never
/// touches battle state. Hidden while there is no chain.
/// </summary>
internal static class Homm3StrongholdWarcryCounter
{
	private const string CanvasObjectName = "Homm3StrongholdWarcryCounter";
	private static readonly Color SubTextColor = new(1f, 0.86f, 0.62f, 0.96f);
	private static readonly Color DeadColor = new(0.42f, 0.36f, 0.34f, 1f);

	private sealed class Digit
	{
		internal RectTransform Root;
		internal Image Flame;
		internal Image FlameNext;
		internal Image Face;
	}

	private static ManualLogSource _log;
	private static bool _pumpCreated;
	private static bool _failed;
	private static GameObject _canvasObject;
	private static RectTransform _group;
	private static readonly Digit[] Digits = new Digit[Homm3StrongholdWarcryCounterLayout.MaxDigits];
	private static Image _label;
	private static TextMeshProUGUI _subText;
	private static CanvasGroup _groupAlpha;
	private static Texture2D _faceTexture;
	private static Texture2D _flameTexture;
	private static Texture2D _labelTexture;
	private static readonly Dictionary<int, Sprite> FaceSprites = new();
	private static readonly Dictionary<int, Sprite> FlameSprites = new();
	private static readonly Sprite[] LabelSprites = new Sprite[Homm3StrongholdWarcryCounterLayout.HeatStages];

	private static int _shownValue;
	private static int _shownContributors = -1;
	private static float _nextViewCheck;
	private static bool _battleViewUp;
	private static int _attack;
	private static int _shownAttack = -1;
	private static int _shownStage = -1;
	private static int _breakSerial;
	private static bool _hasSerials;
	private static float _popAt = -10f;
	private static float _breakAt = -10f;
	private static int _breakValue;
	private static float _flameClock;

	internal static void TryRegister(ManualLogSource log)
	{
		_log = log;
		if (_pumpCreated || !Homm3StrongholdWarcryRuntime.Registered)
			return;
		try
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3StrongholdWarcryCounterPump>();
			var go = new GameObject("Homm3StrongholdWarcryCounterPump");
			go.AddComponent<Homm3StrongholdWarcryCounterPump>();
			UnityObject.DontDestroyOnLoad(go);
			_pumpCreated = true;
			_log?.LogInfo("HoMM3 Stronghold Warcry counter registered (shown while a chain is alive).");
		}
		catch (Exception ex)
		{
			_log?.LogWarning("HoMM3 Stronghold Warcry counter NOT registered (the chain still works, no on-screen number): " + ex.GetBaseException().Message);
		}
	}

	internal static void Tick()
	{
		if (_failed)
			return;
		try
		{
			var now = Time.unscaledTime;
			// Auto-battle runs the battle logic with no battle on screen, so the chain is live but has nothing to show
			// (user, 2026-11-18). Show the counter only while the battle view is up.
			// The chain is asked first: without one there is nothing to show, and the view check below scans every
			// loaded object when no battle is on screen (it ran 4 times a second on the map, in towns and menus).
			var hasChain = Homm3StrongholdWarcryRuntime.TryGetCounter(out var snapshot);
			if (!hasChain)
			{
				_nextViewCheck = 0f;
				_battleViewUp = false;
			}
			else if (now >= _nextViewCheck)
			{
				_nextViewCheck = now + 0.25f;
				_battleViewUp = BattleQueueOnScreen();
			}
			var active = hasChain && _battleViewUp;
			if (!active)
			{
				_hasSerials = false;
				_shownValue = 0;
				if (_canvasObject && _canvasObject.activeSelf)
					_canvasObject.SetActive(false);
				return;
			}
			if (!_hasSerials)
			{
				_hasSerials = true;
				_breakSerial = snapshot.BreakSerial;
				_shownValue = 0;
				_breakAt = -10f;
			}
			if (snapshot.BreakSerial != _breakSerial)
			{
				_breakSerial = snapshot.BreakSerial;
				if (_shownValue > 0)
				{
					_breakAt = now;
					_breakValue = _shownValue;
				}
			}
			var breaking = now - _breakAt < Homm3StrongholdWarcryCounterLayout.BreakSeconds;
			if (snapshot.Value > _shownValue && snapshot.Value > 0)
			{
				_popAt = now;
				_breakAt = -10f;
				breaking = false;
			}
			_shownValue = snapshot.Value;
			if (snapshot.Value <= 0 && !breaking)
			{
				if (_canvasObject && _canvasObject.activeSelf)
					_canvasObject.SetActive(false);
				return;
			}
			if (!EnsureBuilt())
				return;
			if (!_canvasObject.activeSelf)
				_canvasObject.SetActive(true);
			_attack = snapshot.Attack;
			Draw(breaking ? _breakValue : snapshot.Value, snapshot.Contributors, breaking, now);
		}
		catch (Exception ex)
		{
			_failed = true;
			_log?.LogWarning("HoMM3 Stronghold Warcry counter stopped (display only; the chain still works): " + ex.GetBaseException().Message);
			try
			{
				if (_canvasObject)
					_canvasObject.SetActive(false);
			}
			catch
			{
			}
		}
	}

	private static Hex.Session.Battle.BhTurnView _queueItem;

	/// <summary>True while the battle initiative bar is on screen. Auto-battle never builds it. (Hex.Session.Battle.BhActiveBattle,
	/// which TempleSwordsmanBillboardPrototype.IsBattleViewActive looks for, is gone from build 26615913.)</summary>
	private static bool BattleQueueOnScreen()
	{
		try
		{
			if (_queueItem && _queueItem.gameObject.activeInHierarchy)
				return true;
			_queueItem = null;
			foreach (var view in Resources.FindObjectsOfTypeAll<Hex.Session.Battle.BhTurnView>())
			{
				if (view && view.gameObject.activeInHierarchy)
				{
					_queueItem = view;
					return true;
				}
			}
			return false;
		}
		catch
		{
			return true; // fail open: a counter that shows is better than one that never does
		}
	}

	private static void Draw(int value, int contributors, bool breaking, float now)
	{
		value = Math.Min(value, 999);
		var stage = Homm3StrongholdWarcryCounterLayout.StageFor(value);
		var text = value.ToString();
		var scale = Homm3StrongholdWarcryCounterLayout.DigitScale;
		var advance = Homm3StrongholdWarcryCounterLayout.DigitAdvance * scale;

		// flame clock (per-stage speed)
		_flameClock += Time.unscaledDeltaTime * Homm3StrongholdWarcryCounterLayout.FlameFps[stage];
		var frame = (int)_flameClock % Homm3StrongholdWarcryCounterLayout.FlameFrames;
		// The flipbook runs at 13-27 fps; each frame cross-fades into the next so the fire moves at the display rate.
		var blend = _flameClock - Mathf.Floor(_flameClock);
		_shownStage = stage;

		for (var i = 0; i < Digits.Length; i++)
		{
			var digit = Digits[i];
			var index = text.Length - Digits.Length + i; // right aligned
			var on = index >= 0;
			if (digit.Root.gameObject.activeSelf != on)
				digit.Root.gameObject.SetActive(on);
			if (!on)
				continue;
			var d = text[index] - '0';
			// slot 0 is the rightmost digit
			var slotFromRight = Digits.Length - 1 - i;
			digit.Root.anchoredPosition = new Vector2(-(slotFromRight + 0.5f) * advance, 0f);
			digit.Face.sprite = FaceSprite(d, stage);
			// neighbouring digits run the same fire a few frames apart so the number never pulses as one block
			digit.Flame.sprite = FlameSprite(d, (frame + i * 7) % Homm3StrongholdWarcryCounterLayout.FlameFrames);
			digit.FlameNext.sprite = FlameSprite(d, (frame + 1 + i * 7) % Homm3StrongholdWarcryCounterLayout.FlameFrames);
			var flameSize = Homm3StrongholdWarcryCounterLayout.FlameSize[stage];
			digit.Flame.rectTransform.localScale = new Vector3(flameSize, flameSize, 1f);
			digit.FlameNext.rectTransform.localScale = new Vector3(flameSize, flameSize, 1f);
			var flameAlpha = breaking ? 0f : Homm3StrongholdWarcryCounterLayout.FlameAlpha[stage];
			digit.Flame.color = new Color(1f, 1f, 1f, flameAlpha * (1f - blend * blend));
			digit.FlameNext.color = new Color(1f, 1f, 1f, flameAlpha * blend);
			digit.Face.color = breaking ? DeadColor : Color.white;
		}

		if (_label.sprite != LabelSprite(stage))
			_label.sprite = LabelSprite(stage);
		_label.color = breaking ? DeadColor : Color.white;
		if (contributors != _shownContributors || _attack != _shownAttack)
		{
			_shownContributors = contributors;
			_shownAttack = _attack;
			_subText.text = "x" + contributors + " warcrying   +" + _attack + " Attack";
		}

		// motion: pop on a hit, shake when hot, drop on a break
		var groupScale = 1f;
		var offset = Vector2.zero;
		var alpha = 1f;
		var tilt = 0f;
		if (breaking)
		{
			var t = Mathf.Clamp01((now - _breakAt) / Homm3StrongholdWarcryCounterLayout.BreakSeconds);
			offset.y = -Homm3StrongholdWarcryCounterLayout.BreakDrop * t * t;
			tilt = Homm3StrongholdWarcryCounterLayout.BreakTilt * t;
			alpha = 1f - t * t;
		}
		else
		{
			var t = (now - _popAt) / Homm3StrongholdWarcryCounterLayout.PopSeconds;
			if (t < 1f)
			{
				var peak = Homm3StrongholdWarcryCounterLayout.PopScale + Homm3StrongholdWarcryCounterLayout.PopScalePerStage * stage;
				var ease = 1f - (1f - t) * (1f - t) * (1f - t);
				// overshoot slightly under 1 before settling, like a stamped hit
				groupScale = Mathf.LerpUnclamped(peak, 1f, ease) - 0.06f * Mathf.Sin(t * Mathf.PI) * (t > 0.5f ? 1f : 0f);
			}
			var shake = Homm3StrongholdWarcryCounterLayout.Shake[stage];
			if (shake > 0f)
				offset += new Vector2(Mathf.PerlinNoise(now * 23f, 0.3f) - 0.5f, Mathf.PerlinNoise(0.7f, now * 27f) - 0.5f) * (2f * shake);
		}
		_group.localScale = new Vector3(groupScale, groupScale, 1f);
		_group.anchoredPosition = new Vector2(Homm3StrongholdWarcryCounterLayout.AnchorRightX, -Homm3StrongholdWarcryCounterLayout.BaselineY) + offset;
		_group.localRotation = Quaternion.Euler(0f, 0f, tilt);
		_groupAlpha.alpha = alpha;
	}

	// ------------------------------------------------------------------ build

	private static bool EnsureBuilt()
	{
		if (_canvasObject)
			return true;
		_faceTexture = LoadTexture("digits_face");
		_flameTexture = LoadTexture("digits_flame");
		_labelTexture = LoadTexture("label");
		if (!_faceTexture || !_flameTexture || !_labelTexture)
		{
			_failed = true;
			_log?.LogWarning("HoMM3 Stronghold Warcry counter: art missing under homm3_ui/" + Homm3StrongholdWarcryCounterLayout.ArtFolder + "; no on-screen number.");
			return false;
		}
		FaceSprites.Clear();
		FlameSprites.Clear();
		Array.Clear(LabelSprites, 0, LabelSprites.Length);

		var go = new GameObject(CanvasObjectName, new Il2CppSystem.Type[]
		{
			Il2CppType.Of<RectTransform>(),
			Il2CppType.Of<Canvas>(),
			Il2CppType.Of<CanvasScaler>(),
		});
		UnityObject.DontDestroyOnLoad(go);
		_canvasObject = go;
		var canvas = go.GetComponent<Canvas>();
		var scaler = go.GetComponent<CanvasScaler>();
		canvas.renderMode = RenderMode.ScreenSpaceOverlay;
		canvas.overrideSorting = true;
		canvas.sortingOrder = Homm3StrongholdWarcryCounterLayout.SortingOrder;
		scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
		scaler.referenceResolution = new Vector2(P.ReferenceWidth, P.ReferenceHeight);
		scaler.screenMatchMode = CanvasScaler.ScreenMatchMode.MatchWidthOrHeight;
		scaler.matchWidthOrHeight = Screen.height > 0 && Screen.width / (float)Screen.height >= P.ReferenceWidth / P.ReferenceHeight ? 1f : 0f;
		var canvasRect = go.GetComponent<RectTransform>();

		// Group origin = right end of the number on the digit baseline; everything hangs off it, so pop/shake/drop move as one.
		_group = A.NewRect("Group", canvasRect);
		_group.anchorMin = _group.anchorMax = new Vector2(0f, 1f);
		_group.pivot = new Vector2(1f, 0f);
		_group.sizeDelta = Vector2.zero;
		_groupAlpha = _group.gameObject.AddComponent<CanvasGroup>();
		_groupAlpha.blocksRaycasts = false;
		_groupAlpha.interactable = false;

		var scale = Homm3StrongholdWarcryCounterLayout.DigitScale;
		var cellW = Homm3StrongholdWarcryCounterLayout.CellWidth * scale;
		var cellH = Homm3StrongholdWarcryCounterLayout.CellHeight * scale;
		var footPivot = 1f - Homm3StrongholdWarcryCounterLayout.DigitBaseline / (float)Homm3StrongholdWarcryCounterLayout.CellHeight;
		// two passes so every flame sits behind every face (a hot neighbour's fire never covers a digit)
		for (var i = 0; i < Digits.Length; i++)
		{
			var root = A.NewRect("Digit" + i, _group);
			root.anchorMin = root.anchorMax = root.pivot = new Vector2(0.5f, 0.5f);
			root.sizeDelta = Vector2.zero;
			Digits[i] = new Digit { Root = root };
			Digits[i].Flame = NewCell("Flame", root, cellW, cellH, footPivot);
			Digits[i].FlameNext = NewCell("FlameNext", root, cellW, cellH, footPivot);
		}
		for (var i = 0; i < Digits.Length; i++)
			Digits[i].Face = NewCell("Face", Digits[i].Root, cellW, cellH, footPivot);
		for (var i = 0; i < Digits.Length; i++)
			Digits[i].Root.SetSiblingIndex(i);

		var labelScale = Homm3StrongholdWarcryCounterLayout.LabelScale;
		_label = A.NewImage("Label", _group, LabelSprite(0), Color.white);
		var labelRect = _label.rectTransform;
		labelRect.anchorMin = labelRect.anchorMax = new Vector2(0.5f, 0.5f);
		labelRect.pivot = new Vector2(1f, 1f);
		labelRect.sizeDelta = new Vector2(Homm3StrongholdWarcryCounterLayout.LabelWidth * labelScale, Homm3StrongholdWarcryCounterLayout.LabelHeight * labelScale);
		labelRect.anchoredPosition = new Vector2(18f, -Homm3StrongholdWarcryCounterLayout.LabelGap);

		var subTop = -(Homm3StrongholdWarcryCounterLayout.LabelGap + Homm3StrongholdWarcryCounterLayout.LabelHeight * labelScale + Homm3StrongholdWarcryCounterLayout.SubTextGap);
		// Dark smear behind the small line: the battlefield behind it runs from snow to lava (user, 2026-11-18).
		var plateTexture = LoadTexture("subline_plate");
		if (plateTexture)
		{
			var plate = A.NewImage("SubPlate", _group, Sprite.Create(plateTexture, new Rect(0, 0, plateTexture.width, plateTexture.height), new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect), Color.white);
			var plateRect = plate.rectTransform;
			plateRect.anchorMin = plateRect.anchorMax = new Vector2(0.5f, 0.5f);
			plateRect.pivot = new Vector2(1f, 0.5f);
			plateRect.sizeDelta = new Vector2(plateTexture.width, plateTexture.height);
			plateRect.anchoredPosition = new Vector2(10f, subTop - 14f);
		}
		_subText = A.AddText(_group, P.FontMedium, Homm3StrongholdWarcryCounterLayout.SubTextSize, string.Empty, 0f, 0f, 260f, 28f, SubTextColor, TextAlignmentOptions.Right);
		if (_subText != null)
		{
			var subRect = _subText.rectTransform;
			subRect.anchorMin = subRect.anchorMax = new Vector2(0.5f, 0.5f);
			subRect.pivot = new Vector2(1f, 1f);
			subRect.sizeDelta = new Vector2(260f, 28f);
			subRect.anchoredPosition = new Vector2(-4f, -(Homm3StrongholdWarcryCounterLayout.LabelGap + Homm3StrongholdWarcryCounterLayout.LabelHeight * labelScale + Homm3StrongholdWarcryCounterLayout.SubTextGap));
			_subText.fontStyle = FontStyles.Italic;
			_subText.outlineWidth = 0.3f;
			_subText.outlineColor = new Color32(20, 4, 2, 255);
		}
		_shownContributors = -1;
		_shownStage = -1;
		return true;
	}

	private static Image NewCell(string name, Transform parent, float width, float height, float footPivot)
	{
		var image = A.NewImage(name, parent, null, Color.white);
		var rect = image.rectTransform;
		rect.anchorMin = rect.anchorMax = new Vector2(0.5f, 0.5f);
		// pivot on the digit's foot: the cell hangs on the baseline and the flame scales up from it
		rect.pivot = new Vector2(0.5f, footPivot);
		rect.sizeDelta = new Vector2(width, height);
		rect.anchoredPosition = Vector2.zero;
		image.color = Color.white;
		return image;
	}

	private static Sprite FaceSprite(int digit, int stage)
	{
		var key = stage * 10 + digit;
		if (FaceSprites.TryGetValue(key, out var sprite) && sprite)
			return sprite;
		sprite = Slice(_faceTexture, digit, stage, Homm3StrongholdWarcryCounterLayout.CellWidth, Homm3StrongholdWarcryCounterLayout.CellHeight, "face_" + key);
		FaceSprites[key] = sprite;
		return sprite;
	}

	private static Sprite FlameSprite(int digit, int frame)
	{
		var key = frame * 10 + digit;
		if (FlameSprites.TryGetValue(key, out var sprite) && sprite)
			return sprite;
		var down = Homm3StrongholdWarcryCounterLayout.FlameDownscale;
		sprite = Slice(_flameTexture, digit, frame, Homm3StrongholdWarcryCounterLayout.CellWidth / down, Homm3StrongholdWarcryCounterLayout.CellHeight / down, "flame_" + key);
		FlameSprites[key] = sprite;
		return sprite;
	}

	private static Sprite LabelSprite(int stage)
	{
		if (LabelSprites[stage])
			return LabelSprites[stage];
		return LabelSprites[stage] = Slice(_labelTexture, 0, stage, Homm3StrongholdWarcryCounterLayout.LabelWidth, Homm3StrongholdWarcryCounterLayout.LabelHeight, "label_" + stage);
	}

	/// <summary>Cell (column, row counted from the top) of an atlas as a sprite.</summary>
	private static Sprite Slice(Texture2D texture, int column, int rowFromTop, int cellWidth, int cellHeight, string name)
	{
		var rect = new Rect(column * cellWidth, texture.height - (rowFromTop + 1) * cellHeight, cellWidth, cellHeight);
		var sprite = Sprite.Create(texture, rect, new Vector2(0.5f, 0.5f), 100f, 0, SpriteMeshType.FullRect);
		sprite.name = "homm3_stronghold_warcry_" + name;
		sprite.hideFlags = HideFlags.HideAndDontSave;
		return sprite;
	}

	private static Texture2D LoadTexture(string name)
	{
		var path = Path.Combine(BepInEx.Paths.PluginPath, "OfflineUnlockMod", "homm3_ui", Homm3StrongholdWarcryCounterLayout.ArtFolder, name + ".png");
		if (!File.Exists(path))
			return null;
		var bytes = File.ReadAllBytes(path);
		var texture = new Texture2D(2, 2, TextureFormat.RGBA32, mipChain: false);
		var il2cppBytes = new Il2CppStructArray<byte>(bytes.LongLength);
		// One block copy into the array's data (after the four-pointer IL2CPP array header), as the Cove treasure art loader does.
		System.Runtime.InteropServices.Marshal.Copy(bytes, 0, il2cppBytes.Pointer + IntPtr.Size * 4, bytes.Length);
		if (!ImageConversion.LoadImage(texture, il2cppBytes))
		{
			UnityObject.Destroy(texture);
			return null;
		}
		texture.name = "homm3_stronghold_warcry_" + name;
		texture.filterMode = FilterMode.Bilinear;
		texture.wrapMode = TextureWrapMode.Clamp;
		texture.hideFlags = HideFlags.HideAndDontSave;
		return texture;
	}
}

internal sealed class Homm3StrongholdWarcryCounterPump : MonoBehaviour
{
	public Homm3StrongholdWarcryCounterPump(IntPtr pointer) : base(pointer)
	{
	}

	private void LateUpdate()
	{
		Homm3StrongholdWarcryCounter.Tick();
	}
}
