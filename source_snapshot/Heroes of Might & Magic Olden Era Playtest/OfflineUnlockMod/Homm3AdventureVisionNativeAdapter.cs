using System;
using System.Reflection;
using HarmonyLib;

namespace OfflineUnlockMod;

/// <summary>
/// Exact native adapter for adventure vision/scouting surfaces.
/// Source-prepared from June 18 decomp/live-bridge evidence. This adapter does
/// not mutate fog tiles; only object scouting and map-magic registry operations
/// are exposed for future handlers after packet proof is promoted.
/// </summary>
internal static class Homm3AdventureVisionNativeAdapter
{
	internal readonly struct DataObjectIdentityInfo
	{
		internal readonly int ObjectId;
		internal readonly string ConfigSid;
		internal readonly int OwnerSide;

		internal DataObjectIdentityInfo(int objectId, string configSid, int ownerSide)
		{
			ObjectId = objectId;
			ConfigSid = configSid;
			OwnerSide = ownerSide;
		}

		public override string ToString()
		{
			return "objectId=" + ObjectId
			       + " configSid=" + (ConfigSid ?? "null")
			       + " ownerSide=" + OwnerSide;
		}
	}

	private static Type _dataObjectType;
	private static Type _dataFogOfWarType;
	private static Type _mapMagicsType;
	private static MethodInfo _objectScoutedBySide;
	private static MethodInfo _fogInitialize;
	private static MethodInfo _fogVisibilityRead;
	private static MethodInfo _fogCountCandidate;
	private static MethodInfo _mapMagicAdd;
	private static MethodInfo _mapMagicLookup;
	private static bool _resolved;
	private static string _resolveFailure;

