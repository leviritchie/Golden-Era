using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Patches the battle unit prefab pool loader. This is narrower than ResManager.Get&lt;GameObject&gt;
/// and catches the path actually used by battle unit initialization after UnitViewConfig.mesh /
/// meshVariants has been resolved.
/// </summary>
internal static class EsquirePikemanBattlePoolHook
{
	private static bool _patched;
	private static int _loggedNonTarget;
	private static int _loggedReplace;
	private static int _loggedBoundsNoOpHint;
	private static bool _loggedPresentationAudit;
	private static int _loggedSkipAlreadyCustom;

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched)
			return;
		try
		{
			var t = Homm3BattlePoolInterop.ResolvePoolOwnerType();
			if (t == null)
			{
				log?.LogWarning("EsquirePikeman battle pool: loader type not found; battle visual hook not applied.");
				return;
			}

			const BindingFlags bathFlags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
			var candidates = new List<MethodInfo>();
			foreach (var m in t.GetMethods(bathFlags))
			{
				if (!Homm3BattlePoolInterop.MethodMatchesLoaderHints(m) || m.ReturnType != typeof(bool))
					continue;
				var ps = m.GetParameters();
				if (ps.Length != 3
				    || ps[0].ParameterType != typeof(string)
				    || !ps[1].ParameterType.IsByRef || !GameInteropTypes.TypesMatch(ps[1].ParameterType.GetElementType(), typeof(GameObject))
				    || !Homm3BattlePoolInterop.IsMetadataOutParameter(ps[2]))
					continue;
				candidates.Add(m);
			}

			if (candidates.Count == 0)
			{
				log?.LogWarning("EsquirePikeman battle pool: loader(string,out GameObject,out metadata):bool not found; hook not applied.");
				return;
			}

			// Patch only ONE layer of the call graph: if both static and instance `bath` exist, the static
			// wrapper typically forwards to the instance method. Patching BOTH runs this postfix twice on one
			// load — the second run sees the already-replaced bundle instance as "vanilla", destroys it, and
			// breaks every subsequent battle / pool state.
			var statics = candidates.FindAll(m => m.IsStatic);
			var toPatch = statics.Count > 0 ? statics : candidates.FindAll(m => !m.IsStatic);
			var postfix = new HarmonyMethod(typeof(EsquirePikemanBattlePoolHook), nameof(PostfixBath));
			var patched = new List<string>();
			foreach (var m in toPatch)
			{
				h.Patch(m, postfix: postfix);
				patched.Add((m.IsStatic ? "static" : "instance") + " " + m.Name);
			}

			// Postfix (not prefix+skip): Il2Cpp out/ref slots for GameObject/bei are populated by
			// vanilla first; mutating them after avoids empty refs that show up as invisible units.
			_patched = true;
			log?.LogInfo(
				"EsquirePikeman: Harmony postfix on "
				+ patched.Count
				+ " dzk.bath method(s) ("
				+ (statics.Count > 0 ? "static entry only" : "instance only")
				+ "): "
				+ string.Join(", ", patched));
		}
		catch (Exception ex)
		{
			log?.LogError("EsquirePikeman battle pool hook failed: " + ex);
		}
	}

	private static Type ResolveBattlePoolType() => Homm3BattlePoolInterop.ResolvePoolOwnerType();

	internal static void Cancel()
	{
		_patched = false;
		_loggedNonTarget = 0;
		_loggedReplace = 0;
		_loggedBoundsNoOpHint = 0;
		_loggedPresentationAudit = false;
		_loggedSkipAlreadyCustom = 0;
	}

	private static void PostfixBath(string a, ref GameObject b, ref object c, bool __result)
	{
		if (!IsEsquireBattlePath(a))
		{
			if (_loggedNonTarget < 8 || (!string.IsNullOrEmpty(a) && a.IndexOf("esquire", StringComparison.OrdinalIgnoreCase) >= 0))
			{
				_loggedNonTarget++;
				Plugin.LogSource?.LogInfo("EsquirePikeman battle pool: vanilla path '" + a + "'.");
			}
			return;
		}

		if (!__result || b == null)
		{
			Plugin.LogSource?.LogWarning(
				"EsquirePikeman battle pool: esquire path '"
				+ a
				+ "' but vanilla bath failed or GameObject null (result="
				+ __result
				+ ").");
			return;
		}

		try
		{
			// Pool can hand back our own prior instance; Destroy+re-Instantiate breaks the pool and
			// later spawns fall back to vanilla.
			if (LooksLikeOurBundleBattleInstance(b))
			{
				if (EsquirePikemanVisuals.VerboseEsquireHooks && _loggedSkipAlreadyCustom < 8)
				{
					_loggedSkipAlreadyCustom++;
					Plugin.LogSource?.LogInfo(
						"EsquirePikeman battle pool: keep existing custom instance (path '"
						+ a
						+ "').");
				}

				EsquireBattleAudioPlayer.TryAttach(b, Plugin.LogSource);
				EsquireBattleClipAudioDriver.TryAttach(b, Plugin.LogSource);
				Homm3BattleBillboardCameraFacing.TryAttach(b, Plugin.LogSource);
				return;
			}

			if (!EsquirePikemanVisuals.TryGetEsquireTemplateForUnitsPath(
				EsquirePikemanVisuals.BattleResPath,
				Plugin.LogSource,
				out var template)
			    || template == null)
			{
				Plugin.LogSource?.LogWarning("EsquirePikeman battle pool: custom battle template unavailable; keeping vanilla for '" + a + "'.");
				return;
			}

			var instance = UnityEngine.Object.Instantiate(template);
			if (instance == null)
			{
				Plugin.LogSource?.LogWarning("EsquirePikeman battle pool: Instantiate returned null; keeping vanilla for '" + a + "'.");
				return;
			}

			instance.name = template.name;
			// Vanilla battle units live under the formation/pool parent; an unparented Instantiate
			// sits at the wrong transform and can break culling / bounds. Match sibling placement.
			{
				var parent = b.transform.parent;
				var bt = b.transform;
				var it = instance.transform;
				it.SetParent(parent, false);
				it.localPosition = bt.localPosition;
				it.localRotation = bt.localRotation;
				it.localScale = bt.localScale;
			}

			var firstPresentationAudit = !_loggedPresentationAudit;
			if (firstPresentationAudit)
			{
				_loggedPresentationAudit = true;
				Plugin.LogSource?.LogInfo(EsquireBattleVisualPresentation.DescribeRenderTree("Esquire battle audit vanilla(before swap)", b));
				Plugin.LogSource?.LogInfo(
					EsquireBattleVisualPresentation.DescribeRenderTree("Esquire battle audit bundle(template)", template));
				Plugin.LogSource?.LogInfo(
					EsquireBattleVisualPresentation.DescribeRenderTree("Esquire battle audit custom(reparented)", instance));
			}

			if (EsquirePikemanVisuals.BattleSyncVanillaPresentation)
			{
				EsquireBattleVisualPresentation.SyncLayersOnlyFromVanilla(b, instance);
				EsquireBattleVisualPresentation.SyncSpriteRenderersDepthFirst(b, instance);
			}

			if (firstPresentationAudit && EsquirePikemanVisuals.BattleSyncVanillaPresentation)
			{
				Plugin.LogSource?.LogInfo(
					EsquireBattleVisualPresentation.DescribeRenderTree("Esquire battle audit custom(after layer/sprite sync)", instance));
			}

			// Renderer AABBs often match when both roots use a similar quad, even if HoMM3 texture padding
			// leaves the figure visually higher — then dyAlign≈0. esquirePikemanBattleBillboardExtraY always applies.
			var extraY = EsquirePikemanVisuals.BattleBillboardExtraY;
			var dyAlign = 0f;
			var haveBounds = false;
			float vanillaMinY = 0f, customMinY = 0f;
			if (EsquirePikemanVisuals.BattleAlignFeetToVanilla
			    && EsquireBattleVisualPresentation.TryEncapsulateWorldRenderBounds(b, out var vanillaBounds)
			    && EsquireBattleVisualPresentation.TryEncapsulateWorldRenderBounds(instance, out var customBounds))
			{
				haveBounds = true;
				vanillaMinY = vanillaBounds.min.y;
				customMinY = customBounds.min.y;
				dyAlign = vanillaMinY - customMinY;
			}

			var dy = dyAlign + extraY;
			if (Mathf.Abs(dy) > 1e-5f)
			{
				var it = instance.transform;
				var p = it.position;
				p.y += dy;
				it.position = p;
				if (EsquirePikemanVisuals.VerboseEsquireHooks && _loggedReplace < 4)
				{
					Plugin.LogSource?.LogInfo(
						"EsquirePikeman battle pool: battle Y shift dy="
						+ dy.ToString(System.Globalization.CultureInfo.InvariantCulture)
						+ " (boundsAlign="
						+ (haveBounds
							? dyAlign.ToString(System.Globalization.CultureInfo.InvariantCulture)
							: "n/a")
						+ " extraY="
						+ extraY.ToString(System.Globalization.CultureInfo.InvariantCulture)
						+ " vanillaMinY="
						+ (haveBounds
							? vanillaMinY.ToString(System.Globalization.CultureInfo.InvariantCulture)
							: "n/a")
						+ " customMinY="
						+ (haveBounds
							? customMinY.ToString(System.Globalization.CultureInfo.InvariantCulture)
							: "n/a")
						+ ")");
				}
			}
			else if (haveBounds
			         && EsquirePikemanVisuals.VerboseEsquireHooks
			         && Mathf.Abs(dyAlign) <= 1e-5f
			         && Mathf.Abs(extraY) <= 1e-5f
			         && _loggedBoundsNoOpHint < 4)
			{
				_loggedBoundsNoOpHint++;
				Plugin.LogSource?.LogInfo(
					"EsquirePikeman battle pool: renderer bounds min Y match ("
					+ vanillaMinY.ToString(System.Globalization.CultureInfo.InvariantCulture)
					+ "); no automatic shift. If the sprite still looks floating, lower it with esquirePikemanBattleBillboardExtraY (try a small negative value, e.g. -0.05).");
			}

			// Hide before Destroy: avoids one-frame double draw; may also help if native code still touches the old ref briefly.
			b.SetActive(false);
			if (b.scene.IsValid())
				UnityEngine.Object.Destroy(b);
			b = instance;
			c = Homm3BattlePoolMetadataFactory.Create(instance, EsquirePikemanVisuals.BattleBeiSecondArgTrue, a);
			Homm3BattleBillboardCameraFacing.TryAttach(instance, Plugin.LogSource);
			EsquireBattleAnimatorTelemetry.TryAttach(instance, Plugin.LogSource);
			EsquireBattleAudioPlayer.TryAttach(instance, Plugin.LogSource);
			EsquireBattleClipAudioDriver.TryAttach(instance, Plugin.LogSource);
			if (_loggedReplace < 32)
			{
				_loggedReplace++;
				var rc = instance.GetComponentsInChildren<Renderer>(true).Length;
				Plugin.LogSource?.LogInfo(
					"EsquirePikeman battle pool: replaced '" + a + "' with bundle prefab '" + instance.name + "', renderers=" + rc
					+ " syncVanilla=" + EsquirePikemanVisuals.BattleSyncVanillaPresentation
					+ " bei2nd=" + EsquirePikemanVisuals.BattleBeiSecondArgTrue);
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("EsquirePikeman battle pool PostfixBath failed for '" + a + "': " + ex);
		}
	}

	/// <summary>Our bundle battle prefab is root name <c>battle</c> (or engine clone) with <c>billboard/quad</c>.</summary>
	private static bool LooksLikeOurBundleBattleInstance(GameObject b)
	{
		if (b == null || !b)
			return false;
		var n = b.name ?? string.Empty;
		if (!string.Equals(n, "battle", StringComparison.Ordinal)
		    && !n.StartsWith("battle(", StringComparison.Ordinal)
		    && !n.StartsWith("battle (", StringComparison.Ordinal))
			return false;
		return b.transform.Find("billboard/quad") != null;
	}

	private static bool IsEsquireBattlePath(string path)
	{
		if (string.IsNullOrEmpty(path))
			return false;
		var p = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(path.Trim().Replace('\\', '/'));
		if (p.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			p = p.Substring(0, p.Length - ".prefab".Length);
		return string.Equals(p, EsquirePikemanVisuals.BattleResPath, StringComparison.Ordinal)
		       || (p.EndsWith("/esquire", StringComparison.Ordinal) && !p.EndsWith("/esquire_map", StringComparison.Ordinal));
	}
}
