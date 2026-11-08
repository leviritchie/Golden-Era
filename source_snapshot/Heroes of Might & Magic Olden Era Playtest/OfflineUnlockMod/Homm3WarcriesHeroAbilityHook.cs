using System;
using System.Collections;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Hex.Configs;
using Il2CppInterop.Runtime.InteropTypes;
using UnityEngine;
using UnityEngine.UI;

namespace OfflineUnlockMod;

/// <summary>
/// Normalizes custom Stronghold Warcry hero abilities before native availability
/// checks build their UI wrappers.
/// </summary>
internal static class Homm3WarcriesHeroAbilityHook
{
	private static bool _patched;
	private static int _logged;
	private static int _bindLogged;
	private static int _bindSnapshotLogged;
	private static int _refreshLogged;
	private static int _refreshEmptyLogged;
	private static int _controllerLogged;
	private static int _controllerEmptyLogged;
	private static int _iconLogged;
	private static int _releaseObservedLogged;
	private static bool _heroAbilitiesMembersLogged;
	private static bool DiagnosticsEnabled => Homm3DiagnosticFlags.IsEnabled("homm3_warcry_hero_ability_diag.flag");

	internal static void TryRegister(Harmony h, ManualLogSource log)
	{
		if (_patched || h == null)
			return;

		log?.LogInfo("Homm3WarcriesHeroAbility legacy native-normalization hook skipped: stale pre-release hero ability path is quarantined.");
		_patched = true;
	}

	internal static void TryRegisterReleaseSafeIconSlice(Harmony h, ManualLogSource log)
	{
		RegisterReleaseSafeIconSlice(h, log, required: false);
	}

	internal static void RegisterRequiredReleaseSafeIconSlice(Harmony h, ManualLogSource log)
	{
		RegisterReleaseSafeIconSlice(h, log, required: true);
	}

	private static void RegisterReleaseSafeIconSlice(Harmony h, ManualLogSource log, bool required)
	{
		if (_patched || h == null)
		{
			if (required && h == null)
				throw new InvalidOperationException("Harmony was not initialized.");
			return;
		}

		var (buttonPatched, containerPatched, contextPatched) = TryPatchWarcryIconSurfaces(h, log);

		var patched = buttonPatched + containerPatched + contextPatched;
		if (patched == 0)
		{
			if (required)
				throw new InvalidOperationException("no release-safe warcry hero ability surfaces registered.");
			log?.LogWarning("Homm3WarcriesHeroAbility: no release-safe warcry hero ability surfaces registered.");
		}
		else
			log?.LogInfo("Homm3WarcriesHeroAbility: " + patched + " release-safe warcry hero ability surface(s) registered.");
		if (required && (buttonPatched == 0 || containerPatched == 0 || contextPatched == 0))
			throw new InvalidOperationException(
				"incomplete release-safe warcry hero ability registration: button="
				+ buttonPatched
				+ ", container="
				+ containerPatched
				+ ", context="
				+ contextPatched
				+ ".");
		if (required)
			ValidateRequiredReleaseWarcryIconSurface(log);
		_patched = true;
	}

	private static (int buttonPatched, int containerPatched, int contextPatched) TryPatchWarcryIconSurfaces(Harmony h, ManualLogSource log)
	{
		var buttonPatched = 0;
		var containerPatched = 0;
		var contextPatched = 0;

		var buttonType = FindRuntimeType("Hex.UI.BhHeroAbilitiyView");
		if (buttonType != null)
		{
			foreach (var method in GameMember.FindMethods(
			         buttonType,
			         typeof(void),
			         new Type[] { null, null },
			         GameSymbols.WarcryHeroAbility.PerAbilityBind))
			{
				if (!IsHeroAbilityButtonBindCandidate(method))
					continue;
				if (PatchWarcrySurface(h, log, method, nameof(PostfixReleaseHeroButtonBind)))
					buttonPatched++;
				break;
			}
		}
		else
			log?.LogWarning("Homm3WarcriesHeroAbility: release type not found: Hex.UI.BhHeroAbilitiyView");

		var containerType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.WarcryHeroAbilityHeroAbilitiesView);
		if (containerType != null)
		{
			foreach (var method in GameMember.FindMethods(
			         containerType,
			         typeof(void),
			         new Type[] { null, null },
			         GameSymbols.WarcryHeroAbility.ContainerBind))
			{
				if (!IsHeroAbilityContainerBindCandidate(method))
					continue;
				containerPatched += PatchWarcrySurface(h, log, method, nameof(PostfixReleaseHeroAbilityContainer)) ? 1 : 0;
			}

			foreach (var method in GameMember.FindMethods(
			         containerType,
			         typeof(void),
			         new Type[] { null, null, null },
			         GameSymbols.WarcryHeroAbility.ContainerBindWithArena))
			{
				if (!IsHeroAbilityContainerBindWithArenaCandidate(method))
					continue;
				containerPatched += PatchWarcrySurface(h, log, method, nameof(PostfixReleaseHeroAbilityContainer)) ? 1 : 0;
			}

			foreach (var method in GameMember.FindMethods(
			         containerType,
			         typeof(void),
			         new Type[] { null },
			         GameSymbols.WarcryHeroAbility.ContainerContextSet))
			{
				if (!IsHeroAbilityContainerContextCandidate(method))
					continue;
				if (PatchWarcrySurface(h, log, method, nameof(PostfixReleaseHeroAbilityContainer)))
					contextPatched++;
				break;
			}
		}
		else
			log?.LogWarning("Homm3WarcriesHeroAbility: release type not found: Hex.UI.BhHeroAbilitiesView");

