using System;
using System.Collections;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Homecoming (and any map) can NRE mid-session load, then <c>OnScenesLoaded</c> again.
/// <c>QuestsSystem.Init</c> overwrites static <c>me</c> without deactivating the previous
/// instance's <c>ConStartTurn</c> listeners on <c>EventsDispatcher</c>, so StartTurn Dialogs
/// fire twice (Player.log: qi=2 nre=1 osc=2 → each homecoming_briefing_* Start ×2).
///
/// Prefix: deactivate previous <c>me</c> SubQuests (Condition.Deactivate → Unsubscribe)
/// before the new Init runs. Does not call Quest.Deactivate (that raises QuestComplited).
/// </summary>
internal static class Homm3QuestsSystemReinitGuard
{
	private const string LogPrefix = "HoMM3 QuestsSystem reinit guard";

	private static ManualLogSource _log;
	private static bool _registered;
	private static Type _questsSystemType;
	private static PropertyInfo _staticMeProperty;
	private static FieldInfo _staticMeField;
	private static int _deactivatedCount;
	private static int _loggedFail;

	internal static bool IsRegistered => _registered;

	internal static void TryRegister(Harmony harmony, ManualLogSource log)
	{
		if (_registered || harmony == null)
			return;

		_log = log;
		try
		{
			_questsSystemType = GameMember.FindType(
				GameSymbols.QuestsSystemReinit.QuestsSystemTypeId,
				GameSymbols.QuestsSystemReinit.QuestsSystemTypeHint,
				shapeFallback: ResolveQuestsSystemByShape);
			if (_questsSystemType == null)
				throw new InvalidOperationException("QuestsSystem type was not resolved.");

			ResolveStaticMeAccessor(_questsSystemType);
			var init = FindThreeArgInit(_questsSystemType);
			if (init == null)
				throw new InvalidOperationException("QuestsSystem.Init(Quests,Data,Counters) was not resolved.");

			harmony.Patch(
				init,
				prefix: new HarmonyMethod(typeof(Homm3QuestsSystemReinitGuard), nameof(PrefixInit)));
			_registered = true;
			_log?.LogInfo(
				LogPrefix
				+ ": patched "
				+ _questsSystemType.FullName
				+ "."
				+ init.Name
				+ " to deactivate orphaned SubQuests before re-Init.");
		}
		catch (Exception ex)
		{
			_log?.LogError(LogPrefix + ": registration failed closed: " + ex);
			throw;
		}
	}

	private static void PrefixInit(object __instance)
	{
		try
		{
			var previous = ReadStaticMe();
			if (previous == null || ReferenceEquals(previous, __instance))
				return;

			var deactivated = DeactivateOrphanedSubQuests(previous);
			_deactivatedCount += deactivated;
			_log?.LogWarning(
				LogPrefix
				+ ": deactivated orphaned QuestsSystem before re-Init subQuests="
				+ deactivated
				+ " totalDeactivations="
				+ _deactivatedCount
				+ " (map-load NRE reload left SideStartTurn listeners live).");
		}
		catch (Exception ex)
		{
			if (_loggedFail++ < 8)
				_log?.LogWarning(LogPrefix + ": orphan deactivate failed: " + ex.Message);
		}
	}

	private static Type ResolveQuestsSystemByShape()
	{
		foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
		{
			Type[] types;
			try { types = assembly.GetTypes(); }
			catch (ReflectionTypeLoadException ex) { types = ex.Types; }
			catch { continue; }
			if (types == null)
				continue;
			foreach (var type in types)
			{
				if (type == null || !type.IsClass)
					continue;
				if (FindThreeArgInit(type) == null)
					continue;
				if (!HasStaticSelfAccessor(type))
					continue;
				return type;
			}
		}
		return null;
	}

