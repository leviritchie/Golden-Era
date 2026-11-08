using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex;
using Hex.Configs;
using Hex.Session.Battle;
using Hex.UI;
using Hex.UI.City;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Unit detail previews: current release <see cref="BhUnitWindowPreview"/> wrapper factory / <see cref="BhUnitWindowPreview.Show"/>.
/// Broad preview-wrapper factory patching is intentionally skipped here: those factories include shared
/// <see cref="BhUnitPreviews"/> cache/pool paths used by city/recruitment UI, and mutating their returned rigs can
/// make the adventure HUD's hero/town buttons disappear after leaving those screens.
/// </summary>
internal static class Homm3ImportUnitPreviewModelHook
{
	private const float PreviewScaleMultiplier = 1.25f;
	private const float MinPreviewDownscaleFactor = 0.001f;
	private const float MaxPreviewUpscaleFactor = 5f;
	private const string DetailPreviewOverlayName = "HOMM3_DETAIL_UNIT_PREVIEW_PORTRAIT";
	private const string RecruitmentPreviewOverlayName = "HOMM3_RECRUITMENT_UNIT_PREVIEW_PORTRAIT";
	private static readonly bool PreviewCalibrationEnabled = false;
	private static readonly Vector3 PreviewSlot = new(0f, -0.12f, 0f);
	private static bool _patched;
	private static int _loggedReflectedReplace;
	private static int _loggedReflectedMiss;
	private static int _loggedPreviewAlias;
	private static int _loggedNativePreviewMiss;
	private static int _loggedRecruitmentNativeSuppressed;
	private static int _loggedDetailOverlay;
	private static int _loggedDetailOverlayMiss;
	[ThreadStatic] private static List<RecruitmentAlias> _activeRecruitmentAliases;
	[ThreadStatic] private static List<PreviewAliasState> _activeShowFrames;

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		TryRegister(h, log, includeRecruitmentPreviewFactories: true);
	}

	internal static void TryRegisterDetailWindowOnly(Harmony h, ManualLogSource log)
	{
		Register(h, log, includeRecruitmentPreviewFactories: false, required: false);
	}

	internal static void RegisterRequiredDetailWindowOnly(Harmony h, ManualLogSource log)
	{
		Register(h, log, includeRecruitmentPreviewFactories: false, required: true);
	}

	private static void TryRegister(Harmony h, ManualLogSource log, bool includeRecruitmentPreviewFactories)
	{
		Register(h, log, includeRecruitmentPreviewFactories, required: false);
	}

	private static void Register(Harmony h, ManualLogSource log, bool includeRecruitmentPreviewFactories, bool required)
	{
		if (_patched)
			return;
		if (h == null)
		{
			if (required)
				throw new InvalidOperationException("Harmony was not initialized before required Homm3Import unit detail preview registration.");
			return;
		}

		try
		{
			var patched = 0;
			var missing = new List<string>();

			int Required(string label, Func<int> patch)
			{
				var count = patch();
				if (required && count == 0)
					missing.Add(label);
				return count;
			}

			patched += Required("BhUnitWindowPreview string/Transform preview factory", () => TryPatchFactoryByShape(h, log));
			patched += Required(
				"BhUnitWindowPreview.Show(UnitViewConfig)",
				() => TryPatchPreviewShow(
					h,
					AccessTools.Method(typeof(BhUnitWindowPreview), nameof(BhUnitWindowPreview.Show), new[] { typeof(UnitViewConfig) }),
					log));
			patched += Required(
				"BhHireUnitItemView model list (town hire 3D preview)",
				() => TryPatchHireItemModelList(h, log));
			if (includeRecruitmentPreviewFactories)
				patched += TryPatchReleaseRecruitmentPreviewFactories(h, log);
			Homm3ImportPreviewSyntheticMeshHook.TryRegister(h, log);

			if (missing.Count > 0)
				throw new InvalidOperationException("required Homm3Import unit detail preview surface(s) missing: " + string.Join(", ", missing));

			if (patched > 0)
				log?.LogInfo("Homm3Import: Harmony postfix on " + patched + (required ? " required" : "") + " BhUnitWindowPreview wrapper method(s).");
			else
				log?.LogWarning(
					"Homm3Import unit preview model: BhUnitWindowPreview factory/Show not patched; broad preview-wrapper factory discovery is intentionally disabled.");

			log?.LogInfo(includeRecruitmentPreviewFactories
				? "Homm3Import unit preview model: broad preview-wrapper factory hooks skipped to avoid shared BhUnitPreviews UI-cache mutation."
				: "Homm3Import unit preview model: recruitment/shared preview factories skipped; detail-window replacement only.");
			_patched = true;
		}
		catch (Exception ex)
		{
			if (required)
				throw;
			log?.LogError("Homm3Import unit preview model hook failed: " + ex);
		}
	}

	private static int TryPatch(Harmony h, System.Reflection.MethodInfo method, Type patchType, string patchName, ManualLogSource log)
	{
		if (method == null)
			return 0;
		try
		{
			h.Patch(method, postfix: new HarmonyMethod(patchType, patchName));
			log?.LogInfo("Homm3Import unit preview model target: " + method.DeclaringType?.FullName + "." + method.Name);
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import unit preview model: could not patch " + method + ": " + ex.Message);
			return 0;
		}
	}

	private static int TryPatchPreviewShow(Harmony h, System.Reflection.MethodInfo method, ManualLogSource log)
	{
		if (method == null)
			return 0;
		try
		{
			h.Patch(method,
				prefix: new HarmonyMethod(typeof(Homm3ImportUnitPreviewModelHook), nameof(PrefixBhUnitWindowPreviewShow)),
				postfix: new HarmonyMethod(typeof(Homm3ImportUnitPreviewModelHook), nameof(PostfixBhUnitWindowPreviewShow)),
				finalizer: new HarmonyMethod(typeof(Homm3ImportUnitPreviewModelHook), nameof(FinalizerBhUnitWindowPreviewShow)));
			log?.LogInfo("Homm3Import unit preview model target: " + method.DeclaringType?.FullName + "." + method.Name + " (custom-key guarded).");
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import unit preview model: could not patch " + method + ": " + ex.Message);
			return 0;
		}
	}

	private static int TryPatchReleaseRecruitmentPreviewFactories(Harmony h, ManualLogSource log)
	{
		var patched = 0;
		try
		{
			var hireFactory = FindStringOutPreviewWrapperMethod(typeof(BhHireUnitItemView), typeof(void), 2);
			patched += TryPatch(h, hireFactory, typeof(Homm3ImportUnitPreviewModelHook), nameof(PostfixBhHireUnitItemViewPreviewFactory), log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import unit preview model: BhHireUnitItemView preview factory shape scan failed: " + ex.Message);
		}

		try
		{
			var previewsFactory = AccessTools.GetDeclaredMethods(typeof(BhUnitPreviews))
				.FirstOrDefault(m =>
				{
					if (m == null || m.IsStatic || m.ReturnType != typeof(bool))
						return false;
					var ps = m.GetParameters();
					return ps.Length == 3
					       && ps[0].ParameterType == typeof(string)
					       && ps[1].ParameterType == typeof(float)
					       && IsByRefPreviewWrapper(ps[2].ParameterType);
				});
			patched += TryPatch(h, previewsFactory, typeof(Homm3ImportUnitPreviewModelHook), nameof(PostfixBhUnitPreviewsPreviewFactory), log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import unit preview model: BhUnitPreviews preview factory shape scan failed: " + ex.Message);
		}

		return patched;
	}

	private static MethodInfo FindStringOutPreviewWrapperMethod(Type type, Type returnType, int parameterCount)
	{
		return AccessTools.GetDeclaredMethods(type)
			.FirstOrDefault(m =>
			{
				if (m == null || m.IsStatic || m.ReturnType != returnType)
					return false;
				var ps = m.GetParameters();
				return ps.Length == parameterCount
				       && ps[0].ParameterType == typeof(string)
				       && IsByRefPreviewWrapper(ps[parameterCount - 1].ParameterType);
			});
	}

	private static bool IsByRefPreviewWrapper(Type type)
	{
		if (type == null || !type.IsByRef)
			return false;
		var element = type.GetElementType();
		return PreviewWrapperLooksSupported(element);
	}

	private static int TryPatchFactoryByShape(Harmony h, ManualLogSource log)
	{
		try
		{
			var method = AccessTools.GetDeclaredMethods(typeof(BhUnitWindowPreview))
				.FirstOrDefault(m =>
				{
					if (m == null || m.IsStatic || m.ReturnType == typeof(void))
						return false;
					var ps = m.GetParameters();
					return ps.Length == 2
					       && ps[0].ParameterType == typeof(string)
					       && typeof(Transform).IsAssignableFrom(ps[1].ParameterType)
					       && PreviewWrapperLooksSupported(m.ReturnType);
				});
			return TryPatchPreviewFactory(h, method, log);
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import unit preview model: factory shape scan failed: " + ex.Message);
			return 0;
		}
	}

	private static int TryPatchPreviewFactory(Harmony h, System.Reflection.MethodInfo method, ManualLogSource log)
	{
		if (method == null)
			return 0;
		try
		{
			h.Patch(method,
				prefix: new HarmonyMethod(typeof(Homm3ImportUnitPreviewModelHook), nameof(PrefixBhUnitWindowPreviewFactory)),
				postfix: new HarmonyMethod(typeof(Homm3ImportUnitPreviewModelHook), nameof(PostfixBhUnitWindowPreviewFactory)),
				finalizer: new HarmonyMethod(typeof(Homm3ImportUnitPreviewModelHook), nameof(FinalizerBhUnitWindowPreviewFactory)));
			log?.LogInfo("Homm3Import unit preview model target: " + method.DeclaringType?.FullName + "." + method.Name + " (custom-key guarded).");
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3Import unit preview model: could not patch " + method + ": " + ex.Message);
			return 0;
		}
	}

	private static bool PreviewWrapperLooksSupported(Type type)
	{
		if (type == null)
			return false;
		var fullName = type.FullName ?? type.Name ?? string.Empty;
		foreach (var typeName in GameSymbols.UnitPreview.PreviewWrapperTypeNames)
		{
			if (string.Equals(fullName, typeName, StringComparison.Ordinal) || string.Equals(type.Name, typeName, StringComparison.Ordinal))
				return true;
		}
		return HasReadableMember(type, "Model") && HasReadableMember(type, "Rotatable") && HasReadableMember(type, "Background");
	}

	private static bool HasReadableMember(Type type, string name)
	{
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		return type.GetProperty(name, flags) != null || type.GetField(name, flags) != null;
	}

	private static void PostfixBhUnitWindowPreviewBebc([HarmonyArgument(0)] string sid, ref object __result)
	{
		TryApply(__result, sid, "BhUnitWindowPreview.bebc");
	}

	private static void PrefixBhUnitWindowPreviewFactory([HarmonyArgument(0)] ref string sid, ref PreviewAliasState __state, MethodBase __originalMethod)
	{
		__state = null;
		var customKey = ExtractStrongholdPreviewSid(sid);
		if (string.IsNullOrWhiteSpace(customKey))
			return;

		__state = new PreviewAliasState { CustomKey = customKey };
		// Native Show passes [UnitViewConfig+0x10] (the view row id) straight into this factory.
		// That is the only reliable read of the custom key on live Golden Era: the managed
		// DeobfInteropCompat.GetConfigElementId(UnitViewConfig) returns null there (battle diag
		// logs viewConfigId='?'), so hand it to the enclosing Show frame before aliasing.
		RecordShowFactoryCustomKey(customKey);
		// Show.bewc is called with UnitViewConfig.id (Il2Cpp +0x10), not mesh (+0x48).
		// Native rum/htv then null-derefs on custom h3_* catalog ids. Rewrite to the dungeon donor id.
		// Faction units alias through the registry donor; owned units outside any faction (neutrals) name a
		// preview-only donor on their homm3_import row, which never touches HUD/law/icon aliasing.
		if ((!StrongholdUnitSidMapping.TryGetDonorSid(customKey, out var donorSid) || string.IsNullOrWhiteSpace(donorSid))
		    && !Homm3ImportVisuals.TryGetPreviewDonorSidForUnitSid(customKey, Plugin.LogSource, out donorSid))
		{
			Plugin.LogSource?.LogError(
				"Homm3Import unit preview model: Show.bewc has no registry donor or homm3_import previewDonorSid for '"
				+ customKey
				+ "'.");
			return;
		}

		var catalogId = DonorSidToPreviewCatalogId(donorSid);
		if (string.IsNullOrWhiteSpace(catalogId) || string.Equals(sid, catalogId, StringComparison.Ordinal))
			return;
		LogPreviewAlias(customKey, sid, catalogId, FormatMethod(__originalMethod) + ".id");
		PushRecruitmentDonorAlias(catalogId, customKey);
		__state.DonorCatalogId = catalogId;
		sid = catalogId;
	}

	private static void PostfixBhUnitWindowPreviewFactory([HarmonyArgument(0)] string sid, object __result, PreviewAliasState __state)
	{
		// The detail window now uses a UI overlay applied from Show(), where the owning RectTransform is available.
		// Replacing the factory model here re-enters the fragile 3D preview camera/pose path.
	}

	private static Exception FinalizerBhUnitWindowPreviewFactory(
		Exception __exception,
		[HarmonyArgument(1)] Transform parent,
		ref object __result,
		PreviewAliasState __state,
		MethodBase __originalMethod)
	{
		if (__state != null && !string.IsNullOrWhiteSpace(__state.DonorCatalogId))
			PopRecruitmentDonorAlias(__state.DonorCatalogId, __state.CustomKey);
		if (__exception == null)
			return null;
		var key = __state?.CustomKey;
		if (string.IsNullOrWhiteSpace(key))
			return __exception;
		return SuppressKnownPreviewMiss(__exception, key, FormatMethod(__originalMethod) + ".finalizer");
	}

	private static void PostfixBhHireUnitItemViewPreviewFactory(object __instance, [HarmonyArgument(0)] string sid, object[] __args)
	{
		var preview = __args != null && __args.Length > 1 ? __args[1] : null;
		var key = ResolveActiveRecruitmentPreviewKey(sid);
		if (!ShouldKeepNativeDetailPreviewMesh(key))
		{
			var remembered = Homm3CustomUiIconHook.TryGetRememberedRecruitmentItemSid(__instance);
			if (!string.IsNullOrWhiteSpace(remembered))
				key = remembered;
		}
		TryApplyReflectedPreview(preview, key, "BhHireUnitItemView.previewFactory");
	}

	/// <summary>
	/// Town hire screen (the large 3D recruit panel). <c>BhHireUnitItemView.tvn</c> fills its own wrapper list from
	/// the <see cref="BhUnitPreviews"/> per-sid pool; for a custom sid the native view row carries the donor's mesh,
	/// so every wrapper it returns shows the donor. Patch only this consumer (never <c>htv</c> or the shared prefab):
	/// the wrappers are keyed by our own custom sid, so a swapped wrapper that returns to the pool is only ever
	/// dequeued again for that same custom sid.
	/// </summary>
	private static int TryPatchHireItemModelList(Harmony h, ManualLogSource log)
	{
		var symbol = GameSymbols.UnitPreview.HireItemModelList;
		MethodInfo target = null;
		foreach (var hint in symbol.NameHints)
		{
			target = AccessTools.GetDeclaredMethods(typeof(BhHireUnitItemView))
				.FirstOrDefault(m => m != null
				                     && !m.IsStatic
				                     && m.ReturnType == typeof(void)
				                     && string.Equals(m.Name, hint, StringComparison.Ordinal)
				                     && m.GetParameters().Length == 1
				                     && (m.GetParameters()[0].ParameterType.FullName ?? string.Empty).IndexOf("IReadOnlyList", StringComparison.Ordinal) >= 0);
			if (target != null)
				break;
		}

		if (target == null)
		{
			log?.LogError("Homm3Import unit preview model: " + symbol.Id + " not found on BhHireUnitItemView (hints: "
			              + string.Join(", ", symbol.NameHints) + "); the town hire screen will keep showing donor models.");
			return 0;
		}

		return TryPatch(h, target, typeof(Homm3ImportUnitPreviewModelHook), nameof(PostfixBhHireUnitItemViewModelList), log);
	}

	private static void PostfixBhHireUnitItemViewModelList(object __instance, [HarmonyArgument(0)] object sids)
	{
		const string source = "BhHireUnitItemView.modelList";
		var ownedRequested = new List<string>();
		foreach (var sid in ReadRequestedHireSids(sids))
		{
			if (ShouldKeepNativeDetailPreviewMesh(sid))
				ownedRequested.Add(sid);
		}

		var swapped = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
		try
		{
			object list = null;
			foreach (var field in GameSymbols.UnitPreview.HireItemModelListFields)
			{
				list = GetMemberValue(__instance, field);
				if (list != null)
					break;
			}

			if (list == null)
			{
				foreach (var sid in ownedRequested)
					LogOwnedSkinnedPreviewRefused(sid, source, "hire item wrapper list unresolved (fields: "
					                                           + string.Join(", ", GameSymbols.UnitPreview.HireItemModelListFields) + ")");
				return;
			}

			foreach (var wrapper in EnumerateIl2CppList(list))
			{
				if (wrapper == null)
					continue;
				var key = GetMemberValue(wrapper, "Sid") as string;
				if (!ShouldKeepNativeDetailPreviewMesh(key))
					continue;
				if (ApplyOwnedSkinnedHireModel(wrapper, key, source))
					swapped.Add(key);
			}
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import unit preview model " + source + " failed: " + ex);
		}

		foreach (var sid in ownedRequested)
		{
			if (!swapped.Contains(sid))
				LogOwnedSkinnedPreviewRefused(sid, source, "no hire preview wrapper carried this sid after the native list build");
		}
	}

	/// <summary>
	/// Swap one hire wrapper's donor model for the owned skinned battle prefab, synchronously, so the native
	/// <c>UpdateView</c> that follows animates and frames our model. A pooled wrapper that already carries our
	/// model (dequeued again for the same custom sid) is only re-layered.
	/// </summary>
	private static bool ApplyOwnedSkinnedHireModel(object wrapper, string key, string source)
	{
		if (!TryIsSharedPreviewPrefabByNativePointer(wrapper, out var isSharedPrefab, out var sharedCheckFailure))
		{
			LogOwnedSkinnedPreviewRefused(key, source, sharedCheckFailure);
			return false;
		}

		if (isSharedPrefab)
		{
			LogOwnedSkinnedPreviewRefused(key, source, "wrapper is the BhUnitPreviews shared prefab; it is never mutated");
			return false;
		}

		var model = GetPreviewModel(wrapper);
		if (model && Homm3ImportVisuals.LooksLikeHomm3BundleBattleInstance(model))
		{
			ApplyLayerRecursive(model.transform, ResolvePreviewUnityLayer(wrapper, model));
			model.SetActive(true);
			LogHireReuse(key, model);
			return true;
		}

		if (!model)
		{
			LogOwnedSkinnedPreviewRefused(key, source, "hire preview wrapper has no native Model to take the pose from");
			return false;
		}

		if (!TryGetBattleTemplate(key, out var template) || !template)
		{
			LogOwnedSkinnedPreviewRefused(key, source, "battle prefab template did not load from the installed bundle");
			return false;
		}

		ExecuteReplaceReflectedPreview(wrapper, key, source, template);
		var after = GetPreviewModel(wrapper);
		if (after && Homm3ImportVisuals.LooksLikeHomm3BundleBattleInstance(after))
			return true;
		LogOwnedSkinnedPreviewRefused(key, source, "replacement did not install the owned model on the hire wrapper");
		return false;
	}

	private static int _loggedHireReuse;

	private static void LogHireReuse(string key, GameObject model)
	{
		if (_loggedHireReuse >= 16)
			return;
		_loggedHireReuse++;
		Plugin.LogSource?.LogInfo("Homm3Import unit preview model: hire wrapper for '" + key
		                          + "' re-dequeued with its owned model '" + model.name + "' (re-layered only).");
	}

	/// <summary>
	/// Fail closed: when the live <see cref="BhUnitPreviews"/> singleton or its prefab cannot be read, the caller
	/// refuses the swap (loudly) instead of guessing the wrapper is not the shared template.
	/// All members are read by reflection over the live interop through <see cref="GameSymbols.UnitPreview"/>.
	/// </summary>
	private static bool TryIsSharedPreviewPrefabByNativePointer(object wrapper, out bool isSharedPrefab, out string failure)
	{
		isSharedPrefab = false;
		failure = null;
		var host = GetStaticMemberValue(typeof(BhUnitPreviews), GameSymbols.UnitPreview.SharedPreviewsInstanceMembers);
		if (host == null)
		{
			failure = "BhUnitPreviews singleton unresolved on live interop (members: "
			          + string.Join(", ", GameSymbols.UnitPreview.SharedPreviewsInstanceMembers) + ")";
			return false;
		}

		foreach (var field in GameSymbols.UnitPreview.SharedPreviewPrefabFields)
		{
			var prefab = GetMemberValue(host, field);
			if (prefab == null)
				continue;
			var a = Homm3DirectStateIdentity.ResolveKeyOrZero(prefab);
			var b = Homm3DirectStateIdentity.ResolveKeyOrZero(wrapper);
			isSharedPrefab = a != 0 && a == b;
			return true;
		}

		failure = "BhUnitPreviews shared prefab unresolved on live interop (fields: "
		          + string.Join(", ", GameSymbols.UnitPreview.SharedPreviewPrefabFields) + ")";
		return false;
	}

	private static object GetStaticMemberValue(Type type, IEnumerable<string> names)
	{
		const BindingFlags flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names)
		{
			try
			{
				var prop = type.GetProperty(name, flags);
				if (prop != null)
				{
					var value = prop.GetValue(null);
					if (value != null)
						return value;
				}

				var field = type.GetField(name, flags);
				if (field != null)
				{
					var value = field.GetValue(null);
					if (value != null)
						return value;
				}
			}
			catch (Exception ex)
			{
				Plugin.LogSource?.LogWarning("Homm3Import unit preview model: static " + type.Name + "." + name + " read failed: "
				                             + (ex.InnerException?.Message ?? ex.Message));
			}
		}

		return null;
	}

	private static int _loggedHireSidsUnreadable;

	/// <summary>
	/// The native arg is an IL2CPP <c>IReadOnlyList&lt;string&gt;</c> interface proxy; read it through its concrete
	/// List or array. Used only to cross-check that every requested owned sid got swapped.
	/// </summary>
	private static List<string> ReadRequestedHireSids(object sids)
	{
		var result = new List<string>();
		try
		{
			if (sids is Il2CppObjectBase native)
			{
				var list = native.TryCast<Il2CppSystem.Collections.Generic.List<string>>();
				if (list != null)
				{
					for (var i = 0; i < list.Count; i++)
						result.Add(list[i]);
					return result;
				}

				var array = native.TryCast<Il2CppInterop.Runtime.InteropTypes.Arrays.Il2CppStringArray>();
				if (array != null)
				{
					for (var i = 0; i < array.Length; i++)
						result.Add(array[i]);
					return result;
				}
			}
			else if (sids is System.Collections.IEnumerable managed)
			{
				foreach (var item in managed)
				{
					if (item is string s)
						result.Add(s);
				}

				return result;
			}
		}
		catch (Exception ex)
		{
			if (_loggedHireSidsUnreadable++ < 4)
				Plugin.LogSource?.LogWarning("Homm3Import unit preview model: hire sid list unreadable: " + ex.Message);
			return result;
		}

		if (sids != null && _loggedHireSidsUnreadable++ < 4)
			Plugin.LogSource?.LogWarning("Homm3Import unit preview model: hire sid list type " + sids.GetType().FullName
			                             + " is neither List<string> nor string[]; requested-sid cross-check skipped.");
		return result;
	}

	private static IEnumerable<object> EnumerateIl2CppList(object list)
	{
		if (list == null)
			yield break;
		if (list is string single)
		{
			yield return single;
			yield break;
		}

		if (list is System.Collections.IEnumerable managed)
		{
			foreach (var item in managed)
				yield return item;
			yield break;
		}

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = list.GetType();
		var countProp = type.GetProperty("Count", flags);
		var getItem = type.GetMethod("get_Item", flags, null, new[] { typeof(int) }, null);
		if (countProp == null || getItem == null)
		{
			Plugin.LogSource?.LogError("Homm3Import unit preview model: cannot enumerate " + type.FullName
			                           + " (no Count/get_Item); hire preview swap skipped.");
			yield break;
		}

		var count = Convert.ToInt32(countProp.GetValue(list));
		for (var i = 0; i < count; i++)
			yield return getItem.Invoke(list, new object[] { i });
	}

	private static void PostfixBhUnitPreviewsPreviewFactory([HarmonyArgument(0)] string sid, object[] __args)
	{
		var preview = __args != null && __args.Length > 2 ? __args[2] : null;
		var key = ResolveActiveRecruitmentPreviewKey(sid);
		TryApplyReflectedPreview(preview, key, "BhUnitPreviews.previewFactory");
	}

	private static void PrefixBhUnitWindowPreviewShow([HarmonyArgument(0)] UnitViewConfig viewConfig, ref PreviewAliasState __state, MethodBase __originalMethod)
	{
		// Always open a Show frame: the nested native factory call records the custom key on it,
		// and the frame stays open until the finalizer (the last consumer) has run.
		__state = new PreviewAliasState();
		PushShowFrame(__state);
		if (viewConfig == null)
			return;

		var changed = false;
		string customKey = null;
		var oldId = DeobfInteropCompat.GetConfigElementId(viewConfig);
		var oldMesh = viewConfig.mesh;
		var oldMapMesh = DeobfInteropCompat.GetUnitViewConfigMapMesh(viewConfig);

		if (!string.IsNullOrEmpty(oldId) && oldId.StartsWith("h3_", StringComparison.Ordinal))
			customKey = oldId;

		if (TryResolvePreviewMeshAlias(oldMesh, out var meshCustomKey, out var donorMesh)
		    && !ShouldKeepNativeDetailPreviewMesh(meshCustomKey))
		{
			customKey = meshCustomKey;
			viewConfig.mesh = donorMesh;
			changed = true;
			LogPreviewAlias(meshCustomKey, oldMesh, donorMesh, FormatMethod(__originalMethod) + ".mesh");
		}

		if (TryResolvePreviewMeshAlias(oldMapMesh, out var mapCustomKey, out var donorMapMesh)
		    && !ShouldKeepNativeDetailPreviewMesh(mapCustomKey))
		{
			customKey ??= mapCustomKey;
			if (EndsWithMapSuffix(oldMapMesh) && !EndsWithMapSuffix(donorMapMesh))
				donorMapMesh += "_map";
			DeobfInteropCompat.SetUnitViewConfigMapMesh(viewConfig, donorMapMesh);
			changed = true;
			LogPreviewAlias(mapCustomKey, oldMapMesh, donorMapMesh, FormatMethod(__originalMethod) + ".mapMesh");
		}

		__state.CustomKey = customKey;
		if (!changed)
			return;

		__state.ViewConfig = viewConfig;
		__state.OldId = oldId;
		__state.OldMesh = oldMesh;
		__state.OldMapMesh = oldMapMesh;
	}

	private static void PostfixBhUnitWindowPreviewShow(BhUnitWindowPreview __instance, [HarmonyArgument(0)] UnitViewConfig viewConfig, PreviewAliasState __state)
	{
		if (__instance == null)
			return;
		RestorePreviewAlias(__state);
		// Detail preview opens behind custom town art unless UNIT WINDOW SESSION is raised now.
		ModActions.EnsureUnitDetailPreviewWindowAboveTownArt();
		var key = ResolveShowPreviewKey(__state, viewConfig);
		var preview = TryGetPreviewWrapper(__instance);
		if (ShouldKeepNativeDetailPreviewMesh(key))
		{
			// Owned skinned unit: the native factory built the donor rig (Rotatable/Model/Background
			// + render-texture camera); swap its Model for the same bundle prefab battle uses.
			RevealNativeDetailPreview(__instance, preview, key, "BhUnitWindowPreview.Show");
			TryApplyReflectedPreview(preview, key, "BhUnitWindowPreview.Show");
			return;
		}
		if (TryApplyDetailPreviewOverlay(__instance, preview, key, "BhUnitWindowPreview.Show"))
			return;
		if (IsCustomDetailPreviewKey(key))
		{
			LogDetailOverlayMiss(key, "BhUnitWindowPreview.Show", "detail-overlay-missed-no-model-replacement");
			return;
		}
		ClearDetailPreviewOverlayForNative(__instance, preview, key, "BhUnitWindowPreview.Show");
		TryApplyReflectedPreview(preview, key, "BhUnitWindowPreview.Show");
	}

	private static Exception FinalizerBhUnitWindowPreviewShow(
		BhUnitWindowPreview __instance,
		[HarmonyArgument(0)] UnitViewConfig viewConfig,
		Exception __exception,
		PreviewAliasState __state,
		MethodBase __originalMethod)
	{
		RestorePreviewAlias(__state);
		PopShowFrame(__state);
		if (__exception == null)
			return null;
		var key = ResolveShowPreviewKey(__state, viewConfig);
		key = ExtractStrongholdPreviewSid(key);
		if (string.IsNullOrWhiteSpace(key) || __instance == null)
			return __exception;
		var preview = TryGetPreviewWrapper(__instance);
		if (ShouldKeepNativeDetailPreviewMesh(key))
		{
			RevealNativeDetailPreview(__instance, preview, key, FormatMethod(__originalMethod) + ".finalizer");
			TryApplyReflectedPreview(preview, key, FormatMethod(__originalMethod) + ".finalizer");
		}
		else
			TryApplyDetailPreviewOverlay(__instance, preview, key, FormatMethod(__originalMethod) + ".finalizer");
		return SuppressKnownPreviewMiss(__exception, key, FormatMethod(__originalMethod) + ".finalizer");
	}

	private static bool IsCustomDetailPreviewKey(string key)
	{
		key = ExtractStrongholdPreviewSid(key);
		return !string.IsNullOrWhiteSpace(key);
	}

	private static bool ShouldKeepNativeDetailPreviewMesh(string key)
	{
		key = ExtractStrongholdPreviewSid(key);
		if (string.IsNullOrWhiteSpace(key))
			return false;
		if (Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(key, Plugin.LogSource, out var bySid)
		    && Homm3ImportVisuals.IsOwnedSkinnedBattleEntry(bySid))
			return true;
		if (Homm3ImportVisuals.TryResolveHomm3BattleEntry(key, Plugin.LogSource, out var byPath)
		    && Homm3ImportVisuals.IsOwnedSkinnedBattleEntry(byPath))
			return true;
		return false;
	}

	private static void RevealNativeDetailPreview(BhUnitWindowPreview instance, object preview, string key, string source)
	{
		if (instance == null)
			return;
		try
		{
			var root = ResolveDetailPreviewOverlayRoot(instance);
			var cleared = 0;
			if (root)
				cleared = ClearStaleDetailOverlays(instance, root);
			var restored = RestoreDetailPreviewNativeModel(preview);
			if (_loggedDetailOverlay >= 24)
				return;
			_loggedDetailOverlay++;
			Plugin.LogSource?.LogInfo(
				"Homm3Import unit preview: revealed native rig for owned skinned swap key='"
				+ (key ?? "?")
				+ "' source="
				+ (source ?? "?")
				+ " clearedOverlays="
				+ cleared
				+ " restoredRenderers="
				+ restored
				+ ".");
		}
		catch (Exception ex)
		{
			LogDetailOverlayMiss(key, source, "keep-native-mesh-exception:" + ex.Message);
		}
	}

	private static void ClearDetailPreviewOverlayForNative(BhUnitWindowPreview instance, object preview, string key, string source)
	{
		if (instance == null || IsCustomDetailPreviewKey(key))
			return;
		try
		{
			var root = ResolveDetailPreviewOverlayRoot(instance);
			if (!root)
				return;
			var cleared = ClearStaleDetailOverlays(instance, root);
			var restored = RestoreDetailPreviewNativeModel(preview);
			if (cleared <= 0 && restored <= 0)
				return;
			if (_loggedDetailOverlay >= 24)
				return;
			_loggedDetailOverlay++;
			Plugin.LogSource?.LogInfo(
				"Homm3Import unit preview overlay: cleared " + cleared
				+ " stale custom overlay(s), restored " + restored
				+ " native renderer(s) for native key='"
				+ (key ?? "?") + "' source=" + (source ?? "?") + ".");
		}
		catch (Exception ex)
		{
			LogDetailOverlayMiss(key, source, "native-overlay-clear-exception:" + ex.Message);
		}
	}

	private static void RestorePreviewAlias(PreviewAliasState state)
	{
		if (state == null || state.Restored || state.ViewConfig == null)
			return;
		state.Restored = true;
		DeobfInteropCompat.TrySetConfigElementId(state.ViewConfig, state.OldId);
		state.ViewConfig.mesh = state.OldMesh;
		DeobfInteropCompat.SetUnitViewConfigMapMesh(state.ViewConfig, state.OldMapMesh);
	}

	/// <summary>
	/// Custom key for a detail preview Show. The native factory's own id argument (recorded on the
	/// Show frame) wins; the managed view-config read is kept for native units, whose key is the mesh path.
	/// </summary>
	private static string ResolveShowPreviewKey(PreviewAliasState state, UnitViewConfig viewConfig)
	{
		if (!string.IsNullOrWhiteSpace(state?.FactoryCustomKey))
			return state.FactoryCustomKey;
		if (!string.IsNullOrWhiteSpace(state?.CustomKey))
			return state.CustomKey;
		return PreviewKeyFromViewConfig(viewConfig);
	}

	private static void PushShowFrame(PreviewAliasState frame)
	{
		if (frame == null)
			return;
		_activeShowFrames ??= new List<PreviewAliasState>();
		_activeShowFrames.Add(frame);
	}

	private static void PopShowFrame(PreviewAliasState frame)
	{
		var frames = _activeShowFrames;
		if (frame == null || frames == null)
			return;
		for (var i = frames.Count - 1; i >= 0; i--)
		{
			if (!ReferenceEquals(frames[i], frame))
				continue;
			frames.RemoveAt(i);
			return;
		}
	}

	private static void RecordShowFactoryCustomKey(string customKey)
	{
		var frames = _activeShowFrames;
		if (frames == null || frames.Count == 0 || string.IsNullOrWhiteSpace(customKey))
			return;
		var frame = frames[frames.Count - 1];
		if (string.IsNullOrWhiteSpace(frame.FactoryCustomKey))
			frame.FactoryCustomKey = customKey;
	}

	private sealed class PreviewAliasState
	{
		internal UnitViewConfig ViewConfig;
		internal string CustomKey;
		internal string FactoryCustomKey;
		internal string DonorCatalogId;
		internal string OldId;
		internal string OldMesh;
		internal string OldMapMesh;
		internal bool Restored;
	}

	private static object TryGetPreviewWrapper(BhUnitWindowPreview instance)
	{
		if (instance == null)
			return null;

		var ownerType = typeof(BhUnitWindowPreview);
		var pin = GameSymbols.UnitPreview.WindowPreviewWrapperField;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		var properties = ownerType.GetProperties(flags)
			.Where(property => string.Equals(property.Name, pin.FieldName, StringComparison.Ordinal))
			.ToArray();
		var fields = ownerType.GetFields(flags)
			.Where(field => string.Equals(field.Name, pin.FieldName, StringComparison.Ordinal))
			.ToArray();
		var wrapperType = properties.Length == 1 && fields.Length == 0
			? properties[0].PropertyType
			: fields.Length == 1 && properties.Length == 0
				? fields[0].FieldType
				: null;
		if (!HasNativePreviewWrapperSurface(wrapperType))
		{
			LogReflectedMiss(
				"BhUnitWindowPreview native wrapper pin refused: owner metadata does not expose the expected Model/Rotatable/Background surface.");
			return null;
		}

		if (!DeobfInteropCompat.TryReadNativeObjectFieldDeclared(
				instance,
				ownerType,
				wrapperType,
				pin,
				out var wrapper,
				out var failure))
		{
			LogReflectedMiss("BhUnitWindowPreview native wrapper read refused: " + failure + ".");
			return null;
		}

		return wrapper;
	}

	private static bool HasNativePreviewWrapperSurface(Type type)
	{
		return PreviewWrapperLooksSupported(type)
		       && HasReadableMember(type, "Model")
		       && HasReadableMember(type, "Rotatable")
		       && HasReadableMember(type, "Background");
	}

	private static bool TryApplyDetailPreviewOverlay(BhUnitWindowPreview instance, object preview, string key, string source)
	{
		key = ExtractStrongholdPreviewSid(key);
		if (instance == null || string.IsNullOrWhiteSpace(key))
			return false;
		if (ShouldKeepNativeDetailPreviewMesh(key))
		{
			RevealNativeDetailPreview(instance, preview, key, source);
			return false;
		}
		if (!Homm3CustomUiIconHook.TryResolveSprite(key, out var fallback) || !fallback)
		{
			LogDetailOverlayMiss(key, source, "no-static-sprite");
			return false;
		}

		try
		{
			var root = ResolveDetailPreviewOverlayRoot(instance);
			if (!root)
			{
				LogDetailOverlayMiss(key, source, "no-rect-root");
				return false;
			}

			ClearStaleDetailOverlays(instance, root);
			var image = GetOrCreateDetailOverlayImage(instance, root, out var rect);
			if (!image || !rect)
			{
				LogDetailOverlayMiss(key, source, "no-overlay-image");
				return false;
			}

			var placement = ResolveDetailOverlayPlacement(root, preview);
			rect.anchorMin = new Vector2(0.5f, 0.5f);
			rect.anchorMax = new Vector2(0.5f, 0.5f);
			rect.pivot = new Vector2(0.5f, 0.5f);
			rect.anchoredPosition = placement.Position;
			rect.sizeDelta = placement.Size;
			rect.localRotation = Quaternion.identity;
			rect.localScale = Vector3.one;
			rect.SetAsLastSibling();

			image.raycastTarget = false;
			image.preserveAspect = true;
			image.type = Image.Type.Simple;
			image.color = Color.white;
			image.enabled = true;
			image.gameObject.SetActive(true);
			var showcaseApplied = Homm3HireUnitPortraitAnimator.TryApplyShowcase(image, key, fallback, scaleRife: false);
			var useStaticPortrait = UseStaticPreviewPortraits();
			var idleApplied = !showcaseApplied && !useStaticPortrait && Homm3HireUnitPortraitAnimator.TryApplyIdle(image, key, fallback);
			if (!showcaseApplied && useStaticPortrait)
			{
				Homm3HireUnitPortraitAnimator.Stop(image);
				image.sprite = fallback;
			}
			if (!showcaseApplied && !useStaticPortrait && !idleApplied)
				rect.sizeDelta = ResolveDetailStaticOverlaySize(root);
			HideDetailPreviewNativeModel(preview);
			SuppressActiveLookUnitNativePreviewModels(source, key);
			LogDetailOverlay(key, source, rect, image);
			return true;
		}
		catch (Exception ex)
		{
			LogDetailOverlayMiss(key, source, "exception:" + ex.Message);
			return false;
		}
	}

	private readonly struct DetailOverlayPlacement
	{
		internal DetailOverlayPlacement(Vector2 position, Vector2 size)
		{
			Position = position;
			Size = size;
		}

		internal Vector2 Position { get; }
		internal Vector2 Size { get; }
	}

	private static RectTransform ResolveDetailPreviewOverlayRoot(BhUnitWindowPreview instance)
	{
		if (!instance)
			return null;
		var root = instance.transform as RectTransform;
		if (root)
			return root;
		var parent = instance.GetComponentInParent<RectTransform>();
		return parent ? parent : null;
	}

	private static Image GetOrCreateDetailOverlayImage(Component component, RectTransform root, out RectTransform rect)
	{
		rect = null;
		if (!component || !root)
			return null;

		var overlays = component.GetComponentsInChildren<RectTransform>(true);
		for (var i = 0; i < overlays.Length; i++)
		{
			var overlay = overlays[i];
			if (!overlay || !string.Equals(overlay.name, DetailPreviewOverlayName, StringComparison.Ordinal))
				continue;

			if (!rect)
			{
				rect = overlay;
				continue;
			}

			overlay.gameObject.SetActive(false);
			UnityEngine.Object.Destroy(overlay.gameObject);
		}

		Image image;
		if (rect)
		{
			if (rect.parent != root)
				rect.SetParent(root, false);
			rect.gameObject.SetActive(true);
			image = rect.GetComponent<Image>() ?? rect.gameObject.AddComponent<Image>();
		}
		else
		{
			var go = new GameObject(DetailPreviewOverlayName);
			go.transform.SetParent(root, false);
			rect = go.AddComponent<RectTransform>();
			image = go.AddComponent<Image>();
		}
		return image;
	}

	private static Image GetOrCreatePreviewOverlayImage(RectTransform root, string overlayName, out RectTransform rect)
	{
		rect = null;
		if (!root || string.IsNullOrWhiteSpace(overlayName))
			return null;

		var overlays = root.GetComponentsInChildren<RectTransform>(true);
		for (var i = 0; i < overlays.Length; i++)
		{
			var overlay = overlays[i];
			if (!overlay || !string.Equals(overlay.name, overlayName, StringComparison.Ordinal))
				continue;

			if (!rect)
			{
				rect = overlay;
				continue;
			}

			overlay.gameObject.SetActive(false);
			UnityEngine.Object.Destroy(overlay.gameObject);
		}

		Image image;
		if (rect)
		{
			if (rect.parent != root)
				rect.SetParent(root, false);
			rect.gameObject.SetActive(true);
			image = rect.GetComponent<Image>() ?? rect.gameObject.AddComponent<Image>();
		}
		else
		{
			var go = new GameObject(overlayName);
			go.transform.SetParent(root, false);
			rect = go.AddComponent<RectTransform>();
			image = go.AddComponent<Image>();
		}
		return image;
	}

	private static int ClearStaleDetailOverlays(Component component, RectTransform root)
	{
		var canvas = component ? component.GetComponentInParent<Canvas>() : null;
		var searchRoot = canvas ? canvas.transform : root.root;
		if (!searchRoot)
			searchRoot = root;
		if (!searchRoot)
			return 0;
		var cleared = 0;
		var overlays = searchRoot.GetComponentsInChildren<RectTransform>(true);
		for (var i = 0; i < overlays.Length; i++)
		{
			var overlay = overlays[i];
			if (!overlay || !string.Equals(overlay.name, DetailPreviewOverlayName, StringComparison.Ordinal))
				continue;
			overlay.gameObject.SetActive(false);
			UnityEngine.Object.Destroy(overlay.gameObject);
			cleared++;
		}
		return cleared;
	}

	private static DetailOverlayPlacement ResolveDetailOverlayPlacement(RectTransform root, object preview)
	{
		return new DetailOverlayPlacement(ResolveDetailOverlayFallbackOffset(root), ResolveDetailOverlayFallbackSize(root));
	}

	private static Vector2 ResolveDetailOverlayFallbackSize(RectTransform root)
	{
		var rect = root.rect;
		var w = rect.width;
		var h = rect.height;
		if (w > 8f && h > 8f)
		{
			var size = Mathf.Clamp(Mathf.Min(w, h) * 1.35f, 360f, 1400f);
			return new Vector2(size, size);
		}
		return new Vector2(900f, 900f);
	}

	private static Vector2 ResolveDetailStaticOverlaySize(RectTransform root)
	{
		if (!root)
			return new Vector2(360f, 360f);
		var rect = root.rect;
		if (rect.width > 8f && rect.height > 8f)
		{
			var size = Mathf.Clamp(Mathf.Min(rect.width, rect.height) * 0.35f, 220f, 360f);
			return new Vector2(size, size);
		}
		return new Vector2(360f, 360f);
	}

	private static Vector2 ResolveDetailOverlayFallbackOffset(RectTransform root)
	{
		var rect = root ? root.rect : default;
		if (rect.width > 8f || rect.height > 8f)
			return new Vector2(rect.width * 0.15f, rect.height * 0.08f);
		return Vector2.zero;
	}

	private static void HideDetailPreviewNativeModel(object preview)
	{
		var hidden = 0;
		hidden += HideNativePreviewRenderers(GetPreviewModel(preview));
		hidden += HideNativePreviewRenderers(GetPreviewRotatable(preview));
		if (preview is Component component)
			hidden += HideNativePreviewRenderers(component.gameObject);

		var model = GetPreviewModel(preview);
		if (model)
			model.SetActive(false);
		if (hidden == 0 && model)
			model.SetActive(false);
	}

	private static int RestoreDetailPreviewNativeModel(object preview)
	{
		var restored = 0;
		restored += RestoreNativePreviewRenderers(GetPreviewModel(preview));
		restored += RestoreNativePreviewRenderers(GetPreviewRotatable(preview));
		if (preview is Component component)
			restored += RestoreNativePreviewRenderers(component.gameObject);

		var model = GetPreviewModel(preview);
		if (model && !model.activeSelf)
		{
			model.SetActive(true);
			restored++;
		}
		return restored;
	}

	private static int HideNativePreviewRenderers(GameObject root)
	{
		if (!root)
			return 0;
		var hidden = 0;
		var renderers = root.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var renderer = renderers[i];
			if (!renderer || IsCustomPreviewRenderer(renderer))
				continue;
			renderer.enabled = false;
			hidden++;
		}
		return hidden;
	}

	private static bool IsCustomPreviewRenderer(Renderer renderer)
	{
		if (!renderer)
			return false;
		for (var t = renderer.transform; t; t = t.parent)
		{
			var name = t.gameObject ? t.gameObject.name : string.Empty;
			if (string.Equals(name, DetailPreviewOverlayName, StringComparison.Ordinal)
			    || string.Equals(name, RecruitmentPreviewOverlayName, StringComparison.Ordinal)
			    || name.StartsWith("HOMM3_", StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static void LogDetailOverlay(string key, string source, RectTransform rect, Image image)
	{
		if (_loggedDetailOverlay >= 24)
			return;
		_loggedDetailOverlay++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import unit preview overlay: applied idle UI overlay key='"
			+ (key ?? "?")
			+ "' source="
			+ (source ?? "?")
			+ " size="
			+ (rect ? rect.sizeDelta.ToString("F1") : "?")
			+ " sprite='"
			+ (image && image.sprite ? image.sprite.name : "?")
			+ "'.");
	}

	private static void LogDetailOverlayMiss(string key, string source, string reason)
	{
		if (_loggedDetailOverlayMiss >= 24)
			return;
		_loggedDetailOverlayMiss++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import unit preview overlay: skipped key='"
			+ (key ?? "?")
			+ "' source="
			+ (source ?? "?")
			+ " reason='"
			+ (reason ?? "?")
			+ "'.");
	}

	private static object GetMemberValue(object owner, string name)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name))
			return null;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = owner.GetType();
		try
		{
			var prop = type.GetProperty(name, flags);
			if (prop != null)
				return prop.GetValue(owner);
		}
		catch
		{
			// Generated IL2CPP accessors can exist in metadata but be absent at runtime.
		}
		try
		{
			var field = type.GetField(name, flags);
			if (field != null)
				return field.GetValue(owner);
		}
		catch
		{
			// ignored
		}
		return null;
	}

	private static bool SetMemberValue(object owner, string name, object value)
	{
		if (owner == null || string.IsNullOrWhiteSpace(name))
			return false;
		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		var type = owner.GetType();
		try
		{
			var prop = type.GetProperty(name, flags);
			if (prop != null && prop.CanWrite)
			{
				prop.SetValue(owner, value);
				return true;
			}
		}
		catch
		{
			// Generated IL2CPP accessors can drift; try the field.
		}
		try
		{
			var field = type.GetField(name, flags);
			if (field != null)
			{
				field.SetValue(owner, value);
				return true;
			}
		}
		catch
		{
			// ignored
		}
		return false;
	}

	private static GameObject GetPreviewModel(object preview)
	{
		return GetMemberValue(preview, "Model") as GameObject;
	}

	private static GameObject GetPreviewRotatable(object preview)
	{
		return GetMemberValue(preview, "Rotatable") as GameObject;
	}

	private static Renderer GetPreviewBackground(object preview)
	{
		return GetMemberValue(preview, "Background") as Renderer;
	}

	private static string GetPreviewSid(object preview)
	{
		return GetMemberValue(preview, "Sid") as string;
	}

	private static void SetPreviewModel(object preview, GameObject model)
	{
		SetMemberValue(preview, "Model", model);
	}

	private static void SetPreviewSid(object preview, string sid)
	{
		SetMemberValue(preview, "Sid", sid);
	}

	private static Component PreviewComponent(object preview)
	{
		return preview as Component;
	}

	private static void LogReflectedMiss(string message)
	{
		if (_loggedReflectedMiss >= 20)
			return;
		_loggedReflectedMiss++;
		Plugin.LogSource?.LogInfo("Homm3Import unit preview model: " + message);
	}

	private static string PreviewKeyFromViewConfig(UnitViewConfig viewConfig)
	{
		if (viewConfig == null)
			return null;
		var id = DeobfInteropCompat.GetConfigElementId(viewConfig);
		if (!string.IsNullOrEmpty(id) && id.StartsWith("h3_", StringComparison.Ordinal))
			return id;
		if (!string.IsNullOrEmpty(viewConfig.mesh))
			return viewConfig.mesh;
		var mapMesh = DeobfInteropCompat.GetUnitViewConfigMapMesh(viewConfig);
		if (!string.IsNullOrEmpty(mapMesh))
			return mapMesh;
		return null;
	}

	private static void TryApply(object preview, string key, string source)
	{
		if (preview == null || string.IsNullOrWhiteSpace(key))
			return;
		if (IsBhUnitPreviewsSharedPrefab(preview))
			return;
		if (IsRecruitmentPreviewSource(source) && !ShouldKeepNativeDetailPreviewMesh(key) && TryApplyRecruitmentPreviewOverlay(preview, key, source))
			return;
		if (IsRecruitmentPreviewSource(source) && !ShouldKeepNativeDetailPreviewMesh(key))
		{
			SuppressActiveLookUnitNativePreviewModels(source, ExtractStrongholdPreviewSid(key));
			return;
		}
		if (!IsRecruitmentPreviewSource(source) && IsRecruitmentLocalModel(GetPreviewModel(preview)))
			return;
		if (!TryGetBattleTemplate(key, out var template) || !template)
			return;

		var log = Plugin.LogSource;
		Homm3PreviewApplyNextFrame.QueueOrRun(log, () => ExecuteReplace(preview, key, source, template));
	}

	private static void TryApplyReflectedPreview(object preview, string key, string source)
	{
		if (string.IsNullOrWhiteSpace(key))
			return;
		var ownedSkinned = ShouldKeepNativeDetailPreviewMesh(key);
		if (preview == null)
		{
			if (ownedSkinned)
				LogOwnedSkinnedPreviewRefused(key, source, "no native preview wrapper (Model/Rotatable/Background)");
			return;
		}
		if (IsRecruitmentPreviewSource(source) && !ShouldKeepNativeDetailPreviewMesh(key) && TryApplyRecruitmentPreviewOverlay(preview, key, source))
			return;
		if (IsRecruitmentPreviewSource(source) && !ShouldKeepNativeDetailPreviewMesh(key))
		{
			SuppressActiveLookUnitNativePreviewModels(source, ExtractStrongholdPreviewSid(key));
			return;
		}
		var vanilla = GetPreviewModel(preview);
		if (!IsRecruitmentPreviewSource(source) && IsRecruitmentLocalModel(vanilla))
			return;
		if (!TryGetBattleTemplate(key, out var template) || !template)
		{
			if (ownedSkinned)
				LogOwnedSkinnedPreviewRefused(key, source, "battle prefab template did not load from the installed bundle");
			return;
		}

		var log = Plugin.LogSource;
		Homm3PreviewApplyNextFrame.QueueOrRun(log, () => ExecuteReplaceReflectedPreview(preview, key, source, template));
	}

	/// <summary>
	/// An owned skinned unit whose preview cannot take its bundle prefab keeps showing the native
	/// donor rig. That is never acceptable silently: log it as an error on every occurrence.
	/// </summary>
	private static void LogOwnedSkinnedPreviewRefused(string key, string source, string reason)
	{
		Plugin.LogSource?.LogError(
			"Homm3Import unit preview model: owned skinned preview refused key='"
			+ (key ?? "?")
			+ "' source="
			+ (source ?? "?")
			+ " reason='"
			+ (reason ?? "?")
			+ "'; the native donor model stays visible.");
	}

	private static bool TryApplyRecruitmentPreviewOverlay(object preview, string key, string source)
	{
		key = ExtractStrongholdPreviewSid(key);
		if (preview == null || string.IsNullOrWhiteSpace(key))
			return false;
		if (!Homm3CustomUiIconHook.TryResolveSprite(key, out var fallback) || !fallback)
			return false;

		try
		{
			var root = ResolveRecruitmentPreviewOverlayRoot(preview);
			if (!root)
				return false;

			var image = GetOrCreatePreviewOverlayImage(root, RecruitmentPreviewOverlayName, out var rect);
			if (!image || !rect)
				return false;

			rect.anchorMin = new Vector2(0.5f, 0.5f);
			rect.anchorMax = new Vector2(0.5f, 0.5f);
			rect.pivot = new Vector2(0.5f, 0.5f);
			rect.anchoredPosition = Vector2.zero;
			rect.sizeDelta = ResolveRecruitmentOverlaySize(root);
			rect.localRotation = Quaternion.identity;
			rect.localScale = Vector3.one;
			rect.SetAsLastSibling();

			image.raycastTarget = false;
			image.preserveAspect = true;
			image.type = Image.Type.Simple;
			image.color = Color.white;
			image.enabled = true;
			image.gameObject.SetActive(true);
			if (UseStaticPreviewPortraits())
			{
				Homm3HireUnitPortraitAnimator.Stop(image);
				image.sprite = fallback;
			}
			else
			{
				Homm3HireUnitPortraitAnimator.ApplyIdle(image, key, fallback);
			}
			HideDetailPreviewNativeModel(preview);
			LogDetailOverlay(key, source + ".recruitment-overlay", rect, image);
			return true;
		}
		catch (Exception ex)
		{
			LogDetailOverlayMiss(key, source + ".recruitment-overlay", "exception:" + ex.Message);
			if (IsRecruitmentPreviewSource(source))
				SuppressActiveLookUnitNativePreviewModels(source, key);
			return false;
		}
	}

	private static RectTransform ResolveRecruitmentPreviewOverlayRoot(object preview)
	{
		if (preview is Component component)
		{
			var own = component.transform as RectTransform;
			if (own)
				return own;
			var parent = component.GetComponentInParent<RectTransform>();
			if (parent)
				return parent;
		}

		var rotatable = GetPreviewRotatable(preview);
		if (rotatable)
		{
			var own = rotatable.transform as RectTransform;
			if (own)
				return own;
			var parent = rotatable.GetComponentInParent<RectTransform>();
			if (parent)
				return parent;
		}

		var model = GetPreviewModel(preview);
		if (model)
		{
			var own = model.transform.parent as RectTransform;
			if (own)
				return own;
			var parent = model.GetComponentInParent<RectTransform>();
			if (parent)
				return parent;
		}

		return null;
	}

	private static Vector2 ResolveRecruitmentOverlaySize(RectTransform root)
	{
		if (!root)
			return new Vector2(256f, 256f);
		var rect = root.rect;
		if (rect.width > 8f && rect.height > 8f)
		{
			var size = Mathf.Clamp(Mathf.Min(rect.width, rect.height) * 1.15f, 120f, 420f);
			return new Vector2(size, size);
		}
		return new Vector2(256f, 256f);
	}

	private static bool UseStaticPreviewPortraits()
	{
		return LauncherConfigReader.TryLoad()?.Homm3PreviewUseStaticPortraits ?? true;
	}

	private static bool UseStaticDetailPreviewPortraits()
	{
		return LauncherConfigReader.TryLoad()?.Homm3DetailPreviewUseStaticPortraits ?? false;
	}

	internal static void PushRecruitmentDonorAlias(string donorSid, string customSid)
	{
		if (string.IsNullOrWhiteSpace(donorSid) || string.IsNullOrWhiteSpace(customSid))
			return;
		var donor = NormalizePreviewDonorKey(donorSid);
		var custom = customSid.Trim();
		_activeRecruitmentAliases ??= new List<RecruitmentAlias>();
		_activeRecruitmentAliases.Add(new RecruitmentAlias(donor, custom));
	}

	internal static void PopRecruitmentDonorAlias(string donorSid, string customSid)
	{
		var aliases = _activeRecruitmentAliases;
		if (aliases == null || aliases.Count == 0)
			return;
		for (var i = aliases.Count - 1; i >= 0; i--)
		{
			var alias = aliases[i];
			if (string.Equals(alias.DonorSid, donorSid, StringComparison.OrdinalIgnoreCase)
			    && string.Equals(alias.CustomSid, customSid, StringComparison.OrdinalIgnoreCase))
			{
				aliases.RemoveAt(i);
				return;
			}
		}
		aliases.RemoveAt(aliases.Count - 1);
	}

	internal static bool TryResolveActiveRecruitmentCustomSid(string donorSid, out string customSid)
	{
		customSid = null;
		if (string.IsNullOrWhiteSpace(donorSid))
			return false;
		var aliases = _activeRecruitmentAliases;
		if (aliases == null || aliases.Count == 0)
			return false;
		var normalized = NormalizePreviewDonorKey(donorSid);
		for (var i = aliases.Count - 1; i >= 0; i--)
		{
			var alias = aliases[i];
			if (string.Equals(normalized, alias.DonorSid, StringComparison.OrdinalIgnoreCase)
			    || normalized.StartsWith(alias.DonorSid, StringComparison.OrdinalIgnoreCase))
			{
				customSid = alias.CustomSid;
				return !string.IsNullOrWhiteSpace(customSid);
			}
		}
		return false;
	}

	private static string ResolveActiveRecruitmentPreviewKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return key;
		var sid = key.Trim();
		if (sid.StartsWith("h3_", StringComparison.Ordinal))
			return sid;
		var aliases = _activeRecruitmentAliases;
		if (aliases == null || aliases.Count == 0)
			return sid;
		var normalized = NormalizePreviewDonorKey(sid);
		for (var i = aliases.Count - 1; i >= 0; i--)
		{
			var alias = aliases[i];
			if (string.Equals(normalized, alias.DonorSid, StringComparison.OrdinalIgnoreCase)
			    || normalized.StartsWith(alias.DonorSid, StringComparison.OrdinalIgnoreCase))
				return alias.CustomSid;
		}
		return sid;
	}

	private static string NormalizePreviewDonorKey(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return string.Empty;
		var leaf = key.Trim().Replace('\\', '/');
		var slash = leaf.LastIndexOf('/');
		if (slash >= 0)
			leaf = leaf[(slash + 1)..];
		if (leaf.EndsWith("_map", StringComparison.OrdinalIgnoreCase))
			leaf = leaf[..^4];
		if (leaf.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			leaf = leaf[..^7];
		if (string.Equals(leaf, "troglodyte", StringComparison.OrdinalIgnoreCase))
			return "trogl";
		return leaf;
	}

	private static bool TryResolvePreviewSidAlias(string key, out string customKey, out string donorSid)
	{
		customKey = null;
		donorSid = null;
		customKey = ExtractStrongholdPreviewSid(key);
		if (string.IsNullOrWhiteSpace(customKey))
			return false;
		if (!StrongholdUnitSidMapping.TryGetDonorSid(customKey, out donorSid))
			return false;
		return !string.IsNullOrWhiteSpace(donorSid);
	}

	private static bool TryResolvePreviewMeshAlias(string key, out string customKey, out string donorPath)
	{
		customKey = null;
		donorPath = null;
		customKey = ExtractStrongholdPreviewSid(key);
		if (string.IsNullOrWhiteSpace(customKey))
			return false;
		if (!StrongholdUnitSidMapping.TryGetDonorSid(customKey, out var donorSid))
			return false;
		donorPath = DonorSidToDungeonPreviewPath(donorSid);
		return !string.IsNullOrWhiteSpace(donorPath);
	}

	private static string ExtractStrongholdPreviewSid(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return null;
		var leaf = key.Trim().Replace('\\', '/');
		var slash = leaf.LastIndexOf('/');
		if (slash >= 0)
			leaf = leaf[(slash + 1)..];
		if (leaf.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			leaf = leaf[..^7];
		if (leaf.EndsWith("_map", StringComparison.OrdinalIgnoreCase))
			leaf = leaf[..^4];
		return leaf.StartsWith("h3_", StringComparison.Ordinal) ? leaf : null;
	}

	private static string NormalizeDungeonDonorLeaf(string donorSid)
	{
		if (string.IsNullOrWhiteSpace(donorSid))
			return null;
		var leaf = donorSid.Trim();
		if (leaf.StartsWith("trogl", StringComparison.OrdinalIgnoreCase))
			leaf = "troglodyte" + leaf.Substring("trogl".Length);
		return leaf;
	}

	private static string DonorSidToPreviewCatalogId(string donorSid)
	{
		// Show.bewc rum() keys UnitViewConfig.id (DonorBaseSid, e.g. trogl).
		// troglodyte is only the Dungeon/1Prefabs folder leaf — rum("troglodyte") misses and NREs.
		if (string.IsNullOrWhiteSpace(donorSid))
			return null;
		return donorSid.Trim();
	}

	private static string DonorSidToDungeonPreviewPath(string donorSid)
	{
		var leaf = NormalizeDungeonDonorLeaf(donorSid);
		return string.IsNullOrWhiteSpace(leaf) ? null : "Dungeon/1Prefabs/" + leaf;
	}

	private static bool EndsWithMapSuffix(string key)
	{
		if (string.IsNullOrWhiteSpace(key))
			return false;
		var normalized = key.Trim().Replace('\\', '/');
		if (normalized.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
			normalized = normalized[..^7];
		return normalized.EndsWith("_map", StringComparison.OrdinalIgnoreCase);
	}

	private static void LogPreviewAlias(string customKey, string original, string donor, string source)
	{
		if (_loggedPreviewAlias >= 20)
			return;
		_loggedPreviewAlias++;
		Plugin.LogSource?.LogInfo(
			"Homm3Import unit preview model: donor alias '" + customKey
			+ "' original='" + (original ?? "")
			+ "' donor='" + (donor ?? "")
			+ "' source=" + source + ".");
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "?";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}

	private static Exception SuppressKnownPreviewMiss(Exception ex, string key, string source)
	{
		if (!IsKeyNotFoundException(ex) && !IsNativePreviewNullRef(ex))
			return ex;
		if (_loggedNativePreviewMiss < 12)
		{
			_loggedNativePreviewMiss++;
			Plugin.LogSource?.LogWarning(
				"Homm3Import unit preview model: native preview construction missed custom key '"
				+ (key ?? "?")
				+ "' via "
				+ (source ?? "?")
				+ "; suppressing after owned mesh or portrait apply.");
		}
		return null;
	}

	private static bool IsNativePreviewNullRef(Exception ex)
	{
		if (ex == null)
			return false;
		var text = ex.ToString();
		if (text.IndexOf("NullReferenceException", StringComparison.Ordinal) < 0)
			return false;
		return text.IndexOf("BhUnitWindowPreview.bewc", StringComparison.Ordinal) >= 0
		       || text.IndexOf("BhUnitWindowPreview.Show", StringComparison.Ordinal) >= 0
		       || text.IndexOf("clv.sry", StringComparison.Ordinal) >= 0;
	}

	private static bool IsKeyNotFoundException(Exception ex)
	{
		for (var e = ex; e != null; e = e.InnerException)
		{
			if (e.GetType().Name == "KeyNotFoundException")
				return true;
		}
		return ex.ToString().IndexOf("KeyNotFoundException", StringComparison.Ordinal) >= 0;
	}

	private static void ExecuteReplaceReflectedPreview(object preview, string key, string source, GameObject template)
	{
		if (preview == null || !template)
			return;
		var vanilla = GetPreviewModel(preview);
		if (IsProductionPreviewReplacement(vanilla))
		{
			ConfigureExistingReflectedPreviewModel(preview, key, source, vanilla);
			return;
		}
		if (vanilla && Homm3ImportVisuals.LooksLikeHomm3BundleBattleInstance(vanilla))
		{
			ConfigureExistingReflectedPreviewModel(preview, key, source, vanilla);
			return;
		}

		try
		{
			var instance = UnityEngine.Object.Instantiate(template);
			if (!instance)
				return;
			instance.name = template.name;
			TryMoveInstanceToPreviewScene(preview, instance);
			// The native donor model in this rig is a loaded Hex/Lit mesh: hand it over as the
			// material donor so the owned skinned rebind clones a real native Hex/Lit sheet.
			TryPrepareOwnedSkinnedPreview(key, instance, vanilla);
			var skinnedLane = Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance);

			var rotatable = GetPreviewRotatable(preview);
			var parent = vanilla ? vanilla.transform.parent : null;
			if (parent == null && rotatable)
				parent = rotatable.transform;
			if (parent == null)
				parent = vanilla ? vanilla.transform : null;
			if (parent == null && skinnedLane)
			{
				UnityEngine.Object.Destroy(instance);
				LogOwnedSkinnedPreviewRefused(key, source, "native preview wrapper has neither Model nor Rotatable to parent under");
				return;
			}

			var it = instance.transform;
			if (parent != null)
				it.SetParent(parent, false);
			Renderer donor = null;
			if (vanilla)
			{
				instance.SetActive(true);
				if (!skinnedLane)
				{
					var vt = vanilla.transform;
					it.localPosition = vt.localPosition;
					it.localRotation = vt.localRotation;
					it.localScale = vt.localScale;
					EsquireBattleVisualPresentation.SyncAdventureMapPrefabPresentationFromVanilla(vanilla, instance);
					EsquireBattleVisualPresentation.SyncSpriteRenderersDepthFirst(vanilla, instance);

					donor = EsquireBattleVisualPresentation.TryFindDominantRenderable(vanilla);
					EsquireBattleVisualPresentation.ApplyRenderingLayerMaskFromDonor(donor, instance);
					EsquireBattleVisualPresentation.SyncMeshSortingFromDominantVanillaMesh(vanilla, instance);
				}

				var previewLayer = ResolvePreviewUnityLayer(preview, vanilla);
				ApplyLayerRecursive(instance.transform, previewLayer);
				ConfigurePreviewRenderers(instance);
				if (skinnedLane)
					FrameOwnedSkinnedPreview(key, vanilla, instance, keepPose: false, source);
				else
				{
					TryPromoteSpritesDefaultBillboardToHexLit(instance);

					AlignFeetToVanilla(vanilla, instance);
					TryScaleInstanceToDonorBounds(donor, instance);
					AlignFeetToVanilla(vanilla, instance);
				}
				HidePreviewDonorModel(vanilla, instance);
			}
			else
			{
				ConfigurePreviewRenderers(instance);
				if (skinnedLane)
					FrameOwnedSkinnedPreview(key, null, instance, keepPose: false, source);
				else
					TryPromoteSpritesDefaultBillboardToHexLit(instance);
			}

			var background = GetPreviewBackground(preview);
			if (!skinnedLane)
			{
				if (IsRecruitmentPreviewSource(source) || IsRecruitmentLocalModel(vanilla))
					ApplyRecruitmentPreviewPose(preview, instance);
				else
				{
					FitBoundsToPreviewBackground(background, instance);
					instance = BuildPreviewCalibrationSet(preview, instance, donor);
				}
			}

			SetMemberValue(preview, "Model", instance);
			SetMemberValue(preview, "Sid", key);
			Homm3PreviewFineTuneRegistry.SetTarget(instance, donor, background);
			LogReplace(source, key, preview, instance, vanilla, donor);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import unit preview model ExecuteReplaceReflectedPreview: " + ex);
		}
	}

	private static void ConfigureExistingReflectedPreviewModel(object preview, string key, string source, GameObject instance)
	{
		if (preview == null || !instance)
			return;
		try
		{
			if (IsProductionPreviewReplacement(instance))
			{
				ConfigurePreviewRenderers(instance);
				SetMemberValue(preview, "Model", instance);
				SetMemberValue(preview, "Sid", key);
				Homm3PreviewFineTuneRegistry.SetTarget(instance, null, GetPreviewBackground(preview));
				LogReplace(source + ":existing-stable", key, preview, instance, null, null);
				return;
			}

			GameObject presentation = null;
			Renderer donor = null;
			TryPrepareOwnedSkinnedPreview(key, instance);
			if (!Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
			{
				var unitsPath = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(key);
				if (Homm3ImportVisuals.TryResolveHomm3BattleEntry(unitsPath, Plugin.LogSource, out var entry)
				    && entry != null
				    && Homm3ImportVisuals.TryGetBattlePresentationTemplate(entry, Plugin.LogSource, out presentation)
				    && presentation)
				{
					EsquireBattleVisualPresentation.SyncLayersOnlyFromVanilla(presentation, instance);
					EsquireBattleVisualPresentation.SyncSpriteRenderersDepthFirst(presentation, instance);
					donor = EsquireBattleVisualPresentation.TryFindDominantRenderable(presentation);
					EsquireBattleVisualPresentation.ApplyRenderingLayerMaskFromDonor(donor, instance);
					EsquireBattleVisualPresentation.SyncMeshSortingFromDominantVanillaMesh(presentation, instance);
				}
			}

			var previewLayer = ResolvePreviewUnityLayer(preview, instance);
			ApplyLayerRecursive(instance.transform, previewLayer);
			ConfigurePreviewRenderers(instance);
			var skinnedLane = Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance);
			if (!skinnedLane)
				TryPromoteSpritesDefaultBillboardToHexLit(instance);
			var background = GetPreviewBackground(preview);
			if (skinnedLane)
				FrameOwnedSkinnedPreview(key, null, instance, keepPose: true, source);
			else if (IsRecruitmentPreviewSource(source) || IsRecruitmentLocalModel(instance))
				ApplyRecruitmentPreviewPose(preview, instance);
			else
			{
				FitBoundsToPreviewBackground(background, instance);
				instance = BuildPreviewCalibrationSet(preview, instance, donor);
			}

			SetMemberValue(preview, "Model", instance);
			SetMemberValue(preview, "Sid", key);
			Homm3PreviewFineTuneRegistry.SetTarget(instance, donor, background);
			LogReplace(source + ":existing", key, preview, instance, null, donor);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import unit preview model ConfigureExistingReflectedPreviewModel: " + ex);
		}
	}

	/// <summary>
	/// <see cref="BhUnitPreviews.prefab"/> is a shared template preview wrapper; mutating or destroying its model
	/// corrupts every screen that uses the service (e.g. city UI after exit).
	/// </summary>
	private static bool IsBhUnitPreviewsSharedPrefab(object preview)
	{
		var component = PreviewComponent(preview);
		if (!component)
			return false;
		try
		{
			var host = component.GetComponentInParent<BhUnitPreviews>();
			if (host == null)
				return false;
			var pref = GetMemberValue(host, "prefab");
			return pref != null && ReferenceEquals(pref, preview);
		}
		catch
		{
			return false;
		}
	}

	/// <summary>Used by legacy external preview discovery: same replace as <see cref="TryApply"/>.</summary>
	internal static void TryApplyFromExternalDiscovery(object preview, string key, string source)
	{
		TryApply(preview, key, source);
	}

	private static void ExecuteReplace(object preview, string key, string source, GameObject template)
	{
		if (preview == null || !template)
			return;
		if (IsBhUnitPreviewsSharedPrefab(preview))
			return;

		var vanilla = GetPreviewModel(preview);
		if (IsProductionPreviewReplacement(vanilla))
		{
			ConfigureExistingHomm3PreviewModel(preview, key, source, vanilla);
			return;
		}
		if (vanilla && Homm3ImportVisuals.LooksLikeHomm3BundleBattleInstance(vanilla))
		{
			ConfigureExistingHomm3PreviewModel(preview, key, source, vanilla);
			return;
		}

		try
		{
			var instance = UnityEngine.Object.Instantiate(template);
			if (!instance)
				return;
			instance.name = template.name;
			TryMoveInstanceToPreviewScene(preview, instance);
			TryPrepareOwnedSkinnedPreview(key, instance, vanilla);
			var skinnedLane = Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance);

			var parent = vanilla ? vanilla.transform.parent : null;
			var rotatable = GetPreviewRotatable(preview);
			if (parent == null && rotatable)
				parent = rotatable.transform;
			if (parent == null)
				parent = PreviewComponent(preview)?.transform;
			if (parent == null)
				return;

			var it = instance.transform;
			it.SetParent(parent, false);
			Renderer donor = null;
			if (vanilla)
			{
				instance.SetActive(true);
				if (!skinnedLane)
				{
					var vt = vanilla.transform;
					it.localPosition = vt.localPosition;
					it.localRotation = vt.localRotation;
					it.localScale = vt.localScale;
					EsquireBattleVisualPresentation.SyncAdventureMapPrefabPresentationFromVanilla(vanilla, instance);
					EsquireBattleVisualPresentation.SyncSpriteRenderersDepthFirst(vanilla, instance);

					donor = EsquireBattleVisualPresentation.TryFindDominantRenderable(vanilla);
					EsquireBattleVisualPresentation.ApplyRenderingLayerMaskFromDonor(donor, instance);
					EsquireBattleVisualPresentation.SyncMeshSortingFromDominantVanillaMesh(vanilla, instance);
				}

				var previewLayer = ResolvePreviewUnityLayer(preview, vanilla);
				ApplyLayerRecursive(instance.transform, previewLayer);
				ConfigurePreviewRenderers(instance);
				if (skinnedLane)
					FrameOwnedSkinnedPreview(key, vanilla, instance, keepPose: false, source);
				else
				{
					TryPromoteSpritesDefaultBillboardToHexLit(instance);
					AlignFeetToVanilla(vanilla, instance);
					TryScaleInstanceToDonorBounds(donor, instance);
					AlignFeetToVanilla(vanilla, instance);
				}

				HidePreviewDonorModel(vanilla, instance);
			}
			else
			{
				ConfigurePreviewRenderers(instance);
				if (skinnedLane)
					FrameOwnedSkinnedPreview(key, null, instance, keepPose: false, source);
				else
					TryPromoteSpritesDefaultBillboardToHexLit(instance);
			}
			if (!skinnedLane)
			{
				if (IsRecruitmentPreview(preview, source))
					ApplyRecruitmentPreviewPose(preview, instance);
				else
				{
					FitBoundsToPreviewBackground(GetPreviewBackground(preview), instance);
					instance = BuildPreviewCalibrationSet(preview, instance, donor);
				}
			}

			SetPreviewModel(preview, instance);
			SetPreviewSid(preview, key);
			Homm3PreviewFineTuneRegistry.SetTarget(instance, donor, GetPreviewBackground(preview));
			LogReplace(source, key, preview, instance, vanilla, donor);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import unit preview model ExecuteReplace: " + ex);
		}
	}

	private static void ConfigureExistingHomm3PreviewModel(object preview, string key, string source, GameObject instance)
	{
		if (preview == null || !instance)
			return;
		try
		{
			if (IsProductionPreviewReplacement(instance))
			{
				ConfigurePreviewRenderers(instance);
				SetPreviewModel(preview, instance);
				SetPreviewSid(preview, key);
				Homm3PreviewFineTuneRegistry.SetTarget(instance, null, GetPreviewBackground(preview));
				LogReplace(source + "/existing-stable", key, preview, instance, null, null);
				return;
			}

			GameObject presentation = null;
			Renderer donor = null;
			TryPrepareOwnedSkinnedPreview(key, instance);
			var skinnedLane = Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance);
			var unitsPath = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(key);
			if (!skinnedLane
			    && Homm3ImportVisuals.TryResolveHomm3BattleEntry(unitsPath, Plugin.LogSource, out var entry)
			    && entry != null
			    && Homm3ImportVisuals.TryGetBattlePresentationTemplate(entry, Plugin.LogSource, out presentation)
			    && presentation)
			{
				EsquireBattleVisualPresentation.SyncLayersOnlyFromVanilla(presentation, instance);
				EsquireBattleVisualPresentation.SyncSpriteRenderersDepthFirst(presentation, instance);
				donor = EsquireBattleVisualPresentation.TryFindDominantRenderable(presentation);
				EsquireBattleVisualPresentation.ApplyRenderingLayerMaskFromDonor(donor, instance);
				EsquireBattleVisualPresentation.SyncMeshSortingFromDominantVanillaMesh(presentation, instance);
			}

			var previewLayer = ResolvePreviewUnityLayer(preview, instance);
			ApplyLayerRecursive(instance.transform, previewLayer);
			ConfigurePreviewRenderers(instance);
			if (!skinnedLane)
			{
				TryPromoteSpritesDefaultBillboardToHexLit(instance);
				if (donor)
					TryScaleInstanceToDonorBounds(donor, instance);
			}
			if (skinnedLane)
				FrameOwnedSkinnedPreview(key, null, instance, keepPose: true, source);
			else if (IsRecruitmentPreview(preview, source))
				ApplyRecruitmentPreviewPose(preview, instance);
			else
			{
				FitBoundsToPreviewBackground(GetPreviewBackground(preview), instance);
				instance = BuildPreviewCalibrationSet(preview, instance, donor);
			}

			SetPreviewModel(preview, instance);
			SetPreviewSid(preview, key);
			Homm3PreviewFineTuneRegistry.SetTarget(instance, donor, GetPreviewBackground(preview));
			LogReplace(source + "/existing", key, preview, instance, presentation, donor);
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError("Homm3Import unit preview existing model configure failed: " + ex);
		}
	}

	private static void HidePreviewDonorModel(GameObject vanilla, GameObject replacement)
	{
		if (!vanilla || SameGameObject(vanilla, replacement))
			return;
		var renderers = vanilla.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var renderer = renderers[i];
			if (!renderer)
				continue;
			if (replacement && renderer.transform.IsChildOf(replacement.transform))
				continue;
			renderer.enabled = false;
		}
		vanilla.SetActive(false);
	}

	private static bool SameGameObject(GameObject left, GameObject right)
	{
		return left && right && left.GetInstanceID() == right.GetInstanceID();
	}

	/// <summary>Owned skinned preview: the battle-size rule of <see cref="Homm3OwnedSkinnedPreviewFraming"/>, keyed on this preview's own entry.</summary>
	private static void FrameOwnedSkinnedPreview(string key, GameObject vanilla, GameObject instance, bool keepPose, string source)
	{
		if (!TryResolveOwnedSkinnedEntry(key, out var entry))
			LogOwnedSkinnedPreviewRefused(key, source, "no homm3_import entry resolves this key; preview size cannot follow the battle fit");
		else
			Homm3OwnedSkinnedPreviewFraming.TryFrame(instance, entry, vanilla, keepPose, 0f, source, Plugin.LogSource);
		if (instance && instance.name.IndexOf("_preview_inplace", StringComparison.OrdinalIgnoreCase) < 0)
			instance.name = instance.name + "_preview_inplace0";
	}

	private static bool TryResolveOwnedSkinnedEntry(string key, out Homm3ImportVisuals.Entry entry)
	{
		if (Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(key, Plugin.LogSource, out entry) && entry != null)
			return true;
		return Homm3ImportVisuals.TryResolveHomm3BattleEntry(EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(key), Plugin.LogSource, out entry)
		       && entry != null;
	}

	private static void AlignFeetToVanilla(GameObject vanilla, GameObject instance)
	{
		if (!vanilla || !instance)
			return;
		if (!TryMergedRendererBoundsIgnoreInactiveHierarchy(vanilla, out var vb))
			return;
		if (!TryMergedRendererBoundsIgnoreInactiveHierarchy(instance, out var il))
			return;
		var p = instance.transform.position;
		p.y += vb.min.y - il.min.y;
		instance.transform.position = p;
	}

	private static void FitBoundsToPreviewBackground(Renderer background, GameObject instance)
	{
		if (!background || !instance)
			return;
		if (!TryMergedRendererBoundsIgnoreInactiveHierarchy(instance, out var il))
			return;
		var bb = background.bounds;
		const float euo = 1e-4f;
		if (il.size.y > euo && bb.size.y > euo)
		{
			var fit = bb.size.y * 0.85f / il.size.y;
			if (IsUsefulPreviewFitFactor(fit))
			{
				instance.transform.localScale *= fit;
				if (!TryMergedRendererBoundsIgnoreInactiveHierarchy(instance, out il))
					return;
			}
		}

		var p = instance.transform.position;
		p.x += bb.center.x - il.center.x;
		p.y += bb.center.y - il.center.y;
		p.z += bb.center.z - il.center.z;
		instance.transform.position = p;
	}

	private static bool IsRecruitmentPreview(object preview, string source)
	{
		return IsRecruitmentPreviewSource(source) || IsBhUnitPreviewsHostedPreview(preview) || IsRecruitmentLocalModel(GetPreviewModel(preview));
	}

	private static bool IsRecruitmentPreviewSource(string source)
	{
		return !string.IsNullOrEmpty(source)
		       && (source.IndexOf("BhUnitPreviews.hqr", StringComparison.OrdinalIgnoreCase) >= 0
		           || source.IndexOf("BhUnitPreviews.previewFactory", StringComparison.OrdinalIgnoreCase) >= 0
		           || source.IndexOf("BhHireUnitItemView.previewFactory", StringComparison.OrdinalIgnoreCase) >= 0);
	}

	private static void SuppressActiveLookUnitNativePreviewModels(string source, string key)
	{
		try
		{
			var scene = SceneManager.GetSceneByName("lookUnit");
			if (!scene.IsValid() || !scene.isLoaded)
				return;

			var roots = scene.GetRootGameObjects();
			var hidden = 0;
			for (var i = 0; i < roots.Length; i++)
			{
				var root = roots[i];
				if (!root)
					continue;
				hidden += SuppressActiveLookUnitNativePreviewModelsUnder(root.transform);
			}
			if (hidden > 0 && _loggedRecruitmentNativeSuppressed < 20)
			{
				_loggedRecruitmentNativeSuppressed++;
				Plugin.LogSource?.LogInfo(
					"Homm3Import unit preview model: suppressed native recruitment preview models"
					+ " count=" + hidden
					+ " key='" + (key ?? "") + "'"
					+ " source=" + (source ?? "?") + ".");
			}
		}
		catch (Exception ex)
		{
			if (_loggedRecruitmentNativeSuppressed < 20)
			{
				_loggedRecruitmentNativeSuppressed++;
				Plugin.LogSource?.LogWarning("Homm3Import unit preview model: native recruitment preview suppression failed: " + ex.Message);
			}
		}
	}

	private static int SuppressActiveLookUnitNativePreviewModelsUnder(Transform root)
	{
		if (!root)
			return 0;
		var hidden = 0;
		var go = root.gameObject;
		if (go && go.activeInHierarchy && IsLookUnitNativePreviewModelRoot(go))
		{
			go.SetActive(false);
			hidden++;
		}

		for (var i = 0; i < root.childCount; i++)
			hidden += SuppressActiveLookUnitNativePreviewModelsUnder(root.GetChild(i));
		return hidden;
	}

	private static int RestoreNativePreviewRenderers(GameObject root)
	{
		if (!root)
			return 0;
		var restored = 0;
		var renderers = root.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var renderer = renderers[i];
			if (!renderer || IsCustomPreviewRenderer(renderer))
				continue;
			if (renderer.enabled)
				continue;
			renderer.enabled = true;
			restored++;
		}
		return restored;
	}

	private static bool IsLookUnitNativePreviewModelRoot(GameObject go)
	{
		if (!go || !go.transform || !go.scene.IsValid() || !string.Equals(go.scene.name, "lookUnit", StringComparison.Ordinal))
			return false;
		var name = go.name ?? "";
		if (!name.EndsWith("(Clone)", StringComparison.Ordinal))
			return false;
		if (name.IndexOf("PLATFORM", StringComparison.OrdinalIgnoreCase) >= 0
		    || name.IndexOf("BACK", StringComparison.OrdinalIgnoreCase) >= 0
		    || name.IndexOf("background", StringComparison.OrdinalIgnoreCase) >= 0)
			return false;
		var parent = go.transform.parent;
		if (!parent || !string.Equals(parent.gameObject.name ?? "", "platform", StringComparison.OrdinalIgnoreCase))
			return false;
		var cursor = parent.parent;
		var sawSpawnRoot = false;
		var sawLookUnit = false;
		while (cursor)
		{
			var cursorName = cursor.gameObject ? cursor.gameObject.name ?? "" : "";
			if (string.Equals(cursorName, "SPAWN ROOT", StringComparison.OrdinalIgnoreCase)
			    || string.Equals(cursorName, "SPAWN ROOT (1)", StringComparison.OrdinalIgnoreCase))
				sawSpawnRoot = true;
			if (cursorName.StartsWith("LOOK UNIT", StringComparison.OrdinalIgnoreCase))
				sawLookUnit = true;
			cursor = cursor.parent;
		}
		return sawSpawnRoot && sawLookUnit;
	}

	private static bool IsBhUnitPreviewsHostedPreview(object preview)
	{
		var component = PreviewComponent(preview);
		if (!component)
			return false;
		try
		{
			return component.GetComponentInParent<BhUnitPreviews>() != null;
		}
		catch
		{
			return false;
		}
	}

	private static bool IsRecruitmentLocalModel(GameObject model)
	{
		return model && model.name.IndexOf("_recruitment_local", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static void ApplyRecruitmentPreviewPose(object preview, GameObject instance)
	{
		if (!instance)
			return;
		if (!IsRecruitmentLocalModel(instance))
			instance.name = instance.name + "_recruitment_local";
		ScaleOnlyToPreviewBackground(GetPreviewBackground(preview), instance, 0.45f);
		LogPreviewCalibrationCandidate("recruitment_local", instance);
	}

	private static void ScaleOnlyToPreviewBackground(Renderer background, GameObject instance, float fill)
	{
		if (!background || !instance)
			return;
		if (!TryMergedRendererBoundsIgnoreInactiveHierarchy(instance, out var il))
			return;
		var bb = background.bounds;
		const float euo = 1e-4f;
		if (il.size.y < euo || bb.size.y < euo)
			return;
		var fit = bb.size.y * fill / il.size.y;
		if (IsUsefulPreviewFitFactor(fit))
			instance.transform.localScale *= fit;
	}

	private static bool IsUsefulPreviewFitFactor(float fit)
	{
		return !float.IsNaN(fit)
		       && !float.IsInfinity(fit)
		       && fit >= MinPreviewDownscaleFactor
		       && fit <= MaxPreviewUpscaleFactor;
	}

	private static GameObject BuildPreviewCalibrationSet(object preview, GameObject fitted, Renderer donor)
	{
		if (!fitted)
			return fitted;
		if (!PreviewCalibrationEnabled)
		{
			ApplyPreviewCylinderPose(preview, fitted, fitted.transform.parent);
			return fitted;
		}

		try
		{
			var parent = fitted.transform.parent;
			var group = new GameObject("HOMM3_preview_calibration_" + fitted.name);
			TryMoveInstanceToPreviewScene(preview, group);
			group.SetActive(true);
			group.layer = fitted.layer;
			group.transform.SetParent(parent, false);
			group.transform.localPosition = Vector3.zero;
			group.transform.localRotation = Quaternion.identity;
			group.transform.localScale = Vector3.one;

			var variants = new[]
			{
				new PreviewCalibrationVariant("A_orbit160_raised_mid", new Vector3(0f, -0.18f, 0f), Vector3.zero, false, 160f),
				new PreviewCalibrationVariant("B_orbit180_raised_mid", new Vector3(0f, -0.18f, 0f), Vector3.zero, false, 180f),
				new PreviewCalibrationVariant("C_orbit200_raised_mid", new Vector3(0f, -0.18f, 0f), Vector3.zero, false, 200f)
			};

			for (var i = 0; i < variants.Length; i++)
			{
				var v = variants[i];
				var candidate = i == 0 ? fitted : UnityEngine.Object.Instantiate(fitted);
				if (!candidate)
					continue;
				candidate.name = v.Name;
				candidate.SetActive(true);
				TryMoveInstanceToPreviewScene(preview, candidate);
				candidate.transform.SetParent(group.transform, true);
				ApplyLayerRecursive(candidate.transform, group.layer);
				ConfigurePreviewRenderers(candidate);
				ApplyCalibrationPose(candidate, v, donor);
				MoveCalibrationCandidateToSlot(GetPreviewBackground(preview), candidate, v.Slot);
				if (Mathf.Abs(v.OrbitDegrees) > 1e-4f)
					OrbitCandidateAroundParentY(candidate, parent, v.OrbitDegrees);
				LogPreviewCalibrationCandidate(v.Name, candidate);
			}

			Plugin.LogSource?.LogInfo(
				"Homm3 preview calibration active: medium raised upright candidates at orbit160, orbit180, orbit200.");
			return group;
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3 preview calibration setup failed; using fitted single model. " + ex.Message);
			return fitted;
		}
	}

	private static bool IsProductionPreviewReplacement(GameObject instance)
	{
		return instance
		       && !string.IsNullOrWhiteSpace(instance.name)
		       && (instance.name.IndexOf("_preview_orbit", StringComparison.OrdinalIgnoreCase) >= 0
		           || instance.name.IndexOf("_preview_inplace", StringComparison.OrdinalIgnoreCase) >= 0);
	}

	private static void ApplyPreviewCylinderPose(object preview, GameObject instance, Transform parent)
	{
		if (!instance)
			return;
		instance.name = instance.name + "_preview_inplace0";
		instance.transform.localScale *= PreviewScaleMultiplier;
		MoveCalibrationCandidateToSlot(GetPreviewBackground(preview), instance, PreviewSlot);
		LogPreviewCalibrationCandidate("production_inplace0", instance);
	}

	private static void ApplyCalibrationPose(GameObject candidate, PreviewCalibrationVariant variant, Renderer donor)
	{
		if (!candidate)
			return;
		var t = candidate.transform;
		if (variant.UseDonorPose && donor != null)
		{
			try
			{
				t.rotation = donor.transform.rotation;
				if (TryMergedRendererBoundsIgnoreInactiveHierarchy(candidate, out var cb))
				{
					var p = t.position;
					p += donor.bounds.center - cb.center;
					t.position = p;
				}
			}
			catch
			{
				// Fall back to the unrotated fitted pose for this diagnostic candidate.
			}
		}
		else
		{
			t.localEulerAngles += variant.LocalEulerDelta;
		}

		t.localScale *= 1.45f;
	}

	private static void OrbitCandidateAroundParentY(GameObject candidate, Transform parent, float degrees)
	{
		if (!candidate || parent == null)
			return;
		var q = Quaternion.Euler(0f, degrees, 0f);
		var ct = candidate.transform;
		var pivot = parent.position;
		ct.position = pivot + q * (ct.position - pivot);
		ct.rotation = q * ct.rotation;
	}

	private static void OrbitCandidatePositionAroundParentY(GameObject candidate, Transform parent, float degrees)
	{
		if (!candidate || parent == null)
			return;
		var q = Quaternion.Euler(0f, degrees, 0f);
		var ct = candidate.transform;
		var pivot = parent.position;
		ct.position = pivot + q * (ct.position - pivot);
	}

	private static void MoveCalibrationCandidateToSlot(Renderer background, GameObject candidate, Vector3 normalizedSlot)
	{
		if (!background || !candidate)
			return;
		if (!TryMergedRendererBoundsIgnoreInactiveHierarchy(candidate, out var cb))
			return;
		var bb = background.bounds;
		var target = bb.center
		             + new Vector3(bb.size.x * normalizedSlot.x, bb.size.y * normalizedSlot.y, 0f);
		var p = candidate.transform.position;
		p += target - cb.center;
		candidate.transform.position = p;
	}

	private static void LogPreviewCalibrationCandidate(string label, GameObject candidate)
	{
		if (!candidate)
			return;
		if (TryMergedRendererBoundsIgnoreInactiveHierarchy(candidate, out var b))
		{
			Plugin.LogSource?.LogInfo(
				"Homm3 preview calibration "
				+ label
				+ ": localPos="
				+ candidate.transform.localPosition.ToString("F3")
				+ " localEuler="
				+ candidate.transform.localEulerAngles.ToString("F1")
				+ " localScale="
				+ candidate.transform.localScale.ToString("F3")
				+ " boundsCenter="
				+ b.center.ToString("F3")
				+ " boundsSize="
				+ b.size.ToString("F3"));
		}
	}

	private readonly struct PreviewCalibrationVariant
	{
		internal readonly string Name;
		internal readonly Vector3 Slot;
		internal readonly Vector3 LocalEulerDelta;
		internal readonly bool UseDonorPose;
		internal readonly float OrbitDegrees;

		internal PreviewCalibrationVariant(string name, Vector3 slot, Vector3 localEulerDelta, bool useDonorPose, float orbitDegrees)
		{
			Name = name;
			Slot = slot;
			LocalEulerDelta = localEulerDelta;
			UseDonorPose = useDonorPose;
			OrbitDegrees = orbitDegrees;
		}
	}

	private readonly struct RecruitmentAlias
	{
		internal readonly string DonorSid;
		internal readonly string CustomSid;

		internal RecruitmentAlias(string donorSid, string customSid)
		{
			DonorSid = donorSid;
			CustomSid = customSid;
		}
	}

	/// <summary>
	/// <see cref="EsquireBattleVisualPresentation.TryEncapsulateWorldRenderBounds"/> skips renderers whose GameObjects are
	/// inactive in hierarchy; cached preview rigs often have <c>activeInHierarchy=false</c> until the window opens.
	/// </summary>
	private static bool TryMergedRendererBoundsIgnoreInactiveHierarchy(GameObject go, out Bounds merged)
	{
		merged = default;
		if (!go)
			return false;
		var any = false;
		foreach (var r in go.GetComponentsInChildren<Renderer>(true))
		{
			if (!r || !r.enabled)
				continue;
			if (!any)
			{
				merged = r.bounds;
				any = true;
			}
			else
				merged.Encapsulate(r.bounds);
		}
		return any;
	}

	private static void TryScaleInstanceToDonorBounds(Renderer donor, GameObject instance)
	{
		if (!donor || !instance)
			return;
		if (Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
			return;
		if (!TryMergedRendererBoundsIgnoreInactiveHierarchy(instance, out var cb))
			return;
		var v = donor.bounds.size;
		var c = cb.size;
		const float euo = 1e-4f;
		if (c.x < euo || c.y < euo)
			return;
		var fx = v.x / Mathf.Max(c.x, euo);
		var fy = v.y / Mathf.Max(c.y, euo);
		var fz = v.z / Mathf.Max(c.z, euo);
		float u;
		if (c.z < 0.25f)
			u = Mathf.Min(fx, fy);
		else
			u = Mathf.Min(Mathf.Min(fx, fy), fz);
		if (u <= 0f || float.IsNaN(u) || float.IsInfinity(u) || u > 100f)
			return;
		instance.transform.localScale *= u;
	}

	private static int ResolvePreviewUnityLayerLegacy(object preview, GameObject vanilla)
	{
		// Vanilla unit mesh is often layer 0 while the preview rig (Rotatable / backdrop) uses the camera’s culling layer (e.g. 31).
		var rotatable = GetPreviewRotatable(preview);
		if (rotatable)
			return rotatable.layer;
		var component = PreviewComponent(preview);
		if (component && component.gameObject.layer != 0)
			return component.gameObject.layer;
		if (TryGetBhUnitPreviewConfiguredLayer(preview, out var hostLayer))
			return hostLayer;
		return GetPreviewRenderLayer(vanilla);
	}

	private static int ResolvePreviewUnityLayer(object preview, GameObject vanilla)
	{
		var rotatable = GetPreviewRotatable(preview);
		if (rotatable)
			return rotatable.layer;
		var component = PreviewComponent(preview);
		if (component && component.gameObject.layer != 0)
			return component.gameObject.layer;
		if (TryGetBhUnitPreviewConfiguredLayer(preview, out var hostLayer))
			return hostLayer;
		return GetPreviewRenderLayer(vanilla);
	}

	private static bool TryGetBhUnitPreviewConfiguredLayer(object preview, out int unityLayer)
	{
		unityLayer = 0;
		var component = PreviewComponent(preview);
		if (!component)
			return false;
		try
		{
			var bh = component.GetComponentInParent<BhUnitPreview>();
			if (bh == null)
				return false;
			foreach (var pi in typeof(BhUnitPreview).GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
			{
				if (pi == null || !string.Equals(pi.Name, "layer", StringComparison.Ordinal) || pi.PropertyType != typeof(int))
					continue;
				var v = (int)pi.GetValue(bh);
				if (v < 0 || v > 31)
					continue;
				unityLayer = v;
				return true;
			}
		}
		catch
		{
			// ignored
		}

		return false;
	}

	private static void TryMoveInstanceToPreviewSceneLegacy(object preview, GameObject instance)
	{
		var component = PreviewComponent(preview);
		if (!component || !instance)
			return;
		try
		{
			var sc = component.gameObject.scene;
			if (!sc.IsValid() || !instance.scene.IsValid() || instance.scene.handle == sc.handle)
				return;
			SceneManager.MoveGameObjectToScene(instance, sc);
		}
		catch
		{
			// ignored
		}
	}

	private static void TryMoveInstanceToPreviewScene(object preview, GameObject instance)
	{
		if (!instance)
			return;
		try
		{
			var component = PreviewComponent(preview);
			var model = GetPreviewModel(preview);
			var rotatable = GetPreviewRotatable(preview);
			var anchor = component ? component.gameObject : model ? model : rotatable;
			if (!anchor)
				return;
			var sc = anchor.scene;
			if (!sc.IsValid() || !instance.scene.IsValid() || instance.scene.handle == sc.handle)
				return;
			SceneManager.MoveGameObjectToScene(instance, sc);
		}
		catch
		{
			// ignored
		}
	}

	/// <summary>
	/// Preview rigs are lit like the rest of the game; <c>Sprites/Default</c> billboards often read as invisible there.
	/// Clone <c>Hex/Lit</c> with the same main texture so the quad participates in the forward lighting path.
	/// </summary>
	private static void TryPromoteSpritesDefaultBillboardToHexLit(GameObject instance)
	{
		if (!instance)
			return;
		var lit = Shader.Find("Hex/Lit");
		if (!lit)
			return;
		foreach (var nd in instance.GetComponentsInChildren<MeshRenderer>(true))
		{
			if (!nd)
				continue;
			var m = nd.sharedMaterial;
			if (!m || !m.shader)
				continue;
			var sn = m.shader.name ?? string.Empty;
			if (sn.IndexOf("Sprites", StringComparison.OrdinalIgnoreCase) < 0)
				continue;
			var tex = m.mainTexture;
			var nm = new Material(lit)
			{
				name = "Homm3PreviewLit",
				hideFlags = HideFlags.HideAndDontSave
			};
			if (tex)
				nm.mainTexture = tex;
			if (m.HasProperty("_Color"))
				nm.color = m.color;
			SetCullOff(nm);
			nd.sharedMaterial = nm;
			break;
		}
	}

	private static int GetPreviewRenderLayer(GameObject vanilla)
	{
		if (!vanilla)
			return 0;
		var renderers = vanilla.GetComponentsInChildren<Renderer>(true);
		for (var i = 0; i < renderers.Length; i++)
		{
			var r = renderers[i];
			if (r != null && r.enabled)
				return r.gameObject.layer;
		}

		return vanilla.layer;
	}

	private static void ApplyLayerRecursive(Transform t, int layer)
	{
		if (t == null)
			return;
		t.gameObject.layer = layer;
		for (var i = 0; i < t.childCount; i++)
			ApplyLayerRecursive(t.GetChild(i), layer);
	}

	private static void TryPrepareOwnedSkinnedPreview(string key, GameObject instance, GameObject hexLitDonor = null)
	{
		if (!instance || !Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance))
			return;
		// Never hand our own (already replaced) model back in as the "native" material donor.
		if (hexLitDonor && (SameGameObject(hexLitDonor, instance) || Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(hexLitDonor)))
			hexLitDonor = null;
		if (Homm3ImportVisuals.TryResolveHomm3BattleEntryForUnitSid(key, Plugin.LogSource, out var bySid)
		    && bySid != null)
		{
			Homm3ImportVisuals.PrepareOwnedSkinnedIdleInstance(instance, bySid, Plugin.LogSource, hexLitDonor);
			return;
		}

		var unitsPath = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(key);
		if (Homm3ImportVisuals.TryResolveHomm3BattleEntry(unitsPath, Plugin.LogSource, out var byPath)
		    && byPath != null)
		{
			Homm3ImportVisuals.PrepareOwnedSkinnedIdleInstance(instance, byPath, Plugin.LogSource, hexLitDonor);
			return;
		}

		LogOwnedSkinnedPreviewRefused(key, "TryPrepareOwnedSkinnedPreview", "no homm3_import entry resolves this key; skinned instance left unprepared");
	}

	private static void ConfigurePreviewRenderers(GameObject instance)
	{
		if (!instance)
			return;
		var skinnedLane = Homm3ImportVisuals.IsHomm3SkinnedBattleInstance(instance);
		foreach (var r in instance.GetComponentsInChildren<Renderer>(true))
		{
			if (r == null)
				continue;
			r.enabled = true;
			if (!skinnedLane)
			{
				MakePreviewMaterialDoubleSided(r);
				r.sortingOrder = Math.Max(r.sortingOrder, 100);
			}
			if (r is MeshRenderer nd)
			{
				nd.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
				nd.receiveShadows = false;
			}
			else if (r is SkinnedMeshRenderer smr)
			{
				smr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
				smr.receiveShadows = false;
			}
		}
	}

	private static void MakePreviewMaterialDoubleSided(Renderer r)
	{
		if (r == null)
			return;
		var mats = r.sharedMaterials;
		if (mats == null || mats.Length == 0)
			return;
		var changed = false;
		for (var i = 0; i < mats.Length; i++)
		{
			var m = mats[i];
			if (!m)
				continue;
			if (!HasAnyCullProperty(m))
				continue;
			var clone = new Material(m)
			{
				name = "HOMM3_preview_double_sided_" + m.name,
				hideFlags = HideFlags.HideAndDontSave
			};
			SetCullOff(clone);
			ApplyPreviewOverlayRenderState(clone);
			mats[i] = clone;
			changed = true;
		}
		if (changed)
			r.sharedMaterials = mats;
	}

	private static void ApplyPreviewOverlayRenderState(Material m)
	{
		if (!m)
			return;
		m.renderQueue = 4000;
		if (m.HasProperty("_ZWrite"))
			m.SetFloat("_ZWrite", 0f);
		if (m.HasProperty("_ZTest"))
			m.SetFloat("_ZTest", (float)UnityEngine.Rendering.CompareFunction.Always);
	}

	private static bool HasAnyCullProperty(Material m)
	{
		return m
		       && (m.HasProperty("_Cull")
		           || m.HasProperty("_CullMode")
		           || m.HasProperty("_CullModeForward"));
	}

	private static void SetCullOff(Material m)
	{
		if (!m)
			return;
		if (m.HasProperty("_Cull"))
			m.SetFloat("_Cull", 0f);
		if (m.HasProperty("_CullMode"))
			m.SetFloat("_CullMode", 0f);
		if (m.HasProperty("_CullModeForward"))
			m.SetFloat("_CullModeForward", 0f);
	}

	private static bool TryGetBattleTemplate(string key, out GameObject template)
	{
		template = null;
		var unitsPath = EsquirePikemanVisuals.ToUnitsResPathFromSpawnPath(key);
		if (Homm3ImportVisuals.TryResolveHomm3BattleEntry(unitsPath, Plugin.LogSource, out var entry)
		    && entry != null
		    && Homm3ImportVisuals.TryGetBattleTemplate(entry, Plugin.LogSource, out template)
		    && template)
			return true;
		return Homm3ImportVisuals.TryGetBattleTemplateForUnitSid(key, Plugin.LogSource, out template);
	}

	private static void LogReplace(string source, string key, object preview, GameObject instance, GameObject vanilla, Renderer donor)
	{
		if (_loggedReflectedReplace >= 40)
			return;
		_loggedReflectedReplace++;
		var layer = instance ? instance.layer : -1;
		var rendererCount = instance ? instance.GetComponentsInChildren<Renderer>(true).Length : 0;
		var vanillaLayer = vanilla ? ResolvePreviewUnityLayer(preview, vanilla) : -1;
		var scale = instance ? instance.transform.localScale.ToString("F2") : "?";
		var rot = instance ? instance.transform.localEulerAngles.ToString("F1") : "?";
		Plugin.LogSource?.LogInfo(
			"Homm3Import unit preview model: replaced reflected model from "
			+ source
			+ " key='"
			+ key
			+ "' with '"
			+ (instance ? instance.name : "?")
			+ "' layer="
			+ layer
			+ " vanillaLayer="
			+ vanillaLayer
			+ " renderers="
			+ rendererCount
			+ " localScale="
			+ scale
			+ " localEuler="
			+ rot
			+ ".");
		Plugin.LogSource?.LogInfo(DescribePreviewWrapper(preview, donor));
		Plugin.LogSource?.LogInfo(EsquireBattleVisualPresentation.DescribeRenderTree("Homm3Import unit preview vanilla(before disable)", vanilla));
		Plugin.LogSource?.LogInfo(EsquireBattleVisualPresentation.DescribeRenderTree("Homm3Import unit preview custom(after presentation)", instance));
	}

	private static string DescribePreviewWrapper(object preview, Renderer donor)
	{
		if (preview == null)
			return "Homm3Import unit preview wrapper: (null)";
		var rotatable = GetPreviewRotatable(preview);
		var background = GetPreviewBackground(preview);
		var model = GetPreviewModel(preview);
		var rot = rotatable ? DescribeGo("rotatable", rotatable) : "rotatable=(null)";
		var bg = background ? DescribeRenderer("background", background) : "background=(null)";
		var modelText = model ? DescribeGo("model", model) : "model=(null)";
		var donorText = donor ? DescribeRenderer("donor", donor) : "donor=(null)";
		return "Homm3Import unit preview wrapper: type='"
		       + preview.GetType().FullName
		       + "' sid='"
		       + GetPreviewSid(preview)
		       + "' "
		       + rot
		       + " "
		       + bg
		       + " "
		       + modelText
		       + " "
		       + donorText;
	}

	private static string DescribeGo(string label, GameObject go)
	{
		if (!go)
			return label + "=(null)";
		return label
		       + " name='"
		       + go.name
		       + "' layer="
		       + go.layer
		       + " activeSelf="
		       + go.activeSelf
		       + " activeInHierarchy="
		       + go.activeInHierarchy
		       + " localPos="
		       + go.transform.localPosition.ToString("F2")
		       + " localEuler="
		       + go.transform.localEulerAngles.ToString("F1")
		       + " localScale="
		       + go.transform.localScale.ToString("F2")
		       + " worldPos="
		       + go.transform.position.ToString("F2");
	}

	private static string DescribeRenderer(string label, Renderer r)
	{
		if (!r)
			return label + "=(null)";
		var mat = r.sharedMaterial;
		var shader = mat && mat.shader ? mat.shader.name : "(null shader)";
		return label
		       + " type="
		       + r.GetType().Name
		       + " go='"
		       + r.gameObject.name
		       + "' enabled="
		       + r.enabled
		       + " layer="
		       + r.gameObject.layer
		       + " renderMask="
		       + r.renderingLayerMask
		       + " sort="
		       + r.sortingLayerName
		       + "/"
		       + r.sortingOrder
		       + " boundsCenter="
		       + r.bounds.center.ToString("F2")
		       + " boundsSize="
		       + r.bounds.size.ToString("F2")
		       + " mat="
		       + (mat ? mat.name : "(null)")
		       + " shader="
		       + shader;
	}
}
