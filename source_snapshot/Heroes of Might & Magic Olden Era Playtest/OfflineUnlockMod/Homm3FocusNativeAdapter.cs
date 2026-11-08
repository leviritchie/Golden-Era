using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Exact native adapter for Focus/Energy event payloads and hero ability energy
/// metadata. Source-prepared from June 18 decomp evidence. This class does not
/// register hooks, grant Focus, spend Focus, or normalize hero ability state.
/// </summary>
internal static class Homm3FocusNativeAdapter
{
	internal enum EnergyEventKind
	{
		Unknown = 0,
		EnergyUpdate = 1,
		EnergyUpdatedByMech = 2,
		SideUsedEnergy = 3,
	}

	internal readonly struct EnergyEventInfo
	{
		internal readonly EnergyEventKind Kind;
		internal readonly object Side;
		internal readonly int Delta;
		internal readonly int Energy;
		internal readonly object EnergyDistribution;
		internal readonly object ChangeType;

		internal EnergyEventInfo(EnergyEventKind kind, object side, int delta, int energy, object energyDistribution, object changeType)
		{
			Kind = kind;
			Side = side;
			Delta = delta;
			Energy = energy;
			EnergyDistribution = energyDistribution;
			ChangeType = changeType;
		}

		public override string ToString()
		{
			return "kind=" + Kind
			       + " side=" + DescribeObject(Side)
			       + " delta=" + Delta
			       + " energy=" + Energy
			       + " distribution=" + DescribeDistribution(EnergyDistribution)
			       + " changeType=" + FormatShortValue(ChangeType);
		}
	}

	internal readonly struct AbilityEnergyInfo
	{
		internal readonly string Summary;

		internal AbilityEnergyInfo(string summary)
		{
			Summary = summary;
		}

		public override string ToString()
		{
			return Summary ?? string.Empty;
		}
	}

	private static Type _energyUpdateEventArgsType;
	private static Type _energyUpdatedByMechEventArgsType;
	private static Type _sideUsedEnergyEventArgsType;
	private static Type _heroAbilityButtonViewType;
	private static Type _heroAbilityContainerViewType;
	private static Type _energyManagerType;
	private static MethodInfo _grantFocusMethod;
	private static MethodInfo _spendFocusMethod;
	private static bool _resolved;
	private static string _resolveFailure;

	internal static bool TryReadEnergyEvent(object eventArgs, out EnergyEventInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (eventArgs == null)
		{
			failReason = "energy event args are null";
			return false;
		}

		var type = eventArgs.GetType();
		if (_energyUpdateEventArgsType.IsInstanceOfType(eventArgs))
		{
			TryReadExactMember(eventArgs, type, GameSymbols.FocusLaws.EnergyUpdateSideMembers, out var side);
			TryReadIntMember(eventArgs, type, GameSymbols.FocusLaws.EnergyUpdateDeltaMembers, out var delta);
			TryReadIntMember(eventArgs, type, GameSymbols.FocusLaws.EnergyUpdateEnergyMembers, out var energy);
			TryReadExactMember(eventArgs, type, GameSymbols.FocusLaws.EnergyUpdateDistributionMembers, out var distribution);
			info = new EnergyEventInfo(EnergyEventKind.EnergyUpdate, side, delta, energy, distribution, null);
			failReason = null;
			return true;
		}

		if (_energyUpdatedByMechEventArgsType.IsInstanceOfType(eventArgs))
		{
			TryReadExactMember(eventArgs, type, GameSymbols.FocusLaws.EnergyUpdatedByMechSideMembers, out var side);
			TryReadExactMember(eventArgs, type, GameSymbols.FocusLaws.EnergyUpdatedByMechTypeMembers, out var changeType);
			TryReadIntMember(eventArgs, type, GameSymbols.FocusLaws.EnergyUpdatedByMechDeltaMembers, out var delta);
			info = new EnergyEventInfo(EnergyEventKind.EnergyUpdatedByMech, side, delta, 0, null, changeType);
			failReason = null;
			return true;
		}

		if (_sideUsedEnergyEventArgsType.IsInstanceOfType(eventArgs))
		{
			TryReadExactMember(eventArgs, type, GameSymbols.FocusLaws.SideUsedEnergySideMembers, out var side);
			TryReadIntMember(eventArgs, type, GameSymbols.FocusLaws.SideUsedEnergyDeltaMembers, out var delta);
			info = new EnergyEventInfo(EnergyEventKind.SideUsedEnergy, side, delta, 0, null, null);
			failReason = null;
			return true;
		}

		failReason = "event args are not a resolved Focus/Energy event type";
		return false;
	}

