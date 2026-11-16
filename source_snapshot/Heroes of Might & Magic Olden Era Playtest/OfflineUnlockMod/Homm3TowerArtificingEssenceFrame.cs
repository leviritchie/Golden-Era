using System;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.Injection;
using TMPro;
using UnityEngine;
using L = OfflineUnlockMod.Homm3TowerArtificingPickerLayout;
using P = OfflineUnlockMod.Homm3TowerArtificingPicker;
using UnityImage = UnityEngine.UI.Image;

namespace OfflineUnlockMod;

/// <summary>
/// Arcane Essence next to the hero portrait. Vanilla Hex.UI.BhFrameEnergyHero is the small frame beside the portrait
/// that shows a Necromancy (Undead) or Schism (Unfrozen) hero's energy; its bind (Hero, bool) hides it (CanvasGroup
/// alpha 0) when the hero has no energy type (26615913 uny: ffj.blrc false). For a hero with the Artificing faction
/// skill and no vanilla energy, the postfix re-shows that frame with the essence icon and a live essence count.
/// Every type and member is resolved by deobfuscated name / signature, so a build without the frame just skips it.
/// </summary>
internal static class Homm3TowerArtificingEssenceFrame
{
	private const string LogPrefix = "HoMM3 Tower Artificing: [essence frame] ";
	private const string OverlayName = "Homm3ArtificingEssence";

	private static ManualLogSource _log;
	private static bool _registered;
	private static bool _typeRegistered;
	private static PropertyInfo _fill, _group, _iconEnergy, _iconNecromancyActive, _infoUndead, _infoUnfrozen, _forceHide, _button, _hero;
	private static bool _loggedApplyFailure;

