using System;
using System.Reflection;
using UnityEngine;

namespace OfflineUnlockMod;

/// <summary>
/// Builds the battle-pool loader's third out value (live <c>bep</c>, the drawer renderer/material set)
/// for a synthesized battle instance. Mirrors vanilla <c>eat+ear.bbmc</c>: <c>new bep(go, false, null)</c>;
/// the string arg is a comma-separated renderer-name set, which vanilla leaves null.
/// Returns null (with an error log) when the resolved type has no <c>(GameObject, bool, string)</c> ctor
/// or the ctor throws; callers must fail the load rather than hand native a null renderer set.
/// </summary>
internal static class Homm3BattlePoolMetadataFactory
{
	internal static object Create(GameObject instance, bool flag, string path)
	{
		if (instance == null)
			return null;
		var type = Homm3BattlePoolInterop.MetadataType;
		if (type == null)
		{
			Plugin.LogSource?.LogError("Homm3Import battle pool metadata: type unresolved for '" + path + "'.");
			return null;
		}

		ConstructorInfo match = null;
		foreach (var ctor in type.GetConstructors(BindingFlags.Public | BindingFlags.Instance))
		{
			var parameters = ctor.GetParameters();
			if (parameters.Length == 3
			    && GameInteropTypes.TypesMatch(parameters[0].ParameterType, typeof(GameObject))
			    && parameters[1].ParameterType == typeof(bool)
			    && parameters[2].ParameterType == typeof(string))
			{
				match = ctor;
				break;
			}
		}
		if (match == null)
		{
			Plugin.LogSource?.LogError(
				"Homm3Import battle pool metadata: " + type.FullName
				+ " has no (GameObject, bool, string) constructor; cannot build renderer set for '" + path + "'.");
			return null;
		}

		try
		{
			return match.Invoke(new object[] { instance, flag, null });
		}
		catch (Exception ex)
		{
			Plugin.LogSource?.LogError(
				"Homm3Import battle pool metadata: " + type.FullName + " ctor threw for '" + path + "': "
				+ (ex.InnerException ?? ex));
			return null;
		}
	}
}