	internal static bool TryReadAbilityEnergyInfo(object abilityOrWrapper, out AbilityEnergyInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (abilityOrWrapper == null)
		{
			failReason = "ability or wrapper instance is null";
			return false;
		}

		var parts = new List<string>(16);
		AddExactMemberSnapshots(abilityOrWrapper, abilityOrWrapper.GetType(), GameSymbols.FocusLaws.AbilityEnergyMembers, parts, string.Empty);
		for (var i = 0; i < GameSymbols.FocusLaws.AbilityConfigMembers.Length; i++)
		{
			var configName = GameSymbols.FocusLaws.AbilityConfigMembers[i];
			if (!TryReadExactMember(abilityOrWrapper, abilityOrWrapper.GetType(), new[] { configName }, out var config) || config == null)
				continue;
			AddExactMemberSnapshots(config, config.GetType(), GameSymbols.FocusLaws.AbilityConfigEnergyMembers, parts, configName + ".");
		}

		if (parts.Count == 0)
		{
			failReason = "no exact ability energy members were found";
			return false;
		}

		info = new AbilityEnergyInfo(string.Join(";", parts));
		failReason = null;
		return true;
	}

	internal static bool TryGrantFocusToSide(object side, int delta, out string failReason)
	{
		if (delta <= 0)
		{
			failReason = "Focus grant delta must be positive";
			return false;
		}
		if (!TryResolve(out failReason))
			return false;
		if (side == null)
		{
			failReason = "Focus grant side is null";
			return false;
		}
		if (!TryReadExactMember(side, side.GetType(), GameSymbols.FocusLaws.SideEnergyManagerMembers, out var manager) || manager == null)
		{
			failReason = "Focus grant side has no exact energy manager member";
			return false;
		}
		if (!_energyManagerType.IsInstanceOfType(manager))
		{
			failReason = "Focus grant energy manager is not the resolved native eix type";
			return false;
		}
		_grantFocusMethod ??= ResolveExactVoidIntMethod(manager.GetType(), GameSymbols.FocusLaws.GrantEnergy.NameHints);
		if (_grantFocusMethod == null)
		{
			failReason = "Focus grant method bdwy(int) was not found on native energy manager";
			return false;
		}
		try
		{
			_grantFocusMethod.Invoke(manager, new object[] { delta });
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "Focus grant invocation failed: " + ex.Message;
			return false;
		}
	}

	internal static bool TrySpendFocusFromSide(object side, int amount, out string failReason)
	{
		if (amount <= 0)
		{
			failReason = "Focus spend amount must be positive";
			return false;
		}
		if (!TryResolve(out failReason))
			return false;
		if (side == null)
		{
			failReason = "Focus spend side is null";
			return false;
		}
		if (!TryReadExactMember(side, side.GetType(), GameSymbols.FocusLaws.SideEnergyManagerMembers, out var manager)
		    || manager == null
		    || !_energyManagerType.IsInstanceOfType(manager))
		{
			failReason = "Focus spend side has no exact native energy manager";
			return false;
		}
		_spendFocusMethod ??= ResolveExactVoidIntMethod(manager.GetType(), GameSymbols.DirectStateLaws.FocusSpend.NameHints);
		if (_spendFocusMethod == null)
		{
			failReason = "Focus spend method bdwx(int) was not found on native energy manager";
			return false;
		}
		try
		{
			// Native spend (eix.bdwx) takes a signed delta: its native callers pass -cost.
			_spendFocusMethod.Invoke(manager, new object[] { -amount });
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "Focus spend invocation failed: " + ex.GetBaseException().Message;
			return false;
		}
	}
	internal static bool TryDescribeFocusSurfaces(out string description, out string failReason)
	{
		description = null;
		if (!TryResolve(out failReason))
			return false;

		description =
			"energyUpdate=" + DescribeType(_energyUpdateEventArgsType)
			+ " energyUpdatedByMech=" + DescribeType(_energyUpdatedByMechEventArgsType)
			+ " sideUsedEnergy=" + DescribeType(_sideUsedEnergyEventArgsType)
			+ " energyManager=" + DescribeType(_energyManagerType)
			+ " heroAbilityButtonView=" + DescribeType(_heroAbilityButtonViewType)
			+ " heroAbilityContainerView=" + DescribeType(_heroAbilityContainerViewType);
		failReason = null;
		return true;
	}