	internal static bool TryMarkObjectScoutedBySide(object dataObject, int side, out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (dataObject == null)
		{
			failReason = "data object instance is null";
			return false;
		}
		if (!_dataObjectType.IsInstanceOfType(dataObject))
		{
			failReason = "object is not a resolved DataObject instance";
			return false;
		}
		if (_objectScoutedBySide == null)
		{
			failReason = "object scouted-by-side method is unresolved";
			return false;
		}

		try
		{
			_objectScoutedBySide.Invoke(dataObject, new object[] { side });
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "object scouted-by-side invoke failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryRequireDataObjectConfigSid(
		object dataObject,
		string requiredConfigSid,
		out DataObjectIdentityInfo info,
		out string failReason)
	{
		if (!TryReadDataObjectIdentity(dataObject, out info, out failReason))
			return false;
		if (string.IsNullOrWhiteSpace(requiredConfigSid))
		{
			failReason = "required data object config SID is empty";
			return false;
		}
		if (string.Equals(info.ConfigSid, requiredConfigSid, StringComparison.Ordinal))
			return true;
		failReason = "data object config SID mismatch: expected " + requiredConfigSid + " actual " + (info.ConfigSid ?? "null");
		return false;
	}

	internal static bool TryRequireAnyDataObjectConfigSid(
		object dataObject,
		string[] requiredConfigSids,
		out DataObjectIdentityInfo info,
		out string failReason)
	{
		info = default;
		if (requiredConfigSids == null || requiredConfigSids.Length == 0)
		{
			failReason = "required data object config SID list is empty";
			return false;
		}

		string firstFailure = null;
		for (var i = 0; i < requiredConfigSids.Length; i++)
		{
			if (TryRequireDataObjectConfigSid(dataObject, requiredConfigSids[i], out info, out failReason))
				return true;
			firstFailure ??= failReason;
		}

		failReason = firstFailure ?? "no required data object config SID matched";
		return false;
	}

	internal static bool TryReadDataObjectIdentity(object dataObject, out DataObjectIdentityInfo info, out string failReason)
	{
		info = default;
		if (!TryResolve(out failReason))
			return false;
		if (dataObject == null)
		{
			failReason = "data object instance is null";
			return false;
		}
		if (!_dataObjectType.IsInstanceOfType(dataObject))
		{
			failReason = "object is not a resolved DataObject instance";
			return false;
		}

		var type = dataObject.GetType();
		if (!TryReadIntMember(dataObject, type, GameSymbols.AdventureObjectScoutingLaws.DataObjectIdMembers, out var objectId))
		{
			failReason = "data object id was not resolved from exact members";
			return false;
		}
		var configSid = ReadStringMember(dataObject, type, GameSymbols.AdventureObjectScoutingLaws.DataObjectConfigSidMembers);
		if (string.IsNullOrWhiteSpace(configSid))
		{
			failReason = "data object config SID was not resolved from exact members";
			return false;
		}
		if (!TryReadIntMember(dataObject, type, GameSymbols.AdventureObjectScoutingLaws.DataObjectOwnerSideMembers, out var ownerSide))
		{
			failReason = "data object owner side was not resolved from exact members";
			return false;
		}

		info = new DataObjectIdentityInfo(objectId, configSid, ownerSide);
		failReason = null;
		return true;
	}

	internal static bool TryReadFogVisibility(object fogOfWar, int index, out bool visible, out string failReason)
	{
		visible = false;
		if (!TryResolve(out failReason))
			return false;
		if (fogOfWar == null)
		{
			failReason = "fog-of-war instance is null";
			return false;
		}
		if (!_dataFogOfWarType.IsInstanceOfType(fogOfWar))
		{
			failReason = "object is not a resolved DataFogOfWar instance";
			return false;
		}
		if (_fogVisibilityRead == null)
		{
			failReason = "fog visibility read method is unresolved";
			return false;
		}

		try
		{
			visible = Convert.ToBoolean(_fogVisibilityRead.Invoke(fogOfWar, new object[] { index }));
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "fog visibility read failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryReadFogCount(object fogOfWar, out int count, out string failReason)
	{
		count = 0;
		if (!TryResolve(out failReason))
			return false;
		if (fogOfWar == null)
		{
			failReason = "fog-of-war instance is null";
			return false;
		}
		if (!_dataFogOfWarType.IsInstanceOfType(fogOfWar))
		{
			failReason = "object is not a resolved DataFogOfWar instance";
			return false;
		}
		if (_fogCountCandidate == null)
		{
			failReason = "fog count method is unresolved";
			return false;
		}

		try
		{
			count = Convert.ToInt32(_fogCountCandidate.Invoke(fogOfWar, Array.Empty<object>()), System.Globalization.CultureInfo.InvariantCulture);
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "fog count read failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryAddMapMagic(object mapMagics, string magicSid, out string failReason)
	{
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateMapMagics(mapMagics, out failReason))
			return false;
		if (string.IsNullOrWhiteSpace(magicSid))
		{
			failReason = "map magic SID is empty";
			return false;
		}
		if (_mapMagicAdd == null)
		{
			failReason = "map magic add method is unresolved";
			return false;
		}

		try
		{
			_mapMagicAdd.Invoke(mapMagics, new object[] { magicSid });
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "map magic add failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryLookupMapMagic(object mapMagics, string magicSid, out object mapMagic, out string failReason)
	{
		mapMagic = null;
		if (!TryResolve(out failReason))
			return false;
		if (!ValidateMapMagics(mapMagics, out failReason))
			return false;
		if (string.IsNullOrWhiteSpace(magicSid))
		{
			failReason = "map magic SID is empty";
			return false;
		}
		if (_mapMagicLookup == null)
		{
			failReason = "map magic lookup method is unresolved";
			return false;
		}

		try
		{
			mapMagic = _mapMagicLookup.Invoke(mapMagics, new object[] { magicSid });
			failReason = null;
			return true;
		}
		catch (Exception ex)
		{
			failReason = "map magic lookup failed: " + ex.GetBaseException().Message;
			return false;
		}
	}

	internal static bool TryDescribeVisionSurfaces(out string description, out string failReason)
	{
		description = null;
		if (!TryResolve(out failReason))
			return false;

		description =
			"dataObjectType=" + DescribeType(_dataObjectType)
			+ " scoutedBySide=" + DescribeMethod(_objectScoutedBySide)
			+ " fogType=" + DescribeType(_dataFogOfWarType)
			+ " fogInitialize=" + DescribeMethod(_fogInitialize)
			+ " fogVisibilityRead=" + DescribeMethod(_fogVisibilityRead)
			+ " fogCount=" + DescribeMethod(_fogCountCandidate)
			+ " mapMagicsType=" + DescribeType(_mapMagicsType)
			+ " mapMagicAdd=" + DescribeMethod(_mapMagicAdd)
			+ " mapMagicLookup=" + DescribeMethod(_mapMagicLookup);
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
		_dataObjectType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.AdventureObjectScoutingLawsDataObject);
		_dataFogOfWarType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.AdventureVisionLawsDataFogOfWar);
		_mapMagicsType = GameMember.ResolveTypeGroup(GameSymbols.TypeGroups.AdventureVisionLawsMapMagics);

		if (_dataObjectType == null)
			return FailResolve("DataObject type was not found", out failReason);
		if (_dataFogOfWarType == null)
			return FailResolve("DataFogOfWar type was not found", out failReason);
		if (_mapMagicsType == null)
			return FailResolve("MapMagics type was not found", out failReason);

		_objectScoutedBySide = ResolveExactMethod(
			_dataObjectType,
			GameSymbols.AdventureObjectScoutingLaws.ObjectScoutedBySide.NameHints,
			typeof(void),
			new[] { "Int32" });
		_fogInitialize = ResolveExactMethod(
			_dataFogOfWarType,
			GameSymbols.AdventureVisionLaws.FogInitialize.NameHints,
			typeof(void),
			new[] { "Int32", "Int32" });
		_fogVisibilityRead = ResolveExactMethod(
			_dataFogOfWarType,
			GameSymbols.AdventureVisionLaws.FogVisibilityRead.NameHints,
			typeof(bool),
			new[] { "Int32" });
		_fogCountCandidate = ResolveExactMethod(
			_dataFogOfWarType,
			GameSymbols.AdventureVisionLaws.FogCountCandidate.NameHints,
			typeof(int),
			Array.Empty<string>());
		_mapMagicAdd = ResolveExactMethod(
			_mapMagicsType,
			GameSymbols.AdventureVisionLaws.MapMagicAdd.NameHints,
			typeof(void),
			new[] { "String" });
		_mapMagicLookup = ResolveExactMethod(
			_mapMagicsType,
			GameSymbols.AdventureVisionLaws.MapMagicLookup.NameHints,
			null,
			new[] { "String" });

		if (_objectScoutedBySide == null)
			return FailResolve("DataObject scouted-by-side method was not found by exact name", out failReason);
		if (_fogInitialize == null)
			return FailResolve("fog initialize method was not found by exact name", out failReason);
		if (_fogVisibilityRead == null)
			return FailResolve("fog visibility read method was not found by exact name", out failReason);
		if (_fogCountCandidate == null)
			return FailResolve("fog count method was not found by exact name", out failReason);
		if (_mapMagicAdd == null)
			return FailResolve("map magic add method was not found by exact name", out failReason);
		if (_mapMagicLookup == null)
			return FailResolve("map magic lookup method was not found by exact name", out failReason);

		failReason = null;
		return true;
	}

	private static bool ValidateMapMagics(object mapMagics, out string failReason)
	{
		if (mapMagics == null)
		{
			failReason = "map magics instance is null";
			return false;
		}
		if (!_mapMagicsType.IsInstanceOfType(mapMagics))
		{
			failReason = "object is not a resolved MapMagics instance";
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
