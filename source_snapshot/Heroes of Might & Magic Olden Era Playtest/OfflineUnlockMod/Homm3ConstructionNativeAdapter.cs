using System;
using System.Reflection;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Exact native adapter for construction state surfaces.
/// Source-prepared from June 18 decomp/live-bridge evidence. This class does
/// not register Harmony hooks or implement construction laws by itself.
/// </summary>
internal static class Homm3ConstructionNativeAdapter
{
	internal readonly struct BuildingIdentityInfo
	{
		internal readonly string Sid;
		internal readonly int Level;
		internal readonly bool IsConstructed;

		internal BuildingIdentityInfo(string sid, int level, bool isConstructed)
		{
			Sid = sid;
			Level = level;
			IsConstructed = isConstructed;
		}

		public override string ToString()
		{
			return "sid=" + (Sid ?? "null")
			       + " level=" + Level
			       + " isConstructed=" + IsConstructed;
		}
	}

	private static Type _buildingDataType;
	private static Type _buildingsDataType;
	private static Type _objCityType;
	private static Type _cityLogicType;
	private static Type _buildingsManagerType;
	private static Type _buildingSessionType;
	private static Type _buildingViewType;
	private static MethodInfo _constructStateMutation;
	private static MethodInfo _buildingSessionCostCandidate;
	private static MethodInfo _buildingSessionSelectCandidate;
	private static MethodInfo _buildingViewCostCheckCandidate;
	private static MethodInfo _buildingViewBindCandidate;
	private static MethodInfo _buildingViewUpdateCandidate;
	private static FieldInfo _todaysConstructionsCountField;
	private static bool _resolved;
	private static string _resolveFailure;