	internal static bool TryResolve(out string failReason)
	{
		if (_resolved)
		{
			failReason = _resolveFailure;
			return _resolveFailure == null;
		}

		_resolved = true;
		_energyUpdateEventArgsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.FocusLawsEnergyUpdateEventArgs);
		_energyUpdatedByMechEventArgsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.FocusLawsEnergyUpdatedByMechEventArgs);
		_sideUsedEnergyEventArgsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.FocusLawsSideUsedEnergyEventArgs);
		_energyManagerType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.FocusLawsEnergyManager);
		_heroAbilityButtonViewType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.FocusLawsHeroAbilityButtonView);
		_heroAbilityContainerViewType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.FocusLawsHeroAbilityContainerView);

		if (_energyUpdateEventArgsType == null)
			return FailResolve("EnergyUpdateEventArgs type was not found", out failReason);
		if (_energyUpdatedByMechEventArgsType == null)
			return FailResolve("EnergyUpdatedByMechEventArgs type was not found", out failReason);
		if (_sideUsedEnergyEventArgsType == null)
			return FailResolve("SideUsedEnergyEventArgs type was not found", out failReason);
		if (_energyManagerType == null)
			return FailResolve("Focus/Energy manager type was not found", out failReason);
		if (_heroAbilityButtonViewType == null)
			return FailResolve("hero ability button view type was not found", out failReason);
		if (_heroAbilityContainerViewType == null)
			return FailResolve("hero ability container view type was not found", out failReason);

		failReason = null;
		return true;
	}

	private static bool FailResolve(string reason, out string failReason)
	{
		_resolveFailure = reason;
		failReason = reason;
		return false;
	}

	private static MethodInfo ResolveExactVoidIntMethod(Type type, string[] names)
	{
		if (type == null || names == null)
			return null;
		for (var i = 0; i < names.Length; i++)
		{
			var name = names[i];
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in AccessTools.GetDeclaredMethods(type))
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (method.IsSpecialName || method.ReturnType != typeof(void))
					continue;
				var parameters = method.GetParameters();
				if (parameters.Length == 1 && parameters[0].ParameterType == typeof(int))
					return method;
			}
		}
		return null;
	}
	private static void AddExactMemberSnapshots(object value, Type type, string[] names, List<string> parts, string prefix)
	{
		for (var i = 0; i < names.Length && parts.Count < 16; i++)
		{
			var name = names[i];
			if (TryReadExactMember(value, type, new[] { name }, out var raw))
				parts.Add(prefix + name + "=" + FormatShortValue(raw));
		}
	}

	private static bool TryReadIntMember(object value, Type type, string[] names, out int result)
	{
		result = 0;
		if (!TryReadExactMember(value, type, names, out var raw) || raw == null)
			return false;
		try
		{
			result = Convert.ToInt32(raw, System.Globalization.CultureInfo.InvariantCulture);
			return true;
		}
		catch
		{
			return false;
		}
	}

	private static bool TryReadExactMember(object value, Type type, string[] names, out object raw)
	{
		raw = null;
		if (value == null || type == null || names == null)
			return false;
		foreach (var name in names)
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			for (var current = type; current != null && current != typeof(object); current = current.BaseType)
			{
				const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
					{
						raw = field.GetValue(value);
						return true;
					}
				}
				catch
				{
				}
				try
				{
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
					{
						raw = property.GetValue(value, null);
						return true;
					}
				}
				catch
				{
				}
				try
				{
					var method = current.GetMethod(name, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
					{
						raw = method.Invoke(value, null);
						return true;
					}
				}
				catch
				{
				}
			}
		}
		return false;
	}

	private static string DescribeDistribution(object value)
	{
		if (value == null)
			return "null";
		if (value is not System.Collections.IEnumerable enumerable || value is string)
			return DescribeObject(value);
		var parts = new List<string>(8);
		var count = 0;
		foreach (var item in enumerable)
		{
			if (parts.Count < 8)
				parts.Add(FormatShortValue(item));
			count++;
			if (count > 64)
				break;
		}
		return "{count=" + count + ";sample=[" + string.Join(",", parts) + "]}";
	}

	private static string DescribeType(Type type)
	{
		return type?.FullName ?? "unresolved";
	}

	private static string DescribeObject(object value)
	{
		if (value == null)
			return "null";
		var type = value.GetType();
		return type.FullName ?? type.Name;
	}

	private static string FormatShortValue(object value)
	{
		if (value == null)
			return "null";
		var text = value.ToString();
		if (string.IsNullOrEmpty(text))
			text = "(empty)";
		return text.Length <= 80 ? text : text.Substring(0, 80) + "...";
	}
}
