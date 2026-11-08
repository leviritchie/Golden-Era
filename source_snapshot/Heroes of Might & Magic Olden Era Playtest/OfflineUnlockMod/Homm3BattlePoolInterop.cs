using System;
using System.Reflection;
using Hex.Configs;

namespace OfflineUnlockMod;

internal static class Homm3BattlePoolInterop
{
	private static Type _metadataType;
	private static Type _poolOwnerType;

	internal static Type MetadataType => _metadataType ?? (_metadataType = ResolveMetadataType());

	internal static Type ResolveMetadataType()
	{
		var asm = typeof(ObjCityConfig).Assembly;
		foreach (var hint in GameSymbols.ImportVisuals.BattlePoolMetadataTypeHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = asm.GetType(hint, throwOnError: false);
			if (type != null)
				return type;
			type = GameMember.FindType("importVisuals.battlePool.metadata." + hint, hint);
			if (type != null)
				return type;
		}
		return null;
	}

	internal static Type ResolvePoolOwnerType()
	{
		if (_poolOwnerType != null)
			return _poolOwnerType;
		var asm = typeof(ObjCityConfig).Assembly;
		foreach (var hint in GameSymbols.ImportVisuals.BattlePoolTypeHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			var type = asm.GetType(hint, throwOnError: false);
			if (type != null)
			{
				_poolOwnerType = type;
				return type;
			}
			type = GameMember.FindType("importVisuals.battlePool.owner." + hint, hint);
			if (type != null)
			{
				_poolOwnerType = type;
				return type;
			}
		}
		return null;
	}

	internal static bool IsMetadataType(Type type)
	{
		var metadata = MetadataType;
		if (type == null || metadata == null)
			return false;
		return type == metadata || GameInteropTypes.TypesMatch(type, metadata);
	}

	internal static bool IsMetadataOutParameter(ParameterInfo parameter)
	{
		if (parameter == null || !parameter.ParameterType.IsByRef)
			return false;
		return IsMetadataType(parameter.ParameterType.GetElementType());
	}

	internal static bool MethodMatchesLoaderHints(MethodInfo method)
	{
		if (method == null)
			return false;
		foreach (var hint in GameSymbols.ImportVisuals.BattlePoolLoader.NameHints)
		{
			if (string.IsNullOrWhiteSpace(hint))
				continue;
			if (string.Equals(method.Name, hint, StringComparison.Ordinal))
				return true;
			if (string.Equals(GameMember.ReadObfuscatedName(method), hint, StringComparison.Ordinal))
				return true;
		}
		return false;
	}
}