	private static bool HasStaticSelfAccessor(Type type)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		foreach (var prop in type.GetProperties(flags))
		{
			if (prop.PropertyType == type && prop.GetMethod != null)
				return true;
		}
		foreach (var field in type.GetFields(flags))
		{
			if (field.FieldType == type)
				return true;
		}
		return false;
	}

	private static MethodInfo FindThreeArgInit(Type type)
	{
		if (type == null)
			return null;
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly;
		MethodInfo[] methods;
		try { methods = type.GetMethods(flags); }
		catch { return null; }

		MethodInfo named = null;
		MethodInfo shaped = null;
		foreach (var method in methods)
		{
			if (method.ReturnType != typeof(bool))
				continue;
			var parameters = method.GetParameters();
			if (parameters.Length != 3)
				continue;
			if (!LooksLikeQuestScriptQuests(parameters[0].ParameterType))
				continue;
			if (!LooksLikeQuests2Data(parameters[1].ParameterType))
				continue;
			// 3rd arg is StoryHub campaign counters (ox / Counters).
			if (string.Equals(method.Name, "Init", StringComparison.Ordinal))
				named = method;
			else
				shaped ??= method;
		}
		return named ?? shaped;
	}

	private static bool LooksLikeQuestScriptQuests(Type type)
	{
		if (type == null)
			return false;
		var name = type.Name ?? "";
		var full = type.FullName ?? "";
		return name.IndexOf("Quest", StringComparison.OrdinalIgnoreCase) >= 0
		       || full.IndexOf("QuestScript", StringComparison.OrdinalIgnoreCase) >= 0;
	}

	private static bool LooksLikeQuests2Data(Type type)
	{
		if (type == null)
			return false;
		var full = type.FullName ?? "";
		var name = type.Name ?? "";
		return full.IndexOf("Quests2.Data", StringComparison.OrdinalIgnoreCase) >= 0
		       || string.Equals(name, "Data", StringComparison.Ordinal);
	}

	private static void ResolveStaticMeAccessor(Type type)
	{
		const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static;
		foreach (var hint in GameSymbols.QuestsSystemReinit.StaticMePropertyHints)
		{
			try
			{
				var prop = type.GetProperty(hint, flags);
				if (prop != null && prop.PropertyType == type && prop.GetMethod != null)
				{
					_staticMeProperty = prop;
					return;
				}
			}
			catch { /* continue */ }
		}
		foreach (var prop in type.GetProperties(flags))
		{
			if (prop.PropertyType == type && prop.GetMethod != null)
			{
				_staticMeProperty = prop;
				return;
			}
		}
		foreach (var field in type.GetFields(flags))
		{
			if (field.FieldType == type)
			{
				_staticMeField = field;
				return;
			}
		}
	}

	private static object ReadStaticMe()
	{
		if (_staticMeProperty != null)
			return _staticMeProperty.GetValue(null);
		if (_staticMeField != null)
			return _staticMeField.GetValue(null);
		return null;
	}

	private static int DeactivateOrphanedSubQuests(object questsSystem)
	{
		if (questsSystem == null)
			return 0;

		var logicQuests = ReadMember(
			questsSystem,
			GameSymbols.QuestsSystemReinit.LogicQuestsMemberHints);
		if (logicQuests == null)
			return 0;

		var questArray = ReadMember(
			logicQuests,
			GameSymbols.QuestsSystemReinit.QuestArrayMemberHints);
		var deactivated = 0;
		foreach (var quest in EnumerateObjects(questArray))
		{
			if (quest == null)
				continue;
			var subArray = ReadMember(
				quest,
				GameSymbols.QuestsSystemReinit.SubQuestArrayMemberHints);
			foreach (var subQuest in EnumerateObjects(subArray))
			{
				if (TryInvokeDeactivate(subQuest))
					deactivated++;
			}

			// Fallback: dictionary Values when array is empty/unreadable.
			if (subArray == null)
			{
				var subDict = ReadMember(
					quest,
					GameSymbols.QuestsSystemReinit.SubQuestDictMemberHints);
				foreach (var subQuest in EnumerateDictionaryValues(subDict))
				{
					if (TryInvokeDeactivate(subQuest))
						deactivated++;
				}
			}
		}
		return deactivated;
	}

	private static bool TryInvokeDeactivate(object target)
	{
		if (target == null)
			return false;
		var type = target.GetType();
		MethodInfo method = null;
		foreach (var hint in GameSymbols.QuestsSystemReinit.SubQuestDeactivateHints)
		{
			try
			{
				method = type.GetMethod(
					hint,
					BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance,
					null,
					Type.EmptyTypes,
					null);
			}
			catch { method = null; }
			if (method != null && method.ReturnType == typeof(void))
				break;
		}
		if (method == null)
		{
			foreach (var candidate in type.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
			{
				if (candidate.ReturnType != typeof(void))
					continue;
				if (candidate.GetParameters().Length != 0)
					continue;
				if (!string.Equals(candidate.Name, "Deactivate", StringComparison.Ordinal)
				    && candidate.Name.IndexOf("Deactivate", StringComparison.OrdinalIgnoreCase) < 0)
				{
					continue;
				}
				method = candidate;
				break;
			}
		}
		if (method == null)
			return false;
		method.Invoke(target, null);
		return true;
	}

	private static object ReadMember(object target, params string[] names)
	{
		if (target == null || names == null)
			return null;
		var type = target.GetType();
		const BindingFlags flags =
			BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
		foreach (var name in names)
		{
			if (string.IsNullOrEmpty(name))
				continue;
			try
			{
				var prop = type.GetProperty(name, flags);
				if (prop != null && prop.GetMethod != null)
					return prop.GetValue(target);
			}
			catch { /* continue */ }
			try
			{
				var field = type.GetField(name, flags);
				if (field != null)
					return field.GetValue(target);
			}
			catch { /* continue */ }
		}
		return null;
	}

	private static System.Collections.Generic.IEnumerable<object> EnumerateObjects(object container)
	{
		if (container == null)
			yield break;
		if (container is Array array)
		{
			for (var i = 0; i < array.Length; i++)
				yield return array.GetValue(i);
			yield break;
		}
		if (container is IEnumerable enumerable && container is not string)
		{
			foreach (var item in enumerable)
				yield return item;
			yield break;
		}
		// Il2Cpp arrays expose Length + indexer.
		var type = container.GetType();
		PropertyInfo lengthProp = null;
		try { lengthProp = type.GetProperty("Length", BindingFlags.Public | BindingFlags.Instance); }
		catch { /* ignore */ }
		PropertyInfo itemProp = null;
		try { itemProp = type.GetProperty("Item", BindingFlags.Public | BindingFlags.Instance); }
		catch { /* ignore */ }
		if (lengthProp == null || itemProp == null)
			yield break;
		int length;
		try { length = Convert.ToInt32(lengthProp.GetValue(container)); }
		catch { yield break; }
		for (var i = 0; i < length; i++)
		{
			object item;
			try { item = itemProp.GetValue(container, new object[] { i }); }
			catch { continue; }
			yield return item;
		}
	}

	private static System.Collections.Generic.IEnumerable<object> EnumerateDictionaryValues(object dict)
	{
		if (dict == null)
			yield break;
		object values;
		try
		{
			var valuesProp = dict.GetType().GetProperty("Values", BindingFlags.Public | BindingFlags.Instance);
			values = valuesProp?.GetValue(dict);
		}
		catch { yield break; }
		foreach (var item in EnumerateObjects(values))
			yield return item;
	}
}
