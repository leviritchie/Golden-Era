using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Exact native adapter for reward/economy data surfaces.
/// Source-prepared from June 18 decomp/live-bridge evidence. This class does
/// not locate reward ownership or authorize grants; future law handlers must
/// still prove source identity and idempotence before calling mutation helpers.
/// </summary>
internal static class Homm3RewardEconomyNativeAdapter
{
	internal readonly struct ResourceIdentityInfo
	{
		internal readonly string Name;
		internal readonly int Value;

		internal ResourceIdentityInfo(string name, int value)
		{
			Name = name;
			Value = value;
		}

		public override string ToString()
		{
			return "name=" + (Name ?? "null") + " value=" + Value;
		}
	}

	internal readonly struct RewardSetIdentityInfo
	{
		internal readonly int Id;
		internal readonly int HeroId;
		internal readonly int ObjectId;
		internal readonly string Label;
		internal readonly string ShowType;
		internal readonly string ApplyType;
		internal readonly string CancelType;
		internal readonly int RewardCount;
		internal readonly string RewardSummary;

		internal RewardSetIdentityInfo(
			int id,
			int heroId,
			int objectId,
			string label,
			string showType,
			string applyType,
			string cancelType,
			int rewardCount,
			string rewardSummary)
		{
			Id = id;
			HeroId = heroId;
			ObjectId = objectId;
			Label = label;
			ShowType = showType;
			ApplyType = applyType;
			CancelType = cancelType;
			RewardCount = rewardCount;
			RewardSummary = rewardSummary;
		}

		public override string ToString()
		{
			return "id=" + Id
			       + " heroId=" + HeroId
			       + " objectId=" + ObjectId
			       + " label=" + (Label ?? "null")
			       + " showType=" + (ShowType ?? "null")
			       + " applyType=" + (ApplyType ?? "null")
			       + " cancelType=" + (CancelType ?? "null")
			       + " rewardCount=" + RewardCount
			       + " rewardSummary=[" + (RewardSummary ?? "") + "]";
		}
	}

	private static Type _resourceDataType;
	private static Type _resourceWrapperType;
	private static Type _resHeapDataType;
	private static Type _dataRewardSetsType;
	private static Type _rewardApplierType;
	private static MethodInfo _resourceSetValue;
	private static MethodInfo _resourceAddValue;
	private static MethodInfo _resourceSpendIfAvailable;
	private static MethodInfo _resourceHasAtLeast;
	private static MethodInfo _resHeapApply;
	private static MethodInfo _rewardSetQueued;
	private static MethodInfo _rewardSetRemoved;
	private static MethodInfo _rewardSetApply;
	private static bool _resolved;
	private static string _resolveFailure;

	internal static bool TrySetResourceValue(object resource, int value, out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateResource(resource, out failReason))
			return false;
		if (_resourceSetValue == null)
		{
			failReason = "resource set method is unresolved";
			return false;
		}