		return (buttonPatched, containerPatched, contextPatched);
	}

	private static bool IsHeroAbilityButtonBindCandidate(MethodInfo method)
	{
		if (method == null || method.IsSpecialName)
			return false;
		var parameters = method.GetParameters();
		if (parameters.Length != 2)
			return false;
		if (parameters[0].ParameterType == typeof(bool) || parameters[1].ParameterType == typeof(bool))
			return false;
		if (parameters[0].ParameterType.IsSubclassOf(typeof(Delegate)) || parameters[1].ParameterType.IsSubclassOf(typeof(Delegate)))
			return false;
		return IsReleaseHeroAbilityWrapperTypeName(parameters[1].ParameterType.Name)
		       || IsReleaseHeroAbilityWrapperTypeName(parameters[1].ParameterType.FullName);
	}

	private static bool IsHeroAbilityContainerBindCandidate(MethodInfo method)
	{
		if (method == null || method.IsSpecialName)
			return false;
		if (MatchesMethodSymbolHint(method, GameSymbols.WarcryHeroAbility.ContainerBind))
			return true;
		var parameters = method.GetParameters();
		if (parameters.Length != 2)
			return false;
		if (TryGetListElementType(parameters[1].ParameterType, out var elementType))
		{
			return IsReleaseHeroAbilityTypeName(elementType.Name)
			       || string.Equals(elementType.FullName, "Hex.UI.BhHeroAbilitiyView", StringComparison.Ordinal);
		}
		var methodName = method.Name ?? string.Empty;
		return methodName.IndexOf("List_1_", StringComparison.Ordinal) >= 0
		       && methodName.IndexOf("ObjectPublicStInHeInObHecfObchcfUnique", StringComparison.Ordinal) >= 0;
	}

	private static bool IsHeroAbilityContainerBindWithArenaCandidate(MethodInfo method)
	{
		if (method == null || method.IsSpecialName)
			return false;
		var parameters = method.GetParameters();
		if (parameters.Length != 3)
			return false;
		if (TryGetListElementType(parameters[2].ParameterType, out var elementType))
			return IsReleaseHeroAbilityTypeName(elementType.Name);
		return MatchesMethodSymbolHint(method, GameSymbols.WarcryHeroAbility.ContainerBindWithArena);
	}

	private static bool MatchesMethodSymbolHint(MethodInfo method, GameSymbols.MethodSymbol symbol)
	{
		if (method == null || string.IsNullOrEmpty(symbol.Id))
			return false;
		var hints = symbol.NameHints;
		if (hints == null)
			return false;
		foreach (var hint in hints)
		{
			if (!string.IsNullOrEmpty(hint) && string.Equals(method.Name, hint, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static bool TryGetListElementType(Type type, out Type elementType)
	{
		elementType = null;
		if (type == null || !type.IsGenericType)
			return false;
		var args = type.GetGenericArguments();
		if (args == null || args.Length != 1)
			return false;
		var name = type.Name ?? string.Empty;
		if (!name.StartsWith("List`1", StringComparison.Ordinal))
		{
			try
			{
				var def = type.GetGenericTypeDefinition();
				if (def != typeof(List<>) && !string.Equals(def?.Name, "List`1", StringComparison.Ordinal))
					return false;
			}
			catch
			{
				return false;
			}
		}
		elementType = args[0];
		return true;
	}

	private static bool IsHeroAbilityContainerContextCandidate(MethodInfo method)
	{
		if (method == null || method.IsSpecialName)
			return false;
		if (MatchesMethodSymbolHint(method, GameSymbols.WarcryHeroAbility.ContainerContextSet))
			return true;
		var parameters = method.GetParameters();
		if (parameters.Length != 1)
			return false;
		return IsReleaseHeroAbilityTypeName(parameters[0].ParameterType.Name);
	}

	private static bool PatchWarcrySurface(Harmony h, ManualLogSource log, MethodInfo method, string postfixName)
	{
		if (method == null)
			return false;
		try
		{
			var postfix = typeof(Homm3WarcriesHeroAbilityHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(method, postfix, out var reason))
			{
				log?.LogWarning("Homm3WarcriesHeroAbility: refusing incompatible release postfix for " + FormatMethod(method) + ": " + reason);
				return false;
			}
			h.Patch(method, postfix: new HarmonyMethod(postfix));
			log?.LogInfo("Homm3WarcriesHeroAbility: release postfix registered on " + FormatMethod(method) + ".");
			return true;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3WarcriesHeroAbility: release patch failed for " + FormatMethod(method) + ": " + ex.Message);
			return false;
		}
	}

	private static bool IsReleaseHeroAbilityWrapperTypeName(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return false;
		foreach (var candidate in GameSymbols.WarcryHeroAbility.HeroAbilityWrapperTypeNames)
		{
			if (string.Equals(name, candidate, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static void ValidateRequiredReleaseWarcryIconSurface(ManualLogSource log)
	{
		var buttonType = FindRuntimeType("Hex.UI.BhHeroAbilitiyView");
		if (buttonType == null)
			throw new MissingMemberException("Hex.UI.BhHeroAbilitiyView", "type");
		if (!HasAnyMember(buttonType, GameSymbols.WarcryHeroAbility.HeroAbilityFields))
			throw new MissingMemberException(buttonType.FullName, string.Join("/", GameSymbols.WarcryHeroAbility.HeroAbilityFields));
		if (!HasAnyMember(buttonType, GameSymbols.WarcryHeroAbility.HeroAbilityWrapperFields))
			throw new MissingMemberException(buttonType.FullName, string.Join("/", GameSymbols.WarcryHeroAbility.HeroAbilityWrapperFields));

		var containerType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.WarcryHeroAbilityHeroAbilitiesView);
		if (containerType == null)
			throw new MissingMemberException("Hex.UI.BhHeroAbilitiesView", "type");
		// Every list the build scopes must exist. A list the scope drops (build 25509697 removed
		// separateHeroAbilities from the view) is a refusal sentinel, not a missing member.
		var requiredLists = 0;
		foreach (var listName in GameSymbols.WarcryHeroAbility.HeroAbilityViewListFields)
		{
			if (GameSymbolScope.IsSentinel(listName))
				continue;
			if (!HasAnyMember(containerType, new[] { listName }))
				throw new MissingMemberException(containerType.FullName, listName);
			requiredLists++;
		}
		if (requiredLists == 0)
			throw new MissingMemberException(containerType.FullName, "hero ability list fields");

		Type resolvedWrapperType = null;
		MethodInfo outGetter = null;
		foreach (var typeName in GameSymbols.WarcryHeroAbility.HeroAbilityWrapperTypeNames)
		{
			var wrapperType = FindRuntimeType(typeName);
			if (wrapperType == null)
				continue;
			outGetter = FindReleaseHeroAbilityOutGetter(wrapperType);
			if (outGetter == null)
				continue;
			resolvedWrapperType = wrapperType;
			break;
		}
		if (outGetter == null)
			throw new MissingMethodException(
				string.Join("/", GameSymbols.WarcryHeroAbility.HeroAbilityWrapperTypeNames),
				string.Join("/", GameSymbols.WarcryHeroAbility.HeroAbilityOutGetters));
		log?.LogInfo("Homm3WarcriesHeroAbility: release warcry member surface required; outGetter=" + outGetter.Name + " on " + resolvedWrapperType.FullName + ".");
	}

	private static bool HasAnyMember(Type type, string[] names)
	{
		if (type == null || names == null)
			return false;
		for (var current = type; current != null; current = current.BaseType)
		{
			foreach (var name in names)
			{
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					if (current.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static) != null)
						return true;
				}
				catch { }
				try
				{
					if (current.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static) != null)
						return true;
				}
				catch { }
			}
		}
		return false;
	}

	private static MethodInfo FindReleaseHeroAbilityOutGetter(Type wrapperType)
	{
		if (wrapperType == null)
			return null;
		foreach (var name in GameSymbols.WarcryHeroAbility.HeroAbilityOutGetters)
		{
			var method = FindMethodByName(wrapperType, name, 1);
			if (method == null || method.ReturnType != typeof(bool))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != 1)
				continue;
			if (parameters[0].ParameterType.IsByRef
			    && IsReleaseHeroAbilityTypeName(parameters[0].ParameterType.GetElementType()?.Name))
				return method;
			if (!parameters[0].ParameterType.IsByRef
			    && IsReleaseHeroAbilityWrapperTypeName(parameters[0].ParameterType.Name))
				return method;
		}
		return null;
	}

	private static bool IsReleaseHeroAbilityTypeName(string name)
	{
		if (string.IsNullOrWhiteSpace(name))
			return false;
		foreach (var candidate in GameSymbols.WarcryHeroAbility.HeroAbilityTypeNames)
		{
			if (string.Equals(name, candidate, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static int PatchReleaseMethod(Harmony h, ManualLogSource log, string typeName, string methodName, int parameterCount, string postfixName, bool warnIfMissing = true)
	{
		try
		{
			var type = FindRuntimeType(typeName);
			if (type == null)
			{
				if (warnIfMissing)
					log?.LogWarning("Homm3WarcriesHeroAbility: release type not found: " + typeName);
				return 0;
			}

			MethodInfo selected = null;
			foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
			{
				if (method.Name == methodName && method.GetParameters().Length == parameterCount)
				{
					selected = method;
					break;
				}
			}
			if (selected == null)
			{
				if (warnIfMissing)
					log?.LogWarning("Homm3WarcriesHeroAbility: release method not found: " + typeName + "." + methodName + "/" + parameterCount);
				return 0;
			}

			var postfix = typeof(Homm3WarcriesHeroAbilityHook).GetMethod(postfixName, BindingFlags.Static | BindingFlags.NonPublic);
			if (!GameMember.IsHarmonyPatchCompatible(selected, postfix, out var reason))
			{
				log?.LogWarning("Homm3WarcriesHeroAbility: refusing incompatible release postfix for " + (selected.DeclaringType?.FullName ?? typeName) + "." + selected.Name + ": " + reason);
				return 0;
			}
			h.Patch(selected, postfix: new HarmonyMethod(postfix));
			log?.LogInfo("Homm3WarcriesHeroAbility: release postfix registered on " + FormatMethod(selected) + ".");
			return 1;
		}
		catch (Exception ex)
		{
			log?.LogWarning("Homm3WarcriesHeroAbility: release patch failed for " + typeName + "." + methodName + ": " + ex.Message);
			return 0;
		}
	}

	private static ConstructorInfo FindLegacyAbilityWrapperConstructor()
	{
		foreach (var wrapperTypeName in GameSymbols.SelectedUnitHud.AbilityViewWrapperTypeNames)
		{
			var wrapperType = FindRuntimeType(wrapperTypeName);
			if (wrapperType == null)
				continue;
			foreach (var ctor in wrapperType.GetConstructors(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
			{
				var parameters = ctor.GetParameters();
				if (parameters.Length == 3
				    && parameters[1].ParameterType == typeof(bool)
				    && parameters[2].ParameterType == typeof(bool))
					return ctor;
			}
		}
		return null;
	}

	// Resolved through GameSymbols.TypeGroups: the type moved namespace on the live build, so a
	// compile-time `is Hex.UI.BhHeroAbilitiesView` would be an unresolved interop reference there.
	private static bool IsHeroAbilitiesView(object obj)
	{
		if (obj == null)
			return false;
		var viewType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.WarcryHeroAbilityHeroAbilitiesView);
		return viewType != null && viewType.IsInstanceOfType(obj);
	}

	private static Type FindRuntimeType(string fullName)
	{
		var type = ModActions.GetHexType(fullName);
		if (type != null)
			return type;
		foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
		{
			try
			{
				type = asm.GetType(fullName, false);
				if (type != null)
					return type;
			}
			catch { }
		}
		return null;
	}

	private static string FormatMethod(MethodBase method)
	{
		if (method == null)
			return "(null)";
		var parameters = method.GetParameters();
		var parts = new string[parameters.Length];
		for (var i = 0; i < parameters.Length; i++)
		{
			var p = parameters[i];
			parts[i] = (p.ParameterType != null ? p.ParameterType.Name : "?") + " " + p.Name;
		}
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name + "(" + string.Join(", ", parts) + ")";
	}

	private static void PostfixReleaseHeroButtonBind(object __instance, object[] __args)
	{
		var context = __args != null && __args.Length > 0 ? __args[0] : null;
		var carrier = __args != null && __args.Length > 1 ? __args[1] : null;
		var ability = TryGetReleaseWarcryAbility(__instance)
			?? TryGetReleaseWarcryAbility(carrier)
			?? TryGetReleaseWarcryAbility(context);
		LogReleaseWarcryObserved("release-button-bind", ability, __instance, carrier);
		ApplyWarcryHeroIcon(__instance, ability, "release-button-bind");
	}

	private static void PostfixReleaseHeroAbilityContainer(object __instance)
	{
		if (__instance == null)
			return;
		try
		{
			foreach (var view in EnumerateReleaseHeroAbilityViews(__instance))
			{
				var ability = TryGetReleaseWarcryAbility(view);
				LogReleaseWarcryObserved("release-container", ability, view, __instance);
				ApplyWarcryHeroIcon(view, ability, "release-container");
			}
		}
		catch { }
	}

	private static IEnumerable<object> EnumerateReleaseHeroAbilityViews(object root)
	{
		if (root == null)
			yield break;
		if (IsReleaseHeroAbilityView(root))
		{
			yield return root;
			yield break;
		}
		foreach (var fieldName in GameSymbols.WarcryHeroAbility.HeroAbilityViewListFields)
		{
			var list = TryGetMemberValue(root, fieldName);
			foreach (var item in EnumerateIl2CppList(list))
			{
				if (IsReleaseHeroAbilityView(item))
					yield return item;
			}
		}
	}

	private static bool IsReleaseHeroAbilityView(object obj)
	{
		if (obj == null)
			return false;
		return obj is Hex.UI.BhHeroAbilitiyView
			|| string.Equals(obj.GetType().FullName, "Hex.UI.BhHeroAbilitiyView", StringComparison.Ordinal);
	}

	private static void LogReleaseWarcryObserved(string source, object ability, object view, object carrier)
	{
		if (!DiagnosticsEnabled || ability == null || _releaseObservedLogged >= 64)
			return;

		var sid = TryExtractHeroIconOverrideSid(ability);
		if (!IsHeroIconOverrideSid(sid))
			return;

		_releaseObservedLogged++;
		Plugin.LogSource?.LogInfo(
			"Homm3WarcriesHeroAbility: observed release Warcry binding"
			+ " source='" + source + "'"
			+ " sid='" + sid + "'"
			+ " abilityType='" + ability.GetType().FullName + "'"
			+ " viewType='" + (view?.GetType().FullName ?? "<null>") + "'"
			+ " carrierType='" + (carrier?.GetType().FullName ?? "<null>") + "'.");
	}

	private static object TryGetReleaseWarcryAbility(object obj)
	{
		if (obj == null)
			return null;
		if (TryExtractHeroIconOverrideSid(obj) != null)
			return obj;

		foreach (var name in GameSymbols.WarcryHeroAbility.HeroAbilityFields)
		{
			var nested = TryGetMemberValue(obj, name);
			if (TryExtractHeroIconOverrideSid(nested) != null)
				return nested;
		}

		foreach (var name in GameSymbols.WarcryHeroAbility.HeroAbilityWrapperFields)
		{
			var nested = TryGetMemberValue(obj, name);
			var ability = TryGetReleaseWarcryAbility(nested);
			if (ability != null)
				return ability;
		}

		foreach (var methodName in GameSymbols.WarcryHeroAbility.HeroAbilityGetters)
		{
			var ability = TryInvokeReleaseAbilityGetter(obj, methodName);
			if (TryExtractHeroIconOverrideSid(ability) != null)
				return ability;
		}

		foreach (var methodName in GameSymbols.WarcryHeroAbility.HeroAbilityOutGetters)
		{
			var ability = TryInvokeReleaseAbilityOut(obj, methodName);
			if (TryExtractHeroIconOverrideSid(ability) != null)
				return ability;
		}

		return null;
	}

	private static object TryInvokeReleaseAbilityOut(object wrapper, string methodName)
	{
		if (wrapper == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		try
		{
			var method = FindMethodByName(wrapper.GetType(), methodName, 1);
			if (method == null)
				return null;
			var args = new object[] { null };
			var result = method.Invoke(wrapper, args);
			if (result is bool ok && !ok)
				return null;
			return args[0];
		}
		catch { return null; }
	}

	private static object TryInvokeReleaseAbilityGetter(object wrapper, string methodName)
	{
		if (wrapper == null || string.IsNullOrWhiteSpace(methodName))
			return null;
		try
		{
			var method = FindMethodByName(wrapper.GetType(), methodName, 0);
			if (method == null)
				return null;
			return method.Invoke(wrapper, Array.Empty<object>());
		}
		catch { return null; }
	}

	private static MethodInfo FindMethodByName(Type type, string name, int parameterCount)
	{
		if (type == null || string.IsNullOrWhiteSpace(name))
			return null;
		for (var current = type; current != null; current = current.BaseType)
		{
			MethodInfo[] methods;
			try
			{
				methods = current.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly);
			}
			catch
			{
				continue;
			}
			for (var i = 0; i < methods.Length; i++)
			{
				var method = methods[i];
				if (method != null && method.Name == name && method.GetParameters().Length == parameterCount)
					return method;
			}
		}
		return null;
	}

	private static string TryExtractReleaseSid(object ability)
	{
		return TryGetMemberValue(ability, "sid") as string
			?? TryGetMemberValue(ability, "id") as string
			?? TryGetMemberValue(ability, "<sid>k__BackingField") as string
			?? TryGetMemberValue(ability, "_sid_k__BackingField") as string
			?? TryGetMemberValue(ability, "prop_String_0") as string;
	}

	private static int PatchWarcryEnergyGetter(Harmony h, ManualLogSource log, string methodName)
	{
		return 0;
	}

	private static int PatchHeroRefreshDiagnostics(Harmony h, ManualLogSource log)
	{
		var viewType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.WarcryHeroAbilityHeroAbilitiesView);
		if (viewType == null)
		{
			log?.LogWarning("Homm3WarcriesHeroAbility: BhHeroAbilitiesView type unresolved; refresh diagnostics not patched.");
			return 0;
		}
		var patched = 0;
		foreach (var methodName in GameSymbols.WarcryHeroAbility.LegacyHeroViewRefreshDiagnostic.NameHints)
		{
			var method = AccessTools.Method(viewType, methodName);
			if (method == null)
				continue;
			h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3WarcriesHeroAbilityHook), nameof(PostfixHeroAbilityRefreshDiagnostic)));
			patched++;
		}

		if (patched == 0)
			log?.LogWarning("Homm3WarcriesHeroAbility: no BhHeroAbilitiesView refresh diagnostics patched.");
		return patched;
	}

	private static int PatchControllerDiagnostics(Harmony h, ManualLogSource log)
	{
		var controllerType = GameMember.FindType(
			GameSymbols.WarcryHeroAbility.LegacyControllerTypeId,
			GameSymbols.WarcryHeroAbility.LegacyControllerTypeHints[0]);
		if (controllerType == null)
		{
			log?.LogWarning("Homm3WarcriesHeroAbility: legacy controller type not found for diagnostics.");
			return 0;
		}

		var patched = 0;
		var diagnosticNames = new HashSet<string>(GameSymbols.WarcryHeroAbility.LegacyControllerDiagnostic.NameHints, StringComparer.Ordinal);
		foreach (var method in AccessTools.GetDeclaredMethods(controllerType))
		{
			if (method == null)
				continue;
			var name = method.Name;
			if (!diagnosticNames.Contains(name))
				continue;
			h.Patch(method, postfix: new HarmonyMethod(typeof(Homm3WarcriesHeroAbilityHook), nameof(PostfixControllerDiagnostic)));
			patched++;
		}

		if (patched == 0)
			log?.LogWarning("Homm3WarcriesHeroAbility: no legacy controller diagnostics patched.");
		return patched;
	}

	private static void PostfixHeroAbilityConstruct(object __instance)
	{
		NormalizeWarcry(__instance, "construct");
	}

	private static bool PrefixHeroAbilityAvailability(object __instance, ref bool __result)
	{
		if (!IsWarcryAbility(__instance))
			return true;

		NormalizeWarcry(__instance, "availability");
		__result = CanUseWarcryIgnoringFocus(__instance);
		LogNative("availability forced " + __result, __instance);
		return false;
	}

	private static void PostfixHeroAbilityEnergyGetter(object __instance, ref int __result)
	{
		if (!IsWarcryAbility(__instance))
			return;

		NormalizeWarcry(__instance, "energy-getter");
		if (__result != 0)
		{
			LogNative("energy getter forced from " + __result, __instance);
			__result = 0;
		}
	}

	private static void PrefixHeroAbilityListBuild(object __1)
	{
		NormalizeWarcryList(__1, "list-build");
	}

	private static void PostfixAbilityWrapperConstruct(object __instance, object __0, bool __1, bool __2)
	{
		var ability = TryGetWarcryAbility(__0);
		if (ability == null)
			return;

		NormalizeWarcry(ability, "wrapper-construct");
		ForceWrapperEnabled(__instance, ability, "wrapper-construct", __1, __2);
	}

	private static void PrefixHeroButtonBind(object __instance, object __1)
	{
		var ability = TryGetWarcryWrapperAbility(__1);
		LogButtonBind(__1, ability);
		if (ability == null)
			return;

		NormalizeWarcry(ability, "button-bind");
		ForceWrapperEnabled(__1, ability, "button-bind", GetBoolMember(__1, "cgci"), GetBoolMember(__1, "cgcj"));
		ForceHeroViewNativeGates(__instance, ability, "button-bind-prefix");
	}

	private static void PostfixHeroButtonBind(object __instance, object __1)
	{
		ApplyWarcryHeroIcon(__instance, TryGetWrappedAbility(__1), "button-bind");
		if (_bindSnapshotLogged >= 18)
			return;
		LogHeroViewSnapshot("rzt-post", __instance, __1);
	}

	private static void PostfixHeroAbilityRefreshDiagnostic(object __instance, MethodBase __originalMethod)
	{
		if (_refreshLogged >= 96)
			return;
		var methodName = __originalMethod != null ? __originalMethod.Name : "?";
		ApplyWarcryHeroIconsInContainer(__instance, "refresh-" + methodName);
		LogHeroContainerSnapshot("refresh-" + methodName, __instance);
	}

	private static void PostfixControllerDiagnostic(object __instance, MethodBase __originalMethod)
	{
		if (_controllerLogged >= 96)
			return;
		var methodName = __originalMethod != null ? __originalMethod.Name : "?";
		LogHeroContainerSnapshot("controller-" + methodName, __instance);
	}

	private static void NormalizeWarcry(object ability, string source)
	{
		if (!IsWarcryAbility(ability))
			return;
		try
		{
			SetIntMember(ability, "configEnergyLevel", 0);
			var config = TryGetMemberValue(ability, "config");
			if (config != null)
				SetIntMember(config, "energyLevel", 0);

			LogNormalize(source, ability, config);
		}
		catch (Exception ex)
		{
			if (_logged < 8)
			{
				_logged++;
				Plugin.LogSource?.LogWarning("Homm3WarcriesHeroAbility: native normalize failed: " + ex.Message);
			}
		}
	}

	private static bool CanUseWarcryIgnoringFocus(object ability)
	{
		if (ability == null)
			return false;

		var cd = GetIntMember(ability, "cd", 0);
		var casts = GetIntMember(ability, "castsPerBattleLeft", 1);
		var charges = GetIntMember(ability, "charges", 1);
		return cd <= 0 && casts != 0 && charges != 0;
	}

	private static void NormalizeWarcryList(object abilities, string source)
	{
		if (abilities == null)
			return;
		try
		{
			foreach (var ability in EnumerateIl2CppList(abilities))
			{
				if (IsWarcryAbility(ability))
					NormalizeWarcry(ability, source);
			}
		}
		catch (Exception ex)
		{
			if (_logged < 8)
			{
				_logged++;
				Plugin.LogSource?.LogWarning("Homm3WarcriesHeroAbility: list normalize failed: " + ex.Message);
			}
		}
	}

	private static void ForceWrapperEnabled(object wrapper, object ability, string source, bool originalEnabled, bool selected)
	{
		if (wrapper == null || ability == null)
			return;
		try
		{
			if (!CanUseWarcryIgnoringFocus(ability))
				return;
			if (!GetBoolMember(wrapper, "cgci"))
			{
				SetBoolMember(wrapper, "cgci", true);
				LogNative(source + " enabled wrapper from " + originalEnabled + " selected=" + selected, ability);
			}
		}
		catch (Exception ex)
		{
			if (_logged < 8)
			{
				_logged++;
				Plugin.LogSource?.LogWarning("Homm3WarcriesHeroAbility: wrapper enable failed: " + ex.Message);
			}
		}
	}

	private static bool IsWarcryAbility(object ability)
	{
		if (ability == null)
			return false;
		return IsWarcrySid(TryExtractSid(ability));
	}

	private static bool IsWarcrySid(string sid)
	{
		return string.Equals(sid, "skill_faction_homm3_stronghold_ability_moral", StringComparison.Ordinal)
			|| string.Equals(sid, "skill_faction_homm3_stronghold_ability_luck", StringComparison.Ordinal)
			|| string.Equals(sid, "skill_faction_homm3_stronghold_ability_initiative", StringComparison.Ordinal);
	}

	private static bool IsHeroIconOverrideSid(string sid)
	{
		return Homm3CustomHeroAbilityIconSpriteCache.HasIconForAbilitySid(sid);
	}

	private static bool TryGetHeroAbilityIconKey(object ability, string sid, out string iconKey)
	{
		iconKey = null;
		if (string.IsNullOrWhiteSpace(sid))
			return false;
		var level = GetIntMember(ability, "level", -1);
		return Homm3CustomHeroAbilityIconSpriteCache.TryGetIconKeyForAbility(sid, level, out iconKey);
	}

	private static bool IsComparedHeroAbilitySid(string sid)
	{
		if (IsWarcrySid(sid))
			return true;
		if (IsHeroIconOverrideSid(sid))
			return true;
		return !string.IsNullOrEmpty(sid)
			&& sid.StartsWith("skill_faction_dungeon_ability_", StringComparison.Ordinal);
	}

	private static object TryGetWarcryAbility(object ability)
	{
		if (ability == null)
			return null;
		return IsWarcryAbility(ability) ? ability : null;
	}

	private static object TryGetWarcryWrapperAbility(object wrapper)
	{
		if (wrapper == null)
			return null;
		try
		{
			var ability = TryGetWarcryAbility(TryGetMemberValue(wrapper, "cgch"));
			if (ability != null)
				return ability;
		}
		catch { }
		foreach (var methodName in GameSymbols.WarcryHeroAbility.HeroAbilityOutGetters)
		{
			var ability = TryGetWarcryAbility(TryInvokeReleaseAbilityOut(wrapper, methodName));
			if (ability != null)
				return ability;
		}
		return null;
	}

	private static object TryGetWrappedAbility(object wrapper)
	{
		if (wrapper == null)
			return null;
		try
		{
			var ability = TryGetMemberValue(wrapper, "cgch");
			if (ability != null)
				return ability;
		}
		catch { }
		var releaseAbility = TryGetReleaseWarcryAbility(wrapper);
		if (releaseAbility != null)
			return releaseAbility;
		return null;
	}

	private static string TryExtractSid(object ability)
	{
		if (ability == null)
			return null;
		try
		{
			var sid = TryExtractReleaseSid(ability);
			if (!string.IsNullOrWhiteSpace(sid))
				return sid;
		}
		catch { }
		return null;
	}

	private static void LogHeroContainerSnapshot(string source, object root)
	{
		try
		{
			var found = false;
			foreach (var view in EnumerateHeroViews(root, 3))
			{
				found = true;
				LogHeroViewSnapshot(source, view, TryGetViewWrapper(view));
			}
			if (!found)
				LogEmptyDiagnostic(source, root);
		}
		catch (Exception ex)
		{
			if (_refreshLogged < 8)
			{
				_refreshLogged++;
				Plugin.LogSource?.LogWarning("Homm3WarcriesHeroAbility: " + source + " diagnostic failed: " + ex.Message);
			}
		}
	}

	private static void ApplyWarcryHeroIconsInContainer(object root, string source)
	{
		if (root == null)
			return;
		try
		{
			foreach (var view in EnumerateHeroViews(root, 2))
			{
				var wrapper = TryGetViewWrapper(view);
				var iconAbility = TryGetWrappedAbility(wrapper);
				if (string.IsNullOrWhiteSpace(TryExtractSid(iconAbility)))
					iconAbility = TryGetViewAbility(view);
				ApplyWarcryHeroIcon(view, iconAbility, source);
				var ability = TryGetViewAbility(view);
				if (IsWarcryAbility(ability))
					ForceHeroViewNativeGates(view, ability, source);
			}
		}
		catch { }
	}

	private static void ForceHeroViewNativeGates(object view, object ability, string source)
	{
		if (view == null || !IsWarcryAbility(ability))
			return;
		try
		{
			if (!CanUseWarcryIgnoringFocus(ability))
				return;
			if (view is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
				return;

			var oldActive = Marshal.ReadByte(il2Cpp.Pointer, 0x4A) != 0;
			var oldClickEnabled = Marshal.ReadByte(il2Cpp.Pointer, 0x4B) != 0;
			if (!oldActive)
				Marshal.WriteByte(il2Cpp.Pointer, 0x4A, 1);
			if (!oldClickEnabled)
				Marshal.WriteByte(il2Cpp.Pointer, 0x4B, 1);
			if ((!oldActive || !oldClickEnabled) && DiagnosticsEnabled && _logged < 40)
			{
				_logged++;
				Plugin.LogSource?.LogInfo(
					"Homm3WarcriesHeroAbility: forced native hero view gates"
					+ " source='" + source + "'"
					+ " sid='" + TryExtractSid(ability) + "'"
					+ " bxgd " + oldActive + "->True"
					+ " bxge " + oldClickEnabled + "->True"
					+ ".");
			}
		}
		catch (Exception ex)
		{
			if (_logged < 40)
			{
				_logged++;
				Plugin.LogSource?.LogWarning("Homm3WarcriesHeroAbility: native hero view gate force failed: " + ex.Message);
			}
		}
	}

	private static void ApplyWarcryHeroIcon(object view, object ability, string source)
	{
		var sid = TryExtractHeroIconOverrideSid(ability);
		if (view == null || !IsHeroIconOverrideSid(sid))
			return;
		if (!TryGetHeroAbilityIconKey(ability, sid, out var iconKey) || string.IsNullOrWhiteSpace(iconKey))
			return;
		if (!Homm3CustomUiIconHook.TryResolveSprite(iconKey, out var sprite) || !sprite)
			return;

		try
		{
			var applied = ApplyExactHeroAbilityIconImages(view, sprite);
			if (applied > 0)
				LogWarcryIconApplied(source, sid, iconKey, sprite, applied);
		}
		catch (Exception ex)
		{
			if (_iconLogged < 8)
			{
				_iconLogged++;
				Plugin.LogSource?.LogWarning("Homm3WarcriesHeroAbility: hero icon apply failed: " + ex.Message);
			}
		}
	}

	private static string TryExtractHeroIconOverrideSid(object ability)
	{
		var sid = TryExtractSid(ability)
		          ?? TryExtractReleaseSid(ability)
		          ?? TryExtractHeroAbilitySidFromLevelConfig(ability);
		return IsHeroIconOverrideSid(sid) ? sid : null;
	}

	private static string TryExtractHeroAbilitySidFromLevelConfig(object ability)
	{
		var config = TryGetMemberValue(ability, "config");
		var name = TryGetMemberValue(config, "name") as string
		           ?? TryGetMemberValue(config, "<name>k__BackingField") as string;
		if (string.IsNullOrWhiteSpace(name) || !name.EndsWith("_name", StringComparison.Ordinal))
			return null;
		var sid = name.Substring(0, name.Length - "_name".Length);
		return IsHeroIconOverrideSid(sid) ? sid : null;
	}

	private static int ApplyExactHeroAbilityIconImages(object view, Sprite sprite)
	{
		if (view is not Component component || !component)
			throw new InvalidOperationException("custom hero ability icon view is not a Unity Component");

		var applied = 0;
		foreach (var path in new[] { "DISABLED ICON/ICON", "NORMAL ICON/ICON", "HOVER ICON/ICON" })
		{
			var child = component.transform.Find(path);
			var image = child != null ? child.GetComponent<Image>() : null;
			if (!image)
				throw new MissingMemberException("BhHeroAbilitiyView", path);
			if (EnsureWarcrySprite(image, sprite))
				applied++;
		}
		return applied;
	}
	private static bool EnsureWarcrySprite(Image image, Sprite sprite)
	{
		if (!image || !sprite)
			return false;
		var alreadyCorrect =
			image.sprite == sprite
			&& image.overrideSprite == sprite
			&& image.preserveAspect
			&& image.enabled
			&& image.color == Color.white
			&& (!image.gameObject || image.gameObject.activeSelf);
		if (alreadyCorrect)
			return true;
		image.sprite = sprite;
		image.overrideSprite = sprite;
		image.preserveAspect = true;
		image.enabled = true;
		image.color = Color.white;
		image.gameObject.SetActive(true);
		return true;
	}

	private static IEnumerable<object> EnumerateHeroViews(object root, int depth)
	{
		if (root == null || depth < 0)
			yield break;
		if (root is Hex.UI.BhHeroAbilitiyView)
		{
			yield return root;
			yield break;
		}
		if (IsHeroAbilitiesView(root))
		{
			foreach (var view in EnumerateKnownHeroAbilityLists(root))
				yield return view;
		}

		foreach (var field in GetInstanceFields(root.GetType()))
		{
			object value;
			try { value = field.GetValue(root); }
			catch { continue; }
			if (value == null)
				continue;
			if (value is Hex.UI.BhHeroAbilitiyView)
			{
				yield return value;
				continue;
			}

			if (depth == 0 || value is string)
				continue;
			if (value is IEnumerable enumerable)
			{
				foreach (var item in enumerable)
				{
					if (item == null)
						continue;
					if (item is Hex.UI.BhHeroAbilitiyView)
					{
						yield return item;
						continue;
					}
					foreach (var nested in EnumerateHeroViews(item, depth - 1))
						yield return nested;
				}
				continue;
			}

			var valueType = value.GetType();
			if (valueType.IsPrimitive || valueType.IsEnum || valueType == typeof(decimal))
				continue;
			foreach (var nested in EnumerateHeroViews(value, depth - 1))
				yield return nested;
		}
	}

	private static IEnumerable<object> EnumerateKnownHeroAbilityLists(object root)
	{
		LogHeroAbilitiesViewMembers(root);
		foreach (var fieldName in new[] { "heroAbilities", "separateHeroAbilities" })
		{
			var member = TryGetMemberValue(root, fieldName);
			if (member == null)
				continue;
			foreach (var item in EnumerateIl2CppList(member))
			{
				if (item is Hex.UI.BhHeroAbilitiyView)
					yield return item;
			}
		}
	}

	private static object TryGetMemberValue(object root, string memberName)
	{
		if (root == null)
			return null;
		for (var type = root.GetType(); type != null; type = type.BaseType)
		{
			try
			{
				var property = type.GetProperty(memberName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				if (property != null)
					return property.GetValue(root, null);
			}
			catch { }
			try
			{
				var field = type.GetField(memberName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				if (field != null)
					return field.GetValue(root);
			}
			catch { }
		}
		return null;
	}

	private static bool GetBoolMember(object root, string memberName)
	{
		try
		{
			var value = TryGetMemberValue(root, memberName);
			return value is bool flag && flag;
		}
		catch
		{
			return false;
		}
	}

	private static int GetIntMember(object root, string memberName, int fallback)
	{
		try
		{
			var value = TryGetMemberValue(root, memberName);
			return value != null ? Convert.ToInt32(value) : fallback;
		}
		catch
		{
			return fallback;
		}
	}

	private static void SetBoolMember(object root, string memberName, bool value)
	{
		if (root == null)
			return;
		for (var type = root.GetType(); type != null; type = type.BaseType)
		{
			try
			{
				var property = type.GetProperty(memberName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				if (property != null && property.PropertyType == typeof(bool) && property.CanWrite)
				{
					property.SetValue(root, value, null);
					return;
				}
			}
			catch { }
			try
			{
				var field = type.GetField(memberName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				if (field != null && field.FieldType == typeof(bool))
				{
					field.SetValue(root, value);
					return;
				}
			}
			catch { }
		}
	}

	private static void SetIntMember(object root, string memberName, int value)
	{
		if (root == null)
			return;
		for (var type = root.GetType(); type != null; type = type.BaseType)
		{
			try
			{
				var property = type.GetProperty(memberName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				if (property != null && property.CanWrite && property.PropertyType == typeof(int))
				{
					property.SetValue(root, value, null);
					return;
				}
			}
			catch { }
			try
			{
				var field = type.GetField(memberName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly);
				if (field != null && field.FieldType == typeof(int))
				{
					field.SetValue(root, value);
					return;
				}
			}
			catch { }
		}
	}

	private static bool IsKnownWrapperType(Type type)
	{
		if (type == null)
			return false;
		var name = type.Name;
		var fullName = type.FullName;
		foreach (var candidate in GameSymbols.SelectedUnitHud.AbilityWrapperTypeNames)
		{
			if (string.Equals(name, candidate, StringComparison.Ordinal)
			    || string.Equals(fullName, candidate, StringComparison.Ordinal))
				return true;
		}
		foreach (var candidate in GameSymbols.SelectedUnitHud.AbilityViewWrapperTypeNames)
		{
			if (string.Equals(name, candidate, StringComparison.Ordinal)
			    || string.Equals(fullName, candidate, StringComparison.Ordinal))
				return true;
		}
		foreach (var candidate in GameSymbols.WarcryHeroAbility.HeroAbilityWrapperTypeNames)
		{
			if (string.Equals(name, candidate, StringComparison.Ordinal)
			    || string.Equals(fullName, candidate, StringComparison.Ordinal))
				return true;
		}
		return false;
	}

	private static void LogHeroAbilitiesViewMembers(object root)
	{
		if (_heroAbilitiesMembersLogged || root == null)
			return;
		_heroAbilitiesMembersLogged = true;
		try
		{
			var type = root.GetType();
			var props = new List<string>();
			foreach (var property in type.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
			{
				if (property.PropertyType.FullName.IndexOf("BhHeroAbilit", StringComparison.Ordinal) >= 0
				    || property.PropertyType.FullName.IndexOf("List", StringComparison.Ordinal) >= 0
				    || property.Name.IndexOf("hero", StringComparison.OrdinalIgnoreCase) >= 0
				    || property.Name.StartsWith("bxf", StringComparison.Ordinal))
					props.Add(property.Name + ":" + property.PropertyType.FullName);
			}

			var fields = new List<string>();
			foreach (var field in type.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
			{
				if (field.FieldType.FullName.IndexOf("BhHeroAbilit", StringComparison.Ordinal) >= 0
				    || field.FieldType.FullName.IndexOf("List", StringComparison.Ordinal) >= 0
				    || field.Name.IndexOf("hero", StringComparison.OrdinalIgnoreCase) >= 0
				    || field.Name.StartsWith("bxf", StringComparison.Ordinal))
					fields.Add(field.Name + ":" + field.FieldType.FullName);
			}

			Plugin.LogSource?.LogInfo(
				"Homm3WarcriesHeroAbility: BhHeroAbilitiesView members"
				+ " props=[" + string.Join("; ", props) + "]"
				+ " fields=[" + string.Join("; ", fields) + "].");
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogWarning("Homm3WarcriesHeroAbility: member dump failed: " + ex.Message);
		}
	}

	private static IEnumerable<object> EnumerateIl2CppList(object list)
	{
		if (list == null)
			yield break;
		var type = list.GetType();
		var countProperty = type.GetProperty("Count", BindingFlags.Public | BindingFlags.Instance);
		var itemProperty = type.GetProperty("Item", BindingFlags.Public | BindingFlags.Instance);
		var getItem = itemProperty != null ? null : type.GetMethod("get_Item", BindingFlags.Public | BindingFlags.Instance);
		if (countProperty == null || (itemProperty == null && getItem == null))
			yield break;

		int count;
		try { count = Convert.ToInt32(countProperty.GetValue(list, null)); }
		catch { yield break; }
		for (var i = 0; i < count; i++)
		{
			object item = null;
			try
			{
				item = itemProperty != null
					? itemProperty.GetValue(list, new object[] { i })
					: getItem.Invoke(list, new object[] { i });
			}
			catch { }
			if (item != null)
				yield return item;
		}
	}

	private static object TryGetViewWrapper(object view)
	{
		if (view == null)
			return null;
		foreach (var memberName in GameSymbols.WarcryHeroAbility.HeroAbilityWrapperFields)
		{
			var wrapper = TryGetMemberValue(view, memberName);
			if (wrapper != null)
				return wrapper;
		}
		return null;
	}

	private static void LogHeroViewSnapshot(string source, object view, object wrapper)
	{
		if (view == null)
			return;
		var viewAbility = TryGetViewAbility(view);
		var sid = TryExtractSid(TryGetWrappedAbility(wrapper)) ?? TryExtractSid(viewAbility);
		if (!IsComparedHeroAbilitySid(sid))
			return;
		if (source.StartsWith("controller-", StringComparison.Ordinal))
		{
			if (_controllerLogged >= 96)
				return;
			_controllerLogged++;
		}
		else if (source == "rzt-post")
		{
			if (_bindSnapshotLogged >= 18)
				return;
			_bindSnapshotLogged++;
		}
		else
		{
			if (_refreshLogged >= 96)
				return;
			_refreshLogged++;
		}

		Plugin.LogSource?.LogInfo(
			"Homm3WarcriesHeroAbility: " + source
			+ " sid='" + sid + "'"
			+ " wrapperEnabled=" + GetBoolMember(wrapper, "cgci")
			+ " wrapperSelected=" + GetBoolMember(wrapper, "cgcj")
			+ " viewAbilityResolved=" + (viewAbility != null)
			+ " viewBools=" + DescribeBools(view)
			+ " nativeBools=" + DescribeNativeHeroViewBools(view)
			+ " canvas=" + DescribeCanvas(view)
			+ " viewBase=" + DescribeViewBase(view)
			+ ".");
	}

	private static object TryGetViewAbility(object view)
	{
		if (view == null)
			return null;
		foreach (var propertyName in GameSymbols.WarcryHeroAbility.LegacyHeroViewAbilityProperties)
		{
			try
			{
				var property = view.GetType().GetProperty(propertyName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
				var ability = property != null ? property.GetValue(view, null) : null;
				if (IsWarcryAbility(ability) || (ability != null && IsComparedHeroAbilitySid(TryExtractSid(ability))))
					return ability;
			}
			catch { }
		}
		try
		{
			var method = GameMember.FindFirstMethodByNames(
				view.GetType(),
				Type.EmptyTypes,
				GameSymbols.WarcryHeroAbility.LegacyHeroViewAbilityGetter);
			var ability = method != null ? method.Invoke(view, null) : null;
			if (IsWarcryAbility(ability) || (ability != null && IsComparedHeroAbilitySid(TryExtractSid(ability))))
				return ability;
		}
		catch { }
		foreach (var field in GetInstanceFields(view.GetType()))
		{
			if (!IsReleaseHeroAbilityTypeName(field.FieldType.Name))
				continue;
			try
			{
				var ability = field.GetValue(view);
				if (IsWarcryAbility(ability) || (ability != null && IsComparedHeroAbilitySid(TryExtractSid(ability))))
					return ability;
			}
			catch { }
		}
		return null;
	}

	private static void LogEmptyDiagnostic(string source, object root)
	{
		if (source.StartsWith("controller-", StringComparison.Ordinal))
		{
			if (_controllerEmptyLogged >= 24)
				return;
			_controllerEmptyLogged++;
		}
		else
		{
			if (_refreshEmptyLogged >= 24)
				return;
			_refreshEmptyLogged++;
		}

		Plugin.LogSource?.LogInfo(
			"Homm3WarcriesHeroAbility: " + source
			+ " fired; no compared hero ability view found"
			+ " rootType='" + (root != null ? root.GetType().FullName : "(null)") + "'.");
	}

	private static string DescribeBools(object obj)
	{
		if (obj == null)
			return "?";
		var parts = new List<string>();
		foreach (var field in GetInstanceFields(obj.GetType()))
		{
			if (field.FieldType != typeof(bool))
				continue;
			try { parts.Add(field.Name + "=" + (bool)field.GetValue(obj)); }
			catch { }
		}
		return parts.Count == 0 ? "(none)" : string.Join(",", parts);
	}

	private static string DescribeNativeHeroViewBools(object obj)
	{
		try
		{
			if (obj is not Il2CppObjectBase il2Cpp || il2Cpp.Pointer == IntPtr.Zero)
				return "(no-pointer)";

			// Native disassembly of BhHeroAbilitiyView shows the click callback gates on
			// these byte fields: +0x49 must be false, +0x4A and +0x4B must be true.
			return "bxgb@48=" + (Marshal.ReadByte(il2Cpp.Pointer, 0x48) != 0)
				+ ",bxgc@49=" + (Marshal.ReadByte(il2Cpp.Pointer, 0x49) != 0)
				+ ",bxgd@4A=" + (Marshal.ReadByte(il2Cpp.Pointer, 0x4A) != 0)
				+ ",bxge@4B=" + (Marshal.ReadByte(il2Cpp.Pointer, 0x4B) != 0);
		}
		catch (Exception ex)
		{
			return "(err:" + ex.GetType().Name + ")";
		}
	}

	private static string DescribeCanvas(object obj)
	{
		try
		{
			var component = obj as Component;
			if (component == null)
				return "(not-component)";
			var groups = component.GetComponentsInChildren<CanvasGroup>(true);
			if (groups == null || groups.Length == 0)
				return "(none)";
			var limit = Math.Min(groups.Length, 3);
			var parts = new List<string>();
			for (var i = 0; i < limit; i++)
			{
				var group = groups[i];
				if (group == null)
					continue;
				parts.Add("a=" + group.alpha.ToString("0.##")
					+ "/i=" + group.interactable
					+ "/b=" + group.blocksRaycasts);
			}
			return string.Join("|", parts);
		}
		catch
		{
			return "(err)";
		}
	}

	private static string DescribeViewBase(object heroView)
	{
		try
		{
			var viewBase = TryGetMemberValue(heroView, "viewBase");
			if (viewBase == null)
				return "(none)";

			var groups = new List<string>();
			foreach (var name in new[] { "hoverCg", "normalCg", "activeCg", "activeCg2", "cg", "cmjw" })
			{
				var group = TryGetMemberValue(viewBase, name) as CanvasGroup;
				if (group == null)
					continue;
				groups.Add(name + "=a" + group.alpha.ToString("0.##")
					+ "/i" + group.interactable
					+ "/b" + group.blocksRaycasts);
			}

			var imageParts = new List<string>();
			var pics = TryGetMemberValue(viewBase, "pics");
			foreach (var item in EnumerateIl2CppList(pics))
			{
				var image = item as Image;
				if (image == null)
					continue;
				imageParts.Add(DescribeImage(image));
				if (imageParts.Count >= 3)
					break;
			}
			if (imageParts.Count == 0 && viewBase is Component component)
			{
				var images = component.GetComponentsInChildren<Image>(true);
				var limit = Math.Min(images != null ? images.Length : 0, 3);
				for (var i = 0; i < limit; i++)
				{
					if (images[i] != null)
						imageParts.Add(DescribeImage(images[i]));
				}
			}

			return "groups[" + string.Join(",", groups) + "]"
				+ " images[" + string.Join("|", imageParts) + "]";
		}
		catch
		{
			return "(err)";
		}
	}

	private static string DescribeImage(Image image)
	{
		try
		{
			var color = image.color;
			var spriteName = image.sprite != null ? image.sprite.name : "(no-sprite)";
			return image.name
				+ ":rgba(" + color.r.ToString("0.##")
				+ "," + color.g.ToString("0.##")
				+ "," + color.b.ToString("0.##")
				+ "," + color.a.ToString("0.##")
				+ "):enabled=" + image.enabled
				+ ":sprite=" + spriteName;
		}
		catch
		{
			return "(image-err)";
		}
	}

	private static IEnumerable<FieldInfo> GetInstanceFields(Type type)
	{
		for (var current = type; current != null; current = current.BaseType)
		{
			FieldInfo[] fields;
			try
			{
				fields = current.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
			}
			catch
			{
				continue;
			}
			foreach (var field in fields)
				yield return field;
		}
	}

	private static void LogButtonBind(object wrapper, object ability)
	{
		if (!DiagnosticsEnabled)
			return;
		if (_bindLogged >= 36)
			return;
		try
		{
			var wrapped = TryGetWrappedAbility(wrapper);
			var sid = ability != null ? TryExtractSid(ability) : TryExtractSid(wrapped);
			if (ability == null && !IsWarcrySid(sid))
				return;

			_bindLogged++;
			Plugin.LogSource?.LogInfo(
				"Homm3WarcriesHeroAbility: button-bind observed"
				+ " sid='" + (sid ?? "?") + "'"
				+ " wrapperEnabled=" + GetBoolMember(wrapper, "cgci")
				+ " wrapperSelected=" + GetBoolMember(wrapper, "cgcj")
				+ " wrappedType='" + (wrapped != null ? wrapped.GetType().FullName : "(null)") + "'"
				+ " abilityResolved=" + (ability != null)
				+ ".");
		}
		catch { }
	}

	private static void LogNormalize(string source, object ability, object config)
	{
		if (!DiagnosticsEnabled)
			return;
		if (_logged >= 18)
			return;
		_logged++;
		try
		{
			Plugin.LogSource?.LogInfo(
				"Homm3WarcriesHeroAbility: normalized " + source
				+ " sid='" + (ability != null ? TryExtractSid(ability) : "?") + "'"
				+ " level=" + GetIntMember(ability, "level", -1)
				+ " configEnergy=" + GetIntMember(ability, "configEnergyLevel", -1)
				+ " configDontUseEnergy=" + GetBoolMember(config, "dontUseEnergy")
				+ ".");
		}
		catch { }
	}

	private static void LogNative(string source, object ability)
	{
		if (!DiagnosticsEnabled)
			return;
		if (_logged >= 28)
			return;
		_logged++;
		try
		{
			Plugin.LogSource?.LogInfo(
				"Homm3WarcriesHeroAbility: " + source
				+ " sid='" + (ability != null ? TryExtractSid(ability) : "?") + "'"
				+ " cd=" + GetIntMember(ability, "cd", -1)
				+ " configCd=" + GetIntMember(ability, "configCd", -1)
				+ " charges=" + GetIntMember(ability, "charges", -1)
				+ " casts=" + GetIntMember(ability, "castsPerBattleLeft", -2)
				+ " energyField=" + GetIntMember(ability, "configEnergyLevel", -1)
				+ ".");
		}
		catch { }
	}

	private static void LogWarcryIconApplied(string source, string sid, string iconKey, Sprite sprite, int count)
	{
		if (!DiagnosticsEnabled)
			return;
		if (_iconLogged >= 12)
			return;
		_iconLogged++;
		try
		{
			Plugin.LogSource?.LogInfo(
				"Homm3WarcriesHeroAbility: hero icon applied"
				+ " source='" + source + "'"
				+ " sid='" + (sid ?? "?") + "'"
				+ " icon='" + (iconKey ?? "?") + "'"
				+ " sprite='" + (sprite ? sprite.name : "(null)") + "'"
				+ " images=" + count
				+ ".");
		}
		catch { }
	}
}