	internal static bool TrySetConstructedState(object buildingData, int level, bool isConstructed, out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (buildingData == null)
		{
			failReason = "building data instance is null";
			return false;
		}
		if (_constructStateMutation == null)
		{
			failReason = "building construct state mutation method is unresolved";
			return false;
		}
		if (!_buildingDataType.IsInstanceOfType(buildingData))
		{
			failReason = "object is not a resolved BuildingData instance";
			return false;
		}

		try
		{
			_constructStateMutation.Invoke(buildingData, new object[] { level, isConstructed });
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "construct state mutation invoke failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryRequireAnyBuildingSid(
		object buildingData,
		string[] requiredSids,
		out BuildingIdentityInfo info,
		out string failReason)
	{
		info = default;
		if (requiredSids == null || requiredSids.Length == 0)
		{
			failReason = "required building SID list is empty";
			return false;
		}

		string firstFailure = null;
		for (var i = 0; i < requiredSids.Length; i++)
		{
			if (TryRequireBuildingSid(buildingData, requiredSids[i], out info, out failReason))
				return true;
			firstFailure ??= failReason;
		}

		failReason = firstFailure ?? "no required building SID matched";
		return false;
	}

	internal static bool TryRequireBuildingSid(
		object buildingData,
		string requiredSid,
		out BuildingIdentityInfo info,
		out string failReason)
	{
		if (!TryReadBuildingIdentity(buildingData, out info, out failReason))
			return false;
		if (string.IsNullOrWhiteSpace(requiredSid))
		{
			failReason = "required building SID is empty";
			return false;
		}
		if (string.Equals(info.Sid, requiredSid, StringComparison.Ordinal))
			return true;
		failReason = "building SID mismatch: expected " + requiredSid + " actual " + (info.Sid ?? "null");
		return false;
	}

	internal static bool TryReadBuildingIdentity(object buildingData, out BuildingIdentityInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (buildingData == null)
		{
			failReason = "building data instance is null";
			return false;
		}
		if (!_buildingDataType.IsInstanceOfType(buildingData))
		{
			failReason = "object is not a resolved BuildingData instance";
			return false;
		}

		var type = buildingData.GetType();
		var sid = ReadStringMember(
			buildingData,
			type,
			GameSymbols.ReleaseTownUi.BuildingDataSidMembers,
			GameSymbols.ReleaseTownUi.BuildingDataSidAccessorMethods);
		if (string.IsNullOrWhiteSpace(sid))
		{
			failReason = "building SID was not resolved from exact BuildingData members";
			return false;
		}

		if (!TryReadIntMember(
			    buildingData,
			    type,
			    GameSymbols.ReleaseTownUi.BuildingDataLevelMembers,
			    GameSymbols.ReleaseTownUi.BuildingDataLevelAccessorMethods,
			    out var level))
		{
			failReason = "building level was not resolved from exact BuildingData members";
			return false;
		}

		if (!TryReadBoolMember(
			    buildingData,
			    type,
			    GameSymbols.ReleaseTownUi.BuildingDataConstructedMembers,
			    GameSymbols.ReleaseTownUi.BuildingDataConstructedAccessorMethods,
			    out var isConstructed))
		{
			failReason = "building constructed state was not resolved from exact BuildingData members";
			return false;
		}

		info = new BuildingIdentityInfo(sid, level, isConstructed);
		failReason = null;
		return true;
	}

	internal static bool TryResolveBuildingsDataFromCityContext(object cityContext, out object buildingsData, out string failReason)
	{
		buildingsData = null;
		if (!TryResolve(out failReason))
			return false;
		if (cityContext == null)
		{
			failReason = "city context instance is null";
			return false;
		}

		if (_buildingsDataType.IsInstanceOfType(cityContext))
		{
			buildingsData = cityContext;
			failReason = null;
			return true;
		}

		object objCity = null;
		if (_objCityType != null && _objCityType.IsInstanceOfType(cityContext))
		{
			objCity = cityContext;
		}
		else if (_cityLogicType != null && _cityLogicType.IsInstanceOfType(cityContext))
		{
			objCity = ReadFirstExactMember(
				cityContext,
				cityContext.GetType(),
				GameSymbols.ConstructionCommitLaws.CityLogicObjCityMembers,
				GameSymbols.ConstructionCommitLaws.CityLogicObjCityAccessorMethods);
		}

		if (objCity == null || !_objCityType.IsInstanceOfType(objCity))
		{
			failReason = "city context did not expose exact ObjCity";
			return false;
		}

		buildingsData = ReadFirstExactMember(
			objCity,
			objCity.GetType(),
			GameSymbols.ConstructionCommitLaws.ObjCityBuildingsMembers,
			Array.Empty<string>());
		if (buildingsData == null)
		{
			failReason = "ObjCity did not expose exact BuildingsData";
			return false;
		}
		if (!_buildingsDataType.IsInstanceOfType(buildingsData))
		{
			failReason = "ObjCity buildings member is not a resolved BuildingsData instance";
			return false;
		}

		failReason = null;
		return true;
	}

	internal static bool TryResolveConstructionLawOwnerFromCityContext(object cityContext, out object lawOwner, out string failReason)
	{
		lawOwner = null;
		if (!TryResolve(out failReason))
			return false;
		if (cityContext == null)
		{
			failReason = "city context instance is null";
			return false;
		}

		var objCity = ResolveObjCityFromCityContext(cityContext);
		if (objCity == null)
		{
			failReason = "city context did not expose exact ObjCity";
			return false;
		}
		if (!TryReadIntMember(
			    objCity,
			    objCity.GetType(),
			    GameSymbols.ConstructionCommitLaws.ObjCityOwnerSideMembers,
			    Array.Empty<string>(),
			    out var ownerSide))
		{
			failReason = "ObjCity did not expose exact owner side";
			return false;
		}
		if (ownerSide < 0)
		{
			failReason = "ObjCity owner side is neutral or invalid";
			return false;
		}
		if (!TryResolveDataRootFromCityContext(cityContext, out var dataRoot, out failReason))
			return false;
		if (!TryResolveDataSideFromDataRoot(dataRoot, ownerSide, out lawOwner, out failReason))
			return false;
		if (!Homm3CustomLawHandlerRegistry.TryProbeHandler(
			    lawOwner,
			    "construction.commit",
			    Homm3CustomFactionLawRuntime.ExtraConstructionIndex,
			    out _,
			    out failReason))
		{
			return false;
		}

		failReason = null;
		return true;
	}

	internal static bool TryReadTodaysConstructionCount(object buildingsData, out int count, out string failReason)
	{
		count = 0;
		if (!TryResolve(out failReason))
			return false;
		if (buildingsData == null)
		{
			failReason = "buildings data instance is null";
			return false;
		}
		if (_todaysConstructionsCountField == null)
		{
			failReason = "todays constructions count field is unresolved";
			return false;
		}
		if (!_buildingsDataType.IsInstanceOfType(buildingsData))
		{
			failReason = "object is not a resolved BuildingsData instance";
			return false;
		}

		try
		{
			count = Convert.ToInt32(_todaysConstructionsCountField.GetValue(buildingsData), System.Globalization.CultureInfo.InvariantCulture);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "todays constructions count read failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TrySetTodaysConstructionCount(object buildingsData, int count, out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (buildingsData == null)
		{
			failReason = "buildings data instance is null";
			return false;
		}
		if (_todaysConstructionsCountField == null)
		{
			failReason = "todays constructions count field is unresolved";
			return false;
		}
		if (!_buildingsDataType.IsInstanceOfType(buildingsData))
		{
			failReason = "object is not a resolved BuildingsData instance";
			return false;
		}

		try
		{
			_todaysConstructionsCountField.SetValue(buildingsData, Math.Max(0, count));
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "todays constructions count write failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryDescribeUiObservationSurfaces(out string description, out string failReason)
	{
		description = null;
		if (!TryResolve(out failReason))
			return false;

		description =
			"managerType=" + DescribeType(_buildingsManagerType)
			+ " sessionType=" + DescribeType(_buildingSessionType)
			+ " viewType=" + DescribeType(_buildingViewType)
			+ " sessionCost=" + DescribeMethod(_buildingSessionCostCandidate)
			+ " sessionSelect=" + DescribeMethod(_buildingSessionSelectCandidate)
			+ " viewBind=" + DescribeMethod(_buildingViewBindCandidate)
			+ " viewUpdate=" + DescribeMethod(_buildingViewUpdateCandidate)
			+ " viewCostCheck=" + DescribeMethod(_buildingViewCostCheckCandidate);
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
		_buildingDataType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionCommitLawsBuildingData);
		_buildingsDataType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionCommitLawsBuildingsData);
		_objCityType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionCommitLawsObjCity);
		_cityLogicType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionCommitLawsCityLogic);
		_buildingsManagerType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionLawsBuildingsManager);
		_buildingSessionType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionLawsBuildingSession);
		_buildingViewType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.ConstructionLawsBuildingView);

		if (_buildingDataType == null)
			return FailResolve("BuildingData type was not found", out failReason);
		if (_buildingsDataType == null)
			return FailResolve("BuildingsData type was not found", out failReason);
		if (_objCityType == null)
			return FailResolve("ObjCity type was not found", out failReason);
		if (_cityLogicType == null)
			return FailResolve("city logic type fbs was not found", out failReason);

		_constructStateMutation = ResolveExactMethod(
			_buildingDataType,
			GameSymbols.ConstructionCommitLaws.BuildingConstructStateMutation.NameHints,
			typeof(void),
			new[] { "Int32", "Boolean" });
		_buildingSessionCostCandidate = ResolveExactMethod(
			_buildingSessionType,
			GameSymbols.ConstructionLaws.BuildingSessionCostCandidate.NameHints,
			typeof(int),
			new[] { "Int32", "Int32" });
		_buildingSessionSelectCandidate = ResolveExactMethod(
			_buildingSessionType,
			GameSymbols.ConstructionLaws.BuildingSessionSelectCandidate.NameHints,
			typeof(void),
			new[] { "bfh" });
		_buildingViewBindCandidate = ResolveExactMethod(
			_buildingViewType,
			GameSymbols.ConstructionLaws.BuildingViewBindCandidate.NameHints,
			typeof(void),
			new[] { "fbs", "dwc", "Int32" });
		_buildingViewUpdateCandidate = ResolveExactMethod(
			_buildingViewType,
			GameSymbols.ConstructionLaws.BuildingViewUpdateCandidate.NameHints,
			typeof(void),
			Array.Empty<string>());
		_buildingViewCostCheckCandidate = ResolveExactMethod(
			_buildingViewType,
			GameSymbols.ConstructionLaws.BuildingViewCostCheckCandidate.NameHints,
			typeof(bool),
			new[] { "ResNameAndCost[]" });
		_todaysConstructionsCountField = ResolveExactField(
			_buildingsDataType,
			GameSymbols.ConstructionCommitLaws.TodaysConstructionsCountFields,
			typeof(int));

		if (_constructStateMutation == null)
			return FailResolve("BuildingData construct state mutation method was not found by exact name", out failReason);
		if (_todaysConstructionsCountField == null)
			return FailResolve("BuildingsData todaysConstructionsCount field was not found by exact name", out failReason);

		failReason = null;
		return true;
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

	private static FieldInfo ResolveExactField(Type type, string[] names, Type requiredFieldType)
	{
		if (type == null)
			return null;

		const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
		foreach (var name in names ?? Array.Empty<string>())
		{
			if (string.IsNullOrWhiteSpace(name))
				continue;
			var field = type.GetField(name, flags);
			if (field == null)
				continue;
			if (requiredFieldType != null && field.FieldType != requiredFieldType)
				continue;
			return field;
		}

		return null;
	}

	private static string ReadStringMember(object value, Type type, string[] fields, string[] methods)
	{
		var raw = ReadFirstExactMember(value, type, fields, methods);
		return raw as string;
	}

	private static bool TryReadIntMember(object value, Type type, string[] fields, string[] methods, out int result)
	{
		result = 0;
		var raw = ReadFirstExactMember(value, type, fields, methods);
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

	private static bool TryReadBoolMember(object value, Type type, string[] fields, string[] methods, out bool result)
	{
		result = false;
		var raw = ReadFirstExactMember(value, type, fields, methods);
		if (raw is bool b)
		{
			result = b;
			return true;
		}
		return false;
	}

	private static object ReadFirstExactMember(object value, Type type, string[] fields, string[] methods)
	{
		if (value == null || type == null)
			return null;
		for (var current = type; current != null && current != typeof(object); current = current.BaseType)
		{
			const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
			foreach (var fieldName in fields ?? Array.Empty<string>())
			{
				if (string.IsNullOrWhiteSpace(fieldName))
					continue;
				try
				{
					var field = current.GetField(fieldName, flags);
					if (field != null)
						return field.GetValue(value);
				}
				catch
				{
				}
				try
				{
					var property = current.GetProperty(fieldName, flags);
					if (property != null && property.GetIndexParameters().Length == 0)
						return property.GetValue(value, null);
				}
				catch
				{
				}
			}
			foreach (var methodName in methods ?? Array.Empty<string>())
			{
				if (string.IsNullOrWhiteSpace(methodName))
					continue;
				try
				{
					var method = current.GetMethod(methodName, flags, null, Type.EmptyTypes, null);
					if (method != null && method.ReturnType != typeof(void) && !method.ContainsGenericParameters)
						return method.Invoke(value, null);
				}
				catch
				{
				}
			}
		}
		return null;
	}

	private static object ResolveObjCityFromCityContext(object cityContext)
	{
		if (cityContext == null || _objCityType == null)
			return null;
		if (_objCityType.IsInstanceOfType(cityContext))
			return cityContext;
		if (_cityLogicType != null && _cityLogicType.IsInstanceOfType(cityContext))
		{
			var objCity = ReadFirstExactMember(
				cityContext,
				cityContext.GetType(),
				GameSymbols.ConstructionCommitLaws.CityLogicObjCityMembers,
				GameSymbols.ConstructionCommitLaws.CityLogicObjCityAccessorMethods);
			if (objCity != null && _objCityType.IsInstanceOfType(objCity))
				return objCity;
		}
		return null;
	}

	private static bool TryResolveDataRootFromCityContext(object cityContext, out object dataRoot, out string failReason)
	{
		dataRoot = null;
		if (_cityLogicType == null || !_cityLogicType.IsInstanceOfType(cityContext))
		{
			failReason = "city context is not exact city logic and cannot expose session data root";
			return false;
		}

		var session = ReadFirstExactMember(
			cityContext,
			cityContext.GetType(),
			GameSymbols.ConstructionCommitLaws.CityLogicSessionMembers,
			Array.Empty<string>());
		if (session == null)
		{
			failReason = "city logic did not expose exact session owner";
			return false;
		}

		dataRoot = ReadFirstExactMember(
			session,
			session.GetType(),
			GameSymbols.ConstructionCommitLaws.SessionDataMembers,
			Array.Empty<string>());
		if (dataRoot == null)
		{
			failReason = "city session did not expose exact Data root";
			return false;
		}
		failReason = null;
		return true;
	}

	private static bool TryResolveDataSideFromDataRoot(object dataRoot, int ownerSide, out object lawOwner, out string failReason)
	{
		lawOwner = null;
		var dataSides = ReadFirstExactMember(
			dataRoot,
			dataRoot?.GetType(),
			GameSymbols.CustomFactionLawRuntime.DataRootSidesMembers,
			Array.Empty<string>());
		if (dataSides == null)
		{
			failReason = "Data root did not expose exact sides container";
			return false;
		}
		var sidesArray = ReadFirstExactMember(
			dataSides,
			dataSides.GetType(),
			GameSymbols.CustomFactionLawRuntime.DataSidesArrayMembers,
			Array.Empty<string>());
		if (sidesArray is not System.Collections.IEnumerable enumerable)
		{
			failReason = "DataSides did not expose exact side array";
			return false;
		}
		foreach (var candidate in enumerable)
		{
			if (candidate == null)
				continue;
			if (!TryReadIntMember(
				    candidate,
				    candidate.GetType(),
				    GameSymbols.CustomFactionLawRuntime.DataSideIndexMembers,
				    Array.Empty<string>(),
				    out var candidateIndex))
				continue;
			if (candidateIndex != ownerSide)
				continue;
			lawOwner = candidate;
			failReason = null;
			return true;
		}
		failReason = "Data root did not contain a side matching ObjCity.ownerSide";
		return false;
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