		return TryInvokeVoid(_resourceSetValue, resource, new object[] { value }, "resource set", out failReason);
	}

	internal static bool TryRequireGoldResource(object resource, out ResourceIdentityInfo info, out string failReason)
	{
		if (!TryReadResourceIdentity(resource, out info, out failReason))
			return false;
		if (string.Equals(info.Name, GameSymbols.EconomyLaws.GoldResourceName, StringComparison.OrdinalIgnoreCase))
			return true;
		failReason = "resource is not gold: " + (info.Name ?? "null");
		return false;
	}

	internal static bool TryResolveGoldResourceFromSide(object sideOrResHeap, out object goldResource, out ResourceIdentityInfo info, out string failReason)
	{
		if (!TryResolveResourceFromSide(sideOrResHeap, GameSymbols.EconomyLaws.GoldResourceName, out goldResource, out info, out failReason))
			return false;
		return TryRequireGoldResource(goldResource, out info, out failReason);
	}

	internal static bool TryResolveResourceFromSide(object sideOrResHeap, string resourceName, out object resource, out ResourceIdentityInfo info, out string failReason)
	{
		resource = null;
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (sideOrResHeap == null)
		{
			failReason = "side or resource heap instance is null";
			return false;
		}
		if (!TryGetResHeapResourceMembers(resourceName, out var canonicalName, out var resourceMembers))
		{
			failReason = "unsupported exact resource name '" + (resourceName ?? "null") + "'";
			return false;
		}

		object resHeap = sideOrResHeap;
		if (_resHeapDataType == null || !_resHeapDataType.IsInstanceOfType(resHeap))
		{
			resHeap = ReadFirstExactMember(sideOrResHeap, sideOrResHeap.GetType(), GameSymbols.EconomyLaws.SideResourceMembers);
			if (resHeap == null)
			{
				failReason = "side did not expose exact ResHeap";
				return false;
			}
			if (_resHeapDataType == null || !_resHeapDataType.IsInstanceOfType(resHeap))
			{
				failReason = "side resource member is not a resolved ResHeap instance";
				return false;
			}
		}

		resource = ReadFirstExactMember(resHeap, resHeap.GetType(), resourceMembers);
		if (resource == null)
		{
			failReason = "ResHeap did not expose exact " + canonicalName + " Resource";
			return false;
		}
		if (!TryReadResourceIdentity(resource, out info, out failReason))
			return false;
		if (!string.Equals(info.Name, canonicalName, StringComparison.Ordinal))
		{
			failReason = "resource identity mismatch for exact field " + canonicalName + ": " + (info.Name ?? "null");
			return false;
		}
		return true;
	}

	private static bool TryGetResHeapResourceMembers(string resourceName, out string canonicalName, out string[] members)
	{
		canonicalName = null;
		members = null;
		switch (resourceName)
		{
			case "gold": canonicalName = "gold"; members = GameSymbols.EconomyLaws.ResHeapGoldMembers; return true;
			case "wood": canonicalName = "wood"; members = GameSymbols.EconomyLaws.ResHeapWoodMembers; return true;
			case "ore": canonicalName = "ore"; members = GameSymbols.EconomyLaws.ResHeapOreMembers; return true;
			case "gemstones": canonicalName = "gemstones"; members = GameSymbols.EconomyLaws.ResHeapGemstonesMembers; return true;
			case "crystals": canonicalName = "crystals"; members = GameSymbols.EconomyLaws.ResHeapCrystalsMembers; return true;
			case "mercury": canonicalName = "mercury"; members = GameSymbols.EconomyLaws.ResHeapMercuryMembers; return true;
			case "dust": canonicalName = "dust"; members = GameSymbols.EconomyLaws.ResHeapDustMembers; return true;
			case "graal": canonicalName = "graal"; members = GameSymbols.EconomyLaws.ResHeapGraalMembers; return true;
			case "starDust": canonicalName = "starDust"; members = GameSymbols.EconomyLaws.ResHeapStarDustMembers; return true;
			default: return false;
		}
	}
	internal static bool TryReadResourceIdentity(object resource, out ResourceIdentityInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateResource(resource, out failReason))
			return false;

		var type = resource.GetType();
		var name = ReadStringMember(resource, type, GameSymbols.EconomyLaws.ResourceNameMembers);
		if (string.IsNullOrWhiteSpace(name))
		{
			failReason = "resource name was not resolved from exact Resource members";
			return false;
		}
		if (!TryReadIntMember(resource, type, GameSymbols.EconomyLaws.ResourceValueMembers, out var value))
		{
			failReason = "resource value was not resolved from exact Resource members";
			return false;
		}

		info = new ResourceIdentityInfo(name, value);
		failReason = null;
		return true;
	}

	internal static bool TryReadRewardSetIdentity(object rewardSet, out RewardSetIdentityInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (rewardSet == null)
		{
			failReason = "reward set instance is null";
			return false;
		}
		var type = rewardSet.GetType();
		if (!TypeNameLooksLike(type, "DataRewardSet"))
		{
			failReason = "object is not a DataRewardSet-shaped reward set";
			return false;
		}

		if (!TryReadIntMember(rewardSet, type, GameSymbols.RewardCommitLaws.RewardSetIdMembers, out var id))
		{
			failReason = "reward set id was not resolved";
			return false;
		}
		if (!TryReadIntMember(rewardSet, type, GameSymbols.RewardCommitLaws.RewardSetHeroIdMembers, out var heroId))
		{
			failReason = "reward set heroId was not resolved";
			return false;
		}
		if (!TryReadIntMember(rewardSet, type, GameSymbols.RewardCommitLaws.RewardSetObjectIdMembers, out var objectId))
		{
			failReason = "reward set objectId was not resolved";
			return false;
		}

		var label = ReadStringMember(rewardSet, type, GameSymbols.RewardCommitLaws.RewardSetLabelMembers);
		var showType = ReadShortMember(rewardSet, type, GameSymbols.RewardCommitLaws.RewardSetShowTypeMembers);
		var applyType = ReadShortMember(rewardSet, type, GameSymbols.RewardCommitLaws.RewardSetApplyTypeMembers);
		var cancelType = ReadShortMember(rewardSet, type, GameSymbols.RewardCommitLaws.RewardSetCancelTypeMembers);
		var rewards = ReadFirstExactMember(rewardSet, type, GameSymbols.RewardCommitLaws.RewardSetRewardsMembers);
		if (rewards == null)
		{
			failReason = "reward set rewards list was not resolved";
			return false;
		}

		var rewardCount = CountEnumerable(rewards, out var summary);
		info = new RewardSetIdentityInfo(id, heroId, objectId, label, showType, applyType, cancelType, rewardCount, summary);
		failReason = null;
		return true;
	}

	internal static bool TryAddResourceValue(object resource, int amount, out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateResource(resource, out failReason))
			return false;
		if (_resourceAddValue == null)
		{
			failReason = "resource add method is unresolved";
			return false;
		}

		return TryInvokeVoid(_resourceAddValue, resource, new object[] { amount }, "resource add", out failReason);
	}

	internal static bool TrySpendResourceIfAvailableFromWrapper(object resourceWrapper, string resourceName, int amount, out bool spent, out string failReason)
	{
		spent = false;
		if (!TryResolve(out failReason))
			return false;
		if (resourceWrapper == null)
		{
			failReason = "resource wrapper instance is null";
			return false;
		}
		if (_resourceWrapperType == null || !_resourceWrapperType.IsInstanceOfType(resourceWrapper))
		{
			failReason = "object is not a resolved resource wrapper instance";
			return false;
		}
		if (string.IsNullOrWhiteSpace(resourceName))
		{
			failReason = "resource spend name is empty";
			return false;
		}
		if (amount <= 0)
		{
			failReason = "resource spend amount must be positive";
			return false;
		}
		if (_resourceSpendIfAvailable == null)
		{
			failReason = "resource spend-if-available wrapper method is unresolved";
			return false;
		}

		return TryInvokeBool(_resourceSpendIfAvailable, resourceWrapper, new object[] { resourceName, amount }, "resource spend-if-available wrapper", out spent, out failReason);
	}

	internal static bool TrySubtractResourceIfAvailable(object resource, int amount, out bool subtracted, out string failReason)
	{
		subtracted = false;
		failReason = "direct Resource.bggw subtract-if-available is rejected: June 20 runtime construction proof showed patching this tiny primitive crashes at GameAssembly+0x210d7ae. Use TrySpendResourceIfAvailableFromWrapper/dti.ymk instead.";
		return false;
	}

	internal static bool TryResourceHasAtLeast(object resource, int amount, out bool hasEnough, out string failReason)
	{
		hasEnough = false;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateResource(resource, out failReason))
			return false;
		if (_resourceHasAtLeast == null)
		{
			failReason = "resource has-at-least method is unresolved";
			return false;
		}

		return TryInvokeBool(_resourceHasAtLeast, resource, new object[] { amount }, "resource has-at-least", out hasEnough, out failReason);
	}

	internal static bool TryDescribeRewardLifecycleSurfaces(out string description, out string failReason)
	{
		description = null;
		if (!TryResolve(out failReason))
			return false;

		description =
			"dataRewardSetsType=" + DescribeType(_dataRewardSetsType)
			+ " queue=" + DescribeMethod(_rewardSetQueued)
			+ " remove=" + DescribeMethod(_rewardSetRemoved)
			+ " rewardApplierType=" + DescribeType(_rewardApplierType)
			+ " apply=" + DescribeMethod(_rewardSetApply)
			+ " resHeapType=" + DescribeType(_resHeapDataType)
						+ " resourceSpendWrapper=" + DescribeMethod(_resourceSpendIfAvailable)
+ " resHeapApply=" + DescribeMethod(_resHeapApply);
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
		_resourceDataType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.EconomyLawsResourceData);
		_resourceWrapperType = GameMember.FindType(
			GameSymbols.EconomyLaws.ResourceWrapperTypeId,
			GameSymbols.EconomyLaws.ResourceWrapperTypeHint);
		_resHeapDataType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.EconomyLawsResHeapData);
		_dataRewardSetsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.RewardCommitLawsDataRewardSets);
		_rewardApplierType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.RewardCommitLawsRewardApplier);

		if (_resourceDataType == null)
			return FailResolve("Resource data type was not found", out failReason);
		if (_resourceWrapperType == null)
			return FailResolve("Resource wrapper type was not found", out failReason);
		if (_dataRewardSetsType == null)
			return FailResolve("DataRewardSets type was not found", out failReason);

		_resourceSetValue = ResolveExactMethod(
			_resourceDataType,
			GameSymbols.EconomyLaws.ResourceSetValue.NameHints,
			typeof(void),
			new[] { "Int32" });
		_resourceAddValue = ResolveExactMethod(
			_resourceDataType,
			GameSymbols.EconomyLaws.ResourceAddValue.NameHints,
			typeof(void),
			new[] { "Int32" });
		_resourceSpendIfAvailable = ResolveExactMethod(
			_resourceWrapperType,
			GameSymbols.EconomyLaws.SpendResourceIfAvailable.NameHints,
			typeof(bool),
			new[] { "String", "Int32" });
		_resourceHasAtLeast = ResolveExactMethod(
			_resourceDataType,
			GameSymbols.EconomyLaws.ResourceHasAtLeast.NameHints,
			typeof(bool),
			new[] { "Int32" });
		_resHeapApply = ResolveExactMethod(
			_resHeapDataType,
			GameSymbols.EconomyLaws.ResHeapApply.NameHints,
			typeof(bool),
			new[] { "ResHeap", "Boolean" });
		_rewardSetQueued = ResolveExactMethod(
			_dataRewardSetsType,
			GameSymbols.RewardCommitLaws.RewardSetQueued.NameHints,
			typeof(void),
			new[] { "DataRewardSet" });
		_rewardSetRemoved = ResolveExactMethod(
			_dataRewardSetsType,
			GameSymbols.RewardCommitLaws.RewardSetRemoved.NameHints,
			typeof(void),
			new[] { "DataRewardSet" });
		_rewardSetApply = ResolveExactMethod(
			_rewardApplierType,
			GameSymbols.RewardCommitLaws.RewardSetApply.NameHints,
			typeof(void),
			new[] { "Hero", "DataRewardSet" });

		if (_resourceSetValue == null)
			return FailResolve("resource set method was not found by exact name", out failReason);
		if (_resourceAddValue == null)
			return FailResolve("resource add method was not found by exact name", out failReason);
		if (_resourceSpendIfAvailable == null)
			return FailResolve("resource spend-if-available wrapper method was not found by exact name", out failReason);
		if (_resourceHasAtLeast == null)
			return FailResolve("resource has-at-least method was not found by exact name", out failReason);
		if (_rewardSetQueued == null)
			return FailResolve("reward set queue method was not found by exact name", out failReason);
		if (_rewardSetRemoved == null)
			return FailResolve("reward set remove method was not found by exact name", out failReason);

		failReason = null;
		return true;
	}

	private static bool ValidateResource(object resource, out string failReason)
	{
		if (resource == null)
		{
			failReason = "resource instance is null";
			return false;
		}
		if (!_resourceDataType.IsInstanceOfType(resource))
		{
			failReason = "object is not a resolved Resource instance";
			return false;
		}
		failReason = null;
		return true;
	}

	private static object ReadFirstExactMember(object value, Type type, string[] names)
	{
		if (value == null || type == null || names == null)
			return null;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			for (var i = 0; i < names.Length; i++)
			{
				var name = names[i];
				if (string.IsNullOrWhiteSpace(name))
					continue;
				try
				{
					var field = current.GetField(name, flags);
					if (field != null)
						return field.GetValue(value);
				}
				catch
				{
				}
				try
				{
					var property = current.GetProperty(name, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
						return property.GetValue(value, null);
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static string ReadStringMember(object value, Type type, string[] names)
	{
		return ReadFirstExactMember(value, type, names) as string;
	}

	private static string ReadShortMember(object value, Type type, string[] names)
	{
		var raw = ReadFirstExactMember(value, type, names);
		if (raw == null)
			return null;
		var text = raw.ToString();
		if (string.IsNullOrEmpty(text))
			return null;
		return text.Length <= 80 ? text : text.Substring(0, 80) + "...";
	}

	private static bool TryReadIntMember(object value, Type type, string[] names, out int result)
	{
		result = 0;
		var raw = ReadFirstExactMember(value, type, names);
		if (raw == null)
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

	private static int CountEnumerable(object value, out string summary)
	{
		summary = null;
		if (value is not IEnumerable enumerable || value is string)
			return -1;

		var count = 0;
		var samples = new List<string>(4);
		foreach (var item in enumerable)
		{
			count++;
			if (samples.Count < 4)
				samples.Add(DescribeRewardItem(item));
		}
		summary = string.Join(";", samples);
		return count;
	}

	private static string DescribeRewardItem(object reward)
	{
		if (reward == null)
			return "null";
		var type = reward.GetType();
		var stringType = ReadStringMember(reward, type, GameSymbols.RewardCommitLaws.RewardItemStringTypeMembers);
		var rewardType = ReadShortMember(reward, type, GameSymbols.RewardCommitLaws.RewardItemTypeMembers);
		var name = ReadStringMember(reward, type, GameSymbols.RewardCommitLaws.RewardItemNameMembers);
		var icon = ReadStringMember(reward, type, GameSymbols.RewardCommitLaws.RewardItemIconMembers);
		var parameters = ReadFirstExactMember(reward, type, GameSymbols.RewardCommitLaws.RewardItemParametersMembers);
		return "type=" + (type.FullName ?? type.Name)
		       + ",stringRewardType=" + (stringType ?? "null")
		       + ",rewardType=" + (rewardType ?? "null")
		       + ",name=" + (name ?? "null")
		       + ",icon=" + (icon ?? "null")
		       + ",parameters=" + DescribeCollection(parameters);
	}

	private static string DescribeCollection(object value)
	{
		if (value == null)
			return "null";
		if (value is not IEnumerable enumerable || value is string)
			return value.GetType().FullName ?? value.GetType().Name;
		var count = 0;
		foreach (var _ in enumerable)
			count++;
		return "count=" + count;
	}

	private static bool TypeNameLooksLike(Type type, string expected)
	{
		if (type == null || string.IsNullOrWhiteSpace(expected))
			return false;
		return string.Equals(type.Name, expected, StringComparison.Ordinal)
		       || string.Equals(type.FullName, "Hex.Session.Data." + expected, StringComparison.Ordinal);
	}

	private static bool TryInvokeVoid(MethodInfo method, object instance, object[] args, string operation, out string failReason)
	{
		try
		{
			method.Invoke(instance, args);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = operation + " invoke failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	private static bool TryInvokeBool(MethodInfo method, object instance, object[] args, string operation, out bool result, out string failReason)
	{
		result = false;
		try
		{
			var raw = method.Invoke(instance, args);
			result = Convert.ToBoolean(raw);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = operation + " invoke failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	private static bool FailResolve(string reason, out string failReason)
	{
		_resolveFailure = reason;
		failReason = reason;
		return false;
	}

	private static MethodInfo ResolveExactMethod(Type type, string[] names, Type requiredReturnType, string[] parameterTypeNames)
	{
		if (type == null)
			return null;

		var methods = AccessTools.GetDeclaredMethods(type);
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			foreach (var method in methods)
			{
				if (!string.Equals(method.Name, name, StringComparison.Ordinal))
					continue;
				if (method.IsSpecialName)
					continue;
				if (requiredReturnType != null && method.ReturnType != requiredReturnType)
					continue;
				if (!ParametersMatch(method, parameterTypeNames))
					continue;
				return method;
			}
		}

		return null;
	}

	private static bool ParametersMatch(MethodInfo method, string[] parameterTypeNames)
	{
		var parameters = method.GetParameters();
		parameterTypeNames ??= Array.Empty<string>();
		if (parameters.Length != parameterTypeNames.Length)
			return false;
		for (var i = 0; i < parameters.Length; i++)
		{
			var expected = parameterTypeNames[i];
			if (string.IsNullOrWhiteSpace(expected))
				continue;
			var actual = parameters[i].ParameterType;
			var actualName = actual.Name;
			var actualFullName = actual.FullName ?? actualName;
			var actualObfuscatedName = GameMember.ReadObfuscatedName(actual);
			if (!string.Equals(actualName, expected, StringComparison.Ordinal)
			    && !string.Equals(actualFullName, expected, StringComparison.Ordinal)
			    && !actualFullName.EndsWith("." + expected, StringComparison.Ordinal)
			    && !string.Equals(actualObfuscatedName, expected, StringComparison.Ordinal))
				return false;
		}
		return true;
	}

	private static string DescribeType(Type type)
	{
		return type?.FullName ?? "unresolved";
	}

	private static string DescribeMethod(MethodBase method)
	{
		if (method == null)
			return "unresolved";
		return (method.DeclaringType?.FullName ?? "?") + "." + method.Name;
	}
}