	internal static void TryRegister(Harmony harmony, Assembly hexAssembly, ManualLogSource log)
	{
		if (_registered || harmony == null || hexAssembly == null)
			return;
		_registered = true;
		_log = log;
		try
		{
			var frameType = hexAssembly.GetType("Hex.UI.BhFrameEnergyHero", false)
				?? throw new InvalidOperationException("Hex.UI.BhFrameEnergyHero not found");
			const BindingFlags inst = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
			_fill = frameType.GetProperty("fill", inst);
			_group = frameType.GetProperty("group", inst);
			_iconEnergy = frameType.GetProperty("iconEnergy", inst);
			_iconNecromancyActive = frameType.GetProperty("iconNecromancyActive", inst);
			_infoUndead = frameType.GetProperty("infoUndead", inst);
			_infoUnfrozen = frameType.GetProperty("infoUnfrozen", inst);
			_forceHide = frameType.GetProperty("forceHide", inst);
			_button = frameType.GetProperty("buttonNecromancyChange", inst);
			if (_group == null || _iconEnergy == null)
				throw new InvalidOperationException("frame members group/iconEnergy missing");

			// The public (Hex.Session.Logic.Hero, bool) bind; the hero is the only Hero-typed parameter in the class.
			MethodInfo bind = null;
			foreach (var m in frameType.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly))
			{
				var ps = m.GetParameters();
				if (m.ReturnType == typeof(void) && ps.Length == 2 && ps[1].ParameterType == typeof(bool)
					&& ps[0].ParameterType.FullName == "Hex.Session.Logic.Hero")
				{
					if (bind != null)
						throw new InvalidOperationException("ambiguous (Hero, bool) bind: " + bind.Name + " / " + m.Name);
					bind = m;
				}
			}
			if (bind == null)
				throw new InvalidOperationException("(Hero, bool) bind not found");
			foreach (var prop in frameType.GetProperties(inst))
			{
				if (prop.PropertyType == bind.GetParameters()[0].ParameterType && prop.CanRead)
				{
					_hero = prop;
					break;
				}
			}

			harmony.Patch(bind,
				prefix: new HarmonyMethod(typeof(Homm3TowerArtificingEssenceFrame), nameof(PrefixBind)),
				postfix: new HarmonyMethod(typeof(Homm3TowerArtificingEssenceFrame), nameof(PostfixBind)));
			_log?.LogInfo(LogPrefix + "registered on " + frameType.FullName + "." + bind.Name);
		}
		catch (Exception ex)
		{
			_log?.LogWarning(LogPrefix + "NOT registered (no essence beside the hero portrait): " + ex.GetBaseException().Message);
		}
	}

	/// <summary>The native bind always rewrites the group alpha (0 or 1) unless forceHide returns early, so clearing it
	/// first makes the post-bind alpha say exactly whether vanilla showed an energy type for this hero.</summary>
	private static void PrefixBind(object __instance)
	{
		try
		{
			if (__instance is Component frame && !(_forceHide?.GetValue(frame) is bool b && b) && _group.GetValue(frame) is CanvasGroup group)
				group.alpha = 0f;
		}
		catch
		{
			// The postfix logs.
		}
	}

	private static void PostfixBind(object __instance, object __0)
	{
		try
		{
			Apply(__instance as Component, __0);
		}
		catch (Exception ex)
		{
			if (!_loggedApplyFailure)
			{
				_loggedApplyFailure = true;
				_log?.LogWarning(LogPrefix + "apply failed: " + ex.GetBaseException().Message);
			}
		}
	}

	/// <summary>Re-reads the essence for a frame's bound hero (the host's poll; also after a graft or a battle).</summary>
	internal static void Refresh(Homm3TowerArtificingEssenceFrameHost host)
	{
		if (host == null || host.Frame == null)
			return;
		var hero = _hero?.GetValue(host.Frame);
		if (hero == null || !Homm3TowerArtificingRuntime.TryReadState(hero, out var state, out _))
			return;
		if (host.Label != null && host.Shown != state.Essence)
		{
			host.Shown = state.Essence;
			host.Label.text = state.Essence.ToString();
		}
	}

	private static void Apply(Component frame, object hero)
	{
		if (frame == null)
			return;
		var overlay = frame.transform.Find(OverlayName);
		var host = overlay != null ? overlay.GetComponent<Homm3TowerArtificingEssenceFrameHost>() : null;
		var group = _group.GetValue(frame) as CanvasGroup;
		var forceHide = _forceHide?.GetValue(frame) is bool b && b;
		// The native bind set alpha 1 only when the hero has a vanilla energy type (the prefix cleared it); that stays vanilla.
		var vanillaShown = group != null && group.alpha > 0.5f;
		var ours = !forceHide && hero != null && group != null && !vanillaShown
			&& Homm3TowerArtificingRuntime.HeroHasArtificing(hero)
			&& Homm3TowerArtificingRuntime.TryReadState(hero, out _, out _);

		var icon = _iconEnergy.GetValue(frame) as UnityImage;
		var fill = _fill?.GetValue(frame) as UnityImage;
		if (!ours)
		{
			if (host != null && host.Active)
			{
				host.Active = false;
				if (icon != null)
					icon.color = host.IconColor;
				if (fill != null)
					fill.enabled = true;
				overlay.gameObject.SetActive(false);
			}
			return;
		}

		if (host == null)
			host = CreateOverlay(frame, icon);
		if (host == null)
			return;
		if (!host.Active)
		{
			host.Active = true;
			if (icon != null)
				host.IconColor = icon.color;
		}
		host.Frame = frame;
		host.Shown = -1;
		host.gameObject.SetActive(true);

		group.alpha = 1f;
		group.blocksRaycasts = false;
		group.interactable = false;
		if (icon != null)
		{
			icon.gameObject.SetActive(true);
			P.ResolveNativeSprites();
			var essence = P.NativeSprite(L.SpriteEssence);
			if (essence)
			{
				icon.sprite = essence;
				icon.color = L.EssenceTint;
			}
		}
		if (fill != null && !fill.sprite)
			fill.enabled = false;
		SetActive(_iconNecromancyActive?.GetValue(frame) as Component, false);
		SetActive(_infoUndead?.GetValue(frame) as GameObject, false);
		SetActive(_infoUnfrozen?.GetValue(frame) as GameObject, false);
		SetActive(_button?.GetValue(frame) as Component, false);
		Refresh(host);
	}

	private static Homm3TowerArtificingEssenceFrameHost CreateOverlay(Component frame, UnityImage icon)
	{
		if (!_typeRegistered)
		{
			ClassInjector.RegisterTypeInIl2Cpp<Homm3TowerArtificingEssenceFrameHost>();
			_typeRegistered = true;
		}
		var go = new GameObject(OverlayName, new Il2CppSystem.Type[] { Il2CppType.Of<RectTransform>() });
		go.transform.SetParent(frame.transform, false);
		var rect = go.GetComponent<RectTransform>();
		rect.anchorMin = Vector2.zero;
		rect.anchorMax = Vector2.one;
		rect.offsetMin = Vector2.zero;
		rect.offsetMax = Vector2.zero;
		go.transform.SetAsLastSibling();
		var host = go.AddComponent<Homm3TowerArtificingEssenceFrameHost>();
		if (host == null)
			return null;

		// The count sits over the lower part of the essence icon, like a stack count, so it never leaves the frame.
		var parent = icon != null ? icon.rectTransform : rect;
		var label = P.AddText(go.transform, L.FontMedium, 18f, "0", 0f, 0f, 10f, 10f, Color.white, TextAlignmentOptions.Bottom);
		if (label != null)
		{
			var lr = label.rectTransform;
			lr.SetParent(parent, false);
			lr.anchorMin = new Vector2(-0.4f, -0.15f);
			lr.anchorMax = new Vector2(1.4f, 0.45f);
			lr.offsetMin = Vector2.zero;
			lr.offsetMax = Vector2.zero;
			label.enableAutoSizing = true;
			label.fontSizeMin = 10f;
			label.fontSizeMax = 22f;
			label.outlineWidth = 0.25f;
			label.outlineColor = new Color32(0, 0, 0, 255);
			// Parented under the icon so it follows it; the overlay object toggles it with the frame mode.
			host.LabelOwner = label.gameObject;
		}
		host.Label = label;
		return host;
	}

	private static void SetActive(Component c, bool on)
	{
		if (c != null && c.gameObject.activeSelf != on)
			c.gameObject.SetActive(on);
	}

	private static void SetActive(GameObject go, bool on)
	{
		if (go != null && go.activeSelf != on)
			go.SetActive(on);
	}
}

public sealed class Homm3TowerArtificingEssenceFrameHost : MonoBehaviour
{
	public Homm3TowerArtificingEssenceFrameHost(IntPtr ptr) : base(ptr) { }

	internal Component Frame;
	internal TextMeshProUGUI Label;
	internal GameObject LabelOwner;
	internal Color IconColor = Color.white;
	internal bool Active;
	internal int Shown = -1;
	private float _next;

	private void OnEnable()
	{
		if (LabelOwner != null)
			LabelOwner.SetActive(true);
	}

	private void OnDisable()
	{
		if (LabelOwner != null)
			LabelOwner.SetActive(false);
	}

	private void Update()
	{
		if (Time.unscaledTime < _next)
			return;
		_next = Time.unscaledTime + 0.5f;
		try
		{
			Homm3TowerArtificingEssenceFrame.Refresh(this);
		}
		catch
		{
			// A stale hero between binds; the next bind re-applies.
		}
	}
}
