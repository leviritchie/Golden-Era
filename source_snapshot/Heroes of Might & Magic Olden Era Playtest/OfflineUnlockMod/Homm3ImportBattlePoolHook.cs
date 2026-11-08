using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Lane B: same <c>dzk.bath</c> postfix as <see cref="EsquirePikemanBattlePoolHook"/> for paths listed in <c>homm3_import.json</c>.
/// </summary>
internal static class Homm3ImportBattlePoolHook
{
	private static bool _patched;

	internal static void ResetHarmonyGuardForHotReload()
	{
		_patched = false;
	}

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		Register(h, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafeSlice(Harmony h, ManualLogSource log)
	{
		Register(h, log, required: true);
	}

	private static void Register(Harmony h, ManualLogSource log, bool required)
	{
		if (_patched)
			return;
		if (h == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized before required battle-pool registration.");
			return;
		}
		try
		{
			if (required)
				Homm3ImportVisuals.RequireLoadedEntriesForReleaseSafeFeature(log, "battle pool");

			if (Homm3BattlePoolInterop.MetadataType == null)
			{
				HandleMissing(required, "battle-pool metadata type not found.");
				return;
			}

			var candidates = FindBattlePoolLoaders(out var t);
			if (candidates.Count == 0 || t == null)
			{
				HandleMissing(required, "string/out GameObject loader not found.");
				return;
			}

			var statics = candidates.FindAll(m => m.IsStatic);
			var toPatch = statics.Count > 0 ? statics : candidates.FindAll(m => !m.IsStatic);
			// A 3-arg loader's third out param is the drawer's renderer set (live bep -> eck.cfdq).
			// Patching it with the 2-arg prefix leaves that out param null, and eck.bcah later
			// null-derefs it (battle-result softlock). Refuse any 3-arg loader whose out type is not
			// the resolved metadata type instead of silently downgrading it.
			foreach (var m in toPatch)
			{
				var ps = m.GetParameters();
				if (ps.Length < 3)
					continue;
				var thirdOut = ps[2].ParameterType.GetElementType();
				if (!Homm3BattlePoolInterop.IsMetadataType(thirdOut))
				{
					HandleMissing(
						required,
						"3-arg loader "
						+ t.FullName + "." + m.Name
						+ " has out type '" + (thirdOut?.FullName ?? "?")
						+ "' but GameSymbols.ImportVisuals.BattlePoolMetadataTypeHints resolved '"
						+ (Homm3BattlePoolInterop.MetadataType?.FullName ?? "null")
						+ "'; refusing to patch (would leave the drawer renderer set null).");
					return;
				}
			}
			var prefix = new HarmonyMethod(typeof(Homm3ImportBattlePoolHook), nameof(PrefixBath));
			var prefixTwoArg = new HarmonyMethod(typeof(Homm3ImportBattlePoolHook), nameof(PrefixBathTwoArg));
			var postfix = new HarmonyMethod(typeof(Homm3ImportBattlePoolHook), nameof(PostfixBath));
			var postfixAny = new HarmonyMethod(typeof(Homm3ImportBattlePoolHook), nameof(PostfixBathAny));
			var patched = new List<string>();
			foreach (var m in toPatch)
			{
				if (m.GetParameters().Length >= 3)
					h.Patch(m, prefix: prefix, postfix: postfix);
				else
					h.Patch(m, prefix: prefixTwoArg, postfix: postfixAny);
				patched.Add((m.IsStatic ? "static" : "instance") + " " + m.Name);
			}

			_patched = true;
			log?.LogInfo(
				"Homm3Import: Harmony prefix/postfix on "
				+ patched.Count
				+ " "
				+ t.FullName
				+ " battle-pool loader(s) for "
				+ (required ? "required " : "")
				+ "homm3_import battle paths ("
				+ string.Join(", ", patched)
				+ ").");
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogError("Homm3Import battle pool hook failed: " + ex);
		}
	}

	private static List<MethodInfo> FindBattlePoolLoaders(out Type ownerType)
	{
		ownerType = Homm3BattlePoolInterop.ResolvePoolOwnerType();
		if (ownerType != null)
		{
			var ownerCandidates = FindBattlePoolLoadersOnType(ownerType, requireKnownName: false);
			if (ownerCandidates.Count > 0)
				return ownerCandidates;
		}

		var asm = typeof(ObjCityConfig).Assembly;
		foreach (var hint in GameSymbols.ImportVisuals.BattlePoolTypeHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = asm.GetType(hint, throwOnError: false);
			var hinted = FindBattlePoolLoadersOnType(type, requireKnownName: true);
			if (hinted.Count > 0)
			{
				ownerType = type;
				return hinted;
			}
		}

		foreach (var type in SafeGetTypes(asm))
		{
			var candidates = FindBattlePoolLoadersOnType(type, requireKnownName: true);
			if (candidates.Count > 0)
			{
				ownerType = type;
				return candidates;
			}
		}

		foreach (var type in SafeGetTypes(asm))
		{
			var candidates = FindBattlePoolLoadersOnType(type, requireKnownName: false);
			if (candidates.Count > 0)
			{
				ownerType = type;
				return candidates;
			}
		}

		return new List<MethodInfo>();
	}

	private static List<Type> SafeGetTypes(Assembly asm)
	{
		var result = new List<Type>();
		if (asm == null)
			return result;
		try
		{
			result.AddRange(asm.GetTypes());
		}
		catch (ReflectionTypeLoadException ex)
		{
			if (ex.Types == null)
				return result;
			foreach (var type in ex.Types)
			{
				if (type != null)
					result.Add(type);
			}
		}
		catch
		{
			// ignored
		}
		return result;
	}

	private static List<MethodInfo> FindBattlePoolLoadersOnType(Type type, bool requireKnownName)
	{
		var candidates = new List<MethodInfo>();
		if (type == null)
			return candidates;
		const BindingFlags bathFlags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
		foreach (var m in type.GetMethods(bathFlags))
		{
			if (m.ReturnType != typeof(bool))
				continue;
			if (requireKnownName && !Homm3BattlePoolInterop.MethodMatchesLoaderHints(m))
				continue;
			var ps = m.GetParameters();
			if ((ps.Length != 2 && ps.Length != 3)
			    || ps[0].ParameterType != typeof(string)
			    || !ps[1].ParameterType.IsByRef || !GameInteropTypes.TypesMatch(ps[1].ParameterType.GetElementType(), typeof(GameObject)))
				continue;
			if (ps.Length == 3 && !ps[2].ParameterType.IsByRef)
				continue;
			candidates.Add(m);
		}
		return candidates;
	}

	private static void HandleMissing(bool required, string message)
	{
		if (required)
			throw new InvalidOperationException("required battle-pool surface missing: " + message);
		Plugin.LogSource?.LogWarning("Homm3Import battle pool: " + message);
	}

	private static bool PrefixBath(string a, ref GameObject b, ref object c, ref bool __result)
	{
		if (!TrySynthesizeSyntheticBattlePool(a, out var instance, out var skipNative))
		{
			if (!skipNative)
				return true;
			b = null;
			__result = false;
			return false;
		}
		var metadata = Homm3BattlePoolMetadataFactory.Create(instance, EsquirePikemanVisuals.BattleBeiSecondArgTrue, a);
		if (metadata == null)
		{
			// eck.Init stores this out param in eck.cfdq and eck.bcah dereferences it unguarded;
			// report a failed load rather than hand native a drawer with no renderer set.
			Plugin.LogSource?.LogError(
				"Homm3Import battle pool: could not build renderer set '"
				+ (Homm3BattlePoolInterop.MetadataType?.FullName ?? "null")
				+ "' for synthetic path '" + a + "'; failing the load.");
			UnityEngine.Object.Destroy(instance);
			b = null;
			c = null;
			__result = false;
			return false;
		}
		b = instance;
		c = metadata;
		__result = true;
		return false;
	}

	private static bool PrefixBathTwoArg(string a, ref GameObject b, ref bool __result)
	{
		if (!TrySynthesizeSyntheticBattlePool(a, out var instance, out var skipNative))
		{
			if (!skipNative)
				return true;
			b = null;
			__result = false;
			return false;
		}
		b = instance;
		__result = true;
		return false;
	}

	/// <summary>
	/// Instantiates the HoMM3 bundle prefab for synthetic <c>homm3_import/...</c> paths.
	/// Combat Init uses both 2-arg and 3-arg pool loaders; native catalog does not contain those paths.
	/// Presentation-donor sync is cache-only — never ResManager-load during BattleLogic.Init.
	/// </summary>
	private static bool TrySynthesizeSyntheticBattlePool(string a, out GameObject instance, out bool skipNative)
	{
		instance = null;
		skipNative = false;
		if (!Homm3ImportVisuals.TryResolveHomm3BattleEntry(a, Plugin.LogSource, out var entry)
		    || !Homm3ImportVisuals.IsSyntheticHomm3ImportEntry(entry))
			return false;

		skipNative = true;
		if (!Homm3ImportVisuals.TryGetBattleTemplate(entry, Plugin.LogSource, out var template) || template == null)
		{
			Plugin.LogSource?.LogError(
				"Homm3Import battle pool: synthetic path '"
				+ a
				+ "' has no HoMM3 battle template (bundle='"
				+ (entry.BundleName ?? "?")
				+ "' prefab='"
				+ (entry.BattlePrefabAssetPath ?? "?")
				+ "').");
			return false;
		}

		try
		{
			instance = UnityEngine.Object.Instantiate(template);
			if (instance == null)
			{
				Plugin.LogSource?.LogError("Homm3Import battle pool: Instantiate returned null for '" + a + "'.");
				return false;
			}
			instance.name = template.name;

			GameObject presentation = null;
			Homm3ImportVisuals.TryGetCachedBattlePresentationTemplate(entry, Plugin.LogSource, out presentation);
			if (presentation && EsquirePikemanVisuals.BattleSyncVanillaPresentation)
			{
				EsquireBattleVisualPresentation.SyncLayersOnlyFromVanilla(presentation, instance);
				EsquireBattleVisualPresentation.SyncSpriteRenderersDepthFirst(presentation, instance);
			}
			if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
				Homm3ImportVisuals.FitSkinnedBattleMesh(presentation, instance, entry, Plugin.LogSource);

			var extraY = EsquirePikemanVisuals.BattleBillboardExtraY;
			var dyAlign = 0f;
			if (presentation
			    && EsquirePikemanVisuals.BattleAlignFeetToVanilla
			    && EsquireBattleVisualPresentation.TryEncapsulateWorldRenderBounds(presentation, out var vanillaBounds)
			    && EsquireBattleVisualPresentation.TryEncapsulateWorldRenderBounds(instance, out var customBounds))
			{
				dyAlign = vanillaBounds.min.y - customBounds.min.y;
			}

			var dy = dyAlign + extraY;
			if (Mathf.Abs(dy) > 1e-5f)
			{
				var p = instance.transform.position;
				p.y += dy;
				instance.transform.position = p;
			}

			Homm3ImportVisuals.EnsureSkinnedBattleRuntimeCompatibility(instance, presentation, entry, Plugin.LogSource);
			Homm3ImportVisuals.ApplyRuntimeBattleSpriteScale(instance);
			if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
			{
				Homm3ImportReleaseBattleVisualHook.AttachRuntimeHelpers(instance, entry);
			}
			else
			{
				Homm3BattleBillboardCameraFacing.TryAttach(instance, Plugin.LogSource);
				EsquireBattleAnimatorTelemetry.TryAttach(instance, Plugin.LogSource);
				var stemPrefix = Homm3ImportVisuals.ResolveHomm3LabAudioStemPrefix(entry);
				if (!string.IsNullOrEmpty(stemPrefix))
				{
					Homm3LabBattleAudioPlayer.TryAttach(instance, entry.BundleName, stemPrefix, Plugin.LogSource);
					Homm3LabClipAudioDriver.TryAttach(instance, Plugin.LogSource);
				}
			}

			Plugin.LogSource?.LogInfo(
				"Homm3Import battle pool: synthesized '"
				+ a
				+ "' with HoMM3 bundle prefab; localScale="
				+ FormatVector3(instance.transform.localScale)
				+ ".");
			return true;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import battle pool synthesize failed for '" + a + "': " + ex);
			instance = null;
			return false;
		}
	}

	private static void PostfixBath(string a, ref GameObject b, ref object c, bool __result)
	{
		var before = b;
		PostfixBattlePoolResult(a, ref b, __result);
		if (b != null && b != before)
		{
			c = Homm3BattlePoolMetadataFactory.Create(b, EsquirePikemanVisuals.BattleBeiSecondArgTrue, a);
			if (c == null)
				Plugin.LogSource?.LogError(
					"Homm3Import battle pool: replaced '" + a + "' but could not build renderer set '"
					+ (Homm3BattlePoolInterop.MetadataType?.FullName ?? "null")
					+ "'; eck.cfdq will be null and eck.bcah will throw.");
		}
	}

	private static void PostfixBathAny(string a, ref GameObject b, bool __result)
	{
		PostfixBattlePoolResult(a, ref b, __result);
	}

	private static void PostfixBattlePoolResult(string a, ref GameObject b, bool __result)
	{
		if (!Homm3ImportVisuals.TryResolveHomm3BattleEntry(a, Plugin.LogSource, out var entry))
			return;

		if (!__result || b == null)
		{
			if (Homm3ImportVisuals.IsSyntheticHomm3ImportEntry(entry)
			    && TrySynthesizeSyntheticBattlePool(a, out var synthesized, out _)
			    && synthesized)
			{
				b = synthesized;
				return;
			}
			Plugin.LogSource?.LogError("Homm3Import battle pool: bath failed for '" + a + "'.");
			return;
		}

		if (Homm3ImportVisuals.LooksLikeHomm3BundleBattleInstance(b))
		{
			if (Homm3ImportVisuals.TryResolveHomm3BattleEntry(a, Plugin.LogSource, out var existing))
			{
				var prefixKeep = Homm3ImportVisuals.ResolveHomm3LabAudioStemPrefix(existing);
				if (!string.IsNullOrEmpty(prefixKeep))
				{
					Homm3LabBattleAudioPlayer.TryAttach(b, existing.BundleName, prefixKeep, Plugin.LogSource);
					Homm3LabClipAudioDriver.TryAttach(b, Plugin.LogSource);
				}
			}

			if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(b))
				Homm3ImportReleaseBattleVisualHook.AttachRuntimeHelpers(b, existing);
			else
				Homm3BattleBillboardCameraFacing.TryAttach(b, Plugin.LogSource);
			return;
		}

		if (!Homm3ImportVisuals.TryGetBattleTemplate(entry, Plugin.LogSource, out var template) || template == null)
		{
			Plugin.LogSource?.LogWarning("Homm3Import battle pool: no template for '" + a + "'.");
			return;
		}

		try
		{
			var instance = UnityEngine.Object.Instantiate(template);
			if (instance == null)
				return;
			instance.name = template.name;
			var parent = b.transform.parent;
			var bt = b.transform;
			var it = instance.transform;
			it.SetParent(parent, false);
			it.localPosition = bt.localPosition;
			it.localRotation = bt.localRotation;
			if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
			{
				it.localScale = Vector3.one;
				Homm3ImportVisuals.FitSkinnedBattleMesh(b, instance, entry, Plugin.LogSource);
			}
			else
				it.localScale = bt.localScale;

			if (EsquirePikemanVisuals.BattleSyncVanillaPresentation)
			{
				EsquireBattleVisualPresentation.SyncLayersOnlyFromVanilla(b, instance);
				EsquireBattleVisualPresentation.SyncSpriteRenderersDepthFirst(b, instance);
			}

			var extraY = EsquirePikemanVisuals.BattleBillboardExtraY;
			var dyAlign = 0f;
			if (EsquirePikemanVisuals.BattleAlignFeetToVanilla
			    && EsquireBattleVisualPresentation.TryEncapsulateWorldRenderBounds(b, out var vanillaBounds)
			    && EsquireBattleVisualPresentation.TryEncapsulateWorldRenderBounds(instance, out var customBounds))
			{
				dyAlign = vanillaBounds.min.y - customBounds.min.y;
			}

			var dy = dyAlign + extraY;
			if (Mathf.Abs(dy) > 1e-5f)
			{
				var p = instance.transform.position;
				p.y += dy;
				instance.transform.position = p;
			}

			Homm3ImportVisuals.EnsureSkinnedBattleRuntimeCompatibility(instance, b, entry, Plugin.LogSource);
			Homm3ImportVisuals.ApplyRuntimeBattleSpriteScale(instance);
			b.SetActive(false);
			if (b.scene.IsValid())
				UnityEngine.Object.Destroy(b);
			b = instance;
			if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
			{
				Homm3ImportReleaseBattleVisualHook.AttachRuntimeHelpers(instance, entry);
			}
			else
			{
				Homm3BattleBillboardCameraFacing.TryAttach(instance, Plugin.LogSource);
				EsquireBattleAnimatorTelemetry.TryAttach(instance, Plugin.LogSource);
				var stemPrefix = Homm3ImportVisuals.ResolveHomm3LabAudioStemPrefix(entry);
				if (!string.IsNullOrEmpty(stemPrefix))
				{
					Homm3LabBattleAudioPlayer.TryAttach(instance, entry.BundleName, stemPrefix, Plugin.LogSource);
					Homm3LabClipAudioDriver.TryAttach(instance, Plugin.LogSource);
				}
			}

			Plugin.LogSource?.LogInfo(
				"Homm3Import battle pool: replaced '"
				+ a
				+ "' with HoMM3 bundle prefab; copied vanilla localScale="
				+ FormatVector3(instance.transform.localScale)
				+ ".");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import battle pool PostfixBath: " + ex);
		}
	}

	private static string FormatVector3(Vector3 v) =>
		"("
		+ v.x.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
		+ ", "
		+ v.y.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
		+ ", "
		+ v.z.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)
		+ ")";
}
